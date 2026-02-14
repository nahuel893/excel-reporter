"""
Procesador de datos de cobertura.

Transforma los datos crudos de cobertura en formato tabular
listo para generar reportes Excel.
"""
import pandas as pd


def procesar_cobertura_preventista_generico(df: pd.DataFrame) -> pd.DataFrame:
    """
    Procesa cobertura por preventista y generico.

    Pivotea los periodos como columnas para comparar meses lado a lado.

    Args:
        df: DataFrame con columnas: periodo, sucursal, vendedor, id_ruta,
            generico, clientes_compradores, volumen_total

    Returns:
        DataFrame pivoteado con periodos como columnas
    """
    if df.empty:
        return df

    # Formatear periodo como texto legible (ej: "Ene 2026")
    df = df.copy()
    df["periodo_label"] = df["periodo"].apply(_formatear_periodo)

    # Pivotear clientes_compradores por periodo
    pivot = df.pivot_table(
        index=["sucursal", "vendedor", "generico"],
        columns="periodo_label",
        values="clientes_compradores",
        aggfunc="sum",
        fill_value=0
    ).reset_index()

    # Aplanar columnas
    pivot.columns = [
        col if not isinstance(col, tuple) else col
        for col in pivot.columns
    ]

    return pivot


def procesar_cobertura_preventista_marca(df: pd.DataFrame) -> pd.DataFrame:
    """
    Procesa cobertura por preventista y marca.

    Args:
        df: DataFrame con columnas: periodo, sucursal, vendedor, id_ruta,
            marca, clientes_compradores, volumen_total

    Returns:
        DataFrame pivoteado con periodos como columnas
    """
    if df.empty:
        return df

    df = df.copy()
    df["periodo_label"] = df["periodo"].apply(_formatear_periodo)

    pivot = df.pivot_table(
        index=["sucursal", "vendedor", "marca"],
        columns="periodo_label",
        values="clientes_compradores",
        aggfunc="sum",
        fill_value=0
    ).reset_index()

    pivot.columns = [
        col if not isinstance(col, tuple) else col
        for col in pivot.columns
    ]

    return pivot


def procesar_cobertura_sucursal_marca(df: pd.DataFrame) -> pd.DataFrame:
    """
    Procesa cobertura agregada por sucursal y marca.

    Args:
        df: DataFrame con columnas: periodo, sucursal, marca,
            clientes_compradores, volumen_total

    Returns:
        DataFrame pivoteado con periodos como columnas
    """
    if df.empty:
        return df

    df = df.copy()
    df["periodo_label"] = df["periodo"].apply(_formatear_periodo)

    pivot = df.pivot_table(
        index=["sucursal", "marca"],
        columns="periodo_label",
        values="clientes_compradores",
        aggfunc="sum",
        fill_value=0
    ).reset_index()

    pivot.columns = [
        col if not isinstance(col, tuple) else col
        for col in pivot.columns
    ]

    return pivot


# Meses en espanol
_MESES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Ago",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"
}


def _formatear_periodo(periodo) -> str:
    """Formatea un periodo date como 'Ene 2026'."""
    if hasattr(periodo, "month"):
        return f"{_MESES[periodo.month]} {periodo.year}"
    return str(periodo)
