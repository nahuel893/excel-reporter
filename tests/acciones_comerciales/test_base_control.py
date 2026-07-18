"""RED tests — S3.1: BASE control workbook writer (RF-10, RF-11).

Covers ``writers/base_control.py``:

  - 6-sheet output: FACT_NET, ART-ACCION, CLIENTE-FECHA, ACC-GEN, wapi,
    Reconciliacion — exact names + order (RF-10).
  - EVERY sheet ends with a distinctly-styled (bold + FFE08A fill)
    TOTAL GENERAL row (RF-10). The 4 pivot frames arrive with the row
    already baked in (pivots.py); base_control.py appends + styles it for
    the wapi-derived table and appends + styles it for the reconciliation
    sheet (which the sheet literally ENDS with).
  - Reconciliation sums the CORRECT named Facturacion-Neta/Descuentos
    columns (never a column-letter/AZ-AX-style drift bug) grouped by
    SUCURSAL, with a per-row AND overall tolerance flag (RF-11).
  - MIN/MAX date-range checks (aexcel vs wapi vs the configured period).
  - Multi-price terna audit section: terna key, candidate prices/Bonific,
    the deterministically-picked value, and the pick reason (RF-11 audit
    surface for the RF-12 diff harness).
  - Unresolved-rows sections fed by the RF-04/RF-05 flagged subsets.

Strict-TDD: written before ``writers/base_control.py`` exists (import fails
RED).
"""
from __future__ import annotations

import pandas as pd
import pytest
from openpyxl import load_workbook

from src.services.acciones_comerciales.gold_source import MultiPriceTerna
from src.services.acciones_comerciales.writers.base_control import (
    SHEET_ACC_GEN,
    SHEET_ART_ACCION,
    SHEET_CLIENTE_FECHA,
    SHEET_FACT_NET,
    SHEET_RECONCILIACION,
    SHEET_WAPI,
    TOTAL_GENERAL_LABEL,
    ReconciliationInputs,
    build_base_control_workbook,
)

_TOTAL_FILL_RGB = "00FFE08A"


# ─────────────────────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────────────────────


def _pivot_with_total(rows: list[dict], total: dict) -> pd.DataFrame:
    """Mimic a pivots.py frame that already carries its own TOTAL GENERAL
    row (base_control.py only STYLES it for the 4 pivot sheets, never
    appends a second one)."""
    return pd.concat([pd.DataFrame(rows), pd.DataFrame([total])], ignore_index=True)


def _fact_net_df() -> pd.DataFrame:
    return _pivot_with_total(
        [
            {
                "Sucursal": "1 - CASA CENTRAL",
                "Código": 900,
                "Descripción_2": "ART UNO",
                "Descripción_3": "MARCA UNO",
                "Descripción_12": "CERVEZAS",
                "Suma de Facturacion Neta": 1000.0,
                "Suma de Descuentos": 100.0,
                "Suma de Campo1": 0.1,
            }
        ],
        {
            "Sucursal": TOTAL_GENERAL_LABEL,
            "Código": "",
            "Descripción_2": "",
            "Descripción_3": "",
            "Descripción_12": "",
            "Suma de Facturacion Neta": 1000.0,
            "Suma de Descuentos": 100.0,
            "Suma de Campo1": 0.1,
        },
    )


def _simple_descuento_pivot_df(label_col: str) -> pd.DataFrame:
    return _pivot_with_total(
        [{label_col: "1 - CASA CENTRAL", "Suma de Descuento": 90.0}],
        {label_col: TOTAL_GENERAL_LABEL, "Suma de Descuento": 90.0},
    )


def _acc_gen_df() -> pd.DataFrame:
    return _pivot_with_total(
        [
            {
                "SUCURSAL": "1 - CASA CENTRAL",
                "Acción": "ACC1",
                "Descripción Acción": "MVB PROMO",
                "mvb": "MVB",
                "(en blanco)": "",
                "CERVEZAS": 90.0,
                "AGUAS DANONE": 0.0,
                "VINOS CCU": 0.0,
                "PERNOD RICARD": 0.0,
                "SIDRAS Y LICORES": 0.0,
            }
        ],
        {
            "SUCURSAL": TOTAL_GENERAL_LABEL,
            "Acción": "",
            "Descripción Acción": "",
            "mvb": "",
            "(en blanco)": "",
            "CERVEZAS": 90.0,
            "AGUAS DANONE": 0.0,
            "VINOS CCU": 0.0,
            "PERNOD RICARD": 0.0,
            "SIDRAS Y LICORES": 0.0,
        },
    )


def _aexcel_data_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Sucursal": "1 - CASA CENTRAL",
                "Descripción Período": "2026-07-01",
                "Facturacion Neta": 1000.0,
                "Descuentos": 100.0,
            },
            {
                "Sucursal": "2 - SUCURSAL CAFAYATE",
                "Descripción Período": "2026-07-15",
                "Facturacion Neta": 500.0,
                "Descuentos": 50.0,
            },
        ]
    )


