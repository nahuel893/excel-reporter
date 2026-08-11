"""Pure pandas transforms for stock-valorizado.

No DB access, no openpyxl. This module turns the raw stock snapshot plus the
price list into the frames the workbook renders. The universe policy encoded in
``build_universe`` is the contract agreed in
``docs/superpowers/specs/2026-08-07-stock-valorizado-design.md`` section 3.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Genericos that are not merchandise (returnable packaging, POS material,
# coolers, dispensers). Excluding them is the ONLY thing that removes rows from
# this report; everything else is kept and, where odd, flagged in Control.
NO_VENDIBLES = [
    "ENVASES CCU",
    "ENVASES GASEOSAS",
    "ENVASES PALAU",
    "EQUIPOS DE FRIO",
    "MARKETING",
    "MARKETING BRANCA",
    "DISPENSER",
]

SIN_CLASIFICAR = "SIN CLASIFICAR"
SIN_MARCA = "SIN MARCA"

# CASA CENTRAL first (it holds ~42% of the capital), then the same order the
# rest of the stock reports use.
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

IDENTIDAD = ["Artículo", "Descripción", "Genérico", "Marca"]


def ordenar_sucursales(sucursales) -> list[str]:
    """Known sucursales in canonical order, then any unexpected one alphabetically.

    A sucursal added in the ERP must never be silently dropped from the sheet,
    so unknown names are appended rather than filtered.
    """
    presentes = {str(s) for s in sucursales}
    conocidas = [s for s in SUCURSAL_ORDER if s in presentes]
    extras = sorted(presentes - set(SUCURSAL_ORDER))
    if extras:
        logger.warning(
            "Sucursal(es) fuera de SUCURSAL_ORDER, se agregan al final: %s", extras
        )
    return conocidas + extras


def build_universe(
    stock_df: pd.DataFrame,
    precios_df: pd.DataFrame,
    genericos_excluidos: list[str] | None = None,
) -> pd.DataFrame:
    """Join the stock snapshot to the price list and value every row.

    Policy (see design spec section 3):

    - ``genericos_excluidos`` are dropped (case/whitespace-insensitive). This is
      the only exclusion.
    - ``generico IS NULL`` survives, relabelled ``SIN CLASIFICAR``.
    - ``precio_base == 0`` survives with real bultos and a $0 valuation.
    - Negative stock survives and keeps a negative valuation.
    - Zero-stock rows survive — the sheet is a full catalog view.
    - An article missing from the price list keeps its bultos at $0 rather than
      vanishing from the merge.

    Merge key is ``id_articulo`` alone: the price list is a global article
    master with no sucursal dimension, so the composite-key rule does not apply.
    ``get_stock_diario`` already returns one row per (article, sucursal), so no
    fan-out is possible.

    Returns:
        DataFrame with columns: id_articulo, des_articulo, generico, marca,
        sucursal, cant_bultos, precio_base, valorizado.
    """
    df = stock_df.copy()

    if genericos_excluidos:
        excluidos = {str(g).strip().upper() for g in genericos_excluidos}
        antes = len(df)
        # astype(str) renders NaN as "nan", which never matches an entry here —
        # that is deliberate: a NULL generico must survive the exclusion.
        df = df.loc[
            ~df["generico"].astype(str).str.strip().str.upper().isin(excluidos)
        ].copy()
        logger.info(
            "build_universe: %d fila(s) excluidas por genérico no vendible %s",
            antes - len(df), sorted(excluidos),
        )

    df["generico"] = df["generico"].fillna(SIN_CLASIFICAR)
    df["marca"] = df["marca"].fillna(SIN_MARCA)
    # SUM(...) over gold.fact_stock can come back NaN; NaN would poison every
    # downstream total, so coalesce before valuing.
    df["cant_bultos"] = pd.to_numeric(df["cant_bultos"], errors="coerce").fillna(0.0)

    merged = df.merge(
        precios_df[["id_articulo", "precio_base", "precio_final"]],
        on="id_articulo", how="left",
    )
    sin_precio = int(merged["precio_base"].isna().sum())
    if sin_precio:
        logger.warning(
            "build_universe: %d fila(s) de stock sin precio en la lista — "
            "se valorizan en $0 y se listan en la hoja Control.", sin_precio,
        )
    merged["precio_base"] = merged["precio_base"].fillna(0.0)
    merged["precio_final"] = merged["precio_final"].fillna(0.0)
    merged["valorizado"] = merged["cant_bultos"] * merged["precio_base"]
    merged["valorizado_final"] = merged["cant_bultos"] * merged["precio_final"]

    return merged[
        [
            "id_articulo", "des_articulo", "generico", "marca", "sucursal",
            "cant_bultos", "precio_base", "valorizado",
            "precio_final", "valorizado_final",
        ]
    ].reset_index(drop=True)


def pivot_wide(universe_df: pd.DataFrame, valor_col: str = "valorizado") -> pd.DataFrame:
    """One row per article, two columns per sucursal (Bultos, Valorizado).

    ``valor_col`` selects which valuation feeds the money columns —
    ``"valorizado"`` (Precio Base) or ``"valorizado_final"`` (Precio Final).
    The output column NAMES are identical either way, so every downstream
    consumer (workbook, abc_pareto) works unchanged on either frame.

    Columns are a MultiIndex, not flat strings: ``Bultos`` and ``Valorizado``
    repeat once per sucursal, so a flat name would address all 14 at once.
    Access a leaf via its tuple, e.g. ``wide[("CASA CENTRAL", "Bultos")]`` or
    ``wide[("", "Artículo")]``.

    Rows are sorted by total valuation descending — the capital leads. A
    missing (article, sucursal) pair renders as 0, never NaN.
    """
    if universe_df.empty:
        return pd.DataFrame(
            columns=pd.MultiIndex.from_tuples(
                [("", c) for c in IDENTIDAD]
                + [("Total", "Total Bultos"), ("Total", "Total Valorizado")]
            )
        )

    sucursales = ordenar_sucursales(universe_df["sucursal"].unique())

    identidad = (
        universe_df.groupby("id_articulo", as_index=False)
        .agg(
            des_articulo=("des_articulo", "first"),
            generico=("generico", "first"),
            marca=("marca", "first"),
        )
    )

    def _matriz(valores: str) -> pd.DataFrame:
        m = universe_df.pivot_table(
            index="id_articulo", columns="sucursal", values=valores,
            aggfunc="sum", fill_value=0.0,
        )
        return m.reindex(
            index=identidad["id_articulo"], columns=sucursales, fill_value=0.0
        ).fillna(0.0)

    bultos = _matriz("cant_bultos")
    plata = _matriz(valor_col)

    columnas: list[tuple[str, str]] = []
    series: list[pd.Series] = []

    def _add(clave: tuple[str, str], valores) -> None:
        columnas.append(clave)
        series.append(pd.Series(list(valores), name=str(clave)))

    _add(("", "Artículo"), identidad["id_articulo"])
    _add(("", "Descripción"), identidad["des_articulo"])
    _add(("", "Genérico"), identidad["generico"])
    _add(("", "Marca"), identidad["marca"])
    for sucursal in sucursales:
        _add((sucursal, "Bultos"), bultos[sucursal])
        _add((sucursal, "Valorizado"), plata[sucursal])
    _add(("Total", "Total Bultos"), bultos.sum(axis=1))
    _add(("Total", "Total Valorizado"), plata.sum(axis=1))

    wide = pd.concat(series, axis=1)
    wide.columns = pd.MultiIndex.from_tuples(columnas)
    return wide.sort_values(("Total", "Total Valorizado"), ascending=False).reset_index(
        drop=True
    )


def resumen_sucursal(universe_df: pd.DataFrame) -> pd.DataFrame:
    """Bultos, money, share of capital and average value per bulto, per sucursal."""
    resumen = universe_df.groupby("sucursal", as_index=False).agg(
        Bultos=("cant_bultos", "sum"), Valorizado=("valorizado", "sum")
    )

    con_stock = (
        universe_df.loc[universe_df["cant_bultos"] != 0]
        .groupby("sucursal")["id_articulo"]
        .nunique()
    )
    resumen["Artículos con Stock"] = resumen["sucursal"].map(con_stock).fillna(0)

    total = resumen["Valorizado"].sum()
    resumen["% Capital"] = resumen["Valorizado"] / total if total else 0.0
    resumen["Valor Promedio x Bulto"] = resumen["Valorizado"].div(
        resumen["Bultos"].where(resumen["Bultos"] != 0)
    ).fillna(0.0)

    resumen = resumen.rename(columns={"sucursal": "Sucursal"})
    return resumen[
        ["Sucursal", "Bultos", "Artículos con Stock", "Valorizado", "% Capital",
         "Valor Promedio x Bulto"]
    ].sort_values("Valorizado", ascending=False).reset_index(drop=True)


def abc_pareto(wide_df: pd.DataFrame) -> pd.DataFrame:
    """ABC classification by cumulative share of immobilised capital.

    A = up to 80% of the money, B = up to 95%, C = the tail. Articles with no
    positive valuation (zero-price or negative stock) hold no capital to
    classify and are excluded; they are visible in Control instead.
    """
    if wide_df.empty:
        return pd.DataFrame(
            columns=["Artículo", "Descripción", "Genérico", "Marca", "Bultos",
                     "Valorizado", "% del Total", "% Acumulado", "Clase"]
        )

    base = pd.DataFrame(
        {
            "Artículo": wide_df[("", "Artículo")],
            "Descripción": wide_df[("", "Descripción")],
            "Genérico": wide_df[("", "Genérico")],
            "Marca": wide_df[("", "Marca")],
            "Bultos": wide_df[("Total", "Total Bultos")],
            "Valorizado": wide_df[("Total", "Total Valorizado")],
        }
    )
    base = base.loc[base["Valorizado"] > 0].sort_values(
        "Valorizado", ascending=False
    ).reset_index(drop=True)

    if base.empty:
        base["% del Total"] = []
        base["% Acumulado"] = []
        base["Clase"] = []
        return base

    total = base["Valorizado"].sum()
    base["% del Total"] = base["Valorizado"] / total
    base["% Acumulado"] = base["Valorizado"].cumsum() / total

    # Epsilon guards the boundary: 800/1000 must land in A, not B.
    eps = 1e-9
    base["Clase"] = "C"
    base.loc[base["% Acumulado"] <= 0.95 + eps, "Clase"] = "B"
    base.loc[base["% Acumulado"] <= 0.80 + eps, "Clase"] = "A"
    return base


def generico_x_sucursal(universe_df: pd.DataFrame) -> pd.DataFrame:
    """Valuation matrix: one row per generico, one column per sucursal, plus Total."""
    if universe_df.empty:
        return pd.DataFrame(columns=["Genérico", "Total"])

    sucursales = ordenar_sucursales(universe_df["sucursal"].unique())
    matriz = universe_df.pivot_table(
        index="generico", columns="sucursal", values="valorizado",
        aggfunc="sum", fill_value=0.0,
    ).reindex(columns=sucursales, fill_value=0.0).fillna(0.0)

    matriz["Total"] = matriz.sum(axis=1)
    return (
        matriz.sort_values("Total", ascending=False)
        .reset_index()
        .rename(columns={"generico": "Genérico"})
    )


def frames_control(
    stock_df: pd.DataFrame,
    universe_df: pd.DataFrame,
    genericos_excluidos: list[str] | None,
) -> dict[str, pd.DataFrame]:
    """Diagnostics so nothing is invisible.

    Returns four frames keyed by section title: articles priced at zero that
    hold stock, rows with negative stock, the SIN CLASIFICAR total, and what
    the generico exclusion removed.
    """
    sin_precio = (
        universe_df.loc[
            (universe_df["precio_base"] == 0) & (universe_df["cant_bultos"] != 0)
        ]
        .groupby(["id_articulo", "des_articulo", "generico"], as_index=False)
        .agg(Bultos=("cant_bultos", "sum"))
        .rename(columns={
            "id_articulo": "Artículo", "des_articulo": "Descripción",
            "generico": "Genérico",
        })
        .sort_values("Bultos", ascending=False)
    )

    negativos = (
        universe_df.loc[universe_df["cant_bultos"] < 0]
        .rename(columns={
            "id_articulo": "Artículo", "des_articulo": "Descripción",
            "generico": "Genérico", "sucursal": "Sucursal",
            "cant_bultos": "Bultos", "valorizado": "Valorizado",
        })[["Artículo", "Descripción", "Genérico", "Sucursal", "Bultos", "Valorizado"]]
        .sort_values("Bultos")
    )

    sin_clasificar = (
        universe_df.loc[universe_df["generico"] == SIN_CLASIFICAR]
        .groupby(["id_articulo", "des_articulo"], as_index=False)
        .agg(Bultos=("cant_bultos", "sum"), Valorizado=("valorizado", "sum"))
        .rename(columns={"id_articulo": "Artículo", "des_articulo": "Descripción"})
        .sort_values("Bultos", ascending=False)
    )

    excluidos = {str(g).strip().upper() for g in (genericos_excluidos or [])}
    mask = stock_df["generico"].astype(str).str.strip().str.upper().isin(excluidos)
    fuera = (
        stock_df.loc[mask]
        .groupby("generico", as_index=False)
        .agg(Bultos=("cant_bultos", "sum"))
        .rename(columns={"generico": "Genérico"})
        .sort_values("Bultos", ascending=False)
    )

    return {
        "Artículos con Precio Base = 0 y stock (se valorizan en $0)": sin_precio,
        "Stock negativo (se respeta el dato, con valorización negativa)": negativos,
        "SIN CLASIFICAR — artículos sin genérico en dim_articulo": sin_clasificar,
        "Excluido del informe por genérico no vendible": fuera,
    }
