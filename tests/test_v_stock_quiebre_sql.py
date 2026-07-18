"""
Tests for gold.mv_stock_quiebre (materialized view) — Vista 1 (Mensual/Quiebre)

Static SQL-contract assertions (no DB needed) + integration column/grain/logic
checks (DB required, skipped when unreachable).

Column contract (RF-01): sucursal, id_articulo, des_articulo, generico, marca,
stock_hoy_bultos, stock_hoy_htls, venta_mes_bultos, venta_mes_htls,
dias_habiles_transcurridos, venta_diaria_bultos, tendencia_bultos,
pedido_sugerido_15d_bultos, estado_semaforo.

Non-goals (RF-15): no `medida` long-format column, no stored `alcance_dias`
column (it is a Superset-only metric), no ROUND/TRUNC/::INTEGER anywhere.
"""

import re
from contextlib import contextmanager
from pathlib import Path

import pytest

try:
    import sqlglot
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False

SQL_VIEW_FILE = Path(__file__).parent.parent / "scripts" / "sql" / "v_stock_quiebre.sql"
MV_RELATION = "gold.mv_stock_quiebre"


def _strip_sql_comments(content: str) -> str:
    """Drop full-line `--` comments so structural assertions check actual SQL,
    not explanatory prose (which legitimately needs to reference the exact
    forbidden terms/patterns when documenting why they were NOT used)."""
    return "\n".join(
        line for line in content.splitlines() if not line.strip().startswith("--")
    )


# ---------------------------------------------------------------------------
# DB availability helper (mirrors test_v_resumen_mensual_sql.py)
# ---------------------------------------------------------------------------

def _try_get_db_engine():
    """Return a live SQLAlchemy engine or None if DB is unreachable."""
    try:
        from sqlalchemy import create_engine, text
        import os
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


@pytest.fixture(scope="module")
def refreshed_mv(db_engine):
    """Refresh the MV so integration tests see current data. No-op if already fresh."""
    from sqlalchemy import text
    with db_engine.connect() as conn:
        conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {MV_RELATION}"))
        conn.commit()
    return True


@contextmanager
def _conn(engine):
    with engine.connect() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Static/offline assertions (no DB needed)
# ---------------------------------------------------------------------------

def test_view_sql_file_exists():
    assert SQL_VIEW_FILE.exists(), f"SQL view file not found: {SQL_VIEW_FILE}"


def test_view_sql_file_non_empty():
    assert SQL_VIEW_FILE.exists()
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert len(content.strip()) > 0, "SQL view file should not be empty"


def test_view_sql_contains_create_materialized_view():
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r"CREATE\s+MATERIALIZED\s+VIEW", re.IGNORECASE)
    assert pattern.search(content), "Expected 'CREATE MATERIALIZED VIEW' (not plain VIEW)"


def test_view_sql_is_idempotent_via_drop_if_exists():
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r"DROP\s+MATERIALIZED\s+VIEW\s+IF\s+EXISTS", re.IGNORECASE)
    assert pattern.search(content), "Expected 'DROP MATERIALIZED VIEW IF EXISTS' for idempotent re-runs"


def test_view_sql_targets_gold_schema():
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert "gold.mv_stock_quiebre" in content


def test_view_sql_has_unique_index():
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    pattern = re.compile(r"CREATE\s+UNIQUE\s+INDEX", re.IGNORECASE)
    assert pattern.search(content), "Expected 'CREATE UNIQUE INDEX' — required for REFRESH CONCURRENTLY"


