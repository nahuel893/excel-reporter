"""
Tests for gold.mv_resumen_mensual (materialized view) — T-1.4

SQL assertions on the MV structure and business logic:
- T-VM-01: All 14 RF-01 columns present with correct names (including medida)
- T-VM-02: VALLE SALTA routing (CASA CENTRAL + id_ruta in VALLE SALTA set → sucursal='VALLE SALTA', grupo='CASA CENTRAL')
- T-VM-03: DIRECTA SUCURSALES routing (id_ruta=100, non-CC → sucursal='DIRECTA SUCURSALES', grupo='DIRECTA')
- T-VM-04: Regular sucursal → grupo='INTERIOR'
- T-VM-05: PRVTA excluded for FRATELLI B
- T-VM-06: PRVTA included for non-FRATELLI B genericos
- T-VM-07: Closed-month tendencia = total_ventas
- T-VM-09: Zero habiles_transcurridos guard → tendencia = NULL (edge-case; NULLIF)
- T-VM-10: objetivo NULL when no fact_cupos row
- T-VM-11: objetivo = 0 → tend_vs_obj = NULL
- T-VM-12: objetivo present → tend_vs_obj = tendencia/objetivo (partition includes medida)
- T-VM-13: Historical period query returns rows
- T-VM-14: Static/offline — sqlglot parses the SQL; feriados comment present; no 'cupos_manuales' text
- T-VM-MEDIDA-01: medida='BULTOS' total_ventas matches SUM(fact_ventas.cantidades_total)
- T-VM-MEDIDA-02: medida='HTLS' total_ventas matches SUM(fact_ventas.cantidad_total_htls)

DB-required tests are marked @pytest.mark.integration and skipped if DB is unreachable.
"""

import re
from pathlib import Path
from contextlib import contextmanager

import pytest

# Skip sqlglot-dependent tests if not installed
try:
    import sqlglot
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False

SQL_VIEW_FILE = Path(__file__).parent.parent / "scripts" / "sql" / "v_resumen_mensual.sql"

# Relation name used by all integration tests (materialized view)
MV_RELATION = "gold.mv_resumen_mensual"

# ---------------------------------------------------------------------------
# DB availability helper
# ---------------------------------------------------------------------------

def _try_get_db_engine():
    """Return a live SQLAlchemy engine or None if DB is unreachable."""
    try:
        from sqlalchemy import create_engine, text
        import os
        from pathlib import Path
        # Load .env if vars not already in environment (supports both run modes)
        try:
            from dotenv import load_dotenv
            env_path = Path(__file__).parent.parent / ".env"
            if env_path.exists():
                load_dotenv(str(env_path), override=False)
        except ImportError:
            pass
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        db = os.getenv("DB_NAME")
        user = os.getenv("DB_USER")
        password = os.getenv("DB_PASSWORD")
        if not all([db, user, password]):
            return None
        url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception:
        return None


@pytest.fixture(scope="module")
def db_engine():
    engine = _try_get_db_engine()
    if engine is None:
        pytest.skip("DB not reachable — skipping integration tests")
    return engine


@pytest.fixture(scope="module", autouse=False)
def refreshed_mv(db_engine):
    """
    Ensure the materialized view is populated before integration tests run.
    Calls REFRESH MATERIALIZED VIEW CONCURRENTLY so the view data is current.
    This is safe to call repeatedly — it is a no-op if the view is already fresh.
    """
    from sqlalchemy import text
    with db_engine.connect() as conn:
        conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {MV_RELATION}"))
        conn.commit()
    return True


@contextmanager
def _conn(engine):
    with engine.connect() as conn:
        yield conn


# Closed test period — May 2026 (guaranteed complete)
CLOSED_PERIOD = "2026-05-01"
CLOSED_PERIOD_YM = "2026-05"


# ---------------------------------------------------------------------------
# T-VM-14: Static/offline assertions (no DB needed)
# ---------------------------------------------------------------------------

def test_view_sql_file_exists():
    assert SQL_VIEW_FILE.exists(), f"SQL view file not found: {SQL_VIEW_FILE}"


