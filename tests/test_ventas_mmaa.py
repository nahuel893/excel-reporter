"""
Tests para las columnas MMAA (Mismo Mes Año Anterior) y Var%.

Cubre los escenarios TS-001 a TS-012 del spec ventas-mmaa.
"""
import pytest
import pandas as pd
from config.settings import COLUMN_NAMES
from src.services.ventas.processor import procesar_ventas_diarias
from src.services.ventas.service import _crear_estilo_ventas


# ---------------------------------------------------------------------------
# Fixtures comunes
# ---------------------------------------------------------------------------

def _make_df_ventas_simple(sucursal="SUC1", generico="CERV", marca="CORONA",
                            cantidad=100, cantidad_htls=50):
    """DataFrame de ventas con una fila para una sola fecha."""
    return pd.DataFrame({
        "sucursal": [sucursal],
        "generico": [generico],
        "marca": [marca],
        "fecha": pd.to_datetime(["2026-01-15"]),
        "cantidad": [cantidad],
        "cantidad_htls": [cantidad_htls],
        "monto": [5000],
    })


def _make_df_mmaa(sucursal="SUC1", generico="CERV", marca="CORONA",
                  cantidad=500, cantidad_htls=250):
    """DataFrame df_mmaa con una fila."""
    return pd.DataFrame({
        "sucursal": [sucursal],
        "generico": [generico],
        "marca": [marca],
        "cantidad": [cantidad],
        "cantidad_htls": [cantidad_htls],
    })


def _procesar(df_ventas=None, df_mmaa=None, col_cantidad="cantidad"):
    """Helper que llama a procesar_ventas_diarias con parámetros mínimos."""
    if df_ventas is None:
        df_ventas = _make_df_ventas_simple()
    return procesar_ventas_diarias(
        df_ventas,
        fecha_desde="2026-01-01",
        fecha_hasta="2026-01-31",
        col_cantidad=col_cantidad,
        df_mmaa=df_mmaa,
    )


# ---------------------------------------------------------------------------
# TS-001: MMAA correcto y Var% como decimal
# ---------------------------------------------------------------------------

class TestTS001MmaaCorrectoVarDecimal:
    """TS-001: df_mmaa tiene (SUC1,CERV,CORONA,cantidad=500), total_marca=100 → mmaa=500, var=0.2."""

    def test_mmaa_valor_correcto(self):
        df_mmaa = _make_df_mmaa(cantidad=500)
        resultado = _procesar(df_mmaa=df_mmaa)
        assert resultado[COLUMN_NAMES["mmaa_marca"]].iloc[0] == 500

    def test_var_valor_correcto(self):
        """total_marca=100, mmaa=500 → var = 100/500 = 0.2."""
        df_mmaa = _make_df_mmaa(cantidad=500)
        resultado = _procesar(df_mmaa=df_mmaa)
        var = resultado[COLUMN_NAMES["var_mmaa_marca"]].iloc[0]
        assert abs(var - 0.2) < 1e-9


# ---------------------------------------------------------------------------
# TS-002: MMAA=0 → None y Var% None
# ---------------------------------------------------------------------------

class TestTS002MmaaZero:
    """TS-002: MMAA=0 en df_mmaa → columna MMAA None, Var% None."""

    def test_mmaa_cero_es_none(self):
        df_mmaa = _make_df_mmaa(cantidad=0)
        resultado = _procesar(df_mmaa=df_mmaa)
        assert resultado[COLUMN_NAMES["mmaa_marca"]].iloc[0] is None

    def test_var_mmaa_cero_es_none(self):
        df_mmaa = _make_df_mmaa(cantidad=0)
        resultado = _procesar(df_mmaa=df_mmaa)
        assert resultado[COLUMN_NAMES["var_mmaa_marca"]].iloc[0] is None


# ---------------------------------------------------------------------------
# TS-003: Combinacion no encontrada → ambas None
# ---------------------------------------------------------------------------

class TestTS003CombinacionAusente:
    """TS-003: df_mmaa no tiene la combinación (SUC1,CERV,CORONA) → ambas None."""

    def test_mmaa_ausente_es_none(self):
        df_mmaa = _make_df_mmaa(sucursal="OTRA", generico="OTRA", marca="OTRA")
        resultado = _procesar(df_mmaa=df_mmaa)
        assert resultado[COLUMN_NAMES["mmaa_marca"]].iloc[0] is None

    def test_var_ausente_es_none(self):
        df_mmaa = _make_df_mmaa(sucursal="OTRA", generico="OTRA", marca="OTRA")
        resultado = _procesar(df_mmaa=df_mmaa)
        assert resultado[COLUMN_NAMES["var_mmaa_marca"]].iloc[0] is None


# ---------------------------------------------------------------------------
# TS-004: df_mmaa vacío → todos None
# ---------------------------------------------------------------------------

class TestTS004MmaaVacio:
    """TS-004: df_mmaa vacío → todas las filas tienen MMAA=None y Var%=None."""

    def test_mmaa_vacio_es_none(self):
        df_mmaa = pd.DataFrame(columns=["sucursal", "generico", "marca", "cantidad", "cantidad_htls"])
        resultado = _procesar(df_mmaa=df_mmaa)
        assert resultado[COLUMN_NAMES["mmaa_marca"]].iloc[0] is None

    def test_var_mmaa_vacio_es_none(self):
        df_mmaa = pd.DataFrame(columns=["sucursal", "generico", "marca", "cantidad", "cantidad_htls"])
        resultado = _procesar(df_mmaa=df_mmaa)
        assert resultado[COLUMN_NAMES["var_mmaa_marca"]].iloc[0] is None


