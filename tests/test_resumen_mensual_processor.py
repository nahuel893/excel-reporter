"""
Tests for resumen_mensual processor rewrite (Phase 2 — T-013 to T-018).

Covers:
- T-013: Column headers 'MMAA'/'MA', column order, no rounding (PRIMARY RULE), dash number_format
- T-014: DIRECTA SUCURSALES presence
- T-015: Objetivo left-join + tend_vs_obj computation
- T-016: _segregar_directa_sucursales helper in service

These tests follow Strict TDD: written BEFORE implementation.
"""
import pandas as pd
import pytest
from unittest.mock import patch, Mock
from pathlib import Path

from src.services.resumen_mensual.processor import procesar_resumen_mensual
from src.services.resumen_mensual.service import (
    ResumenMensualService,
    ResumenMensualConfig,
    _crear_estilo_resumen,
    _segregar_directa_sucursales,
)
from src.core.data_loader import DataLoader


# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------

def _df_mes(sucursales, genericos, cantidades, id_rutas=None):
    """Build a basic df_ventas_mes fixture."""
    n = len(sucursales)
    return pd.DataFrame({
        "sucursal": sucursales,
        "generico": genericos,
        "id_ruta": id_rutas if id_rutas is not None else [1] * n,
        "cantidad": cantidades,
    })


def _df_dias_simple(sucursal="SUC1", generico="CERVEZAS", fecha="2026-02-26", cantidad=10):
    return pd.DataFrame({
        "sucursal": [sucursal],
        "generico": [generico],
        "fecha": pd.to_datetime([fecha]),
        "id_ruta": [1],
        "cantidad": [cantidad],
    })


def _df_vacio(cols=None):
    cols = cols or ["sucursal", "generico", "cantidad"]
    return pd.DataFrame(columns=cols)


def _run_processor(
    df_mes=None,
    df_dias=None,
    df_ma=None,
    df_aa=None,
    df_cupos=None,
    factor=1.0,
    con_objetivo=False,
    apply_segregation=True,
):
    """Convenience wrapper: runs procesar_resumen_mensual with mocked factor.

    By default simulates the service pipeline by applying _segregar_directa_sucursales
    + groupby before calling the processor, matching what the service does.
    Set apply_segregation=False to pass data directly to processor as-is.
    """
    if df_mes is None:
        df_mes = _df_mes(["SUC1"], ["CERVEZAS"], [100])
    if df_dias is None:
        df_dias = _df_dias_simple()
    if df_ma is None:
        df_ma = _df_vacio()
    if df_aa is None:
        df_aa = _df_vacio()
    if df_cupos is None:
        df_cupos = _df_vacio(["sucursal", "generico", "cupo"])

    if apply_segregation:
        # Simulate service pipeline: segregar DIRECTA, then groupby (drops id_ruta)
        df_mes = _segregar_directa_sucursales(df_mes)
        if not df_mes.empty and "cantidad" in df_mes.columns:
            df_mes = df_mes.groupby(["sucursal", "generico"], as_index=False)["cantidad"].sum()

        df_dias = _segregar_directa_sucursales(df_dias)
        if not df_dias.empty and "fecha" in df_dias.columns:
            df_dias = df_dias.groupby(["sucursal", "generico", "fecha"], as_index=False)["cantidad"].sum()

        df_ma = _segregar_directa_sucursales(df_ma)
        if not df_ma.empty and "cantidad" in df_ma.columns:
            df_ma = df_ma.groupby(["sucursal", "generico"], as_index=False)["cantidad"].sum()

        df_aa = _segregar_directa_sucursales(df_aa)
        if not df_aa.empty and "cantidad" in df_aa.columns:
            df_aa = df_aa.groupby(["sucursal", "generico"], as_index=False)["cantidad"].sum()

    with patch(
        "src.services.resumen_mensual.processor.calcular_factor_tendencia",
        return_value=factor,
    ):
        return procesar_resumen_mensual(
            df_mes, df_dias, df_ma, df_aa,
            "2026-02-01", "2026-02-28",
            con_objetivo=con_objetivo,
            df_cupos=df_cupos,
        )


# ===========================================================================
# T-013 — Column headers: MMAA/MA, column order, no rounding
# ===========================================================================