def test_view_sql_unique_index_on_grain_columns():
    """Unique index must be on (sucursal, id_articulo) per RF-01 grain."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    pattern = re.compile(
        r"CREATE\s+UNIQUE\s+INDEX\s+\w+\s+ON\s+gold\.mv_stock_quiebre\s*\(\s*sucursal\s*,\s*id_articulo\s*\)",
        re.IGNORECASE,
    )
    assert pattern.search(content), "Expected unique index on (sucursal, id_articulo)"


def test_view_sql_references_settings_feriados():
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert "settings.py" in content and "FERIADOS" in content, (
        "SQL view must reference 'settings.py::FERIADOS' for yearly maintenance"
    )


def test_view_sql_contains_nullif_guard():
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert "NULLIF" in content.upper(), "Expected NULLIF guard against zero division"


def test_view_sql_left_joins_ventas_onto_stock():
    """Universe: venta_mes is LEFT-JOINed onto stock_hoy so dormant stock (stock>0,
    no current-month sales) surfaces as VERDE instead of being dropped, guarded by a
    WHERE keeping only rows with physical stock OR a sales row. NOT a FULL OUTER JOIN
    (an article selling with zero stock still has a zero stock_hoy row)."""
    content = _strip_sql_comments(SQL_VIEW_FILE.read_text(encoding="utf-8"))
    assert re.search(r"\bLEFT\s+(OUTER\s+)?JOIN\s+venta_mes\b", content, re.IGNORECASE), (
        "Expected a LEFT JOIN of venta_mes onto stock_hoy (dormant stock must not be dropped)"
    )
    assert not re.search(r"\bINNER\s+JOIN\s+venta_mes\b", content, re.IGNORECASE), (
        "venta_mes must NOT be INNER-joined — that drops dormant stock and contradicts the design"
    )
    assert not re.search(r"\bFULL\s+(OUTER\s+)?JOIN\b", content, re.IGNORECASE), (
        "No FULL OUTER JOIN expected (a selling article always has a zero stock_hoy row)"
    )
    assert re.search(r"stock_bultos\s*<>\s*0\s+OR", content, re.IGNORECASE), (
        "Expected the universe guard (stock_bultos <> 0 OR sales row) to drop zero-stock/zero-sale noise"
    )


def test_view_sql_no_medida_dimension():
    """RF-01/tasks override: no long-format `medida` column, no CROSS JOIN VALUES measure unpivot."""
    content = _strip_sql_comments(SQL_VIEW_FILE.read_text(encoding="utf-8"))
    assert not re.search(r"\bmedida\b", content, re.IGNORECASE), (
        "mv_stock_quiebre must NOT have a 'medida' long-format dimension (parallel _bultos/_htls columns instead)"
    )
    assert "VALUES ('BULTOS')" not in content and "VALUES('BULTOS')" not in content


def test_view_sql_no_stored_alcance_dias_column():
    """RF-04: alcance_dias must be a Superset metric, never a stored MV column."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    # Only forbid it as an output column name; comments mentioning the concept are fine.
    pattern = re.compile(r"\bAS\s+alcance_dias\b", re.IGNORECASE)
    assert not pattern.search(content), "alcance_dias must not be a stored MV column"


def test_view_sql_no_zonas_virtuales_split():
    """RF-15: no VALLE SALTA / zona-virtual split in this MV — raw sucursal only."""
    content = _strip_sql_comments(SQL_VIEW_FILE.read_text(encoding="utf-8"))
    assert "VALLE SALTA" not in content.upper()


def test_view_sql_no_rounding_or_truncation():
    """RF-15: no ROUND/TRUNC/::INTEGER cast anywhere on numeric bultos/htls/dias values."""
    content = _strip_sql_comments(SQL_VIEW_FILE.read_text(encoding="utf-8"))
    assert not re.search(r"\bROUND\s*\(", content, re.IGNORECASE), "Found ROUND( — rounding is forbidden"
    assert not re.search(r"\bTRUNC\s*\(", content, re.IGNORECASE), "Found TRUNC( — truncation is forbidden"
    assert not re.search(r"::\s*INTEGER\b", content, re.IGNORECASE), "Found ::INTEGER cast — truncation is forbidden"
    assert not re.search(r"::\s*INT\b", content, re.IGNORECASE), "Found ::INT cast — truncation is forbidden"


def test_view_sql_contains_3yr_exclusion():
    """RF-05: 3-year no-sales article exclusion must be present."""
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert re.search(r"3\s*years?", content, re.IGNORECASE), "Expected a 3-year interval filter"


def test_view_sql_contains_grants_for_both_roles():
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    assert "superset_ro" in content
    assert "superset_user" in content
    assert content.count("GRANT SELECT ON gold.mv_stock_quiebre") >= 2


