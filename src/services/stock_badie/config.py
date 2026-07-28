"""Configuration for the stock-badie report (RF-01..RF-11)."""

from dataclasses import dataclass


@dataclass
class StockBadieConfig:
    """Configuration for stock-badie report generation.

    fecha_desde/fecha_hasta define the current-month sales window consumed
    by DataLoader.get_venta_mes(): half-open [fecha_desde, fecha_hasta),
    where fecha_hasta is the 1st of the NEXT month (see get_venta_mes's
    docstring — never BETWEEN/inclusive, to avoid partial-month leakage).
    Stock is always the latest available snapshot
    (DataLoader.get_ultima_fecha_stock()), independent of this window.

    fecha_referencia is an optional YYYY-MM-DD override for the "as of"
    date used to compute DiasVenta (business days elapsed this month) via
    processor.compute_dias_venta(). Defaults to date.today() when None —
    the design spec's "business days from the 1st of the month through
    CURRENT_DATE inclusive". Exposed here (rather than hardcoding
    date.today() inside the service) so callers/tests can pin it without a
    freezegun dependency, matching the deterministic-by-parameter
    precedent already set by processor.compute_dias_venta().

    genericos_excluidos drops non-sale genericos (envases, marketing,
    equipos de frio, dispensers) from the whole report — article rows AND
    the per-generico band. Parameterized here so the list lives in
    configs/stock_badie.json, not in code.
    """

    fecha_desde: str
    fecha_hasta: str
    dias_stock: int = 15
    genericos: list[str] | None = None
    genericos_excluidos: list[str] | None = None
    nombre_archivo: str | None = None
    db_name: str | None = None
    fecha_referencia: str | None = None
