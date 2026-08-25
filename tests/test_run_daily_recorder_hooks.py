"""
Tests for the recorder hooks inside scripts/run_daily.py (RF-01, RF-02, RF-03,
RF-05, RF-06).

This is the file systemd runs at 07:00, so the tests that matter most are not
the ones proving it records well. They are the ones proving that when the
recording is broken, the daily behaves exactly as it did before any of this
existed: same exit code, same services executed, same exception propagation.

Everything outside the hooks is stubbed. These tests never touch the database,
never send anything, and never run a report.
"""
from __future__ import annotations

import functools
import json
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import scripts.run_daily as run_daily
from scripts.daily_recorder import recording_run
from src.api.daily_store import (
    DailyRun,
    DailyRunService,
    engine_from_url,
    init_daily_store,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path):
    eng = engine_from_url(f"sqlite:///{tmp_path}/daily.db")
    init_daily_store(eng)
    return eng


def _servicio(tmp_path, nombre: str, payload: dict | None = None):
    path = tmp_path / f"{nombre}.json"
    path.write_text(
        json.dumps(payload or {"filtros": {}, "reportes": [{"nombre": nombre}]}),
        encoding="utf-8",
    )
    return run_daily.Servicio(nombre=nombre, config_path=path, fecha_modo="hoy")


@pytest.fixture
def daily(monkeypatch, engine, tmp_path):
    """run_daily.main() with the world stubbed out and recording pointed at a temp DB.

    Returns a callable: daily(servicios, overrides=..., argv=..., run=...) -> exit code.
    """
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()

    monkeypatch.setattr(
        run_daily, "recording_run", functools.partial(recording_run, engine=engine)
    )
    monkeypatch.setattr(run_daily, "_refresh_mv_resumen_mensual", lambda: None)
    monkeypatch.setattr(run_daily, "_refresh_mv_stock_quiebre", lambda: None)
    monkeypatch.setattr(run_daily, "CONFIGS_DIR", configs_dir)
    monkeypatch.setattr(run_daily, "CONTACTOS_PATH", tmp_path / "no-contactos.json")
    monkeypatch.setattr(
        run_daily,
        "load_report_config",
        lambda p: SimpleNamespace(validate_contacts=lambda c: None),
    )
    monkeypatch.setattr(run_daily, "load_contacts", lambda p: {})

    def _call(servicios, *, overrides=None, argv=None, run=None):
        monkeypatch.setattr(run_daily, "SERVICIOS", servicios)
        monkeypatch.setattr(run_daily, "_load_overrides", lambda: overrides or {})
        monkeypatch.setattr(
            run_daily, "_run_reportes", run or (lambda cfg, contactos, test_mode=False: 0)
        )
        monkeypatch.setattr(
            "sys.argv", ["run_daily.py", "--date", "2026-08-24", *(argv or [])]
        )
        return run_daily.main()

    return _call


def _runs(engine):
    with Session(engine) as s:
        return list(s.execute(select(DailyRun)).scalars())


def _services(engine):
    with Session(engine) as s:
        return list(
            s.execute(select(DailyRunService).order_by(DailyRunService.orden)).scalars()
        )


# ---------------------------------------------------------------------------
# The isolation contract, at the level that matters (RF-01)
# ---------------------------------------------------------------------------


def test_a_broken_store_does_not_change_the_exit_code(monkeypatch, daily, tmp_path):
    """Instrumentation failing must be invisible to the daily."""
    monkeypatch.setattr(
        run_daily,
        "recording_run",
        functools.partial(
            recording_run,
            engine=engine_from_url(f"sqlite:///{tmp_path}/no-such-dir/x.db"),
        ),
    )

    code = daily([_servicio(tmp_path, "ventas")])

    assert code == 0


def test_a_broken_store_still_runs_every_service(monkeypatch, daily, tmp_path):
    ran = []
    monkeypatch.setattr(
        run_daily,
        "recording_run",
        functools.partial(
            recording_run,
            engine=engine_from_url(f"sqlite:///{tmp_path}/no-such-dir/x.db"),
        ),
    )

    daily(
        [_servicio(tmp_path, "a"), _servicio(tmp_path, "b")],
        run=lambda cfg, contactos, test_mode=False: (ran.append(1), 0)[1],
    )

    assert len(ran) == 2


def test_a_failing_service_still_returns_one(daily, tmp_path, engine):
    """Exit codes are the daily's contract with systemd. They do not move."""
    code = daily(
        [_servicio(tmp_path, "ventas")],
        run=lambda cfg, contactos, test_mode=False: 3,
    )

    assert code == 1
    assert _services(engine)[0].exit_code == 3


def test_a_raising_service_is_caught_exactly_as_before(daily, tmp_path):
    def boom(cfg, contactos, test_mode=False):
        raise ValueError("boom")

    code = daily([_servicio(tmp_path, "a"), _servicio(tmp_path, "b")], run=boom)

    # Both services attempted, run reports failure — unchanged behaviour.
    assert code == 1


