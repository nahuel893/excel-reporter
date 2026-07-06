"""Surgical worksheet-data replacement for xlsx files that openpyxl cannot
round-trip.

Some engine workbooks embed huge pivot caches (hundreds of MB uncompressed).
``openpyxl.load_workbook`` parses those caches into Python objects, which makes a
load->save round-trip take minutes and risks dropping the pivot tables entirely.

This module rewrites ONLY the target worksheets' XML and their associated Excel
table refs, copying every other zip part byte-for-byte. Pivot caches, pivot
tables, charts, styles and shared strings survive untouched.

Design constraints:
- No XML parser is used on the source workbook (regex extraction only), so the
  huge cache is never parsed and there is no XXE surface.
- Generated cells reuse the per-column style index and the header row from the
  original sheet, so number/date formatting is preserved exactly.
- Text columns are written as inline strings, so ``sharedStrings.xml`` is never
  touched.
- Numbers are written verbatim (no rounding).
"""
from __future__ import annotations

import os
import re
import zipfile
from datetime import date, datetime

import pandas as pd

# Excel's day 0 is 1899-12-30 (the 1900 leap-year bug is already accounted for
# by this epoch for all dates from 1900-03-01 onward).
_EXCEL_EPOCH = date(1899, 12, 30)


def excel_serial(value) -> int:
    """Convert a date / datetime / 'YYYY-MM-DD' string to an Excel serial day."""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    elif isinstance(value, datetime):
        value = value.date()
    elif isinstance(value, pd.Timestamp):
        value = value.date()
    return (value - _EXCEL_EPOCH).days


