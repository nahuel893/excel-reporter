"""Agregacion de volumen y cobertura.

La regla que gobierna todo este modulo: **la cobertura se cuenta agrupando por
cliente DENTRO del corte y recien despues filtrando por el umbral**. Agrupar
despues de filtrar cuenta como cubierto a quien compro 5 y devolvio 5.

De ahi se sigue que la cobertura del acumulado NO es la suma de los meses: quien
compra en julio y en agosto es UN cliente en el acumulado, no dos. En cambio SI
es aditiva entre sucursales, porque la clave del cliente es compuesta
``(id_cliente, id_sucursal)`` y el mismo numero en dos sucursales son dos
clientes distintos.
"""
from __future__ import annotations

import pandas as pd

from .constants import UMBRAL_COBERTURA

CLAVE_CLIENTE = ["id_sucursal", "id_cliente"]


def clientes_cubiertos(ventas: pd.DataFrame, umbral: float = UMBRAL_COBERTURA) -> int:
    """Cuenta clientes distintos cubiertos en el corte que se le pase.

    `ventas` ya viene recortado a la dimension que se quiera medir (un mes, una
    marca, una sucursal, o la ventana entera). Aca solo se totaliza por cliente
    y se filtra.
    """
    if ventas.empty:
        return 0
    neto = ventas.groupby(CLAVE_CLIENTE, as_index=False)["bultos"].sum()
    return int((neto["bultos"] > umbral).sum())


def _medidas(ventas: pd.DataFrame) -> dict[str, float | int]:
    """Bultos, hectolitros y cobertura de un corte."""
    if ventas.empty:
        return {"bultos": 0.0, "hectolitros": 0.0, "cobertura": 0}
    return {
        # Los bultos y los HL SI se suman: son medidas aditivas.
        "bultos": float(ventas["bultos"].sum()),
        "hectolitros": float(ventas["hectolitros"].sum()),
        "cobertura": clientes_cubiertos(ventas),
    }


def meses_con_movimiento(ventas: pd.DataFrame) -> list[str]:
    """Meses de la ventana que tienen al menos un registro, en orden.

    Un mes sin ninguna venta no se dibuja: tres columnas en cero en una imagen
    se leen como un error del informe, no como 'el generico todavia no existia'.
    Eso ultimo va en el subtitulo, que es donde se puede explicar.
    """
    if ventas.empty:
        return []
    return sorted(ventas["mes"].unique())


def construir_tabla(
    ventas: pd.DataFrame,
    padron: pd.DataFrame,
    dimension: str = "des_sucursal",
) -> pd.DataFrame:
    """Una fila por valor de `dimension`, con un bloque de medidas por mes mas
    el acumulado de la ventana completa.

    `padron` solo se usa cuando la dimension es la sucursal: el padron es de
    clientes, no de marcas, asi que preguntar "que porcentaje del padron compro
    la marca X" solo tiene sentido contra el total de la sucursal.

    Returns:
        DataFrame con columnas ``[<dimension>, bultos_<mes>, hl_<mes>,
        cob_<mes>, ..., bultos_acum, hl_acum, cob_acum, padron, pct_padron]``.
        La ultima fila es el TOTAL, cuya cobertura acumulada se recalcula sobre
        el corte completo en vez de sumar la columna.
    """
    meses = meses_con_movimiento(ventas)
    if ventas.empty:
        return pd.DataFrame()

    padron_por_suc = (
        dict(zip(padron["id_sucursal"], padron["padron"]))
        if not padron.empty and "id_sucursal" in padron
        else {}
    )

    filas: list[dict] = []
    for valor, grupo in ventas.groupby(dimension, sort=False):
        fila: dict = {dimension: valor}
        for mes in meses:
            m = _medidas(grupo[grupo["mes"] == mes])
            fila[f"bultos_{mes}"] = m["bultos"]
            fila[f"hl_{mes}"] = m["hectolitros"]
            fila[f"cob_{mes}"] = m["cobertura"]

        # Acumulado: se mide sobre la ventana ENTERA, no se suman los meses.
        acum = _medidas(grupo)
        fila["bultos_acum"] = acum["bultos"]
        fila["hl_acum"] = acum["hectolitros"]
        fila["cob_acum"] = acum["cobertura"]

        if dimension == "des_sucursal":
            id_suc = int(grupo["id_sucursal"].iloc[0])
            base = padron_por_suc.get(id_suc, 0)
            fila["padron"] = base
            fila["pct_padron"] = (acum["cobertura"] / base) if base else 0.0

        filas.append(fila)

    tabla = pd.DataFrame(filas).sort_values("bultos_acum", ascending=False)
    return tabla.reset_index(drop=True)


