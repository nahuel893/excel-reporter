"""Constantes del reporte Descuentos CCU.

LISTA_PRECIO_LABELS: mapa id_lista_precio → descripción. gold.dim_lista_precio
está vacío (sin títulos) y dim_cliente.des_lista_precio viene nulo, así que el
match id→descripción se reconstruyó cruzando el Excel base del ERP
(DESCUENTOS CCU.xlsx, col "Descripcion lista de precios") con
gold.dim_cliente.id_lista_precio por cliente. Ids no mapeados caen a "Lista {id}".
"""

LISTA_PRECIO_LABELS: dict[int, str] = {
    1: "LISTA SALTA MAYORISTA",
    3: "LISTA SALTA MINORISTA",
    4: "LISTA SALTA ON PREMISE",
    5: "LISTA SALTA AUTOSERVICIOS",
    6: "INTERIOR MAYORISTA",
    7: "INTERIOR MINORISTA",
    8: "INTERIOR ON PREMISE",
    9: "INTERIOR AUTOSERVICIOS",
    12: "SUB DISTRIBUIDORES INTERIOR",
}


def label_lista_precio(id_lista: int | float | None) -> str:
    """Devuelve la descripción de la lista, o 'Lista {id}' si no está mapeada."""
    if id_lista is None:
        return "SIN LISTA"
    try:
        idl = int(id_lista)
    except (TypeError, ValueError):
        return "SIN LISTA"
    return LISTA_PRECIO_LABELS.get(idl, f"Lista {idl}")
