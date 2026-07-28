"""Processor for stock-badie: pure pandas transforms (RF-03/RF-04/RF-05).

No DB access and no openpyxl workbook building here — this module only
shapes DataFrames. The workbook (formulas, styling, layout) is built in a
later work unit; this module hands it clean, formula-free data.
"""

import logging
from datetime import date, datetime, timedelta

import pandas as pd

from config.settings import FERIADOS

logger = logging.getLogger(__name__)

# Sucursal column order, exact as in the reference xlsm STOCK sheet.
SUCURSAL_ORDER = [
    "CASA CENTRAL",
    "SUCURSAL LIBERTADOR",
    "SUCURSAL MAIMARA",
    "SUCURSAL HUMAHUACA",
    "SUCURSAL ABRA PAMPA",
    "SUCURSAL LA QUIACA",
    "SUCURSAL SAN PEDRO",
    "SUCURSAL GUEMES",
    "SUCURSAL CAFAYATE",
    "SUCURSAL JOAQUIN V GONZALEZ",
    "SUCURSAL METAN",
    "SUCURSAL ORAN",
    "SUCURSAL TARTAGAL",
    "SUCURSAL PERICO",
]

_IDENTITY_COLUMNS = ["idArticulo", "dsArticulo", "GENERICO", "MARCA"]
_BLOCK_SUFFIXES = ["VENTA", "PEDIDO", "ALCANCE"]
_TOTAL_BLOCK_COLUMNS = ["Total", "VENTA TOTAL", "PEDIDO TOTAL", "ALCANCE TOTAL"]


def _wide_columns() -> pd.MultiIndex:
    """Build the fixed 64-column MultiIndex: 4 identity + 14x4 sucursal
    blocks + 4 total block.

    Column contract (consumed by PR3 to map onto Excel headers/cells):
    - Identity: ("", "idArticulo" | "dsArticulo" | "GENERICO" | "MARCA")
    - Each of the 14 SUCURSAL_ORDER blocks:
      (sucursal, "Stock" | "VENTA" | "PEDIDO" | "ALCANCE")
    - Total block: ("Total", "Total" | "VENTA TOTAL" | "PEDIDO TOTAL" | "ALCANCE TOTAL")

    A flat list would repeat the labels VENTA/PEDIDO/ALCANCE 14x (one per
    sucursal), which is a silent-overwrite footgun in pandas
    (df["PEDIDO"] = x sets all 14 identically). The MultiIndex keeps every
    leaf column addressable unambiguously via its (block, suffix) tuple
    while preserving the exact 64-column layout/order.
    """
    tuples = [("", col) for col in _IDENTITY_COLUMNS]
    for sucursal in SUCURSAL_ORDER:
        tuples.append((sucursal, "Stock"))
        for suffix in _BLOCK_SUFFIXES:
            tuples.append((sucursal, suffix))
    for col in _TOTAL_BLOCK_COLUMNS:
        tuples.append(("Total", col))
    return pd.MultiIndex.from_tuples(tuples)


