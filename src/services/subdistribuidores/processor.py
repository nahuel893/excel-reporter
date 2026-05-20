"""Processor functions for subdistribuidores report."""

import logging
from typing import Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def procesar_subdistribuidores(df_ventas: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Procesa ventas de subdistribuidores y genera两份DataFrames:
    - df_bultos: detalle a nivel de articulo (6-level hierarchy)
    - df_totales: agregados por niveles (Cliente, Fantasia, Razon Social, Generico, Marca)

    Args:
        df_ventas: DataFrame con columnas:
            [id_cliente, fantasia, razon_social, generico, marca, des_articulo, cantidad]

    Returns:
        (df_bultos, df_totales)
        - df_bultos: 6-level hierarchy rows (Cliente, Fantasia, Razon Social, Generico, Marca, Articulo, Bultos)
        - df_totales: 5-level aggregates at each level
    """
    if df_ventas.empty:
        logger.warning("DataFrame vacio en procesar_subdistribuidores")
        cols_bultos = ["Cliente", "Fantasia", "Razon Social", "Generico", "Marca", "Articulo", "Bultos"]
        cols_totales = ["Nivel", "Cliente", "Fantasia", "Razon Social", "Generico", "Marca", "Bultos"]
        return pd.DataFrame(columns=cols_bultos), pd.DataFrame(columns=cols_totales)

    df = df_ventas.copy()

    # Asegurar que no haya nulos en columnas de cliente
    df["fantasia"] = df["fantasia"].fillna("")
    df["razon_social"] = df["razon_social"].fillna("")

    # ── Bultos: una fila por combinacion unica de los 6 niveles ──────────────
    bultos_cols = ["id_cliente", "fantasia", "razon_social", "generico", "marca", "des_articulo"]
    df_bultos = (
        df.groupby(bultos_cols, as_index=False)
        .agg(Bultos=("cantidad", "sum"))
    )
    # Renombrar columnas para el Excel
    df_bultos.columns = ["Cliente", "Fantasia", "Razon Social", "Generico", "Marca", "Articulo", "Bultos"]

    # ── Totales: aggregations a 5 niveles ──────────────────────────────────
    niveles = []

    # Nivel 1: Cliente
    agg_cliente = (
        df.groupby(["id_cliente"], as_index=False)
        .agg(Bultos=("cantidad", "sum"))
    )
    agg_cliente.columns = ["Cliente", "Bultos"]
    niveles.append(("Cliente", agg_cliente))

    # Nivel 2: Cliente + Fantasia
    agg_fantasia = (
        df.groupby(["id_cliente", "fantasia"], as_index=False)
        .agg(Bultos=("cantidad", "sum"))
    )
    agg_fantasia.columns = ["Cliente", "Fantasia", "Bultos"]
    niveles.append(("Fantasia", agg_fantasia))

    # Nivel 3: Cliente + Fantasia + Razon Social
    agg_razon = (
        df.groupby(["id_cliente", "fantasia", "razon_social"], as_index=False)
        .agg(Bultos=("cantidad", "sum"))
    )
    agg_razon.columns = ["Cliente", "Fantasia", "Razon Social", "Bultos"]
    niveles.append(("Razon Social", agg_razon))

    # Nivel 4: Cliente + Fantasia + Razon Social + Generico
    agg_generico = (
        df.groupby(["id_cliente", "fantasia", "razon_social", "generico"], as_index=False)
        .agg(Bultos=("cantidad", "sum"))
    )
    agg_generico.columns = ["Cliente", "Fantasia", "Razon Social", "Generico", "Bultos"]
    niveles.append(("Generico", agg_generico))

    # Nivel 5: Cliente + Fantasia + Razon Social + Generico + Marca
    agg_marca = (
        df.groupby(["id_cliente", "fantasia", "razon_social", "generico", "marca"], as_index=False)
        .agg(Bultos=("cantidad", "sum"))
    )
    agg_marca.columns = ["Cliente", "Fantasia", "Razon Social", "Generico", "Marca", "Bultos"]
    niveles.append(("Marca", agg_marca))

    # Ensamblar df_totales con columna Nivel
    rows = []
    for nivel_nombre, df_nivel in niveles:
        df_copy = df_nivel.copy()
        # Agregar columnas faltantes para alineacion
        for col in ["Fantasia", "Razon Social", "Generico", "Marca"]:
            if col not in df_copy.columns:
                df_copy[col] = ""
        df_copy.insert(0, "Nivel", nivel_nombre)
        # Reordenar columnas
        df_copy = df_copy[["Nivel", "Cliente", "Fantasia", "Razon Social", "Generico", "Marca", "Bultos"]]
        rows.append(df_copy)

    df_totales = pd.concat(rows, ignore_index=True)

    return df_bultos, df_totales