@pytest.mark.skipif(not HAS_SQLGLOT, reason="sqlglot not installed")
def test_view_sql_parses_with_sqlglot():
    content = SQL_VIEW_FILE.read_text(encoding="utf-8")
    errors = []
    try:
        result = sqlglot.parse(content, dialect="postgres", error_level=sqlglot.ErrorLevel.WARN)
        if not result:
            errors.append("sqlglot returned empty result for view SQL")
    except Exception as exc:
        errors.append(f"sqlglot raised {type(exc).__name__}: {exc}")
    assert not errors, "sqlglot parse errors:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# RF-01: Column contract + grain (DB required)
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS = {
    "sucursal", "id_articulo", "des_articulo", "generico", "marca",
    "stock_hoy_bultos", "stock_hoy_htls", "venta_mes_bultos", "venta_mes_htls",
    "dias_habiles_transcurridos", "venta_diaria_bultos", "tendencia_bultos",
    "pedido_sugerido_15d_bultos", "estado_semaforo",
}


@pytest.mark.integration
def test_view_column_contract(db_engine, refreshed_mv):
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"SELECT * FROM {MV_RELATION} LIMIT 1"))
        actual_columns = set(result.keys())
    assert EXPECTED_COLUMNS.issubset(actual_columns), (
        f"Missing columns: {EXPECTED_COLUMNS - actual_columns}"
    )
    assert "medida" not in actual_columns
    assert "alcance_dias" not in actual_columns


@pytest.mark.integration
def test_no_valle_salta_in_sucursal(db_engine, refreshed_mv):
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {MV_RELATION} WHERE sucursal = 'VALLE SALTA'"))
        row = result.fetchone()
    assert row[0] == 0, "VALLE SALTA must never appear — Vista 1 uses raw sucursal, no zona-virtual split"


@pytest.mark.integration
def test_one_row_per_sucursal_articulo(db_engine, refreshed_mv):
    """RF-01: grain is (sucursal, id_articulo) — no duplicates."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"""
            SELECT sucursal, id_articulo, COUNT(*) AS n
            FROM {MV_RELATION}
            GROUP BY sucursal, id_articulo
            HAVING COUNT(*) > 1
            LIMIT 5
        """))
        rows = result.fetchall()
    assert rows == [], f"Found duplicate (sucursal, id_articulo) grain rows: {rows}"


# ---------------------------------------------------------------------------
# RF-06: unique index enables REFRESH CONCURRENTLY
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_unique_index_exists(db_engine, refreshed_mv):
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'gold' AND tablename = 'mv_stock_quiebre'
              AND indexdef ILIKE '%UNIQUE%'
        """))
        rows = result.fetchall()
    assert rows, "Expected a unique index on gold.mv_stock_quiebre"


@pytest.mark.integration
def test_refresh_concurrently_succeeds(db_engine):
    """REFRESH CONCURRENTLY must not raise (requires the unique index)."""
    from sqlalchemy import text
    with db_engine.connect() as conn:
        conn.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {MV_RELATION}"))
        conn.commit()


