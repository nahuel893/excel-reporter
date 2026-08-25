"""Layout of the INCENTIVO HERNAN workbook (variable mensual / 4% mensual).

Everything here was derived from the workbook itself, not guessed. The three
sources of truth were the tab colours (blue = base data Python must load), the
formulas the report sheets fire at those base sheets, and the pivot table
definitions inside ``xl/pivotTables``.
"""
from __future__ import annotations

from src.core.xlsx_blocks import BLANK, FORMULA, VALUE, ColumnSpec

# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #

# The workbook only ever carried these four. PERNOD RICARD is a CCU generic but
# is outside this incentive, so it is deliberately absent.
GENERICOS = ["CERVEZAS", "AGUAS DANONE", "VINOS CCU", "SIDRAS Y LICORES"]

# The three generics scored in marcas_x_pdv, in the order of columns N, O, P.
GENERICOS_MXPDV = ["CERVEZAS", "AGUAS DANONE", "VINOS CCU"]

# suc!Q:R — the VLOOKUP table behind AX column AD. Four zones.
ZONA_POR_SUCURSAL = {
    "1 - CASA CENTRAL": "SALTA Y VALLE",
    "VALLE SALTA": "SALTA Y VALLE",
    "3 - SUCURSAL CAFAYATE": "SALTA INTERIOR",
    "4 - SUCURSAL JOAQUIN V GONZALEZ": "SALTA INTERIOR",
    "5 - SUCURSAL METAN": "SALTA INTERIOR",
    "16 - SUCURSAL GUEMES": "SALTA INTERIOR",
    "9 - SUCURSAL PERICO": "QUEBRADA",
    "10 - SUCURSAL LIBERTADOR": "QUEBRADA",
    "11 - SUCURSAL MAIMARA": "QUEBRADA",
    "12 - SUCURSAL HUMAHUACA": "QUEBRADA",
    "13 - SUCURSAL ABRA PAMPA": "QUEBRADA",
    "15 - SUCURSAL SAN PEDRO": "QUEBRADA",
    "14 - SUCURSAL LA QUIACA": "QUEBRADA",
    "6 - SUCURSAL ORAN": "RAMAL",
    "7 - SUCURSAL TARTAGAL": "RAMAL",
}

# CASA CENTRAL is split by the client's preventa route, exactly as the workbook
# already had it: these routes report as VALLE SALTA, the rest stay CASA CENTRAL.
# (Route 93 / SUB DISTRIBUIDORES is NOT split out here — the workbook keeps it
# inside CASA CENTRAL, unlike ZONAS_VIRTUALES in config/settings.py.)
VALLE_SALTA_RUTAS = [81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 118, 119, 120, 122]
VALLE_SALTA_LABEL = "VALLE SALTA"
CASA_CENTRAL_ID = 1

# AX column V. The names are pinned here because gold has no source for them:
# ``gold.dim_lista_precio`` is empty and ``dim_cliente.des_lista_precio`` is blank
# for all 28.392 clients. The mapping was recovered by cross-referencing the
# workbook's own AX export against ``dim_cliente.id_lista_precio`` — every id
# resolved to exactly one name. ramal/qbrd/inte read this column to compute the
# wholesale share, matching on the literal strings below.
LISTAS_DE_PRECIO = {
    1: "LISTA SALTA MAYORISTA",
    3: "LISTA SALTA MINORISTA",
    4: "LISTA SALTA ON PREMISE",
    5: "LISTA SALTA AUTOSERVICIOS",
    6: "INTERIOR MAYORISTA",
    7: "INTERIOR MINORISTA",
    8: "INTERIOR ON PREMISE",
    9: "INTERIOR AUTOSERVICIOS",
    11: "SUB DISTRIBUIDORES SALTA CAPIT",
    12: "SUB DISTRIBUIDORES INTERIOR",
}

MARCAS_VILLA = ["VILLAVICENCIO", "VILLA DEL SUR"]
MARCA_VILLA_LABEL = "VILLAVICENCIO Y VILLA DEL SUR"

# Preventa. Coverage tables mix fuerza 1 and 4; the workbook counts preventa only.
ID_FUERZA_VENTAS = 1

