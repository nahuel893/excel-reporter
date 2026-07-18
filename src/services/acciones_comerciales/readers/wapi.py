"""wapi.xlsx ingestion — CCU variant only (RF-02).

Reads ONLY the ``Wapi`` sheet (header at Excel row 8 / pandas ``header=7``),
producing the 21-column raw contract. ``Calibre`` IS the business genérico
dimension (5 values: CERVEZAS, AGUAS DANONE, VINOS CCU, PERNOD RICARD,
SIDRAS Y LICORES) — this reader passes it through verbatim, never renaming
or reinterpreting it as a physical size attribute.

FEDESUR (``Wapi_R2``) and BRANCA (``Wapi_Branca``) sheet variants are OUT OF
SCOPE and are never read, even if present in the workbook.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

WAPI_SHEET_NAME = "Wapi"
WAPI_HEADER_ROW = 7  # pandas header index (0-based) -> Excel row 8

# 21-column raw contract, in order (RF-02).
WAPI_RAW_COLUMNS: list[str] = [
    "Fecha",
    "Comprobante",
    "Agrupaciones",
    "Cod. Cliente",
    "Razón Social",
    "Dirección",
    "Artículo CMQ",
    "Descripción",
    "Marca",
    "Calibre",
    "Cantidad",
    "Precio Neto SF",
    "Total",
    "Cantidad Sin Cargo",
    "Descuento %",
    "Descuento $ sobre PN SF",
    "Participación CMQ",
    "Monto A Acreditar",
    "Acción",
    "Descripción Acción",
    "Artículo Distribuidora",
]


def read_wapi(path: str | Path) -> pd.DataFrame:
    """Ingest wapi.xlsx (CCU variant only) — RF-02.

    Reads ONLY the ``Wapi`` sheet (ignores ``Wapi_R2``/``Wapi_Branca`` even
    when present), header at Excel row 8 (pandas ``header=7``), enforcing
    the exact 21-column raw contract (drops any stray trailing columns,
    raises if an expected column is missing — a changed source contract
    must fail loudly, never silently).

    Raises:
        FileNotFoundError: if ``path`` does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"wapi.xlsx no encontrado: {path}")

    df = pd.read_excel(
        path, sheet_name=WAPI_SHEET_NAME, header=WAPI_HEADER_ROW, engine="openpyxl"
    )
    return df[WAPI_RAW_COLUMNS]
