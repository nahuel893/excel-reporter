"""Tests for universe expansion in resumen-mensual processor.

Spec:
- All sucursales appearing in ANY of the 4 input dataframes (mes, dias, ma, aa)
  must appear in the output for EVERY generico (including sheets where they
  have 0 across all periods).
- Historical columns (MMAA, MA) preserve actual values when present, even when
  current month is 0.
- Combinations with zero across all periods still appear in the output (filled
  with 0); they no longer get dropped.
"""
import pandas as pd

from src.services.resumen_mensual.processor import procesar_resumen_mensual


def _empty_n_dias() -> pd.DataFrame:
    return pd.DataFrame(columns=["sucursal", "generico", "fecha", "cantidad"])


def _df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["sucursal", "generico", "cantidad"])
    return pd.DataFrame(rows)


class TestUniverseExpansion:
    """The result must include every (sucursal × generico) combination from the universe."""

    def test_sucursal_only_in_aa_appears_with_current_zero(self):
        """Sucursal that has data in AA but NOT in mes still appears (existing behavior)."""
        df_mes = _df([{"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "cantidad": 100}])
        df_aa = _df([
            {"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "cantidad": 80},
            {"sucursal": "SUC X", "generico": "CERVEZAS", "cantidad": 50},  # only in aa
        ])
        result = procesar_resumen_mensual(
            df_mes, _empty_n_dias(), pd.DataFrame(), df_aa,
            "2026-05-01", "2026-05-31",
        )
        # SUC X must appear with Total Ventas=0 and MMAA=50
        suc_x = result[result["Sucursal"] == "SUC X"]
        assert len(suc_x) == 1
        assert suc_x["Total Ventas"].iloc[0] == 0
        assert suc_x["MMAA"].iloc[0] == 50

    def test_sucursal_only_in_ma_appears(self):
        """Sucursal that has data ONLY in MA (no mes, no aa) must still appear (NEW behavior)."""
        df_mes = _df([{"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "cantidad": 100}])
        df_aa = _df([{"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "cantidad": 80}])
        df_ma = _df([{"sucursal": "SUC ML ONLY", "generico": "CERVEZAS", "cantidad": 30}])
        result = procesar_resumen_mensual(
            df_mes, _empty_n_dias(), df_ma, df_aa,
            "2026-05-01", "2026-05-31",
        )
        suc_ml = result[result["Sucursal"] == "SUC ML ONLY"]
        assert len(suc_ml) == 1
        assert suc_ml["Total Ventas"].iloc[0] == 0
        assert suc_ml["MMAA"].iloc[0] == 0
        assert suc_ml["MA"].iloc[0] == 30

    def test_all_sucursales_appear_in_every_generico(self):
        """A sucursal in df_mes for one generico must appear with 0 for OTHER genericos."""
        df_mes = _df([
            {"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "cantidad": 100},
            {"sucursal": "SUC X", "generico": "AGUAS DANONE", "cantidad": 50},
        ])
        df_aa = _df([
            {"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "cantidad": 80},
            {"sucursal": "SUC X", "generico": "AGUAS DANONE", "cantidad": 40},
        ])
        result = procesar_resumen_mensual(
            df_mes, _empty_n_dias(), pd.DataFrame(), df_aa,
            "2026-05-01", "2026-05-31",
        )
        # CASA CENTRAL must appear in AGUAS DANONE sheet with all zeros
        # SUC X must appear in CERVEZAS sheet with all zeros
        cc_aguas = result[(result["Sucursal"] == "CASA CENTRAL") & (result["Generico"] == "AGUAS DANONE")]
        x_cervezas = result[(result["Sucursal"] == "SUC X") & (result["Generico"] == "CERVEZAS")]
        assert len(cc_aguas) == 1, "CASA CENTRAL must appear in AGUAS DANONE sheet"
        assert len(x_cervezas) == 1, "SUC X must appear in CERVEZAS sheet"
        assert cc_aguas["Total Ventas"].iloc[0] == 0
        assert x_cervezas["Total Ventas"].iloc[0] == 0

    def test_historical_values_preserved_when_current_zero(self):
        """User warning: 'pueden tener venta historica'. Don't zero out historical
        columns when the current period is 0."""
        df_mes = _df([{"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "cantidad": 100}])
        df_aa = _df([
            {"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "cantidad": 80},
            {"sucursal": "SUC X", "generico": "CERVEZAS", "cantidad": 75},
        ])
        df_ma = _df([
            {"sucursal": "SUC X", "generico": "CERVEZAS", "cantidad": 60},
        ])
        result = procesar_resumen_mensual(
            df_mes, _empty_n_dias(), df_ma, df_aa,
            "2026-05-01", "2026-05-31",
        )
        suc_x = result[result["Sucursal"] == "SUC X"]
        assert suc_x["Total Ventas"].iloc[0] == 0
        assert suc_x["MMAA"].iloc[0] == 75
        assert suc_x["MA"].iloc[0] == 60

    def test_zeros_filled_explicitly(self):
        """All numeric columns are 0 (not NaN/None) when no data exists."""
        df_mes = _df([{"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "cantidad": 100}])
        df_aa = _df([
            {"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "cantidad": 80},
            {"sucursal": "SUC NEW", "generico": "AGUAS", "cantidad": 50},
        ])
        result = procesar_resumen_mensual(
            df_mes, _empty_n_dias(), pd.DataFrame(), df_aa,
            "2026-05-01", "2026-05-31",
        )
        # SUC NEW for CERVEZAS — should appear with all zeros (no data anywhere for it)
        suc_new_cerv = result[(result["Sucursal"] == "SUC NEW") & (result["Generico"] == "CERVEZAS")]
        assert len(suc_new_cerv) == 1
        for col in ["Total Ventas", "Tendencia", "MMAA", "MA"]:
            val = suc_new_cerv[col].iloc[0]
            assert val == 0, f"Column {col} should be 0, got {val!r}"

    def test_marca_split_synthetic_genericos_get_full_universe(self):
        """When marca_splits produces synthetic genericos like 'QUARA' and 'VINOS FINOS (sin QUARA)',
        all sucursales must appear for EACH synthetic generico."""
        df_mes = _df([
            {"sucursal": "CASA CENTRAL", "generico": "VINOS FINOS (sin QUARA)", "cantidad": 100},
            {"sucursal": "SUC X", "generico": "QUARA", "cantidad": 50},
        ])
        df_aa = _df([
            {"sucursal": "CASA CENTRAL", "generico": "VINOS FINOS (sin QUARA)", "cantidad": 80},
            {"sucursal": "SUC X", "generico": "QUARA", "cantidad": 40},
        ])
        result = procesar_resumen_mensual(
            df_mes, _empty_n_dias(), pd.DataFrame(), df_aa,
            "2026-05-01", "2026-05-31",
        )
        # CASA CENTRAL must appear with QUARA generico (cross-product even without data)
        cc_quara = result[(result["Sucursal"] == "CASA CENTRAL") & (result["Generico"] == "QUARA")]
        x_sin_quara = result[(result["Sucursal"] == "SUC X") & (result["Generico"] == "VINOS FINOS (sin QUARA)")]
        assert len(cc_quara) == 1
        assert len(x_sin_quara) == 1
        assert cc_quara["Total Ventas"].iloc[0] == 0
        assert x_sin_quara["Total Ventas"].iloc[0] == 0
