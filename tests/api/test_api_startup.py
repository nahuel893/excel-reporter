"""
Tests for T-110: api.py startup hooks — init_db, recover_interrupted_runs,
RunRegistry attached to app.state, scheduler started.

TDD: written BEFORE api.py changes.
"""
import pytest


def test_api_imports_cleanly():
    """import api; print('ok') must succeed."""
    import importlib
    try:
        import api  # noqa: F401
        importlib.reload(api)
    except Exception as exc:
        pytest.fail(f"api.py import failed: {exc}")


def test_api_has_mgmt_routers():
    """api.py must have /mgmt/ routes registered."""
    import api
    from fastapi.testclient import TestClient
    client = TestClient(api.app)
    # mgmt/configs should exist
    r = client.get("/mgmt/configs")
    assert r.status_code in (200,), f"Expected 200, got {r.status_code}: {r.text}"


def test_startup_marks_running_as_interrupted(tmp_path, monkeypatch):
    """On startup, any 'running' row in the DB is flipped to 'interrupted'."""
    from src.api.db import init_db, engine_from_url, Run
    from datetime import datetime, timezone
    from sqlalchemy.orm import Session
    from sqlalchemy import text

    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = engine_from_url(db_url)
    init_db(engine=engine)

    # Insert a 'running' row
    with Session(engine) as sess:
        run = Run(
            id="20260101-120000-ventas",
            config_file="ventas.json",
            slug="ventas",
            started_at=datetime.now(timezone.utc).isoformat(),
            status="running",
            log_path="data/runs/test.log",
            triggered_by="manual",
            test_mode=False,
        )
        sess.add(run)
        sess.commit()

    # Call recover
    from src.api.db import recover_interrupted_runs
    recover_interrupted_runs(engine=engine)

    with Session(engine) as sess:
        row = sess.execute(
            text("SELECT status FROM runs WHERE id = '20260101-120000-ventas'")
        ).fetchone()

    assert row[0] == "interrupted"