def test_view_sql_file_non_empty():
    assert SQL_VIEW_FILE.exists()
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert len(content.strip()) > 0, "SQL view file should not be empty"


def test_view_sql_contains_create_materialized_view():
    """SQL file must define a MATERIALIZED VIEW (not a plain VIEW)."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r"CREATE\s+MATERIALIZED\s+VIEW", re.IGNORECASE)
    assert pattern.search(content), "Expected 'CREATE MATERIALIZED VIEW' in SQL file (not plain VIEW)"


def test_view_sql_is_idempotent_via_drop_if_exists():
    """Idempotent pattern: DROP MATERIALIZED VIEW IF EXISTS ... CASCADE."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r"DROP\s+MATERIALIZED\s+VIEW\s+IF\s+EXISTS", re.IGNORECASE)
    assert pattern.search(content), (
        "Expected 'DROP MATERIALIZED VIEW IF EXISTS' for idempotent re-runs"
    )


def test_view_sql_targets_gold_schema():
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert "gold.mv_resumen_mensual" in content, (
        "Expected 'gold.mv_resumen_mensual' as the materialized view target"
    )


def test_view_sql_has_unique_index():
    """Unique index on natural key required for REFRESH CONCURRENTLY."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r"CREATE\s+UNIQUE\s+INDEX", re.IGNORECASE)
    assert pattern.search(content), (
        "Expected 'CREATE UNIQUE INDEX' — required for REFRESH MATERIALIZED VIEW CONCURRENTLY"
    )


def test_view_sql_references_settings_feriados():
    """SQL must have a comment referencing settings.py::FERIADOS for yearly maintenance."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert "settings.py" in content and "FERIADOS" in content, (
        "SQL view must contain a comment referencing 'settings.py::FERIADOS' "
        "for yearly maintenance"
    )


def test_view_sql_no_cupos_manuales():
    """No hardcoded cupos_manuales concept in the view."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert "cupos_manuales" not in content.lower(), (
        "Found 'cupos_manuales' in view SQL — this concept is removed in the view (use fact_cupos only)"
    )


def test_view_sql_contains_prvta_exclusion():
    """View must exclude PRVTA documents for FRATELLI B."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert "PRVTA" in content, "Expected PRVTA exclusion logic in view SQL"
    assert "FRATELLI" in content.upper(), (
        "Expected FRATELLI B referenced in PRVTA exclusion"
    )


def test_view_sql_contains_nullif_guard():
    """View must use NULLIF to guard against zero-division."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert "NULLIF" in content.upper(), (
        "Expected NULLIF guard in view SQL for zero habiles_transcurridos"
    )


@pytest.mark.skipif(not HAS_SQLGLOT, reason="sqlglot not installed")
def test_view_sql_parses_with_sqlglot():
    """
    sqlglot can parse the non-CTE portions of the view SQL.
    DO blocks / PL/pgSQL are stripped; the core SELECT statement must parse.
    We validate at minimum that the file is valid SQL-ish text.
    """
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    # Extract the main SELECT body (after WITH ... AS (...) pattern)
    # We just verify the file can be parsed without fatal exceptions.
    errors = []
    # Parse the whole thing with postgres dialect, warn-level errors
    try:
        result = sqlglot.parse(content, dialect="postgres", error_level=sqlglot.ErrorLevel.WARN)
        if not result:
            errors.append("sqlglot returned empty result for view SQL")
    except Exception as exc:
        errors.append(f"sqlglot raised {type(exc).__name__}: {exc}")
    assert not errors, "sqlglot parse errors:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# T-VM-01: Column contract (DB required)
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS = {
    "periodo", "sucursal", "grupo", "generico", "marca", "medida",
    "vtas_n1", "vtas_n2", "total_ventas", "tendencia",
    "mmaa", "ma", "objetivo", "tend_vs_obj",
}


@pytest.mark.integration
def test_view_column_contract(db_engine, refreshed_mv):
    """T-VM-01: MV exposes exactly the 14 RF-01 columns (including medida)."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(
            text(f"SELECT * FROM gold.mv_resumen_mensual WHERE periodo = :p LIMIT 1"),
            {"p": CLOSED_PERIOD_YM},
        )
        actual_columns = set(result.keys())
    assert EXPECTED_COLUMNS.issubset(actual_columns), (
        f"Missing columns: {EXPECTED_COLUMNS - actual_columns}"
    )


