import json
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


class TestAvanceGuemesRegistration:
    """avance-guemes must be registered in the daily but stay DORMANT
    (ejecutar=false) until the base template + build verification ship (PR4).
    run_daily defaults ejecutar=True for unlisted services, so the override
    entry is what prevents a template-less production run."""

    def test_avance_guemes_in_servicios(self):
        svc = next((s for s in run_daily.SERVICIOS if s.nombre == "avance-guemes"), None)
        assert svc is not None, "avance-guemes not registered in SERVICIOS"
        assert svc.config_path == run_daily.CONFIGS_DIR / "avances_guemes.json"
        assert svc.fecha_modo == "mes_a_hoy"

    def test_avance_guemes_override_active(self):
        """Now activated: the template shipped and the objetivo gate (not a manual
        pause) controls whether a send actually goes out."""
        overrides = json.loads(run_daily.OVERRIDES_PATH.read_text(encoding="utf-8"))
        assert "avance-guemes" in overrides, "avance-guemes missing from daily_overrides.json"
        assert overrides["avance-guemes"]["ejecutar"] is True
        assert overrides["avance-guemes"]["enviar"] is True

    def test_avances_guemes_config_parses_as_guemes(self):
        from src.config.resolver import load_report_config, merge_filters

        cfg = load_report_config(run_daily.CONFIGS_DIR / "avances_guemes.json")
        assert cfg.tipo == "avances"
        merged = merge_filters(cfg.filtros, cfg.reportes[0].filtros)
        assert merged["tipo_plantilla"] == "guemes"
        assert merged["id_sucursal"] == 16

    def test_avances_guemes_config_has_gate_and_recipients(self):
        from src.config.resolver import load_report_config

        cfg = load_report_config(run_daily.CONFIGS_DIR / "avances_guemes.json")
        assert cfg.filtros.esperar_objetivo is True
        enviar_a = cfg.reportes[0].enviar_a or {}
        assert set(enviar_a) == {"Gonzalo Farah", "Sebastian Dellamea", "Nahuel Aguirre"}


class TestObjetivoGate:
    """The objetivo gate holds delivery until the month's cupos are loaded."""

    def _patched(self, **filtros):
        base = {"fecha_desde": "2026-08-01", "id_sucursal": 16}
        base.update(filtros)
        return {"filtros": base}

    def test_no_gate_when_flag_absent(self):
        # No esperar_objetivo -> never blocks, no DB call needed.
        assert run_daily._objetivo_gate_bloquea(self._patched()) is False

    def test_blocks_when_flag_set_and_cupos_missing(self, monkeypatch):
        monkeypatch.setattr(run_daily, "_objetivo_cargado", lambda per, suc: False)
        assert run_daily._objetivo_gate_bloquea(self._patched(esperar_objetivo=True)) is True

    def test_passes_when_flag_set_and_cupos_loaded(self, monkeypatch):
        monkeypatch.setattr(run_daily, "_objetivo_cargado", lambda per, suc: True)
        assert run_daily._objetivo_gate_bloquea(self._patched(esperar_objetivo=True)) is False

    def test_checks_period_from_fecha_desde_not_today(self, monkeypatch):
        """The cierre (previous month) must be gated on the previous month's
        cupos — the period comes from the report's own fecha_desde."""
        seen = {}

        def fake(periodo, id_sucursal):
            seen["periodo"], seen["id_sucursal"] = periodo, id_sucursal
            return True

        monkeypatch.setattr(run_daily, "_objetivo_cargado", fake)
        run_daily._objetivo_gate_bloquea(
            self._patched(fecha_desde="2026-06-01", esperar_objetivo=True)
        )
        assert seen == {"periodo": "2026-06", "id_sucursal": 16}

    def test_fail_closed_when_id_sucursal_missing(self):
        """Gate opted in but no id_sucursal to check -> hold the send (fail-closed)."""
        patched = {"filtros": {"fecha_desde": "2026-08-01", "esperar_objetivo": True}}
        assert run_daily._objetivo_gate_bloquea(patched) is True

    def test_fail_closed_when_id_sucursal_not_numeric(self, monkeypatch):
        # Even if it reached the DB, a non-numeric sucursal must not send ungated.
        monkeypatch.setattr(run_daily, "_objetivo_cargado", lambda per, suc: True)
        patched = self._patched(id_sucursal="CASA CENTRAL", esperar_objetivo=True)
        assert run_daily._objetivo_gate_bloquea(patched) is True

    def test_ejecutar_servicio_blocked_gate_strips_delivery_but_still_runs(self, tmp_path, monkeypatch):
        """Wiring: a blocked gate empties enviar_a (no send) yet the report still runs."""
        monkeypatch.setattr(run_daily, "_objetivo_cargado", lambda per, suc: False)
        monkeypatch.setattr(run_daily, "load_contacts", lambda p: {})
        captured = {}

        def fake_run_reportes(report_config, contactos, test_mode=False):
            captured["reportes"] = report_config.reportes
            return 0

        monkeypatch.setattr(run_daily, "_run_reportes", fake_run_reportes)

        cfg = {
            "tipo": "avances",
            "filtros": {
                "tipo_plantilla": "guemes", "fecha_desde": "2026-08-01",
                "fecha_hasta": "2026-08-31", "id_sucursal": 16, "id_fuerza_ventas": 1,
                "enviar_email": True, "esperar_objetivo": True,
            },
            "reportes": [{
                "nombre": "AVANCE GUEMES - TEST",
                "enviar_a": {"Nahuel Aguirre": {"via": ["email"]}},
            }],
        }
        cfg_path = tmp_path / "guemes_test.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        svc = Servicio(nombre="avance-guemes", config_path=cfg_path, fecha_modo="mes_a_hoy")

        rc = run_daily._ejecutar_servicio(svc, date(2026, 8, 15), enviar=True)

        assert rc == 0
        assert "reportes" in captured, "_run_reportes must still run (report is generated)"
        assert all(not (r.enviar_a or {}) for r in captured["reportes"]), "delivery must be stripped"
