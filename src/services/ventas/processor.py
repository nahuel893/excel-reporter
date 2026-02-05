"""
Procesador especifico para reportes de ventas.

Contiene la logica de procesamiento y formato de datos
para el reporte de ventas por sucursal, generico y marca.
"""
import pandas as pd
from datetime import datetime
from config.settings import COLUMN_NAMES, DIAS_SEMANA
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


def formatear_nombre_dia(fecha: datetime) -> str:
    """
    Formatea una fecha como 'dd-mm DayName'.

    Args:
        fecha: Objeto datetime

    Returns:
        String formateado, ej: '01-01 Jueves'
    """
    dia_semana = DIAS_SEMANA[fecha.weekday()]
    return f"{fecha.strftime('%d-%m')} {dia_semana}"


def procesar_ventas_diarias(
    df: pd.DataFrame,
    fecha_desde: str,
    fecha_hasta: str,
    df_sucursales: pd.DataFrame | None = None,
    df_articulos: pd.DataFrame | None = None
) -> pd.DataFrame:
    """
    Procesa las ventas diarias para generar tabla con columnas por dia.

    Formato de salida:
    Sucursal | Generico | Cant(Gen) | Tend(Gen) | Monto(Gen) | Marca | 01-01 Jueves | ... | Total | Tend | Monto

    Args:
        df: DataFrame con columnas: sucursal, generico, marca, fecha, cantidad, monto
        fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
        fecha_hasta: Fecha fin formato 'YYYY-MM-DD'
        df_sucursales: DataFrame con todas las sucursales (para completar combinaciones)
        df_articulos: DataFrame con todas las combinaciones generico-marca

    Returns:
        DataFrame con formato incluyendo dias como columnas
    """
    if df.empty:
        return pd.DataFrame(columns=list(COLUMN_NAMES.values()))

    # Asegurar que fecha sea datetime
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"])

    # Completar combinaciones faltantes si se proporcionan las dimensiones
    if df_sucursales is not None and df_articulos is not None:
        fechas_unicas = df["fecha"].unique()

        # Crear producto cartesiano: sucursales × articulos × fechas
        df_sucursales_temp = df_sucursales.copy()
        df_articulos_temp = df_articulos.copy()
        df_sucursales_temp["_key"] = 1
        df_articulos_temp["_key"] = 1

        todas_combinaciones = df_sucursales_temp.merge(df_articulos_temp, on="_key").drop("_key", axis=1)

        # Expandir por fechas
        df_fechas = pd.DataFrame({"fecha": fechas_unicas, "_key": 1})
        todas_combinaciones["_key"] = 1
        todas_combinaciones = todas_combinaciones.merge(df_fechas, on="_key").drop("_key", axis=1)

        # Merge con ventas reales (left join)
        df = todas_combinaciones.merge(
            df,
            on=["sucursal", "generico", "marca", "fecha"],
            how="left"
        )

        # Rellenar NaN con 0
        df["cantidad"] = df["cantidad"].fillna(0)
        df["monto"] = df["monto"].fillna(0)

    # Factor de tendencia
    factor_tendencia = calcular_factor_tendencia(fecha_desde, fecha_hasta)

    # Obtener fechas unicas ordenadas y crear nombres de columnas
    fechas_unicas = sorted(df["fecha"].unique())
    columnas_dias = {fecha: formatear_nombre_dia(pd.Timestamp(fecha)) for fecha in fechas_unicas}

    # Pivotar cantidades por dia
    pivot_dias = df.pivot_table(
        index=["sucursal", "generico", "marca"],
        columns="fecha",
        values="cantidad",
        aggfunc="sum",
        fill_value=0
    ).reset_index()

    # Renombrar columnas de fecha al formato deseado
    pivot_dias.columns = [
        columnas_dias.get(col, col) if col in columnas_dias else col
        for col in pivot_dias.columns
    ]

    # Calcular totales por marca (suma de cantidad y monto)
    totales_marca = df.groupby(["sucursal", "generico", "marca"]).agg({
        "cantidad": "sum",
        "monto": "sum"
    }).reset_index()
    totales_marca.columns = ["sucursal", "generico", "marca", "total_marca", "monto_marca"]
    totales_marca["tend_marca"] = totales_marca["total_marca"] * factor_tendencia

    # Merge pivot con totales
    df_merged = pivot_dias.merge(totales_marca, on=["sucursal", "generico", "marca"])

    # Calcular totales por generico
    totales_generico = df_merged.groupby(["sucursal", "generico"]).agg({
        "total_marca": "sum",
        "monto_marca": "sum"
    }).reset_index()
    totales_generico.columns = ["sucursal", "generico", "cant_generico", "monto_generico"]
    totales_generico["tend_generico"] = totales_generico["cant_generico"] * factor_tendencia

    # Ordenar por sucursal, generico y monto descendente
    df_merged = df_merged.sort_values(
        ["sucursal", "generico", "monto_marca"],
        ascending=[True, True, False]
    )

    # Obtener nombres de columnas de dias en orden
    cols_dias = [columnas_dias[f] for f in fechas_unicas]

    # Construir tabla final con totales de generico solo en primera fila
    rows = []
    for (sucursal, generico), grupo in df_merged.groupby(["sucursal", "generico"], sort=False):
        # Obtener totales del generico
        totales = totales_generico[
            (totales_generico["sucursal"] == sucursal) &
            (totales_generico["generico"] == generico)
        ].iloc[0]

        for i, (_, fila) in enumerate(grupo.iterrows()):
            row = {
                COLUMN_NAMES["sucursal"]: sucursal,
                COLUMN_NAMES["generico"]: generico,
                COLUMN_NAMES["cant_generico"]: totales["cant_generico"] if i == 0 else None,
                COLUMN_NAMES["tend_generico"]: round(totales["tend_generico"]) if i == 0 else None,
                COLUMN_NAMES["monto_generico"]: totales["monto_generico"] if i == 0 else None,
                COLUMN_NAMES["marca"]: fila["marca"],
            }

            # Agregar columnas de dias (0 si no hay venta)
            for col_dia in cols_dias:
                row[col_dia] = int(fila[col_dia])

            # Agregar totales de marca
            row[COLUMN_NAMES["total_marca"]] = fila["total_marca"]
            row[COLUMN_NAMES["tend_marca"]] = round(fila["tend_marca"])
            row[COLUMN_NAMES["monto_marca"]] = fila["monto_marca"]

            rows.append(row)

    return pd.DataFrame(rows)


# Mantener funcion original para compatibilidad
def procesar_ventas(df: pd.DataFrame, fecha_desde: str, fecha_hasta: str) -> pd.DataFrame:
    """
    Procesa las ventas para generar tabla con totales por generico y tendencias.
    Version sin desglose diario (compatibilidad).

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
                COLUMN_NAMES["total_marca"]: fila["cantidad"],
                COLUMN_NAMES["tend_marca"]: round(tendencia_marca),
                COLUMN_NAMES["monto_marca"]: fila["monto"],
            }
            rows.append(row)

    return pd.DataFrame(rows)
