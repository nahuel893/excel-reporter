"""
Tests for the resumen-mensual JSON serializer (TDD — written before implementation).

Tests verify the to_datos_json() contract:
  - NaN Objetivo → JSON null (not 0)
  - 0.0 Objetivo → JSON 0.0 (not null)
  - is_subtotal: true for the 3 special Sucursal labels, false for all others
  - Single section when no marca_splits; 2 sections when marca_splits defines a split
  - meta.col_n1 / meta.col_n2 carry the dynamic human names; row keys are canonical
  - con_objetivo reflected in meta
  - sin_prvta: true on the matching sheet, absent/false on others
"""
import math
import numpy as np
import pandas as pd
import pytest

from src.services.resumen_mensual.service import (
    _SheetSection,
    _SheetStruct,
    _SUBTOTAL_CC,
    _SUC_SIN_DIRECTA,
    _TOTAL_SIN_SMK,
)
from src.services.resumen_mensual.serializer import to_datos_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    sucursal: str = "CASA CENTRAL",
    generico: str = "CERVEZAS",
    n2: float = 100.0,
    n1: float = 200.0,
    total: float = 5000.0,
    tendencia: float = 6000.0,
    mmaa: float = 4500.0,
    ma: float = 4800.0,
    objetivo: float | None = None,
    tend_vs_obj: float | None = None,
) -> dict:
    """Build a single row dict matching the 10-column DataFrame schema."""
    return {
        "Sucursal": sucursal,
        "Generico": generico,
        "col_n2_placeholder": n2,   # renamed to dynamic col_n2 by fixture
        "col_n1_placeholder": n1,   # renamed to dynamic col_n1 by fixture
        "Total Ventas": total,
        "Tendencia": tendencia,
        "MMAA": mmaa,
        "MA": ma,
        "Objetivo": objetivo,
        "Tend vs Obj (%)": tend_vs_obj,
    }


_COL_N1 = "09-06 Martes"
_COL_N2 = "08-06 Lunes"


def _make_section_df(rows: list[dict], col_n1: str = _COL_N1, col_n2: str = _COL_N2) -> pd.DataFrame:
    """Build a DataFrame with the real column names for col_n1/col_n2."""
    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "col_n2_placeholder": col_n2,
        "col_n1_placeholder": col_n1,
    })
    return df


def _make_info_dias() -> dict:
    return {"Dias Habiles": 22, "Dias Transcurridos": 7, "Dias Faltantes": 15}


def _simple_struct(rows: list[dict], generico: str = "CERVEZAS", note: str | None = None) -> list[_SheetStruct]:
    """Single-section, single-sheet struct list."""
    df = _make_section_df(rows)
    section = _SheetSection(label=generico, df=df)
    struct = _SheetStruct(logical_generico=generico, sections=[section], note=note)
    return [struct]


# ---------------------------------------------------------------------------
# TC-01: NaN Objetivo → JSON null (not 0)
# ---------------------------------------------------------------------------

