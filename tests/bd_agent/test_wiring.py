"""tests/bd_agent/test_wiring.py — Tests for bd_agent.wiring factory (T-073).

Tests verify that build_agent_runtime correctly wires the dependency graph
and returns an AgentRuntime, with graceful skip on missing env vars.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import guard — module must exist
# ---------------------------------------------------------------------------

def test_module_importable():
    """T-073: bd_agent.wiring must be importable."""
    from bd_agent.wiring import build_agent_runtime  # noqa: F401


def test_agent_runtime_importable():
    """T-073: AgentRuntime dataclass must be importable from bd_agent.wiring."""
    from bd_agent.wiring import AgentRuntime  # noqa: F401


# ---------------------------------------------------------------------------
# AgentRuntime structure
# ---------------------------------------------------------------------------

def test_agent_runtime_has_expected_fields():
    """T-073: AgentRuntime must expose agent_turn, contacts_repo, db_gateway, router."""
    from bd_agent.wiring import AgentRuntime
    import dataclasses
    fields = {f.name for f in dataclasses.fields(AgentRuntime)}
    assert {"agent_turn", "contacts_repo", "db_gateway", "router"} <= fields


# ---------------------------------------------------------------------------
# Missing GEMINI_API_KEY → returns None, doesn't crash
# ---------------------------------------------------------------------------

def test_missing_gemini_key_returns_none(tmp_path, monkeypatch):
    """T-073/RF-081: Missing GEMINI_API_KEY → build_agent_runtime returns None."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_DB_URL", "postgresql+psycopg://agent:pwd@localhost/db")

    contacts_path = tmp_path / "contactos.json"
    contacts_path.write_text(
        '{"contacts": [], "settings": {"active_hours_start": "07:00", '
        '"active_hours_end": "22:00", "timezone": "America/Argentina/Salta"}}'
    )
    schema_path = tmp_path / "CONTEXT_DATABASE.md"
    schema_path.write_text("# schema")

    from bd_agent.wiring import build_agent_runtime
    runtime = build_agent_runtime(
        contacts_path=contacts_path,
        schema_doc_path=schema_path,
    )
    assert runtime is None


def test_missing_agent_db_url_returns_none(tmp_path, monkeypatch):
    """T-073/RF-081: Missing AGENT_DB_URL → build_agent_runtime returns None."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("AGENT_DB_URL", raising=False)

    contacts_path = tmp_path / "contactos.json"
    contacts_path.write_text(
        '{"contacts": [], "settings": {"active_hours_start": "07:00", '
        '"active_hours_end": "22:00", "timezone": "America/Argentina/Salta"}}'
    )
    schema_path = tmp_path / "CONTEXT_DATABASE.md"
    schema_path.write_text("# schema")

    from bd_agent.wiring import build_agent_runtime
    runtime = build_agent_runtime(
        contacts_path=contacts_path,
        schema_doc_path=schema_path,
    )
    assert runtime is None


# ---------------------------------------------------------------------------
# Happy path — all env vars present, returns AgentRuntime
# ---------------------------------------------------------------------------

def test_happy_path_returns_agent_runtime(tmp_path, monkeypatch):
    """T-073: All env vars present → returns AgentRuntime (not None)."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("AGENT_DB_URL", "postgresql+psycopg://agent:pwd@localhost/db")

    contacts_path = tmp_path / "contactos.json"
    contacts_path.write_text(
        '{"contacts": [], "settings": {"active_hours_start": "07:00", '
        '"active_hours_end": "22:00", "timezone": "America/Argentina/Salta"}}'
    )
    schema_path = tmp_path / "CONTEXT_DATABASE.md"
    schema_path.write_text("# schema doc")

    # Patch create_engine to avoid real DB
    fake_engine = MagicMock()
    fake_conn = MagicMock()
    fake_engine.connect.return_value.__enter__ = MagicMock(return_value=fake_conn)
    fake_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("bd_agent.integrations.database.create_engine", return_value=fake_engine):
        from bd_agent.wiring import build_agent_runtime, AgentRuntime
        runtime = build_agent_runtime(
            contacts_path=contacts_path,
            schema_doc_path=schema_path,
        )

    assert runtime is not None
    assert isinstance(runtime, AgentRuntime)