class TestColumnHeaders:
    """T-013: Output DataFrame must use 'MMAA' and 'MA' headers (not the old long names)."""

    def test_header_mmaa_present(self):
        """T-013a: Column 'MMAA' exists in result columns."""
        resultado = _run_processor()
        assert "MMAA" in resultado.columns

    def test_header_ma_present(self):
        """T-013a: Column 'MA' exists in result columns."""
        resultado = _run_processor()
        assert "MA" in resultado.columns

    def test_old_header_ventas_mismo_mes_aa_absent(self):
        """T-013a: Old column name 'Ventas Mismo Mes AA' must NOT be present."""
        resultado = _run_processor()
        assert "Ventas Mismo Mes AA" not in resultado.columns

    def test_old_header_ventas_mes_anterior_absent(self):
        """T-013a: Old column name 'Ventas Mes Anterior' must NOT be present."""
        resultado = _run_processor()
        assert "Ventas Mes Anterior" not in resultado.columns

    def test_column_order_mmaa_before_ma(self):
        """T-013b: 'MMAA' is at position 6, 'MA' at position 7 (MMAA before MA)."""
        resultado = _run_processor()
        cols = list(resultado.columns)
        assert cols[6] == "MMAA"
        assert cols[7] == "MA"

    def test_column_order_full(self):
        """T-013b: All 10 columns in exact order: Sucursal, Generico, DiaN-2, DiaN-1,
        Total Ventas, Tendencia, MMAA, MA, Objetivo, Tend vs Obj (%)."""
        resultado = _run_processor()
        cols = list(resultado.columns)
        assert len(cols) == 10
        assert cols[0] == "Sucursal"
        assert cols[1] == "Generico"
        # cols[2] and cols[3] are dynamic date columns
        assert cols[4] == "Total Ventas"
        assert cols[5] == "Tendencia"
        assert cols[6] == "MMAA"
        assert cols[7] == "MA"
        assert cols[8] == "Objetivo"
        assert cols[9] == "Tend vs Obj (%)"


class TestNoRounding:
    """T-013c: Tendencia must be a float, never rounded/int-cast (PRIMARY RULE)."""

    def test_tendencia_is_float_not_int(self):
        """T-013c: With factor=1.333, tendencia should be float 133.3, not int 133."""
        df_mes = _df_mes(["SUC1"], ["CERVEZAS"], [100])
        resultado = _run_processor(df_mes=df_mes, factor=1.333)
        tendencia = resultado.iloc[0]["Tendencia"]
        # Must be float — PRIMARY RULE: no rounding
        assert isinstance(tendencia, float), (
            f"Tendencia should be float, got {type(tendencia).__name__}: {tendencia}"
        )
        assert tendencia == pytest.approx(133.3, rel=1e-3)

    def test_tendencia_not_rounded(self):
        """T-013c: With factor=1.5 and ventas=101, tendencia=151.5, not 152."""
        df_mes = _df_mes(["SUC1"], ["CERVEZAS"], [101])
        resultado = _run_processor(df_mes=df_mes, factor=1.5)
        tendencia = resultado.iloc[0]["Tendencia"]
        assert tendencia == pytest.approx(151.5, rel=1e-6)
        # Confirm it's truly float (not rounded to 152)
        assert tendencia != 152


