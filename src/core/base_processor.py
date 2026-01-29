"""
BaseProcessor - Utilidades compartidas para procesamiento de datos.

Contiene funciones utilitarias que pueden ser utilizadas
por diferentes procesadores de reportes.
"""
import pandas as pd
from datetime import datetime, date, timedelta
from calendar import monthrange
from config.settings import FERIADOS


def calcular_dias_habiles(fecha_desde: date, fecha_hasta: date) -> tuple[int, int]:
    """
    Calcula los dias habiles (sin domingos ni feriados).

    Los dias transcurridos se calculan hasta HOY (fecha actual del sistema),
    no hasta fecha_hasta. Esto permite calcular tendencias realistas.

    Args:
        fecha_desde: Fecha inicio del periodo
        fecha_hasta: Fecha fin del periodo (define el mes para dias totales)

    Returns:
        Tupla (dias_transcurridos_hasta_hoy, dias_totales_mes)
    """
    hoy = date.today()
    feriados_set = {datetime.strptime(f, "%Y-%m-%d").date() for f in FERIADOS}

    # Dias del mes completo (basado en fecha_hasta)
    _, ultimo_dia = monthrange(fecha_hasta.year, fecha_hasta.month)
    primer_dia_mes = date(fecha_hasta.year, fecha_hasta.month, 1)
    ultimo_dia_mes = date(fecha_hasta.year, fecha_hasta.month, ultimo_dia)

    # Fecha de corte para dias transcurridos: el minimo entre hoy y fecha_hasta
    fecha_corte = min(hoy, fecha_hasta)

    dias_totales = 0
    dias_transcurridos = 0

    dia_actual = primer_dia_mes
    while dia_actual <= ultimo_dia_mes:
        es_habil = dia_actual.weekday() != 6 and dia_actual not in feriados_set
        if es_habil:
            dias_totales += 1
            if fecha_desde <= dia_actual <= fecha_corte:
                dias_transcurridos += 1
        dia_actual += timedelta(days=1)

    return dias_transcurridos, dias_totales


def calcular_factor_tendencia(fecha_desde: str, fecha_hasta: str) -> float:
    """
    Calcula el factor de tendencia basado en dias habiles.

    Args:
        fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
        fecha_hasta: Fecha fin formato 'YYYY-MM-DD'

    Returns:
        Factor de tendencia (dias_totales / dias_transcurridos)
    """
    fecha_desde_dt = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
    fecha_hasta_dt = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()
    dias_transcurridos, dias_totales = calcular_dias_habiles(fecha_desde_dt, fecha_hasta_dt)

    if dias_transcurridos > 0:
        return dias_totales / dias_transcurridos
    return 1.0


def completar_combinaciones(
    df_datos: pd.DataFrame,
    df_dimension1: pd.DataFrame,
    df_dimension2: pd.DataFrame,
    cols_join: list[str],
    cols_fill: list[str]
) -> pd.DataFrame:
    """
    Completa el DataFrame con todas las combinaciones de dimensiones.
    Las combinaciones faltantes se rellenan con 0.

    Args:
        df_datos: DataFrame con datos (ej: ventas)
        df_dimension1: Primera dimension (ej: sucursales)
        df_dimension2: Segunda dimension (ej: articulos)
        cols_join: Columnas para el join
        cols_fill: Columnas numericas a rellenar con 0

    Returns:
        DataFrame con todas las combinaciones
    """
    # Crear producto cartesiano
    df_dim1 = df_dimension1.copy()
    df_dim2 = df_dimension2.copy()
    df_dim1["_key"] = 1
    df_dim2["_key"] = 1
    todas_combinaciones = df_dim1.merge(df_dim2, on="_key").drop("_key", axis=1)

    # Merge con datos (left join para mantener todas las combinaciones)
    df_completo = todas_combinaciones.merge(
        df_datos,
        on=cols_join,
        how="left"
    )

    # Rellenar NaN con 0
    for col in cols_fill:
        if col in df_completo.columns:
            df_completo[col] = df_completo[col].fillna(0)

    return df_completo
