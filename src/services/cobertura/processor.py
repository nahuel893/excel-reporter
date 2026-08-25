"""
Procesador de datos de cobertura.

Transforma los datos crudos de cobertura en formato
listo para generar reportes Excel.
"""
import pandas as pd
from pandas.api.types import is_numeric_dtype


# Meses en espanol
_MESES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Ago",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"
}

# Marcador para claves de index que llegan vacias desde la BD. `vendedor` sale de
# un LEFT JOIN contra dim_vendedor: si falta la fila del dim, el valor es NULL.
SIN_DATO = "(sin dato)"
SIN_DATO_NUMERICO = -1


def _formatear_periodo(periodo) -> str:
    """Formatea un periodo date como 'Ene 2026'."""
    if hasattr(periodo, "month"):
        return f"{_MESES[periodo.month]} {periodo.year}"
    return str(periodo)


def _orden_cronologico(df: pd.DataFrame) -> list[str]:
    """Etiquetas de periodo ordenadas por fecha real, no alfabeticamente.

    El pivot ordena sus columnas por el texto de la etiqueta, y ahi 'Ene 2026'
    precede a 'Feb 2025'. Leer dos meses lado a lado solo funciona si el mas
    viejo queda a la izquierda.
    """
    return (
        df.sort_values("periodo")["periodo_label"]
        .drop_duplicates()
        .tolist()
    )


def procesar_cobertura(df: pd.DataFrame, columnas_index: list[str]) -> pd.DataFrame:
    """
    Pivotea periodos como columnas para comparar meses lado a lado.

    La cobertura son clientes DISTINTOS: no se puede sumar entre marcas,
    genericos ni periodos. Este pivot no lo hace — marca/generico viven en el
    index y el periodo en las columnas, asi que el `aggfunc="sum"` solo puede
    colapsar filas que difieren por preventista, el unico eje donde la suma es
    valida (cada cliente pertenece a una sola ruta).

    Args:
        df: DataFrame con columna 'periodo' y datos de cobertura
        columnas_index: Columnas que forman el index del pivot

    Returns:
        DataFrame pivoteado con periodos como columnas, en orden cronologico
    """
    if df.empty:
        return df

    df = df.copy()
    df["periodo_label"] = df["periodo"].apply(_formatear_periodo)

    # pivot_table DESCARTA las filas cuya clave de index sea NaN, sin aviso: esa
    # cobertura desapareceria del informe. Se rellena antes de pivotear. El
    # relleno se elige por tipo, no por `dtype == object`: desde pandas 3.0 las
    # columnas de texto son `str`, no `object`, y ese chequeo mandaba los
    # nombres de vendedor faltantes al centinela numerico.
    for col in columnas_index:
        if df[col].isna().any():
            relleno = SIN_DATO_NUMERICO if is_numeric_dtype(df[col]) else SIN_DATO
            df[col] = df[col].fillna(relleno)

    pivot = df.pivot_table(
        index=columnas_index,
        columns="periodo_label",
        values="clientes_compradores",
        aggfunc="sum",
        fill_value=0
    ).reset_index()

    pivot.columns.name = None
    return pivot[columnas_index + _orden_cronologico(df)]
