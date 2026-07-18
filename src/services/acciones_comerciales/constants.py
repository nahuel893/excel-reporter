"""Exact label / shape specs for the acciones-comerciales pivots and the
derived wapi columns (RF-02, RF-08, RF-09).

Everything here is a byte-for-byte contract: downstream BASE-control display
(S3) and the Phase-2 informe positional paste (S5, RF-15/RF-16) depend on
these exact strings and column orders. In particular:

  * ``COL_PRECIO_FINAL`` keeps its TRAILING SPACE (``"PRECIO FINAL "``) — the
    original engine's header carries it and the paste/lookup targets match on
    the exact string.
  * The pivot value labels (``Suma de ...``) mirror Excel's pivot-field naming
    verbatim (case-sensitive, no variation).
  * ``ACC_GEN`` reserves a BLANK spacer column at position E so the five
    genéricos land at F:J (NOT E:I) when pasted positionally into the informe
    (RF-09 / RF-15). The genérico grand ``Total`` (informe col K, a broken
    ``=SUM(#REF!)``) is OUTSIDE the A:J paste zone and is never emitted here.
"""
from __future__ import annotations

# ── derived wapi column headers (RF-02 enriched contract, RF-04..RF-08) ──
COL_SUCURSAL = "SUCURSAL"
COL_CONCAT = "CONCAT"
COL_PRECIO_FINAL = "PRECIO FINAL "  # trailing space is intentional (engine contract)
COL_MVB = "mvb"
COL_ZONA = "ZONA"
COL_TOTAL2 = "Total2"
COL_DESCUENTO = "Descuento"
COL_TIPO_DESCUENTO = "Tipo Descuento"

# Order the derived columns are appended after the raw 21-column wapi block.
# Mirrors the informe wapi V:AD map MINUS AC (Clientes Reversa), which has no
# RF-04..RF-08 derivation and is preserved as-is by the Phase-2 writer.
DERIVED_WAPI_COLUMNS: list[str] = [
    COL_SUCURSAL,
    COL_CONCAT,
    COL_PRECIO_FINAL,
    COL_MVB,
    COL_ZONA,
    COL_TOTAL2,
    COL_DESCUENTO,
    COL_TIPO_DESCUENTO,
]

# ── mvb 3-tier classifier (RF-06) — case-sensitive FIND substrings ──
# Order matters: first matching tier wins.
MVB_TIERS: list[tuple[str, str]] = [
    ("MVB", "MVB"),
    ("(ESC.)", "ESC"),
    ("EXTRA TASA", "EXTRA TASA"),
]
MVB_DEFAULT = "OTRAS"

# ── Tipo Descuento labels (RF-08) ──
TIPO_DESCUENTO_SIN_CARGO = "SIN CARGO"
TIPO_DESCUENTO_DESCUENTOS = "Descuentos"

# ── genéricos (Calibre) — exact positional order for ACC-GEN F:J ──
GENERICOS_ORDER: list[str] = [
    "CERVEZAS",
    "AGUAS DANONE",
    "VINOS CCU",
    "PERNOD RICARD",
    "SIDRAS Y LICORES",
]

# ── pivot value labels (RF-09) — byte-for-byte Excel pivot-field names ──
LABEL_SUMA_FACT_NETA = "Suma de Facturacion Neta"
LABEL_SUMA_DESCUENTOS = "Suma de Descuentos"
LABEL_SUMA_CAMPO1 = "Suma de Campo1"
LABEL_SUMA_DESCUENTO = "Suma de Descuento"

# ── FACT_NET (aexcel) — rows A:E, values F:H (A:H) ──
FACT_NET_ROW_FIELDS: list[str] = [
    "Sucursal",
    "Código",
    "Descripción_2",
    "Descripción_3",
    "Descripción_12",
]
# source measure columns on the aexcel-equivalent frame
FACT_NET_FACT_NETA_SRC = "Facturacion Neta"
FACT_NET_DESCUENTOS_SRC = "Descuentos"

# ── ART-ACCION (wapi) — rows A:F, value G (A:G) ──
ART_ACCION_ROW_FIELDS: list[str] = [
    "SUCURSAL",
    "Artículo Distribuidora",
    "Descripción",
    "Acción",
    "Descripción Acción",
    "mvb",
]

# ── CLIENTE-FECHA (wapi) — rows A:I, value J (A:J) ──
CLIENTE_FECHA_ROW_FIELDS: list[str] = [
    "Fecha",
    "SUCURSAL",
    "Cod. Cliente",
    "Razón Social",
    "Artículo Distribuidora",
    "Descripción",
    "Calibre",
    "Acción",
    "Descripción Acción",
]

# ── ACC-GEN (wapi) — rows A:D, blank spacer E, genéricos F:J (A:J) ──
ACC_GEN_ROW_FIELDS: list[str] = [
    "SUCURSAL",
    "Acción",
    "Descripción Acción",
    "mvb",
]
# Column field feeding the genérico columns.
ACC_GEN_COLUMN_FIELD = "Calibre"
# The blank spacer column (informe col E). Kept empty so the positional A:J
# paste aligns each genérico under its correct header (RF-09 / RF-15).
ACC_GEN_SPACER_COL = "(en blanco)"
# The genérico measure being summed into each F:J column.
ACC_GEN_VALUE_SRC = COL_DESCUENTO

# ── config-owned sucursal -> supervisor mapping (ZONA, RF-07) ──
ZONA_CONFIG_PATH = "configs/acciones_comerciales_zonas.json"
ZONA_CONFIG_KEY = "sucursal_supervisor"
