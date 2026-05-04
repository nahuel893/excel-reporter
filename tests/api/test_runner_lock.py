"""
Tests for T-105: concurrency lock — second trigger returns 409.

TDD: written BEFORE implementation.
"""
import asyncio
import sys
import textwrap
import pytest
from pathlib import Path


SLOW_SCRIPT = textwrap.dedent("""\
    import time, sys
    print("started", flush=True)
    time.sleep(60)
    sys.exit(0)
""")


def _make_config(tmp_path, tipo="ventas"):
    cfg = tmp_path / "ventas.json"
    cfg.write_text(f'{{"tipo": "{tipo}", "filtros": {{}}, "reportes": []}}')
    return cfg


def test_second_trigger_same_config_returns_409_via_http(tmp_path):
    """POST /mgmt/runs twice for the same config while first is running → 409."""
    import asyncio
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from src.api.db import init_db, engine_from_url
    from src.api.runner import RunRegistry

    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = engine_from_url(db_url)
    init_db(engine=engine)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    slow_script = tmp_path / "slow.py"
    slow_script.write_text(SLOW_SCRIPT)

    # Create a mini FastAPI app for testing
    app = FastAPI()
    loop = asyncio.new_event_loop()

    class FakeRegistry(RunRegistry):
        def _build_cmd(self, config_filename, no_delivery, test_mode):
            return [sys.executable, str(slow_script)]

    registry = FakeRegistry(loop=loop, runs_dir=runs_dir, engine=engine)
    app.state.runner = registry
    app.state.engine = engine

    from src.api.routes.mgmt_runs import router as mgmt_runs_router
    app.include_router(mgmt_runs_router)

    config_path = _make_config(tmp_path)

    with TestClient(app, raise_server_exceptions=False) as client:
        # First request
        r1 = client.post("/mgmt/runs", json={"config_filename": str(config_path)})
        assert r1.status_code in (200, 202), f"First trigger failed: {r1.status_code} {r1.text}"
        run_id1 = r1.json()["run_id"]

        # Second request — same config should be 409
        r2 = client.post("/mgmt/runs", json={"config_filename": str(config_path)})
        assert r2.status_code == 409, f"Expected 409, got {r2.status_code}: {r2.text}"
        body = r2.json()
        assert "detail" in body
        assert "run_id" in body
        assert body["run_id"] == run_id1

    # Terminate running process
    session = registry.get_session(run_id1)
    if session:
        session.terminate()
    loop.close()