class TestNullVsZeroObjectivo:
    def test_nan_objetivo_serializes_as_null(self):
        """NaN in Objetivo column must serialize to JSON null, not 0."""
        row = _make_row(objetivo=float("nan"), tend_vs_obj=float("nan"))
        structs = _simple_struct([row])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        data_rows = result["sheets"][0]["sections"][0]["rows"]
        assert len(data_rows) == 1
        assert data_rows[0]["Objetivo"] is None, "NaN Objetivo must serialize as null"
        assert data_rows[0]["Tend vs Obj (%)"] is None, "NaN Tend vs Obj must serialize as null"

    def test_np_nan_objetivo_serializes_as_null(self):
        """np.nan in Objetivo column must also serialize to null."""
        row = _make_row(objetivo=np.nan, tend_vs_obj=np.nan)
        structs = _simple_struct([row])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        data_rows = result["sheets"][0]["sections"][0]["rows"]
        assert data_rows[0]["Objetivo"] is None

    def test_zero_objetivo_serializes_as_zero(self):
        """0.0 Objetivo must serialize as 0.0, NOT null."""
        row = _make_row(objetivo=0.0, tend_vs_obj=None)
        structs = _simple_struct([row])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        data_rows = result["sheets"][0]["sections"][0]["rows"]
        assert data_rows[0]["Objetivo"] == 0.0, "0.0 Objetivo must serialize as 0.0, not null"
        # 0.0 Objetivo → tend_vs_obj is null (cannot divide by zero)
        assert data_rows[0]["Tend vs Obj (%)"] is None

    def test_positive_objetivo_serializes_as_float(self):
        """A positive cupo value serializes as a float."""
        row = _make_row(objetivo=1500.0, tend_vs_obj=0.8)
        structs = _simple_struct([row])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        data_rows = result["sheets"][0]["sections"][0]["rows"]
        assert data_rows[0]["Objetivo"] == 1500.0
        assert data_rows[0]["Tend vs Obj (%)"] == 0.8

    def test_null_none_objetivo_serializes_as_null(self):
        """Python None in Objetivo (NaT-like) also serializes as null."""
        row = _make_row(objetivo=None, tend_vs_obj=None)
        # Build the section DF — None becomes NaN when stored in a float column
        structs = _simple_struct([row])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        data_rows = result["sheets"][0]["sections"][0]["rows"]
        assert data_rows[0]["Objetivo"] is None


# ---------------------------------------------------------------------------
# TC-02: is_subtotal flag for the 3 special labels
# ---------------------------------------------------------------------------

class TestIsSubtotalFlag:
    @pytest.mark.parametrize("label", [_SUBTOTAL_CC, _SUC_SIN_DIRECTA, _TOTAL_SIN_SMK])
    def test_subtotal_label_rows_have_is_subtotal_true(self, label):
        """Rows whose Sucursal is one of the 3 special labels must have is_subtotal: true."""
        subtotal_row = _make_row(sucursal=label)
        structs = _simple_struct([subtotal_row])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        rows = result["sheets"][0]["sections"][0]["rows"]
        matching = [r for r in rows if r["Sucursal"] == label]
        assert len(matching) == 1
        assert matching[0]["is_subtotal"] is True

    def test_regular_row_has_is_subtotal_false(self):
        """A normal data row must have is_subtotal: false."""
        row = _make_row(sucursal="CASA CENTRAL")
        structs = _simple_struct([row])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        rows = result["sheets"][0]["sections"][0]["rows"]
        assert rows[0]["is_subtotal"] is False

    def test_mixed_rows_flags_correctly(self):
        """Mixed rows: data rows → false, subtotal rows → true."""
        rows_data = [
            _make_row(sucursal="CASA CENTRAL"),
            _make_row(sucursal="SUC1"),
            _make_row(sucursal=_SUBTOTAL_CC),
            _make_row(sucursal=_SUC_SIN_DIRECTA),
            _make_row(sucursal=_TOTAL_SIN_SMK),
        ]
        structs = _simple_struct(rows_data)
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        rows = result["sheets"][0]["sections"][0]["rows"]
        flags = {r["Sucursal"]: r["is_subtotal"] for r in rows}
        assert flags["CASA CENTRAL"] is False
        assert flags["SUC1"] is False
        assert flags[_SUBTOTAL_CC] is True
        assert flags[_SUC_SIN_DIRECTA] is True
        assert flags[_TOTAL_SIN_SMK] is True


# ---------------------------------------------------------------------------
# TC-03: Single section vs marca_splits sections
# ---------------------------------------------------------------------------

