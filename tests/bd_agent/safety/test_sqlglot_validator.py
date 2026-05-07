"""T-020: Tests for bd_agent/safety/sqlglot_validator.py — SQL safety validator.

Tests are table-driven per design §8. All attack vectors MUST be rejected;
valid SELECT-only queries MUST be accepted.

TDD cycle: RED first (sqlglot_validator.py does not exist) → GREEN → REFACTOR.
"""
import pytest

# Skip entire module if sqlglot is not installed (SUGGESTION-1)
pytest.importorskip("sqlglot")


# ---------------------------------------------------------------------------
# Attack vectors — MUST be rejected
# ---------------------------------------------------------------------------

REJECTED_QUERIES = [
    # DDL
    ("DROP TABLE gold.ventas", "non_select_forbidden"),
    ("CREATE TABLE x AS SELECT * FROM gold.ventas", "non_select_forbidden"),
    ("ALTER TABLE gold.dim_articulo ADD COLUMN x INT", "non_select_forbidden"),
    ("TRUNCATE gold.ventas", "non_select_forbidden"),
    # DML
    ("DELETE FROM gold.dim_cliente", "non_select_forbidden"),
    ("INSERT INTO gold.fact_ventas VALUES (1, 2, 3)", "non_select_forbidden"),
    ("UPDATE gold.dim_articulo SET descripcion = 'x' WHERE id = 1", "non_select_forbidden"),
    # Multi-statement
    ("SELECT * FROM gold.ventas; DELETE FROM gold.fact_ventas", "multi_statement_forbidden"),
    ("SELECT 1; DELETE FROM gold.x", "multi_statement_forbidden"),
    # CTE with DML
    (
        "WITH t AS (DELETE FROM gold.x RETURNING *) SELECT * FROM t",
        "cte_dml_forbidden",
    ),
    (
        "WITH t AS (INSERT INTO gold.x VALUES (1)) SELECT * FROM t",
        "cte_dml_forbidden",
    ),
    # Transactional control
    ("BEGIN", "non_select_forbidden"),
    ("COMMIT", "non_select_forbidden"),
    ("ROLLBACK", "non_select_forbidden"),
    # System / privileged functions
    ("SELECT pg_read_file('/etc/passwd')", "system_function_forbidden"),
    ("SELECT pg_ls_dir('/tmp')", "system_function_forbidden"),
    # MERGE (DML)
    (
        "MERGE INTO gold.fact_ventas AS t USING gold.dim_cliente AS s ON t.id_cliente = s.id_cliente WHEN NOT MATCHED THEN INSERT VALUES (1)",
        "non_select_forbidden",
    ),
]

ACCEPTED_QUERIES = [
    "SELECT * FROM gold.ventas LIMIT 100",
    "SELECT a, b FROM gold.dim_cliente WHERE id = 1",
    "SELECT count(*) FROM gold.fact_ventas",
    "SELECT id, descripcion FROM gold.dim_articulo WHERE id_generico = 5",
    # Plain CTE (no DML)
    "WITH t AS (SELECT * FROM gold.ventas WHERE fecha >= '2026-01-01') SELECT * FROM t",
    # Subquery
    "SELECT * FROM (SELECT id FROM gold.dim_cliente) sub",
    # JOIN
    "SELECT v.*, a.descripcion FROM gold.fact_ventas v JOIN gold.dim_articulo a ON v.id_articulo = a.id_articulo LIMIT 50",
]


class TestSqlglotValidatorRejections:
    """All attack vectors must raise UnsafeQuery."""

    @pytest.mark.parametrize("sql,expected_reason", REJECTED_QUERIES)
    def test_reject_unsafe_query(self, sql: str, expected_reason: str):
        """validate() MUST raise UnsafeQuery for every attack vector."""
        from bd_agent.safety.sqlglot_validator import UnsafeQuery, validate

        with pytest.raises(UnsafeQuery) as exc_info:
            validate(sql)

        err = exc_info.value
        # Error must carry the expected reason code
        assert err.reason == expected_reason, (
            f"Expected reason {expected_reason!r} for SQL: {sql!r}\n"
            f"Got reason: {err.reason!r}"
        )

    def test_unsafequery_has_sql_attribute(self):
        """UnsafeQuery.sql exposes the offending SQL for logging."""
        from bd_agent.safety.sqlglot_validator import UnsafeQuery, validate

        bad_sql = "DROP TABLE gold.ventas"
        with pytest.raises(UnsafeQuery) as exc_info:
            validate(bad_sql)

        assert exc_info.value.sql == bad_sql

    def test_unsafequery_is_exception(self):
        """UnsafeQuery must be an Exception subclass."""
        from bd_agent.safety.sqlglot_validator import UnsafeQuery

        assert issubclass(UnsafeQuery, Exception)


class TestSqlglotValidatorAccepts:
    """All valid SELECT-only queries must pass through without raising."""

    @pytest.mark.parametrize("sql", ACCEPTED_QUERIES)
    def test_accept_valid_select(self, sql: str):
        """validate() MUST NOT raise for valid SELECT queries."""
        from bd_agent.safety.sqlglot_validator import validate

        # Should not raise any exception
        validate(sql)

    def test_validate_returns_none_on_success(self):
        """validate() returns None on success (not the query or AST)."""
        from bd_agent.safety.sqlglot_validator import validate

        result = validate("SELECT 1 FROM gold.fact_ventas")
        assert result is None


class TestSqlglotValidatorEdgeCases:
    """Boundary and injection-specific edge cases."""

    def test_empty_string_is_rejected(self):
        """Empty SQL must be rejected."""
        from bd_agent.safety.sqlglot_validator import UnsafeQuery, validate

        with pytest.raises(UnsafeQuery):
            validate("")

    def test_whitespace_only_is_rejected(self):
        """Whitespace-only input must be rejected."""
        from bd_agent.safety.sqlglot_validator import UnsafeQuery, validate

        with pytest.raises(UnsafeQuery):
            validate("   \n\t  ")

    def test_semicolon_followed_by_whitespace_is_ok(self):
        """SELECT ending with a trailing semicolon (no second statement) is accepted."""
        from bd_agent.safety.sqlglot_validator import validate

        # Trailing semicolon after a single SELECT is valid SQL
        validate("SELECT * FROM gold.ventas LIMIT 10;")

    def test_raw_semicolon_injection(self):
        """SELECT 1; DELETE — multi-statement injection is rejected."""
        from bd_agent.safety.sqlglot_validator import UnsafeQuery, validate

        with pytest.raises(UnsafeQuery) as exc_info:
            validate("SELECT 1; DELETE FROM gold.x")

        assert exc_info.value.reason == "multi_statement_forbidden"

    def test_case_insensitive_ddl_rejection(self):
        """DDL keywords are rejected regardless of case."""
        from bd_agent.safety.sqlglot_validator import UnsafeQuery, validate

        with pytest.raises(UnsafeQuery):
            validate("drop table gold.ventas")

    def test_pg_read_binary_file_rejected(self):
        """pg_read_binary_file function is rejected as system access."""
        from bd_agent.safety.sqlglot_validator import UnsafeQuery, validate

        with pytest.raises(UnsafeQuery) as exc_info:
            validate("SELECT pg_read_binary_file('/etc/passwd')")

        assert exc_info.value.reason == "system_function_forbidden"
