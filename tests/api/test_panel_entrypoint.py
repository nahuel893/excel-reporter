"""
Tests for panel.py — the admin panel composition root.

What matters here is the boundary it claims: panel.py adds the admin routers,
api.py is left alone, and the isolation is by process rather than by app
object. The last part is easy to describe wrongly, so it is asserted.
"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    assert included == {"mgmt_artifacts_router", "mgmt_schedule_router"}


def test_panel_mounts_each_admin_route_exactly_once(panel):
    seen = [
        (r.path, method)
        for r in panel.app.routes
        if getattr(r, "path", "").startswith(("/mgmt/artifacts", "/mgmt/schedule"))
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
        if path.startswith("/mgmt/artifacts") or path.startswith("/mgmt/schedule"):
            assert set(getattr(route, "methods", set())) <= {"GET", "HEAD"}
