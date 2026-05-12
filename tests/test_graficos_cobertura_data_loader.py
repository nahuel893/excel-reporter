"""Tests for the 5 DataLoader methods + table_exists added for graficos-cobertura."""
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.core.data_loader import DataLoader


def _make_loader_with_mock_query(return_df: pd.DataFrame) -> tuple[DataLoader, MagicMock]:
    """Helper: build a DataLoader whose execute_query returns return_df."""
    loader = DataLoader(engine=MagicMock())
    mock = MagicMock(return_value=return_df)
    loader.execute_query = mock
    return loader, mock


class TestTableExists:
    """RF-007 helper: table_exists via information_schema."""

    def test_returns_true_when_table_exists(self):
        df = pd.DataFrame({"existe": [True]})
        loader, mock = _make_loader_with_mock_query(df)

        assert loader.table_exists("gold", "cob_sucursal_aguas") is True

        query, params = mock.call_args.args[0], mock.call_args.args[1]
        assert "information_schema.tables" in query
        assert params == {"schema": "gold", "table_name": "cob_sucursal_aguas"}

    def test_returns_false_when_table_absent(self):
        df = pd.DataFrame({"existe": [False]})
        loader, _ = _make_loader_with_mock_query(df)

        assert loader.table_exists("gold", "inexistente") is False

    def test_returns_false_on_empty_result(self):
        df = pd.DataFrame({"existe": []})
        loader, _ = _make_loader_with_mock_query(df)

        assert loader.table_exists("gold", "whatever") is False