# cober_marca keeps every brand the coverage table has EXCEPT these. PERNOD RICARD
# runs its own incentive and never appears in this workbook; SIN MARCA is the
# unbranded bucket. Note this is not "the brands of GENERICOS": FRATELLI BRANCA,
# ENERGIZANTES and SECCO are all in the sheet despite living outside those four
# generics, and a brand can belong to several generics at once.
GENERICOS_EXCLUIDOS_COBERTURA = ["PERNOD RICARD"]
MARCAS_EXCLUIDAS_COBERTURA = ["SIN MARCA"]


# --------------------------------------------------------------------------- #
# AX — the base sales table (Excel table ``aexcel``)
# --------------------------------------------------------------------------- #

SHEET_AX = "AX"
AX_TABLE = "aexcel"

# Only 11 of the 31 columns are read by anything. The other 20 are written as
# empty styled cells so every downstream formula, table column reference and
# pivot field keeps resolving, while the sheet stops carrying dead payload.
#
# Who reads what:
#   C   MAX(AX!C:C) in salta!F1 — the last sale date shown on the report
#   D   pivotTable1 row field (Codigo Cliente)
#   F   SUMIFS criteria in ramal/qbrd/inte + pivot row field
#   M   feeds the COLON DULCE VLOOKUP in AE
#   P   pivotTable1 row field (Descripcion_Marca)
#   T   SUMIFS sum range for the mayorista share
#   V   SUMIFS criteria (price list) for the mayorista share
#   W   SUMIFS criteria (generic) — the most referenced column in the workbook
#   AC  SUMIFS sum range for volume in hectolitres
#   AD  zona, VLOOKUP over suc!Q:R
#   AE  COLON DULCE flag, VLOOKUP over art_colon_dulce!A:C
AX_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("A", BLANK),                                     # Column1
    ColumnSpec("B", BLANK),                                     # Cod. Período
    ColumnSpec("C", VALUE, source="fecha"),                     # Descripcion Período
    ColumnSpec("D", VALUE, source="id_cliente"),                # Codigo Cliente
    ColumnSpec("E", BLANK),                                     # Descripción
    ColumnSpec("F", VALUE, source="sucursal"),                  # Sucursal
    ColumnSpec("G", BLANK),                                     # Ruta
    ColumnSpec("H", BLANK),                                     # Descripcion_Ruta
    ColumnSpec("I", BLANK),                                     # Ramo
    ColumnSpec("J", BLANK),                                     # Descripcion Ramo
    ColumnSpec("K", BLANK),                                     # Vendedor
    ColumnSpec("L", BLANK),                                     # Descripcion Vendedor
    ColumnSpec("M", VALUE, source="id_articulo"),               # Código_Articulo
    ColumnSpec("N", BLANK),                                     # Descripcion_Articulo
    ColumnSpec("O", BLANK),                                     # Marca (código)
    ColumnSpec("P", VALUE, source="marca"),                     # Descripcion_Marca
    ColumnSpec("Q", BLANK),                                     # Precio
    ColumnSpec("R", BLANK),                                     # Bonific
    ColumnSpec("S", BLANK),                                     # Pr Neto
    ColumnSpec("T", VALUE, source="cantidad"),                  # Cantidades Totales
    ColumnSpec("U", BLANK),                                     # Importes Finales
    ColumnSpec("V", VALUE, source="lista_precio"),              # Descripcion lista de precios
    ColumnSpec("W", VALUE, source="generico"),                  # GENERICO
    ColumnSpec("X", BLANK),                                     # Supervisor
    ColumnSpec("Y", BLANK),                                     # htls (factor)
    ColumnSpec("Z", BLANK),                                     # ImporteNetoSinDesc
    ColumnSpec("AA", BLANK),                                    # Bonificacion$
    ColumnSpec("AB", BLANK),                                    # Bonificacion%
    ColumnSpec("AC", VALUE, source="cantidad_htls"),            # Cantidad htls
    ColumnSpec(
        "AD",
        FORMULA,
        formula=f"+VLOOKUP({AX_TABLE}[[#This Row],[Sucursal]],suc!Q:R,2,0)",
    ),
    ColumnSpec(
        "AE",
        FORMULA,
        formula=f"+VLOOKUP({AX_TABLE}[[#This Row],[Código_Articulo]],art_colon_dulce!A:C,3,0)",
    ),
]


# --------------------------------------------------------------------------- #
# Coverage sheets — one row per (sucursal, preventista, ruta, marca|generico)
# --------------------------------------------------------------------------- #

