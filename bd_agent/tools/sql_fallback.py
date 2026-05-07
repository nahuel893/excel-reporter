"""bd_agent/tools/sql_fallback.py — run_sql_select fallback tool.

Implements RF-021: last-resort SQL SELECT tool with sqlglot validation.

The tool:
1. Validates the query with bd_agent.safety.sqlglot_validator (rejects any
   non-SELECT, multi-statement, CTE-DML, or system-function query).
2. Executes via DatabaseGateway.execute_select(query, params, max_rows=500).
3. Returns a ToolResult with JSON payload:
   {
     "rows": [...],
     "row_count": <int>,
     "truncated": <bool>   # True if row_count == 500
   }
4. Caps at 500 rows (RF-063).
5. On validator rejection or gateway exception, returns ToolResult(is_error=True)
   with a structured error payload (RF-022).

Zero imports from src.* (RF-070).
"""
from __future__ import annotations

import json
from typing import Any

from bd_agent.contracts import DatabaseGateway, ToolResult
from bd_agent.safety.sqlglot_validator import UnsafeQuery, validate

_MAX_ROWS = 500

_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "SELECT query to execute against gold.* schema. "
                "Must be a single SELECT statement — DDL, DML, and "
                "transactional control are forbidden."
            ),
        },
        "params": {
            "type": "object",
            "description": (
                "Optional parameter dict for parameterized queries "
                "(e.g. {\"id\": 99} for WHERE id = %(id)s)."
            ),
        },
    },
    "required": ["query"],
}


def run_sql_select(
    gateway: DatabaseGateway,
    query: str,
    params: dict[str, Any] | None = None,
) -> ToolResult:
    """Execute a validated SELECT query and return results as a ToolResult.

    Args:
        gateway: DatabaseGateway instance for DB access.
        query: Raw SQL string from the LLM tool call.
        params: Optional parameter dict for parameterized queries.

    Returns:
        ToolResult — is_error=False with rows on success, is_error=True with
        error payload on validation failure or gateway exception.
    """
    _params = params or {}

    # 1. Validate: reject non-SELECT, multi-statement, CTE-DML, etc.
    try:
        validate(query)
    except UnsafeQuery as exc:
        error_payload = json.dumps(
            {
                "error": exc.reason,
                "message": str(exc),
            }
        )
        return ToolResult(
            call_id="",
            name="run_sql_select",
            content=error_payload,
            is_error=True,
        )

    # 2. Execute via gateway
    try:
        rows = gateway.execute_select(query=query, params=_params, max_rows=_MAX_ROWS)
    except Exception as exc:  # noqa: BLE001
        error_payload = json.dumps(
            {
                "error": "tool_execution_error",
                "tool": "run_sql_select",
                "message": str(exc),
            }
        )
        return ToolResult(
            call_id="",
            name="run_sql_select",
            content=error_payload,
            is_error=True,
        )

    # 3. Build response
    row_count = len(rows)
    payload = json.dumps(
        {
            "rows": rows,
            "row_count": row_count,
            "truncated": row_count >= _MAX_ROWS,
        }
    )
    return ToolResult(
        call_id="",
        name="run_sql_select",
        content=payload,
        is_error=False,
    )


def _handler(gateway: DatabaseGateway, **kwargs: Any) -> dict[str, Any]:
    """Registry-compatible handler for run_sql_select.

    Unpacks kwargs and calls run_sql_select, then re-parses the ToolResult
    content so the registry can re-serialize it.
    """
    query = kwargs.get("query", "")
    params = kwargs.get("params")
    result = run_sql_select(gateway, query=query, params=params)
    if result.is_error:
        # Re-raise so registry wraps it in its own error envelope
        payload = json.loads(result.content)
        raise RuntimeError(payload.get("message", "sql validation or execution error"))
    return json.loads(result.content)


def register_into(registry) -> None:  # type: ignore[type-arg]
    """Register run_sql_select into a ToolRegistry.

    Args:
        registry: ToolRegistry instance.
    """
    registry.register(
        name="run_sql_select",
        description=(
            "Execute a raw SELECT query against the gold.* schema. "
            "Use only when no curated tool covers the question. "
            "The query MUST be a single SELECT — DDL, DML, and transactional "
            "control are forbidden. Returns at most 500 rows."
        ),
        params_schema=_PARAMS_SCHEMA,
        handler=_handler,
    )
