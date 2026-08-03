"""
Tests for src/api/runner.py — RunSession, RunRegistry, trigger(), subscribe().

TDD: written BEFORE implementation.
"""
import asyncio
import os
import re
import pytest


@pytest.fixture
def registry(tmp_path, event_loop):
    """Create a RunRegistry with a tmp data/runs dir."""
    from src.api.db import engine_from_url, init_db
    from src.api.runner import RunRegistry
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    loop = asyncio.get_event_loop()
    engine = engine_from_url(f"sqlite:///{tmp_path}/test.db")
    init_db(engine=engine)
    reg = RunRegistry(loop=loop, runs_dir=runs_dir, engine=engine)
    return reg


def test_run_id_format_matches_regex(tmp_path):
    """trigger() returns a run_id matching ^\\d{8}-\\d{6}-[a-z0-9-]+$"""
    import asyncio
    from src.api.db import engine_from_url, init_db
    from src.api.runner import RunRegistry

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    loop = asyncio.new_event_loop()

    engine = engine_from_url(f"sqlite:///{tmp_path}/test.db")
    init_db(engine=engine)
    reg = RunRegistry(loop=loop, runs_dir=runs_dir, engine=engine)

    # Use a fake config that reads tipo from a JSON file
    config_path = tmp_path / "ventas.json"
    config_path.write_text('{"tipo": "ventas", "filtros": {}, "reportes": []}')

    run_id = asyncio.get_event_loop().run_until_complete(
        reg.trigger(
            config_filename=str(config_path),
            triggered_by="manual",
            no_delivery=False,
            test_mode=False,
        )
    )
    pattern = r'^\d{8}-\d{6}-[a-z0-9-]+$'
    assert re.match(pattern, run_id), f"run_id {run_id!r} does not match pattern {pattern}"

    # Wait for the reader thread to finish (bounded — a hang here means the
    # isolation fix regressed, not that the suite should hang forever).
    loop.run_until_complete(asyncio.wait_for(reg.wait_for(run_id), timeout=5))
    loop.close()


def test_slug_derived_from_config_tipo(tmp_path):
    """run_id slug comes from the config's 'tipo' field."""
    import asyncio
    from src.api.db import engine_from_url, init_db
    from src.api.runner import RunRegistry

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    loop = asyncio.new_event_loop()

    engine = engine_from_url(f"sqlite:///{tmp_path}/test.db")
    init_db(engine=engine)
    reg = RunRegistry(loop=loop, runs_dir=runs_dir, engine=engine)

    config_path = tmp_path / "resumen_mensual.json"
    config_path.write_text('{"tipo": "resumen-mensual", "filtros": {}, "reportes": []}')

    run_id = loop.run_until_complete(
        reg.trigger(
            config_filename=str(config_path),
            triggered_by="manual",
            no_delivery=False,
            test_mode=False,
        )
    )
    # run_id ends with the slug part
    assert run_id.endswith("-resumen-mensual"), f"expected slug 'resumen-mensual' in {run_id!r}"

    loop.run_until_complete(asyncio.wait_for(reg.wait_for(run_id), timeout=5))
    loop.close()


def test_run_registry_stores_active_session(tmp_path):
    """After trigger(), the session is stored in the registry."""
    import asyncio
    from src.api.db import engine_from_url, init_db
    from src.api.runner import RunRegistry

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    loop = asyncio.new_event_loop()
    engine = engine_from_url(f"sqlite:///{tmp_path}/test.db")
    init_db(engine=engine)
    reg = RunRegistry(loop=loop, runs_dir=runs_dir, engine=engine)

    config_path = tmp_path / "ventas.json"
    config_path.write_text('{"tipo": "ventas", "filtros": {}, "reportes": []}')

    run_id = loop.run_until_complete(
        reg.trigger(
            config_filename=str(config_path),
            triggered_by="manual",
            no_delivery=False,
            test_mode=False,
        )
    )
    assert reg.get_session(run_id) is not None

    loop.run_until_complete(asyncio.wait_for(reg.wait_for(run_id), timeout=5))
    loop.close()


def test_second_trigger_same_config_returns_busy_error(tmp_path):
    """A second trigger for the same config while first is running returns RunBusyError."""
    import asyncio
    from src.api.db import engine_from_url, init_db
    from src.api.runner import RunRegistry, RunBusyError

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    loop = asyncio.new_event_loop()
    engine = engine_from_url(f"sqlite:///{tmp_path}/test.db")
    init_db(engine=engine)
    reg = RunRegistry(loop=loop, runs_dir=runs_dir, engine=engine)

    config_path = tmp_path / "ventas.json"
    config_path.write_text('{"tipo": "ventas", "filtros": {}, "reportes": []}')

    # First trigger
    run_id1 = loop.run_until_complete(
        reg.trigger(config_filename=str(config_path), triggered_by="manual")
    )

    # Second trigger same config should raise
    with pytest.raises(RunBusyError) as exc_info:
        loop.run_until_complete(
            reg.trigger(config_filename=str(config_path), triggered_by="manual")
        )

    assert exc_info.value.active_run_id == run_id1

    loop.run_until_complete(asyncio.wait_for(reg.wait_for(run_id1), timeout=5))
    loop.close()


def test_get_default_engine_raises_when_run_under_pytest():
    """get_default_engine() must refuse to point at data/mgmt.db while pytest is running.

    pytest sets PYTEST_CURRENT_TEST for the duration of every test, so this
    guard fires unconditionally unless a test explicitly injects its own
    engine= (RF-08 — test isolation from the production DB).
    """
    from src.api.db import get_default_engine

    assert os.environ.get("PYTEST_CURRENT_TEST"), "expected to run under pytest"

    with pytest.raises(RuntimeError):
        get_default_engine()
