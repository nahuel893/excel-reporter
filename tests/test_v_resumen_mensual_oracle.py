"""
Oracle cross-check test — T-1.5 (THE CRITICAL CORRECTNESS GATE)

For a closed period (2026-05), run ResumenMensualService.generar_datos() and
compare its group totals against the materialized view gold.mv_resumen_mensual.

Both pipelines must agree within ±1 unit for:
  - SUBTOTAL CASA CENTRAL  ↔  SUM(total_ventas) WHERE grupo='CASA CENTRAL'
  - SUCURSALES SIN DIRECTA ↔  SUM(total_ventas) WHERE grupo='INTERIOR'
  - TOTAL SIN SMK (all)    ↔  SUM(total_ventas) all grupos

DB is required. Tests are skipped cleanly if DB is unreachable.

NOTE on data equivalence:
  The Excel pipeline uses config.genericos (specific list). The MV exposes
  ALL genericos. This test runs the Excel service with genericos=None (all)
  to achieve apples-to-apples comparison. If the service only has some genericos
  configured, totals for matching groups should still align.
"""

import os
from contextlib import contextmanager
from decimal import Decimal

import pytest


# ---------------------------------------------------------------------------
# DB availability helpers
# ---------------------------------------------------------------------------

def _try_get_db_engine():
    """Return a live SQLAlchemy engine or None if DB is unreachable."""
    try:
        from sqlalchemy import create_engine, text
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


@contextmanager
def _conn(engine):
    with engine.connect() as conn:
        yield conn


# Closed test period — May 2026 (month is complete; tendencia = total_ventas)
CLOSED_DESDE = "2026-05-01"
CLOSED_HASTA = "2026-05-31"
CLOSED_PERIOD_YM = "2026-05"

