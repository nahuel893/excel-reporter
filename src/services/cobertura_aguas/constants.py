"""Marca taxonomy for the aguas coverage report.

The five marcas below are the whole of the AGUAS DANONE generico. FULL SPORT is
one of them but belongs to NEITHER group: it is an isotonic drink, not a
flavoured water. Keeping it out of AGUA SABORIZADA is a deliberate business
call, not an oversight.
"""
from __future__ import annotations

from dataclasses import dataclass

MARCAS_MINERAL: tuple[str, ...] = ("VILLA DEL SUR", "VILLAVICENCIO")
MARCAS_SABORIZADA: tuple[str, ...] = ("LEVITE", "BRIO")
MARCAS_OTRAS: tuple[str, ...] = ("FULL SPORT",)

MARCAS_AGUAS: tuple[str, ...] = MARCAS_MINERAL + MARCAS_SABORIZADA + MARCAS_OTRAS

GENERICO_AGUAS = "AGUAS DANONE"
TOTAL_AGUAS = "TOTAL AGUAS"

# Fuerza de ventas de preventa. Filtrar por ella es lo que hace que el calculo
# reproduzca `gold.cob_sucursal_marca` exacto: sin el filtro entran movimientos
# con `id_vendedor = 0` (vendedor placeholder sin ficha en dim_vendedor).
ID_FUERZA_VENTAS_PREVENTA = 1

ID_CASA_CENTRAL = 1

# Rutas que NO son preventa y por lo tanto quedan fuera del universo del informe.
# Se expresan con la clave COMPUESTA (id_sucursal, id_ruta) porque `id_ruta` se
# reusa entre sucursales; `None` significa "en todas las sucursales".
#
#   ruta 100 -> DIRECTA, en las 11 sucursales que la tienen
#   ruta 200 -> CERVECERA / VENDEDOR CHOPERAS, solo en CASA CENTRAL
#
# La MISMA exclusion se aplica a la cobertura y al padron. Si se aplicara solo a
# una de las dos, el peso sobre padron mediria un numerador y un denominador de
# universos distintos y no significaria nada. Sacan 90 clientes de la cobertura
# pero 2.398 del padron (el 15 %), asi que la asimetria es grande.
RUTAS_EXCLUIDAS: tuple[tuple[int | None, int], ...] = (
    (None, 100),
    (ID_CASA_CENTRAL, 200),
)


@dataclass(frozen=True)
class Concepto:
    """Una fila del informe: una marca sola, un grupo de marcas, o el total.

    `marcas` es el conjunto sobre el que se cuentan clientes distintos. Para un
    grupo eso es la UNION de sus marcas, nunca la suma de sus coberturas.
    """
    etiqueta: str
    tipo: str  # "marca" | "grupo" | "total"
    marcas: tuple[str, ...]


# Orden de lectura: cada familia con su subtotal debajo, y el total al final.
CONCEPTOS: tuple[Concepto, ...] = (
    *(Concepto(m, "marca", (m,)) for m in MARCAS_MINERAL),
    Concepto("AGUA MINERAL", "grupo", MARCAS_MINERAL),
    *(Concepto(m, "marca", (m,)) for m in MARCAS_SABORIZADA),
    Concepto("AGUA SABORIZADA", "grupo", MARCAS_SABORIZADA),
    *(Concepto(m, "marca", (m,)) for m in MARCAS_OTRAS),
    Concepto(TOTAL_AGUAS, "total", MARCAS_AGUAS),
)
