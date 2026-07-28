"""StockBadieService — orchestrates the automated stock/alcance report.

Pipeline: latest stock snapshot (get_ultima_fecha_stock) + current-month
sales (get_venta_mes) -> build_universe -> pivot_wide -> compute_dias_venta
-> build_workbook -> save to disk. See ``docs/superpowers/specs/
2026-07-21-stock-badie-design.md`` for the full design.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.core.data_loader import DataLoader
from src.services.base_service import BaseService
from src.services.stock_badie.config import StockBadieConfig
from src.services.stock_badie.processor import build_universe, compute_dias_venta, pivot_wide
from src.services.stock_badie.workbook import build_workbook

logger = logging.getLogger(__name__)


@dataclass
class StockBadieResult:
    """Result of stock-badie report generation."""

    archivo_generado: Path
    fecha_stock: date
    dias_venta: int
    n_articulos: int


class StockBadieService(BaseService):
    """Generates the automated stock/alcance report (STOCK sheet)."""

    SERVICE_SLUG = "stock-badie"
    GRANULARITY = "month"

    def _create_data_loader(self, db_name: str | None = None) -> DataLoader:
        """Create/reuse a DataLoader.

        A ``db_name`` override always creates a fresh DataLoader targeting
        that database. Otherwise the constructor-injected loader (see
        ``BaseService.__init__``) is reused when present — required so
        tests can inject a mock via ``StockBadieService(data_loader=mock)``
        and have it actually exercised by ``generar_reporte``.
        """
        if db_name:
            return DataLoader(db_name=db_name)
        if self._data_loader is not None:
            return self._data_loader
        return DataLoader()

    def generar_reporte(self, config: StockBadieConfig) -> StockBadieResult:
        """Build the STOCK sheet workbook and save it to disk.

        Raises:
            ValueError: If gold.fact_stock has no rows at all (no snapshot
                date available) — never builds a bogus empty report.
        """
        data_loader = self._create_data_loader(config.db_name)

        fecha_stock = data_loader.get_ultima_fecha_stock()
        if fecha_stock is None:
            raise ValueError(
                "No hay snapshot de stock disponible en gold.fact_stock "
                "(get_ultima_fecha_stock() devolvio None)"
            )
        fecha_stock_str = fecha_stock.strftime("%Y-%m-%d")

        stock_df = data_loader.get_stock_diario(fecha_stock_str, config.genericos)
        venta_df = data_loader.get_venta_mes(
            fecha_desde=config.fecha_desde, fecha_hasta=config.fecha_hasta
        )

        universe = build_universe(
            stock_df, venta_df, genericos_excluidos=config.genericos_excluidos
        )
        wide = pivot_wide(universe)

        if len(wide) == 0:
            logger.warning(
                "Stock Badie: universo vacio para %s..%s (genericos=%s) — "
                "el reporte saldra sin filas de articulo.",
                config.fecha_desde, config.fecha_hasta, config.genericos,
            )

        # DiasVenta must reflect business days elapsed WITHIN the reporting
        # period, not the wall-clock month. Clamp the reference date into
        # [fecha_desde, ultimo_dia_periodo] so a past-month re-run (or a cron
        # that slips past midnight on the 1st) computes DiasVenta for the
        # reported month, never today's month. fecha_hasta is exclusive (1st
        # of the next month), so the period's last day is fecha_hasta - 1.
        primer_dia = datetime.strptime(config.fecha_desde, "%Y-%m-%d").date()
        ultimo_dia = datetime.strptime(config.fecha_hasta, "%Y-%m-%d").date() - timedelta(days=1)
        if config.fecha_referencia:
            ref = datetime.strptime(config.fecha_referencia, "%Y-%m-%d").date()
        else:
            ref = date.today()
        ref = max(primer_dia, min(ref, ultimo_dia))
        dias_venta = compute_dias_venta(ref)

        # `ref` is the effective last day the sales cover (clamped into the
        # period), so it — not `ultimo_dia` — is what the sheet should show.
        wb = build_workbook(
            wide,
            dias_venta,
            config.dias_stock,
            fecha_stock=fecha_stock,
            periodo_desde=primer_dia,
            periodo_hasta=ref,
        )

        out_dir = self._output_dir(config.fecha_desde)
        out_dir.mkdir(parents=True, exist_ok=True)

        periodo = config.fecha_desde[:7]
        nombre = config.nombre_archivo or f"Stock Badie - {periodo}.xlsx"
        if not nombre.lower().endswith(".xlsx"):
            nombre += ".xlsx"
        ruta = out_dir / nombre
        wb.save(ruta)

        logger.info(
            "Stock Badie generado: %s (%d articulos, DiasVenta=%d)",
            ruta.name, len(wide), dias_venta,
        )

        return StockBadieResult(
            archivo_generado=ruta,
            fecha_stock=fecha_stock,
            dias_venta=dias_venta,
            n_articulos=len(wide),
        )
