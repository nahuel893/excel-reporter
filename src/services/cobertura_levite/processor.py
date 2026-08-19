"""Processor for Levite coverage report by caliber.

Categorizes articles by caliber directly from article descriptions (`des_articulo`)
rather than relying on database metadata (`calibre`).
Calculates coverage and volumes per client, branch, and caliber.
"""
from __future__ import annotations

import re
import pandas as pd


# Canonical caliber ordering
CALIBRE_ORDER = ["300cc", "500cc", "575cc", "600cc", "1000cc", "1350cc", "1500cc", "2000cc", "2250cc", "2500cc"]


def extraer_calibre(descripcion: str | None) -> str:
    """Extrae el calibre normalizado a partir de la descripcion del articulo.
    
    Busca patrones de empaque como '1500*6', '500*12', '2250*6', '1000*6', etc.
    o menciones directas del volumen en centimetros cubicos.
    """
    if not descripcion:
        return "OTRO"
    
    desc = descripcion.upper().strip()
    
    # Patron principal: numero antes del multiplicador de bulto (ej: 1500*6, 500*12, 2250*6)
    m = re.search(r"(\d+)\s*\*\s*\d+", desc)
    if m:
        val = int(m.group(1))
        return f"{val}cc"
    
    # Patron secundario: volumen explicito en la descripcion
    m2 = re.search(r"\b(300|500|575|600|1000|1350|1500|2000|2250|2500)\b", desc)
    if m2:
        return f"{m2.group(1)}cc"
    
    return "OTRO"


def ordenar_calibres(calibres: list[str]) -> list[str]:
    """Ordena una lista de calibres de menor a mayor volumen."""
    def _clave(c: str) -> int:
        num = re.sub(r"[^\d]", "", c)
        return int(num) if num else 99999
    return sorted(calibres, key=_clave)


