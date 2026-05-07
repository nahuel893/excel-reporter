"""bd_agent/safety/sqlglot_validator.py — SQL safety validator using sqlglot AST.

Enforces SELECT-only access (RF-021, RF-062):
- Rejects any non-SELECT root statement (DDL, DML, transactional control, CALL)
- Rejects multi-statement input (bare semicolon followed by non-whitespace)
- Rejects CTEs that contain DML statements in their body
- Rejects calls to pg_* system functions (pg_read_file, pg_ls_dir, etc.)

Zero imports from src.* (RF-070). Deps: stdlib + sqlglot.
"""
from __future__ import annotations

import sqlglot
import sqlglot.expressions as exp

# ---------------------------------------------------------------------------
# Reason codes (used in UnsafeQuery.reason)
# ---------------------------------------------------------------------------
REASON_NON_SELECT = "non_select_forbidden"
REASON_MULTI_STATEMENT = "multi_statement_forbidden"
REASON_CTE_DML = "cte_dml_forbidden"
REASON_SYSTEM_FUNCTION = "system_function_forbidden"

# Set of pg_* function name prefixes that indicate system/privilege access.
# We match on prefix so pg_read_file, pg_read_binary_file, pg_ls_dir, etc.
_PG_SYSTEM_PREFIXES = ("pg_read_file", "pg_read_binary_file", "pg_ls_dir")

# sqlglot expression types that represent DML (not SELECT)
_DML_TYPES = (exp.Insert, exp.Update, exp.Delete, exp.Merge)

# sqlglot expression types that represent DDL
_DDL_TYPES = (exp.Drop, exp.Create, exp.Alter, exp.Command, exp.TruncateTable)

# Transactional / procedural control statements
_TXN_TYPES = (exp.Transaction, exp.Commit, exp.Rollback, exp.Var)


class UnsafeQuery(Exception):
    """Raised when a SQL query fails the safety validator.

    Attributes:
        sql: the original query string.
        reason: a machine-readable reason code (one of the REASON_* constants).
    """

    def __init__(self, sql: str, reason: str, message: str = "") -> None:
        self.sql = sql
        self.reason = reason
        super().__init__(message or f"Unsafe SQL [{reason}]: {sql!r}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _contains_dml(node: exp.Expression) -> bool:
    """Return True if the expression tree contains any DML statement."""
    return bool(node.find(*_DML_TYPES))


def _validate_cte_bodies(stmt: exp.Expression, sql: str) -> None:
    """Walk all CTE definitions and reject any that contain DML."""
    with_clause = stmt.find(exp.With)
    if with_clause is None:
        return
    for cte in with_clause.find_all(exp.CTE):
        # The CTE body is the first child of the CTE expression
        cte_body = cte.this
        if cte_body is not None and _contains_dml(cte_body):
            raise UnsafeQuery(sql, REASON_CTE_DML)


def _validate_system_functions(stmt: exp.Expression, sql: str) -> None:
    """Reject calls to privileged pg_* system functions."""
    for func in stmt.find_all(exp.Anonymous):
        name = (func.name or "").lower()
        if any(name.startswith(prefix) for prefix in _PG_SYSTEM_PREFIXES):
            raise UnsafeQuery(sql, REASON_SYSTEM_FUNCTION)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate(sql: str) -> None:
    """Validate that *sql* is a safe, SELECT-only query.

    Raises UnsafeQuery with a reason code if the query is not safe.
    Returns None on success.

    Args:
        sql: raw SQL string from the LLM tool call.

    Raises:
        UnsafeQuery: if the query is rejected for any safety reason.
    """
    if not sql or not sql.strip():
        raise UnsafeQuery(sql, REASON_NON_SELECT, "Empty or whitespace-only SQL")

    # Parse (permissively — we validate semantics, not syntax purity)
    try:
        statements = sqlglot.parse(sql.strip(), read="postgres", error_level=sqlglot.ErrorLevel.WARN)
    except Exception as exc:
        raise UnsafeQuery(sql, REASON_NON_SELECT, f"SQL parse failed: {exc}") from exc

    # Filter out None entries that sqlglot may emit for empty statements
    statements = [s for s in statements if s is not None]

    if not statements:
        raise UnsafeQuery(sql, REASON_NON_SELECT, "No parseable statement found")

    # Multi-statement: more than one non-None statement
    if len(statements) > 1:
        raise UnsafeQuery(sql, REASON_MULTI_STATEMENT)

    stmt = statements[0]

    # Root statement must be SELECT
    if not isinstance(stmt, exp.Select):
        # Determine a more precise reason for common root types
        reason = REASON_NON_SELECT
        raise UnsafeQuery(sql, reason)

    # CTE bodies must not contain DML
    _validate_cte_bodies(stmt, sql)

    # System function access must be blocked
    _validate_system_functions(stmt, sql)
