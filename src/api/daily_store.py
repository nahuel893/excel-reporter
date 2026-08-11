"""
SQLAlchemy 2.x setup for the daily-run instrumentation tables.

DB path: data/mgmt.db (relative to project root — same file as src/api/db.py,
but a SEPARATE MetaData/declarative base, so create_all() here never touches
or collides with the 'runs' table owned by db.py).

Tables: daily_runs, daily_run_services, run_artifacts (RF-02, RF-03, RF-04,
RF-05, RF-06 — see sdd/admin-panel-daily/design).

Two-axis state model (RF-04, non-negotiable): 'status' records what happened
to GENERATION (running/success/error/...); 'delivery_status' + 'delivery_gate'
record what happened to DELIVERY and which gate blocked it. These must never
be collapsed into a single column.
"""
from __future__ import annotations

import logging

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Index,
    Integer,
    String,
    create_engine,
    desc,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class DailyStoreBase(DeclarativeBase):
    """Own declarative base / MetaData — independent of src/api/db.py's Base."""

    pass


class DailyRun(DailyStoreBase):
    """ORM model for the 'daily_runs' table — one row per run_daily.py invocation."""

    __tablename__ = "daily_runs"

    id = Column(String, primary_key=True)  # {YYYYMMDD-HHMMSS}-daily
    started_at = Column(String, nullable=False)  # ISO8601 UTC
    finished_at = Column(String, nullable=True)  # NULL while running
    status = Column(
        String,
        CheckConstraint(
            "status IN ('running','success','partial','error','interrupted')",
            name="ck_daily_runs_status",
        ),
        nullable=False,
    )
    exit_code = Column(Integer, nullable=True)
    triggered_by = Column(
        String,
        CheckConstraint(
            "triggered_by IN ('schedule','manual','panel')",
            name="ck_daily_runs_triggered_by",
        ),
        nullable=False,
    )
    test_mode = Column(Boolean, nullable=False, default=False)
    hoy = Column(String, nullable=False)  # effective run date (YYYY-MM-DD)
    solo_canal = Column(String, nullable=True)
    git_branch = Column(String, nullable=True)
    git_sha = Column(String, nullable=True)
    git_dirty = Column(Boolean, nullable=True)
    overrides_snapshot = Column(String, nullable=True)  # JSON — used to reconstruct skips
    host_mem_available_mb = Column(Integer, nullable=True)
    log_path = Column(String, nullable=True)

    __table_args__ = (
        Index("idx_daily_runs_started", desc("started_at")),
    )


class DailyRunService(DailyStoreBase):
    """ORM model for 'daily_run_services' — one row per service in a daily run.

    Natural key (run_id, servicio) is unique: re-emitting the same service
    within the same run UPDATEs the existing row instead of duplicating it
    (upsert-on-emit pattern, design decision E4).
    """

    __tablename__ = "daily_run_services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False)  # logical FK -> daily_runs.id
    orden = Column(Integer, nullable=False)
    servicio = Column(String, nullable=False)
    fecha_modo = Column(String, nullable=True)
    fecha_desde = Column(String, nullable=True)
    fecha_hasta = Column(String, nullable=True)
    started_at = Column(String, nullable=True)
    finished_at = Column(String, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    status = Column(
        String,
        CheckConstraint(
            "status IN ('skipped','running','success','error','exception')",
            name="ck_daily_run_services_status",
        ),
        nullable=False,
    )
    exit_code = Column(Integer, nullable=True)
    skip_reason = Column(String, nullable=True)
    # Delivery axis — independent from 'status' (RF-04). Never collapse these.
    delivery_status = Column(String, nullable=True)
    delivery_gate = Column(String, nullable=True)
    delivery_gate_detail = Column(String, nullable=True)
    error_repr = Column(String, nullable=True)
    error_traceback = Column(String, nullable=True)
    log_path = Column(String, nullable=True)

    __table_args__ = (
        Index("idx_drs_run_id", "run_id"),
        Index("idx_drs_run_servicio", "run_id", "servicio", unique=True),
    )


class RunArtifact(DailyStoreBase):
    """ORM model for 'run_artifacts' — one row per generated file."""

    __tablename__ = "run_artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_row_id = Column(Integer, nullable=False)  # logical FK -> daily_run_services.id
    path = Column(String, nullable=False)  # relative to data/output/
    kind = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    mtime = Column(String, nullable=True)
    sent = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_run_artifacts_service", "service_row_id"),
    )


def engine_from_url(url: str):
    """Create a SQLAlchemy engine from a URL string.

    Used in tests to inject a temporary DB path (mirrors src/api/db.py).
    """
    return create_engine(url, connect_args={"check_same_thread": False})


def init_daily_store(engine) -> None:
    """Create the 3 daily-store tables (CREATE TABLE IF NOT EXISTS semantics).

    Idempotent: calling this twice on the same engine must not raise.
    """
    DailyStoreBase.metadata.create_all(engine)
    logger.debug("Daily store initialized at %s", engine.url)