def procesar_cobertura_sucursal_calibre(
    df_ventas: pd.DataFrame,
    df_padron: pd.DataFrame,
    calibres_activos: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Procesa la matriz de cobertura por sucursal y calibre, y el resumen consolidado.
    
    Args:
        df_ventas: Ventas con columnas [id_sucursal, sucursal, id_cliente, calibre, id_articulo, bultos].
        df_padron: Padron activo con columnas [id_sucursal, sucursal, padron].
        calibres_activos: Lista ordenada de calibres presentes en el periodo.
        
    Returns:
        tuple (df_matriz_sucursales, df_resumen_calibres)
    """
    # 1. Totalizar por cliente y calibre
    df_cli_cal = (
        df_ventas.groupby(["id_sucursal", "sucursal", "id_cliente", "calibre"], as_index=False)["bultos"]
        .sum()
    )
    df_cli_cal = df_cli_cal[df_cli_cal["bultos"] > 0]
    
    # 2. Totalizar por cliente en todo Levite
    df_cli_tot = (
        df_ventas.groupby(["id_sucursal", "sucursal", "id_cliente"], as_index=False)["bultos"]
        .sum()
    )
    df_cli_tot = df_cli_tot[df_cli_tot["bultos"] > 0]
    
    total_padron_gral = int(df_padron["padron"].sum())
    total_cob_gral = int(df_cli_tot.groupby(["id_sucursal", "id_cliente"]).ngroups)
    total_vol_gral = float(df_cli_tot["bultos"].sum())
    
    # 3. Filas por sucursal
    filas_suc = []
    for _, r_pad in df_padron.sort_values("sucursal").iterrows():
        id_suc = r_pad["id_sucursal"]
        nom_suc = r_pad["sucursal"]
        pad = int(r_pad["padron"])
        
        suc_cal = df_cli_cal[df_cli_cal["id_sucursal"] == id_suc]
        suc_tot = df_cli_tot[df_cli_tot["id_sucursal"] == id_suc]
        
        cob_tot = int(suc_tot["id_cliente"].nunique())
        vol_tot = float(suc_tot["bultos"].sum())
        
        fila = {
            "id_sucursal": id_suc,
            "sucursal": nom_suc,
            "padron": pad,
        }
        
        for cal in calibres_activos:
            en_cal = suc_cal[suc_cal["calibre"] == cal]
            cob_cal = int(en_cal["id_cliente"].nunique())
            vol_cal = float(en_cal["bultos"].sum())
            fila[f"cob_{cal}"] = cob_cal
            fila[f"pct_{cal}"] = (cob_cal / pad) if pad > 0 else 0.0
            fila[f"vol_{cal}"] = vol_cal
            
        fila["cob_total"] = cob_tot
        fila["pct_cob_total"] = (cob_tot / pad) if pad > 0 else 0.0
        fila["vol_total"] = vol_tot
        fila["es_total_general"] = False
        filas_suc.append(fila)
        
    # Fila TOTAL GENERAL
    fila_tg = {
        "id_sucursal": None,
        "sucursal": "TOTAL GENERAL",
        "padron": total_padron_gral,
    }
    for cal in calibres_activos:
        en_cal = df_cli_cal[df_cli_cal["calibre"] == cal]
        cob_cal = int(en_cal.groupby(["id_sucursal", "id_cliente"]).ngroups)
        vol_cal = float(en_cal["bultos"].sum())
        fila_tg[f"cob_{cal}"] = cob_cal
        fila_tg[f"pct_{cal}"] = (cob_cal / total_padron_gral) if total_padron_gral > 0 else 0.0
        fila_tg[f"vol_{cal}"] = vol_cal
        
    fila_tg["cob_total"] = total_cob_gral
    fila_tg["pct_cob_total"] = (total_cob_gral / total_padron_gral) if total_padron_gral > 0 else 0.0
    fila_tg["vol_total"] = total_vol_gral
    fila_tg["es_total_general"] = True
    filas_suc.append(fila_tg)
    
    df_matriz = pd.DataFrame(filas_suc)
    
    # 4. Resumen consolidado por calibre
    filas_resumen_cal = []
    for cal in calibres_activos:
        en_cal = df_cli_cal[df_cli_cal["calibre"] == cal]
        articulos_activos = int(df_ventas[df_ventas["calibre"] == cal]["id_articulo"].nunique())
        cob_cal = int(en_cal.groupby(["id_sucursal", "id_cliente"]).ngroups)
        vol_cal = float(en_cal["bultos"].sum())
        
        filas_resumen_cal.append({
            "calibre": cal,
            "articulos": articulos_activos,
            "cobertura": cob_cal,
            "pct_penetracion_levite": (cob_cal / total_cob_gral) if total_cob_gral > 0 else 0.0,
            "pct_cobertura_padron": (cob_cal / total_padron_gral) if total_padron_gral > 0 else 0.0,
            "volumen_bultos": vol_cal,
            "pct_mix_volumen": (vol_cal / total_vol_gral) if total_vol_gral > 0 else 0.0,
            "drop_size": (vol_cal / cob_cal) if cob_cal > 0 else 0.0,
        })
        
    # Fila total resumen
    filas_resumen_cal.append({
        "calibre": "TOTAL LEVITE",
        "articulos": int(df_ventas["id_articulo"].nunique()),
        "cobertura": total_cob_gral,
        "pct_penetracion_levite": 1.0,
        "pct_cobertura_padron": (total_cob_gral / total_padron_gral) if total_padron_gral > 0 else 0.0,
        "volumen_bultos": total_vol_gral,
        "pct_mix_volumen": 1.0,
        "drop_size": (total_vol_gral / total_cob_gral) if total_cob_gral > 0 else 0.0,
    })
    
    df_resumen_cal = pd.DataFrame(filas_resumen_cal)
    
    return df_matriz, df_resumen_cal


def procesar_clientes_compradores(
    df_ventas: pd.DataFrame,
    calibres_activos: list[str],
) -> pd.DataFrame:
    """Construye el detalle cliente por cliente con los volumenes por calibre en columnas.
    
    Args:
        df_ventas: Ventas agrupadas por [id_sucursal, sucursal, id_cliente, cliente, id_ruta, vendedor, calibre, bultos].
        calibres_activos: Lista ordenada de calibres presentes en el periodo.
        
    Returns:
        DataFrame con una fila por cliente y columnas:
        [id_sucursal, sucursal, id_cliente, cliente, id_ruta, vendedor, <calibres...>, total_bultos, calibres_comprados]
    """
    if df_ventas.empty:
        columnas = ["id_sucursal", "sucursal", "id_cliente", "cliente", "id_ruta", "vendedor"] + calibres_activos + ["total_bultos", "calibres_comprados"]
        return pd.DataFrame(columns=columnas)
        
    piv = df_ventas.pivot_table(
        index=["id_sucursal", "sucursal", "id_cliente", "cliente", "id_ruta", "vendedor"],
        columns="calibre",
        values="bultos",
        aggfunc="sum",
        fill_value=0.0
    ).reset_index()
    piv.columns.name = None
    
    # Asegurar que todos los calibres esten presentes
    for cal in calibres_activos:
        if cal not in piv.columns:
            piv[cal] = 0.0
            
    piv["total_bultos"] = piv[calibres_activos].sum(axis=1)
    # Filtrar solo clientes con compra neta positiva en el periodo
    piv = piv[piv["total_bultos"] > 0].copy()
    piv["calibres_comprados"] = (piv[calibres_activos] > 0).sum(axis=1)
    
    # Ordenar por sucursal, ruta y total bultos descendente
    piv.sort_values(by=["sucursal", "id_ruta", "total_bultos"], ascending=[True, True, False], inplace=True)
    
    columnas_orden = ["id_sucursal", "sucursal", "id_cliente", "cliente", "id_ruta", "vendedor"] + calibres_activos + ["total_bultos", "calibres_comprados"]
    return piv[columnas_orden].reset_index(drop=True)


# --- Matriz calibre x marca -------------------------------------------------

# Categorias comerciales del universo de aguas. Se reusan las de
# cobertura-aguas para que los dos informes digan lo mismo: FULL SPORT es
# ISOTONICA y NO entra en agua saborizada, aunque sume al total.
CATEGORIAS: list[tuple[str, tuple[str, ...]]] = [
    ("AGUA MINERAL", ("VILLA DEL SUR", "VILLAVICENCIO")),
    ("AGUA SABORIZADA", ("LEVITE", "BRIO")),
    ("ISOTONICA", ("FULL SPORT",)),
]

CLAVE_CLIENTE = ["id_sucursal", "id_cliente"]


def _cubiertos(df: pd.DataFrame, umbral: float = 0.0) -> int:
    """Clientes distintos con neto > umbral en el corte que se le pase.

    Se totaliza por cliente DENTRO del corte y recien despues se filtra: al
    reves, quien compro 5 y devolvio 5 quedaria contado como cubierto.
    """
    if df.empty:
        return 0
    neto = df.groupby(CLAVE_CLIENTE, as_index=False)["bultos"].sum()
    return int((neto["bultos"] > umbral).sum())


def matriz_calibre_marca(
    df_ventas: pd.DataFrame,
    categorias: list[tuple[str, tuple[str, ...]]] | None = None,
    umbral: float = 0.0,
) -> tuple[pd.DataFrame, list[tuple[str, list[str]]]]:
    """Cobertura con el CALIBRE en filas y las marcas en columnas.

    Cada celda es la cantidad de clientes DISTINTOS que compraron ese calibre
    de esa marca. La cobertura no es aditiva ni entre calibres ni entre marcas
    —el mismo cliente compra varias—, asi que **ningun total se suma**: la fila
    TOTAL, la columna de cada categoria y el TOTAL AGUAS se recalculan sobre su
    propio corte. Sumar la columna de LEVITE 500cc + 1500cc + 2250cc cuenta dos
    veces al que compro los tres.

    Returns:
        ``(df, bloques)`` donde `df` tiene una fila por calibre mas la fila
        TOTAL, y `bloques` es ``[(categoria, [columnas...])]`` para que la hoja
        sepa como agrupar los encabezados.
    """
    categorias = categorias or CATEGORIAS
    if df_ventas.empty:
        return pd.DataFrame(), []

    presentes = set(df_ventas["marca"].unique())
    bloques: list[tuple[str, list[str]]] = []
    for etiqueta, marcas in categorias:
        # Solo las marcas con movimiento: una columna entera en cero es ruido.
        cols = [m for m in marcas if m in presentes]
        if cols:
            bloques.append((etiqueta, cols))

    calibres = ordenar_calibres([c for c in df_ventas["calibre"].unique()])

    filas = []
    for cal in calibres:
        del_cal = df_ventas[df_ventas["calibre"] == cal]
        fila: dict = {"calibre": cal}
        for etiqueta, cols in bloques:
            for marca in cols:
                fila[marca] = _cubiertos(del_cal[del_cal["marca"] == marca], umbral)
            # Subtotal de categoria: se RECALCULA, no se suman sus marcas.
            fila[f"TOTAL {etiqueta}"] = _cubiertos(
                del_cal[del_cal["marca"].isin(cols)], umbral
            )
        fila["TOTAL AGUAS"] = _cubiertos(del_cal, umbral)
        filas.append(fila)

    # Fila TOTAL: cada celda sobre la ventana entera, sin sumar los calibres.
    total: dict = {"calibre": "TOTAL"}
    for etiqueta, cols in bloques:
        for marca in cols:
            total[marca] = _cubiertos(df_ventas[df_ventas["marca"] == marca], umbral)
        total[f"TOTAL {etiqueta}"] = _cubiertos(
            df_ventas[df_ventas["marca"].isin(cols)], umbral
        )
    total["TOTAL AGUAS"] = _cubiertos(df_ventas, umbral)
    filas.append(total)

    return pd.DataFrame(filas), bloques