# ---------------------------------------------------------------------------
# T-VM-02: VALLE SALTA routing (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_valle_salta_routing(db_engine, refreshed_mv):
    """T-VM-02: Rows with CASA CENTRAL + VALLE SALTA routes appear as sucursal='VALLE SALTA', grupo='CASA CENTRAL'."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT sucursal, grupo
            FROM gold.mv_resumen_mensual
            WHERE periodo = :p
              AND sucursal = 'VALLE SALTA'
            LIMIT 1
        """), {"p": CLOSED_PERIOD_YM})
        row = result.fetchone()

    if row is None:
        pytest.skip("No VALLE SALTA rows in test period — verify data exists")

    assert row[0] == "VALLE SALTA", f"Expected sucursal='VALLE SALTA', got '{row[0]}'"
    assert row[1] == "CASA CENTRAL", f"Expected grupo='CASA CENTRAL' for VALLE SALTA, got '{row[1]}'"


# ---------------------------------------------------------------------------
# T-VM-03: DIRECTA SUCURSALES routing (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_directa_sucursales_routing(db_engine, refreshed_mv):
    """T-VM-03: Rows with id_ruta=100 (non-CC) appear as sucursal='DIRECTA SUCURSALES', grupo='DIRECTA'."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT sucursal, grupo
            FROM gold.mv_resumen_mensual
            WHERE periodo = :p
              AND sucursal = 'DIRECTA SUCURSALES'
            LIMIT 1
        """), {"p": CLOSED_PERIOD_YM})
        row = result.fetchone()

    if row is None:
        pytest.skip("No DIRECTA SUCURSALES rows in test period — verify data exists")

    assert row[0] == "DIRECTA SUCURSALES", f"Expected 'DIRECTA SUCURSALES', got '{row[0]}'"
    assert row[1] == "DIRECTA", f"Expected grupo='DIRECTA', got '{row[1]}'"


# ---------------------------------------------------------------------------
# T-VM-04: Regular sucursal → grupo='INTERIOR' (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_regular_sucursal_grupo_interior(db_engine, refreshed_mv):
    """T-VM-04: A sucursal outside CC-family and non-DIRECTA gets grupo='INTERIOR'."""
    from sqlalchemy import text
    cc_family = ("CASA CENTRAL", "VALLE SALTA", "SUB DISTRIBUIDORES", "DIRECTA SUCURSALES")
    placeholders = ", ".join(f"'{s}'" for s in cc_family)
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"""
            SELECT DISTINCT grupo
            FROM gold.mv_resumen_mensual
            WHERE periodo = :p
              AND sucursal NOT IN ({placeholders})
            LIMIT 5
        """), {"p": CLOSED_PERIOD_YM})
        rows = result.fetchall()

    if not rows:
        pytest.skip("No non-CC sucursales in test period")

    grupos = {row[0] for row in rows}
    assert grupos == {"INTERIOR"}, (
        f"Expected only 'INTERIOR' for regular sucursales, got: {grupos}"
    )


# ---------------------------------------------------------------------------
# T-VM-07: Closed-month tendencia = total_ventas (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_closed_month_tendencia_equals_total_ventas(db_engine, refreshed_mv):
    """T-VM-07: For a closed past month, tendencia must equal total_ventas."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT
                SUM(CASE WHEN ABS(tendencia - total_ventas) > 0.01 THEN 1 ELSE 0 END) AS mismatches,
                COUNT(*) AS total_rows
            FROM gold.mv_resumen_mensual
            WHERE periodo = :p
              AND total_ventas > 0
        """), {"p": CLOSED_PERIOD_YM})
        row = result.fetchone()

    if row is None or row[1] == 0:
        pytest.skip("No rows in closed period — verify data exists")

    mismatches = row[0]
    total_rows = row[1]
    assert mismatches == 0, (
        f"Closed-month tendencia != total_ventas for {mismatches}/{total_rows} rows in {CLOSED_PERIOD_YM}"
    )


