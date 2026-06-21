"""
Tests for scripts/sql/superset_user.sql — T-1.6

Static assertions that validate the SQL script without a live DB:
1. File exists and is non-empty
2. Idempotent DO $$ block checks pg_catalog.pg_roles
3. CREATE ROLE superset_user (not agent_user — detect copy-paste errors)
4. CHANGEME password placeholder present
5. REVOKE ALL ON SCHEMA gold FROM superset_user
6. GRANT USAGE ON SCHEMA gold TO superset_user
7. GRANT SELECT ON ALL TABLES IN SCHEMA gold TO superset_user
8. ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES
9. No 'superuser' keyword in role definition
10. sqlglot parses the plain SQL statements without error
"""

import re
from pathlib import Path

import pytest

# Skip entire module if sqlglot is not installed
sqlglot = pytest.importorskip("sqlglot")

SQL_FILE = Path(__file__).parent.parent / "scripts" / "sql" / "superset_user.sql"


@pytest.fixture(scope="module")
def sql_content() -> str:
    """Read the SQL file once per module."""
    assert SQL_FILE.exists(), f"SQL file not found: {SQL_FILE}"
    return SQL_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# File existence and non-empty
# ---------------------------------------------------------------------------

def test_sql_file_exists():
    assert SQL_FILE.exists(), f"Expected {SQL_FILE} to exist"


def test_sql_file_non_empty(sql_content):
    assert len(sql_content.strip()) > 0, "SQL file should not be empty"


# ---------------------------------------------------------------------------
# Idempotent DO $$ block
# ---------------------------------------------------------------------------

def test_contains_do_block(sql_content):
    assert "DO $$" in sql_content or "DO $" in sql_content, (
        "Expected a DO $$ block for idempotent role creation"
    )


def test_do_block_checks_pg_roles(sql_content):
    assert "pg_catalog.pg_roles" in sql_content or "pg_roles" in sql_content, (
        "DO block should check pg_catalog.pg_roles for IF NOT EXISTS logic"
    )


def test_do_block_creates_superset_user(sql_content):
    pattern = re.compile(
        r"CREATE\s+ROLE\s+superset_user\b",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected 'CREATE ROLE superset_user' inside the DO block"
    )


def test_role_name_is_superset_user_not_agent_user(sql_content):
    """Catch copy-paste error: role must be superset_user, not agent_user."""
    pattern_agent = re.compile(r"\bagent_user\b", re.IGNORECASE)
    assert not pattern_agent.search(sql_content), (
        "Found 'agent_user' in superset_user.sql — likely a copy-paste error. "
        "Role name must be 'superset_user'."
    )


def test_role_has_login(sql_content):
    pattern = re.compile(
        r"CREATE\s+ROLE\s+superset_user\s+WITH\s+LOGIN",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected 'CREATE ROLE superset_user WITH LOGIN'"
    )


def test_role_has_password_placeholder(sql_content):
    assert "CHANGEME" in sql_content, (
        "Expected 'CHANGEME' password placeholder so operators know to substitute it"
    )


# ---------------------------------------------------------------------------
# No superuser privilege
# ---------------------------------------------------------------------------

def test_no_superuser_in_create_role(sql_content):
    """The CREATE ROLE statement must not grant SUPERUSER."""
    # Allow the word 'superuser' only inside comments (lines starting with --)
    # We check that no non-comment line has 'SUPERUSER' adjacent to CREATE ROLE context.
    non_comment_lines = [
        line for line in sql_content.splitlines()
        if not line.strip().startswith("--")
    ]
    non_comment_text = "\n".join(non_comment_lines).upper()
    # Superuser is acceptable only in comments.  If it appears outside comments, fail.
    # We look for SUPERUSER as a keyword (not inside a string like 'NO SUPERUSER' comment refs)
    # Strategy: the DO block body is the danger zone; check the full non-comment text.
    assert "SUPERUSER" not in non_comment_text or "NO SUPERUSER" in non_comment_text, (
        "Found 'SUPERUSER' privilege in non-comment SQL — role must NOT be a superuser"
    )


# ---------------------------------------------------------------------------
# REVOKE statement
# ---------------------------------------------------------------------------

def test_contains_revoke_all_on_schema_gold(sql_content):
    pattern = re.compile(
        r"REVOKE\s+ALL\s+ON\s+SCHEMA\s+gold\s+FROM\s+superset_user",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected: REVOKE ALL ON SCHEMA gold FROM superset_user"
    )


# ---------------------------------------------------------------------------
# GRANT USAGE
# ---------------------------------------------------------------------------

def test_contains_grant_usage_on_schema_gold(sql_content):
    pattern = re.compile(
        r"GRANT\s+USAGE\s+ON\s+SCHEMA\s+gold\s+TO\s+superset_user",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected: GRANT USAGE ON SCHEMA gold TO superset_user"
    )


# ---------------------------------------------------------------------------
# GRANT SELECT ON ALL TABLES
# ---------------------------------------------------------------------------

def test_contains_grant_select_all_tables(sql_content):
    pattern = re.compile(
        r"GRANT\s+SELECT\s+ON\s+ALL\s+TABLES\s+IN\s+SCHEMA\s+gold\s+TO\s+superset_user",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected: GRANT SELECT ON ALL TABLES IN SCHEMA gold TO superset_user"
    )


# ---------------------------------------------------------------------------
# ALTER DEFAULT PRIVILEGES
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
        r"GRANT\s+SELECT\s+ON\s+TABLES\s+TO\s+superset_user",
        re.IGNORECASE | re.MULTILINE,
    )
    assert pattern.search(sql_content), (
        "Expected: GRANT SELECT ON TABLES TO superset_user (inside ALTER DEFAULT PRIVILEGES)"
    )


# ---------------------------------------------------------------------------
# sqlglot parses the plain (non-PL/pgSQL) statements
# ---------------------------------------------------------------------------

def _extract_plain_sql_statements(content: str) -> list[str]:
    """Return only plain SQL statements, stripping DO $$ ... $$ blocks."""
    cleaned = re.sub(
        r"DO\s+\$\$.*?\$\$\s*;",
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
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
    stmts = _extract_plain_sql_statements(sql_content)
    combined = "\n".join(stmts).upper()
    assert stmt_keyword.upper() in combined, (
        f"Expected statement containing '{stmt_keyword}' in plain SQL section"
    )


def test_plain_statements_parse_with_sqlglot(sql_content):
    """sqlglot parses REVOKE, GRANT, ALTER statements without raising exceptions."""
    stmts = _extract_plain_sql_statements(sql_content)
    errors = []
    for stmt in stmts:
        try:
            parsed = sqlglot.parse(stmt, dialect="postgres", error_level=sqlglot.ErrorLevel.WARN)
            if parsed and parsed[0] is None:
                errors.append(f"sqlglot returned None for: {stmt[:80]}")
        except Exception as exc:
            errors.append(f"sqlglot raised {type(exc).__name__} for: {stmt[:80]} — {exc}")
    assert not errors, "sqlglot parse errors:\n" + "\n".join(errors)
