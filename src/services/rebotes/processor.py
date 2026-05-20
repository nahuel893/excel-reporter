"""Processor functions for rebotes report."""

import logging
from typing import Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def calcular_rebotes_vendedor(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega columna % rechazo = bultos_rechazados / bultos_vendidos.

    Maneja division por cero: cuando bultos_vendidos == 0, % rechazo = 0.0.

    Args:
        df: DataFrame con columnas [vendedor, bultos_vendidos, bultos_rechazados, id_fuerza_ventas]

    Returns:
        DataFrame con columna adicional % Rechazo.
    """
    if df.empty:
        return df.assign(**{"% Rechazo": pd.Series(dtype=float)})

    df = df.copy()
    df["% Rechazo"] = (
        df["bultos_rechazados"].astype(float) / df["bultos_vendidos"].astype(float)
    ).fillna(0.0).replace([float("inf"), float("-inf")], 0.0)

    return df


def agregar_totales_supervisor(
    df: pd.DataFrame, supervisor_map: dict[str, list[str]]
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Separa datos en seccion de vendedores y seccion de supervisores agregados.

    Case-insensitive matching: los nombres de vendedores en df se comparan
    en uppercase contra los keys/values de supervisor_map (tambien uppercase).

    Args:
        df: DataFrame con columna 'vendedor' (y bultos_vendidos, bultos_rechazados)
        supervisor_map: dict[supervisor_key -> list_of_vendor_names]

    Returns:
        (df_vendedor, df_supervisor) donde:
          - df_vendedor: misma estructura que df, ordenada por supervisor key + vendedor
          - df_supervisor: aggregate por supervisor con columnas [Supervisor, Bultos Vendidos,
            Bultos Rechazados, % Rechazo]
    """
    if df.empty:
        cols = ["Supervisor", "Bultos Vendidos", "Bultos Rechazados", "% Rechazo"]
        return pd.DataFrame(columns=df.columns.tolist()), pd.DataFrame(columns=cols)

    df = df.copy()
    df["vendedor_upper"] = df["vendedor"].str.upper()

    # Build reverse map: vendor_upper -> supervisor_key
    vendor_to_supervisor: dict[str, str] = {}
    for supervisor_key, vendors in supervisor_map.items():
        for vendor in vendors:
            vendor_upper = vendor.upper()
            if vendor_upper in vendor_to_supervisor:
                logger.warning(
                    "Vendor '%s' appears under multiple supervisors (first: '%s', second: '%s')",
                    vendor,
                    vendor_to_supervisor[vendor_upper],
                    supervisor_key,
                )
            vendor_to_supervisor[vendor_upper] = supervisor_key

    # Asignar supervisor a cada vendedor
    def lookup_supervisor(vendor_upper: str) -> str:
        return vendor_to_supervisor.get(vendor_upper, "Sin Supervisor")

    df["Supervisor"] = df["vendedor_upper"].apply(lookup_supervisor)

    # Log vendors not in map
    unmapped = df[df["Supervisor"] == "Sin Supervisor"]["vendedor"].unique()
    for v in unmapped:
        logger.warning("Vendor '%s' not found in SUPERVISOR_VENDOR_MAP", v)

    # --- Vendedor section: sorted by supervisor key then vendedor ---
    df_vendedor = (
        df.sort_values(["Supervisor", "vendedor"])
        .reset_index(drop=True)
    )

    # --- Supervisor section: aggregate ---
    supervisor_agg = (
        df.groupby("Supervisor", as_index=False)
        .agg(
            **{
                "Bultos Vendidos": ("bultos_vendidos", "sum"),
                "Bultos Rechazados": ("bultos_rechazados", "sum"),
            }
        )
    )

    gfarah_total = pd.DataFrame(
        {
            "Supervisor": ["GFARAH"],
            "Bultos Vendidos": [df["bultos_vendidos"].sum()],
            "Bultos Rechazados": [df["bultos_rechazados"].sum()],
        }
    )
    supervisor_agg = pd.concat([supervisor_agg, gfarah_total], ignore_index=True)
    supervisor_agg = supervisor_agg.drop_duplicates(subset=["Supervisor"], keep="last")

    # Recalculate % rechazo per supervisor aggregate
    supervisor_agg["% Rechazo"] = (
        supervisor_agg["Bultos Rechazados"] / supervisor_agg["Bultos Vendidos"]
    ).fillna(0.0).replace([float("inf"), float("-inf")], 0.0)

    # GFARAH va al final (es el jefe, tiene el total de todos)
    supervisor_agg = supervisor_agg.sort_values("Supervisor", key=lambda x: x == "GFARAH").reset_index(drop=True)

    return df_vendedor, supervisor_agg


def pivot_rebotes_por_generico(
    df: pd.DataFrame, supervisor_map: dict[str, list[str]]
) -> pd.DataFrame:
    """
    Calcula % rechazo por vendedor para cada grupo de generico y pivota.

    Agrupa VINOS CCU + SIDRAS Y LICORES como MULTICCU.
    Retorna DataFrame con columnas intercaladas por grupo:
    [Vendedor, Supervisor, CERVEZAS Bultos, CERVEZAS Rechazados, %CERVEZAS, ...]
    """
    if df.empty:
        cols = ["Vendedor", "Supervisor"]
        for g in ["CERVEZAS", "AGUAS DANONE", "MULTICCU"]:
            cols += [f"{g} Bultos", f"{g} Rechazados", f"%{g}"]
        return pd.DataFrame(columns=cols)

    df = df.copy()
    df["grupo"] = df["generico"].replace(
        {"VINOS CCU": "MULTICCU", "SIDRAS Y LICORES": "MULTICCU"}
    )

    # Aggregate per vendor + grupo
    agg = df.groupby(["vendedor", "grupo"], as_index=False).agg(
        bultos_vendidos=("bultos_vendidos", "sum"),
        bultos_rechazados=("bultos_rechazados", "sum"),
    )
    agg["% Rechazo"] = (
        agg["bultos_rechazados"].astype(float) / agg["bultos_vendidos"].astype(float)
    ).fillna(0.0).replace([float("inf"), float("-inf")], 0.0)

    # Pivot each metric
    pivot_vendidos = agg.pivot_table(index="vendedor", columns="grupo", values="bultos_vendidos", aggfunc="first").fillna(0)
    pivot_rechazados = agg.pivot_table(index="vendedor", columns="grupo", values="bultos_rechazados", aggfunc="first").fillna(0)
    pivot_pct = agg.pivot_table(index="vendedor", columns="grupo", values="% Rechazo", aggfunc="first").fillna(0.0)

    for col in ["CERVEZAS", "AGUAS DANONE", "MULTICCU"]:
        for p in [pivot_vendidos, pivot_rechazados, pivot_pct]:
            if col not in p.columns:
                p[col] = 0

    groups = ["CERVEZAS", "AGUAS DANONE", "MULTICCU"]
    result = pd.DataFrame()
    result["Vendedor"] = pivot_vendidos.index
    for g in groups:
        result[f"{g} Bultos"] = pivot_vendidos[g].values
        result[f"{g} Rechazados"] = pivot_rechazados[g].values
        result[f"%{g}"] = pivot_pct[g].values

    # Assign supervisor
    result["vendedor_upper"] = result["Vendedor"].str.upper()
    vendor_to_supervisor: dict[str, str] = {}
    for sk, vendors in supervisor_map.items():
        for v in vendors:
            vendor_to_supervisor[v.upper()] = sk

    def lookup(vu: str) -> str:
        return vendor_to_supervisor.get(vu, "Sin Supervisor")

    result["Supervisor"] = result["vendedor_upper"].apply(lookup)
    result = result.drop(columns=["vendedor_upper"])
    result = result.sort_values(["Supervisor", "Vendedor"]).reset_index(drop=True)

    cols = ["Vendedor", "Supervisor"]
    for g in groups:
        cols += [f"{g} Bultos", f"{g} Rechazados", f"%{g}"]
    result = result[cols]
    return result


def pivot_rebotes_por_generico_supervisor(
    df: pd.DataFrame, supervisor_map: dict[str, list[str]]
) -> pd.DataFrame:
    """
    Calcula % rechazo por supervisor para cada grupo de generico y pivota.

    Agrupa VINOS CCU + SIDRAS Y LICORES como MULTICCU.
    Retorna DataFrame con columnas intercaladas por grupo.
    """
    if df.empty:
        cols = ["Supervisor"]
        for g in ["CERVEZAS", "AGUAS DANONE", "MULTICCU"]:
            cols += [f"{g} Bultos", f"{g} Rechazados", f"%{g}"]
        return pd.DataFrame(columns=cols)

    df = df.copy()

    # Map vendors to supervisor
    vendor_to_supervisor: dict[str, str] = {}
    for sk, vendors in supervisor_map.items():
        for v in vendors:
            vendor_to_supervisor[v.upper()] = sk

    df["vendedor_upper"] = df["vendedor"].str.upper()

    def lookup(vu: str) -> str:
        return vendor_to_supervisor.get(vu, "Sin Supervisor")

    df["Supervisor"] = df["vendedor_upper"].apply(lookup)

    df["grupo"] = df["generico"].replace(
        {"VINOS CCU": "MULTICCU", "SIDRAS Y LICORES": "MULTICCU"}
    )

    # Aggregate per supervisor + grupo
    agg = df.groupby(["Supervisor", "grupo"], as_index=False).agg(
        bultos_vendidos=("bultos_vendidos", "sum"),
        bultos_rechazados=("bultos_rechazados", "sum"),
    )

    # GFARAH = total de todos los vendedores
    gfarah_totals = df.groupby("grupo", as_index=False).agg(
        bultos_vendidos=("bultos_vendidos", "sum"),
        bultos_rechazados=("bultos_rechazados", "sum"),
    )
    gfarah_totals["Supervisor"] = "GFARAH"
    agg = pd.concat([agg, gfarah_totals], ignore_index=True)
    agg = agg.drop_duplicates(subset=["Supervisor", "grupo"], keep="last")

    agg["% Rechazo"] = (
        agg["bultos_rechazados"].astype(float) / agg["bultos_vendidos"].astype(float)
    ).fillna(0.0).replace([float("inf"), float("-inf")], 0.0)

    # Pivot each metric
    pivot_vendidos = agg.pivot_table(index="Supervisor", columns="grupo", values="bultos_vendidos", aggfunc="first").fillna(0)
    pivot_rechazados = agg.pivot_table(index="Supervisor", columns="grupo", values="bultos_rechazados", aggfunc="first").fillna(0)
    pivot_pct = agg.pivot_table(index="Supervisor", columns="grupo", values="% Rechazo", aggfunc="first").fillna(0.0)

    for col in ["CERVEZAS", "AGUAS DANONE", "MULTICCU"]:
        for p in [pivot_vendidos, pivot_rechazados, pivot_pct]:
            if col not in p.columns:
                p[col] = 0

    groups = ["CERVEZAS", "AGUAS DANONE", "MULTICCU"]
    result = pd.DataFrame()
    result["Supervisor"] = pivot_vendidos.index
    for g in groups:
        result[f"{g} Bultos"] = pivot_vendidos[g].values
        result[f"{g} Rechazados"] = pivot_rechazados[g].values
        result[f"%{g}"] = pivot_pct[g].values

    result = result.sort_values("Supervisor", key=lambda x: x == "GFARAH").reset_index(drop=True)

    cols = ["Supervisor"]
    for g in groups:
        cols += [f"{g} Bultos", f"{g} Rechazados", f"%{g}"]
    result = result[cols]
    return result
