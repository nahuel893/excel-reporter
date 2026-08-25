"""Block-level surgical worksheet editing for workbooks openpyxl cannot round-trip.

``xlsx_surgical`` replaces a whole worksheet from a DataFrame whose header sits on
row 1 and whose data starts on row 2. That shape does not fit every sheet:

- ``AX`` needs formula columns (``AD``/``AE`` are VLOOKUPs that must stretch to the
  last row of the table) and blanked-out columns for the fields nothing reads.
- ``marcas_x_pdv`` holds several independent blocks anchored at different cells
  (``A3``, ``J2``, ``N1``, ``R1``) that must be written without disturbing each other.

This module keeps the same guarantees as ``xlsx_surgical``: no XML parser runs over
the source workbook, every zip part that is not explicitly edited is copied
byte-for-byte, and numbers are written verbatim with no rounding.

Two entry points:

``rebuild_table_sheet``
    Regenerates every data row of a single-table sheet from a column plan. Streams
    the source worksheet so a 180 MB ``sheetData`` never lands in memory at once.

``patch_blocks``
    Merges rectangular blocks into an existing sheet, keeping every cell the blocks
    do not cover exactly as it was (shared-formula masters included).

Both are driven by :func:`edit_workbook`, which performs the zip-level copy.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from src.core.xlsx_surgical import _col_letter, _xml_escape, excel_serial

# Reuse the shared numeric formatter so both modules round-trip numbers identically.
from src.core.xlsx_surgical import _fmt_number

_ROW_RE = re.compile(r"<row\b[^>]*>.*?</row>|<row\b[^>]*/>", re.S)
_ROW_NUM_RE = re.compile(r'<row\b[^>]*?\br="(\d+)"')
_CELL_RE = re.compile(r'<c\s+r="([A-Z]+)(\d+)"(?:[^>]*?/>|[^>]*?>.*?</c>)', re.S)
_SI_RE = re.compile(r"<si\b.*?</si>|<si\b[^>]*/>", re.S)
_SIMPLE_SI_RE = re.compile(r"^<si><t(?:\s[^>]*)?>(.*)</t></si>$", re.S)

SHARED_STRINGS_PART = "xl/sharedStrings.xml"


class SharedStrings:
    """The workbook's string table, so repeated text is stored once.

    AX repeats a handful of branch, brand, price-list and generic names across
    ~150k rows. Written inline that is ~65 MB of duplicated text; through the
    string table each one is a small integer. Existing entries keep their index,
    so every cell already pointing at the table stays correct.
    """

    def __init__(self, xml: str | None) -> None:
        self._entries: list[str] = []
        self._index: dict[str, int] = {}
        self.dirty = False
        if xml:
            for match in _SI_RE.finditer(xml):
                entry = match.group(0)
                position = len(self._entries)
                self._entries.append(entry)
                simple = _SIMPLE_SI_RE.match(entry)
                # Rich-text entries (<si> with <r> runs) are kept but not reused:
                # matching their plain text could silently change formatting.
                if simple and simple.group(1) not in self._index:
                    self._index[simple.group(1)] = position

    def intern(self, text: str) -> int:
        """Return the table index for ``text``, appending it if it is new."""
        escaped = _xml_escape(text)
        existing = self._index.get(escaped)
        if existing is not None:
            return existing
        position = len(self._entries)
        self._entries.append(f'<si><t xml:space="preserve">{escaped}</t></si>')
        self._index[escaped] = position
        self.dirty = True
        return position

    def to_xml(self) -> bytes:
        total = len(self._entries)
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'count="{total}" uniqueCount="{total}">' + "".join(self._entries) + "</sst>"
        ).encode("utf-8")


def load_shared_strings(zin: zipfile.ZipFile) -> SharedStrings:
    """Read the workbook's string table, or start an empty one."""
    if SHARED_STRINGS_PART in zin.namelist():
        return SharedStrings(zin.read(SHARED_STRINGS_PART).decode("utf-8"))
    return SharedStrings(None)


# --------------------------------------------------------------------------- #
# Column / block description
# --------------------------------------------------------------------------- #

VALUE = "value"
FORMULA = "formula"
BLANK = "blank"


