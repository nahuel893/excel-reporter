"""Constantes del reporte Cupo Desagregado Por Ruta.

Todo lo que cambia mes a mes (nuevos vendedores, sucursales, overrides) se
edita aca. Ver docstring de `service.py` para la receta mensual completa.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Archivo fuente (Objetivo <MES> Badie)
# ---------------------------------------------------------------------------
# Columnas del bloque "Objetivo" — el bloque MASTER de cupos por vendedor.
# El bloque de filas 1-44 es un escenario reducido derivado de este; el de
# filas 131-145 es el totalizado por sucursal (informativo, no se distribuye).
SRC_COLS: dict[str, str] = {
    "CERVEZAS": "D", "SALTA": "G", "HEINEKEN": "J", "IMPERIAL": "M",
    "MILLER": "P", "MULTICERVEZA": "S", "AGUA DANONE": "V",
    "FERNET": "Y", "VINOS": "AB", "R2": "AE",
}
SRC_ROW_INI = 66
SRC_ROW_FIN = 109

# ---------------------------------------------------------------------------
# Categorias
# ---------------------------------------------------------------------------
# Orden de las categorias en la salida.
CATEGORIAS = ["CERVEZAS", "SALTA", "HEINEKEN", "IMPERIAL", "MILLER",
              "MULTICERVEZA", "AGUA DANONE", "FERNET", "VINOS", "R2"]

# CERVEZAS es la doble apertura: la suma de las 5 marcas cerveceras.
CERVEZA_MARCAS = ["SALTA", "HEINEKEN", "IMPERIAL", "MILLER", "MULTICERVEZA"]

# Categorias que se distribuyen con historia propia (CERVEZAS se deriva).
CATEGORIAS_DISTRIBUIBLES = [c for c in CATEGORIAS if c != "CERVEZAS"]

# Marcas de dim_articulo agrupadas bajo cada categoria de cerveza.
MARCAS_SALTA = {"SALTA", "SCHNEIDER", "NORTE"}
MARCAS_MULTICERVEZA = {"AMSTEL", "GROLSCH", "IGUANA", "WARSTEINER"}
MARCAS_PROPIAS = {"HEINEKEN", "IMPERIAL", "MILLER"}

# ---------------------------------------------------------------------------
# Sucursales
# ---------------------------------------------------------------------------
# Texto de la columna B del archivo fuente -> id_sucursal en gold.
# CASA CENTRAL (1) queda fuera: tiene su propio circuito de cupos.
SUCURSAL_IDS: dict[str, int] = {
    "CAFAYATE": 3, "JVG": 4, "METAN": 5, "ORAN": 6, "TARTAGAL": 7,
    "PERICO": 9, "LIBERTADOR": 10, "MAIMARA": 11, "HUMAHUACA": 12,
    "ABRA PAMPA": 13, "LA QUIACA": 14, "SAN PEDRO": 15, "GUEMES": 16,
}

SUCURSALES_INCLUIDAS = sorted(SUCURSAL_IDS.values())

# ---------------------------------------------------------------------------
# Overrides de vendedores
# ---------------------------------------------------------------------------
# El nombre del archivo fuente no siempre coincide con des_vendedor en
# dim_vendedor. (nombre_archivo, id_sucursal) -> id_vendedor.
NOMBRE_OVERRIDES: dict[tuple[str, int], int] = {
    ("CRUZ GABRIEL ARNALDO", 14): 167,       # dim dice 'CRUZ GABRIEL'
    ("LAMAS SEBASTIAN", 13): 162,            # dim dice 'LAMAS SEBASTIAN NO USAR'
}

# Vendedores cuyo cupo se carga bajo una sucursal pero cuyas rutas reales
# viven en otra (migraciones). (nombre, id_sucursal_cupo) ->
# [(id_sucursal_historia, id_ruta, etiqueta_a_mostrar)].
RUTAS_OVERRIDE: dict[tuple[str, int], list[tuple[int, int, str]]] = {
    # ABRA PAMPA (13) no vendio nada: LAMAS opera desde LA QUIACA (14).
    ("LAMAS SEBASTIAN", 13): [
        (14, 14, "LAMAS MA-VI"),
        (14, 15, "LAMAS MI-SA"),
        (14, 16, "LAMAS LUN-JUE"),
    ],
}

# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
ETIQUETA_SIN_RUTA = "SIN RUTA ASIGNADA"
ETIQUETA_TOTAL_GENERAL = "TOTAL GENERAL"

# Nombres de mes en mayuscula, 1-indexados (indice 0 sin usar). Se usan para
# resolver la hoja del archivo fuente a partir de la fecha del periodo.
MESES_ES = [
    "", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
]