class TestSectionStructure:
    def test_no_marca_splits_produces_single_section(self):
        """Without marca_splits, each sheet has exactly one section."""
        row = _make_row()
        structs = _simple_struct([row])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        sheet = result["sheets"][0]
        assert len(sheet["sections"]) == 1
        assert sheet["sections"][0]["label"] == "CERVEZAS"

    def test_marca_splits_produces_multiple_sections(self):
        """With marca_splits, sections are preserved per split group."""
        row1 = _make_row(sucursal="CASA CENTRAL", generico="VINOS FINOS (sin QUARA)")
        row2 = _make_row(sucursal="CASA CENTRAL", generico="QUARA")

        df1 = _make_section_df([row1])
        df2 = _make_section_df([row2])

        sections = [
            _SheetSection(label="VINOS FINOS (sin QUARA)", df=df1),
            _SheetSection(label="QUARA", df=df2),
        ]
        struct = _SheetStruct(logical_generico="VINOS FINOS", sections=sections, note=None)
        result = to_datos_json([struct], _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        sheet = result["sheets"][0]
        assert len(sheet["sections"]) == 2
        assert sheet["sections"][0]["label"] == "VINOS FINOS (sin QUARA)"
        assert sheet["sections"][1]["label"] == "QUARA"
        # Each section must have its own rows
        assert len(sheet["sections"][0]["rows"]) == 1
        assert len(sheet["sections"][1]["rows"]) == 1

    def test_multiple_sheets_in_response(self):
        """Multiple structs produce multiple sheets."""
        struct1 = _SheetStruct(
            logical_generico="CERVEZAS",
            sections=[_SheetSection(label="CERVEZAS", df=_make_section_df([_make_row()]))],
        )
        struct2 = _SheetStruct(
            logical_generico="AGUAS DANONE",
            sections=[_SheetSection(label="AGUAS DANONE", df=_make_section_df([_make_row(generico="AGUAS DANONE")]))],
        )
        result = to_datos_json([struct1, struct2], _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        assert len(result["sheets"]) == 2
        assert result["sheets"][0]["generico"] == "CERVEZAS"
        assert result["sheets"][1]["generico"] == "AGUAS DANONE"

    def test_empty_structs_produces_empty_sheets(self):
        """Empty structs list → sheets is an empty array."""
        result = to_datos_json([], _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)
        assert result["sheets"] == []


# ---------------------------------------------------------------------------
# TC-04: meta fields — col_n1 / col_n2 names and info_dias
# ---------------------------------------------------------------------------

class TestMetaContract:
    def test_meta_col_n1_col_n2_carry_human_names(self):
        """meta.col_n1 and meta.col_n2 must carry the dynamic day column human names."""
        structs = _simple_struct([_make_row()])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        meta = result["meta"]
        assert meta["col_n1"] == _COL_N1
        assert meta["col_n2"] == _COL_N2

    def test_row_uses_canonical_col_keys(self):
        """Row data keyed by canonical 'col_n1'/'col_n2', not the dynamic name."""
        structs = _simple_struct([_make_row(n2=42.0, n1=99.0)])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        row = result["sheets"][0]["sections"][0]["rows"][0]
        assert "col_n2" in row, "Row must use canonical key 'col_n2'"
        assert "col_n1" in row, "Row must use canonical key 'col_n1'"
        assert row["col_n2"] == 42.0
        assert row["col_n1"] == 99.0
        # Dynamic name must NOT appear as a key in the row
        assert _COL_N2 not in row
        assert _COL_N1 not in row

    def test_meta_info_dias_present(self):
        """meta.info_dias carries the day stats dict."""
        info = {"Dias Habiles": 20, "Dias Transcurridos": 10, "Dias Faltantes": 10}
        structs = _simple_struct([_make_row()])
        result = to_datos_json(structs, info, _COL_N1, _COL_N2, con_objetivo=True)

        assert result["meta"]["info_dias"]["Dias Habiles"] == 20
        assert result["meta"]["info_dias"]["Dias Transcurridos"] == 10
        assert result["meta"]["info_dias"]["Dias Faltantes"] == 10

    def test_meta_con_objetivo_reflected(self):
        """meta.con_objetivo reflects the con_objetivo parameter."""
        structs = _simple_struct([_make_row()])
        result_true = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)
        result_false = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=False)

        assert result_true["meta"]["con_objetivo"] is True
        assert result_false["meta"]["con_objetivo"] is False


# ---------------------------------------------------------------------------
# TC-05: sin_prvta signal on sheet
# ---------------------------------------------------------------------------

