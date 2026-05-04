"""
Tests for src/api/db.py — SQLAlchemy setup, Run model, init_db, recover_interrupted_runs.

TDD: these tests are written BEFORE the implementation.
"""
import pytest
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session


@pytest.fixture
def tmp_db(tmp_path):
    """In-memory SQLite DB URL for isolation."""
    return f"sqlite:///{tmp_path}/test_mgmt.db"


def test_init_db_creates_runs_table(tmp_db):
    """init_db() must create the 'runs' table."""
    from src.api.db import init_db, engine_from_url

    eng = engine_from_url(tmp_db)
    init_db(engine=eng)

    insp = inspect(eng)
    assert "runs" in insp.get_table_names()


def test_runs_table_has_required_columns(tmp_db):
    """runs table must have all RF-301 columns."""
    from src.api.db import init_db, engine_from_url

    eng = engine_from_url(tmp_db)
    init_db(engine=eng)

    insp = inspect(eng)
    columns = {c["name"] for c in insp.get_columns("runs")}
    expected = {
        "id", "config_file", "slug", "started_at", "finished_at",
        "status", "exit_code", "log_path", "triggered_by", "test_mode",
    }
    assert expected.issubset(columns)


def test_status_check_constraint_accepts_valid_values(tmp_db):
    """status CHECK allows running|success|error|interrupted (NOT 'failed')."""
    from src.api.db import init_db, engine_from_url, Run
    from datetime import datetime, timezone

    eng = engine_from_url(tmp_db)
    init_db(engine=eng)

    with Session(eng) as session:
        for status in ("running", "success", "error", "interrupted"):
            run = Run(
                id=f"20260101-120000-test-{status}",
                config_file="ventas.json",
                slug="ventas",
                started_at=datetime.now(timezone.utc).isoformat(),
                status=status,
                log_path=f"data/runs/test-{status}.log",
                triggered_by="manual",
                test_mode=False,
            )
            session.add(run)
        session.commit()


def test_status_check_rejects_failed(tmp_db):
    """'failed' is not a valid status — must raise or be caught."""
    from src.api.db import init_db, engine_from_url, Run
    from datetime import datetime, timezone
    from sqlalchemy.exc import IntegrityError

    eng = engine_from_url(tmp_db)
    init_db(engine=eng)

    with pytest.raises((IntegrityError, ValueError)):
        with Session(eng) as session:
            run = Run(
                id="20260101-120000-test-failed",
                config_file="ventas.json",
                slug="ventas",
                started_at=datetime.now(timezone.utc).isoformat(),
                status="failed",  # invalid
                log_path="data/runs/test-failed.log",
                triggered_by="manual",
                test_mode=False,
            )
            session.add(run)
            session.commit()


def test_recover_interrupted_runs(tmp_db):
    """recover_interrupted_runs() updates all status='running' rows to 'interrupted'."""
    from src.api.db import init_db, engine_from_url, Run, recover_interrupted_runs
    from datetime import datetime, timezone

    eng = engine_from_url(tmp_db)
    init_db(engine=eng)

    with Session(eng) as session:
        for i in range(3):
            run = Run(
                id=f"20260101-12000{i}-test",
                config_file="ventas.json",
                slug="ventas",
                started_at=datetime.now(timezone.utc).isoformat(),
                status="running",
                log_path=f"data/runs/test-{i}.log",
                triggered_by="manual",
                test_mode=False,
            )
            session.add(run)
        # One already successful run (must NOT change)
        session.add(Run(
            id="20260101-120099-success",
            config_file="ventas.json",
            slug="ventas",
            started_at=datetime.now(timezone.utc).isoformat(),
            status="success",
            log_path="data/runs/success.log",
            triggered_by="manual",
            test_mode=False,
        ))
        session.commit()

    recover_interrupted_runs(engine=eng)

    with Session(eng) as session:
        rows = session.execute(text("SELECT id, status FROM runs")).fetchall()
        by_id = {r[0]: r[1] for r in rows}

    # All running→interrupted
    for i in range(3):
        assert by_id[f"20260101-12000{i}-test"] == "interrupted"
    # Success row unchanged
    assert by_id["20260101-120099-success"] == "success"


def test_recover_interrupted_runs_no_running_rows(tmp_db):
    """recover_interrupted_runs() must not crash when there are no running rows."""
    from src.api.db import init_db, engine_from_url, recover_interrupted_runs

    eng = engine_from_url(tmp_db)
    init_db(engine=eng)
    # Should not raise
    recover_interrupted_runs(engine=eng)