def build_universe(
    stock_df: pd.DataFrame,
    venta_df: pd.DataFrame,
    genericos_excluidos: list[str] | None = None,
) -> pd.DataFrame:
    """Build the (sucursal, articulo) universe merging today's stock with
    this month's sales.

    Merge key: (sucursal, id_articulo) BY NAME. get_stock_diario() only
    carries the sucursal descripcion (no id_sucursal), while get_venta_mes()
    carries both id_sucursal and descripcion; des_sucursal == descripcion
    for all 14 sucursales (verified), so a name merge is safe here.

    Base = stock_df, LEFT JOIN venta_df onto it: gold.fact_stock emits a
    zero-stock row for every (article, deposito) every day, so a
    sold-but-zero-stock pair (quiebre) already has a stock row to join
    sales onto.

    A pair is kept when stock_bultos != 0 OR venta_bultos != 0 (after
    coalescing missing sales to 0); the stock=0/no-sales pairs (~91% zero
    noise) are dropped.

    Adds an `estado` column, classified totally over every kept row
    (get_venta_mes does not filter anulado, so venta_bultos may be negative
    from net returns — a plain "normal" default with two partial masks would
    silently mislabel a negative-venta row): 'quiebre' (stock_bultos <= 0 &
    venta_bultos != 0), 'dormant' (stock_bultos > 0 & venta_bultos <= 0),
    'normal' (stock_bultos > 0 & venta_bultos > 0 — the only remaining case).

    `genericos_excluidos` drops non-sale genericos (packaging, marketing
    material, coolers, dispensers) before anything else, so they appear
    neither in the article rows nor in the per-generico band. Matching is
    case-insensitive and whitespace-tolerant; unknown names are ignored
    (a typo silently filters nothing, so the count is logged).

    Returns:
        DataFrame with columns: id_articulo, des_articulo, generico, marca,
        sucursal, stock_bultos, stock_htls, venta_bultos, venta_htls, estado.
    """
    if genericos_excluidos:
        excluidos = {str(g).strip().upper() for g in genericos_excluidos}
        antes = len(stock_df)
        stock_df = stock_df.loc[
            ~stock_df["generico"].astype(str).str.strip().str.upper().isin(excluidos)
        ]
        logger.info(
            "build_universe: %d fila(s) de stock excluidas por generico %s",
            antes - len(stock_df), sorted(excluidos),
        )

    venta_cols = ["sucursal", "id_articulo", "venta_bultos", "venta_htls"]
    venta_subset = venta_df[venta_cols]

    # Orphan sucursal (NaN) from get_venta_mes's LEFT JOIN onto dim_sucursal —
    # these sales carry no known sucursal name, can never match a stock_df
    # row, and are silently lost by the merge below unless we warn here.
    orphan_sucursal_count = int(venta_subset["sucursal"].isna().sum())
    if orphan_sucursal_count:
        logger.warning(
            "build_universe: %d venta row(s) have a NaN sucursal (orphan "
            "id_sucursal from get_venta_mes's LEFT JOIN to dim_sucursal) and "
            "are not reflected in the report.",
            orphan_sucursal_count,
        )

    # Anti-join: venta rows whose (sucursal, id_articulo) key is absent from
    # stock_df — possible fact_stock lag or sucursal-name drift between the
    # two sources. Never crash on this; just warn with the count so the sales
    # gap is visible instead of silently dropped by the left merge below.
    stock_keys = set(zip(stock_df["sucursal"], stock_df["id_articulo"]))
    unmatched_count = sum(
        1
        for key in zip(venta_subset["sucursal"], venta_subset["id_articulo"])
        if key not in stock_keys
    )
    if unmatched_count:
        logger.warning(
            "build_universe: %d venta row(s) did not match any stock_df row "
            "by (sucursal, id_articulo) and are not reflected in the report "
            "(possible fact_stock lag or sucursal-name drift).",
            unmatched_count,
        )

    # NOTE (future hardening, deferred): this merges by sucursal NAME rather
    # than id_sucursal (see docstring above for why that's currently safe).
    # Switching to an id-based merge is deferred to a later work unit.
    merged = stock_df.merge(
        venta_subset,
        on=["sucursal", "id_articulo"],
        how="left",
    )
    merged = merged.rename(columns={"cant_bultos": "stock_bultos", "cant_htls": "stock_htls"})
    # gold.fact_stock SUM(...) can return NaN (same NaN-coalesce precedent as
    # stock_diario/processor.py); NaN breaks the `!= 0` keep-filter below
    # (NaN != 0 evaluates True) and the estado classification, so coalesce
    # immediately after the rename.
    merged["stock_bultos"] = merged["stock_bultos"].fillna(0)
    merged["stock_htls"] = merged["stock_htls"].fillna(0)
    merged["venta_bultos"] = merged["venta_bultos"].fillna(0)
    merged["venta_htls"] = merged["venta_htls"].fillna(0)

    # Membership test uses bultos only (design decision) — htls is
    # intentionally not part of the universe keep-filter.
    kept = merged.loc[(merged["stock_bultos"] != 0) | (merged["venta_bultos"] != 0)].copy()

    kept["estado"] = "normal"
    kept.loc[(kept["stock_bultos"] <= 0) & (kept["venta_bultos"] != 0), "estado"] = "quiebre"
    kept.loc[(kept["stock_bultos"] > 0) & (kept["venta_bultos"] <= 0), "estado"] = "dormant"

    return kept[
        [
            "id_articulo", "des_articulo", "generico", "marca", "sucursal",
            "stock_bultos", "stock_htls", "venta_bultos", "venta_htls", "estado",
        ]
    ].reset_index(drop=True)