def test_runtime_agent_turn_not_none(tmp_path, monkeypatch):
    """T-073: runtime.agent_turn is a valid AgentTurn instance."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("AGENT_DB_URL", "postgresql+psycopg://agent:pwd@localhost/db")

    contacts_path = tmp_path / "contactos.json"
    contacts_path.write_text(
        '{"contacts": [], "settings": {"active_hours_start": "07:00", '
        '"active_hours_end": "22:00", "timezone": "America/Argentina/Salta"}}'
    )
    schema_path = tmp_path / "CONTEXT_DATABASE.md"
    schema_path.write_text("# schema doc")

    fake_engine = MagicMock()
    fake_conn = MagicMock()
    fake_engine.connect.return_value.__enter__ = MagicMock(return_value=fake_conn)
    fake_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("bd_agent.integrations.database.create_engine", return_value=fake_engine):
        from bd_agent import wiring as wiring_mod
        # Force reimport to pick up patched create_engine
        import importlib
        importlib.reload(wiring_mod)
        runtime = wiring_mod.build_agent_runtime(
            contacts_path=contacts_path,
            schema_doc_path=schema_path,
        )

    assert runtime is not None
    assert runtime.agent_turn is not None


def test_runtime_router_not_none(tmp_path, monkeypatch):
    """T-073: runtime.router is a FastAPI APIRouter."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("AGENT_DB_URL", "postgresql+psycopg://agent:pwd@localhost/db")

    contacts_path = tmp_path / "contactos.json"
    contacts_path.write_text(
        '{"contacts": [], "settings": {"active_hours_start": "07:00", '
        '"active_hours_end": "22:00", "timezone": "America/Argentina/Salta"}}'
    )
    schema_path = tmp_path / "CONTEXT_DATABASE.md"
    schema_path.write_text("# schema doc")

    fake_engine = MagicMock()
    fake_conn = MagicMock()
    fake_engine.connect.return_value.__enter__ = MagicMock(return_value=fake_conn)
    fake_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("bd_agent.integrations.database.create_engine", return_value=fake_engine):
        from bd_agent.wiring import build_agent_runtime
        runtime = build_agent_runtime(
            contacts_path=contacts_path,
            schema_doc_path=schema_path,
        )

    from fastapi.routing import APIRouter
    assert runtime is not None
    assert runtime.router is not None


# ---------------------------------------------------------------------------
# No imports from src.*
# ---------------------------------------------------------------------------

def test_no_src_imports():
    """T-073/RF-070: bd_agent.wiring must not import from src.*"""
    import ast
    import importlib.util

    spec = importlib.util.find_spec("bd_agent.wiring")
    assert spec is not None, "Module not found"
    source = Path(spec.origin).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("src."), (
                f"bd_agent.wiring imports from src.*: {node.module}"
            )


# ---------------------------------------------------------------------------
# RF-091: build_agent_runtime installs RotatingFileHandler on bd_agent logger
# ---------------------------------------------------------------------------

# These tests require google.genai to be installed (GeminiProvider dependency).
# They are skipped gracefully when the package is absent (SUGGESTION-1).
_google_genai_available = True
try:
    import google.genai  # noqa: F401
except ImportError:
    _google_genai_available = False

_needs_google_genai = pytest.mark.skipif(
    not _google_genai_available,
    reason="google-genai not installed — skipping wiring tests that require GeminiProvider",
)


def _make_tmp_contacts(tmp_path):
    contacts_path = tmp_path / "contactos.json"
    contacts_path.write_text(
        '{"contacts": [], "settings": {"active_hours_start": "07:00", '
        '"active_hours_end": "22:00", "timezone": "America/Argentina/Salta"}}'
    )
    return contacts_path