SHEET_COBER_MARCA = "cober_marca"
SHEET_COBER_GEN = "cober_gen"
SHEET_VILLA = "villav y villa sur"

COBER_TABLE = {
    SHEET_COBER_MARCA: "cober_marca",
    SHEET_COBER_GEN: "cober_generico",
    SHEET_VILLA: "Sheet1",
}


def cober_columns(table_name: str, concepto_source: str) -> list[ColumnSpec]:
    """Column plan shared by the three coverage sheets.

    They differ only in the Excel table name their column G formula points at and
    in whether column E holds a brand or a generic.
    """
    return [
        ColumnSpec("A", VALUE, source="orden"),                 # Column1
        ColumnSpec("B", VALUE, source="sucursal"),              # Sucursal
        ColumnSpec("C", VALUE, source="vendedor"),              # Descripcion Vendedor
        ColumnSpec("D", VALUE, source="ruta"),                  # Ruta
        ColumnSpec("E", VALUE, source=concepto_source),         # Descripcion_Marca / GENERICO
        ColumnSpec("F", VALUE, source="clientes"),              # Numero_Clientes
        ColumnSpec(
            "G",
            FORMULA,
            formula=f"+VLOOKUP({table_name}[[#This Row],[Sucursal]],suc!Q:R,2,0)",
        ),
    ]


# --------------------------------------------------------------------------- #
# referencia ma — each branch's share of its zone
# --------------------------------------------------------------------------- #

SHEET_REFERENCIA = "referencia ma"
SHEET_ART_COLON = "art_colon_dulce"
REFERENCIA_TABLE = "Tabla_MXPDV_Cobertura"

# Thirteen branches in a fixed order, and CASA CENTRAL / VALLE SALTA are absent:
# this sheet only feeds ramal, qbrd and inte, which are the interior zones. The
# order matches marcas_x_pdv!R12:R24 and must not be reshuffled — the report
# sheets match on the label, but a reader comparing the blocks side by side
# relies on the rows lining up.
REFERENCIA_SUCURSALES = [
    "3 - SUCURSAL CAFAYATE",
    "4 - SUCURSAL JOAQUIN V GONZALEZ",
    "5 - SUCURSAL METAN",
    "16 - SUCURSAL GUEMES",
    "9 - SUCURSAL PERICO",
    "10 - SUCURSAL LIBERTADOR",
    "11 - SUCURSAL MAIMARA",
    "12 - SUCURSAL HUMAHUACA",
    "13 - SUCURSAL ABRA PAMPA",
    "15 - SUCURSAL SAN PEDRO",
    "14 - SUCURSAL LA QUIACA",
    "6 - SUCURSAL ORAN",
    "7 - SUCURSAL TARTAGAL",
]

# The seven focus brands of the P:V block, as {label written in the sheet: brand
# in gold}. The labels are kept verbatim because qbrd and inte match on them;
# Excel's SUMIFS is case-insensitive, so "Imperial" still finds IMPERIAL, but
# rewriting the label would be a gratuitous change to Nahuel's sheet.
REFERENCIA_MARCAS = {
    "SALTA": "SALTA",
    "VILLAVICENCIO": "VILLAVICENCIO",
    "LEVITE": "LEVITE",
    "O-61": "O-61",
    "Imperial": "IMPERIAL",
    "NORTE": "NORTE",
    "BRIO": "BRIO",
}

REFERENCIA_MARCA_COLON = "COLON DULCE"

# Price lists that count as wholesale for the AD:AN block. Verified against the
# pasted values: SUB DISTRIBUIDORES is NOT wholesale here.
LISTAS_MAYORISTAS = ["LISTA SALTA MAYORISTA", "INTERIOR MAYORISTA"]

REFERENCIA_FIRST_ROW = 2

# Only the percentage columns (G, N, U, AB) are read by anything: ramal, qbrd and
# inte pull them with SUMIFS. The rest is context for whoever opens the sheet.
REFERENCIA_COBERTURA_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("A", VALUE, source="sucursal"),
    ColumnSpec("B", VALUE, source="zona"),
    ColumnSpec("C", VALUE, source="generico"),
    ColumnSpec("D", VALUE, source="marcas_x_pdv"),
    ColumnSpec("E", VALUE, source="total_zona"),
    ColumnSpec("F", VALUE, source="valor"),
    ColumnSpec("G", VALUE, source="participacion"),
]

