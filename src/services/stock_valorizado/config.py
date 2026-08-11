"""Configuration for the stock-valorizado report."""

from __future__ import annotations

from dataclasses import dataclass

from src.services.stock_valorizado.precios import MAX_DIAS_DEFAULT


@dataclass
class StockValorizadoConfig:
    """Parameters for a stock-valorizado run.

    Attributes:
        lista_precios_path: Path to the ERP price-list xlsx. Required — there
            is no price column in ``gold``, so without it there is no report.
        fecha_stock: Snapshot date (YYYY-MM-DD). Defaults to the latest date
            available in ``gold.fact_stock``.
        genericos: Restrict the report to these genericos. ``None`` = all.
        genericos_excluidos: Non-sellable genericos to drop. ``None`` falls
            back to ``processor.NO_VENDIBLES``; pass ``[]`` to exclude nothing.
        lista_precios_max_dias: Age in days past which the price list is
            flagged as stale on every sheet. Prices are re-exported by hand, so
            nothing else notices when that stops happening.
        nombre_archivo: Output filename override.
        db_name: Target a different database (multi-DB setups).
    """

    lista_precios_path: str
    fecha_stock: str | None = None
    genericos: list[str] | None = None
    genericos_excluidos: list[str] | None = None
    lista_precios_max_dias: int = MAX_DIAS_DEFAULT
    nombre_archivo: str | None = None
    db_name: str | None = None
