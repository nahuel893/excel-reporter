"""
SQLAlchemy 2.x setup for the management UI SQLite database.

DB path: data/mgmt.db (relative to project root)
Table: runs — run history (RF-301)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Index,
    Integer,
    String,
    create_engine,
    desc,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session

logger = logging.getLogger(__name__)

# Default DB path (relative to project root — resolved at runtime)
_DEFAULT_DB_PATH = Path("data/mgmt.db")


class Base(DeclarativeBase):
    pass


class Run(Base):
    """ORM model for the 'runs' table (RF-301)."""

    __tablename__ = "runs"

    id = Column(String, primary_key=True)  # {YYYYMMDD-HHMMSS}-{slug}
    config_file = Column(String, nullable=False)  # e.g. ventas.json
    slug = Column(String, nullable=False)  # report type slug
    started_at = Column(String, nullable=False)  # ISO8601 UTC
    finished_at = Column(String, nullable=True)  # NULL while running
    status = Column(
        String,
        CheckConstraint(
            "status IN ('running','success','error','interrupted')",
            name="ck_runs_status",
        ),
        nullable=False,
    )
    exit_code = Column(Integer, nullable=True)  # NULL while running
    log_path = Column(String, nullable=False)  # data/runs/{run_id}.log
    triggered_by = Column(
        String,
        CheckConstraint(
            "triggered_by IN ('manual','schedule')",
            name="ck_runs_triggered_by",
        ),
        nullable=False,
    )
    test_mode = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_runs_started", desc("started_at")),
        Index("idx_runs_config", "config_file"),
    )


def engine_from_url(url: str):
    """Create a SQLAlchemy engine from a URL string.

    Used in tests to inject a temporary DB path.
    """
    return create_engine(url, connect_args={"check_same_thread": False})


def get_default_engine():
    """Return the default engine pointing to data/mgmt.db.

    Refuses to run while pytest is executing (RF-08): tests must inject
    their own engine= (see engine_from_url()) instead of writing to the
    production data/mgmt.db. This guard exists because previous test runs
    silently polluted the production 'runs' table (139/139 rows were
    pytest artifacts) — see sdd/admin-panel-daily.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError(
            "get_default_engine() was called while running under pytest "
            "(PYTEST_CURRENT_TEST is set). Tests must inject their own "
            "engine= via engine_from_url(f\"sqlite:///{tmp_path}/test.db\") "
            "instead of writing to the production data/mgmt.db."
        )
    db_path = _DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return engine_from_url(f"sqlite:///{db_path}")


def init_db(engine=None) -> None:
    """Create all tables (CREATE TABLE IF NOT EXISTS semantics)."""
    if engine is None:
        engine = get_default_engine()
    Base.metadata.create_all(engine)
    logger.debug("DB initialized at %s", engine.url)


def recover_interrupted_runs(engine=None) -> int:
    """On startup: mark all status='running' rows as 'interrupted'.

    Returns the number of rows updated.
    """
    if engine is None:
        engine = get_default_engine()

    with Session(engine) as session:
        result = session.execute(
            text(
                "UPDATE runs SET status = 'interrupted' WHERE status = 'running'"
            )
        )
        session.commit()
        count = result.rowcount

    if count:
        logger.warning(
            "Startup recovery: %d run(s) marked as 'interrupted'", count
        )
    return count
