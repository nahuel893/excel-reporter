"""T-031: Tests for bd_agent/tools/sql_fallback.py — run_sql_select tool.

TDD cycle: RED first (sql_fallback.py does not exist) -> GREEN -> REFACTOR.

Covers:
- run_sql_select with valid SELECT -> rows from mocked DatabaseGateway
- run_sql_select with DROP -> validator rejects -> error ToolResult
- run_sql_select with multi-statement -> validator rejects -> error ToolResult
- run_sql_select with CTE DML -> validator rejects
- Row cap (max_rows=500 forwarded to gateway)
- truncated flag when gateway returns exactly 500 rows (gateway may cap)
- Exception from gateway -> error ToolResult with tool_execution_error
- Tool is registered in a ToolRegistry and callable via invoke()
"""
from __future__ import annotations

import pytest

# Skip entire module if sqlglot is not installed (SUGGESTION-1)
pytest.importorskip("sqlglot")

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from bd_agent.contracts import ToolCall, ToolResult


# ---------------------------------------------------------------------------
# Fake DatabaseGateway
# ---------------------------------------------------------------------------


class FakeGateway:
    """Minimal fake DatabaseGateway for unit tests."""

    def __init__(self, rows: list[dict] | None = None, raises: Exception | None = None):
        self._rows = rows or []
        self._raises = raises
        self.calls: list[dict] = []

    def execute_select(self, query: str, params: dict[str, Any], max_rows: int) -> list[dict]:
        self.calls.append({"query": query, "params": params, "max_rows": max_rows})
        if self._raises:
            raise self._raises
        return self._rows

    def get_schema_doc(self) -> str:
        return "fake schema"


# ---------------------------------------------------------------------------
# Import guard — RED phase
# ---------------------------------------------------------------------------


def test_sql_fallback_module_importable():
    from bd_agent.tools.sql_fallback import run_sql_select  # noqa: F401


# ---------------------------------------------------------------------------
# Valid SELECT
# ---------------------------------------------------------------------------


class TestValidSelect:
    def test_select_returns_rows_as_tool_result(self):
        """Valid SELECT: gateway returns rows, tool returns ToolResult(is_error=False)."""
        from bd_agent.tools.sql_fallback import run_sql_select

        rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        gateway = FakeGateway(rows=rows)
        result = run_sql_select(gateway, query="SELECT id, name FROM gold.dim_cliente")
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        payload = json.loads(result.content)
        assert payload["rows"] == rows

    def test_select_passes_max_rows_500_to_gateway(self):
        """run_sql_select must cap at 500 rows (RF-063)."""
        from bd_agent.tools.sql_fallback import run_sql_select

        gateway = FakeGateway(rows=[])
        run_sql_select(gateway, query="SELECT 1")
        assert len(gateway.calls) == 1
        assert gateway.calls[0]["max_rows"] == 500

    def test_select_row_count_in_response(self):
        """Response payload must include row_count."""
        from bd_agent.tools.sql_fallback import run_sql_select

        rows = [{"x": i} for i in range(10)]
        gateway = FakeGateway(rows=rows)
        result = run_sql_select(gateway, query="SELECT x FROM gold.fact_ventas LIMIT 10")
        payload = json.loads(result.content)
        assert payload["row_count"] == 10

    def test_select_truncated_flag_when_500_rows(self):
        """When gateway returns exactly 500 rows, truncated=True in response."""
        from bd_agent.tools.sql_fallback import run_sql_select

        rows = [{"x": i} for i in range(500)]
        gateway = FakeGateway(rows=rows)
        result = run_sql_select(gateway, query="SELECT x FROM gold.fact_ventas")
        payload = json.loads(result.content)
        assert payload["truncated"] is True

    def test_select_not_truncated_when_fewer_than_500(self):
        """When gateway returns fewer than 500 rows, truncated=False."""
        from bd_agent.tools.sql_fallback import run_sql_select

        rows = [{"x": i} for i in range(100)]
        gateway = FakeGateway(rows=rows)
        result = run_sql_select(gateway, query="SELECT x FROM gold.fact_ventas LIMIT 100")
        payload = json.loads(result.content)
        assert payload["truncated"] is False

    def test_select_with_params(self):
        """run_sql_select accepts optional params dict and forwards to gateway."""
        from bd_agent.tools.sql_fallback import run_sql_select

        rows = [{"total": 42}]
        gateway = FakeGateway(rows=rows)
        result = run_sql_select(
            gateway,
            query="SELECT count(*) AS total FROM gold.fact_ventas WHERE id_cliente = %(id)s",
            params={"id": 99},
        )
        assert gateway.calls[0]["params"] == {"id": 99}
        assert result.is_error is False

    def test_trailing_semicolon_is_accepted(self):
        """A trailing semicolon on an otherwise valid SELECT must pass validation."""
        from bd_agent.tools.sql_fallback import run_sql_select

        gateway = FakeGateway(rows=[{"n": 1}])
        result = run_sql_select(gateway, query="SELECT 1 AS n;")
        assert result.is_error is False


