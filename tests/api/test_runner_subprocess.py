"""
Tests for T-103: reader thread → asyncio bridge.

Spawns a fake script, asserts all lines captured in log file,
run row has status=success exit_code=0, lock released.

TDD: written BEFORE full implementation (though runner.py has a partial impl).
"""
import asyncio
import sys
import textwrap
import time
import pytest
from pathlib import Path


FAKE_SCRIPT_1000 = textwrap.dedent("""\
    import sys
    for i in range(1000):
        print(f"line {i}", flush=True)
    sys.exit(0)
""")


@pytest.fixture
def fake_1000_script(tmp_path):
    script = tmp_path / "fake_1000.py"
    script.write_text(FAKE_SCRIPT_1000)
    return script


def _make_config(tmp_path, tipo="ventas"):
    cfg = tmp_path / "ventas.json"
    cfg.write_text(f'{{"tipo": "{tipo}", "filtros": {{}}, "reportes": []}}')
    return cfg


def test_reader_captures_all_1000_lines(tmp_path, fake_1000_script):
    """Fake script prints 1000 lines; all must appear in the log file."""
    import asyncio
    from src.api.runner import RunRegistry
    from src.api.db import init_db, engine_from_url

    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = engine_from_url(db_url)
    init_db(engine=engine)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Patch the command to run our fake script directly
    loop = asyncio.new_event_loop()

    reg = RunRegistry(loop=loop, runs_dir=runs_dir, engine=engine)

    # Monkey-patch trigger to run the fake script directly
    config_path = _make_config(tmp_path)

    # We override the subprocess command via a subclass
    class FakeRegistry(RunRegistry):
        def _build_cmd(self, config_filename, no_delivery, test_mode):
            return [sys.executable, str(fake_1000_script)]

    reg2 = FakeRegistry(loop=loop, runs_dir=runs_dir, engine=engine)
    run_id = loop.run_until_complete(
        reg2.trigger(config_filename=str(config_path), triggered_by="manual")
    )

    # Wait for the run to complete
    loop.run_until_complete(reg2.wait_for(run_id))

    log_path = runs_dir / f"{run_id}.log"
    assert log_path.exists(), f"Log file not found: {log_path}"

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1000, f"Expected 1000 lines, got {len(lines)}"

    # Verify DB row
    from sqlalchemy import text
    from sqlalchemy.orm import Session as SA_Session
    with SA_Session(engine) as sess:
        row = sess.execute(
            text("SELECT status, exit_code FROM runs WHERE id=:id"),
            {"id": run_id}
        ).fetchone()
    assert row is not None, "Run row not found in DB"
    assert row[0] == "success", f"Expected status=success, got {row[0]}"
    assert row[1] == 0, f"Expected exit_code=0, got {row[1]}"

    # Lock should be released (new trigger on same config should not raise RunBusyError)
    from src.api.runner import RunBusyError
    try:
        run_id2 = loop.run_until_complete(
            reg2.trigger(config_filename=str(config_path), triggered_by="manual")
        )
        loop.run_until_complete(reg2.wait_for(run_id2))
    except RunBusyError:
        pytest.fail("Lock was not released after first run finished")

    loop.close()


def test_reader_captures_exit_code_nonzero(tmp_path):
    """Script that exits 1 produces status=error in DB."""
    import asyncio
    from src.api.runner import RunRegistry
    from src.api.db import init_db, engine_from_url

    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = engine_from_url(db_url)
    init_db(engine=engine)

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    error_script = tmp_path / "fail.py"
    error_script.write_text("import sys; print('error line'); sys.exit(1)")

    loop = asyncio.new_event_loop()

    class FakeRegistry(RunRegistry):
        def _build_cmd(self, config_filename, no_delivery, test_mode):
            return [sys.executable, str(error_script)]

    config_path = _make_config(tmp_path)
    reg = FakeRegistry(loop=loop, runs_dir=runs_dir, engine=engine)
    run_id = loop.run_until_complete(
        reg.trigger(config_filename=str(config_path), triggered_by="manual")
    )
    loop.run_until_complete(reg.wait_for(run_id))

    from sqlalchemy import text
    from sqlalchemy.orm import Session as SA_Session
    with SA_Session(engine) as sess:
        row = sess.execute(
            text("SELECT status, exit_code FROM runs WHERE id=:id"),
            {"id": run_id}
        ).fetchone()
    assert row[0] == "error", f"Expected status=error, got {row[0]}"
    assert row[1] == 1

    loop.close()