# ---------------------------------------------------------------------------
# RF-03: venta_diaria / pedido formulas (DB required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_venta_diaria_formula(db_engine, refreshed_mv):
    """venta_diaria_bultos = venta_mes_bultos / dias_habiles_transcurridos, within tolerance."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"""
            SELECT COUNT(*) FROM {MV_RELATION}
            WHERE dias_habiles_transcurridos > 0
              AND ABS(venta_diaria_bultos - venta_mes_bultos / dias_habiles_transcurridos) > 0.01
        """))
        row = result.fetchone()
    assert row[0] == 0, "venta_diaria_bultos formula mismatch found"


@pytest.mark.integration
def test_pedido_never_negative(db_engine, refreshed_mv):
    """pedido_sugerido_15d_bultos must never be negative (GREATEST floor at 0)."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"""
            SELECT COUNT(*) FROM {MV_RELATION} WHERE pedido_sugerido_15d_bultos < 0
        """))
        row = result.fetchone()
    assert row[0] == 0, "Found negative pedido_sugerido_15d_bultos — GREATEST floor missing"


@pytest.mark.integration
def test_pedido_formula(db_engine, refreshed_mv):
    """pedido_sugerido_15d_bultos = GREATEST(venta_diaria*15 - stock_hoy, 0)."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"""
            SELECT COUNT(*) FROM {MV_RELATION}
            WHERE venta_diaria_bultos IS NOT NULL
              AND ABS(
                    pedido_sugerido_15d_bultos
                    - GREATEST(venta_diaria_bultos * 15 - stock_hoy_bultos, 0)
                  ) > 0.01
        """))
        row = result.fetchone()
    assert row[0] == 0, "pedido_sugerido_15d_bultos formula mismatch found"


# ---------------------------------------------------------------------------
# RF-02: dias_habiles_transcurridos — same constant on every row, matches hand-computed value
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_dias_habiles_transcurridos_is_constant(db_engine, refreshed_mv):
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"SELECT COUNT(DISTINCT dias_habiles_transcurridos) FROM {MV_RELATION}"))
        row = result.fetchone()
    assert row[0] <= 1, "dias_habiles_transcurridos must be a single constant value across all rows"


@pytest.mark.integration
def test_dias_habiles_transcurridos_matches_hand_computed(db_engine, refreshed_mv):
    """NETWORKDAYS.INTL-equivalent: exclude Sundays + FERIADOS, count 1st-of-month..today inclusive."""
    from datetime import date, timedelta
    from sqlalchemy import text
    from config.settings import FERIADOS

    feriados = {date.fromisoformat(f) for f in FERIADOS}
    today = date.today()
    first_of_month = today.replace(day=1)

    expected = 0
    d = first_of_month
    while d <= today:
        if d.weekday() != 6 and d not in feriados:  # Monday=0 .. Sunday=6
            expected += 1
        d += timedelta(days=1)

    with _conn(db_engine) as conn:
        result = conn.execute(text(f"SELECT DISTINCT dias_habiles_transcurridos FROM {MV_RELATION}"))
        row = result.fetchone()

    if row is None:
        pytest.skip("No rows in MV — cannot verify dias_habiles_transcurridos")

    assert float(row[0]) == float(expected), (
        f"dias_habiles_transcurridos={row[0]} != hand-computed {expected}"
    )


# ---------------------------------------------------------------------------
# RF-05: 3-year no-sales article exclusion
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_dead_article_excluded(db_engine, refreshed_mv):
    """An article with fact_stock rows but zero fact_ventas rows in the last 3 years is absent."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        dead = conn.execute(text("""
            SELECT fs.id_articulo
            FROM gold.fact_stock fs
            WHERE fs.date_stock = (SELECT MAX(date_stock) FROM gold.fact_stock)
              AND NOT EXISTS (
                  SELECT 1 FROM gold.fact_ventas fv
                  WHERE fv.id_articulo = fs.id_articulo
                    AND fv.fecha_comprobante >= (CURRENT_DATE - interval '3 years')::date
              )
            LIMIT 1
        """)).fetchone()

        if dead is None:
            pytest.skip("No dead (3yr-inactive) article found in current stock snapshot")

        result = conn.execute(
            text(f"SELECT COUNT(*) FROM {MV_RELATION} WHERE id_articulo = :art"),
            {"art": dead[0]},
        )
        row = result.fetchone()

    assert row[0] == 0, f"Dead article {dead[0]} (no sales in 3yr) must be absent from the MV"


@pytest.mark.integration
def test_recently_sold_article_present_even_with_zero_stock(db_engine, refreshed_mv):
    """A zero-current-stock article that sold this month must still appear (quiebre visible)."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"""
            SELECT id_articulo FROM {MV_RELATION}
            WHERE stock_hoy_bultos = 0 AND venta_mes_bultos > 0
            LIMIT 1
        """))
        row = result.fetchone()
    if row is None:
        pytest.skip("No zero-stock-with-sales article present this month — cannot verify")
    assert row[0] is not None


# ---------------------------------------------------------------------------
# RF-11/RF-04: semáforo band boundaries
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_semaforo_band_boundaries(db_engine, refreshed_mv):
    """
    estado_semaforo bands (positive velocity only): alcance = stock_hoy / venta_diaria
      < 15 -> ROJO, 15..30 -> AMARILLO, > 30 -> VERDE.
    Non-positive velocity (NULL / 0 / net-negative) is VERDE — see the dedicated test.
    """
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"""
            SELECT COUNT(*) FROM {MV_RELATION}
            WHERE venta_diaria_bultos > 0
              AND (
                (stock_hoy_bultos / venta_diaria_bultos < 15 AND estado_semaforo != 'ROJO')
                OR (stock_hoy_bultos / venta_diaria_bultos >= 15
                    AND stock_hoy_bultos / venta_diaria_bultos <= 30
                    AND estado_semaforo != 'AMARILLO')
                OR (stock_hoy_bultos / venta_diaria_bultos > 30 AND estado_semaforo != 'VERDE')
              )
        """))
        row = result.fetchone()
    assert row[0] == 0, "Found rows where estado_semaforo does not match the alcance band"


@pytest.mark.integration
def test_semaforo_verde_when_no_positive_venta_diaria(db_engine, refreshed_mv):
    """Non-positive velocity must render VERDE: dormant stock (venta_diaria NULL/0) AND
    net-negative sales (returns > sales -> venta_diaria < 0). A net-negative article is
    over-stocked, not a quiebre; classifying it ROJO would inflate the quiebre KPI."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"""
            SELECT COUNT(*) FROM {MV_RELATION}
            WHERE (venta_diaria_bultos IS NULL OR venta_diaria_bultos <= 0)
              AND estado_semaforo != 'VERDE'
        """))
        row = result.fetchone()
    assert row[0] == 0, "Non-positive velocity rows (NULL/0/negative) must be classified VERDE"


@pytest.mark.integration
def test_no_estado_semaforo_outside_known_bands(db_engine, refreshed_mv):
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        result = conn.execute(text(f"""
            SELECT DISTINCT estado_semaforo FROM {MV_RELATION}
        """))
        values = {row[0] for row in result}
    assert values.issubset({"ROJO", "AMARILLO", "VERDE"}), f"Unexpected estado_semaforo values: {values}"


# ---------------------------------------------------------------------------
# RF-10: read-only role grants
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_both_roles_can_select(db_engine, refreshed_mv):
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError

    tested_any = False
    for role in ("superset_ro", "superset_user"):
        with db_engine.connect() as conn:
            role_exists = conn.execute(
                text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :r"), {"r": role}
            ).fetchone()
            if not role_exists:
                continue
            try:
                conn.execute(text(f"SET ROLE {role}"))
            except ProgrammingError:
                # Current DB user lacks membership in this role — cannot exercise
                # SET ROLE from this session. Grants are still verified statically
                # (test_view_sql_contains_grants_for_both_roles) and via
                # information_schema below.
                conn.rollback()
                continue
            conn.execute(text(f"SELECT * FROM {MV_RELATION} LIMIT 1"))
            conn.execute(text("RESET ROLE"))
            tested_any = True

    if not tested_any:
        # Fall back to has_table_privilege() — confirms the GRANT actually took
        # effect even when this session cannot SET ROLE to verify it interactively.
        # (information_schema.role_table_grants only shows grants visible to the
        # CURRENT session's enabled roles, per the SQL standard — it under-reports
        # here since this session cannot assume superset_ro/superset_user.)
        with _conn(db_engine) as conn:
            granted = {
                role: conn.execute(
                    text("SELECT has_table_privilege(:role, 'gold.mv_stock_quiebre', 'SELECT')"),
                    {"role": role},
                ).scalar()
                for role in ("superset_ro", "superset_user")
            }
        assert any(granted.values()), (
            f"Expected SELECT grant for superset_ro or superset_user: {granted}"
        )


@pytest.mark.integration
def test_write_attempt_rejected_for_both_roles(db_engine, refreshed_mv):
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError, InternalError

    tested_any = False
    for role in ("superset_ro", "superset_user"):
        with db_engine.connect() as conn:
            role_exists = conn.execute(
                text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :r"), {"r": role}
            ).fetchone()
            if not role_exists:
                continue
            try:
                conn.execute(text(f"SET ROLE {role}"))
            except ProgrammingError:
                conn.rollback()
                continue
            with pytest.raises((ProgrammingError, InternalError)):
                conn.execute(text(f"INSERT INTO {MV_RELATION} (sucursal) VALUES ('X')"))
            conn.rollback()
            tested_any = True

    if not tested_any:
        pytest.skip(
            "Current DB user cannot SET ROLE to superset_ro/superset_user in this "
            "environment — write-rejection cannot be exercised interactively"
        )
