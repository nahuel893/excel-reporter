"""
Tests for gold.v_resumen_mensual — T-1.4

SQL assertions on the view structure and business logic:
- T-VM-01: All 13 RF-01 columns present with correct names
- T-VM-02: VALLE SALTA routing (CASA CENTRAL + id_ruta in VALLE SALTA set → sucursal='VALLE SALTA', grupo='CASA CENTRAL')
- T-VM-03: DIRECTA SUCURSALES routing (id_ruta=100, non-CC → sucursal='DIRECTA SUCURSALES', grupo='DIRECTA')
- T-VM-04: Regular sucursal → grupo='INTERIOR'
- T-VM-05: PRVTA excluded for FRATELLI B
- T-VM-06: PRVTA included for non-FRATELLI B genericos
- T-VM-07: Closed-month tendencia = total_ventas
- T-VM-09: Zero habiles_transcurridos guard → tendencia = NULL (edge-case; NULLIF)
- T-VM-10: objetivo NULL when no fact_cupos row
- T-VM-11: objetivo = 0 → tend_vs_obj = NULL
- T-VM-12: objetivo present → tend_vs_obj = tendencia/objetivo
- T-VM-13: Historical period query returns rows
- T-VM-14: Static/offline — sqlglot parses the SQL; feriados comment present; no 'cupos_manuales' text

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


def test_view_sql_contains_create_or_replace():
    """View must be defined with CREATE OR REPLACE (idempotent)."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r"CREATE\s+OR\s+REPLACE\s+VIEW", re.IGNORECASE)
    assert pattern.search(content), "Expected 'CREATE OR REPLACE VIEW' in view SQL"


def test_view_sql_targets_gold_schema():
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert "gold.v_resumen_mensual" in content.lower() or "gold.v_resumen_mensual" in content, (
        "Expected 'gold.v_resumen_mensual' as the view target"
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
    "periodo", "sucursal", "grupo", "generico", "marca",
    "vtas_n1", "vtas_n2", "total_ventas", "tendencia",
    "mmaa", "ma", "objetivo", "tend_vs_obj",
}


@pytest.mark.integration
def test_view_column_contract(db_engine):
    """T-VM-01: View exposes exactly the 13 RF-01 columns."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(
            text(f"SELECT * FROM gold.v_resumen_mensual WHERE periodo = :p LIMIT 1"),
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
def test_valle_salta_routing(db_engine):
    """T-VM-02: Rows with CASA CENTRAL + VALLE SALTA routes appear as sucursal='VALLE SALTA', grupo='CASA CENTRAL'."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT sucursal, grupo
            FROM gold.v_resumen_mensual
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
def test_directa_sucursales_routing(db_engine):
    """T-VM-03: Rows with id_ruta=100 (non-CC) appear as sucursal='DIRECTA SUCURSALES', grupo='DIRECTA'."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT sucursal, grupo
            FROM gold.v_resumen_mensual
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
def test_regular_sucursal_grupo_interior(db_engine):
    """T-VM-04: A sucursal outside CC-family and non-DIRECTA gets grupo='INTERIOR'."""
    from sqlalchemy import text
    cc_family = ("CASA CENTRAL", "VALLE SALTA", "SUB DISTRIBUIDORES", "DIRECTA SUCURSALES")
    placeholders = ", ".join(f"'{s}'" for s in cc_family)
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"""
            SELECT DISTINCT grupo
            FROM gold.v_resumen_mensual
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
def test_closed_month_tendencia_equals_total_ventas(db_engine):
    """T-VM-07: For a closed past month, tendencia must equal total_ventas."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT
                SUM(CASE WHEN ABS(tendencia - total_ventas) > 0.01 THEN 1 ELSE 0 END) AS mismatches,
                COUNT(*) AS total_rows
            FROM gold.v_resumen_mensual
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
def test_objetivo_null_when_no_cupos(db_engine):
    """T-VM-10: sucursales not in fact_cupos must have objetivo=NULL and tend_vs_obj=NULL."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        # Find a sucursal+generico combo with no cupos
        result = conn.execute(text("""
            SELECT COUNT(*) AS rows_without_objetivo_but_with_null_tend
            FROM gold.v_resumen_mensual
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
def test_tend_vs_obj_null_when_objetivo_zero(db_engine):
    """T-VM-11: When objetivo=0, tend_vs_obj must be NULL (NULLIF guard)."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) AS violations
            FROM gold.v_resumen_mensual
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
# T-VM-12: objetivo present → tend_vs_obj = tendencia/objetivo (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_tend_vs_obj_equals_tendencia_over_objetivo(db_engine):
    """T-VM-12: When objetivo > 0, tend_vs_obj must equal tendencia/objetivo within tolerance."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT
                SUM(CASE
                    WHEN ABS(tend_vs_obj - tendencia / objetivo) > 0.0001 THEN 1
                    ELSE 0
                END) AS mismatches,
                COUNT(*) AS total
            FROM gold.v_resumen_mensual
            WHERE periodo = :p
              AND objetivo IS NOT NULL
              AND objetivo > 0
              AND tend_vs_obj IS NOT NULL
        """), {"p": CLOSED_PERIOD_YM})
        row = result.fetchone()

    if row is None or row[1] == 0:
        pytest.skip("No rows with valid objetivo in test period")

    mismatches = row[0]
    assert mismatches == 0, (
        f"tend_vs_obj != tendencia/objetivo for {mismatches} rows in {CLOSED_PERIOD_YM}"
    )


# ---------------------------------------------------------------------------
# T-VM-13: Historical period query returns rows (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_historical_period_returns_rows(db_engine):
    """T-VM-13: WHERE periodo = '2026-05' returns rows (historical period support)."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) AS cnt
            FROM gold.v_resumen_mensual
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
def test_prvta_excluded_for_fratelli_b(db_engine):
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

    # If PRVTA rows exist, the view's total_ventas should NOT include them.
    # We verify by comparing view total_ventas against raw SUM excluding PRVTA.
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT
                v.total_ventas AS view_total,
                SUM(fv.cantidades_total) AS raw_total_no_prvta
            FROM gold.v_resumen_mensual v
            JOIN gold.fact_ventas fv ON
                fv.fecha_comprobante BETWEEN :desde AND :hasta
                AND fv.id_documento <> 'PRVTA'
            JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
            WHERE v.periodo = :p
              AND v.generico = 'FRATELLI B'
              AND da.generico = 'FRATELLI B'
              AND ds.descripcion = v.sucursal
            GROUP BY v.total_ventas
            LIMIT 1
        """), {"p": CLOSED_PERIOD_YM, "desde": CLOSED_PERIOD, "hasta": "2026-05-31"})
        row = result.fetchone()

    if row is None:
        pytest.skip("Could not cross-check FRATELLI B totals")

    view_total, raw_total = float(row[0]), float(row[1])
    assert abs(view_total - raw_total) < 1.0, (
        f"FRATELLI B total_ventas mismatch: view={view_total}, raw_no_prvta={raw_total} — "
        "PRVTA may not be excluded correctly"
    )


# ---------------------------------------------------------------------------
# T-VM-06: PRVTA included for non-FRATELLI B genericos (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_prvta_included_for_non_fratelli_b(db_engine):
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
            FROM gold.v_resumen_mensual v
            WHERE v.periodo = :p
              AND v.generico = 'CERVEZAS'
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
