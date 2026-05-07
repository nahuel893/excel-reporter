"""tests/bd_agent/transport/test_router.py — Tests for FastAPI router (T-072).

Uses FastAPI TestClient with mocked AgentTurn and ContactsRepo.
All tests run without a real DB or WhatsApp connection.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Import guard — module must exist
# ---------------------------------------------------------------------------

def test_module_importable():
    """T-072: bd_agent.transport.router must be importable."""
    from bd_agent.transport.router import make_router  # noqa: F401


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_agent_turn():
    turn = MagicMock()
    turn.handle_incoming = MagicMock()
    return turn


@pytest.fixture()
def mock_contacts_repo():
    repo = MagicMock()
    repo.reload = MagicMock()
    return repo


@pytest.fixture()
def mock_gateway():
    gw = MagicMock()
    gw.reload_schema_doc = MagicMock()
    return gw


@pytest.fixture()
def client(mock_agent_turn, mock_contacts_repo, mock_gateway):
    """TestClient wired with mocked AgentTurn, ContactsRepo, and gateway."""
    from bd_agent.transport.router import make_router
    router = make_router(
        agent_turn=mock_agent_turn,
        contacts_repo=mock_contacts_repo,
        db_gateway=mock_gateway,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), mock_agent_turn, mock_contacts_repo, mock_gateway


# ---------------------------------------------------------------------------
# POST /agent/message — happy path
# ---------------------------------------------------------------------------

def test_post_message_returns_200(client):
    """T-072: POST /agent/message returns 200 with {ok: true}."""
    tc, agent, _, _ = client
    payload = {"from": "5493870000001@s.whatsapp.net", "text": "hola", "ts": time.time()}
    resp = tc.post("/agent/message", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True


def test_post_message_calls_handle_incoming(client):
    """T-072: POST /agent/message invokes agent_turn.handle_incoming with jid/text/ts."""
    tc, agent, _, _ = client
    ts = time.time()
    jid = "5493870000001@s.whatsapp.net"
    payload = {"from": jid, "text": "hola", "ts": ts}
    tc.post("/agent/message", json=payload)
    # Wait for background task (TestClient runs synchronously)
    agent.handle_incoming.assert_called_once_with(jid, "hola", ts)


def test_post_message_returns_immediately(client):
    """T-072: POST /agent/message returns 200 without waiting for processing."""
    tc, agent, _, _ = client
    # Even if handle_incoming is slow, the response comes back quickly
    import threading
    event = threading.Event()
    original = agent.handle_incoming

    def slow_handler(*args, **kwargs):
        event.wait(timeout=0.1)  # simulate brief delay
        return original(*args, **kwargs)

    agent.handle_incoming = slow_handler
    payload = {"from": "jid@s.whatsapp.net", "text": "hello", "ts": 1.0}
    resp = tc.post("/agent/message", json=payload)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /agent/message — deduplication (RF-011)
# ---------------------------------------------------------------------------

def test_duplicate_message_returns_202_accepted(client):
    """T-072/RF-011: Same (from, ts) within 60s window returns 202 {status: duplicate}."""
    tc, agent, _, _ = client
    ts = time.time()
    payload = {"from": "5493870000001@s.whatsapp.net", "text": "hola", "ts": ts}
    # First call
    resp1 = tc.post("/agent/message", json=payload)
    assert resp1.status_code == 200
    # Second call (same from + ts)
    resp2 = tc.post("/agent/message", json=payload)
    assert resp2.status_code == 202
    assert resp2.json().get("status") == "duplicate"


def test_duplicate_does_not_invoke_agent_twice(client):
    """T-072/RF-011: Duplicate message must NOT invoke handle_incoming a second time."""
    tc, agent, _, _ = client
    ts = time.time()
    payload = {"from": "jid@s.whatsapp.net", "text": "test", "ts": ts}
    tc.post("/agent/message", json=payload)
    tc.post("/agent/message", json=payload)
    agent.handle_incoming.assert_called_once()


def test_different_ts_is_not_deduped(client):
    """T-072: Different ts values from same JID are treated as distinct messages."""
    tc, agent, _, _ = client
    jid = "jid@s.whatsapp.net"
    tc.post("/agent/message", json={"from": jid, "text": "msg1", "ts": 100.0})
    tc.post("/agent/message", json={"from": jid, "text": "msg2", "ts": 200.0})
    assert agent.handle_incoming.call_count == 2


def test_different_jid_same_ts_is_not_deduped(client):
    """T-072: Same ts from different JIDs is treated as distinct messages."""
    tc, agent, _, _ = client
    ts = 999.0
    tc.post("/agent/message", json={"from": "jid1@s.whatsapp.net", "text": "a", "ts": ts})
    tc.post("/agent/message", json={"from": "jid2@s.whatsapp.net", "text": "b", "ts": ts})
    assert agent.handle_incoming.call_count == 2


# ---------------------------------------------------------------------------
# POST /agent/message — validation
# ---------------------------------------------------------------------------

def test_missing_from_field_returns_422(client):
    """T-072: POST /agent/message with missing 'from' returns 422."""
    tc, _, _, _ = client
    resp = tc.post("/agent/message", json={"text": "hola", "ts": 1.0})
    assert resp.status_code == 422


def test_missing_text_field_returns_422(client):
    """T-072: POST /agent/message with missing 'text' returns 422."""
    tc, _, _, _ = client
    resp = tc.post("/agent/message", json={"from": "jid@s.whatsapp.net", "ts": 1.0})
    assert resp.status_code == 422


def test_missing_ts_field_returns_422(client):
    """T-072: POST /agent/message with missing 'ts' returns 422."""
    tc, _, _, _ = client
    resp = tc.post("/agent/message", json={"from": "jid@s.whatsapp.net", "text": "hi"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /agent/reload-schema
# ---------------------------------------------------------------------------

def test_reload_schema_returns_200(client):
    """T-072/RF-082: POST /agent/reload-schema returns 200."""
    tc, _, _, _ = client
    resp = tc.post("/agent/reload-schema")
    assert resp.status_code == 200


def test_reload_schema_calls_gateway_reload(client):
    """T-072/RF-082: POST /agent/reload-schema triggers schema doc reload."""
    tc, _, _, gw = client
    tc.post("/agent/reload-schema")
    gw.reload_schema_doc.assert_called_once()


# ---------------------------------------------------------------------------
# POST /agent/reload-contacts
# ---------------------------------------------------------------------------

def test_reload_contacts_returns_200(client):
    """T-072: POST /agent/reload-contacts returns 200."""
    tc, _, _, _ = client
    resp = tc.post("/agent/reload-contacts")
    assert resp.status_code == 200


def test_reload_contacts_calls_repo_reload(client):
    """T-072: POST /agent/reload-contacts triggers ContactsRepo.reload()."""
    tc, _, repo, _ = client
    tc.post("/agent/reload-contacts")
    repo.reload.assert_called_once()


# ---------------------------------------------------------------------------
# GET /agent/metrics
# ---------------------------------------------------------------------------

def test_metrics_endpoint_returns_200(client):
    """T-111: GET /agent/metrics returns 200 with metrics snapshot."""
    tc, _, _, _ = client
    resp = tc.get("/agent/metrics")
    assert resp.status_code == 200


def test_metrics_endpoint_returns_expected_keys(client):
    """T-111: GET /agent/metrics returns all expected counter keys."""
    tc, _, _, _ = client
    resp = tc.get("/agent/metrics")
    data = resp.json()
    expected_keys = {
        "messages_received",
        "messages_sent",
        "tool_calls_by_name",
        "errors_by_type",
        "errors_total",
        "tokens_in_total",
        "tokens_out_total",
        "uptime_seconds",
    }
    assert expected_keys.issubset(set(data.keys()))


# ---------------------------------------------------------------------------
# No imports from src.*
# ---------------------------------------------------------------------------

def test_no_src_imports():
    """T-072/RF-070: bd_agent.transport.router must not import from src.*"""
    import ast
    import importlib.util

    spec = importlib.util.find_spec("bd_agent.transport.router")
    assert spec is not None, "Module not found"
    source = Path(spec.origin).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("src."), (
                f"bd_agent.transport.router imports from src.*: {node.module}"
            )