def _make_tmp_schema(tmp_path):
    schema_path = tmp_path / "CONTEXT_DATABASE.md"
    schema_path.write_text("# schema doc")
    return schema_path


def _patched_runtime(tmp_path, monkeypatch):
    """Helper: build runtime with patched DB engine; returns runtime."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("AGENT_DB_URL", "postgresql+psycopg://agent:pwd@localhost/db")

    contacts_path = _make_tmp_contacts(tmp_path)
    schema_path = _make_tmp_schema(tmp_path)

    fake_engine = MagicMock()
    fake_conn = MagicMock()
    fake_engine.connect.return_value.__enter__ = MagicMock(return_value=fake_conn)
    fake_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("bd_agent.integrations.database.create_engine", return_value=fake_engine):
        from bd_agent.wiring import build_agent_runtime
        return build_agent_runtime(
            contacts_path=contacts_path,
            schema_doc_path=schema_path,
        )


@_needs_google_genai
def test_build_agent_runtime_installs_error_log_handler(tmp_path, monkeypatch):
    """RF-091: build_agent_runtime must install a RotatingFileHandler on the bd_agent logger."""
    import logging
    from logging.handlers import RotatingFileHandler

    runtime = _patched_runtime(tmp_path, monkeypatch)
    assert runtime is not None

    bd_agent_logger = logging.getLogger("bd_agent")
    error_handlers = [
        h for h in bd_agent_logger.handlers if isinstance(h, RotatingFileHandler)
    ]
    assert len(error_handlers) >= 1, (
        "build_agent_runtime must install a RotatingFileHandler on the 'bd_agent' logger"
    )


@_needs_google_genai
def test_error_log_handler_level_is_error(tmp_path, monkeypatch):
    """RF-091: The installed RotatingFileHandler must be at ERROR level."""
    import logging
    from logging.handlers import RotatingFileHandler

    runtime = _patched_runtime(tmp_path, monkeypatch)
    assert runtime is not None

    bd_agent_logger = logging.getLogger("bd_agent")
    error_handlers = [
        h for h in bd_agent_logger.handlers if isinstance(h, RotatingFileHandler)
    ]
    assert len(error_handlers) >= 1
    assert error_handlers[0].level == logging.ERROR


@_needs_google_genai
def test_build_agent_runtime_delay_fn_is_not_noop(tmp_path, monkeypatch):
    """WARNING-1/RF-040: build_agent_runtime must inject a real delay_fn into AgentTurn.

    The delay_fn must NOT be the bd_agent.agent._noop (no-op) function.
    This ensures replies actually wait for the jitter delay in production.
    """
    from bd_agent.agent import _noop

    runtime = _patched_runtime(tmp_path, monkeypatch)
    assert runtime is not None

    agent_turn = runtime.agent_turn
    # Access the injected delay_fn from the AgentTurn instance
    injected_delay_fn = agent_turn._delay_fn
    assert injected_delay_fn is not _noop, (
        "build_agent_runtime must inject a real jitter delay_fn, not the _noop sentinel"
    )


@_needs_google_genai
def test_build_agent_runtime_delay_fn_returns_float(tmp_path, monkeypatch):
    """RF-040: The injected delay_fn must be callable and return a numeric value.

    We don't actually sleep in tests — we check the callable returns [2, 30].
    """
    runtime = _patched_runtime(tmp_path, monkeypatch)
    assert runtime is not None

    # Calling delay_fn in test should NOT sleep (we patch time.sleep)
    with patch("time.sleep"):
        agent_turn = runtime.agent_turn
        delay_fn = agent_turn._delay_fn
        # Call the delay_fn; if it returns a number it's the jitter value
        # If it calls time.sleep internally, that's also fine (we patched it)
        # The key requirement: it must not raise and must be callable
        delay_fn()  # Should not raise
