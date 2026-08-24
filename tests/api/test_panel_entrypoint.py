"""
Tests for panel.py — the admin panel composition root.

What matters here is the boundary it claims: panel.py adds the admin routers,
api.py is left alone, and the isolation is by process rather than by app
object. The last part is easy to describe wrongly, so it is asserted.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every route prefix this file is responsible for.
_PANEL_PREFIXES = ("/mgmt/artifacts", "/mgmt/schedule", "/mgmt/daily-runs")


@pytest.fixture
def panel():
    # Imported, never reloaded: re-executing panel.py would call
    # include_router a second time on the same app and duplicate every route
    # it adds — an artefact of the test, not of the module.
    import panel as panel_module

    return panel_module


def _paths(app) -> set[str]:
    return {route.path for route in app.routes if hasattr(route, "path")}


def test_panel_mounts_the_admin_routers(panel):
    paths = _paths(panel.app)
    assert "/mgmt/artifacts/tree" in paths
    assert "/mgmt/artifacts/file" in paths
    assert "/mgmt/schedule" in paths
    assert "/mgmt/schedule/journal" in paths
    assert "/mgmt/daily-runs" in paths
    assert "/mgmt/daily-runs/{run_id}" in paths


def test_panel_keeps_what_api_already_served(panel):
    """Composition, not replacement: the production surface still answers."""
    paths = _paths(panel.app)
    assert "/health" in paths
    assert any(p.startswith("/ventas") for p in paths)


def test_panel_does_not_remount_routers_api_already_had():
    """mgmt_runs and mgmt_configs are mounted inside api.py. Including them
    here too would duplicate every one of their routes.

    Checked against the parsed include_router calls, not the file text — the
    module docstring names both on purpose, to explain why they are absent.
    """
    import ast

    tree = ast.parse((REPO_ROOT / "panel.py").read_text(encoding="utf-8"))
    included = {
        node.args[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "include_router"
        and node.args
        and isinstance(node.args[0], ast.Name)
    }
    assert included == {
        "mgmt_artifacts_router",
        "mgmt_schedule_router",
        "mgmt_daily_router",
    }


def test_panel_mounts_each_admin_route_exactly_once(panel):
    seen = [
        (r.path, method)
        for r in panel.app.routes
        if getattr(r, "path", "").startswith(_PANEL_PREFIXES)
        for method in getattr(r, "methods", set())
    ]
    assert len(seen) == len(set(seen)), f"duplicated routes: {seen}"


def test_api_py_does_not_reference_the_panel_routers():
    """The whole point of panel.py: api.py stays untouched by this feature.

    If someone later adds these imports to api.py, panel.py has lost its
    reason to exist and this test should be deleted deliberately, not
    silently drift.
    """
    source = (REPO_ROOT / "api.py").read_text(encoding="utf-8")
    assert "mgmt_artifacts" not in source
    assert "mgmt_schedule" not in source
    assert "mgmt_daily" not in source


def test_panel_app_is_the_same_object_api_builds(panel):
    """Isolation is by PROCESS, not by app object.

    panel.py mutates the app api.py built. Asserted so the docstring's honesty
    about that cannot quietly stop being true — if this ever becomes a real
    copy, the claim in the docs has to change with it.
    """
    import api

    assert panel.app is api.app


def test_panel_exposes_no_write_route_of_its_own(panel):
    """The routers panel.py adds are read-only (RF-17)."""
    for route in panel.app.routes:
        path = getattr(route, "path", "")
        if path.startswith(_PANEL_PREFIXES):
            assert set(getattr(route, "methods", set())) <= {"GET", "HEAD"}


def test_startup_creates_the_daily_store_tables(tmp_path):
    """Reading a table that was never created is a 500, not an empty history.

    api.py builds the engine and knows nothing about these tables, so the
    panel creates them itself on startup — create_all is idempotent, and an
    empty daily-runs screen is the honest answer before the first run.
    """
    from sqlalchemy import inspect

    import panel as panel_module
    from src.api.daily_store import engine_from_url

    engine = engine_from_url(f"sqlite:///{tmp_path}/mgmt.db")
    app = SimpleNamespace(state=SimpleNamespace(engine=engine))

    panel_module._init_daily_store(app)

    tables = set(inspect(engine).get_table_names())
    assert {"daily_runs", "daily_run_services", "run_artifacts"} <= tables


def test_the_startup_hook_is_actually_registered(panel):
    """The two tests above call _init_daily_store directly, so a decorator
    pointed at the wrong app or the wrong event name would leave them green
    while nothing ran on startup. This is what checks the wiring itself.

    Registration rather than a live startup: api.py's own handler builds the
    production engine, which refuses to run under pytest by design.
    """
    assert panel._panel_startup in panel.app.router.on_startup


def test_duplicate_positions_do_not_turn_a_log_request_into_a_500(tmp_path):
    """orden is not unique in the schema — (run_id, servicio) is.

    The recorder numbers sequentially so this should not happen, but "should
    not" is not a constraint, and the failure mode would be a 500 on a page
    whose whole job is telling you what went wrong.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.daily_store import (
        DailyRun,
        DailyRunService,
        engine_from_url,
        init_daily_store,
    )
    from src.api.routes.mgmt_daily import router, set_log_root
    from sqlalchemy.orm import Session

    engine = engine_from_url(f"sqlite:///{tmp_path}/mgmt.db")
    init_daily_store(engine)
    logs = tmp_path / "logs"
    logs.mkdir()
    log = logs / "svc.log"
    log.write_text("contenido\n", encoding="utf-8")

    with Session(engine) as s:
        s.add(DailyRun(
            id="r1", started_at="2026-08-24T07:00:00+00:00", status="success",
            triggered_by="schedule", test_mode=False, hoy="2026-08-24",
        ))
        for name in ("uno", "dos"):
            s.add(DailyRunService(
                run_id="r1", orden=1, servicio=name, status="success",
                log_path=str(log),
            ))
        s.commit()

    app = FastAPI()
    app.include_router(router)
    app.state.engine = engine
    set_log_root(logs)
    try:
        res = TestClient(app).get("/mgmt/daily-runs/r1/services/1/log")
    finally:
        set_log_root(None)

    assert res.status_code == 200
    assert "contenido" in res.text


def test_startup_without_an_engine_warns_instead_of_crashing():
    """api.py owns the engine. If it is not there, the panel must not take
    the whole process down on the way up."""
    import panel as panel_module

    panel_module._init_daily_store(SimpleNamespace(state=SimpleNamespace()))