def _col_letter(idx0: int) -> str:
    """0-based column index -> Excel column letters (0 -> A, 26 -> AA)."""
    letters = ""
    n = idx0 + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _fmt_number(value) -> str | None:
    """Format a numeric cell value without rounding. Returns None for NaN/None."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if pd.isna(value):
        return None
    f = float(value)
    if f.is_integer():
        return str(int(f))
    return repr(f)  # shortest round-trippable representation, no rounding


def _parse_column_template(sheetdata_xml: str):
    """Return (header_row_xml, {col_letter: (style_attr, is_string)}).

    The template is taken from the FIRST data row (row 2). The header row (row 1)
    is returned verbatim so its shared-string references stay valid.
    """
    rows = re.findall(r"<row\b[^>]*>.*?</row>", sheetdata_xml, re.S)
    if len(rows) < 2:
        raise ValueError("sheet needs a header row and at least one data row to template from")
    header_row = rows[0]
    template: dict[str, tuple[str, bool]] = {}
    for col_letter, attrs in re.findall(
        r'<c\s+r="([A-Z]+)\d+"([^>]*?)(?:/>|>.*?</c>)', rows[1], re.S
    ):
        style = re.search(r'\ss="(\d+)"', attrs)
        is_string = 't="s"' in attrs or 't="inlineStr"' in attrs
        template[col_letter] = (f' s="{style.group(1)}"' if style else "", is_string)
    return header_row, template


def build_worksheet_xml(original_xml: str, df: pd.DataFrame) -> str:
    """Rebuild a worksheet XML preserving everything except the data rows.

    df columns are written left-to-right into columns A, B, C ... starting at
    row 2. The header row and per-column styles are inherited from the original.
    """
    head, _, rest = original_xml.partition("<sheetData>")
    data_block, _, suffix = rest.partition("</sheetData>")
    header_row, template = _parse_column_template(data_block)

    ncols = df.shape[1]
    nrows = len(df)
    last_row = nrows + 1
    end_col = _col_letter(ncols - 1)

    head = re.sub(
        r'<dimension ref="[^"]*"/>',
        f'<dimension ref="A1:{end_col}{last_row}"/>',
        head,
        count=1,
    )

    letters = [_col_letter(i) for i in range(ncols)]
    span = f"1:{ncols}"
    parts = [head, "<sheetData>", header_row]
    for row_idx, values in enumerate(df.itertuples(index=False, name=None)):
        r = row_idx + 2
        cells = [f'<row r="{r}" spans="{span}">']
        for col_idx, raw in enumerate(values):
            letter = letters[col_idx]
            style, is_string = template.get(letter, ("", False))
            ref = f"{letter}{r}"
            if is_string:
                text = "" if raw is None or (isinstance(raw, float) and pd.isna(raw)) else str(raw)
                cells.append(
                    f'<c r="{ref}"{style} t="inlineStr"><is>'
                    f'<t xml:space="preserve">{_xml_escape(text)}</t></is></c>'
                )
            else:
                num = _fmt_number(raw)
                if num is None:
                    cells.append(f'<c r="{ref}"{style}/>')
                else:
                    cells.append(f'<c r="{ref}"{style}><v>{num}</v></c>')
        cells.append("</row>")
        parts.append("".join(cells))
    parts.append("</sheetData>")
    parts.append(suffix)
    return "".join(parts)


def _map_sheet_files(z: zipfile.ZipFile) -> dict[str, str]:
    workbook = z.read("xl/workbook.xml").decode("utf-8", "replace")
    sheets = re.findall(r'<sheet[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', workbook)
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
    rid_to_target = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
    return {
        name: "xl/" + rid_to_target[rid].lstrip("/")
        for name, rid in sheets
        if rid in rid_to_target
    }


def _sheet_table_file(z: zipfile.ZipFile, sheet_file: str) -> str | None:
    rels_path = sheet_file.replace("worksheets/", "worksheets/_rels/") + ".rels"
    if rels_path not in z.namelist():
        return None
    rels = z.read(rels_path).decode("utf-8", "replace")
    match = re.search(r'Target="([^"]*tables/[^"]+)"', rels)
    if not match:
        return None
    target = match.group(1)
    if target.startswith("/"):
        return target.lstrip("/")
    normalized = os.path.normpath("xl/worksheets/" + target).replace("\\", "/")
    return normalized


def _bump_table_ref(table_xml: str, nrows: int) -> str:
    return re.sub(
        r'ref="A1:([A-Z]+)\d+"',
        lambda m: f'ref="A1:{m.group(1)}{nrows + 1}"',
        table_xml,
        count=1,
    )


def replace_sheets(
    src_path: str,
    dst_path: str,
    replacements: dict[str, pd.DataFrame],
) -> dict[str, int]:
    """Write ``dst_path`` = ``src_path`` with the given sheets' data replaced.

    Args:
        src_path: source xlsx (never modified).
        dst_path: destination xlsx (overwritten).
        replacements: {sheet_name: DataFrame}. Each DataFrame's columns are
            written into worksheet columns A.. starting at row 2. Values must
            already be in final Excel form (e.g. dates as ``excel_serial``).

    Returns:
        {sheet_name: rows_written}.

    Every zip part that is not a replaced sheet or its Excel table is copied
    byte-for-byte, so pivot caches / pivot tables / charts survive untouched.
    """
    with zipfile.ZipFile(src_path) as zin:
        name_to_file = _map_sheet_files(zin)
        edits: dict[str, bytes] = {}
        rows_written: dict[str, int] = {}

        for sheet_name, df in replacements.items():
            if sheet_name not in name_to_file:
                raise KeyError(f"Sheet '{sheet_name}' not found in workbook")
            sheet_file = name_to_file[sheet_name]
            original = zin.read(sheet_file).decode("utf-8")
            edits[sheet_file] = build_worksheet_xml(original, df).encode("utf-8")
            rows_written[sheet_name] = len(df)

            table_file = _sheet_table_file(zin, sheet_file)
            if table_file and table_file in zin.namelist():
                table_xml = zin.read(table_file).decode("utf-8")
                edits[table_file] = _bump_table_ref(table_xml, len(df)).encode("utf-8")

        with zipfile.ZipFile(dst_path, "w") as zout:
            for item in zin.infolist():
                data = edits.get(item.filename) or zin.read(item.filename)
                info = zipfile.ZipInfo(item.filename, date_time=item.date_time)
                info.compress_type = item.compress_type
                info.external_attr = item.external_attr
                zout.writestr(info, data)

    return rows_written
