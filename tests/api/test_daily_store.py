"""
Tests for src/api/daily_store.py — daily_runs, daily_run_services, run_artifacts.

TDD: these tests are written BEFORE the implementation (RED first).

Covers the schema contract from sdd/admin-panel-daily/design:
- 3 tables created by init_daily_store(engine), own MetaData (independent of
  src/api/db.py's Base — must never touch/collide with the 'runs' table).
- CheckConstraint on daily_runs.status and daily_runs.triggered_by.
- CheckConstraint on daily_run_services.status.
- Unique index on daily_run_services (run_id, servicio) — natural key that
  backs the upsert-on-emit pattern (E4 in design): re-emitting the same
  service for the same run must UPDATE, never duplicate.
- init_daily_store() is idempotent (CREATE TABLE IF NOT EXISTS semantics).
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.daily_store import (
    DailyRun,
    DailyRunService,
    RunArtifact,
    engine_from_url,
    init_daily_store,
)

RUN_ID = "20260101-070000-daily"


@pytest.fixture
def store_engine(tmp_path):
    """Engine pointing to a tmp SQLite file, with the daily store already initialized."""
    eng = engine_from_url(f"sqlite:///{tmp_path}/test_mgmt.db")
    init_daily_store(eng)
    return eng


def _daily_run(run_id=RUN_ID, status="running", triggered_by="schedule"):
    return DailyRun(
        id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        triggered_by=triggered_by,
        test_mode=False,
        hoy="2026-01-01",
    )


def _service_row(run_id=RUN_ID, orden=1, servicio="ventas", status="success", **extra):
    return DailyRunService(run_id=run_id, orden=orden, servicio=servicio, status=status, **extra)


# ---------------------------------------------------------------------------
# Table / column presence
# ---------------------------------------------------------------------------


def test_init_daily_store_creates_tables_with_required_columns(store_engine):
    """init_daily_store() creates the 3 tables with all design columns, and
    must never create/reference the unrelated 'runs' table from db.py."""
    insp = inspect(store_engine)
    table_names = set(insp.get_table_names())
    assert {"daily_runs", "daily_run_services", "run_artifacts"}.issubset(table_names)
    assert "runs" not in table_names

    daily_runs_cols = {c["name"] for c in insp.get_columns("daily_runs")}
    assert daily_runs_cols.issuperset({
        "id", "started_at", "finished_at", "status", "exit_code",
        "triggered_by", "test_mode", "hoy", "solo_canal",
        "git_branch", "git_sha", "git_dirty", "overrides_snapshot",
        "host_mem_available_mb", "log_path",
    })

    services_cols = {c["name"] for c in insp.get_columns("daily_run_services")}
    assert services_cols.issuperset({
        "id", "run_id", "orden", "servicio", "fecha_modo", "fecha_desde",
        "fecha_hasta", "started_at", "finished_at", "duration_ms", "status",
        "exit_code", "skip_reason", "delivery_status", "delivery_gate",
        "delivery_gate_detail", "error_repr", "error_traceback", "log_path",
    })

    artifacts_cols = {c["name"] for c in insp.get_columns("run_artifacts")}
    assert artifacts_cols.issuperset({
        "id", "service_row_id", "path", "kind", "size_bytes", "mtime", "sent",
    })


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


def test_daily_run_services_unique_index_on_run_id_servicio(store_engine):
    """Natural key (run_id, servicio) has a UNIQUE index (backs upsert-on-emit,
    E4) and rejects a duplicate insert at the DB level — re-emitting a
    service is expected to UPDATE, never INSERT twice."""
    indexes = inspect(store_engine).get_indexes("daily_run_services")
    unique_run_servicio = [
        ix for ix in indexes
        if ix["unique"] and set(ix["column_names"]) == {"run_id", "servicio"}
    ]
    assert unique_run_servicio, f"no unique (run_id, servicio) index found in {indexes!r}"

    with Session(store_engine) as session:
        session.add(_daily_run())
        session.commit()

    with pytest.raises(IntegrityError):
        with Session(store_engine) as session:
            session.add(_service_row())
            session.add(_service_row())
            session.commit()


def test_run_artifacts_has_index_on_service_row_id(store_engine):
    indexes = inspect(store_engine).get_indexes("run_artifacts")
    assert any("service_row_id" in ix["column_names"] for ix in indexes)


def test_run_artifacts_round_trips_a_row(store_engine):
    with Session(store_engine) as session:
        session.add(
            RunArtifact(
                service_row_id=1,
                path="ventas/2026-08/Ventas Walter Vilte - 11-08-2026.xlsx",
                kind="xlsx",
                size_bytes=51234,
                mtime="2026-08-11T07:12:03+00:00",
            )
        )
        session.commit()

    with Session(store_engine) as session:
        artifact = session.query(RunArtifact).one()
        assert artifact.path.endswith(".xlsx")
        assert artifact.kind == "xlsx"
        assert artifact.size_bytes == 51234
        # An artifact is not considered delivered until a send step says so.
        assert artifact.sent is False


# ---------------------------------------------------------------------------
# CheckConstraints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["running", "success", "partial", "error", "interrupted"])
def test_daily_runs_status_accepts_valid_values(store_engine, status):
    with Session(store_engine) as session:
        session.add(_daily_run(run_id=f"{RUN_ID}-{status}", status=status))
        session.commit()


def test_daily_runs_status_rejects_invalid_value(store_engine):
    with pytest.raises(IntegrityError):
        with Session(store_engine) as session:
            session.add(_daily_run(status="bogus"))
            session.commit()


@pytest.mark.parametrize("triggered_by", ["schedule", "manual", "panel"])
def test_daily_runs_triggered_by_accepts_valid_values(store_engine, triggered_by):
    with Session(store_engine) as session:
        session.add(_daily_run(run_id=f"{RUN_ID}-{triggered_by}", triggered_by=triggered_by))
        session.commit()


def test_daily_runs_triggered_by_rejects_invalid_value(store_engine):
    with pytest.raises(IntegrityError):
        with Session(store_engine) as session:
            session.add(_daily_run(triggered_by="bogus"))
            session.commit()


@pytest.mark.parametrize("status", ["skipped", "running", "success", "error", "exception"])
def test_daily_run_services_status_accepts_valid_values(store_engine, status):
    with Session(store_engine) as session:
        session.add(_daily_run())
        session.commit()
    with Session(store_engine) as session:
        session.add(_service_row(servicio=f"svc-{status}", status=status))
        session.commit()


def test_daily_run_services_status_rejects_invalid_value(store_engine):
    with Session(store_engine) as session:
        session.add(_daily_run())
        session.commit()
    with pytest.raises(IntegrityError):
        with Session(store_engine) as session:
            session.add(_service_row(status="bogus"))
            session.commit()


# ---------------------------------------------------------------------------
# Two-axis state model (RF-04): status vs delivery_status/delivery_gate
# ---------------------------------------------------------------------------


def test_daily_run_services_keeps_status_and_delivery_status_independent(store_engine):
    """status (generation outcome) and delivery_status/delivery_gate
    (delivery outcome) are distinct columns — a service can succeed at
    generation but be suppressed/partial/etc. at delivery, or vice versa."""
    with Session(store_engine) as session:
        session.add(_daily_run())
        session.commit()

    with Session(store_engine) as session:
        session.add(_service_row(
            status="success",
            delivery_status="suppressed",
            delivery_gate="objetivo_no_cargado",
        ))
        session.commit()

    with Session(store_engine) as session:
        row = session.query(DailyRunService).filter_by(servicio="ventas").one()
        assert row.status == "success"
        assert row.delivery_status == "suppressed"
        assert row.delivery_gate == "objetivo_no_cargado"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_init_daily_store_is_idempotent(store_engine):
    """Calling init_daily_store() twice on the same engine must not raise
    (CREATE TABLE IF NOT EXISTS semantics, matches init_db() in db.py)."""
    init_daily_store(store_engine)  # must not raise