class TestSinPrvtaSignal:
    def test_struct_with_note_sets_sin_prvta_true(self):
        """Sheet with a note (from sin_prvta list) must have sin_prvta: true."""
        struct = _SheetStruct(
            logical_generico="FRATELLI B",
            sections=[_SheetSection(label="FRATELLI B", df=_make_section_df([_make_row()]))],
            note="Nota: FRATELLI B excluye documentos PRVTA",
        )
        result = to_datos_json([struct], _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        sheet = result["sheets"][0]
        assert sheet.get("sin_prvta") is True

    def test_struct_without_note_does_not_have_sin_prvta_true(self):
        """Sheet without a note must not have sin_prvta: true."""
        struct = _SheetStruct(
            logical_generico="CERVEZAS",
            sections=[_SheetSection(label="CERVEZAS", df=_make_section_df([_make_row()]))],
            note=None,
        )
        result = to_datos_json([struct], _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        sheet = result["sheets"][0]
        assert sheet.get("sin_prvta") is not True

    def test_mixed_sheets_sin_prvta_only_on_flagged(self):
        """Only the flagged sheet has sin_prvta: true; others do not."""
        s1 = _SheetStruct(
            logical_generico="FRATELLI B",
            sections=[_SheetSection(label="FRATELLI B", df=_make_section_df([_make_row()]))],
            note="some note",
        )
        s2 = _SheetStruct(
            logical_generico="CERVEZAS",
            sections=[_SheetSection(label="CERVEZAS", df=_make_section_df([_make_row()]))],
            note=None,
        )
        result = to_datos_json([s1, s2], _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)

        sheets_by_gen = {s["generico"]: s for s in result["sheets"]}
        assert sheets_by_gen["FRATELLI B"].get("sin_prvta") is True
        assert sheets_by_gen["CERVEZAS"].get("sin_prvta") is not True


# ---------------------------------------------------------------------------
# TC-06: top-level schema shape
# ---------------------------------------------------------------------------

class TestTopLevelSchema:
    def test_top_level_keys_present(self):
        """Response must have 'meta' and 'sheets' at top level."""
        result = to_datos_json([], _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)
        assert "meta" in result
        assert "sheets" in result

    def test_meta_has_required_keys(self):
        """meta must have col_n1, col_n2, info_dias, con_objetivo."""
        structs = _simple_struct([_make_row()])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)
        meta = result["meta"]
        for key in ("col_n1", "col_n2", "info_dias", "con_objetivo"):
            assert key in meta, f"meta must have key '{key}'"

    def test_sheet_has_required_keys(self):
        """Each sheet must have 'generico', 'note', and 'sections'."""
        structs = _simple_struct([_make_row()])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)
        sheet = result["sheets"][0]
        for key in ("generico", "note", "sections"):
            assert key in sheet, f"sheet must have key '{key}'"

    def test_row_has_required_keys(self):
        """Each row must have Sucursal, col_n2, col_n1, Total Ventas, Tendencia,
        MMAA, MA, Objetivo, Tend vs Obj (%), is_subtotal."""
        structs = _simple_struct([_make_row(objetivo=100.0, tend_vs_obj=0.9)])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)
        row = result["sheets"][0]["sections"][0]["rows"][0]
        expected_keys = {
            "Sucursal", "col_n2", "col_n1", "Total Ventas", "Tendencia",
            "MMAA", "MA", "Objetivo", "Tend vs Obj (%)", "is_subtotal",
        }
        for key in expected_keys:
            assert key in row, f"row must have key '{key}'"

    def test_generico_column_dropped_from_rows(self):
        """The 'Generico' column must not appear in individual row dicts."""
        structs = _simple_struct([_make_row()])
        result = to_datos_json(structs, _make_info_dias(), _COL_N1, _COL_N2, con_objetivo=True)
        row = result["sheets"][0]["sections"][0]["rows"][0]
        assert "Generico" not in row, "Generico column must be dropped from individual rows"
