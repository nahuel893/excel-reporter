"""Workbook builder for stock-badie: STOCK sheet skeleton, values, and the
core live Excel formulas (RF-06/RF-07).

Consumes the wide DataFrame produced by ``processor.pivot_wide()`` — a
MultiIndex-columned frame with 4 identity columns, 14 sucursal blocks of
[Stock, VENTA, PEDIDO, ALCANCE] (PEDIDO/ALCANCE are ``None`` placeholders
there), and a Total block [Total, VENTA TOTAL, PEDIDO TOTAL, ALCANCE TOTAL]
(also placeholders). This module fills those placeholders with LIVE Excel
formulas — never computed in Python — so ``DiasStock`` stays an interactive
knob in the delivered workbook. Stock/VENTA cells are written as plain
values pulled straight from ``wide_df`` (never formulas, never rounded).

Scope note (PR3): only the sheet skeleton, values, and the core
PEDIDO/ALCANCE/Total-block formulas. The per-generico totals band, the
TOTAL GENERAL bottom row, number formatting, and conditional formatting are
added in a later work unit (PR4), which may need to shift rows below the
params cells to insert the per-generico band above ``HEADER_ROW``.
"""

from __future__ import annotations

import pandas as pd
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName

SHEET_NAME = "STOCK"

# ── Param cells (rows 1-2) ──────────────────────────────────────────────
DIAS_STOCK_ROW = 1
DIAS_VENTA_ROW = 2
PARAM_LABEL_COL = 1
PARAM_VALUE_COL = 2
DIAS_STOCK_CELL = f"{get_column_letter(PARAM_VALUE_COL)}{DIAS_STOCK_ROW}"
DIAS_VENTA_CELL = f"{get_column_letter(PARAM_VALUE_COL)}{DIAS_VENTA_ROW}"

# ── Table layout ─────────────────────────────────────────────────────────
# Row 3 left blank as a spacer: PR4 inserts the per-generico totals band
# between the params and the table header without having to touch this
# module's row numbering contract for the header/data rows below it.
HEADER_ROW = 4
DATA_START_ROW = HEADER_ROW + 1

_IDENTITY_HEADERS = ["idArticulo", "dsArticulo", "GENERICO", "MARCA"]
_N_IDENTITY = len(_IDENTITY_HEADERS)  # 4
_BLOCK_WIDTH = 4  # Stock, VENTA, PEDIDO, ALCANCE
_FIRST_BLOCK_COL = _N_IDENTITY + 1  # column 5 (E)

_TOTAL_HEADERS = ["Total", "VENTA TOTAL", "PEDIDO TOTAL", "ALCANCE TOTAL"]


def _sucursal_block_keys(columns: pd.MultiIndex) -> list[str]:
    """Ordered, de-duplicated list of sucursal block keys (MultiIndex level
    0), excluding the identity ("") and Total blocks. Order is inherited
    from wide_df's column order, which processor.pivot_wide() fixes to
    SUCURSAL_ORDER regardless of input row order."""
    keys: list[str] = []
    seen: set[str] = set()
    for level0, _level1 in columns:
        if level0 in ("", "Total") or level0 in seen:
            continue
        seen.add(level0)
        keys.append(level0)
    return keys


