"""
Unit tests for DataLoader methods added for reporte-general-badie:
  - get_ventas_mensuales_ccu
  - get_cobertura_clientes_ccu
"""

from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest

from src.core.data_loader import DataLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loader_with_mock_execute(return_value: pd.DataFrame) -> DataLoader:
    """Return a DataLoader whose execute_query is mocked to return `return_value`."""
    loader = DataLoader(engine=MagicMock())
    loader.execute_query = MagicMock(return_value=return_value)
    return loader


# ---------------------------------------------------------------------------
# get_ventas_mensuales_ccu
# ---------------------------------------------------------------------------


class TestGetVentasMensualesCcu:
    def _fake_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "sucursal": ["CASA CENTRAL"],
                "generico": ["CERVEZAS"],
                "anio": [2026],
                "trimestre": [2],
                "bultos": [1500],
            }
        )

    def test_returns_dataframe_with_expected_columns(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        result = loader.get_ventas_mensuales_ccu("2026-01-01", "2026-04-30")
        assert list(result.columns) == ["sucursal", "generico", "anio", "trimestre", "bultos"]

    def test_passes_correct_params(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        loader.get_ventas_mensuales_ccu("2026-01-01", "2026-04-30")
        _, kwargs = loader.execute_query.call_args
        # Called as positional: (query, params)
        args = loader.execute_query.call_args[0]
        params = args[1]
        assert params["desde"] == "2026-01-01"
        assert params["hasta"] == "2026-04-30"

    def test_sql_does_not_filter_prvta(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        loader.get_ventas_mensuales_ccu("2026-01-01", "2026-04-30")
        sql = loader.execute_query.call_args[0][0]
        assert "PRVTA" not in sql

    def test_sql_filters_ccu_genericos(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        loader.get_ventas_mensuales_ccu("2026-01-01", "2026-04-30")
        sql = loader.execute_query.call_args[0][0]
        assert "CERVEZAS" in sql
        assert "AGUAS DANONE" in sql
        assert "VINOS CCU" in sql
        assert "SIDRAS Y LICORES" in sql

    def test_sql_uses_named_params_desde_hasta(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        loader.get_ventas_mensuales_ccu("2026-01-01", "2026-04-30")
        sql = loader.execute_query.call_args[0][0]
        assert ":desde" in sql
        assert ":hasta" in sql

    def test_sql_groups_by_sucursal_generico_anio_trimestre(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        loader.get_ventas_mensuales_ccu("2026-01-01", "2026-04-30")
        sql = loader.execute_query.call_args[0][0].upper()
        assert "GROUP BY" in sql

    def test_returns_data_intact(self):
        expected = self._fake_df()
        loader = _make_loader_with_mock_execute(expected)
        result = loader.get_ventas_mensuales_ccu("2026-01-01", "2026-04-30")
        pd.testing.assert_frame_equal(result, expected)


# ---------------------------------------------------------------------------
# get_cobertura_clientes_ccu
# ---------------------------------------------------------------------------


class TestGetCoberturaClientesCCU:
    def _fake_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "sucursal": ["CASA CENTRAL"],
                "anio": [2026],
                "trimestre": [2],
                "id_cliente": [1001],
                "bultos": [50],
                "bultos_sin_regalos": [45],
                "bultos_aguas_danone": [10],
                "bultos_aguas_danone_sin_regalos": [10],
                "meses_con_compra": [3],
            }
        )

    def test_returns_dataframe_with_expected_columns(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        result = loader.get_cobertura_clientes_ccu("2026-01-01", "2026-04-30")
        assert list(result.columns) == [
            "sucursal", "anio", "trimestre", "id_cliente",
            "bultos", "bultos_sin_regalos",
            "bultos_aguas_danone", "bultos_aguas_danone_sin_regalos",
            "meses_con_compra",
        ]

    def test_passes_correct_params(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        loader.get_cobertura_clientes_ccu("2026-01-01", "2026-04-30")
        args = loader.execute_query.call_args[0]
        params = args[1]
        assert params["desde"] == "2026-01-01"
        assert params["hasta"] == "2026-04-30"

    def test_sql_does_not_filter_prvta(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        loader.get_cobertura_clientes_ccu("2026-01-01", "2026-04-30")
        sql = loader.execute_query.call_args[0][0]
        assert "PRVTA" not in sql

    def test_sql_filters_all_ccu_genericos(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        loader.get_cobertura_clientes_ccu("2026-01-01", "2026-04-30")
        sql = loader.execute_query.call_args[0][0]
        assert "CERVEZAS" in sql
        assert "AGUAS DANONE" in sql
        assert "VINOS CCU" in sql
        assert "SIDRAS Y LICORES" in sql

    def test_sql_uses_named_params_desde_hasta(self):
        loader = _make_loader_with_mock_execute(self._fake_df())
        loader.get_cobertura_clientes_ccu("2026-01-01", "2026-04-30")
        sql = loader.execute_query.call_args[0][0]
        assert ":desde" in sql
        assert ":hasta" in sql

    def test_empty_result_returns_empty_df_with_correct_columns(self):
        """If no rows returned, should return empty DataFrame with proper columns."""
        loader = _make_loader_with_mock_execute(pd.DataFrame())
        result = loader.get_cobertura_clientes_ccu("2026-01-01", "2026-04-30")
        assert list(result.columns) == [
            "sucursal", "anio", "trimestre", "id_cliente",
            "bultos", "bultos_sin_regalos",
            "bultos_aguas_danone", "bultos_aguas_danone_sin_regalos",
            "meses_con_compra",
        ]
        assert len(result) == 0

    def test_returns_data_intact_when_not_empty(self):
        expected = self._fake_df()
        loader = _make_loader_with_mock_execute(expected)
        result = loader.get_cobertura_clientes_ccu("2026-01-01", "2026-04-30")
        pd.testing.assert_frame_equal(result, expected)
