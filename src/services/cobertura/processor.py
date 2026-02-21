"""
Procesador de datos de cobertura.

Transforma los datos crudos de cobertura en formato
listo para generar reportes Excel.
"""
import pandas as pd


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


def procesar_cobertura(df: pd.DataFrame, columnas_index: list[str]) -> pd.DataFrame:
    """
    Pivotea periodos como columnas para comparar meses lado a lado.

    Args:
        df: DataFrame con columna 'periodo' y datos de cobertura
        columnas_index: Columnas que forman el index del pivot

    Returns:
        DataFrame pivoteado con periodos como columnas
    """
    if df.empty:
        return df

    df = df.copy()
    df["periodo_label"] = df["periodo"].apply(_formatear_periodo)

    pivot = df.pivot_table(
        index=columnas_index,
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