def _wapi_enriched_df() -> pd.DataFrame:
    # RF-04's SUCURSAL is a BARE name (spec scenario: SUCURSAL = "CASA
    # CENTRAL", no id prefix) — a DIFFERENT convention from aexcel's own
    # "{id} - {DESC}" Sucursal field used above.
    return pd.DataFrame(
        [
            {
                "Fecha": "2026-07-02",
                "SUCURSAL": "CASA CENTRAL",
                "Cantidad": 10.0,
                "Total2": 500.0,
                "Descuento": 90.0,
            },
            {
                "Fecha": "2026-07-20",
                "SUCURSAL": "SUCURSAL CAFAYATE",
                "Cantidad": 5.0,
                "Total2": 250.0,
                "Descuento": 60.0,
            },
        ]
    )


def _multi_price_ternas() -> list[MultiPriceTerna]:
    return [
        MultiPriceTerna(
            fecha="2026-07-01",
            id_cliente=100,
            id_articulo=900,
            candidate_precios=[50.0, 55.0],
            candidate_bonific=[0.1],
            picked_precio=55.0,
            picked_bonific=0.1,
            pick_reason="greatest Cantidades Totales; tie-break greatest Precio; tie-break lowest _id_linea (ctid-equivalent)",
        )
    ]


def _unresolved_sucursal_df() -> pd.DataFrame:
    return pd.DataFrame([{"Cod. Cliente": 999, "Fecha": "2026-07-03", "Artículo Distribuidora": 901}])


def _unresolved_precio_df() -> pd.DataFrame:
    return pd.DataFrame([{"Cod. Cliente": 100, "Fecha": "2026-07-04", "Artículo Distribuidora": 902}])


def _build_workbook_path(tmp_path):
    reconciliation = ReconciliationInputs(
        aexcel_data=_aexcel_data_df(),
        wapi_enriched=_wapi_enriched_df(),
        multi_price_ternas=_multi_price_ternas(),
        unresolved_sucursal=_unresolved_sucursal_df(),
        unresolved_precio=_unresolved_precio_df(),
        fecha_desde="2026-07-01",
        fecha_hasta="2026-07-31",
    )
    return build_base_control_workbook(
        nombre_archivo="BASE control TEST",
        output_dir=tmp_path,
        fact_net=_fact_net_df(),
        art_accion=_simple_descuento_pivot_df("SUCURSAL"),
        cliente_fecha=_simple_descuento_pivot_df("SUCURSAL"),
        acc_gen=_acc_gen_df(),
        wapi_enriched=_wapi_enriched_df(),
        reconciliation=reconciliation,
    )


def _find_row(ws, value, col: int = 1) -> int:
    for row in range(1, ws.max_row + 1):
        if ws.cell(row, col).value == value:
            return row
    raise AssertionError(f"row with {value!r} in col {col} not found in sheet {ws.title!r}")


# ─────────────────────────────────────────────────────────────────────────
# sheet structure (RF-10)
# ─────────────────────────────────────────────────────────────────────────


class TestSheetStructure:
    def test_six_sheets_exact_names_and_order(self, tmp_path):
        path = _build_workbook_path(tmp_path)
        wb = load_workbook(str(path))
        assert wb.sheetnames == [
            SHEET_FACT_NET,
            SHEET_ART_ACCION,
            SHEET_CLIENTE_FECHA,
            SHEET_ACC_GEN,
            SHEET_WAPI,
            SHEET_RECONCILIACION,
        ]

    @pytest.mark.parametrize(
        "sheet_name",
        [SHEET_FACT_NET, SHEET_ART_ACCION, SHEET_CLIENTE_FECHA, SHEET_ACC_GEN, SHEET_WAPI, SHEET_RECONCILIACION],
    )
    def test_total_general_row_ends_every_sheet_distinctly_styled(self, tmp_path, sheet_name):
        path = _build_workbook_path(tmp_path)
        wb = load_workbook(str(path))
        ws = wb[sheet_name]
        last_row = ws.max_row
        label_cell = ws.cell(last_row, 1)
        assert label_cell.value == TOTAL_GENERAL_LABEL
        assert label_cell.font.bold is True
        assert label_cell.fill.start_color.rgb == _TOTAL_FILL_RGB


# ─────────────────────────────────────────────────────────────────────────
# wapi sheet — summable Total2/Descuento (RF-10)
# ─────────────────────────────────────────────────────────────────────────


class TestWapiSheetTotals:
    def test_wapi_total_general_sums_total2_and_descuento(self, tmp_path):
        path = _build_workbook_path(tmp_path)
        wb = load_workbook(str(path))
        ws = wb[SHEET_WAPI]
        headers = [c.value for c in ws[1]]
        last_row = ws.max_row
        total2_col = headers.index("Total2") + 1
        descuento_col = headers.index("Descuento") + 1
        assert ws.cell(last_row, total2_col).value == 750.0
        assert ws.cell(last_row, descuento_col).value == 150.0


