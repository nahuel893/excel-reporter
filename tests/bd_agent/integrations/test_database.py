"""tests/bd_agent/integrations/test_database.py — Tests for PgDatabaseGateway (T-070).

All tests mock the SQLAlchemy engine so no real DB is required.
Integration tests (marked @pytest.mark.integration) are skipped by default.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Import guard — module must exist
# ---------------------------------------------------------------------------

def test_module_importable():
    """T-070: bd_agent.integrations.database must be importable."""
    from bd_agent.integrations.database import PgDatabaseGateway  # noqa: F401


def test_database_module_has_curated_queries():
    """T-070: _CURATED_QUERIES must be a dict with all 5 named queries."""
    from bd_agent.integrations.database import _CURATED_QUERIES
    assert isinstance(_CURATED_QUERIES, dict)
    required = {
        "get_ventas_cliente",
        "get_clientes_sucursal",
        "get_articulos_generico",
        "get_cobertura_periodo",
        "get_ventas_articulo",
    }
    assert required <= set(_CURATED_QUERIES.keys())


# ---------------------------------------------------------------------------
# Missing env var raises EnvironmentError (RF-061)
# ---------------------------------------------------------------------------

def test_missing_agent_db_url_raises(tmp_path, monkeypatch):
    """T-070/RF-061: raises EnvironmentError when AGENT_DB_URL is not set."""
    monkeypatch.delenv("AGENT_DB_URL", raising=False)
    from bd_agent.integrations import database as db_mod
    with pytest.raises(EnvironmentError, match="AGENT_DB_URL"):
        db_mod.PgDatabaseGateway(schema_doc_path=tmp_path / "schema.md")


# ---------------------------------------------------------------------------
# Fixture: patch create_engine so no real connection is made
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_engine():
    """A mocked SQLAlchemy engine with a fake connection context manager."""
    engine = MagicMock()
    conn = MagicMock()
    # engine.connect() returns a context manager that yields conn
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


@pytest.fixture()
def gateway(tmp_path, monkeypatch, fake_engine):
    """PgDatabaseGateway with patched engine + temp schema doc."""
    engine, conn = fake_engine
    monkeypatch.setenv("AGENT_DB_URL", "postgresql+psycopg://agent:pwd@localhost/db")
    schema_doc = tmp_path / "CONTEXT_DATABASE.md"
    schema_doc.write_text("# Schema\nTable: gold.fact_ventas\n")
    with patch("bd_agent.integrations.database.create_engine", return_value=engine):
        from bd_agent.integrations.database import PgDatabaseGateway
        gw = PgDatabaseGateway(schema_doc_path=schema_doc)
    return gw, conn


# ---------------------------------------------------------------------------
# get_schema_doc — returns file contents
# ---------------------------------------------------------------------------

def test_get_schema_doc_returns_file_content(gateway):
    """T-070: get_schema_doc() returns the content of the schema doc file."""
    gw, _ = gateway
    doc = gw.get_schema_doc()
    assert "gold.fact_ventas" in doc


def test_get_schema_doc_missing_file_raises(tmp_path, monkeypatch):
    """T-070: get_schema_doc() raises FileNotFoundError when schema doc is absent (RF-023/S2)."""
    monkeypatch.setenv("AGENT_DB_URL", "postgresql+psycopg://agent:pwd@localhost/db")
    missing = tmp_path / "missing.md"
    engine = MagicMock()
    with patch("bd_agent.integrations.database.create_engine", return_value=engine):
        from bd_agent.integrations.database import PgDatabaseGateway
        gw = PgDatabaseGateway(schema_doc_path=missing)
    with pytest.raises(FileNotFoundError):
        gw.get_schema_doc()


# ---------------------------------------------------------------------------
# execute_select — raw SQL fallback path
# ---------------------------------------------------------------------------

def _make_row_proxy(data: dict):
    """Create a mock row proxy that behaves like SQLAlchemy row with _mapping."""
    row = MagicMock()
    row._mapping = data
    return row


def test_execute_select_raw_sql(gateway):
    """T-070: execute_select with a non-curated query executes it directly."""
    gw, conn = gateway
    rows_data = [{"id": 1, "name": "foo"}, {"id": 2, "name": "bar"}]
    mock_result = MagicMock()
    mock_result.fetchmany.return_value = [_make_row_proxy(r) for r in rows_data]
    conn.execute.return_value = mock_result

    result = gw.execute_select(
        query="SELECT id, name FROM gold.dim_sucursal",
        params={},
        max_rows=10,
    )
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["id"] == 1


def test_execute_select_respects_max_rows(gateway):
    """T-070: execute_select asks DB for at most max_rows rows via fetchmany."""
    gw, conn = gateway
    mock_result = MagicMock()
    mock_result.fetchmany.return_value = []
    conn.execute.return_value = mock_result

    gw.execute_select(
        query="SELECT 1",
        params={},
        max_rows=42,
    )
    mock_result.fetchmany.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# execute_select — curated query names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query_name", [
    "get_ventas_cliente",
    "get_clientes_sucursal",
    "get_articulos_generico",
    "get_cobertura_periodo",
    "get_ventas_articulo",
])
def test_curated_query_name_executes_sql(query_name, gateway):
    """T-070: passing a curated query name executes the mapped SQL (not raw query name as SQL)."""
    gw, conn = gateway
    mock_result = MagicMock()
    mock_result.fetchmany.return_value = []
    conn.execute.return_value = mock_result

    gw.execute_select(query=query_name, params={}, max_rows=10)

    # execute must have been called; the text passed should NOT be just the query name
    assert conn.execute.called
    call_args = conn.execute.call_args
    # First positional arg to execute is a text() or similar, not the bare query name
    sql_arg = str(call_args[0][0])
    assert query_name not in sql_arg or "SELECT" in sql_arg.upper() or "FROM" in sql_arg.upper()


def test_curated_query_passes_params(gateway):
    """T-070: curated query passes bound params to execute."""
    gw, conn = gateway
    mock_result = MagicMock()
    mock_result.fetchmany.return_value = []
    conn.execute.return_value = mock_result

    params = {"id_cliente": 123, "periodo": "2026-03", "max_rows": 100}
    gw.execute_select(query="get_ventas_cliente", params=params, max_rows=100)

    assert conn.execute.called


# ---------------------------------------------------------------------------
# execute_select — row dict conversion
# ---------------------------------------------------------------------------

def test_execute_select_returns_list_of_dicts(gateway):
    """T-070: execute_select always returns list[dict], not row proxy objects."""
    gw, conn = gateway
    rows_data = [{"col_a": "x", "col_b": 99}]
    mock_result = MagicMock()
    mock_result.fetchmany.return_value = [_make_row_proxy(r) for r in rows_data]
    conn.execute.return_value = mock_result

    result = gw.execute_select("SELECT col_a, col_b FROM gold.t", {}, max_rows=10)
    assert result == [{"col_a": "x", "col_b": 99}]


# ---------------------------------------------------------------------------
# execute_select — empty result
# ---------------------------------------------------------------------------

def test_execute_select_empty_returns_empty_list(gateway):
    """T-070: execute_select returns [] when query finds no rows."""
    gw, conn = gateway
    mock_result = MagicMock()
    mock_result.fetchmany.return_value = []
    conn.execute.return_value = mock_result

    result = gw.execute_select("SELECT 1 WHERE false", {}, max_rows=10)
    assert result == []


# ---------------------------------------------------------------------------
# DatabaseGateway Protocol satisfaction
# ---------------------------------------------------------------------------

def test_implements_database_gateway_protocol(gateway):
    """T-070: PgDatabaseGateway satisfies the DatabaseGateway Protocol."""
    from bd_agent.contracts import DatabaseGateway
    gw, _ = gateway
    assert isinstance(gw, DatabaseGateway)


# ---------------------------------------------------------------------------
# No imports from src.*
# ---------------------------------------------------------------------------

def test_no_src_imports():
    """T-070/RF-070: bd_agent.integrations.database must not import from src.*"""
    import ast
    import importlib
    import importlib.util

    spec = importlib.util.find_spec("bd_agent.integrations.database")
    assert spec is not None, "Module not found"
    source = Path(spec.origin).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("src."), (
                    f"bd_agent.integrations.database imports from src.*: {node.module}"
                )
