"""
Tests for scripts/sql/agent_user.sql — T-100

Validates that the SQL script:
1. Parses cleanly (no syntax errors) via sqlglot
2. Contains the expected idempotent role-creation DO block
3. Contains REVOKE ALL ON SCHEMA gold
4. Contains GRANT USAGE ON SCHEMA gold
5. Contains GRANT SELECT ON ALL TABLES IN SCHEMA gold
6. Contains ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES
"""

import re
from pathlib import Path

import pytest
import sqlglot

# Path to the SQL script under test
SQL_FILE = Path(__file__).parent.parent / "scripts" / "sql" / "agent_user.sql"


@pytest.fixture(scope="module")
def sql_content() -> str:
    """Read the SQL file once per module."""
    assert SQL_FILE.exists(), f"SQL file not found: {SQL_FILE}"
    return SQL_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T-100-A: File exists and is non-empty
# ---------------------------------------------------------------------------

def test_sql_file_exists():
    assert SQL_FILE.exists(), f"Expected {SQL_FILE} to exist"


def test_sql_file_non_empty(sql_content):
    assert len(sql_content.strip()) > 0, "SQL file should not be empty"


# ---------------------------------------------------------------------------
# T-100-B: Idempotent role-creation block present
# The DO $$ block checks pg_catalog.pg_roles before creating the role.
# We validate the pattern via regex since DO blocks are PL/pgSQL, not pure SQL.
# ---------------------------------------------------------------------------

def test_contains_do_block(sql_content):
    assert "DO $$" in sql_content or "DO $" in sql_content, (
        "Expected a DO $$ block for idempotent role creation"
    )


def test_do_block_checks_pg_roles(sql_content):
    assert "pg_catalog.pg_roles" in sql_content or "pg_roles" in sql_content, (
        "DO block should check pg_catalog.pg_roles for IF NOT EXISTS logic"
    )


def test_do_block_creates_agent_user(sql_content):
    # Match: CREATE ROLE agent_user (with optional whitespace/newlines)
    pattern = re.compile(
        r"CREATE\s+ROLE\s+agent_user\b",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected 'CREATE ROLE agent_user' inside the DO block"
    )


def test_role_has_login(sql_content):
    # The CREATE ROLE line should include LOGIN
    pattern = re.compile(
        r"CREATE\s+ROLE\s+agent_user\s+WITH\s+LOGIN",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected 'CREATE ROLE agent_user WITH LOGIN'"
    )


def test_role_has_password_placeholder(sql_content):
    # Must contain a PASSWORD clause (any value is acceptable in the script;
    # we just verify the clause is present and uses the placeholder 'CHANGEME')
    assert "CHANGEME" in sql_content, (
        "Expected 'CHANGEME' password placeholder so operators know to substitute it"
    )


# ---------------------------------------------------------------------------
# T-100-C: REVOKE statement present
# ---------------------------------------------------------------------------

def test_contains_revoke_all_on_schema_gold(sql_content):
    pattern = re.compile(
        r"REVOKE\s+ALL\s+ON\s+SCHEMA\s+gold\s+FROM\s+agent_user",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected: REVOKE ALL ON SCHEMA gold FROM agent_user"
    )


# ---------------------------------------------------------------------------
# T-100-D: GRANT USAGE statement present
# ---------------------------------------------------------------------------

def test_contains_grant_usage_on_schema_gold(sql_content):
    pattern = re.compile(
        r"GRANT\s+USAGE\s+ON\s+SCHEMA\s+gold\s+TO\s+agent_user",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected: GRANT USAGE ON SCHEMA gold TO agent_user"
    )


# ---------------------------------------------------------------------------
# T-100-E: GRANT SELECT ON ALL TABLES statement present
# ---------------------------------------------------------------------------

def test_contains_grant_select_all_tables(sql_content):
    pattern = re.compile(
        r"GRANT\s+SELECT\s+ON\s+ALL\s+TABLES\s+IN\s+SCHEMA\s+gold\s+TO\s+agent_user",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected: GRANT SELECT ON ALL TABLES IN SCHEMA gold TO agent_user"
    )


# ---------------------------------------------------------------------------
# T-100-F: ALTER DEFAULT PRIVILEGES statement present
# ---------------------------------------------------------------------------

def test_contains_alter_default_privileges(sql_content):
    pattern = re.compile(
        r"ALTER\s+DEFAULT\s+PRIVILEGES\s+IN\s+SCHEMA\s+gold",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected: ALTER DEFAULT PRIVILEGES IN SCHEMA gold"
    )


def test_alter_default_privileges_grants_select(sql_content):
    pattern = re.compile(
        r"GRANT\s+SELECT\s+ON\s+TABLES\s+TO\s+agent_user",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected: GRANT SELECT ON TABLES TO agent_user (inside ALTER DEFAULT PRIVILEGES)"
    )


# ---------------------------------------------------------------------------
# T-100-G: sqlglot can parse the non-PL/pgSQL statements
# DO blocks are PL/pgSQL and cannot be parsed by sqlglot, so we extract
# only the bare SQL statements (REVOKE, GRANT, ALTER) and validate those.
# ---------------------------------------------------------------------------

def _extract_plain_sql_statements(content: str) -> list[str]:
    """Return only lines that look like plain SQL (not inside DO blocks)."""
    # Remove DO $$ ... $$ blocks (single or double dollar-quoted)
    cleaned = re.sub(
        r"DO\s+\$\$.*?\$\$\s*;",
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Split on semicolons and filter out comments / empty strings
    stmts = []
    for raw in cleaned.split(";"):
        stmt = "\n".join(
            line for line in raw.splitlines()
            if not line.strip().startswith("--") and line.strip()
        ).strip()
        if stmt:
            stmts.append(stmt + ";")
    return stmts


@pytest.mark.parametrize("stmt_keyword", [
    "REVOKE",
    "GRANT USAGE",
    "GRANT SELECT ON ALL TABLES",
    "ALTER DEFAULT PRIVILEGES",
])
def test_plain_statements_present(sql_content, stmt_keyword):
    """Each expected statement keyword appears in the non-DO portion of the script."""
    stmts = _extract_plain_sql_statements(sql_content)
    combined = "\n".join(stmts).upper()
    assert stmt_keyword.upper() in combined, (
        f"Expected statement containing '{stmt_keyword}' in plain SQL section"
    )


def test_plain_statements_parse_with_sqlglot(sql_content):
    """
    sqlglot can parse the REVOKE, GRANT, and ALTER statements without error.
    We use dialect='postgres' for best fidelity. Statements that sqlglot
    cannot handle (e.g. ALTER DEFAULT PRIVILEGES is Postgres-specific)
    are allowed to produce a warning but should not raise an exception.
    """
    stmts = _extract_plain_sql_statements(sql_content)
    errors = []
    for stmt in stmts:
        try:
            parsed = sqlglot.parse(stmt, dialect="postgres", error_level=sqlglot.ErrorLevel.WARN)
            # parse() returns a list; None entries indicate parse failures
            if parsed and parsed[0] is None:
                errors.append(f"sqlglot returned None for: {stmt[:80]}")
        except Exception as exc:
            errors.append(f"sqlglot raised {type(exc).__name__} for: {stmt[:80]} — {exc}")
    assert not errors, "sqlglot parse errors:\n" + "\n".join(errors)
