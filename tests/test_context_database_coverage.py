"""
T-003 — Guard test: CONTEXT_DATABASE.md covers every gold.* table.

Unit variant: uses a hardcoded fixture of all known gold.* table names
(obtained via T-001 introspection). The check is case-insensitive substring
match, so the doc can reference tables in prose, SQL examples, or headers.

Integration variant (@pytest.mark.integration): queries information_schema
against the real Postgres DB to get the live table list, then performs the
same coverage check. Skipped in CI unless AGENT_TEST_DB_URL or DB_HOST env
var is set.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
CONTEXT_DB_PATH = REPO_ROOT / "CONTEXT_DATABASE.md"

# Complete list of gold.* tables as discovered in T-001 introspection
# (2026-05-07 snapshot). Update this list when new tables are added to gold.
KNOWN_GOLD_TABLES = [
    "cob_preventista_articulo",
    "cob_preventista_generico",
    "cob_preventista_marca",
    "cob_sucursal_aguas",
    "cob_sucursal_articulo",
    "cob_sucursal_generico",
    "cob_sucursal_lista_generico",
    "cob_sucursal_lista_marca",
    "cob_sucursal_marca",
    "dim_articulo",
    "dim_cliente",
    "dim_deposito",
    "dim_lista_precio",
    "dim_lista_sucursal",
    "dim_sucursal",
    "dim_tiempo",
    "dim_vendedor",
    "fact_comodatos",
    "fact_cupos",
    "fact_cupos_cobertura",
    "fact_precio_historico",
    "fact_precio_vigente",
    "fact_stock",
    "fact_ventas",
    "fact_ventas_contabilidad",
]


def _read_context_doc() -> str:
    """Read CONTEXT_DATABASE.md content (lowercased for case-insensitive check)."""
    assert CONTEXT_DB_PATH.exists(), (
        f"CONTEXT_DATABASE.md not found at {CONTEXT_DB_PATH}. "
        "Create or update it to document all gold.* tables."
    )
    return CONTEXT_DB_PATH.read_text(encoding="utf-8").lower()


# ---------------------------------------------------------------------------
# Unit tests (no DB required)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table_name", KNOWN_GOLD_TABLES)
def test_context_doc_mentions_each_gold_table(table_name: str) -> None:
    """Every table in KNOWN_GOLD_TABLES must appear at least once in CONTEXT_DATABASE.md.

    The check is case-insensitive. The table name may appear in headers, SQL
    blocks, prose, or table summaries — any mention counts.
    """
    doc = _read_context_doc()
    assert table_name.lower() in doc, (
        f"Table 'gold.{table_name}' is not mentioned in CONTEXT_DATABASE.md. "
        f"Add documentation for this table so the BD Agent's system prompt is accurate."
    )


def test_context_doc_is_non_empty() -> None:
    """CONTEXT_DATABASE.md must exist and contain meaningful content (>500 chars)."""
    doc = _read_context_doc()
    assert len(doc) > 500, (
        "CONTEXT_DATABASE.md appears nearly empty. "
        "It should contain full schema documentation."
    )


# ---------------------------------------------------------------------------
# Integration test (requires real Postgres connection)
# ---------------------------------------------------------------------------


def _has_db_access() -> bool:
    """Return True if DB credentials are available in the environment."""
    return bool(
        os.environ.get("AGENT_TEST_DB_URL")
        or os.environ.get("DB_HOST")
    )


@pytest.mark.integration
@pytest.mark.skipif(not _has_db_access(), reason="No DB credentials in environment")
def test_context_doc_covers_all_live_gold_tables() -> None:
    """Query information_schema for the real gold.* table list and assert
    that every table is mentioned in CONTEXT_DATABASE.md.

    Requires: AGENT_TEST_DB_URL or DB_HOST + DB_PORT + DB_NAME + DB_USER + DB_PASSWORD
    in the environment (via .env or explicit export).
    """
    try:
        import sqlalchemy as sa
        from config.settings import DB_CONFIG  # type: ignore[import]
    except ImportError as exc:
        pytest.skip(f"Cannot import sqlalchemy or config.settings: {exc}")

    agent_db_url = os.environ.get("AGENT_TEST_DB_URL")
    if agent_db_url:
        engine = sa.create_engine(agent_db_url)
    else:
        url = sa.engine.URL.create(
            drivername="postgresql+psycopg2",
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            database=DB_CONFIG["database"],
            username=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
        )
        engine = sa.create_engine(url)

    with engine.connect() as conn:
        result = conn.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'gold' ORDER BY table_name"
            )
        )
        live_tables = [row[0] for row in result.fetchall()]

    doc = _read_context_doc()
    missing: list[str] = [t for t in live_tables if t.lower() not in doc]

    assert not missing, (
        f"The following gold.* tables are missing from CONTEXT_DATABASE.md:\n"
        + "\n".join(f"  - {t}" for t in missing)
        + "\n\nAdd documentation for these tables."
    )