# ---------------------------------------------------------------------------
# What gets recorded
# ---------------------------------------------------------------------------


def test_one_run_row_per_invocation(daily, tmp_path, engine):
    daily([_servicio(tmp_path, "ventas")])

    runs = _runs(engine)
    assert len(runs) == 1
    assert runs[0].hoy == "2026-08-24"
    assert runs[0].status == "success"
    assert runs[0].triggered_by == "schedule"


def test_run_meta_captures_the_overrides_that_were_in_force(daily, tmp_path, engine):
    overrides = {"ventas": {"enviar": False, "razon": "sin envío hoy"}}

    daily([_servicio(tmp_path, "ventas")], overrides=overrides)

    assert json.loads(_runs(engine)[0].overrides_snapshot) == overrides


def test_run_meta_captures_which_code_actually_ran(daily, tmp_path, engine):
    daily([_servicio(tmp_path, "ventas")])

    run = _runs(engine)[0]
    assert run.git_branch  # this worktree is on a branch
    assert run.git_sha


def test_each_service_gets_a_row_in_order(daily, tmp_path, engine):
    daily([_servicio(tmp_path, "a"), _servicio(tmp_path, "b")])

    rows = _services(engine)
    assert [r.servicio for r in rows] == ["a", "b"]
    assert all(r.status == "success" for r in rows)


def test_the_patched_date_window_is_captured(daily, tmp_path, engine):
    """It exists nowhere else: the patched config goes to a temp file that the
    finally block deletes."""
    daily([_servicio(tmp_path, "ventas")])

    row = _services(engine)[0]
    assert row.fecha_modo == "hoy"
    assert row.fecha_desde == "2026-08-24"
    assert row.fecha_hasta == "2026-08-24"


def test_delivery_is_recorded_as_its_own_axis(daily, tmp_path, engine):
    daily([_servicio(tmp_path, "ventas")])

    row = _services(engine)[0]
    assert row.status == "success"
    assert row.delivery_status == "sent"


def test_an_override_that_suppresses_delivery_is_not_a_failure(daily, tmp_path, engine):
    daily(
        [_servicio(tmp_path, "ventas")],
        overrides={"ventas": {"enviar": False}},
    )

    row = _services(engine)[0]
    assert row.status == "success"
    assert row.delivery_status == "none_configured"


def test_test_mode_is_recorded_without_the_hook_repeating_it(daily, tmp_path, engine):
    """The run already told recording_run; the hook has no reason to say it again."""
    daily([_servicio(tmp_path, "ventas")], argv=["--test-mode"])

    assert _runs(engine)[0].test_mode is True
    assert _services(engine)[0].delivery_status == "test_redirect"


def test_solo_canal_is_recorded_as_a_partial_delivery(daily, tmp_path, engine):
    daily([_servicio(tmp_path, "ventas")], argv=["--solo-canal", "whatsapp"])

    assert _runs(engine)[0].solo_canal == "whatsapp"
    assert _services(engine)[0].delivery_status == "partial"


# ---------------------------------------------------------------------------
# Skips
# ---------------------------------------------------------------------------


def test_a_service_turned_off_records_why(daily, tmp_path, engine):
    daily(
        [_servicio(tmp_path, "ventas")],
        overrides={"ventas": {"ejecutar": False, "razon": "pedido de Nahuel"}},
    )

    row = _services(engine)[0]
    assert row.status == "skipped"
    assert row.skip_reason == "pedido de Nahuel"


def test_the_day_of_month_gate_records_the_reason_it_computed(daily, tmp_path, engine):
    """`desde_dia_del_mes` builds its reason at runtime; it is in no config file."""
    daily(
        [_servicio(tmp_path, "avance-badie")],
        overrides={"avance-badie": {"desde_dia_del_mes": 28}},
        argv=[],
    )

    row = _services(engine)[0]
    assert row.status == "skipped"
    assert "24" in row.skip_reason and "28" in row.skip_reason


def test_a_skipped_service_never_ran(daily, tmp_path, engine):
    ran = []
    daily(
        [_servicio(tmp_path, "ventas")],
        overrides={"ventas": {"ejecutar": False}},
        run=lambda cfg, contactos, test_mode=False: (ran.append(1), 0)[1],
    )

    assert ran == []


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


def test_an_exception_keeps_the_traceback_that_was_being_thrown_away(
    daily, tmp_path, engine
):
    """Today the except block prints repr(exc) and the traceback is lost.

    That hook is the only place in the system where it still exists.
    """

    def boom(cfg, contactos, test_mode=False):
        raise ValueError("algo se rompio")

    daily([_servicio(tmp_path, "ventas")], run=boom)

    row = _services(engine)[0]
    assert row.status == "exception"
    assert "algo se rompio" in row.error_repr
    assert "ValueError: algo se rompio" in row.error_traceback
    assert "run_daily" in row.error_traceback  # a real stack, not just the message


