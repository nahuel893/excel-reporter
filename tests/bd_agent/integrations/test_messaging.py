"""tests/bd_agent/integrations/test_messaging.py — Tests for WhatsAppMessagingGateway (T-071).

All tests mock httpx so no real HTTP calls are made.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import guard — module must exist
# ---------------------------------------------------------------------------

def test_module_importable():
    """T-071: bd_agent.integrations.messaging must be importable."""
    from bd_agent.integrations.messaging import WhatsAppMessagingGateway  # noqa: F401


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def base_url():
    return "http://localhost:3000"


@pytest.fixture()
def gateway(base_url):
    from bd_agent.integrations.messaging import WhatsAppMessagingGateway
    return WhatsAppMessagingGateway(base_url=base_url)


# ---------------------------------------------------------------------------
# Happy path — send_text posts to /send-text
# ---------------------------------------------------------------------------

def test_send_text_posts_to_correct_url(base_url):
    """T-071: send_text posts to {base_url}/send-text."""
    import httpx
    from bd_agent.integrations.messaging import WhatsAppMessagingGateway

    sent_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    gw = WhatsAppMessagingGateway(base_url=base_url, http_client=client)
    gw.send_text("5493870000000@s.whatsapp.net", "Hola!")

    assert len(sent_requests) == 1
    assert sent_requests[0].url.path == "/send-text"


def test_send_text_body_contains_jid_and_text(base_url):
    """T-071: send_text body contains 'jid' and 'text' fields."""
    import httpx
    import json
    from bd_agent.integrations.messaging import WhatsAppMessagingGateway

    captured_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    jid = "5493870000001@s.whatsapp.net"
    text = "Buenos días, este es el agente."
    gw = WhatsAppMessagingGateway(base_url=base_url, http_client=client)
    gw.send_text(jid, text)

    assert captured_body["jid"] == jid
    assert captured_body["text"] == text


def test_send_text_uses_post_method(base_url):
    """T-071: send_text uses HTTP POST (not GET/PUT/etc.)."""
    import httpx
    from bd_agent.integrations.messaging import WhatsAppMessagingGateway

    methods = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    gw = WhatsAppMessagingGateway(base_url=base_url, http_client=client)
    gw.send_text("jid@s.whatsapp.net", "test")
    assert methods == ["POST"]


# ---------------------------------------------------------------------------
# Error handling — non-2xx raises RuntimeError
# ---------------------------------------------------------------------------

def test_send_text_raises_on_non_2xx(base_url):
    """T-071: send_text raises RuntimeError when the service returns non-2xx."""
    import httpx
    from bd_agent.integrations.messaging import WhatsAppMessagingGateway

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    gw = WhatsAppMessagingGateway(base_url=base_url, http_client=client)
    with pytest.raises(RuntimeError):
        gw.send_text("jid@s.whatsapp.net", "hello")


def test_send_text_raises_on_network_error(base_url):
    """T-071: send_text raises when httpx encounters a network error."""
    import httpx
    from bd_agent.integrations.messaging import WhatsAppMessagingGateway

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    gw = WhatsAppMessagingGateway(base_url=base_url, http_client=client)
    with pytest.raises(Exception):
        gw.send_text("jid@s.whatsapp.net", "hello")


# ---------------------------------------------------------------------------
# Default http_client is created if none provided
# ---------------------------------------------------------------------------

def test_default_client_is_created_when_none_provided(base_url):
    """T-071: WhatsAppMessagingGateway creates its own httpx.Client if none injected."""
    import httpx
    from bd_agent.integrations.messaging import WhatsAppMessagingGateway
    gw = WhatsAppMessagingGateway(base_url=base_url)
    assert hasattr(gw, "_client")
    assert isinstance(gw._client, httpx.Client)


# ---------------------------------------------------------------------------
# MessagingGateway Protocol satisfaction
# ---------------------------------------------------------------------------

def test_implements_messaging_gateway_protocol(base_url):
    """T-071: WhatsAppMessagingGateway satisfies the MessagingGateway Protocol."""
    from bd_agent.contracts import MessagingGateway
    from bd_agent.integrations.messaging import WhatsAppMessagingGateway
    gw = WhatsAppMessagingGateway(base_url=base_url)
    assert isinstance(gw, MessagingGateway)


# ---------------------------------------------------------------------------
# No imports from src.*
# ---------------------------------------------------------------------------

def test_no_src_imports():
    """T-071/RF-070: bd_agent.integrations.messaging must not import from src.*"""
    import ast
    import importlib.util

    spec = importlib.util.find_spec("bd_agent.integrations.messaging")
    assert spec is not None, "Module not found"
    source = Path(spec.origin).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("src."), (
                f"bd_agent.integrations.messaging imports from src.*: {node.module}"
            )
