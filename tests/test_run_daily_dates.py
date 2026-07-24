"""Tests for scripts/run_daily.py date-range helpers.

Regression lock for the BLOCKER found in the final reliability review of
stock-badie: the daily must send a fecha_hasta that INCLUDES the last day
of the reported month (or today). The mes_completo mode emits fecha_hasta
as the EXCLUSIVE upper bound (1st of next month, or tomorrow for the
current month), so the consumer's SQL `fecha < :fecha_hasta` includes the
last day of the period.

Calendar scenarios used:
- Feb 2026: day 1 is Sunday; Monday Feb 2 is the first business day.
  mes_a_hoy must return the CLOSED previous month (Jan 1-31).
  mes_completo must return (Jan 1, Feb 1) so the consumer's
  `fecha < 2026-02-01` includes Jan 31.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# scripts/run_daily.py uses a @dataclass(frozen=True) decorator that depends
# on `Servicio` being importable as main.Servicio — it imports main at
# module top, so load it via importlib to bypass the python-3.14
# __module__-annotation quirk noted in the PR6 review.
_spec = importlib.util.spec_from_file_location("run_daily", ROOT / "scripts" / "run_daily.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules["run_daily"] = _mod
_spec.loader.exec_module(_mod)


def test_mes_completo_closed_prev_month_first_business_day_includes_last_day():
    """Feb 1 2026 is Sunday; Feb 2 (Mon) is the first business day.
    mes_completo must return (2026-01-01, 2026-02-01) so the consumer's
    SQL `fecha < 2026-02-01` includes Jan 31 — the date that the legacy
    mes_a_hoy would have ENDED on (and therefore lost)."""
    fd, fh = _mod._resolve_mes_completo_range(date(2026, 2, 2))
    assert fd == "2026-01-01"
    assert fh == "2026-02-01"


def test_mes_completo_current_month_to_date_includes_today():
    """Mid-month: fecha_hasta = tomorrow (exclusive) so today IS included."""
    fd, fh = _mod._resolve_mes_completo_range(date(2026, 8, 19))
    assert fd == "2026-08-01"
    assert fh == "2026-08-20"


def test_mes_a_hoy_unchanged_inclusive_bounds():
    """The existing mes_a_hoy contract is unchanged: inclusive fecha_hasta
    (last day of closed month or today). Verified on the same Feb 2026
    trigger so the BLOCKER is obvious from the diff."""
    fd, fh = _mod._resolve_mes_a_hoy_range(date(2026, 2, 2))
    assert fd == "2026-01-01"
    assert fh == "2026-01-31"  # inclusive — this is the historical bug

    fd2, fh2 = _mod._resolve_mes_a_hoy_range(date(2026, 8, 19))
    assert fd2 == "2026-08-01"
    assert fh2 == "2026-08-19"  # inclusive today


def test_servicio_patch_mes_completo_uses_exclusive_upper_bound():
    """End-to-end: Servicio.fecha_modo='mes_completo' patches fecha_hasta
    to the exclusive upper bound (1st of next month, for the closed previous
    month case)."""
    from scripts.run_daily import Servicio  # type: ignore  # noqa: F401
    svc = Servicio(
        nombre="stock-badie",
        config_path=Path("configs/stock_badie.json"),
        fecha_modo="mes_completo",
    )
    patched = svc.patch({"filtros": {}}, date(2026, 2, 2))  # 1st biz day of Feb
    assert patched["filtros"]["fecha_desde"] == "2026-01-01"
    assert patched["filtros"]["fecha_hasta"] == "2026-02-01"


def test_servicio_patch_mes_a_hoy_unchanged_for_other_services():
    """Other services on mes_a_hoy (champions-league, etc.) keep inclusive
    bounds — no regression for the rest of the daily."""
    from scripts.run_daily import Servicio  # type: ignore  # noqa: F401
    svc = Servicio(
        nombre="champions-league",
        config_path=Path("configs/champions_league.json"),
        fecha_modo="mes_a_hoy",
    )
    patched = svc.patch({"filtros": {}}, date(2026, 2, 2))
    assert patched["filtros"]["fecha_hasta"] == "2026-01-31"  # inclusive, unchanged