def fila_total(ventas: pd.DataFrame, padron: pd.DataFrame, dimension: str) -> dict:
    """TOTAL GENERAL, recalculado sobre el corte completo.

    Los bultos y los HL coinciden con la suma de la columna. La cobertura NO
    siempre: entre sucursales es aditiva, pero entre marcas el mismo cliente
    compra varias y sumarlas lo cuenta dos veces. Recalcular sirve para las dos.
    """
    meses = meses_con_movimiento(ventas)
    fila: dict = {dimension: "TOTAL GENERAL"}
    for mes in meses:
        m = _medidas(ventas[ventas["mes"] == mes])
        fila[f"bultos_{mes}"] = m["bultos"]
        fila[f"hl_{mes}"] = m["hectolitros"]
        fila[f"cob_{mes}"] = m["cobertura"]

    acum = _medidas(ventas)
    fila["bultos_acum"] = acum["bultos"]
    fila["hl_acum"] = acum["hectolitros"]
    fila["cob_acum"] = acum["cobertura"]

    if dimension == "des_sucursal":
        sucursales = set(ventas["id_sucursal"].unique())
        base = int(padron[padron["id_sucursal"].isin(sucursales)]["padron"].sum()) if not padron.empty else 0
        fila["padron"] = base
        fila["pct_padron"] = (acum["cobertura"] / base) if base else 0.0

    return fila


def construir_bloques(
    ventas: pd.DataFrame,
    dimension_bloque: str = "des_sucursal",
    dimension_fila: str = "marca",
) -> list[tuple[str, pd.DataFrame, dict]]:
    """Un bloque por sucursal, con sus marcas adentro y un subtotal al pie.

    Solo se listan las marcas que esa sucursal efectivamente vendio: una tabla
    de 12 sucursales x 20 marcas es mayormente ceros, y los ceros tapan lo poco
    que hay. Que marca falto donde se responde en la matriz, que para eso esta.

    El subtotal del bloque **recalcula** la cobertura sobre el corte de la
    sucursal entera. Sumar las marcas contaria dos veces al cliente que compro
    ABSOLUT y CHIVAS.

    Returns:
        Lista de ``(etiqueta_bloque, filas, subtotal)`` ordenada por volumen
        del bloque, de mayor a menor.
    """
    if ventas.empty:
        return []

    orden = (
        ventas.groupby(dimension_bloque)["bultos"].sum().sort_values(ascending=False).index
    )
    bloques: list[tuple[str, pd.DataFrame, dict]] = []
    for etiqueta in orden:
        grupo = ventas[ventas[dimension_bloque] == etiqueta]
        filas = construir_tabla(grupo, pd.DataFrame(), dimension=dimension_fila)
        subtotal = fila_total(grupo, pd.DataFrame(), dimension_fila)
        subtotal[dimension_fila] = f"TOTAL {etiqueta}"
        bloques.append((str(etiqueta), filas, subtotal))
    return bloques


def matriz_sucursal_marca(ventas: pd.DataFrame, medida: str = "bultos") -> pd.DataFrame:
    """Matriz sucursal x marca de la ventana completa.

    Responde "que marca entro donde": una marca con cero en media tabla es una
    marca que todavia no se distribuye, no una que se vende mal.
    """
    if ventas.empty:
        return pd.DataFrame()
    matriz = ventas.pivot_table(
        index="des_sucursal", columns="marca", values=medida, aggfunc="sum", fill_value=0.0
    )
    matriz = matriz.loc[matriz.sum(axis=1).sort_values(ascending=False).index]
    return matriz[matriz.sum().sort_values(ascending=False).index]
