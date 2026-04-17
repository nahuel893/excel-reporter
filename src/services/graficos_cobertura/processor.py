"""Pure pandas transformations for graficos-cobertura.

All functions are side-effect-free — they take DataFrames in and return
DataFrames out. Zone routing is LOCAL to this service (5-zone scheme) — it
does NOT use src.core.zonas.aplicar_zonas_virtuales.
"""
from __future__ import annotations

import math

import pandas as pd

from src.services.graficos_cobertura.constants import (
    MARCAS_POR_GENERICO,
    MAX_MARCAS,
    RUTAS_A_SUC16,
    SUBDIVISION_AGUAS,
    ZONA_SUCS_AGUAS,
)


def reassign_rutas_suc1(
    df_marca_prev: pd.DataFrame,
    df_gen_prev: pd.DataFrame,
    df_marca_interior: pd.DataFrame,
    df_gen_interior: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Move rows whose id_ruta is in RUTAS_A_SUC16 out of suc-1 preventista
    data and INTO the interior sucursal aggregates.

    Returns updated (marca_prev, gen_prev, marca_interior, gen_interior).
    Originals are not mutated.
    """
    mask_m = df_marca_prev["id_ruta"].isin(RUTAS_A_SUC16)
    mask_g = df_gen_prev["id_ruta"].isin(RUTAS_A_SUC16)

    reasig_marca = (
        df_marca_prev[mask_m]
        .groupby(["anio", "mes", "marca"])["clientes"]
        .sum()
        .reset_index()
    )
    reasig_gen = (
        df_gen_prev[mask_g]
        .groupby(["anio", "mes", "generico"])["clientes"]
        .sum()
        .reset_index()
    )

    new_marca_prev = df_marca_prev[~mask_m].copy()
    new_gen_prev = df_gen_prev[~mask_g].copy()

    new_marca_interior = (
        pd.concat([df_marca_interior, reasig_marca], ignore_index=True)
        .groupby(["anio", "mes", "marca"])["clientes"]
        .sum()
        .reset_index()
    )
    new_gen_interior = (
        pd.concat([df_gen_interior, reasig_gen], ignore_index=True)
        .groupby(["anio", "mes", "generico"])["clientes"]
        .sum()
        .reset_index()
    )

    return new_marca_prev, new_gen_prev, new_marca_interior, new_gen_interior


def build_gen_marcas_mapping(df_articulos: pd.DataFrame) -> dict[str, set[str]]:
    """Build mapping generico -> set of marcas from dim_articulo.

    Also adds SUBDIVISION_AGUAS pseudo-genericos (AGUAS SABORIZADAS,
    AGUAS MINERAL) keyed by their configured marca lists.
    """
    if df_articulos.empty:
        mapping: dict[str, set[str]] = {}
    else:
        mapping = (
            df_articulos.groupby("generico")["marca"].apply(set).to_dict()
        )

    for subdiv, marcas in SUBDIVISION_AGUAS.items():
        mapping[subdiv] = set(marcas)

    return mapping


def filtrar_barras_mixtas(
    df: pd.DataFrame,
    anio_actual: int,
    anio_anterior: int,
    mes_corte: int,
) -> pd.DataFrame:
    """Filter a df with (anio, mes, ...) columns to keep:
       - rows where anio == anio_actual AND mes <= mes_corte, OR
       - rows where anio == anio_anterior AND mes > mes_corte.

    Drops the 'anio' column from the result.
    """
    if df.empty:
        return df.drop(columns=["anio"], errors="ignore").copy()

    actual = df[(df["anio"] == anio_actual) & (df["mes"] <= mes_corte)]
    anterior = df[(df["anio"] == anio_anterior) & (df["mes"] > mes_corte)]
    return pd.concat([actual, anterior], ignore_index=True).drop(columns="anio")


def get_zona_data(
    zona: str,
    generico: str,
    gen_marcas: dict[str, set[str]],
    *,
    df_marca_prev: pd.DataFrame,
    df_gen_prev: pd.DataFrame,
    df_marca_interior: pd.DataFrame,
    df_gen_interior: pd.DataFrame,
    df_marca_snorte: pd.DataFrame,
    df_gen_snorte: pd.DataFrame,
    df_marca_jujuy: pd.DataFrame,
    df_gen_jujuy: pd.DataFrame,
    df_marca_todas: pd.DataFrame,
    df_gen_todas: pd.DataFrame,
    df_gen_suc1: pd.DataFrame,
    df_aguas: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Dispatch per zone — return (df_bars, df_gen) for a zona/generico pair.

    - df_bars: columns=[mes, marca, clientes] — for bar chart
    - df_gen: columns=[anio, mes, clientes] — for line chart
    """
    marcas_gen = gen_marcas.get(generico, set())
    is_aguas = generico in SUBDIVISION_AGUAS

    # ── BARS (marca) ──
    if zona == "INTERIOR SALTA SUR":
        df_bars = df_marca_interior[df_marca_interior["marca"].isin(marcas_gen)].copy()
    elif zona == "INTERIOR SALTA NORTE":
        df_bars = df_marca_snorte[df_marca_snorte["marca"].isin(marcas_gen)].copy()
    elif zona == "JUJUY INTERIOR":
        df_bars = df_marca_jujuy[df_marca_jujuy["marca"].isin(marcas_gen)].copy()
    elif zona == "NOA NORTE":
        df_bars = df_marca_todas[df_marca_todas["marca"].isin(marcas_gen)].copy()
    elif zona == "SALTA CAPITAL":
        df_bars = df_marca_prev[df_marca_prev["marca"].isin(marcas_gen)].copy()
        if not df_bars.empty:
            df_bars = (
                df_bars.groupby(["mes", "marca"])["clientes"].sum().reset_index()
            )
    else:
        df_bars = pd.DataFrame(columns=["mes", "marca", "clientes"])

    # ── GEN lines ──
    if is_aguas:
        sucs = ZONA_SUCS_AGUAS.get(zona)
        df_a = df_aguas[df_aguas["subdivision_aguas"] == generico].copy()
        if sucs is not None:
            df_a = df_a[df_a["id_sucursal"].isin(sucs)]
        df_gen = df_a.groupby(["anio", "mes"])["clientes"].sum().reset_index()
    elif zona == "INTERIOR SALTA SUR":
        df_gen = df_gen_interior[df_gen_interior["generico"] == generico].copy()
    elif zona == "INTERIOR SALTA NORTE":
        df_gen = df_gen_snorte[df_gen_snorte["generico"] == generico].copy()
    elif zona == "JUJUY INTERIOR":
        df_gen = df_gen_jujuy[df_gen_jujuy["generico"] == generico].copy()
    elif zona == "NOA NORTE":
        df_gen = df_gen_todas[df_gen_todas["generico"] == generico].copy()
    elif zona == "SALTA CAPITAL":
        # anio<2025 from preventista, anio>=2025 from suc 1
        df_prev = df_gen_prev[df_gen_prev["generico"] == generico].copy()
        if not df_prev.empty:
            df_prev = (
                df_prev.groupby(["anio", "mes"])["clientes"].sum().reset_index()
            )
            df_prev = df_prev[df_prev["anio"] < 2025]
        df_suc = df_gen_suc1[df_gen_suc1["generico"] == generico].copy()
        df_suc = df_suc[df_suc["anio"] >= 2025]
        df_gen = pd.concat([df_prev, df_suc], ignore_index=True)
    else:
        df_gen = pd.DataFrame(columns=["anio", "mes", "clientes"])

    return df_bars, df_gen


def build_matrix_generico_mensual(
    df: pd.DataFrame, anios: list[int]
) -> pd.DataFrame:
    """Pivot a long-form df [zona, anio, mes, clientes] into:
       - rows = zona
       - columns = MultiIndex (anio, mes) for all anios × meses 1..12
       - values = clientes (missing cells filled with 0).
    """
    if df.empty:
        return pd.DataFrame()

    # All possible (anio, mes) column keys
    full_cols = pd.MultiIndex.from_tuples(
        [(a, m) for a in anios for m in range(1, 13)],
        names=["anio", "mes"],
    )

    pivot = (
        df.pivot_table(
            index="zona",
            columns=["anio", "mes"],
            values="clientes",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(columns=full_cols, fill_value=0)
    )
    return pivot


def build_matrix_comparativo(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot [zona, anio, marca, clientes] into rows=(zona, anio), cols=marca."""
    if df.empty:
        return pd.DataFrame()

    return df.pivot_table(
        index=["zona", "anio"],
        columns="marca",
        values="clientes",
        aggfunc="sum",
        fill_value=0,
    )


def select_marcas_para_grafico(
    generico: str,
    gen_marcas_set: set[str],
    df_bars: pd.DataFrame,
    max_marcas: int = MAX_MARCAS,
) -> list[str]:
    """Decide which marcas to plot:
       1. If generico is in MARCAS_POR_GENERICO → use that fixed list (filtered to ones present in df_bars).
       2. If generico is in SUBDIVISION_AGUAS → use that subdivision list.
       3. Otherwise → top-N marcas by clientes sum, descending.
    """
    marcas_en_bars = set(df_bars["marca"].unique()) if not df_bars.empty else set()

    if generico in MARCAS_POR_GENERICO:
        return [m for m in MARCAS_POR_GENERICO[generico] if m in marcas_en_bars]

    if generico in SUBDIVISION_AGUAS:
        return [m for m in SUBDIVISION_AGUAS[generico] if m in marcas_en_bars]

    if df_bars.empty:
        return []

    return (
        df_bars.groupby("marca")["clientes"]
        .sum()
        .sort_values(ascending=False)
        .head(max_marcas)
        .index.tolist()
    )


def compute_yoy(actual: float, anterior: float) -> float:
    """Year-over-year percentage change.

    Formula: ((actual - anterior) / anterior) * 100

    Edge cases:
    - 0/0 → 0.0 (no growth, no prior)
    - positive/0 → 100.0 (new coverage)
    - NaN inputs → treat as 0
    """
    a = 0.0 if (actual is None or (isinstance(actual, float) and math.isnan(actual))) else float(actual)
    p = 0.0 if (anterior is None or (isinstance(anterior, float) and math.isnan(anterior))) else float(anterior)

    if p == 0:
        return 0.0 if a == 0 else 100.0

    return ((a - p) / p) * 100.0