# Subtotal row labels from the Excel service (mirror service.py constants)
_SUBTOTAL_CC = "SUBTOTAL CASA CENTRAL"
_SUC_SIN_DIRECTA = "SUCURSALES SIN DIRECTA"
_TOTAL_SIN_SMK = "TOTAL SIN SMK"
_CC_FAMILY = {"CASA CENTRAL", "VALLE SALTA", "SUB DISTRIBUIDORES"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_engine():
    engine = _try_get_db_engine()
    if engine is None:
        pytest.skip("DB not reachable — skipping oracle cross-check tests")
    return engine


@pytest.fixture(scope="module")
def refreshed_mv(db_engine):
    """
    Ensure mv_resumen_mensual is populated before oracle tests query it.
    REFRESH CONCURRENTLY is safe to call repeatedly; no lock on reads.
    """
    from sqlalchemy import text
    with db_engine.connect() as conn:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_resumen_mensual"))
        conn.commit()
    return True


@pytest.fixture(scope="module")
def excel_totals(db_engine):
    """
    Run ResumenMensualService.generar_datos() for the closed period
    and extract the three group totals from the returned JSON structure.

    Returns a dict: {"cc": float, "interior": float, "total": float}
    """
    from src.core.data_loader import DataLoader
    from src.services.resumen_mensual.service import ResumenMensualService, ResumenMensualConfig

    config = ResumenMensualConfig(
        fecha_desde=CLOSED_DESDE,
        fecha_hasta=CLOSED_HASTA,
        genericos=None,  # all genericos → apples-to-apples with view
        con_objetivo=False,  # avoid fact_cupos dependency for this check
    )

    loader = DataLoader()
    service = ResumenMensualService(data_loader=loader)
    data = service.generar_datos(config)

    # The JSON structure from to_datos_json has a "sheets" list.
    # Each sheet has "rows" entries that may include subtotal rows.
    # We sum total_ventas across all sheets for each group.
    cc_total = 0.0
    interior_total = 0.0
    grand_total = 0.0

    sheets = data.get("sheets", [])
    for sheet in sheets:
        for section in sheet.get("sections", []):
            for row in section.get("rows", []):
                sucursal = row.get("Sucursal", "")
                total_ventas = float(row.get("Total Ventas") or 0)

                # Skip injected subtotal placeholder rows
                if sucursal in (_SUBTOTAL_CC, _SUC_SIN_DIRECTA, _TOTAL_SIN_SMK):
                    continue
                if not sucursal:
                    continue
                # Skip rows marked as subtotal
                if row.get("is_subtotal"):
                    continue

                grand_total += total_ventas
                if sucursal in _CC_FAMILY:
                    cc_total += total_ventas
                elif sucursal == "DIRECTA SUCURSALES":
                    pass  # not counted in INTERIOR or CC; included in grand_total
                else:
                    interior_total += total_ventas

    return {"cc": cc_total, "interior": interior_total, "total": grand_total}


@pytest.fixture(scope="module")
def view_totals(db_engine, refreshed_mv):
    """
    Query gold.mv_resumen_mensual for the closed period and return group sums.

    Returns a dict: {"cc": float, "interior": float, "total": float}
    """
    from sqlalchemy import text

    with _conn(db_engine) as conn:
        result = conn.execute(text("""
            SELECT
                SUM(CASE WHEN grupo = 'CASA CENTRAL' THEN total_ventas ELSE 0 END) AS cc,
                SUM(CASE WHEN grupo = 'INTERIOR'     THEN total_ventas ELSE 0 END) AS interior,
                SUM(total_ventas)                                                   AS total
            FROM gold.mv_resumen_mensual
            WHERE periodo = :p
        """), {"p": CLOSED_PERIOD_YM})
        row = result.fetchone()

    if row is None:
        pytest.skip(f"No rows in view for periodo='{CLOSED_PERIOD_YM}'")

    return {
        "cc":       float(row[0] or 0),
        "interior": float(row[1] or 0),
        "total":    float(row[2] or 0),
    }


# ---------------------------------------------------------------------------
# T-VM-ORACLE-01: CC family total matches
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_oracle_cc_family_total_matches(excel_totals, view_totals):
    """
    SUBTOTAL CASA CENTRAL from Excel ≈ SUM(total_ventas) WHERE grupo='CASA CENTRAL' from view.
    Tolerance: ±1 unit.
    """
    excel_cc = excel_totals["cc"]
    view_cc = view_totals["cc"]

    if excel_cc == 0 and view_cc == 0:
        pytest.skip("Both Excel and view return 0 for CC family — no data to compare")

    assert abs(excel_cc - view_cc) <= 1.0, (
        f"CC family total mismatch: Excel={excel_cc:.2f}, View={view_cc:.2f}, "
        f"diff={abs(excel_cc - view_cc):.2f} (tolerance ±1)"
    )


# ---------------------------------------------------------------------------
# T-VM-ORACLE-02: INTERIOR total matches
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_oracle_interior_total_matches(excel_totals, view_totals):
    """
    SUCURSALES SIN DIRECTA from Excel ≈ SUM(total_ventas) WHERE grupo='INTERIOR' from view.
    Tolerance: ±1 unit.
    """
    excel_interior = excel_totals["interior"]
    view_interior = view_totals["interior"]

    if excel_interior == 0 and view_interior == 0:
        pytest.skip("Both Excel and view return 0 for INTERIOR — no data to compare")

    assert abs(excel_interior - view_interior) <= 1.0, (
        f"INTERIOR total mismatch: Excel={excel_interior:.2f}, View={view_interior:.2f}, "
        f"diff={abs(excel_interior - view_interior):.2f} (tolerance ±1)"
    )


# ---------------------------------------------------------------------------
# T-VM-ORACLE-03: Grand total matches
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_oracle_grand_total_matches(excel_totals, view_totals):
    """
    TOTAL SIN SMK from Excel ≈ SUM(total_ventas) all grupos from view.
    Tolerance: ±1 unit.

    Note: DIRECTA SUCURSALES is counted in the grand total of both Excel and view.
    """
    excel_total = excel_totals["total"]
    view_total = view_totals["total"]

    if excel_total == 0 and view_total == 0:
        pytest.skip("Both Excel and view return 0 for grand total — no data to compare")

    assert abs(excel_total - view_total) <= 1.0, (
        f"Grand total mismatch: Excel={excel_total:.2f}, View={view_total:.2f}, "
        f"diff={abs(excel_total - view_total):.2f} (tolerance ±1)"
    )
