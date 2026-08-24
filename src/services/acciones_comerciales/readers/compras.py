"""compras.xls ingestion — legacy BIFF via xlrd, faithful paste (RF-03).

The real compras.xls export is written by legacy/WPS tooling using BIFF
(.xls). Two read-fidelity issues (NOT data-cleaning transforms — Decision
13) must be corrected on read so the emitted text matches what a human
copy-paste from Excel/WPS would show:

1. Mojibake — some cells' bytes decode as UTF-8-read-as-Latin-1 mojibake
   (e.g. "RegalÃ­as" instead of "Regalías"). Fixed via a targeted
   latin-1-encode / utf-8-decode round-trip, applied only where the
   round-trip succeeds (a genuine mojibake string); text that fails the
   round-trip (including already-correct text, in the common case) is left
   untouched.
2. The literal "/  /" no-date sentinel (legacy ERP's "no date" placeholder)
   MUST survive as the literal string "/  /" — never coerced to NaN/NaT.
   This reader never applies date parsing, so it is preserved by
   construction.

The full 32-column A:AF header enumeration (informe paste-target contract)
is a Phase-2 (S5 writer) concern; this reader is a faithful, header-agnostic
paste of whatever columns exist at the header row (Decision 13: plain
faithful paste — no column renaming/reordering).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

COMPRAS_HEADER_ROW = 3  # pandas header index (0-based) -> Excel row 4


def _fix_mojibake(value):
    """Re-decode a single cell value if it looks like UTF-8-as-Latin-1
    mojibake. Non-strings and strings that fail the round-trip pass through
    unchanged (never raises)."""
    if not isinstance(value, str):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def read_compras(path: str | Path) -> pd.DataFrame:
    """Ingest compras.xls (BIFF, legacy) — RF-03.

    Reads the first sheet with header at Excel row 4 (pandas ``header=3``),
    applies the mojibake read-fidelity fix to every text cell, and leaves
    the literal "/  /" no-date sentinel untouched (no date parsing is ever
    applied — read fidelity only, Decision 13).

    Raises:
        FileNotFoundError: if ``path`` does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"compras.xls no encontrado: {path}")

    df = pd.read_excel(path, sheet_name=0, header=COMPRAS_HEADER_ROW, engine="xlrd")
    return df.map(_fix_mojibake)
