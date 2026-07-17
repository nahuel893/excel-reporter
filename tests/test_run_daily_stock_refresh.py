"""
Tests for scripts/run_daily.py::_refresh_mv_stock_quiebre — T-1.3/T-1.7

NEW file — does NOT import from or modify the pre-existing (broken, out of
scope per RF-15) tests/test_run_daily.py.

Covers:
- _refresh_mv_stock_quiebre() issues REFRESH MATERIALIZED VIEW CONCURRENTLY
  gold.mv_stock_quiebre.
- Exceptions raised during refresh are caught/logged, never propagated
  (a stale MV must never crash the daily run).
- _refresh_mv_resumen_mensual() still works as before (no regression to the
  existing resumen-mensual refresh).
"""

from unittest.mock import MagicMock, patch

import pytest

import scripts.run_daily as run_daily


def _make_engine_mock():
    """Build a MagicMock standing in for a SQLAlchemy Engine + Connection."""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    engine = MagicMock()
    engine.connect.return_value = conn
    return engine, conn


def test_refresh_mv_stock_quiebre_issues_refresh_concurrently(monkeypatch):
    """_refresh_mv_stock_quiebre() must run REFRESH MATERIALIZED VIEW CONCURRENTLY
    gold.mv_stock_quiebre."""
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "testdb")
    monkeypatch.setenv("DB_USER", "testuser")
    monkeypatch.setenv("DB_PASSWORD", "testpass")

    engine, conn = _make_engine_mock()

    with patch("sqlalchemy.create_engine", return_value=engine) as mock_create_engine:
        run_daily._refresh_mv_stock_quiebre()

    mock_create_engine.assert_called_once()
    executed_sql = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any(
        "REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_stock_quiebre" in sql
        for sql in executed_sql
    ), f"Expected REFRESH CONCURRENTLY statement, got: {executed_sql}"
    conn.commit.assert_called_once()


def test_refresh_mv_stock_quiebre_is_non_fatal_on_error(monkeypatch, capsys):
    """A failure during refresh must be caught and logged, not raised."""
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "testdb")
    monkeypatch.setenv("DB_USER", "testuser")
    monkeypatch.setenv("DB_PASSWORD", "testpass")

    with patch("sqlalchemy.create_engine", side_effect=RuntimeError("connection refused")):
        # Must NOT raise.
        run_daily._refresh_mv_stock_quiebre()

    captured = capsys.readouterr()
    assert "mv_stock_quiebre" in captured.out
    assert "non-fatal" in captured.out.lower() or "failed" in captured.out.lower()


def test_refresh_mv_stock_quiebre_skips_when_credentials_missing(monkeypatch, capsys):
    """Missing DB credentials must not raise — refresh is skipped with a warning."""
    monkeypatch.delenv("DB_NAME", raising=False)
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)

    # Prevent the real worktree .env (which DOES have credentials) from being
    # re-loaded by the function's own load_dotenv(override=False) call — this
    # test wants to exercise the "credentials genuinely absent" branch.
    with patch("dotenv.load_dotenv"):
        run_daily._refresh_mv_stock_quiebre()

    captured = capsys.readouterr()
    assert "skipped" in captured.out.lower()


def test_refresh_mv_resumen_mensual_still_works(monkeypatch):
    """Regression guard: the existing resumen-mensual refresh must be unaffected."""
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "testdb")
    monkeypatch.setenv("DB_USER", "testuser")
    monkeypatch.setenv("DB_PASSWORD", "testpass")

    engine, conn = _make_engine_mock()

    with patch("sqlalchemy.create_engine", return_value=engine):
        run_daily._refresh_mv_resumen_mensual()

    executed_sql = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any(
        "REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_resumen_mensual" in sql
        for sql in executed_sql
    ), f"Expected REFRESH CONCURRENTLY statement for mv_resumen_mensual, got: {executed_sql}"
