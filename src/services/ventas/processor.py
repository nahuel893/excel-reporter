"""
Procesador especifico para reportes de ventas.

Contiene la logica de procesamiento y formato de datos
para el reporte de ventas por sucursal, generico y marca.
"""
import pandas as pd
from config.settings import COLUMN_NAMES
from src.core.base_processor import calcular_factor_tendencia, completar_combinaciones as base_completar


def completar_combinaciones(df_ventas: pd.DataFrame, df_sucursales: pd.DataFrame, df_articulos: pd.DataFrame) -> pd.DataFrame:
    """
    Completa el DataFrame de ventas con todas las combinaciones sucursal-generico-marca.
    Las combinaciones sin ventas se rellenan con 0.

    Args:
        df_ventas: DataFrame con ventas (sucursal, generico, marca, cantidad, monto)
        df_sucursales: DataFrame con todas las sucursales
        df_articulos: DataFrame con todas las combinaciones generico-marca

    Returns:
        DataFrame con todas las combinaciones, ventas faltantes en 0
    """
    return base_completar(
        df_datos=df_ventas,
        df_dimension1=df_sucursales,
        df_dimension2=df_articulos,
        cols_join=["sucursal", "generico", "marca"],
        cols_fill=["cantidad", "monto"]
    )


def procesar_ventas(df: pd.DataFrame, fecha_desde: str, fecha_hasta: str) -> pd.DataFrame:
    """
    Procesa las ventas para generar tabla con totales por generico y tendencias.

    El total del generico aparece solo en la primera fila de cada grupo
    sucursal-generico. Las demas filas tienen esas columnas vacias.

    Args:
        df: DataFrame con columnas: sucursal, generico, marca, cantidad, monto
        fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
        fecha_hasta: Fecha fin formato 'YYYY-MM-DD'

    Returns:
        DataFrame con formato incluyendo tendencias
    """
    if df.empty:
        return pd.DataFrame(columns=list(COLUMN_NAMES.values()))

    # Factor de tendencia
    factor_tendencia = calcular_factor_tendencia(fecha_desde, fecha_hasta)

    # Calcular totales por sucursal y generico
    totales_generico = df.groupby(["sucursal", "generico"]).agg({
        "cantidad": "sum",
        "monto": "sum"
    }).reset_index()
    totales_generico.columns = ["sucursal", "generico", "cant_generico", "monto_generico"]
    totales_generico["tend_generico"] = totales_generico["cant_generico"] * factor_tendencia

    # Ordenar datos por sucursal, generico y monto descendente
    df = df.sort_values(["sucursal", "generico", "monto"], ascending=[True, True, False])

    # Construir tabla final
    rows = []
    for (sucursal, generico), grupo in df.groupby(["sucursal", "generico"], sort=False):
        # Obtener totales del generico
        totales = totales_generico[
            (totales_generico["sucursal"] == sucursal) &
            (totales_generico["generico"] == generico)
        ].iloc[0]

        for i, (_, fila) in enumerate(grupo.iterrows()):
            tendencia_marca = fila["cantidad"] * factor_tendencia
            row = {
                COLUMN_NAMES["sucursal"]: sucursal,
                COLUMN_NAMES["generico"]: generico,
                COLUMN_NAMES["cant_generico"]: totales["cant_generico"] if i == 0 else None,
                COLUMN_NAMES["tend_generico"]: round(totales["tend_generico"]) if i == 0 else None,
                COLUMN_NAMES["monto_generico"]: totales["monto_generico"] if i == 0 else None,
                COLUMN_NAMES["marca"]: fila["marca"],
                COLUMN_NAMES["cant_marca"]: fila["cantidad"],
                COLUMN_NAMES["tend_marca"]: round(tendencia_marca),
                COLUMN_NAMES["monto_marca"]: fila["monto"],
            }
            rows.append(row)

    return pd.DataFrame(rows)