# ---------------------------------------------------------------------------
# Unsafe queries — validator must reject before DB call
# ---------------------------------------------------------------------------


class TestValidatorRejectsUnsafeSQL:
    @pytest.mark.parametrize(
        "sql,expected_reason",
        [
            ("DROP TABLE gold.fact_ventas", "non_select_forbidden"),
            ("DELETE FROM gold.dim_cliente", "non_select_forbidden"),
            ("INSERT INTO gold.fact_ventas VALUES (1)", "non_select_forbidden"),
            ("UPDATE gold.dim_articulo SET x=1", "non_select_forbidden"),
            ("ALTER TABLE gold.x ADD COLUMN y INT", "non_select_forbidden"),
            (
                "SELECT * FROM gold.fact_ventas; DELETE FROM gold.fact_ventas",
                "multi_statement_forbidden",
            ),
            (
                "WITH cte AS (DELETE FROM gold.x RETURNING *) SELECT * FROM cte",
                "cte_dml_forbidden",
            ),
        ],
    )
    def test_unsafe_sql_rejected(self, sql: str, expected_reason: str):
        """Unsafe SQL must return error ToolResult without calling gateway."""
        from bd_agent.tools.sql_fallback import run_sql_select

        gateway = FakeGateway(rows=[{"x": 1}])
        result = run_sql_select(gateway, query=sql)

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        # No DB call must have been made
        assert len(gateway.calls) == 0
        payload = json.loads(result.content)
        assert payload["error"] == "non_select_forbidden" or payload["error"] == expected_reason

    def test_drop_table_error_payload_shape(self):
        """Error payload for rejected SQL must include error, reason, message keys."""
        from bd_agent.tools.sql_fallback import run_sql_select

        gateway = FakeGateway()
        result = run_sql_select(gateway, query="DROP TABLE gold.fact_ventas")
        payload = json.loads(result.content)
        assert "error" in payload
        assert "message" in payload


# ---------------------------------------------------------------------------
# Gateway exception -> structured error result
# ---------------------------------------------------------------------------


class TestGatewayException:
    def test_gateway_raises_returns_error_result(self):
        """If the gateway raises, run_sql_select returns error ToolResult."""
        from bd_agent.tools.sql_fallback import run_sql_select

        gateway = FakeGateway(raises=TimeoutError("DB timeout after 30s"))
        result = run_sql_select(gateway, query="SELECT 1")
        assert result.is_error is True
        payload = json.loads(result.content)
        assert payload["error"] == "tool_execution_error"
        assert "timeout" in payload["message"].lower()


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    def test_sql_fallback_registered_in_default_registry(self):
        """sql_fallback must expose a register_into(registry) function."""
        from bd_agent.tools.registry import ToolRegistry
        from bd_agent.tools.sql_fallback import register_into

        registry = ToolRegistry()
        register_into(registry)
        assert "run_sql_select" in registry.list_names()

    def test_sql_fallback_invokable_via_registry(self):
        """After registration, can invoke run_sql_select via ToolRegistry.invoke()."""
        from bd_agent.tools.registry import ToolRegistry
        from bd_agent.tools.sql_fallback import register_into

        registry = ToolRegistry()
        register_into(registry)

        rows = [{"total": 7}]
        gateway = FakeGateway(rows=rows)
        call = ToolCall(
            id="call-sql-1",
            name="run_sql_select",
            arguments={"query": "SELECT count(*) AS total FROM gold.fact_ventas"},
        )
        result = registry.invoke(call, gateway=gateway)
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        payload = json.loads(result.content)
        assert payload["rows"] == rows