class TestZeroNumberFormat:
    """T-013d: _crear_estilo_resumen uses '#,##0;-#,##0;"-"' for day/total/tendency columns."""

    def test_col_n1_number_format_has_dash_for_zero(self):
        """T-013d: Column N-1 uses number_format with '-' for zero display."""
        style = _crear_estilo_resumen(
            {"Dias Habiles": 20, "Dias Transcurridos": 15, "Dias Faltantes": 5},
            "28-02 Sabado",
            "27-02 Viernes",
        )
        col_fmt = style.column_formats["28-02 Sabado"]
        assert col_fmt.number_format == '#,##0;-#,##0;"-"'

    def test_col_n2_number_format_has_dash_for_zero(self):
        """T-013d: Column N-2 uses number_format with '-' for zero display."""
        style = _crear_estilo_resumen(
            {"Dias Habiles": 20, "Dias Transcurridos": 15, "Dias Faltantes": 5},
            "28-02 Sabado",
            "27-02 Viernes",
        )
        col_fmt = style.column_formats["27-02 Viernes"]
        assert col_fmt.number_format == '#,##0;-#,##0;"-"'

    def test_total_ventas_number_format_has_dash_for_zero(self):
        """T-013d: 'Total Ventas' column uses number_format with '-' for zero display."""
        style = _crear_estilo_resumen(
            {"Dias Habiles": 20, "Dias Transcurridos": 15, "Dias Faltantes": 5},
            "28-02 Sabado",
            "27-02 Viernes",
        )
        col_fmt = style.column_formats["Total Ventas"]
        assert col_fmt.number_format == '#,##0;-#,##0;"-"'

    def test_tendencia_number_format_has_dash_for_zero(self):
        """T-013d: 'Tendencia' column uses number_format with '-' for zero display."""
        style = _crear_estilo_resumen(
            {"Dias Habiles": 20, "Dias Transcurridos": 15, "Dias Faltantes": 5},
            "28-02 Sabado",
            "27-02 Viernes",
        )
        col_fmt = style.column_formats["Tendencia"]
        assert col_fmt.number_format == '#,##0;-#,##0;"-"'

    def test_mmaa_number_format_has_dash_for_zero(self):
        """T-013d: 'MMAA' column uses number_format with '-' for zero display."""
        style = _crear_estilo_resumen(
            {"Dias Habiles": 20, "Dias Transcurridos": 15, "Dias Faltantes": 5},
            "28-02 Sabado",
            "27-02 Viernes",
        )
        col_fmt = style.column_formats["MMAA"]
        assert col_fmt.number_format == '#,##0;-#,##0;"-"'

    def test_ma_number_format_has_dash_for_zero(self):
        """T-013d: 'MA' column uses number_format with '-' for zero display."""
        style = _crear_estilo_resumen(
            {"Dias Habiles": 20, "Dias Transcurridos": 15, "Dias Faltantes": 5},
            "28-02 Sabado",
            "27-02 Viernes",
        )
        col_fmt = style.column_formats["MA"]
        assert col_fmt.number_format == '#,##0;-#,##0;"-"'

    def test_objetivo_number_format_has_dash_for_zero(self):
        """T-013d: 'Objetivo' column uses number_format with '-' for zero display."""
        style = _crear_estilo_resumen(
            {"Dias Habiles": 20, "Dias Transcurridos": 15, "Dias Faltantes": 5},
            "28-02 Sabado",
            "27-02 Viernes",
        )
        col_fmt = style.column_formats["Objetivo"]
        assert col_fmt.number_format == '#,##0;-#,##0;"-"'

    def test_tend_vs_obj_keeps_percentage_format(self):
        """T-013d: 'Tend vs Obj (%)' keeps percentage format, NOT the dash-zero format."""
        style = _crear_estilo_resumen(
            {"Dias Habiles": 20, "Dias Transcurridos": 15, "Dias Faltantes": 5},
            "28-02 Sabado",
            "27-02 Viernes",
        )
        col_fmt = style.column_formats["Tend vs Obj (%)"]
        # Must NOT have the dash-zero format
        assert col_fmt.number_format != '#,##0;-#,##0;"-"'
        # Must be a percentage-type format
        assert "%" in col_fmt.number_format or "0.0" in col_fmt.number_format


# ===========================================================================
# T-014 — DIRECTA SUCURSALES presence
# ===========================================================================

