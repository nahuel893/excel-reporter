"""Tests for bd_agent/scripts/smoke_test.py — individual check functions.

TDD — RED phase: tests fail until smoke_test.py is implemented.

Each check function is tested in isolation with mocked dependencies.
The smoke script itself is tested for basic importability and __main__ mode.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: import module under test
# ---------------------------------------------------------------------------

def _import():
    # Ensure bd_agent package root is importable
    from bd_agent.scripts.smoke_test import (
        check_env_vars,
        check_db_ping,
        check_sqlglot_validator,
        check_whatsapp_status,
        run_all_checks,
    )
    return check_env_vars, check_db_ping, check_sqlglot_validator, check_whatsapp_status, run_all_checks


# ---------------------------------------------------------------------------
# check_env_vars
# ---------------------------------------------------------------------------

class TestCheckEnvVars:

    def test_pass_when_all_vars_set(self):
        check_env_vars, *_ = _import()
        env = {
            "AGENT_DB_URL": "postgresql+psycopg://agent_user:pwd@localhost/db",
            "GEMINI_API_KEY": "fake-key",
            "WHATSAPP_SERVICE_URL": "http://localhost:3000",
        }
        result = check_env_vars(env=env)
        assert result["ok"] is True

    def test_fail_when_agent_db_url_missing(self):
        check_env_vars, *_ = _import()
        env = {
            "GEMINI_API_KEY": "fake-key",
            "WHATSAPP_SERVICE_URL": "http://localhost:3000",
        }
        result = check_env_vars(env=env)
        assert result["ok"] is False
        assert "AGENT_DB_URL" in result["missing"]

    def test_fail_when_gemini_key_missing(self):
        check_env_vars, *_ = _import()
        env = {
            "AGENT_DB_URL": "postgresql+psycopg://agent_user:pwd@localhost/db",
            "WHATSAPP_SERVICE_URL": "http://localhost:3000",
        }
        result = check_env_vars(env=env)
        assert result["ok"] is False
        assert "GEMINI_API_KEY" in result["missing"]

    def test_fail_when_whatsapp_url_missing(self):
        check_env_vars, *_ = _import()
        env = {
            "AGENT_DB_URL": "postgresql+psycopg://agent_user:pwd@localhost/db",
            "GEMINI_API_KEY": "fake-key",
        }
        result = check_env_vars(env=env)
        assert result["ok"] is False
        assert "WHATSAPP_SERVICE_URL" in result["missing"]

    def test_reports_all_missing_vars(self):
        check_env_vars, *_ = _import()
        result = check_env_vars(env={})
        assert result["ok"] is False
        assert len(result["missing"]) == 3


# ---------------------------------------------------------------------------
# check_db_ping
# ---------------------------------------------------------------------------

class TestCheckDbPing:

    def test_pass_when_db_returns_one(self):
        _, check_db_ping, *_ = _import()
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.scalar.return_value = 1
        mock_engine.connect.return_value = mock_conn

        result = check_db_ping(engine=mock_engine)
        assert result["ok"] is True

    def test_fail_when_db_raises(self):
        _, check_db_ping, *_ = _import()
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("connection refused")

        result = check_db_ping(engine=mock_engine)
        assert result["ok"] is False
        assert "connection refused" in result["error"].lower()

    def test_fail_when_scalar_is_not_one(self):
        _, check_db_ping, *_ = _import()
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.scalar.return_value = 0
        mock_engine.connect.return_value = mock_conn

        result = check_db_ping(engine=mock_engine)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# check_sqlglot_validator
# ---------------------------------------------------------------------------

class TestCheckSqlglotValidator:

    def test_pass_when_select_accepted_and_drop_rejected(self):
        _, _, check_sqlglot_validator, *_ = _import()
        result = check_sqlglot_validator()
        assert result["ok"] is True
        assert result["select_accepted"] is True
        assert result["drop_rejected"] is True

    def test_validator_rejects_drop(self):
        """The validator must block DROP TABLE."""
        from bd_agent.safety.sqlglot_validator import validate, UnsafeQuery
        with pytest.raises(UnsafeQuery):
            validate("DROP TABLE gold.fact_ventas")

    def test_validator_accepts_select(self):
        """The validator must allow a plain SELECT."""
        from bd_agent.safety.sqlglot_validator import validate
        validate("SELECT 1")  # must not raise


# ---------------------------------------------------------------------------
# check_whatsapp_status
# ---------------------------------------------------------------------------

class TestCheckWhatsappStatus:

    def test_pass_when_status_connected(self):
        _, _, _, check_whatsapp_status, _ = _import()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "connected"}
        mock_client.get.return_value = mock_response

        result = check_whatsapp_status(http_client=mock_client, url="http://localhost:3000/status")
        assert result["ok"] is True

    def test_fail_when_status_not_connected(self):
        _, _, _, check_whatsapp_status, _ = _import()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "disconnected"}
        mock_client.get.return_value = mock_response

        result = check_whatsapp_status(http_client=mock_client, url="http://localhost:3000/status")
        assert result["ok"] is False

    def test_fail_when_http_error(self):
        _, _, _, check_whatsapp_status, _ = _import()
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("ECONNREFUSED")

        result = check_whatsapp_status(http_client=mock_client, url="http://localhost:3000/status")
        assert result["ok"] is False
        assert "ECONNREFUSED" in result["error"]

    def test_fail_when_non_200_status_code(self):
        _, _, _, check_whatsapp_status, _ = _import()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.json.return_value = {}
        mock_client.get.return_value = mock_response

        result = check_whatsapp_status(http_client=mock_client, url="http://localhost:3000/status")
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# run_all_checks
# ---------------------------------------------------------------------------

class TestRunAllChecks:

    def test_returns_list_of_check_results(self):
        *_, run_all_checks = _import()
        # Patch all dependency checks to avoid real network/DB calls
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.scalar.return_value = 1
        mock_engine.connect.return_value = mock_conn

        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "connected"}
        mock_http.get.return_value = mock_resp

        env = {
            "AGENT_DB_URL": "postgresql+psycopg://agent_user:pwd@localhost/db",
            "GEMINI_API_KEY": "fake-key",
            "WHATSAPP_SERVICE_URL": "http://localhost:3000",
        }

        results = run_all_checks(env=env, engine=mock_engine, http_client=mock_http)
        assert isinstance(results, list)
        assert len(results) >= 4  # env, db, sqlglot, whatsapp
        for r in results:
            assert "name" in r
            assert "ok" in r

    def test_no_src_imports(self):
        """bd_agent/scripts/smoke_test.py must have zero 'from src.' imports (RF-070)."""
        import ast
        import pathlib
        src = pathlib.Path(__file__).parent.parent.parent / "bd_agent" / "scripts" / "smoke_test.py"
        if not src.exists():
            pytest.skip("smoke_test.py not yet created")
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src."):
                    pytest.fail(f"Found forbidden import: from {node.module} in smoke_test.py")
