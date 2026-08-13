"""Constantes del informe de quesos LA HUERTA."""
from __future__ import annotations

MARCA = "LA HUERTA"

MESES_CORTOS: tuple[str, ...] = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
)

# El factor sale de un xlsx exportado a mano: id_articulo -> kg por unidad.
#
# OJO con el encabezado del archivo: dice "PESO PROMEDIO POR UNIDAD EN GRAMOS"
# pero los valores estan en KILOS (3.8 para una barra de queso). La columna de
# gramos es la de al lado (3800).
#
# Y `cantidades_total` de estos articulos ya viene en UNIDADES, no en cajas: la
# columna "UNIDADES POR CAJA/BULTO" del archivo NO entra en la cuenta.
# Verificado contra la planilla del proveedor: enero-2025, 370 x peso_unidad da
# los 74,14 kg exactos; multiplicando ademas por unidades daria 632,63.
COL_CODIGO = 1
COL_PESO_KG = 2