class TestDirectaSucursales:
    """T-014: DIRECTA SUCURSALES row appears when id_ruta=100 + sucursal != 'CASA CENTRAL'."""

    def test_directa_sucursales_row_present(self):
        """T-014: When a non-CASA CENTRAL sucursal has id_ruta=100, it becomes DIRECTA SUCURSALES."""
        df_mes = _df_mes(
            sucursales=["3 - SUCURSAL A", "3 - SUCURSAL A"],
            genericos=["CERVEZAS", "CERVEZAS"],
            cantidades=[100, 50],
            id_rutas=[100, 100],
        )
        resultado = _run_processor(df_mes=df_mes)
        assert "DIRECTA SUCURSALES" in resultado["Sucursal"].values

    def test_directa_sucursales_not_present_for_casa_central(self):
        """T-014: CASA CENTRAL with id_ruta=100 does NOT become DIRECTA SUCURSALES."""
        df_mes = _df_mes(
            sucursales=["CASA CENTRAL"],
            genericos=["CERVEZAS"],
            cantidades=[100],
            id_rutas=[100],
        )
        resultado = _run_processor(df_mes=df_mes)
        assert "DIRECTA SUCURSALES" not in resultado["Sucursal"].values
        assert "CASA CENTRAL" in resultado["Sucursal"].values

    def test_directa_sucursales_aggregates_multiple_rutas_100(self):
        """T-014: Multiple non-CC sucursales with id_ruta=100 aggregate into one DIRECTA row."""
        df_mes = pd.DataFrame({
            "sucursal": ["3 - SUC A", "4 - SUC B"],
            "generico": ["CERVEZAS", "CERVEZAS"],
            "id_ruta": [100, 100],
            "cantidad": [60, 40],
        })
        resultado = _run_processor(df_mes=df_mes)
        directa_rows = resultado[resultado["Sucursal"] == "DIRECTA SUCURSALES"]
        assert len(directa_rows) == 1
        assert directa_rows.iloc[0]["Total Ventas"] == pytest.approx(100)


# ===========================================================================
# T-015 — Objetivo left-join + tend_vs_obj
# ===========================================================================

class TestObjetivoYTendVsObj:
    """T-015: objetivo comes from df_cupos left-join; tend_vs_obj = tendencia/objetivo."""

    def test_objetivo_from_cupos_when_present(self):
        """T-015a: When cupos has a matching row, Objetivo is filled from the cupo value."""
        df_mes = _df_mes(["SUC1"], ["CERVEZAS"], [100])
        df_cupos = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cupo": [200.0],
        })
        resultado = _run_processor(df_mes=df_mes, df_cupos=df_cupos, con_objetivo=True)
        assert resultado.iloc[0]["Objetivo"] == pytest.approx(200.0)

    def test_objetivo_none_when_no_matching_cupo(self):
        """T-015a: When cupos has no matching row for a (sucursal, generico), Objetivo is None/NaN."""
        df_mes = _df_mes(["SUC1"], ["CERVEZAS"], [100])
        df_cupos = pd.DataFrame({
            "sucursal": ["OTRA SUC"],
            "generico": ["CERVEZAS"],
            "cupo": [200.0],
        })
        resultado = _run_processor(df_mes=df_mes, df_cupos=df_cupos, con_objetivo=True)
        objetivo = resultado.iloc[0]["Objetivo"]
        assert objetivo is None or pd.isna(objetivo)

    def test_tend_vs_obj_calculated_when_objetivo_positive(self):
        """T-015b: tend_vs_obj = tendencia / objetivo when objetivo > 0."""
        df_mes = _df_mes(["SUC1"], ["CERVEZAS"], [100])
        df_cupos = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cupo": [200.0],
        })
        # factor=1.0 → tendencia=100; objetivo=200 → tend_vs_obj = 100/200 = 0.5
        resultado = _run_processor(
            df_mes=df_mes, df_cupos=df_cupos, factor=1.0, con_objetivo=True
        )
        assert resultado.iloc[0]["Tend vs Obj (%)"] == pytest.approx(0.5, rel=1e-6)

    def test_tend_vs_obj_none_when_objetivo_is_none(self):
        """T-015b: tend_vs_obj is None when objetivo is None (no matching cupo)."""
        df_mes = _df_mes(["SUC1"], ["CERVEZAS"], [100])
        df_cupos = _df_vacio(["sucursal", "generico", "cupo"])
        resultado = _run_processor(df_mes=df_mes, df_cupos=df_cupos, con_objetivo=True)
        tend = resultado.iloc[0]["Tend vs Obj (%)"]
        assert tend is None or pd.isna(tend)

    def test_tend_vs_obj_none_when_objetivo_zero(self):
        """T-015b: tend_vs_obj is None when objetivo == 0 (division by zero guard)."""
        df_mes = _df_mes(["SUC1"], ["CERVEZAS"], [100])
        df_cupos = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cupo": [0.0],
        })
        resultado = _run_processor(df_mes=df_mes, df_cupos=df_cupos, con_objetivo=True)
        tend = resultado.iloc[0]["Tend vs Obj (%)"]
        assert tend is None or pd.isna(tend)

    def test_objetivo_none_when_con_objetivo_false(self):
        """T-015b: Objetivo and Tend vs Obj (%) are None when con_objetivo=False, even with cupos."""
        df_mes = _df_mes(["SUC1"], ["CERVEZAS"], [100])
        df_cupos = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cupo": [200.0],
        })
        resultado = _run_processor(df_mes=df_mes, df_cupos=df_cupos, con_objetivo=False)
        assert resultado.iloc[0]["Objetivo"] is None or pd.isna(resultado.iloc[0]["Objetivo"])
        tend = resultado.iloc[0]["Tend vs Obj (%)"]
        assert tend is None or pd.isna(tend)


