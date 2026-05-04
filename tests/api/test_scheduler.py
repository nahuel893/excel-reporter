"""
Tests for T-109: APScheduler + log rotation (keep last 200 runs).

TDD: written BEFORE implementation.
"""
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path


@pytest.fixture
def tmp_db_engine(tmp_path):
    from src.api.db import init_db, engine_from_url
    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = engine_from_url(db_url)
    init_db(engine=engine)
    return engine, tmp_path


def _insert_runs(engine, runs_dir, count, start_offset_hours=0):
    """Insert 'count' dummy runs into DB and create fake .log files."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    inserted = []
    with Session(engine) as session:
        for i in range(count):
            run_id = f"2026010{i//10:01d}-{i:06d}-ventas"
            # Use unique timestamps
            started_at = (
                datetime(2026, 1, 1, tzinfo=timezone.utc)
                + timedelta(hours=start_offset_hours + i)
            ).isoformat()
            log_file = runs_dir / f"{run_id}.log"
            log_file.write_text(f"log for {run_id}")
            session.execute(
                text("""
                    INSERT INTO runs (id, config_file, slug, started_at, status, log_path, triggered_by, test_mode)
                    VALUES (:id, 'ventas.json', 'ventas', :started_at, 'success', :log_path, 'manual', 0)
                """),
                {"id": run_id, "started_at": started_at, "log_path": str(log_file)},
            )
            inserted.append((run_id, log_file))
        session.commit()
    return inserted


def test_rotation_keeps_last_200(tmp_db_engine, tmp_path):
    """After inserting 201 runs, DB has exactly 200 rows and oldest log is deleted."""
    from src.api.scheduler import prune_old_runs

    engine, _ = tmp_db_engine
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    inserted = _insert_runs(engine, runs_dir, 201)
    oldest_run_id, oldest_log = inserted[0]

    prune_old_runs(engine=engine, max_runs=200)

    from sqlalchemy import text
    from sqlalchemy.orm import Session
    with Session(engine) as session:
        count = session.execute(text("SELECT COUNT(*) FROM runs")).fetchone()[0]

    assert count == 200, f"Expected 200 rows, got {count}"
    assert not oldest_log.exists(), f"Oldest log should be deleted: {oldest_log}"


def test_rotation_no_op_when_under_limit(tmp_db_engine, tmp_path):
    """prune_old_runs() is a no-op when count <= max_runs."""
    from src.api.scheduler import prune_old_runs

    engine, _ = tmp_db_engine
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    _insert_runs(engine, runs_dir, 50)

    prune_old_runs(engine=engine, max_runs=200)

    from sqlalchemy import text
    from sqlalchemy.orm import Session
    with Session(engine) as session:
        count = session.execute(text("SELECT COUNT(*) FROM runs")).fetchone()[0]
    assert count == 50


def test_build_scheduler_returns_scheduler(tmp_db_engine, tmp_path):
    """build_scheduler() returns an APScheduler instance with SQLAlchemyJobStore."""
    from src.api.scheduler import build_scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    engine, _ = tmp_db_engine
    sched = build_scheduler(engine=engine)
    assert isinstance(sched, BackgroundScheduler)
    # Don't call shutdown() if it was never started
