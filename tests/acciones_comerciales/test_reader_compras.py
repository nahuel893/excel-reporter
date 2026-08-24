"""RED tests — S1.5: compras.xls ingestion, legacy BIFF via xlrd (RF-03).

Covers:
  - Encoding-fix read-fidelity: mojibake cells ("RegalÃ­as", "DevoluciÃ³n")
    are re-decoded to the correct text ("Regalías", "Devolución").
  - The literal "/  /" no-date sentinel survives AS-IS (never NaN/NaT).
  - Header at Excel row 4 (pandas header=3).
  - Missing-file abort.

Fixture built programmatically via xlwt (writes real BIFF/.xls). Because
BIFF8 strings are stored as UTF-16LE Unicode (not byte+codepage), writing
the mojibake text directly as the cell VALUE round-trips byte-for-byte
through xlrd — so the fixture can inject the known-bad string directly
without fighting codepage internals, and the test asserts the reader's
fix function converts it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import xlwt

from src.services.acciones_comerciales.readers.compras import (
    COMPRAS_HEADER_ROW,
    read_compras,
)

_BANNER_ROWS = 3  # rows 0-2 (Excel rows 1-3); header at Excel row 4 (xlwt row 3)

_HEADERS = [
    "Fecha", "Comprobante", "Proveedor", "Concepto", "Importe", "Cliente",
]


def _make_compras_fixture(tmp_path: Path) -> Path:
    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("compras")

    for r in range(_BANNER_ROWS):
        ws.write(r, 0, f"banner row {r + 1}")

    header_row = _BANNER_ROWS  # xlwt 0-indexed row 3 -> Excel row 4
    for c, h in enumerate(_HEADERS):
        ws.write(header_row, c, h)

    # Row with mojibake text that the reader must fix.
    ws.write(header_row + 1, 0, "/  /")  # literal no-date sentinel, NOT touched by parsing
    ws.write(header_row + 1, 1, "COMP-001")
    ws.write(header_row + 1, 2, "PROVEEDOR SA")
    ws.write(header_row + 1, 3, "RegalÃ­as")  # mojibake for "Regalías"
    ws.write(header_row + 1, 4, 1000.50)
    ws.write(header_row + 1, 5, "1 - CICSA")

    # A second, clean row (no mojibake) to prove the fix does not corrupt
    # already-correct text.
    ws.write(header_row + 2, 0, "15/07/2026")
    ws.write(header_row + 2, 1, "COMP-002")
    ws.write(header_row + 2, 2, "OTRO PROVEEDOR")
    ws.write(header_row + 2, 3, "DevoluciÃ³n")  # mojibake for "Devolución"
    ws.write(header_row + 2, 4, 2500.75)
    ws.write(header_row + 2, 5, "2 - CICSA")

    path = tmp_path / "compras.xls"
    wb.save(str(path))
    return path


class TestReadCompras:
    def test_header_row_is_excel_row_4(self):
        assert COMPRAS_HEADER_ROW == 3  # pandas 0-indexed header -> Excel row 4

    def test_mojibake_fixed_to_correct_text(self, tmp_path):
        path = _make_compras_fixture(tmp_path)

        df = read_compras(path)

        assert df.iloc[0]["Concepto"] == "Regalías"
        assert df.iloc[1]["Concepto"] == "Devolución"

    def test_literal_no_date_sentinel_preserved_as_string(self, tmp_path):
        """The literal '/  /' sentinel MUST survive as the exact string —
        never converted to NaN/NaT/blank (RF-03, Decision 13)."""
        path = _make_compras_fixture(tmp_path)

        df = read_compras(path)

        value = df.iloc[0]["Fecha"]
        assert value == "/  /"
        assert isinstance(value, str)
        assert not (isinstance(value, float))  # never coerced to NaN (a float)

    def test_normal_date_string_untouched(self, tmp_path):
        path = _make_compras_fixture(tmp_path)

        df = read_compras(path)

        assert df.iloc[1]["Fecha"] == "15/07/2026"

    def test_headers_read_at_correct_row(self, tmp_path):
        path = _make_compras_fixture(tmp_path)

        df = read_compras(path)

        assert list(df.columns) == _HEADERS
        assert len(df) == 2

    def test_missing_file_aborts(self, tmp_path):
        missing = tmp_path / "does_not_exist_compras.xls"

        with pytest.raises(FileNotFoundError):
            read_compras(missing)

    def test_cliente_column_passthrough_not_resolved(self, tmp_path):
        """Cliente (CICSA depot codes) is an opaque pass-through — never
        joined/resolved against dim_cliente."""
        path = _make_compras_fixture(tmp_path)

        df = read_compras(path)

        assert df.iloc[0]["Cliente"] == "1 - CICSA"
        assert df.iloc[1]["Cliente"] == "2 - CICSA"
