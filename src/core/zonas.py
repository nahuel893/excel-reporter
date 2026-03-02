"""
zonas.py - Logica compartida para zonas virtuales.

Contiene funciones para aplicar y expandir zonas virtuales definidas en
ZONAS_VIRTUALES de config/settings.py.
"""
import pandas as pd

from config.settings import ZONAS_VIRTUALES


def aplicar_zonas_virtuales(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renombra sucursal en filas que pertenecen a zonas virtuales segun id_ruta.

    Para cada zona virtual definida en ZONAS_VIRTUALES, las filas cuya sucursal
    coincide con sucursal_real y cuyo id_ruta esta en la lista de rutas se renombran.
    Luego elimina la columna id_ruta y reagrupa los datos.

    Args:
        df: DataFrame con columnas 'sucursal' e 'id_ruta'

    Returns:
        DataFrame sin columna id_ruta, con sucursales renombradas
    """
    if "id_ruta" not in df.columns:
        return df

    df = df.copy()
    for zona_nombre, zona_config in ZONAS_VIRTUALES.items():
        mask = (
            (df["sucursal"] == zona_config["sucursal_real"])
            & (df["id_ruta"].isin(zona_config["rutas"]))
        )
        df.loc[mask, "sucursal"] = zona_nombre

    df = df.drop(columns=["id_ruta"])

    # Reagrupar porque una misma (sucursal, generico, marca, fecha) puede tener
    # multiples filas de distintas rutas que ahora comparten la misma sucursal
    cols_grupo = [c for c in df.columns if c not in ("cantidad", "cantidad_htls", "monto")]
    if all(c in df.columns for c in ("cantidad", "cantidad_htls", "monto")):
        df = df.groupby(cols_grupo, as_index=False, dropna=False).sum()
    elif "clientes_compradores" in df.columns:
        cols_grupo = [c for c in df.columns if c not in ("clientes_compradores", "volumen_total")]
        df = df.groupby(cols_grupo, as_index=False, dropna=False).sum()

    return df


def expandir_sucursales(sucursales_list: list[str]) -> list[str]:
    """
    Expande sucursales reales a incluir sus zonas virtuales.

    Si un supervisor tiene 'CASA CENTRAL', se agrega 'VALLE SALTA' automaticamente.
    """
    expandidas = list(sucursales_list)
    for zona_nombre, zona_config in ZONAS_VIRTUALES.items():
        if zona_config["sucursal_real"] in expandidas and zona_nombre not in expandidas:
            expandidas.append(zona_nombre)
    return expandidas
