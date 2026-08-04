"""Logica pura del incentivo preventa SALTA.

La cobertura de este informe usa umbral **0.5 bultos**, no el `> 0` por defecto
del resto del proyecto: el negocio quiere dejar afuera al pdv de compromiso que
se lleva una o dos botellas de un pack de doce. El umbral es de ESTE informe y
no se hereda a ningun otro.
"""
import calendar
from datetime import date

import pandas as pd

# Media caja. Ver el docstring del modulo.
UMBRAL_BULTOS = 0.5

_CLIENTE_KEY = ["id_cliente", "id_sucursal"]


def ventana_del_mes(mes: str, hasta: str | None = None) -> tuple[str, str]:
    """Rango [desde, hasta] del mes 'YYYY-MM', recortado por `hasta` si aplica.

    Un mes cerrado devuelve el mes entero; el mes en curso se corta en `hasta`
    para no pedirle a la base dias que todavia no existen.
    """
    anio, m = (int(x) for x in mes.split("-"))
    desde = date(anio, m, 1)
    fin = date(anio, m, calendar.monthrange(anio, m)[1])
    if hasta:
        tope = date.fromisoformat(hasta)
        fin = min(fin, tope)
    return desde.isoformat(), fin.isoformat()


def mes_ya_empezo(mes: str, hoy: str) -> bool:
    """True si el mes del bloque ya arranco a la fecha `hoy`.

    Un bloque cuyo mes todavia no llego se deja EN BLANCO, no en cero: un cero
    se lee como "no vendio nada" y pintaria el semaforo en rojo antes de tiempo.
    """
    return mes <= hoy[:7]


def contar_cobertura(
    df: pd.DataFrame, sabor: str, calibre: str, umbral: float = UMBRAL_BULTOS
) -> dict[str, int]:
    """Clientes distintos por preventista que llegan al umbral en ese corte.

    Se totaliza por cliente DENTRO del corte (sabor + calibre) y recien despues
    se filtra. Agrupar antes de filtrar es lo que hace que un cliente cuya
    devolucion cancela la compra quede afuera, y que uno que llego al umbral en
    varias compras chicas quede adentro.
    """
    if df.empty:
        return {}
    d = df[(df["sabor"] == sabor) & (df["calibre"] == calibre)]
    if d.empty:
        return {}
    neto = d.groupby(_CLIENTE_KEY + ["preventista"], as_index=False)["bultos"].sum()
    return neto[neto["bultos"] >= umbral].groupby("preventista").size().to_dict()


def cobertura_total(
    df: pd.DataFrame, sabor: str, calibre: str, umbral: float = UMBRAL_BULTOS
) -> int:
    """Clientes distintos del corte, sin abrir por preventista.

    Se cuenta desde el grano y no sumando los preventistas. En la practica dan
    igual porque cada cliente pertenece a una sola ruta, pero contar desde el
    grano no depende de que eso siga siendo cierto.
    """
    if df.empty:
        return 0
    d = df[(df["sabor"] == sabor) & (df["calibre"] == calibre)]
    if d.empty:
        return 0
    neto = d.groupby(_CLIENTE_KEY, as_index=False)["bultos"].sum()
    return int((neto["bultos"] >= umbral).sum())
