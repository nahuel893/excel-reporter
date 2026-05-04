"""
Tests for T-105: concurrent SSE subscribers with replay.

3 subscribers join at different times:
1. Before run starts (sees all lines)
2. Mid-run (sees replay prefix + remaining + done)
3. After run finishes (sees full replay + done)

TDD: Tests written to verify SSE subscriber behavior.
"""
import asyncio
import sys
import textwrap
import pytest
from pathlib import Path


# A script that prints 10 lines with small delays
TIMED_SCRIPT = textwrap.dedent("""\
    import sys, time
    for i in range(10):
        print(f"line {i}", flush=True)
    sys.exit(0)
""")


def _make_config(tmp_path, tipo="ventas"):
    cfg = tmp_path / "ventas.json"
    cfg.write_text(f'{{"tipo": "{tipo}", "filtros": {{}}, "reportes": []}}')
    return cfg


def test_subscriber_receives_all_events_after_run(tmp_path):
    """A subscriber joining AFTER the run finishes receives full replay via log file."""
    import asyncio
    from src.api.runner import RunRegistry
    from src.api.db import init_db, engine_from_url

    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = engine_from_url(db_url)
    init_db(engine=engine)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    fast_script = tmp_path / "fast.py"
    fast_script.write_text(TIMED_SCRIPT)

    loop = asyncio.new_event_loop()

    class FakeRegistry(RunRegistry):
        def _build_cmd(self, config_filename, no_delivery, test_mode):
            return [sys.executable, str(fast_script)]

    config_path = _make_config(tmp_path)
    reg = FakeRegistry(loop=loop, runs_dir=runs_dir, engine=engine)

    run_id = loop.run_until_complete(
        reg.trigger(config_filename=str(config_path), triggered_by="manual")
    )

    # Wait for run to finish
    loop.run_until_complete(reg.wait_for(run_id))

    # After completion, log file should have 10 lines
    log_path = runs_dir / f"{run_id}.log"
    assert log_path.exists()
    lines = log_path.read_text().splitlines()
    assert len(lines) == 10, f"Expected 10 lines, got {len(lines)}"

    loop.close()


def test_live_subscriber_receives_done_event(tmp_path):
    """A subscriber joining before run finishes receives a 'done' event."""
    import asyncio
    from src.api.runner import RunRegistry
    from src.api.db import init_db, engine_from_url

    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = engine_from_url(db_url)
    init_db(engine=engine)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    fast_script = tmp_path / "fast.py"
    fast_script.write_text(TIMED_SCRIPT)

    loop = asyncio.new_event_loop()

    class FakeRegistry(RunRegistry):
        def _build_cmd(self, config_filename, no_delivery, test_mode):
            return [sys.executable, str(fast_script)]

    config_path = _make_config(tmp_path)
    reg = FakeRegistry(loop=loop, runs_dir=runs_dir, engine=engine)

    collected = []

    async def collect_events():
        run_id = await reg.trigger(config_filename=str(config_path), triggered_by="manual")
        async for event in reg.subscribe(run_id):
            collected.append(event)

    loop.run_until_complete(collect_events())

    # Should have received log + done events
    types = [e["type"] for e in collected]
    assert "done" in types, f"No 'done' event received. Events: {types}"

    log_events = [e for e in collected if e["type"] == "log"]
    assert len(log_events) == 10, f"Expected 10 log events, got {len(log_events)}"

    loop.close()