@dataclass
class ColumnSpec:
    """How one worksheet column is written.

    Args:
        letter: target column letter (``"AD"``).
        kind: ``VALUE`` writes the block's data, ``FORMULA`` writes ``formula``
            with ``{row}`` substituted, ``BLANK`` writes no cell at all — the
            column keeps its header and table entry but carries no payload.
        source: key into the block's DataFrame for ``VALUE`` columns. Defaults to
            the column letter, which is rarely what you want, so pass it.
        formula: formula body without the leading ``=``. ``{row}`` is replaced by
            the 1-based row number.
        style: explicit ``s="N"`` index. ``None`` samples it from the template row.
        is_string: force text output. ``None`` samples it from the template row.
    """

    letter: str
    kind: str = VALUE
    source: str | None = None
    formula: str | None = None
    style: str | None = None
    is_string: bool | None = None


@dataclass
class Block:
    """A rectangular region written into a sheet.

    Args:
        first_row: 1-based worksheet row of the block's FIRST DATA row.
        columns: column specs, in any order (they carry their own letter).
        data: rows to write. A DataFrame is read through ``ColumnSpec.source``;
            a list of dicts works the same way.
        clear_through: last row to wipe clean under the block. Rows between the
            block's end and this row get the block's columns removed, which is how
            stale drag-down formulas are pruned. ``None`` clears nothing.
        template_row: row to sample styles from. Defaults to ``first_row``.
    """

    first_row: int
    columns: list[ColumnSpec]
    data: pd.DataFrame | list[dict] = field(default_factory=list)
    clear_through: int | None = None
    template_row: int | None = None

    @property
    def n_rows(self) -> int:
        return len(self.data)

    @property
    def last_row(self) -> int:
        return self.first_row + self.n_rows - 1

    def sample_row(self) -> int:
        return self.template_row if self.template_row is not None else self.first_row


# --------------------------------------------------------------------------- #
# Cell rendering
# --------------------------------------------------------------------------- #


def _style_attr(style: str | None) -> str:
    return f' s="{style}"' if style else ""


def _render_cell(
    ref: str,
    spec: ColumnSpec,
    value,
    row: int,
    strings: SharedStrings | None = None,
) -> str:
    """Render one ``<c>`` element for ``spec`` at ``ref``.

    A ``BLANK`` column renders nothing at all: a spreadsheet cell that holds no
    value needs no element, and skipping ~20 of them per row over 150k rows keeps
    the sheet a third of the size for exactly the same result.
    """
    style = _style_attr(spec.style)

    if spec.kind == BLANK:
        return ""

    if spec.kind == FORMULA:
        body = _xml_escape(spec.formula.format(row=row))
        return f'<c r="{ref}"{style}><f>{body}</f></c>'

    if spec.is_string:
        text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
        if not text:
            return f'<c r="{ref}"{style}/>'
        if strings is not None:
            return f'<c r="{ref}"{style} t="s"><v>{strings.intern(text)}</v></c>'
        return (
            f'<c r="{ref}"{style} t="inlineStr"><is>'
            f'<t xml:space="preserve">{_xml_escape(text)}</t></is></c>'
        )

    if isinstance(value, (date, datetime, pd.Timestamp)):
        value = excel_serial(value)
    number = _fmt_number(value)
    if number is None:
        return f'<c r="{ref}"{style}/>'
    return f'<c r="{ref}"{style}><v>{number}</v></c>'


def _render_row(row: int, cells: list[str], span_lo: int, span_hi: int) -> str:
    return f'<row r="{row}" spans="{span_lo}:{span_hi}">' + "".join(cells) + "</row>"


# --------------------------------------------------------------------------- #
# Style sampling
# --------------------------------------------------------------------------- #


def _sample_styles(row_xml: str) -> dict[str, tuple[str | None, bool]]:
    """Return ``{column_letter: (style_index, is_string)}`` from one row's XML."""
    out: dict[str, tuple[str | None, bool]] = {}
    for match in re.finditer(r'<c\s+r="([A-Z]+)\d+"([^>]*?)(?:/>|>)', row_xml):
        letter, attrs = match.group(1), match.group(2)
        style = re.search(r'\ss="(\d+)"', attrs)
        is_string = 't="s"' in attrs or 't="inlineStr"' in attrs or 't="str"' in attrs
        out[letter] = (style.group(1) if style else None, is_string)
    return out


