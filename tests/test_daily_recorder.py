"""
Tests for scripts/daily_recorder.py — the instrumentation the daily flow writes
its history into.

The whole point of this module is that it must never be the reason a report
fails to run. So the tests that matter most are not the ones proving it records
correctly; they are the ones proving it stays quiet when it cannot. A broken
database, a missing column, a field nobody defined: none of those may reach the
caller.

Every test injects engine= explicitly. A test that forgot to would silently get
a NullRecorder and pass while recording nothing, so each assertion reads real
rows back — a no-op recorder fails them.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts.daily_recorder import (
    NullRecorder,
    RunRecorder,
    emit,
    recording_run,
)
from src.api.daily_store import (
    DailyRun,
    DailyRunService,
    engine_from_url,
    init_daily_store,
)


@pytest.fixture
def engine(tmp_path):
    """A real, working store in a temp file."""
    eng = engine_from_url(f"sqlite:///{tmp_path}/daily.db")
    init_daily_store(eng)
    return eng


@pytest.fixture
def broken_engine(tmp_path):
    """An engine that resolves but can never connect.

    The directory does not exist, so SQLite fails at connect time rather than
    at create_engine time — which is exactly how a real failure would arrive:
    late, inside emit(), long after the daily started running.
    """
    return engine_from_url(f"sqlite:///{tmp_path}/no-such-dir/daily.db")


def _runs(engine) -> list[DailyRun]:
    with Session(engine) as s:
        return list(s.execute(select(DailyRun)).scalars())


def _services(engine, run_id: str) -> list[DailyRunService]:
    with Session(engine) as s:
        return list(
            s.execute(
                select(DailyRunService)
                .where(DailyRunService.run_id == run_id)
                .order_by(DailyRunService.orden)
            ).scalars()
        )


# ---------------------------------------------------------------------------
# The isolation contract (RF-01): instrumentation never breaks the daily
# ---------------------------------------------------------------------------


def test_emit_never_raises_when_the_store_is_broken(broken_engine):
    """A dead database must not turn into a failed report."""
    calls = []

    with recording_run(hoy="2026-08-24", test_mode=False, engine=broken_engine):
        for i in range(5):
            emit("service_start", service=f"svc-{i}")
            emit("gate", service=f"svc-{i}", delivery_gate="objetivo_no_cargado")
            emit("service_done", service=f"svc-{i}", exit_code=0, enviar=True)
            calls.append(i)

    assert calls == [0, 1, 2, 3, 4]


def test_a_broken_store_yields_a_null_recorder(broken_engine):
    """Opening against a dead store degrades to a no-op, it does not raise."""
    with recording_run(hoy="2026-08-24", test_mode=False, engine=broken_engine) as rec:
        assert isinstance(rec, NullRecorder)


def test_module_emit_outside_a_run_is_a_no_op():
    """run_daily.py calls emit() unconditionally; outside a run it must be inert."""
    emit("service_start", service="ventas")  # must not raise


def test_an_unknown_field_is_ignored_rather_than_raising(engine):
    """A typo in a hook name must not take the daily down with it."""
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_done", service="ventas", exit_code=0, enviar=True, no_such_field=1)

    rows = _services(engine, rec.run_id)
    assert len(rows) == 1
    assert rows[0].status == "success"


def test_an_exception_inside_the_run_is_re_raised_and_the_run_closes_as_error(engine):
    """The recorder observes the failure; it never swallows it.

    A daily that blew up must still blow up. The only difference is that now
    there is a row saying so.
    """
    with pytest.raises(ValueError, match="boom"):
        with recording_run(hoy="2026-08-24", test_mode=False, engine=engine):
            emit("service_start", service="ventas")
            raise ValueError("boom")

    runs = _runs(engine)
    assert len(runs) == 1
    assert runs[0].status == "error"
    assert runs[0].finished_at is not None


# ---------------------------------------------------------------------------
# The run row
# ---------------------------------------------------------------------------


def test_the_run_row_exists_and_is_running_while_inside(engine):
    with recording_run(hoy="2026-08-24", test_mode=True, solo_canal="whatsapp", engine=engine) as rec:
        inside = _runs(engine)
        assert len(inside) == 1
        assert inside[0].status == "running"
        assert inside[0].finished_at is None
        assert inside[0].id == rec.run_id

    after = _runs(engine)
    assert after[0].hoy == "2026-08-24"
    assert after[0].test_mode is True
    assert after[0].solo_canal == "whatsapp"
    assert after[0].triggered_by == "schedule"


def test_run_id_ends_in_daily_and_carries_a_timestamp(engine):
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        pass
    assert rec.run_id.endswith("-daily")
    stamp = rec.run_id[: -len("-daily")]
    datetime.strptime(stamp, "%Y%m%d-%H%M%S")  # raises if the shape drifted


def test_run_meta_stores_the_overrides_snapshot_as_json(engine):
    overrides = {"ventas": {"ejecutar": False, "razon": "pedido de Nahuel"}}

    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("run_meta", overrides=overrides)

    row = _runs(engine)[0]
    assert json.loads(row.overrides_snapshot) == overrides
    assert row.id == rec.run_id


def test_run_meta_captures_git_state_with_an_explicit_repo_path(engine, monkeypatch):
    """git is invoked with -C <root>, never trusting the process cwd.

    systemd runs the daily from a working directory this code does not choose.
    Reading whatever repository happens to be under cwd would record the state
    of the wrong tree.
    """
    seen: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = "main\n"
        stderr = ""

    def fake_run(argv, **kwargs):
        seen.append(argv)
        assert kwargs.get("shell") is not True
        return _Proc()

    monkeypatch.setattr("scripts.daily_recorder.subprocess.run", fake_run)

    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine):
        emit("run_meta", overrides={})

    assert seen, "git was never invoked"
    for argv in seen:
        assert argv[0] == "git"
        assert "-C" in argv
        root = argv[argv.index("-C") + 1]
        assert root.startswith("/"), f"repo path must be absolute, got {root!r}"


def test_git_failure_leaves_the_columns_null_instead_of_failing(engine, monkeypatch):
    def fake_run(argv, **kwargs):
        raise OSError("git is not installed")

    monkeypatch.setattr("scripts.daily_recorder.subprocess.run", fake_run)

    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine):
        emit("run_meta", overrides={})

    row = _runs(engine)[0]
    assert row.git_branch is None
    assert row.git_sha is None


# ---------------------------------------------------------------------------
# Service rows — upsert on the natural key (E4)
# ---------------------------------------------------------------------------


def test_repeated_emits_for_one_service_update_a_single_row(engine):
    """(run_id, servicio) is the natural key: four events, one row."""
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_start", service="ventas", fecha_modo="mes_a_hoy")
        emit("gate", service="ventas", delivery_gate="ram_guard_whatsapp")
        emit("service_done", service="ventas", exit_code=0, enviar=False)

    rows = _services(engine, rec.run_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.fecha_modo == "mes_a_hoy"          # from service_start
    assert row.delivery_gate == "ram_guard_whatsapp"  # from gate
    assert row.status == "success"                 # from service_done


def test_orden_follows_first_appearance(engine):
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_start", service="ventas")
        emit("service_start", service="avance-badie")
        emit("service_done", service="ventas", exit_code=0, enviar=True)
        emit("service_start", service="rechazos")

    rows = _services(engine, rec.run_id)
    assert [r.servicio for r in rows] == ["ventas", "avance-badie", "rechazos"]
    assert [r.orden for r in rows] == [1, 2, 3]


def test_service_start_records_the_patched_date_window(engine):
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit(
            "service_start",
            service="ventas",
            fecha_modo="mes_a_hoy",
            fecha_desde="2026-08-01",
            fecha_hasta="2026-08-24",
        )

    row = _services(engine, rec.run_id)[0]
    assert row.status == "running"
    assert row.started_at is not None
    assert (row.fecha_desde, row.fecha_hasta) == ("2026-08-01", "2026-08-24")


def test_a_non_zero_exit_code_is_an_error_not_a_success(engine):
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_start", service="ventas")
        emit("service_done", service="ventas", exit_code=1, enviar=True)

    row = _services(engine, rec.run_id)[0]
    assert row.status == "error"
    assert row.exit_code == 1


def test_done_without_an_exit_code_is_not_called_a_success(engine):
    """A result we could not read is not a result.

    The service status enum has no "unknown", so the row stays 'running' —
    which is literally what happened: it started and never reported back. The
    run then closes 'partial'/'interrupted' and someone goes looking, which is
    the point. Calling it success would bury it.
    """
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_start", service="ventas")
        emit("service_done", service="ventas", exit_code=None, enviar=True)

    row = _services(engine, rec.run_id)[0]
    assert row.status == "running"
    assert row.exit_code is None
    assert row.delivery_status == "sent"  # delivery is a separate axis and it did go out


def test_service_exception_keeps_the_traceback(engine):
    """The traceback exists exactly once, at the except site, and is dropped today."""
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_start", service="ventas")
        emit(
            "service_exception",
            service="ventas",
            error_repr="ValueError('boom')",
            error_traceback="Traceback (most recent call last):\n  ...\nValueError: boom",
        )

    row = _services(engine, rec.run_id)[0]
    assert row.status == "exception"
    assert row.error_repr == "ValueError('boom')"
    assert "ValueError: boom" in row.error_traceback
    assert row.finished_at is not None


def test_an_exception_leaves_the_delivery_axis_unknown_rather_than_guessing(engine):
    """A crash can land on either side of the send.

    The except hook knows nothing about whether anything went out, so
    delivery_status stays NULL — "we never got that far" — while any gate that
    already fired is still on the row.
    """
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_start", service="ventas")
        emit("gate", service="ventas", delivery_gate="ram_guard_whatsapp")
        emit("service_exception", service="ventas", error_repr="RuntimeError()")

    row = _services(engine, rec.run_id)[0]
    assert row.status == "exception"
    assert row.delivery_status is None
    assert row.delivery_gate == "ram_guard_whatsapp"


def test_duration_is_measured_between_start_and_done(engine):
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_start", service="ventas")
        emit("service_done", service="ventas", exit_code=0, enviar=True)

    row = _services(engine, rec.run_id)[0]
    assert row.duration_ms is not None
    assert row.duration_ms >= 0


def test_done_without_start_still_records_the_outcome(engine):
    """Never lose the result because the opening hook did not fire."""
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_done", service="ventas", exit_code=0, enviar=True)

    rows = _services(engine, rec.run_id)
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].duration_ms is None  # unknown, not zero


# ---------------------------------------------------------------------------
# delivery_status derivation (RF-04) — the second axis, never merged into status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gate,fields,expected",
    [
        # test_mode wins over everything: nothing reached a real recipient.
        (None, {"test_mode": True, "enviar": True}, "test_redirect"),
        (None, {"test_mode": True, "enviar": False}, "test_redirect"),
        # Not delivered, and a gate said why.
        ("ram_guard_whatsapp", {"enviar": False}, "suppressed"),
        ("objetivo_no_cargado", {"enviar": False}, "suppressed"),
        # Not delivered, and nothing blocked it — the config simply has no channel.
        (None, {"enviar": False}, "none_configured"),
        # Delivered, but only down one of the configured channels.
        (None, {"enviar": True, "solo_canal": "whatsapp"}, "partial"),
        # Delivered as configured.
        (None, {"enviar": True}, "sent"),
    ],
)
def test_delivery_status_derivation(engine, gate, fields, expected):
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_start", service="ventas")
        if gate:
            emit("gate", service="ventas", delivery_gate=gate)
        emit("service_done", service="ventas", exit_code=0, **fields)

    row = _services(engine, rec.run_id)[0]
    assert row.delivery_status == expected


def test_a_test_mode_run_never_records_a_real_delivery(engine):
    """The run knows it is in test mode; the hook does not have to say so.

    This is the case the parametrized table above cannot catch, because it
    injects test_mode through emit(). A real hook has no reason to repeat what
    it already handed to recording_run() — and when it did not, every service
    in a test run was recorded as 'sent' while nothing left the building.
    """
    with recording_run(hoy="2026-08-24", test_mode=True, engine=engine) as rec:
        emit("service_start", service="ventas")
        emit("service_done", service="ventas", exit_code=0, enviar=True)

    assert _services(engine, rec.run_id)[0].delivery_status == "test_redirect"


def test_a_single_channel_run_records_partial_delivery(engine):
    """--solo-canal is run-level too, and the hook does not repeat it either."""
    with recording_run(
        hoy="2026-08-24", test_mode=False, solo_canal="whatsapp", engine=engine
    ) as rec:
        emit("service_start", service="ventas")
        emit("service_done", service="ventas", exit_code=0, enviar=True)

    assert _services(engine, rec.run_id)[0].delivery_status == "partial"


def test_a_blocked_delivery_is_not_a_failed_generation(engine):
    """The two axes stay independent: the file was built, it just never went out."""
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        emit("service_start", service="avance-badie")
        emit(
            "gate",
            service="avance-badie",
            delivery_gate="ram_guard_whatsapp",
            delivery_gate_detail="MemAvailable=812MB, umbral 3000",
        )
        emit("service_done", service="avance-badie", exit_code=0, enviar=False)

    row = _services(engine, rec.run_id)[0]
    assert row.status == "success"
    assert row.delivery_status == "suppressed"
    assert row.delivery_gate == "ram_guard_whatsapp"
    assert "812MB" in row.delivery_gate_detail


# ---------------------------------------------------------------------------
# Closing status, aggregated from the children (E6)
# ---------------------------------------------------------------------------


def _close_with(engine, outcomes: list[tuple[str, int]]) -> str:
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        for name, code in outcomes:
            emit("service_start", service=name)
            emit("service_done", service=name, exit_code=code, enviar=True)
    return _runs(engine)[0].status


def test_every_service_ok_closes_success(engine):
    assert _close_with(engine, [("a", 0), ("b", 0)]) == "success"


def test_a_mix_closes_partial(engine):
    assert _close_with(engine, [("a", 0), ("b", 1)]) == "partial"


def test_every_service_failing_closes_error(engine):
    assert _close_with(engine, [("a", 1), ("b", 2)]) == "error"


def test_a_run_with_no_services_closes_success(engine):
    """Every service skipped is a run that succeeded at doing nothing."""
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine):
        pass
    assert _runs(engine)[0].status == "success"


def test_a_service_that_never_reported_back_does_not_read_as_success(engine):
    """A row still 'running' at close means we never learned the outcome.

    Counting it as success is the one lie this whole feature exists to avoid.
    """
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine):
        emit("service_start", service="a")
        emit("service_start", service="b")
        emit("service_done", service="b", exit_code=0, enviar=True)

    assert _runs(engine)[0].status == "partial"


def test_a_run_where_nothing_reported_back_closes_interrupted(engine):
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine):
        emit("service_start", service="a")

    assert _runs(engine)[0].status == "interrupted"


def test_closing_status_respects_the_check_constraint(engine):
    """Whatever we compute has to be a value the schema actually allows.

    The allowed set is parsed out of the CHECK clause rather than substring
    matched against the whole CREATE TABLE: 'run' is a substring of that text
    and would sail through a containment check while being no valid status
    at all.
    """
    _close_with(engine, [("a", 0), ("b", 1)])

    raw = sqlite3.connect(str(engine.url).replace("sqlite:///", ""))
    try:
        ddl = raw.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'daily_runs'"
        ).fetchone()[0]
    finally:
        raw.close()

    clause = re.search(r"status IN \(([^)]+)\)", ddl)
    assert clause, f"no status CHECK constraint found in:\n{ddl}"
    allowed = set(re.findall(r"'([^']+)'", clause.group(1)))
    assert allowed  # a constraint we could not parse proves nothing

    assert _runs(engine)[0].status in allowed


# ---------------------------------------------------------------------------
# Host metadata
# ---------------------------------------------------------------------------


def test_available_memory_is_recorded_when_meminfo_is_readable(engine, monkeypatch):
    monkeypatch.setattr("scripts.daily_recorder._mem_available_mb", lambda: 2048)

    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine):
        emit("run_meta", overrides={})

    assert _runs(engine)[0].host_mem_available_mb == 2048


def test_unreadable_meminfo_leaves_the_column_null(engine, monkeypatch):
    monkeypatch.setattr("scripts.daily_recorder._mem_available_mb", lambda: None)

    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine):
        emit("run_meta", overrides={})

    assert _runs(engine)[0].host_mem_available_mb is None


# ---------------------------------------------------------------------------
# triggered_by
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("triggered_by", ["schedule", "manual", "panel"])
def test_triggered_by_accepts_every_allowed_source(engine, triggered_by):
    with recording_run(
        hoy="2026-08-24", test_mode=False, triggered_by=triggered_by, engine=engine
    ):
        pass
    assert _runs(engine)[0].triggered_by == triggered_by


def test_recorder_is_a_run_recorder_when_the_store_works(engine):
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine) as rec:
        assert isinstance(rec, RunRecorder)
        assert not isinstance(rec, NullRecorder)


def test_started_at_is_utc_and_iso(engine):
    with recording_run(hoy="2026-08-24", test_mode=False, engine=engine):
        pass
    parsed = datetime.fromisoformat(_runs(engine)[0].started_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)