# ---------------------------------------------------------------------------
# TS-005: df_mmaa=None (default) → todos None, sin crash
# ---------------------------------------------------------------------------

class TestTS005MmaaNone:
    """TS-005: df_mmaa=None (default) → no crash, MMAA y Var% son None."""

    def test_sin_df_mmaa_no_explota(self):
        resultado = _procesar(df_mmaa=None)
        assert resultado is not None
        assert len(resultado) > 0

    def test_mmaa_es_none_cuando_no_se_pasa(self):
        resultado = _procesar(df_mmaa=None)
        assert resultado[COLUMN_NAMES["mmaa_marca"]].iloc[0] is None

    def test_var_es_none_cuando_no_se_pasa(self):
        resultado = _procesar(df_mmaa=None)
        assert resultado[COLUMN_NAMES["var_mmaa_marca"]].iloc[0] is None


# ---------------------------------------------------------------------------
# TS-006: Var% es decimal (no porcentaje ×100)
# ---------------------------------------------------------------------------

class TestTS006VarEsDecimal:
    """TS-006: total=115, mmaa=100 → var=1.15 (no 115)."""

    def test_var_es_decimal_no_porcentaje(self):
        # Ventas de 115 unidades
        df_ventas = _make_df_ventas_simple(cantidad=115)
        df_mmaa = _make_df_mmaa(cantidad=100)
        resultado = _procesar(df_ventas=df_ventas, df_mmaa=df_mmaa)
        var = resultado[COLUMN_NAMES["var_mmaa_marca"]].iloc[0]
        assert abs(var - 1.15) < 1e-9
        assert var < 10  # definitivamente no es 115


# ---------------------------------------------------------------------------
# TS-010: HTLs usa cantidad_htls
# ---------------------------------------------------------------------------

class TestTS010HtlsUsaCantidadHtls:
    """TS-010: col_cantidad='cantidad_htls' → MMAA viene de cantidad_htls del df_mmaa."""

    def test_htls_usa_columna_correcta(self):
        # cantidad=500 pero cantidad_htls=250
        df_mmaa = _make_df_mmaa(cantidad=500, cantidad_htls=250)
        resultado = _procesar(df_mmaa=df_mmaa, col_cantidad="cantidad_htls")
        assert resultado[COLUMN_NAMES["mmaa_marca"]].iloc[0] == 250

    def test_htls_var_usa_cantidad_htls(self):
        """total_htls=50 (ventas fixture), mmaa_htls=250 → var=50/250=0.2."""
        df_mmaa = _make_df_mmaa(cantidad=500, cantidad_htls=250)
        resultado = _procesar(df_mmaa=df_mmaa, col_cantidad="cantidad_htls")
        var = resultado[COLUMN_NAMES["var_mmaa_marca"]].iloc[0]
        assert abs(var - (50 / 250)) < 1e-9


# ---------------------------------------------------------------------------
# TS-011: MMAA en subtotal_cols, Var% no
# ---------------------------------------------------------------------------

class TestTS011SubtotalCols:
    """TS-011: MMAA debe estar en subtotal_columns; Var% NO."""

    def test_mmaa_en_subtotal_columns(self):
        style = _crear_estilo_ventas(columnas_dias=[], info_dias={})
        assert COLUMN_NAMES["mmaa_marca"] in style.subtotal_columns

    def test_var_no_en_subtotal_columns(self):
        style = _crear_estilo_ventas(columnas_dias=[], info_dias={})
        assert COLUMN_NAMES["var_mmaa_marca"] not in style.subtotal_columns


# ---------------------------------------------------------------------------
# TS-012: Orden de columnas — mmaa después de total, var después de mmaa
# ---------------------------------------------------------------------------

class TestTS012ColumnOrder:
    """TS-012: Orden marca: Total | Tend | Cupo | CupoVsTend | MMAA | Var% | Cob | Monto | Desc | %Desc"""

    def test_tend_despues_de_total(self):
        resultado = _procesar(df_mmaa=_make_df_mmaa())
        cols = list(resultado.columns)
        idx_total = cols.index(COLUMN_NAMES["total_marca"])
        idx_tend = cols.index(COLUMN_NAMES["tend_marca"])
        assert idx_tend == idx_total + 1

    def test_mmaa_despues_de_cupo_vs_tend(self):
        resultado = _procesar(df_mmaa=_make_df_mmaa())
        cols = list(resultado.columns)
        idx_cupo_vs = cols.index(COLUMN_NAMES["cupo_vs_tend_marca"])
        idx_mmaa = cols.index(COLUMN_NAMES["mmaa_marca"])
        assert idx_mmaa == idx_cupo_vs + 1

    def test_var_despues_de_mmaa(self):
        resultado = _procesar(df_mmaa=_make_df_mmaa())
        cols = list(resultado.columns)
        idx_mmaa = cols.index(COLUMN_NAMES["mmaa_marca"])
        idx_var = cols.index(COLUMN_NAMES["var_mmaa_marca"])
        assert idx_var == idx_mmaa + 1
