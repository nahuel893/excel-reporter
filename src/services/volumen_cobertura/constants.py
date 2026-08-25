"""Constantes del informe de volumen y cobertura por sucursal."""
from __future__ import annotations

# Preventa. Es el filtro que hace que el conteo desde `fact_ventas` reproduzca
# `gold.cob_sucursal_*` exacto; sin el entran movimientos con id_vendedor = 0.
ID_FUERZA_VENTAS_PREVENTA = 1

ID_CASA_CENTRAL = 1

# Mismo conjunto que usa cobertura-aguas. DIRECTA (100) no es un preventista:
# son entregas sin visita, y contarlas infla la cobertura y el padron con
# clientes que ninguna ruta persigue. VENDEDOR CHOPERAS (200) solo existe en
# CASA CENTRAL.
# DIRECTA en todas las sucursales. Se saca por separado porque es la unica que
# el informe puede volver a meter (filtro `incluir_directa`).
RUTA_DIRECTA: tuple[int | None, int] = (None, 100)

RUTAS_EXCLUIDAS: tuple[tuple[int | None, int], ...] = (
    RUTA_DIRECTA,
    (ID_CASA_CENTRAL, 200),
)

# Umbral de cobertura: un cliente esta cubierto si su NETO en el corte supera
# esto. Se aplica DESPUES de totalizar por cliente dentro del corte.
UMBRAL_COBERTURA = 0.0

ETIQUETA_TOTAL = "TOTAL GENERAL"

MESES_ES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
}


def etiqueta_mes(mes: str) -> str:
    """'2026-07' -> 'Jul 26'."""
    anio, num = mes.split("-")
    return f"{MESES_ES[int(num)]} {anio[2:]}"
