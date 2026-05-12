"""Per-sucursal matrix builder and data dispatcher for graficos-cobertura.

Pure pandas transformations that produce per-sucursal DataFrames instead of
per-zone aggregates. Mirrors the zone-level functions in processor.py but
keeps id_sucursal as the grouping key.

All functions are side-effect-free — they take DataFrames in and return
dicts of DataFrames out.
"""
from __future__ import annotations

import pandas as pd

from src.services.graficos_cobertura.constants import RUTAS_A_SUC16


def reassign_rutas_suc1_sucursal(
    df_marca_prev: pd.DataFrame,
    df_generico_prev: pd.DataFrame,
    df_marca_interior: pd.DataFrame,
    df_generico_interior: pd.DataFrame,
    sucursal_destino: int = 16,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Move rows whose id_ruta is in RUTAS_A_SUC16 from suc-1 preventista data
    into the per-sucursal interior aggregates.

    This is the per-sucursal variant of reassign_rutas_suc1. Reassigned rows
    from prev data are tagged with ``sucursal_destino`` (default: sucursal 16,
    matching the RUTAS_A_SUC16 semantics) so they merge into the correct
    per-sucursal row.

    Args:
        df_marca_prev: Preventista marca data for suc 1 (with id_ruta column).
        df_generico_prev: Preventista generico data for suc 1 (with id_ruta column).
        df_marca_interior: Per-sucursal marca data (with id_sucursal column).
        df_generico_interior: Per-sucursal generico data (with id_sucursal column).
        sucursal_destino: ID of the sucursal to assign reassigned rows to.
            Defaults to 16 (RUTAS_A_SUC16 routes map to sucursal 16).

    Returns updated (marca_prev, generico_prev, marca_interior, generico_interior).
    Originals are not mutated.
    """
    mask_m = df_marca_prev["id_ruta"].isin(RUTAS_A_SUC16)
    mask_g = df_generico_prev["id_ruta"].isin(RUTAS_A_SUC16)

    # Reassigned rows: drop id_ruta, add id_sucursal=sucursal_destino
    reasig_marca = df_marca_prev[mask_m].drop(columns=["id_ruta"]).copy()
    reasig_marca["id_sucursal"] = sucursal_destino

    reasig_gen = df_generico_prev[mask_g].drop(columns=["id_ruta"]).copy()
    reasig_gen["id_sucursal"] = sucursal_destino

    new_marca_prev = df_marca_prev[~mask_m].copy()
    new_gen_prev = df_generico_prev[~mask_g].copy()

    # Group columns for re-aggregation (common columns after concat)
    group_cols_m = [c for c in df_marca_interior.columns if c != "clientes"]
    group_cols_g = [c for c in df_generico_interior.columns if c != "clientes"]

    # Ensure reasig has same columns as interior for clean concat
    for col in group_cols_m:
        if col not in reasig_marca.columns:
            reasig_marca[col] = pd.NA
    reasig_marca = reasig_marca[group_cols_m + ["clientes"]]

    for col in group_cols_g:
        if col not in reasig_gen.columns:
            reasig_gen[col] = pd.NA
    reasig_gen = reasig_gen[group_cols_g + ["clientes"]]

    new_marca_interior = (
        pd.concat([df_marca_interior, reasig_marca], ignore_index=True)
        .groupby(group_cols_m, observed=True)["clientes"]
        .sum()
        .reset_index()
    )
    new_gen_interior = (
        pd.concat([df_generico_interior, reasig_gen], ignore_index=True)
        .groupby(group_cols_g, observed=True)["clientes"]
        .sum()
        .reset_index()
    )

    return new_marca_prev, new_gen_prev, new_marca_interior, new_gen_interior


def build_sucursal_matrices(
    df_marca_suc: pd.DataFrame,
    df_generico_suc: pd.DataFrame,
    generico: str,
    zona: str,
    sucursales_config: dict[str, list[int] | None],
) -> tuple[dict[int, pd.DataFrame], dict[int, pd.DataFrame]]:
    """Build per-sucursal bar and line matrices for a given zona and generico.

    Takes per-sucursal DataFrames (from get_cobertura_sucursal_marca
    and get_cobertura_sucursal_generico) and splits them by id_sucursal
    according to the zona's sucursal list from sucursales_config.

    Args:
        df_marca_suc: DataFrame with columns [anio, mes, id_sucursal, marca, clientes]
        df_generico_suc: DataFrame with columns [anio, mes, id_sucursal, generico, clientes]
        generico: Generico name to filter (e.g. "CERVEZAS")
        zona: Zone name (e.g. "INTERIOR SALTA SUR")
        sucursales_config: Mapping of zona -> list of id_sucursal (None = all)

    Returns:
        Tuple of (bars_dict, gen_dict) where:
        - bars_dict: {id_sucursal: DataFrame[mes, marca, clientes]}
        - gen_dict: {id_sucursal: DataFrame[anio, mes, clientes]}
    """
    id_sucursales = sucursales_config.get(zona)

    # If zona not in config, return empty dicts
    if id_sucursales is None and zona not in sucursales_config:
        return {}, {}

    bars_dict: dict[int, pd.DataFrame] = {}
    gen_dict: dict[int, pd.DataFrame] = {}

    # Determine which sucursales to process
    if id_sucursales is None:
        # NOA NORTE — all sucursales present in data
        suc_ids = sorted(df_marca_suc["id_sucursal"].unique()) if not df_marca_suc.empty else []
        suc_ids_gen = sorted(df_generico_suc["id_sucursal"].unique()) if not df_generico_suc.empty else []
        suc_ids = sorted(set(suc_ids) | set(suc_ids_gen))
    else:
        suc_ids = id_sucursales

    for sid in suc_ids:
        # Bars: filter marca data for this sucursal
        suc_marca = df_marca_suc[df_marca_suc["id_sucursal"] == sid].copy()
        # Gen: filter generico data for this sucursal
        suc_gen = df_generico_suc[
            (df_generico_suc["id_sucursal"] == sid) &
            (df_generico_suc["generico"] == generico)
        ].copy()

        if not suc_marca.empty:
            bars_dict[sid] = suc_marca[["mes", "marca", "clientes"]].reset_index(drop=True)
        if not suc_gen.empty:
            gen_dict[sid] = suc_gen[["anio", "mes", "generico", "clientes"]].reset_index(drop=True)

    return bars_dict, gen_dict


def get_sucursal_data(
    zona: str,
    generico: str,
    df_marca_suc: pd.DataFrame,
    df_generico_suc: pd.DataFrame,
    sucursales_config: dict[str, list[int] | None],
    gen_marcas: dict[str, set[str]],
    df_marca_prev: pd.DataFrame | None = None,
    df_generico_prev: pd.DataFrame | None = None,
    df_generico_suc1: pd.DataFrame | None = None,
    df_aguas: pd.DataFrame | None = None,
) -> dict[int, pd.DataFrame]:
    """Per-sucursal data dispatcher — same logic as get_zona_data but per sucursal.

    Handles:
    - NOA NORTE (all sucursales, id_sucursales=None)
    - SALTA CAPITAL (suc 1, uses preventista data with ruta split for bars,
      suc1 data for generico lines)
    - Interior zones (uses per-sucursal cob data filtered by zone's sucursal list)
    - AGUAS subdivisions (uses aguas data filtered by subdivision and zone)

    Args:
        zona: Zone name
        generico: Generico name
        df_marca_suc: Per-sucursal marca data [anio, mes, id_sucursal, marca, clientes]
        df_generico_suc: Per-sucursal generico data [anio, mes, id_sucursal, generico, clientes]
        sucursales_config: Mapping zona -> list of id_sucursal
        gen_marcas: Mapping generico -> set of marcas
        df_marca_prev: Preventista marca data for suc 1 (with id_ruta), for SALTA CAPITAL bars
        df_generico_prev: Preventista generico data for suc 1, for SALTA CAPITAL
        df_generico_suc1: Sucursal 1 generico cob data, for SALTA CAPITAL lines >= 2025
        df_aguas: Aguas subdivision data if generico is an AGUAS subdivision

    Returns:
        Dict mapping id_sucursal -> DataFrame[mes, marca, clientes] for bar charts.
    """
    from src.services.graficos_cobertura.constants import SUBDIVISION_AGUAS, ZONA_SUCS_AGUAS

    is_aguas = generico in SUBDIVISION_AGUAS
    id_sucursales = sucursales_config.get(zona)

    # Unknown zone
    if id_sucursales is None and zona not in sucursales_config and zona != "NOA NORTE":
        return {}

    # ── AGUAS subdivisions ──
    if is_aguas:
        if df_aguas is None or df_aguas.empty:
            return {}
        df_a = df_aguas[df_aguas["subdivision_aguas"] == generico].copy()
        sucs = ZONA_SUCS_AGUAS.get(zona)
        if sucs is not None:
            df_a = df_a[df_a["id_sucursal"].isin(sucs)]
        # Per-sucursal aguas: group by id_sucursal
        result: dict[int, pd.DataFrame] = {}
        for sid, grp in df_a.groupby("id_sucursal"):
            result[sid] = grp[["mes", "clientes"]].reset_index(drop=True)
        return result

    # ── NOA NORTE (all sucursales) ──
    if zona == "NOA NORTE" or (id_sucursales is None and zona in sucursales_config):
        marcas_gen = gen_marcas.get(generico, set())
        filtered = df_marca_suc[df_marca_suc["marca"].isin(marcas_gen)].copy()
        result = {}
        for sid, grp in filtered.groupby("id_sucursal"):
            result[sid] = grp[["mes", "marca", "clientes"]].reset_index(drop=True)
        return result

    # ── SALTA CAPITAL ──
    if zona == "SALTA CAPITAL" and id_sucursales == [1]:
        if df_marca_prev is not None and not df_marca_prev.empty:
            marcas_gen = gen_marcas.get(generico, set())
            # For bars: use preventista data (with id_ruta), filtered to marcas
            prev = df_marca_prev[df_marca_prev["marca"].isin(marcas_gen)].copy()
            # Aggregate away id_ruta for the single sucursal
            if not prev.empty:
                prev = prev.groupby(["mes", "marca"])["clientes"].sum().reset_index()
                return {1: prev}
        return {}

    # ── Interior zones ──
    marcas_gen = gen_marcas.get(generico, set())
    filtered = df_marca_suc[
        (df_marca_suc["id_sucursal"].isin(id_sucursales)) &
        (df_marca_suc["marca"].isin(marcas_gen))
    ].copy()

    result = {}
    for sid, grp in filtered.groupby("id_sucursal"):
        result[sid] = grp[["mes", "marca", "clientes"]].reset_index(drop=True)
    return result