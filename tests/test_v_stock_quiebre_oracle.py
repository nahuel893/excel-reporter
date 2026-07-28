"""
Oracle cross-check test — gold.mv_stock_quiebre (RF-07, THE CRITICAL CORRECTNESS GATE)

For a sample (sucursal, id_articulo) pair, the MV's venta_mes_bultos,
stock_hoy_bultos, and the derived alcance_dias must match a DIRECT
fact_ventas/fact_stock query using the same formulas, within +/-1, with NO
rounding on either side.

DB is required. All tests are skipped cleanly if the DB is unreachable.
Because Vista 1 is inherently a "current month / latest snapshot" view (not a
fixed historical period like mv_resumen_mensual), samples are discovered
dynamically at test time rather than hardcoded — the assertions stay valid
regardless of which day the suite runs.
"""

from contextlib import contextmanager
from pathlib import Path

import pytest


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
        pytest.skip("DB not reachable — skipping oracle cross-check tests")
    return engine


@pytest.fixture(scope="module")
def refreshed_mv(db_engine):
    from sqlalchemy import text
    with db_engine.connect() as conn:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_stock_quiebre"))
        conn.commit()
    return True


@contextmanager
def _conn(engine):
    with engine.connect() as conn:
        yield conn


# ---------------------------------------------------------------------------
# T-ORACLE-01: sample row totals match a direct fact_ventas/fact_stock query
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_oracle_sample_row_matches_direct_query(db_engine, refreshed_mv):
    """
    Pick any one (sucursal, id_articulo) from the MV, then recompute
    venta_mes_bultos and stock_hoy_bultos directly from fact_ventas/fact_stock
    for the SAME sucursal+articulo+period, and compare within +/-1.
    """
    from sqlalchemy import text

    with _conn(db_engine) as conn:
        sample = conn.execute(text("""
            SELECT sucursal, id_articulo, venta_mes_bultos, stock_hoy_bultos,
                   dias_habiles_transcurridos, venta_diaria_bultos
            FROM gold.mv_stock_quiebre
            ORDER BY id_articulo
            LIMIT 1
        """)).fetchone()

    if sample is None:
        pytest.skip("mv_stock_quiebre is empty — nothing to cross-check")

    sucursal, id_articulo, mv_venta, mv_stock, dias_habiles, mv_venta_diaria = sample

    with _conn(db_engine) as conn:
        direct = conn.execute(text("""
            SELECT
                (SELECT COALESCE(SUM(fv.cantidades_total), 0)
                 FROM gold.fact_ventas fv
                 JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
                 WHERE ds.descripcion = :sucursal
                   AND fv.id_articulo = :articulo
                   AND fv.fecha_comprobante >= date_trunc('month', CURRENT_DATE)::date
                   AND fv.fecha_comprobante < (date_trunc('month', CURRENT_DATE) + interval '1 month')::date
                ) AS direct_venta,
                (SELECT COALESCE(SUM(fs.cant_bultos), 0)
                 FROM gold.fact_stock fs
                 JOIN gold.dim_deposito dd ON fs.id_deposito = dd.id_deposito
                 WHERE dd.id_sucursal = (SELECT id_sucursal FROM gold.dim_sucursal WHERE descripcion = :sucursal)
                   AND fs.id_articulo = :articulo
                   AND fs.date_stock = (SELECT MAX(date_stock) FROM gold.fact_stock)
                ) AS direct_stock
        """), {"sucursal": sucursal, "articulo": id_articulo}).fetchone()

    direct_venta, direct_stock = float(direct[0]), float(direct[1])

    # Both sides SUM the same rows with the same filters -> the delta is exactly 0.
    # The 1e-6 window only tolerates float-repr noise; it still catches any ROUND()/
    # TRUNC regression in the MV (the whole point of this oracle gate).
    assert abs(float(mv_venta) - direct_venta) <= 1e-6, (
        f"venta_mes_bultos mismatch for {sucursal}/{id_articulo}: "
        f"MV={mv_venta}, direct={direct_venta}"
    )
    assert abs(float(mv_stock) - direct_stock) <= 1e-6, (
        f"stock_hoy_bultos mismatch for {sucursal}/{id_articulo}: "
        f"MV={mv_stock}, direct={direct_stock}"
    )

    # alcance_dias cross-check (Superset metric formula, computed here in Python):
    # alcance_dias = stock_hoy_bultos / (venta_mes_bultos / dias_habiles_transcurridos)
    if dias_habiles and float(dias_habiles) != 0 and direct_venta != 0:
        direct_venta_diaria = direct_venta / float(dias_habiles)
        direct_alcance = direct_stock / direct_venta_diaria if direct_venta_diaria else None
        if mv_venta_diaria and float(mv_venta_diaria) != 0:
            mv_alcance = float(mv_stock) / float(mv_venta_diaria)
            if direct_alcance is not None:
                # Relative tolerance: alcance is a ratio, and mv_venta_diaria is a
                # Postgres NUMERIC (finite scale) while direct is double — the delta is
                # float-repr noise, not rounding. Still orders of magnitude tighter than
                # the band widths (15, 30), so a real ROUND() regression is caught.
                assert abs(mv_alcance - direct_alcance) <= 1e-6 * max(1.0, abs(direct_alcance)), (
                    f"alcance_dias mismatch for {sucursal}/{id_articulo}: "
                    f"MV-derived={mv_alcance}, direct={direct_alcance}"
                )


# ---------------------------------------------------------------------------
# T-ORACLE-02: 3-year-excluded (dead) article is absent from the MV
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_oracle_3yr_excluded_article_absent(db_engine, refreshed_mv):
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
            pytest.skip("No 3yr-dead article found in current stock snapshot")

        count = conn.execute(
            text("SELECT COUNT(*) FROM gold.mv_stock_quiebre WHERE id_articulo = :art"),
            {"art": dead[0]},
        ).scalar()

    assert count == 0, f"Article {dead[0]} has no sales in 3yr but appears in mv_stock_quiebre"