REFERENCIA_VOLUMEN_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("I", VALUE, source="sucursal"),
    ColumnSpec("J", VALUE, source="zona"),
    ColumnSpec("K", VALUE, source="generico"),
    ColumnSpec("L", VALUE, source="total_zona"),
    ColumnSpec("M", VALUE, source="valor"),
    ColumnSpec("N", VALUE, source="participacion"),
]

REFERENCIA_MARCA_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("P", VALUE, source="sucursal"),
    ColumnSpec("Q", VALUE, source="zona"),
    ColumnSpec("R", VALUE, source="marca"),
    ColumnSpec("S", VALUE, source="total_zona"),
    ColumnSpec("T", VALUE, source="valor"),
    ColumnSpec("U", VALUE, source="participacion"),
]

REFERENCIA_COLON_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("W", VALUE, source="sucursal"),
    ColumnSpec("X", VALUE, source="zona"),
    ColumnSpec("Y", VALUE, source="marca"),
    ColumnSpec("Z", VALUE, source="total_zona"),
    ColumnSpec("AA", VALUE, source="valor"),
    ColumnSpec("AB", VALUE, source="participacion"),
]

REFERENCIA_MAYORISTA_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("AD", VALUE, source="sucursal"),
    ColumnSpec("AE", VALUE, source="zona"),
    ColumnSpec("AF", VALUE, source="generico"),
    ColumnSpec("AG", VALUE, source="volumen_zona"),
    ColumnSpec("AH", VALUE, source="volumen_sucursal"),
    ColumnSpec("AI", VALUE, source="mayorista_zona"),
    ColumnSpec("AJ", VALUE, source="mayorista_sucursal"),
    ColumnSpec("AK", VALUE, source="pct_mayo_zona"),
    ColumnSpec("AL", VALUE, source="pct_participacion"),
    ColumnSpec("AM", VALUE, source="pct_mayo_sucursal"),
]


# --------------------------------------------------------------------------- #
# marcas_x_pdv — brands per point of sale
# --------------------------------------------------------------------------- #

SHEET_MXPDV = "marcas_x_pdv"

# A3:F60803 used to be pivotTable1 over ``aexcel``. Python now writes the same
# grouping (Codigo Cliente x GENERICO x Descripcion_Marca x Sucursal x zona,
# summing Cantidades Totales) straight into the range, so the pivot part is
# dropped from the package to stop it fighting the pasted values.
MXPDV_PIVOT_HEADER_ROW = 3
MXPDV_PIVOT_FIRST_ROW = 4
MXPDV_PIVOT_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("A", VALUE, source="id_cliente"),
    ColumnSpec("B", VALUE, source="generico"),
    ColumnSpec("C", VALUE, source="marca"),
    ColumnSpec("D", VALUE, source="sucursal"),
    ColumnSpec("E", VALUE, source="zona"),
    ColumnSpec("F", VALUE, source="cantidad"),
]

# J3:L — the deduplicated client list the COUNTIFS block walks.
MXPDV_CLIENTES_FIRST_ROW = 3
MXPDV_CLIENTES_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("J", VALUE, source="id_cliente"),
    ColumnSpec("K", VALUE, source="sucursal"),
    ColumnSpec("L", VALUE, source="zona"),
]

# N3:P — was COUNTIFS($A:$A,$J3,$B:$B,N$1,$F:$F,">0"): how many brands of that
# generic the point of sale bought with a positive net. Now a plain value.
MXPDV_CONTEO_FIRST_ROW = 3
MXPDV_CONTEO_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("N", VALUE, source="CERVEZAS"),
    ColumnSpec("O", VALUE, source="AGUAS DANONE"),
    ColumnSpec("P", VALUE, source="VINOS CCU"),
]

# The R:V summary block (zone and branch averages) stays as live formulas: it is
# 50 rows, it is what ramal/qbrd/inte actually read, and leaving it alone keeps
# its shared-formula master intact.
MXPDV_KEEP_FROM_COLUMN = "R"

# Rows 1 and 2 hold the block headers; row 3 doubles as the pivot header row.
MXPDV_PIVOT_TABLE_PART = "xl/pivotTables/pivotTable1.xml"
MXPDV_PIVOT_TABLE_RELS = "xl/pivotTables/_rels/pivotTable1.xml.rels"