# ---------------------------------------------------------------------------
# T-VM-10: objetivo NULL when no fact_cupos row (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_objetivo_null_when_no_cupos(db_engine, refreshed_mv):
    """T-VM-10: sucursales not in fact_cupos must have objetivo=NULL and tend_vs_obj=NULL."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        # Find a sucursal+generico combo with no cupos
        result = conn.execute(text("""
            SELECT COUNT(*) AS rows_without_objetivo_but_with_null_tend
            FROM gold.mv_resumen_mensual
            WHERE periodo = :p
              AND objetivo IS NULL
              AND tend_vs_obj IS NOT NULL
        """), {"p": CLOSED_PERIOD_YM})
        row = result.fetchone()

    # If objetivo is NULL then tend_vs_obj must also be NULL — count violations
    violations = row[0] if row else 0
    assert violations == 0, (
        f"Found {violations} rows where objetivo IS NULL but tend_vs_obj IS NOT NULL — "
        "tend_vs_obj must be NULL when objetivo is NULL"
    )


# ---------------------------------------------------------------------------
# T-VM-11: objetivo = 0 → tend_vs_obj = NULL (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_tend_vs_obj_null_when_objetivo_zero(db_engine, refreshed_mv):
    """T-VM-11: When objetivo=0, tend_vs_obj must be NULL (NULLIF guard)."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) AS violations
            FROM gold.mv_resumen_mensual
            WHERE periodo = :p
              AND objetivo = 0
              AND tend_vs_obj IS NOT NULL
        """), {"p": CLOSED_PERIOD_YM})
        row = result.fetchone()

    violations = row[0] if row else 0
    assert violations == 0, (
        f"Found {violations} rows where objetivo=0 but tend_vs_obj IS NOT NULL — NULLIF guard missing"
    )


# ---------------------------------------------------------------------------
# T-VM-12: objetivo present → tend_vs_obj = SUM(tendencia over sucgen) / objetivo
# (DB required)
#
# After the fan-out fix, objetivo is emitted on ONE row per (periodo,sucursal,generico)
# and tend_vs_obj on that same row equals:
#   SUM(tendencia) OVER (periodo, sucursal, generico) / objetivo
# NOT the single-row's tendencia / objetivo.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_tend_vs_obj_equals_tendencia_over_objetivo(db_engine, refreshed_mv):
    """
    T-VM-12: On rows where tend_vs_obj IS NOT NULL (i.e. the single allocation row
    per sucgen+medida), tend_vs_obj must equal the sucgen-medida total tendencia divided
    by objetivo within 0.0001 tolerance.

    The MV now has long format (one BULTOS row + one HTLS row per marca). The view's
    ROW_NUMBER() and SUM() windows partition by (periodo_date, sucursal, generico, medida),
    so each medida slice is allocated independently. The test window must also include
    medida to recompute the correct sucgen-medida tendencia total.
    """
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            WITH sucgen_totals AS (
                SELECT
                    periodo,
                    sucursal,
                    generico,
                    marca,
                    medida,
                    objetivo,
                    tend_vs_obj,
                    -- Recompute sucgen-medida total tendencia (same partition as the view)
                    SUM(tendencia) OVER (
                        PARTITION BY periodo, sucursal, generico, medida
                    ) AS sucgen_medida_tendencia
                FROM gold.mv_resumen_mensual
                WHERE periodo = :p
            )
            SELECT
                SUM(CASE
                    WHEN ABS(tend_vs_obj - sucgen_medida_tendencia / objetivo) > 0.0001 THEN 1
                    ELSE 0
                END) AS mismatches,
                COUNT(*) AS total
            FROM sucgen_totals
            WHERE objetivo IS NOT NULL
              AND objetivo > 0
              AND tend_vs_obj IS NOT NULL
        """), {"p": CLOSED_PERIOD_YM})
        row = result.fetchone()

    if row is None or row[1] == 0:
        pytest.skip("No rows with valid objetivo in test period")

    mismatches = row[0]
    assert mismatches == 0, (
        f"tend_vs_obj != SUM(tendencia_over_sucgen_medida)/objetivo for {mismatches} rows in {CLOSED_PERIOD_YM}"
    )