# ─────────────────────────────────────────────────────────────────────────
# reconciliation sheet — correct FN/Descuentos columns, tolerance (RF-11)
# ─────────────────────────────────────────────────────────────────────────


class TestReconciliationFacturacionDescuentos:
    def test_reconciliation_sums_correct_named_columns_per_sucursal(self, tmp_path):
        path = _build_workbook_path(tmp_path)
        wb = load_workbook(str(path))
        ws = wb[SHEET_RECONCILIACION]

        # aexcel's "1 - CASA CENTRAL" is normalized (prefix stripped) to
        # match wapi's bare "CASA CENTRAL" before grouping.
        row = _find_row(ws, "CASA CENTRAL")
        values = [ws.cell(row, c).value for c in range(1, 7)]
        # SUCURSAL | Facturacion Neta (aexcel) | Descuentos (aexcel) | Descuento (wapi) | Delta | tolerancia
        assert values[1] == 1000.0
        assert values[2] == 100.0
        assert values[3] == 90.0
        assert values[4] == pytest.approx(10.0)
        assert values[5] == "NO"  # delta 10.0 exceeds the 0.01 tolerance

    def test_reconciliation_ends_with_total_general_over_delta_columns(self, tmp_path):
        path = _build_workbook_path(tmp_path)
        wb = load_workbook(str(path))
        ws = wb[SHEET_RECONCILIACION]
        last_row = ws.max_row
        values = [ws.cell(last_row, c).value for c in range(1, 7)]
        assert values[0] == TOTAL_GENERAL_LABEL
        assert values[1] == 1500.0  # 1000 + 500
        assert values[2] == 150.0  # 100 + 50
        assert values[3] == 150.0  # 90 + 60
        assert values[4] == pytest.approx(0.0, abs=1e-9)  # deltas net to ~0
        assert values[5] == "SI"  # grand-total delta IS within tolerance


class TestReconciliationDateRangeChecks:
    def test_min_max_date_range_per_source(self, tmp_path):
        path = _build_workbook_path(tmp_path)
        wb = load_workbook(str(path))
        ws = wb[SHEET_RECONCILIACION]

        ax_row = _find_row(ws, "aexcel (gold)")
        assert ws.cell(ax_row, 2).value == "2026-07-01"
        assert ws.cell(ax_row, 3).value == "2026-07-15"

        wapi_row = _find_row(ws, "wapi")
        assert ws.cell(wapi_row, 2).value == "2026-07-02"
        assert ws.cell(wapi_row, 3).value == "2026-07-20"


class TestReconciliationMultiPriceTernaSection:
    def test_multi_price_terna_row_present_with_pick_reason(self, tmp_path):
        path = _build_workbook_path(tmp_path)
        wb = load_workbook(str(path))
        ws = wb[SHEET_RECONCILIACION]

        header_row = _find_row(ws, "Fecha", col=1)
        # header row for the multi-price section must declare all 8 columns
        headers = [ws.cell(header_row, c).value for c in range(1, 9)]
        assert headers == [
            "Fecha",
            "Cod. Cliente",
            "Codigo Articulo",
            "Precios candidatos",
            "Bonific candidatos",
            "Precio elegido",
            "Bonific elegido",
            "Motivo de eleccion",
        ]

        data_row = header_row + 1
        assert ws.cell(data_row, 1).value == "2026-07-01"
        assert ws.cell(data_row, 2).value == 100
        assert ws.cell(data_row, 3).value == 900
        assert "50.0" in ws.cell(data_row, 4).value
        assert "55.0" in ws.cell(data_row, 4).value
        assert ws.cell(data_row, 6).value == 55.0
        assert ws.cell(data_row, 7).value == 0.1
        assert "Cantidades Totales" in ws.cell(data_row, 8).value


class TestReconciliationUnresolvedSections:
    def test_unresolved_sucursal_rows_present(self, tmp_path):
        path = _build_workbook_path(tmp_path)
        wb = load_workbook(str(path))
        ws = wb[SHEET_RECONCILIACION]

        row = _find_row(ws, 999, col=1)
        assert ws.cell(row, 2).value == "2026-07-03"

    def test_unresolved_precio_rows_present(self, tmp_path):
        path = _build_workbook_path(tmp_path)
        wb = load_workbook(str(path))
        ws = wb[SHEET_RECONCILIACION]

        # both unresolved sections key on Cod. Cliente in col 1 — the precio
        # section's flagged client is 100, distinct from the sucursal
        # section's flagged client 999.
        row = _find_row(ws, 100, col=1)
        assert ws.cell(row, 2).value == "2026-07-04"