def _apply_template(columns: list[ColumnSpec], template: dict[str, tuple[str | None, bool]]):
    """Fill unset ``style``/``is_string`` on each spec from the sampled row."""
    for spec in columns:
        sampled_style, sampled_is_string = template.get(spec.letter, (None, False))
        if spec.style is None:
            spec.style = sampled_style
        if spec.is_string is None:
            spec.is_string = sampled_is_string


def _block_values(block: Block, spec: ColumnSpec):
    """Return the value sequence for one ``VALUE`` column of a block."""
    key = spec.source if spec.source is not None else spec.letter
    if isinstance(block.data, pd.DataFrame):
        if key not in block.data.columns:
            raise KeyError(f"column '{key}' missing from block data for cell column {spec.letter}")
        return block.data[key].tolist()
    return [row.get(key) for row in block.data]


# --------------------------------------------------------------------------- #
# Streaming rebuild (single-table sheets such as AX)
# --------------------------------------------------------------------------- #


def _stream_sheet_parts(
    zin: zipfile.ZipFile,
    sheet_file: str,
    wanted_rows: set[int],
    chunk: int = 1 << 22,
) -> tuple[str, dict[int, str], str]:
    """Read a worksheet without holding its whole ``sheetData`` in memory.

    Returns ``(head, {row_number: row_xml}, suffix)`` where ``head`` is everything
    up to and including ``<sheetData>`` and ``suffix`` is everything from
    ``</sheetData>`` onward. Only rows listed in ``wanted_rows`` are kept.
    """
    head = ""
    suffix = ""
    rows: dict[int, str] = {}
    buffer = ""
    in_data = False
    max_wanted = max(wanted_rows) if wanted_rows else 0

    with zin.open(sheet_file) as stream:
        while True:
            raw = stream.read(chunk)
            if not raw:
                break
            buffer += raw.decode("utf-8")

            if not in_data:
                marker = buffer.find("<sheetData>")
                if marker == -1:
                    continue
                head = buffer[: marker + len("<sheetData>")]
                buffer = buffer[marker + len("<sheetData>") :]
                in_data = True

            end = buffer.find("</sheetData>")
            if end != -1:
                _collect_rows(buffer[:end], wanted_rows, rows)
                suffix = buffer[end:]
                # Drain the rest of the stream so the zip entry closes cleanly.
                while stream.read(chunk):
                    pass
                buffer = ""
                break

            if len(rows) >= len(wanted_rows) and max_wanted:
                # Every wanted row is in hand: stop parsing, just look for the end.
                keep = buffer[-32:]
                _collect_rows(buffer[: len(buffer) - len(keep)], set(), rows)
                buffer = keep
                continue

            last_close = buffer.rfind("</row>")
            if last_close != -1:
                cut = last_close + len("</row>")
                _collect_rows(buffer[:cut], wanted_rows, rows)
                buffer = buffer[cut:]

    if not suffix:
        end = buffer.find("</sheetData>")
        if end == -1:
            raise ValueError(f"{sheet_file}: no </sheetData> found")
        _collect_rows(buffer[:end], wanted_rows, rows)
        suffix = buffer[end:]

    return head, rows, suffix


def _collect_rows(fragment: str, wanted_rows: set[int], out: dict[int, str]) -> None:
    if not wanted_rows:
        return
    for match in _ROW_RE.finditer(fragment):
        row_xml = match.group(0)
        num = _ROW_NUM_RE.search(row_xml)
        if num and int(num.group(1)) in wanted_rows:
            out[int(num.group(1))] = row_xml


def _set_dimension(head: str, last_col_letter: str, last_row: int) -> str:
    return re.sub(
        r'<dimension ref="[^"]*"/>',
        f'<dimension ref="A1:{last_col_letter}{last_row}"/>',
        head,
        count=1,
    )