def test_a_run_with_one_failure_among_successes_closes_partial(daily, tmp_path, engine):
    calls = {"n": 0}

    def flaky(cfg, contactos, test_mode=False):
        calls["n"] += 1
        return 0 if calls["n"] == 1 else 1

    daily([_servicio(tmp_path, "a"), _servicio(tmp_path, "b")], run=flaky)

    assert _runs(engine)[0].status == "partial"


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def test_the_objetivo_gate_is_recorded_as_a_suppressed_delivery(
    monkeypatch, daily, tmp_path, engine
):
    monkeypatch.setattr(run_daily, "_objetivo_gate_bloquea", lambda patched: True)

    daily([_servicio(tmp_path, "avance-badie")])

    row = _services(engine)[0]
    assert row.status == "success"  # the file was still generated
    assert row.delivery_status == "suppressed"
    assert row.delivery_gate == "objetivo_no_cargado"


def test_the_ram_guard_is_recorded_as_a_degraded_delivery(
    monkeypatch, daily, tmp_path, engine
):
    """The guard drops the images and lets the mail go.

    So something went out, but not what the config asked for — the WhatsApp
    group gets nothing. That is 'partial', never 'sent'.
    """
    monkeypatch.setattr(run_daily, "_report_renderiza_imagenes", lambda patched: True)
    monkeypatch.setattr(run_daily, "_mem_available_mb", lambda: 812)
    monkeypatch.setattr(
        run_daily, "_ram_guard_omite_imagenes", lambda patched, avail: True
    )
    monkeypatch.setattr(run_daily, "_alertar_ram_baja", lambda nombre, avail: None)

    daily([_servicio(tmp_path, "avance-badie")])

    row = _services(engine)[0]
    assert row.status == "success"
    assert row.delivery_status == "partial"
    assert row.delivery_gate == "ram_guard_imagenes"
    assert "812" in row.delivery_gate_detail


# ---------------------------------------------------------------------------
# Modes that must not record anything
# ---------------------------------------------------------------------------


def test_a_dry_run_records_nothing(daily, tmp_path, engine):
    """It executes nothing, so there is no run to describe."""
    code = daily([_servicio(tmp_path, "ventas")], argv=["--dry-run"])

    assert code == 0
    assert _runs(engine) == []


def test_an_unknown_service_name_records_nothing(daily, tmp_path, engine):
    code = daily([_servicio(tmp_path, "ventas")], argv=["--only", "no-existe"])

    assert code == 1
    assert _runs(engine) == []


def test_only_narrows_what_is_recorded(daily, tmp_path, engine):
    daily(
        [_servicio(tmp_path, "a"), _servicio(tmp_path, "b")],
        argv=["--only", "a"],
    )

    assert [r.servicio for r in _services(engine)] == ["a"]


# ---------------------------------------------------------------------------
# Wiring: the hooks exist and are the only thing added
# ---------------------------------------------------------------------------


def test_run_daily_imports_the_recorder():
    assert hasattr(run_daily, "recording_run")
    assert hasattr(run_daily, "emit")


def test_the_hooks_carry_no_error_handling_of_their_own():
    """The isolation contract lives in RunRecorder.emit(), in one place.

    A try/except around a call site would be a second, silent place where the
    rule is enforced — and the first one to drift.

    Parsed rather than pattern-matched on text: `service_done` legitimately
    sits inside the pre-existing try/FINALLY that deletes the temp config, and
    a string search cannot tell that apart from a handler that swallows.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(run_daily))

    def emits_in(nodes) -> list[str]:
        found = []
        for node in nodes:
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "emit"
                ):
                    found.append(f"line {inner.lineno}")
        return found

    for node in ast.walk(tree):
        # Only try blocks that actually handle exceptions. A bare try/finally
        # is cleanup, not error handling.
        if isinstance(node, ast.Try) and node.handlers:
            wrapped = emits_in(node.body)
            assert not wrapped, (
                f"emit() is wrapped in a try/except in run_daily.py ({wrapped}); "
                "the contract belongs to RunRecorder.emit()"
            )


def test_the_runs_own_exit_code_is_recorded(daily, tmp_path, engine):
    """It is the number systemd acts on, and it was being computed and dropped."""
    daily([_servicio(tmp_path, "ventas")])

    assert _runs(engine)[0].exit_code == 0


def test_a_failed_run_records_exit_code_one(daily, tmp_path, engine):
    daily(
        [_servicio(tmp_path, "ventas")],
        run=lambda cfg, contactos, test_mode=False: 5,
    )

    run = _runs(engine)[0]
    assert run.exit_code == 1        # what main() returned
    assert _services(engine)[0].exit_code == 5  # what the service returned
