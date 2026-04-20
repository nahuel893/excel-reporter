"""VentasArticuloService — daily sales report for a single article x sucursal."""

import calendar
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.core.data_loader import DataLoader
from src.services.base_service import BaseService
from src.services.ventas_articulo.processor import MESES_COMPLETOS, build_excel

logger = logging.getLogger(__name__)


@dataclass
class VentasArticuloConfig:
    """Configuration for ventas-articulo-diario report."""

    fecha_desde: str
    fecha_hasta: str
    id_articulo: int | None = None
    id_sucursal: int | None = None
    nombre_archivo: str | None = None
    output_dir: Path | None = None


@dataclass
class VentasArticuloResult:
    """Result of ventas-articulo-diario report generation."""

    ruta_archivo: Path
    registros_procesados: int   # days in month
    dias_con_venta: int
    total_bultos: float         # PRIMARY RULE: always float, never int
    articulo_nombre: str
    hojas: list[str] = field(default_factory=list)


class VentasArticuloService(BaseService):
    """Generates a daily sales Excel for a single article x sucursal."""

    SERVICE_SLUG = "ventas-articulo"
    GRANULARITY = "month"

    def generar_reporte(self, config: VentasArticuloConfig) -> VentasArticuloResult:
        """Generate the Excel report and return a result object.

        Args:
            config: VentasArticuloConfig with required id_articulo and id_sucursal.

        Returns:
            VentasArticuloResult with path, stats, and metadata.

        Raises:
            ValueError: If id_articulo or id_sucursal is None/missing.
        """
        # ── Validate required IDs ─────────────────────────────────
        if config.id_articulo is None:
            raise ValueError("id_articulo es requerido en VentasArticuloConfig")
        if config.id_sucursal is None:
            raise ValueError("id_sucursal es requerido en VentasArticuloConfig")

        # ── Resolve article name ──────────────────────────────────
        descripcion = self.data_loader.get_articulo_descripcion(config.id_articulo)
        articulo_nombre = descripcion if descripcion else f"Articulo {config.id_articulo}"

        # ── Fetch daily sales ─────────────────────────────────────
        df = self.data_loader.get_ventas_diarias_articulo(
            id_articulo=config.id_articulo,
            id_sucursal=config.id_sucursal,
            fecha_desde=config.fecha_desde,
            fecha_hasta=config.fecha_hasta,
        )

        # ── Normalize date keys ───────────────────────────────────
        ventas_por_fecha: dict = {}
        if not df.empty:
            df["fecha_comprobante"] = pd.to_datetime(df["fecha_comprobante"]).dt.date
            for _, row in df.iterrows():
                ventas_por_fecha[row["fecha_comprobante"]] = float(row["bultos"])

        # ── Derive year/month from fecha_desde ────────────────────
        fecha_dt = pd.to_datetime(config.fecha_desde)
        anio = fecha_dt.year
        mes = fecha_dt.month

        _, days_in_month = calendar.monthrange(anio, mes)

        # ── Resolve filename ──────────────────────────────────────
        nombre_archivo = self._resolve_filename(config, articulo_nombre, anio, mes)

        # ── Build Excel ───────────────────────────────────────────
        out_dir = config.output_dir or self._output_dir(config.fecha_desde)
        out_dir.mkdir(parents=True, exist_ok=True)
        ruta = build_excel(
            anio=anio,
            mes=mes,
            articulo_nombre=articulo_nombre,
            id_articulo=config.id_articulo,
            id_sucursal=config.id_sucursal,
            ventas_por_fecha=ventas_por_fecha,
            nombre_archivo=nombre_archivo,
            output_dir=out_dir,
        )

        # ── Compute summary stats ─────────────────────────────────
        dias_con_venta = len(ventas_por_fecha)
        total_bultos = float(sum(ventas_por_fecha.values())) if ventas_por_fecha else 0.0

        mes_nombre = MESES_COMPLETOS[mes]
        hoja_nombre = f"{articulo_nombre} - {mes_nombre[:3]} {anio}"[:31]

        return VentasArticuloResult(
            ruta_archivo=ruta,
            registros_procesados=days_in_month,
            dias_con_venta=dias_con_venta,
            total_bultos=total_bultos,
            articulo_nombre=articulo_nombre,
            hojas=[hoja_nombre],
        )

    def _resolve_filename(
        self,
        config: VentasArticuloConfig,
        articulo_nombre: str,
        anio: int,
        mes: int,
    ) -> str:
        """Compute output filename (without extension)."""
        if config.nombre_archivo:
            return config.nombre_archivo
        mes_nombre = MESES_COMPLETOS[mes]
        return f"{articulo_nombre} - {mes_nombre} {anio}"