def rebuild_table_sheet(
    zin: zipfile.ZipFile,
    sheet_file: str,
    columns: list[ColumnSpec],
    data: pd.DataFrame,
    header_rows: int = 1,
    strings: SharedStrings | None = None,
) -> bytes:
    """Rebuild every data row of a sheet from ``columns`` and ``data``.

    The header rows are copied verbatim (keeping their shared-string references)
    and styles are sampled from the first original data row, so number and date
    formats survive. Streams the source, so sheets with hundreds of MB of
    ``sheetData`` are safe.
    """
    first_data_row = header_rows + 1
    wanted = set(range(1, header_rows + 1)) | {first_data_row}
    head, kept_rows, suffix = _stream_sheet_parts(zin, sheet_file, wanted)

    if first_data_row not in kept_rows:
        raise ValueError(f"{sheet_file}: no data row {first_data_row} to sample styles from")
    _apply_template(columns, _sample_styles(kept_rows[first_data_row]))

    ordered = sorted(columns, key=lambda spec: _letter_index(spec.letter))
    last_col = ordered[-1].letter
    n_cols = _letter_index(last_col) + 1
    last_row = header_rows + len(data)

    series = {
        spec.letter: (_block_values(Block(first_data_row, [spec], data), spec) if spec.kind == VALUE else None)
        for spec in ordered
    }

    parts = [_set_dimension(head, last_col, last_row)]
    for header_row in range(1, header_rows + 1):
        parts.append(kept_rows[header_row])

    for offset in range(len(data)):
        row = first_data_row + offset
        cells = []
        for spec in ordered:
            value = series[spec.letter][offset] if spec.kind == VALUE else None
            cells.append(_render_cell(f"{spec.letter}{row}", spec, value, row, strings))
        parts.append(_render_row(row, cells, 1, n_cols))

    parts.append(suffix)
    return "".join(parts).encode("utf-8")


def _letter_index(letter: str) -> int:
    """``"A"`` -> 0, ``"AA"`` -> 26."""
    total = 0
    for char in letter:
        total = total * 26 + (ord(char) - 64)
    return total - 1


# --------------------------------------------------------------------------- #
# In-memory block patching (multi-block sheets such as marcas_x_pdv)
# --------------------------------------------------------------------------- #


def patch_blocks(
    original_xml: str,
    blocks: list[Block],
    strings: SharedStrings | None = None,
) -> bytes:
    """Merge ``blocks`` into ``original_xml``, keeping every uncovered cell.

    Cells the blocks do not touch are copied verbatim, so shared-formula masters,
    stray notes and summary formulas next to a block all survive. Rows in a
    block's ``clear_through`` tail lose that block's columns, which prunes stale
    drag-down formulas.
    """
    head, _, rest = original_xml.partition("<sheetData>")
    body, _, suffix = rest.partition("</sheetData>")
    head += "<sheetData>"

    rows_xml: dict[int, str] = {}
    for match in _ROW_RE.finditer(body):
        num = _ROW_NUM_RE.search(match.group(0))
        if num:
            rows_xml[int(num.group(1))] = match.group(0)

    # Sample styles before anything is rewritten.
    for block in blocks:
        sample = rows_xml.get(block.sample_row())
        _apply_template(block.columns, _sample_styles(sample) if sample else {})

    # {row: {letter: cell_xml or None-to-delete}}
    edits: dict[int, dict[str, str | None]] = {}
    for block in blocks:
        for spec in block.columns:
            values = _block_values(block, spec) if spec.kind == VALUE else [None] * block.n_rows
            for offset in range(block.n_rows):
                row = block.first_row + offset
                ref = f"{spec.letter}{row}"
                cell = _render_cell(ref, spec, values[offset], row, strings)
                edits.setdefault(row, {})[spec.letter] = cell or None
        if block.clear_through is not None:
            for row in range(block.last_row + 1, block.clear_through + 1):
                for spec in block.columns:
                    edits.setdefault(row, {})[spec.letter] = None

    parts = [head]
    last_row = 1
    last_col = 0
    for row in sorted(set(rows_xml) | set(edits)):
        merged = _merge_row(row, rows_xml.get(row), edits.get(row, {}))
        if not merged:
            continue
        parts.append(merged)
        last_row = max(last_row, row)
        # The dimension must span every surviving cell, not just the blocks': a
        # reader that trusts it (openpyxl does) silently drops whatever falls
        # outside, which would hide the R:V summary sitting beside the blocks.
        for letter in _CELL_RE.findall(merged):
            last_col = max(last_col, _letter_index(letter[0]))
    parts.append("</sheetData>")
    parts.append(suffix)

    rebuilt = _set_dimension("".join(parts), _col_letter(last_col), last_row)
    return rebuilt.encode("utf-8")