class TestGetCoberturaGraficosMarcaRuta:
    """RF-003: get_cobertura_graficos_marca_ruta — preventista-grained per id_ruta."""

    def test_returns_expected_columns(self):
        df = pd.DataFrame({
            "anio": [2026, 2026],
            "mes": [3, 3],
            "id_ruta": [85, 90],
            "marca": ["SALTA", "HEINEKEN"],
            "clientes": [100, 200],
        })
        loader, mock = _make_loader_with_mock_query(df)

        result = loader.get_cobertura_graficos_marca_ruta(
            id_fuerza_ventas=1, anios=[2025, 2026], id_sucursal=1
        )

        assert list(result.columns) == ["anio", "mes", "id_ruta", "marca", "clientes"]
        assert len(result) == 2

    def test_query_uses_cob_preventista_marca_table(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_graficos_marca_ruta(1, [2025, 2026], 1)
        query = mock.call_args.args[0]
        assert "gold.cob_preventista_marca" in query
        assert "id_sucursal" in query

    def test_passes_fv_and_sucursal_params(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_graficos_marca_ruta(id_fuerza_ventas=2, anios=[2024], id_sucursal=7)
        params = mock.call_args.args[1]
        assert params["fv"] == 2
        assert params["id_sucursal"] == 7
        assert params["anio_0"] == 2024


class TestGetCoberturaGraficosGenericoRuta:
    """RF-005: get_cobertura_graficos_generico_ruta."""

    def test_returns_expected_columns(self):
        df = pd.DataFrame({
            "anio": [2026],
            "mes": [3],
            "id_ruta": [85],
            "generico": ["CERVEZAS"],
            "clientes": [100],
        })
        loader, _ = _make_loader_with_mock_query(df)

        result = loader.get_cobertura_graficos_generico_ruta(1, [2025, 2026], 1)
        assert list(result.columns) == ["anio", "mes", "id_ruta", "generico", "clientes"]

    def test_query_uses_cob_preventista_generico_table(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_graficos_generico_ruta(1, [2025, 2026], 1)
        assert "gold.cob_preventista_generico" in mock.call_args.args[0]


class TestGetCoberturaGraficosMarcaSucursal:
    """RF-002: get_cobertura_graficos_marca_sucursal — aggregated."""

    def test_without_sucursales_returns_all(self):
        df = pd.DataFrame({
            "anio": [2026],
            "mes": [3],
            "marca": ["SALTA"],
            "clientes": [100],
        })
        loader, mock = _make_loader_with_mock_query(df)

        result = loader.get_cobertura_graficos_marca_sucursal(1, [2025, 2026])
        assert list(result.columns) == ["anio", "mes", "marca", "clientes"]
        assert "id_sucursal IN" not in mock.call_args.args[0]

    def test_with_sucursales_adds_filter(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_graficos_marca_sucursal(1, [2025, 2026], sucursales=[3, 4, 5, 16])
        query, params = mock.call_args.args
        assert "id_sucursal IN" in query
        # 4 sucursales -> 4 placeholders
        assert params["suc_0"] == 3
        assert params["suc_3"] == 16

    def test_query_uses_cob_sucursal_marca_table(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_graficos_marca_sucursal(1, [2025])
        assert "gold.cob_sucursal_marca" in mock.call_args.args[0]


class TestGetCoberturaGraficosGenericoSucursal:
    """RF-004: get_cobertura_graficos_generico_sucursal."""

    def test_returns_expected_columns(self):
        df = pd.DataFrame({
            "anio": [2026],
            "mes": [3],
            "generico": ["CERVEZAS"],
            "clientes": [100],
        })
        loader, _ = _make_loader_with_mock_query(df)

        result = loader.get_cobertura_graficos_generico_sucursal(1, [2024, 2025, 2026])
        assert list(result.columns) == ["anio", "mes", "generico", "clientes"]

    def test_query_uses_cob_sucursal_generico(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_graficos_generico_sucursal(1, [2024, 2025, 2026])
        assert "gold.cob_sucursal_generico" in mock.call_args.args[0]


class TestGetCoberturaGraficosAguasSucursal:
    """RF-007: get_cobertura_graficos_aguas_sucursal with information_schema pre-check."""

    def test_returns_data_when_table_exists(self):
        aguas_df = pd.DataFrame({
            "anio": [2026],
            "mes": [3],
            "id_sucursal": [1],
            "subdivision_aguas": ["AGUAS SABORIZADAS"],
            "clientes": [50],
        })
        loader = DataLoader(engine=MagicMock())
        loader.table_exists = MagicMock(return_value=True)
        loader.execute_query = MagicMock(return_value=aguas_df)

        result = loader.get_cobertura_graficos_aguas_sucursal(1, [2025, 2026])
        assert len(result) == 1
        assert "subdivision_aguas" in result.columns
        loader.table_exists.assert_called_once_with("gold", "cob_sucursal_aguas")

    def test_returns_empty_df_when_table_missing(self, caplog):
        loader = DataLoader(engine=MagicMock())
        loader.table_exists = MagicMock(return_value=False)
        loader.execute_query = MagicMock()

        import logging
        with caplog.at_level(logging.WARNING):
            result = loader.get_cobertura_graficos_aguas_sucursal(1, [2025, 2026])

        assert result.empty
        assert list(result.columns) == [
            "anio", "mes", "id_sucursal", "subdivision_aguas", "clientes"
        ]
        # execute_query must NOT have been called for the main query
        loader.execute_query.assert_not_called()
        # WARN logged mentioning the table
        assert any(
            "cob_sucursal_aguas" in record.message for record in caplog.records
        )

    def test_does_not_raise_when_table_missing(self):
        loader = DataLoader(engine=MagicMock())
        loader.table_exists = MagicMock(return_value=False)
        loader.execute_query = MagicMock()
        loader.get_cobertura_graficos_aguas_sucursal(1, [2025, 2026])  # no raise


class TestGetCoberturaSucursalMarca:
    """T-001: get_cobertura_sucursal_marca — per-sucursal marca coverage data."""

    def test_returns_expected_columns_with_id_sucursal(self):
        df = pd.DataFrame({
            "anio": [2026],
            "mes": [3],
            "id_sucursal": [1],
            "marca": ["SALTA"],
            "clientes": [100],
        })
        loader, mock = _make_loader_with_mock_query(df)

        result = loader.get_cobertura_sucursal_marca(
            id_fuerza_ventas=1, anios=[2025, 2026], id_sucursales=[1, 3, 4]
        )
        assert list(result.columns) == ["anio", "mes", "id_sucursal", "marca", "clientes"]
        assert len(result) == 1

    def test_query_uses_cob_sucursal_marca_table(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_sucursal_marca(1, [2025, 2026], id_sucursales=[1, 3])
        query = mock.call_args.args[0]
        assert "gold.cob_sucursal_marca" in query

    def test_query_includes_id_sucursal_in_select_and_group_by(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_sucursal_marca(1, [2025, 2026], id_sucursales=[1, 3])
        query = mock.call_args.args[0]
        # id_sucursal must appear in both SELECT and GROUP BY
        assert "id_sucursal" in query
        assert "GROUP BY" in query

    def test_passes_fv_anios_and_sucursales_params(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_sucursal_marca(
            id_fuerza_ventas=2, anios=[2024, 2025], id_sucursales=[1, 3, 4, 5, 16]
        )
        params = mock.call_args.args[1]
        assert params["fv"] == 2
        assert params["anio_0"] == 2024
        assert params["anio_1"] == 2025
        assert params["suc_0"] == 1
        assert params["suc_4"] == 16

    def test_single_anio_and_single_sucursal(self):
        """Triangulation: minimal params."""
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_sucursal_marca(1, [2026], id_sucursales=[7])
        params = mock.call_args.args[1]
        assert params["anio_0"] == 2026
        assert params["suc_0"] == 7


class TestGetCoberturaSucursalGenerico:
    """T-001: get_cobertura_sucursal_generico — per-sucursal generico coverage data."""

    def test_returns_expected_columns_with_id_sucursal(self):
        df = pd.DataFrame({
            "anio": [2026],
            "mes": [3],
            "id_sucursal": [3],
            "generico": ["CERVEZAS"],
            "clientes": [100],
        })
        loader, mock = _make_loader_with_mock_query(df)

        result = loader.get_cobertura_sucursal_generico(
            id_fuerza_ventas=1, anios=[2025, 2026], id_sucursales=[3, 4, 5]
        )
        assert list(result.columns) == ["anio", "mes", "id_sucursal", "generico", "clientes"]
        assert len(result) == 1

    def test_query_uses_cob_sucursal_generico_table(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_sucursal_generico(1, [2025, 2026], id_sucursales=[3])
        query = mock.call_args.args[0]
        assert "gold.cob_sucursal_generico" in query

    def test_query_includes_id_sucursal_in_select_and_group_by(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_sucursal_generico(1, [2025, 2026], id_sucursales=[3])
        query = mock.call_args.args[0]
        assert "id_sucursal" in query
        assert "GROUP BY" in query

    def test_passes_fv_anios_and_sucursales_params(self):
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_sucursal_generico(
            id_fuerza_ventas=2, anios=[2024, 2025, 2026], id_sucursales=[1, 3]
        )
        params = mock.call_args.args[1]
        assert params["fv"] == 2
        assert params["anio_0"] == 2024
        assert params["suc_0"] == 1
        assert params["suc_1"] == 3

    def test_single_anio_and_single_sucursal(self):
        """Triangulation: minimal params."""
        loader, mock = _make_loader_with_mock_query(pd.DataFrame())
        loader.get_cobertura_sucursal_generico(1, [2026], id_sucursales=[6])
        params = mock.call_args.args[1]
        assert params["anio_0"] == 2026
        assert params["suc_0"] == 6