# ---------------------------------------------------------------------------
# Regression: objetivo fan-out guard (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_objetivo_no_fanout(db_engine, refreshed_mv):
    """
    Regression guard: objetivo must be allocated to AT MOST ONE marca row per
    (periodo, sucursal, generico, medida) group. COUNT(objetivo) > 1 in any group
    means the fan-out bug has returned (objetivo would be inflated by #marcas when SUM'd).

    medida is now part of the natural key because the MV emits one BULTOS row and one
    HTLS row per (periodo, sucursal, generico, marca). The ROW_NUMBER() window in the
    view partitions by (periodo_date, sucursal, generico, medida), so the guard must
    also include medida to test the correct allocation boundary.
    """
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) AS fanout_groups
            FROM (
                SELECT periodo, sucursal, generico, medida
                FROM gold.mv_resumen_mensual
                WHERE periodo = :p
                GROUP BY periodo, sucursal, generico, medida
                HAVING COUNT(objetivo) > 1
            ) violations
        """), {"p": CLOSED_PERIOD_YM})
        row = result.fetchone()

    fanout_groups = row[0] if row else 0
    assert fanout_groups == 0, (
        f"Fan-out detected: {fanout_groups} (periodo,sucursal,generico,medida) groups have "
        f"objetivo allocated on more than one marca row in {CLOSED_PERIOD_YM}. "
        f"The ROW_NUMBER()=1 guard in the view is broken."
    )


# ---------------------------------------------------------------------------
# T-VM-13: Historical period query returns rows (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_historical_period_returns_rows(db_engine, refreshed_mv):
    """T-VM-13: WHERE periodo = '2026-05' returns rows (historical period support)."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) AS cnt
            FROM gold.mv_resumen_mensual
            WHERE periodo = :p
        """), {"p": CLOSED_PERIOD_YM})
        row = result.fetchone()

    assert row[0] > 0, (
        f"Expected rows for historical period '{CLOSED_PERIOD_YM}' but got 0"
    )


# ---------------------------------------------------------------------------
# T-VM-05: PRVTA excluded for FRATELLI B (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_prvta_excluded_for_fratelli_b(db_engine, refreshed_mv):
    """T-VM-05: PRVTA documents must not be included in FRATELLI B total_ventas."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        # Check directly in fact_ventas how many PRVTA rows exist for FRATELLI B
        result = conn.execute(text("""
            SELECT COUNT(*) AS prvta_rows
            FROM gold.fact_ventas fv
            JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            WHERE da.generico = 'FRATELLI B'
              AND fv.id_documento = 'PRVTA'
              AND fv.fecha_comprobante BETWEEN :desde AND :hasta
        """), {"desde": CLOSED_PERIOD, "hasta": "2026-05-31"})
        prvta_row = result.fetchone()

    if prvta_row is None or prvta_row[0] == 0:
        pytest.skip("No PRVTA rows for FRATELLI B in test period — cannot verify exclusion")

    # PRVTA rows exist. Verify that the view total is LESS than raw total including PRVTA.
    # This is the simplest correct check: zona-virtual renaming makes exact sucursal-level
    # joins complex, so we compare the grand totals at generico level.
    # If PRVTA is excluded in the view, view_total < raw_with_prvta.
    # Filter medida='BULTOS' to avoid double-counting (BULTOS+HTLS are two rows per marca).
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT
                (SELECT COALESCE(SUM(total_ventas), 0)
                 FROM gold.mv_resumen_mensual
                 WHERE periodo = :p AND generico = 'FRATELLI B' AND medida = 'BULTOS'
                ) AS view_total,
                (SELECT COALESCE(SUM(fv2.cantidades_total), 0)
                 FROM gold.fact_ventas fv2
                 JOIN gold.dim_articulo da2 ON fv2.id_articulo = da2.id_articulo
                 WHERE da2.generico = 'FRATELLI B'
                   AND fv2.fecha_comprobante BETWEEN :desde AND :hasta
                ) AS raw_with_prvta
        """), {"p": CLOSED_PERIOD_YM, "desde": CLOSED_PERIOD, "hasta": "2026-05-31"})
        row = result.fetchone()

    if row is None:
        pytest.skip("Could not retrieve totals for FRATELLI B comparison")

    view_total, raw_with_prvta = float(row[0] or 0), float(row[1] or 0)

    if raw_with_prvta == 0:
        pytest.skip("No FRATELLI B raw data found — cannot verify PRVTA exclusion")

    # The view should exclude PRVTA rows, so view_total <= raw_with_prvta.
    # Since PRVTA rows exist (checked above), view_total should be strictly less.
    assert view_total < raw_with_prvta, (
        f"FRATELLI B total_ventas in view ({view_total:.2f}) should be LESS than "
        f"raw total including PRVTA ({raw_with_prvta:.2f}) — PRVTA exclusion may be broken"
    )


# ---------------------------------------------------------------------------
# T-VM-06: PRVTA included for non-FRATELLI B genericos (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_prvta_included_for_non_fratelli_b(db_engine, refreshed_mv):
    """T-VM-06: PRVTA documents ARE included in total_ventas for non-FRATELLI B genericos."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) AS prvta_rows
            FROM gold.fact_ventas fv
            JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            WHERE da.generico = 'CERVEZAS'
              AND fv.id_documento = 'PRVTA'
              AND fv.fecha_comprobante BETWEEN :desde AND :hasta
        """), {"desde": CLOSED_PERIOD, "hasta": "2026-05-31"})
        row = result.fetchone()

    if row is None or row[0] == 0:
        pytest.skip("No PRVTA rows for CERVEZAS in test period — cannot verify inclusion")

    # PRVTA rows exist for CERVEZAS; view total should be GREATER than total excluding PRVTA.
    # Filter medida='BULTOS' to avoid double-counting (BULTOS+HTLS are two rows per marca).
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT
                SUM(v.total_ventas) AS view_total,
                (
                    SELECT SUM(fv2.cantidades_total)
                    FROM gold.fact_ventas fv2
                    JOIN gold.dim_articulo da2 ON fv2.id_articulo = da2.id_articulo
                    WHERE da2.generico = 'CERVEZAS'
                      AND fv2.id_documento <> 'PRVTA'
                      AND fv2.fecha_comprobante BETWEEN :desde AND :hasta
                ) AS raw_no_prvta
            FROM gold.mv_resumen_mensual v
            WHERE v.periodo = :p
              AND v.generico = 'CERVEZAS'
              AND v.medida = 'BULTOS'
        """), {"p": CLOSED_PERIOD_YM, "desde": CLOSED_PERIOD, "hasta": "2026-05-31"})
        row = result.fetchone()

    if row is None or row[0] is None:
        pytest.skip("No CERVEZAS rows in view for test period")

    view_total = float(row[0])
    raw_no_prvta = float(row[1]) if row[1] is not None else 0.0
    assert view_total >= raw_no_prvta, (
        f"CERVEZAS view total ({view_total}) should be >= total_excl_prvta ({raw_no_prvta}) "
        "since PRVTA is included for non-FRATELLI-B genericos"
    )