# ===========================================================================
# T-016 — _segregar_directa_sucursales helper
# ===========================================================================

class TestSegregarDirectaSucursales:
    """T-016: _segregar_directa_sucursales(df) renames id_ruta=100 + sucursal != CASA CENTRAL."""

    def test_non_cc_ruta_100_renamed_to_directa(self):
        """T-016: Row with id_ruta=100, sucursal='3 - SUC A' → sucursal='DIRECTA SUCURSALES'."""
        df = pd.DataFrame({
            "sucursal": ["3 - SUC A"],
            "generico": ["CERVEZAS"],
            "id_ruta": [100],
            "cantidad": [50],
        })
        result = _segregar_directa_sucursales(df)
        assert result.iloc[0]["sucursal"] == "DIRECTA SUCURSALES"

    def test_cc_ruta_100_not_renamed(self):
        """T-016: Row with id_ruta=100, sucursal='CASA CENTRAL' → NOT renamed."""
        df = pd.DataFrame({
            "sucursal": ["CASA CENTRAL"],
            "generico": ["CERVEZAS"],
            "id_ruta": [100],
            "cantidad": [50],
        })
        result = _segregar_directa_sucursales(df)
        assert result.iloc[0]["sucursal"] == "CASA CENTRAL"

    def test_other_rutas_not_renamed(self):
        """T-016: Row with id_ruta=81, sucursal='CASA CENTRAL' → NOT renamed."""
        df = pd.DataFrame({
            "sucursal": ["CASA CENTRAL"],
            "generico": ["CERVEZAS"],
            "id_ruta": [81],
            "cantidad": [50],
        })
        result = _segregar_directa_sucursales(df)
        assert result.iloc[0]["sucursal"] == "CASA CENTRAL"

    def test_original_df_not_mutated(self):
        """T-016: Original DataFrame is not mutated (uses copy internally)."""
        df = pd.DataFrame({
            "sucursal": ["3 - SUC A"],
            "generico": ["CERVEZAS"],
            "id_ruta": [100],
            "cantidad": [50],
        })
        original_suc = df.iloc[0]["sucursal"]
        _segregar_directa_sucursales(df)
        assert df.iloc[0]["sucursal"] == original_suc  # original unchanged

    def test_no_id_ruta_column_returns_df_unchanged(self):
        """T-016: If 'id_ruta' not in columns, returns df unchanged without error."""
        df = pd.DataFrame({
            "sucursal": ["3 - SUC A"],
            "generico": ["CERVEZAS"],
            "cantidad": [50],
        })
        result = _segregar_directa_sucursales(df)
        assert result.iloc[0]["sucursal"] == "3 - SUC A"

    def test_multiple_rows_only_ruta_100_non_cc_renamed(self):
        """T-016: Mixed rows — only id_ruta=100 + non-CC rows are renamed."""
        df = pd.DataFrame({
            "sucursal": ["CASA CENTRAL", "3 - SUC A", "4 - SUC B", "5 - SUC C"],
            "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS", "CERVEZAS"],
            "id_ruta": [100, 100, 81, 93],
            "cantidad": [100, 50, 30, 20],
        })
        result = _segregar_directa_sucursales(df)
        sucursales = result["sucursal"].tolist()
        assert sucursales[0] == "CASA CENTRAL"     # CC ruta 100 — no change
        assert sucursales[1] == "DIRECTA SUCURSALES"  # non-CC ruta 100 — renamed
        assert sucursales[2] == "4 - SUC B"         # non-CC ruta 81 — no change
        assert sucursales[3] == "5 - SUC C"         # non-CC ruta 93 — no change
