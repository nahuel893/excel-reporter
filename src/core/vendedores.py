"""Preventistas que cambiaron de nombre conservando su id_vendedor.

`gold.dim_vendedor` es SCD tipo 1: cuando a un preventista le cambian el nombre,
el maestro pisa el anterior y no queda rastro. Pero varios insumos nuestros
matchean por TEXTO — el xlsx de objetivos del incentivo, el mapa curado de
supervisores — y esos siguen con el nombre viejo hasta que alguien los edita.

Mientras tanto el cruce falla en silencio: la fila aparece en el informe con el
nombre viejo y TODO en cero, que es peor que si no apareciera. Asi salio el
incentivo SALTA con "DARIO LUPATY" en 0,0% y el de FULL SPORT con el preventista
sin supervisor.

Traducir aca evita editar archivos que mantiene otra persona a mano.
"""
from __future__ import annotations

# nombre viejo -> nombre actual en dim_vendedor.des_vendedor
RENOMBRES: dict[str, str] = {
    # id_vendedor 11, CASA CENTRAL. Confirmado contra dim_vendedor el 2026-08-12.
    "DARIO LUPATY": "LUCIANO GUZMAN",
}


def nombre_actual(nombre: str | None) -> str:
    """Devuelve el nombre vigente del preventista.

    El match es case-insensitive y sin espacios de sobra, pero lo que se
    devuelve conserva el texto original cuando no hay renombre: quien llama
    decide si normalizar o no.
    """
    if nombre is None:
        return ""
    limpio = str(nombre).strip()
    return RENOMBRES.get(limpio.upper(), limpio)