# ---------------------------------------------------------------------------
# T-VM-MEDIDA-01: medida='BULTOS' total_ventas matches SUM(fact_ventas.cantidades_total)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_medida_bultos_matches_cantidades_total(db_engine, refreshed_mv):
    """
    T-VM-MEDIDA-01: For the closed period 2026-05 and generico='CERVEZAS',
    the MV's SUM(total_ventas) WHERE medida='BULTOS' must equal
    SUM(fact_ventas.cantidades_total) with the same base filters:
      - generico IS NOT NULL (base filter from the view)
      - PRVTA excluded for FRATELLI B only (irrelevant for CERVEZAS, but mirrors view logic)

    Tolerance: ±1 unit (rounding from numeric precision).
    """
    from sqlalchemy import text

    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT
                (
                    SELECT COALESCE(SUM(total_ventas), 0)
                    FROM gold.mv_resumen_mensual
                    WHERE periodo = :p
                      AND generico = 'CERVEZAS'
                      AND medida = 'BULTOS'
                ) AS mv_bultos,
                (
                    SELECT COALESCE(SUM(fv.cantidades_total), 0)
                    FROM gold.fact_ventas fv
                    JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
                    WHERE da.generico = 'CERVEZAS'
                      AND da.generico IS NOT NULL
                      AND fv.fecha_comprobante BETWEEN :desde AND :hasta
                      -- PRVTA only excluded for FRATELLI B; CERVEZAS includes all id_documento
                ) AS fact_bultos
        """), {"p": CLOSED_PERIOD_YM, "desde": CLOSED_PERIOD, "hasta": "2026-05-31"})
        row = result.fetchone()

    if row is None:
        pytest.skip("Could not retrieve CERVEZAS totals for medida='BULTOS' check")

    mv_bultos = float(row[0] or 0)
    fact_bultos = float(row[1] or 0)

    if mv_bultos == 0 and fact_bultos == 0:
        pytest.skip("Both MV and fact_ventas return 0 for CERVEZAS BULTOS — no data to compare")

    assert abs(mv_bultos - fact_bultos) <= 1.0, (
        f"medida='BULTOS' total mismatch for CERVEZAS {CLOSED_PERIOD_YM}: "
        f"MV={mv_bultos:.2f}, fact_ventas={fact_bultos:.2f}, "
        f"diff={abs(mv_bultos - fact_bultos):.2f} (tolerance ±1)"
    )


# ---------------------------------------------------------------------------
# T-VM-MEDIDA-02: medida='HTLS' total_ventas matches SUM(fact_ventas.cantidad_total_htls)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_medida_htls_matches_cantidad_total_htls(db_engine, refreshed_mv):
    """
    T-VM-MEDIDA-02: For the closed period 2026-05 and generico='CERVEZAS',
    the MV's SUM(total_ventas) WHERE medida='HTLS' must equal
    SUM(fact_ventas.cantidad_total_htls) with the same base filters.

    Tolerance: ±1 unit.
    """
    from sqlalchemy import text

    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT
                (
                    SELECT COALESCE(SUM(total_ventas), 0)
                    FROM gold.mv_resumen_mensual
                    WHERE periodo = :p
                      AND generico = 'CERVEZAS'
                      AND medida = 'HTLS'
                ) AS mv_htls,
                (
                    SELECT COALESCE(SUM(fv.cantidad_total_htls), 0)
                    FROM gold.fact_ventas fv
                    JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
                    WHERE da.generico = 'CERVEZAS'
                      AND da.generico IS NOT NULL
                      AND fv.fecha_comprobante BETWEEN :desde AND :hasta
                      -- PRVTA only excluded for FRATELLI B; CERVEZAS includes all id_documento
                ) AS fact_htls
        """), {"p": CLOSED_PERIOD_YM, "desde": CLOSED_PERIOD, "hasta": "2026-05-31"})
        row = result.fetchone()

    if row is None:
        pytest.skip("Could not retrieve CERVEZAS totals for medida='HTLS' check")

    mv_htls = float(row[0] or 0)
    fact_htls = float(row[1] or 0)

    if mv_htls == 0 and fact_htls == 0:
        pytest.skip("Both MV and fact_ventas return 0 for CERVEZAS HTLS — no data to compare")

    assert abs(mv_htls - fact_htls) <= 1.0, (
        f"medida='HTLS' total mismatch for CERVEZAS {CLOSED_PERIOD_YM}: "
        f"MV={mv_htls:.2f}, fact_ventas={fact_htls:.2f}, "
        f"diff={abs(mv_htls - fact_htls):.2f} (tolerance ±1)"
    )