def build_workbook(wide_df: pd.DataFrame, dias_venta: int, dias_stock: int = 15) -> Workbook:
    """Build the STOCK sheet: params, header, and one row per article with
    Stock/VENTA values plus live PEDIDO/ALCANCE/Total-block formulas.

    Args:
        wide_df: output of processor.pivot_wide() (MultiIndex columns).
        dias_venta: business days elapsed this month
            (processor.compute_dias_venta()) — written as a plain value into
            the DiasVenta param cell.
        dias_stock: target days of stock coverage — the interactive knob,
            written as a plain editable value into the DiasStock param cell
            (default 15).

    Returns:
        An in-memory openpyxl Workbook. Caller is responsible for saving.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME

    sucursales = _sucursal_block_keys(wide_df.columns)

    # ── Param cells + workbook-level named ranges ──
    ws.cell(row=DIAS_STOCK_ROW, column=PARAM_LABEL_COL, value="DiasStock:")
    ws.cell(row=DIAS_STOCK_ROW, column=PARAM_VALUE_COL, value=dias_stock)
    ws.cell(row=DIAS_VENTA_ROW, column=PARAM_LABEL_COL, value="DiasVenta:")
    ws.cell(row=DIAS_VENTA_ROW, column=PARAM_VALUE_COL, value=dias_venta)

    _param_col_letter = get_column_letter(PARAM_VALUE_COL)
    wb.defined_names["DiasStock"] = DefinedName(
        "DiasStock", attr_text=f"'{SHEET_NAME}'!${_param_col_letter}${DIAS_STOCK_ROW}"
    )
    wb.defined_names["DiasVenta"] = DefinedName(
        "DiasVenta", attr_text=f"'{SHEET_NAME}'!${_param_col_letter}${DIAS_VENTA_ROW}"
    )

    # ── Header row ──
    for i, label in enumerate(_IDENTITY_HEADERS, 1):
        ws.cell(row=HEADER_ROW, column=i, value=label)

    block_col_of: dict[str, int] = {}  # sucursal -> first (Stock) column of its block
    col = _FIRST_BLOCK_COL
    for sucursal in sucursales:
        block_col_of[sucursal] = col
        ws.cell(row=HEADER_ROW, column=col, value=sucursal)
        ws.cell(row=HEADER_ROW, column=col + 1, value="VENTA")
        ws.cell(row=HEADER_ROW, column=col + 2, value="PEDIDO")
        ws.cell(row=HEADER_ROW, column=col + 3, value="ALCANCE")
        col += _BLOCK_WIDTH

    total_col = col  # first column of the Total block
    for i, label in enumerate(_TOTAL_HEADERS):
        ws.cell(row=HEADER_ROW, column=total_col + i, value=label)

    total_stock_col = total_col
    total_venta_col = total_col + 1
    total_pedido_col = total_col + 2
    total_alcance_col = total_col + 3
    total_stock_letter = get_column_letter(total_stock_col)
    total_venta_letter = get_column_letter(total_venta_col)

    # ── Data rows ──
    for offset, (_, row) in enumerate(wide_df.iterrows()):
        r = DATA_START_ROW + offset

        ws.cell(row=r, column=1, value=row[("", "idArticulo")])
        ws.cell(row=r, column=2, value=row[("", "dsArticulo")])
        ws.cell(row=r, column=3, value=row[("", "GENERICO")])
        ws.cell(row=r, column=4, value=row[("", "MARCA")])

        stock_refs: list[str] = []
        venta_refs: list[str] = []
        pedido_refs: list[str] = []
        for sucursal in sucursales:
            block_col = block_col_of[sucursal]
            stock_col = block_col
            venta_col = block_col + 1
            pedido_col = block_col + 2
            alcance_col = block_col + 3

            stock_letter = get_column_letter(stock_col)
            venta_letter = get_column_letter(venta_col)
            stock_ref = f"{stock_letter}{r}"
            venta_ref = f"{venta_letter}{r}"

            # Stock/VENTA: plain DB values, never formulas, never rounded.
            ws.cell(row=r, column=stock_col, value=row[(sucursal, "Stock")])
            ws.cell(row=r, column=venta_col, value=row[(sucursal, "VENTA")])
            ws.cell(
                row=r, column=pedido_col,
                value=f"=MAX(({venta_ref}/DiasVenta)*DiasStock-{stock_ref},0)",
            )
            ws.cell(
                row=r, column=alcance_col,
                value=f"=IFERROR({stock_ref}/({venta_ref}/DiasVenta),0)",
            )

            stock_refs.append(stock_ref)
            venta_refs.append(venta_ref)
            pedido_refs.append(f"{get_column_letter(pedido_col)}{r}")

        total_stock_ref = f"{total_stock_letter}{r}"
        total_venta_ref = f"{total_venta_letter}{r}"

        ws.cell(row=r, column=total_stock_col, value=f"=SUM({','.join(stock_refs)})")
        ws.cell(row=r, column=total_venta_col, value=f"=SUM({','.join(venta_refs)})")
        ws.cell(row=r, column=total_pedido_col, value=f"=SUM({','.join(pedido_refs)})")
        # Ratio-of-sums correction (RF-07): NOT a SUM of the 14 per-sucursal
        # ALCANCE cells — sum of ratios != ratio of sums.
        ws.cell(
            row=r, column=total_alcance_col,
            value=f"=IFERROR({total_stock_ref}/({total_venta_ref}/DiasVenta),0)",
        )

    return wb
