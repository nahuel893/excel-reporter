"""StockValorizadoService — stock in bultos and pesos, per article and sucursal.

Pipeline: latest stock snapshot (``get_stock_diario``) + external ERP price list
-> ``build_universe`` -> ``pivot_wide`` + analytics frames -> ``build_workbook``.
See ``docs/superpowers/specs/2026-08-07-stock-valorizado-design.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from src.core.data_loader import DataLoader
from src.services.base_service import BaseService
from src.services.stock_valorizado.config import StockValorizadoConfig
from src.services.stock_valorizado.precios import cargar_lista_precios, estado_lista_precios
from src.services.stock_valorizado.processor import (
    NO_VENDIBLES,
    abc_pareto,
    build_universe,
    frames_control,
    generico_x_sucursal,
    ordenar_sucursales,
    pivot_wide,
    resumen_sucursal,
)
from src.services.stock_valorizado.workbook import build_workbook

logger = logging.getLogger(__name__)


@dataclass
class StockValorizadoResult:
    """Outcome of a stock-valorizado run."""

    archivo_generado: Path
    fecha_stock: date
    n_articulos: int
    n_sucursales: int
    total_bultos: float
    total_valorizado: float
    total_valorizado_final: float
    lista_precios_path: Path
    lista_precios_mtime: datetime
    lista_precios_dias: int
    lista_precios_vencida: bool


class StockValorizadoService(BaseService):
    """Generates the valued stock workbook (bultos + pesos por sucursal)."""

    SERVICE_SLUG = "stock-valorizado"
    GRANULARITY = "day"

    def _create_data_loader(self, db_name: str | None = None) -> DataLoader:
        """A ``db_name`` override always builds a fresh loader; otherwise reuse
        the injected one so tests exercise their mock."""
        if db_name:
            return DataLoader(db_name=db_name)
        if self._data_loader is not None:
            return self._data_loader
        return DataLoader()

    def generar_reporte(self, config: StockValorizadoConfig) -> StockValorizadoResult:
        """Build the workbook and save it to disk.

        Raises:
            ValueError: ``gold.fact_stock`` has no snapshot at all — never emit
                a bogus empty report.
            FileNotFoundError: The price list is missing.
        """
        data_loader = self._create_data_loader(config.db_name)

        if config.fecha_stock:
            fecha_stock = date.fromisoformat(config.fecha_stock)
        else:
            fecha_stock = data_loader.get_ultima_fecha_stock()
            if fecha_stock is None:
                raise ValueError(
                    "No hay snapshot de stock disponible en gold.fact_stock "
                    "(get_ultima_fecha_stock() devolvió None)"
                )
        fecha_str = fecha_stock.isoformat()

        precios_path = Path(config.lista_precios_path)
        precios_df = cargar_lista_precios(precios_path)
        estado_precios = estado_lista_precios(precios_path, config.lista_precios_max_dias)

        stock_df = data_loader.get_stock_diario(fecha_str, config.genericos)
        if stock_df.empty:
            raise ValueError(f"gold.fact_stock no tiene filas para {fecha_str}")

        excluidos = (
            NO_VENDIBLES if config.genericos_excluidos is None else config.genericos_excluidos
        )
        universe = build_universe(stock_df, precios_df, genericos_excluidos=excluidos)

        wide = pivot_wide(universe)
        wide_final = pivot_wide(universe, valor_col="valorizado_final")
        sucursales = ordenar_sucursales(universe["sucursal"].unique()) if len(universe) else []

        wb = build_workbook(
            wide,
            sucursales,
            resumen_sucursal(universe),
            abc_pareto(wide),
            generico_x_sucursal(universe),
            frames_control(stock_df, universe, excluidos),
            fecha_stock=fecha_stock,
            estado_precios=estado_precios,
            wide_final=wide_final,
        )

        out_dir = self._output_dir(fecha_str)
        out_dir.mkdir(parents=True, exist_ok=True)

        nombre = config.nombre_archivo or f"Stock Valorizado - {fecha_stock.strftime('%d-%m-%Y')}"
        if not nombre.lower().endswith(".xlsx"):
            nombre += ".xlsx"
        ruta = out_dir / nombre
        wb.save(ruta)

        total_bultos = float(universe["cant_bultos"].sum())
        total_valorizado = float(universe["valorizado"].sum())
        total_valorizado_final = float(universe["valorizado_final"].sum())

        logger.info(
            "Stock Valorizado generado: %s (%d artículos, %d sucursales, "
            "%.0f bultos, base $%.2f, final $%.2f)",
            ruta.name, len(wide), len(sucursales), total_bultos,
            total_valorizado, total_valorizado_final,
        )

        return StockValorizadoResult(
            archivo_generado=ruta,
            fecha_stock=fecha_stock,
            n_articulos=len(wide),
            n_sucursales=len(sucursales),
            total_bultos=total_bultos,
            total_valorizado=total_valorizado,
            total_valorizado_final=total_valorizado_final,
            lista_precios_path=precios_path,
            lista_precios_mtime=estado_precios.mtime,
            lista_precios_dias=estado_precios.dias,
            lista_precios_vencida=estado_precios.vencida,
        )
