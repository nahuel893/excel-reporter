from datetime import date
from pathlib import Path

import scripts.run_daily as run_daily

from scripts.run_daily import (
    Servicio,
    _is_business_day,
    _is_first_business_day_of_month,
    _resolve_mes_a_hoy_range,
)


def _raw_config() -> dict:
    return {"filtros": {"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"}}


class TestBusinessDayHelpers:
    def test_is_business_day_excludes_sunday(self):
        assert _is_business_day(date(2026, 6, 7)) is False

    def test_is_business_day_excludes_holiday(self):
        assert _is_business_day(date(2026, 6, 20)) is False

    def test_is_first_business_day_of_month_on_plain_first(self):
        assert _is_first_business_day_of_month(date(2026, 6, 1)) is True

    def test_is_first_business_day_of_month_skips_sunday_and_holiday(self):
        # 2026-11-01 is Sunday; 2026-11-02 is the first business day.
        assert _is_first_business_day_of_month(date(2026, 11, 2)) is True

    def test_is_first_business_day_of_month_skips_holiday_then_sunday(self, monkeypatch):
        # 2026-08-01 is forced as holiday and 2026-08-02 is Sunday,
        # so 2026-08-03 becomes the first business day.
        monkeypatch.setattr(run_daily, "FERIADOS", ["2026-08-01"])

        assert _is_first_business_day_of_month(date(2026, 8, 3)) is True


class TestMesAHoyRange:
    def test_resolve_mes_a_hoy_range_on_first_business_day_returns_previous_month(self):
        assert _resolve_mes_a_hoy_range(date(2026, 6, 1)) == ("2026-05-01", "2026-05-31")

    def test_resolve_mes_a_hoy_range_mid_month_returns_current_month_to_date(self):
        assert _resolve_mes_a_hoy_range(date(2026, 6, 10)) == ("2026-06-01", "2026-06-10")

    def test_resolve_mes_a_hoy_range_january_rolls_back_year(self):
        assert _resolve_mes_a_hoy_range(date(2026, 1, 2)) == ("2025-12-01", "2025-12-31")


class TestServicioPatch:
    def test_patch_hoy_mode_keeps_single_day(self):
        svc = Servicio(nombre="stock-diario", config_path=Path("dummy.json"), fecha_modo="hoy")

        patched = svc.patch(_raw_config(), date(2026, 6, 1))

        assert patched["filtros"] == {
            "fecha_desde": "2026-06-01",
            "fecha_hasta": "2026-06-01",
        }

    def test_patch_mes_a_hoy_uses_previous_month_on_first_business_day(self):
        svc = Servicio(nombre="ventas", config_path=Path("dummy.json"), fecha_modo="mes_a_hoy")

        patched = svc.patch(_raw_config(), date(2026, 6, 1))

        assert patched["filtros"] == {
            "fecha_desde": "2026-05-01",
            "fecha_hasta": "2026-05-31",
        }

    def test_patch_mes_a_hoy_uses_current_month_after_first_business_day(self):
        svc = Servicio(nombre="ventas", config_path=Path("dummy.json"), fecha_modo="mes_a_hoy")

        patched = svc.patch(_raw_config(), date(2026, 6, 10))

        assert patched["filtros"] == {
            "fecha_desde": "2026-06-01",
            "fecha_hasta": "2026-06-10",
        }