# ---------------------------------------------------------------------------
# T-ORACLE-03: known zero-stock-with-sales article shows ROJO
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_oracle_zero_stock_with_sales_shows_rojo(db_engine, refreshed_mv):
    """A quiebre-in-progress article (0 stock, positive sales this month) must be ROJO."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        row = conn.execute(text("""
            SELECT sucursal, id_articulo, estado_semaforo
            FROM gold.mv_stock_quiebre
            WHERE stock_hoy_bultos = 0 AND venta_mes_bultos > 0
            LIMIT 1
        """)).fetchone()

    if row is None:
        pytest.skip("No zero-stock-with-sales article present this month — cannot verify")

    assert row[2] == "ROJO", (
        f"Expected ROJO for zero-stock quiebre {row[0]}/{row[1]}, got {row[2]!r}"
    )


# ---------------------------------------------------------------------------
# T-ORACLE-03b: dormant stock (stock>0, no sales this month) is present and VERDE
# Locks the LEFT-JOIN universe fix: an INNER join would drop these rows entirely.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_oracle_dormant_stock_present_and_verde(db_engine, refreshed_mv):
    """An article with physical stock but zero current-month sales must appear
    (not be dropped) and be VERDE (no quiebre risk without demand)."""
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        total = conn.execute(text("""
            SELECT count(*) FROM gold.mv_stock_quiebre
            WHERE stock_hoy_bultos > 0 AND venta_mes_bultos = 0
        """)).scalar()
        row = conn.execute(text("""
            SELECT sucursal, id_articulo, estado_semaforo, pedido_sugerido_15d_bultos
            FROM gold.mv_stock_quiebre
            WHERE stock_hoy_bultos > 0 AND venta_mes_bultos = 0
            LIMIT 1
        """)).fetchone()

    assert total > 0, (
        "No dormant-stock rows (stock>0, no sales) in the MV — the LEFT-JOIN universe "
        "regressed to INNER and is dropping dormant stock"
    )
    assert row[2] == "VERDE", (
        f"Dormant stock {row[0]}/{row[1]} must be VERDE, got {row[2]!r}"
    )
    assert float(row[3]) == 0.0, (
        f"Dormant stock should suggest pedido 0, got {row[3]}"
    )


# ---------------------------------------------------------------------------
# T-ORACLE-04: pedido formula cross-check on the same sample row
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_oracle_pedido_formula_on_sample_row(db_engine, refreshed_mv):
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        row = conn.execute(text("""
            SELECT stock_hoy_bultos, venta_diaria_bultos, pedido_sugerido_15d_bultos
            FROM gold.mv_stock_quiebre
            WHERE venta_diaria_bultos IS NOT NULL
            ORDER BY id_articulo
            LIMIT 1
        """)).fetchone()

    if row is None:
        pytest.skip("No rows with non-null venta_diaria_bultos — cannot verify pedido formula")

    stock, venta_diaria, pedido = float(row[0]), float(row[1]), float(row[2])
    expected = max(venta_diaria * 15 - stock, 0)
    assert abs(pedido - expected) <= 0.01, (
        f"pedido_sugerido_15d_bultos={pedido} != expected {expected}"
    )


# ---------------------------------------------------------------------------
# T-ORACLE-05: universe boundary — a zero-stock article the sucursal has NEVER
# sold in 3 years is ABSENT (we surface real quiebres, we do NOT fall back to
# every-article-in-every-sucursal noise). Locks against the rejected "Option B".
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_oracle_zero_stock_never_sold_here_is_absent(db_engine, refreshed_mv):
    from sqlalchemy import text
    with _conn(db_engine) as conn:
        cand = conn.execute(text("""
            WITH snap AS (SELECT MAX(date_stock) d FROM gold.fact_stock),
            stock_hoy AS (
                SELECT dd.id_sucursal, fs.id_articulo, SUM(fs.cant_bultos) AS sb
                FROM gold.fact_stock fs
                JOIN gold.dim_deposito dd ON fs.id_deposito = dd.id_deposito
                WHERE fs.date_stock = (SELECT d FROM snap)
                GROUP BY 1, 2
            )
            SELECT ds.descripcion, sh.id_articulo
            FROM stock_hoy sh
            JOIN gold.dim_sucursal ds ON ds.id_sucursal = sh.id_sucursal
            WHERE sh.sb = 0
              AND sh.id_articulo IN (
                  SELECT DISTINCT id_articulo FROM gold.fact_ventas
                  WHERE fecha_comprobante >= (CURRENT_DATE - interval '3 years')::date
              )
              AND NOT EXISTS (
                  SELECT 1 FROM gold.fact_ventas fv
                  WHERE fv.id_sucursal = sh.id_sucursal
                    AND fv.id_articulo = sh.id_articulo
                    AND fv.fecha_comprobante >= (CURRENT_DATE - interval '3 years')::date
              )
            LIMIT 1
        """)).fetchone()

        if cand is None:
            pytest.skip("No zero-stock/never-sold-here candidate found — cannot verify boundary")

        present = conn.execute(text("""
            SELECT COUNT(*) FROM gold.mv_stock_quiebre
            WHERE sucursal = :suc AND id_articulo = :art
        """), {"suc": cand[0], "art": cand[1]}).scalar()

    assert present == 0, (
        f"Article {cand[1]} is zero-stock and never sold by '{cand[0]}' in 3yr — it must NOT "
        f"appear (that would be the rejected every-article-in-every-sucursal noise)"
    )