def _merge_row(row: int, original: str | None, edits: dict[str, str | None]) -> str:
    """Rebuild one row: original cells the edits do not cover, plus the edits."""
    cells: dict[str, str] = {}
    attrs = f'<row r="{row}">'

    if original:
        open_tag = re.match(r"<row\b[^>]*?>", original)
        if open_tag:
            attrs = open_tag.group(0)
        for match in _CELL_RE.finditer(original):
            cells[match.group(1)] = match.group(0)

    for letter, cell_xml in edits.items():
        if cell_xml is None:
            cells.pop(letter, None)
        else:
            cells[letter] = cell_xml

    if not cells:
        return ""

    ordered = sorted(cells, key=_letter_index)
    lo = _letter_index(ordered[0]) + 1
    hi = _letter_index(ordered[-1]) + 1
    attrs = re.sub(r'\sspans="[^"]*"', "", attrs)
    attrs = attrs[:-1] + f' spans="{lo}:{hi}">'
    return attrs + "".join(cells[letter] for letter in ordered) + "</row>"


# --------------------------------------------------------------------------- #
# Table / workbook level fixes
# --------------------------------------------------------------------------- #


def resize_table(table_xml: str, last_row: int) -> str:
    """Point a table's ``ref`` and ``autoFilter`` at ``last_row``.

    This is what makes the table's own formula columns stretch to the foot of the
    data instead of stopping where the previous load ended.
    """
    def _swap(match: re.Match) -> str:
        return f'{match.group(1)}="A1:{match.group(2)}{last_row}"'

    return re.sub(r'\b(ref|autoFilter ref)="A1:([A-Z]+)\d+"', _swap, table_xml)


def force_full_recalc(workbook_xml: str) -> str:
    """Make the workbook recalculate every formula the next time it is opened.

    Formula cells are written without a cached ``<v>``, and pivot-driven values
    downstream of a reloaded sheet would otherwise show the previous run's numbers.
    """
    if "<calcPr" not in workbook_xml:
        return workbook_xml.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')
    return re.sub(
        r"<calcPr\b([^/>]*)/>",
        lambda m: f'<calcPr{m.group(1)} fullCalcOnLoad="1"/>'
        if "fullCalcOnLoad" not in m.group(1)
        else m.group(0),
        workbook_xml,
        count=1,
    )


def refresh_pivot_caches_on_load(cache_definition_xml: str) -> str:
    """Set ``refreshOnLoad`` so a pivot re-reads its source sheet when opened."""
    return re.sub(
        r"<pivotCacheDefinition\b([^>]*?)>",
        lambda m: "<pivotCacheDefinition"
        + (
            m.group(1)
            if "refreshOnLoad" in m.group(1)
            else m.group(1) + ' refreshOnLoad="1"'
        )
        + ">",
        cache_definition_xml,
        count=1,
    )


def set_defined_name(workbook_xml: str, pattern: str, replacement: str) -> str:
    """Rewrite one ``<definedName>`` body matched by ``pattern``."""
    return re.sub(pattern, replacement, workbook_xml, count=1)


# --------------------------------------------------------------------------- #
# Zip-level driver
# --------------------------------------------------------------------------- #


def map_sheet_files(zin: zipfile.ZipFile) -> dict[str, str]:
    """``{sheet name: 'xl/worksheets/sheetN.xml'}``."""
    workbook = zin.read("xl/workbook.xml").decode("utf-8", "replace")
    sheets = re.findall(r'<sheet[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', workbook)
    rels = zin.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
    rid_to_target = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
    return {
        name: "xl/" + rid_to_target[rid].lstrip("/")
        for name, rid in sheets
        if rid in rid_to_target
    }


def edit_workbook(
    src_path: str,
    dst_path: str,
    edits: dict[str, bytes],
    drop: set[str] | None = None,
) -> None:
    """Write ``dst_path`` = ``src_path`` with ``edits`` applied and ``drop`` removed.

    Every other zip part is copied byte-for-byte, so pivot caches, VBA, styles,
    drawings and shared strings survive untouched.
    """
    drop = drop or set()
    with zipfile.ZipFile(src_path) as zin, zipfile.ZipFile(
        dst_path, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            if item.filename in drop:
                continue
            data = edits.get(item.filename)
            if data is None:
                data = zin.read(item.filename)
            info = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            info.compress_type = item.compress_type
            info.external_attr = item.external_attr
            zout.writestr(info, data)