def pivot_wide(universe_df: pd.DataFrame) -> pd.DataFrame:
    """Pivot the long (sucursal, articulo) universe into one row per articulo.

    Layout: 4 identity columns (idArticulo, dsArticulo, GENERICO, MARCA),
    then 14 sucursal blocks (in SUCURSAL_ORDER) of [Stock, VENTA, PEDIDO,
    ALCANCE], then a Total block [Total, VENTA TOTAL, PEDIDO TOTAL,
    ALCANCE TOTAL] — 64 columns total. Column order is fixed regardless of
    input row order.

    Columns are a pandas MultiIndex, not flat strings — VENTA/PEDIDO/ALCANCE
    repeat once per sucursal block, so a flat name would be ambiguous
    (df["PEDIDO"] would silently address all 14 at once). Access a leaf via
    its tuple, e.g. result[("CASA CENTRAL", "Stock")] or result[("", "idArticulo")].
    See ``_wide_columns`` docstring for the full contract (PR3 maps these
    tuples onto Excel headers/cells).

    Stock/Venta cells are DB values (bultos); a missing (articulo, sucursal)
    pair renders as 0, never NaN. PEDIDO, ALCANCE, and the entire Total
    block are left as None placeholders — they become live Excel formulas
    in a later work unit, not computed here.
    """
    columns = _wide_columns()

    if universe_df.empty:
        return pd.DataFrame(columns=columns)

    # Sucursales present in the universe but outside SUCURSAL_ORDER would
    # otherwise be silently excluded by the reindex below — warn so the
    # data loss is visible instead of invisible.
    unknown_sucursales = set(universe_df["sucursal"].unique()) - set(SUCURSAL_ORDER)
    if unknown_sucursales:
        logger.warning(
            "pivot_wide: %d sucursal(es) outside SUCURSAL_ORDER excluded "
            "from the report: %s",
            len(unknown_sucursales), sorted(unknown_sucursales),
        )

    # Article-level attributes (des_articulo/generico/marca) are assumed
    # constant per id_articulo across all sucursales — 'first' picks any one
    # occurrence.
    identity = (
        universe_df.groupby("id_articulo", as_index=False)
        .agg(
            dsArticulo=("des_articulo", "first"),
            GENERICO=("generico", "first"),
            MARCA=("marca", "first"),
        )
        .sort_values("id_articulo")
        .reset_index(drop=True)
    )
    # Coalesce NaN text fields so openpyxl never writes a bare NaN (same
    # precedent as stock_diario/processor.py's build_excel).
    identity[["dsArticulo", "GENERICO", "MARCA"]] = identity[
        ["dsArticulo", "GENERICO", "MARCA"]
    ].fillna("")
    articulo_ids = identity["id_articulo"]

    stock_pivot = universe_df.pivot_table(
        index="id_articulo", columns="sucursal", values="stock_bultos",
        aggfunc="sum", fill_value=0,
    ).reindex(index=articulo_ids, columns=SUCURSAL_ORDER, fill_value=0)
    venta_pivot = universe_df.pivot_table(
        index="id_articulo", columns="sucursal", values="venta_bultos",
        aggfunc="sum", fill_value=0,
    ).reindex(index=articulo_ids, columns=SUCURSAL_ORDER, fill_value=0)

    rows = []
    for _, art in identity.iterrows():
        art_id = art["id_articulo"]
        row = [art_id, art["dsArticulo"], art["GENERICO"], art["MARCA"]]
        for sucursal in SUCURSAL_ORDER:
            row.append(stock_pivot.at[art_id, sucursal])
            row.append(venta_pivot.at[art_id, sucursal])
            row.append(None)  # PEDIDO placeholder — live formula in a later PR
            row.append(None)  # ALCANCE placeholder — live formula in a later PR
        row.extend([None, None, None, None])  # Total block placeholders
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def compute_dias_venta(hasta: date) -> int:
    """Business days from the 1st of `hasta`'s month through `hasta`
    inclusive, excluding Sundays and FERIADOS. Saturdays count (mirrors the
    xlsm NETWORKDAYS.INTL(..., 11, FERIADOS) — weekmask 11 = Sunday-only
    weekend).

    Takes an explicit reference date instead of freezing the clock — this
    project has no freezegun dependency, and a date parameter keeps the
    result deterministic regardless of the real system date at test time.
    Mirrors the day-classification rule used by
    ``base_processor.calcular_dias_habiles`` (weekday() != 6 and not a
    FERIADOS date), but that helper anchors "days elapsed" to
    ``date.today()`` internally, which would make this function's result
    depend on wall-clock time; reimplementing the predicate here keeps it
    pure.

    Floored at 1, mirroring base_processor.calcular_factor_tendencia's
    ``if dias_transcurridos > 0 ... else 1.0`` guard: this value feeds the
    downstream PEDIDO formula MAX((Venta/$DiasVenta$)*$DiasStock$ - Stock, 0),
    which has NO IFERROR wrapper — a raw 0 here would produce #DIV/0! across
    every PEDIDO cell in the workbook.
    """
    feriados = {datetime.strptime(f, "%Y-%m-%d").date() for f in FERIADOS}
    primer_dia = hasta.replace(day=1)

    dias = 0
    dia_actual = primer_dia
    while dia_actual <= hasta:
        if dia_actual.weekday() != 6 and dia_actual not in feriados:
            dias += 1
        dia_actual += timedelta(days=1)
    return max(dias, 1)
