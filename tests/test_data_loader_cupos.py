"""
Tests for DataLoader.get_cupos_resumen_mensual (T-010).
RF-007: New method queries gold.fact_cupos, filters by periodo+generico,
returns DataFrame with columns [id_sucursal, id_ruta, sucursal, generico, cupo].
Aperturas (AMSTEL, HEINEKEN, etc.) are excluded because only top-level genericos are in the WHERE clause.
"""
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from sqlalchemy import Engine

from src.core.data_loader import DataLoader


def _make_loader_with_mock_engine(query_result_df: pd.DataFrame) -> DataLoader:
    """Create a DataLoader whose execute_query returns the given df."""
    mock_engine = MagicMock(spec=Engine)
    loader = DataLoader(engine=mock_engine)
    loader.execute_query = MagicMock(return_value=query_result_df)
    return loader


class TestGetCuposResumenMensual:
    """T-010: Tests for DataLoader.get_cupos_resumen_mensual."""

    def test_method_exists(self):
        """T-010: DataLoader must have a get_cupos_resumen_mensual method."""
        loader = DataLoader(engine=MagicMock(spec=Engine))
        assert hasattr(loader, "get_cupos_resumen_mensual"), (
            "DataLoader must have get_cupos_resumen_mensual method"
        )
        assert callable(loader.get_cupos_resumen_mensual)

    def test_returns_dataframe(self):
        """T-010: get_cupos_resumen_mensual returns a pd.DataFrame."""
        fake_result = pd.DataFrame({
            "sucursal": ["CASA CENTRAL"],
            "generico": ["CERVEZAS"],
            "cupo": [500.0],
        })
        loader = _make_loader_with_mock_engine(fake_result)
        result = loader.get_cupos_resumen_mensual("2026-04", ["CERVEZAS"])
        assert isinstance(result, pd.DataFrame)

    def test_calls_execute_query_once(self):
        """T-010: Method calls execute_query exactly once."""
        fake_result = pd.DataFrame(columns=["sucursal", "generico", "cupo"])
        loader = _make_loader_with_mock_engine(fake_result)
        loader.get_cupos_resumen_mensual("2026-04", ["CERVEZAS"])
        loader.execute_query.assert_called_once()

    def test_query_includes_periodo_param(self):
        """T-010: Query parameters must include 'periodo' bound to the given value."""
        fake_result = pd.DataFrame(columns=["sucursal", "generico", "cupo"])
        loader = _make_loader_with_mock_engine(fake_result)
        loader.get_cupos_resumen_mensual("2026-04", ["CERVEZAS"])

        call_args = loader.execute_query.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert "periodo" in params, f"Expected 'periodo' in params, got: {params}"
        assert params["periodo"] == "2026-04"

    def test_query_references_fact_cupos_table(self):
        """T-010: SQL query must reference gold.fact_cupos."""
        fake_result = pd.DataFrame(columns=["sucursal", "generico", "cupo"])
        loader = _make_loader_with_mock_engine(fake_result)
        loader.get_cupos_resumen_mensual("2026-04", ["CERVEZAS"])

        call_args = loader.execute_query.call_args
        sql = call_args[0][0] if call_args[0] else ""
        assert "fact_cupos" in sql.lower() or "fact_cupos" in str(sql), (
            f"Query should reference fact_cupos: {sql}"
        )

    def test_returns_correct_data_from_mock(self):
        """T-010: Result matches the mocked DB output."""
        fake_result = pd.DataFrame({
            "sucursal": ["CASA CENTRAL", "SUC CAFAYATE"],
            "generico": ["CERVEZAS", "CERVEZAS"],
            "cupo": [1000.0, 500.0],
        })
        loader = _make_loader_with_mock_engine(fake_result)
        result = loader.get_cupos_resumen_mensual("2026-04", ["CERVEZAS"])

        assert len(result) == 2
        assert result.iloc[0]["sucursal"] == "CASA CENTRAL"
        assert result.iloc[0]["cupo"] == 1000.0

    def test_query_groups_by_sucursal_not_descripcion(self):
        """T-010 (bug fix): Query must group by sucursal+id_ruta columns, NOT by descripcion.
        The fact_cupos table has descripcion=client names and sucursal='N - SUCURSAL NAME'.
        The join needs sucursal+id_ruta so zona virtual splitting works correctly.
        """
        fake_result = pd.DataFrame(columns=["sucursal", "generico", "cupo"])
        loader = _make_loader_with_mock_engine(fake_result)
        loader.get_cupos_resumen_mensual("2026-04", ["CERVEZAS"])

        call_args = loader.execute_query.call_args
        sql = call_args[0][0] if call_args[0] else ""
        # Must NOT group by descripcion (client names)
        assert "GROUP BY descripcion" not in sql, (
            "Query must NOT group by descripcion — that's client-level data, not sucursal-level"
        )
        # Must use the sucursal column (which has '1 - CASA CENTRAL' etc.)
        assert "sucursal" in sql.lower(), "Query must reference the sucursal column"
        # Must include id_ruta so zona virtual splitting works
        assert "id_ruta" in sql.lower(), "Query must include id_ruta for zona virtual splitting"

    def test_genericos_filter_passed_as_named_params(self):
        """T-010 (bug fix): Genericos must use named placeholders (:gen_0, :gen_1) not ANY(:genericos).
        The ANY(:genericos) pattern fails with psycopg2 when passed a tuple.
        Named placeholders (gen_0, gen_1, ...) work reliably across all psycopg2 versions.
        """
        fake_result = pd.DataFrame(columns=["sucursal", "generico", "cupo"])
        loader = _make_loader_with_mock_engine(fake_result)
        genericos = ["CERVEZAS", "AGUAS DANONE"]
        loader.get_cupos_resumen_mensual("2026-04", genericos)

        call_args = loader.execute_query.call_args
        sql = call_args[0][0] if call_args[0] else ""
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})

        # Must NOT use ANY() pattern (which fails with tuple params in psycopg2)
        assert "ANY(:genericos)" not in sql and "ANY(%(genericos)s)" not in sql, (
            "Query must NOT use ANY(:genericos) — it fails in psycopg2 with tuple params"
        )
        # Must use named placeholders consistent with the rest of DataLoader
        assert "gen_0" in params, f"Expected gen_0 in params, got: {params.keys()}"
        assert "gen_1" in params, f"Expected gen_1 in params, got: {params.keys()}"
        assert params["gen_0"] == "CERVEZAS"
        assert params["gen_1"] == "AGUAS DANONE"

    def test_genericos_single_item_uses_named_param(self):
        """T-010 (bug fix, triangulation): Single generico also uses named placeholder."""
        fake_result = pd.DataFrame(columns=["sucursal", "generico", "cupo"])
        loader = _make_loader_with_mock_engine(fake_result)
        loader.get_cupos_resumen_mensual("2026-04", ["CERVEZAS"])

        call_args = loader.execute_query.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert "gen_0" in params
        assert params["gen_0"] == "CERVEZAS"

    def test_empty_result_on_no_match(self):
        """T-010: Empty result returns empty DataFrame (no crash)."""
        fake_result = pd.DataFrame(columns=["sucursal", "generico", "cupo"])
        loader = _make_loader_with_mock_engine(fake_result)
        result = loader.get_cupos_resumen_mensual("2026-04", ["CERVEZAS"])
        assert len(result) == 0
        assert isinstance(result, pd.DataFrame)

    def test_cupo_column_is_numeric(self):
        """T-010: cupo column must be numeric (float or int), not string."""
        fake_result = pd.DataFrame({
            "sucursal": ["CASA CENTRAL"],
            "generico": ["CERVEZAS"],
            "cupo": [750.5],
        })
        loader = _make_loader_with_mock_engine(fake_result)
        result = loader.get_cupos_resumen_mensual("2026-04", ["CERVEZAS"])
        assert pd.api.types.is_numeric_dtype(result["cupo"]), (
            f"cupo column must be numeric, got dtype {result['cupo'].dtype}"
        )
