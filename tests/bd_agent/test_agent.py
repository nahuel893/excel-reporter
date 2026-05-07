"""Tests for bd_agent/agent.py — AgentTurn orchestrator pipeline.

TDD cycle (Strict TDD Mode — Slice 7):
  RED:   this file written first; bd_agent/agent.py does not exist yet.
  GREEN: bd_agent/agent.py implemented to pass all tests.

Covers:
  T-060 — AgentTurn class: full incoming-message turn pipeline
  T-061 — Integration test path (happy-path with realistic fakes)

Design:
  All dependencies are injected and mocked/faked — zero real DB, LLM, or
  WhatsApp calls.  delay_fn is a no-op lambda so tests don't sleep.
  now_fn is injected as midday Salta TZ to always be within active hours.

Zero imports from src.* (RF-070).
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Callable
from unittest.mock import MagicMock, call
from zoneinfo import ZoneInfo

import pytest

from bd_agent.contracts import (
    Contact,
    Message,
    ToolCall,
    ToolResult,
)
from bd_agent.llm.provider import LLMMessage, LLMResponse, LLMToolCall
from bd_agent.safety.allowlist import AllowlistGuard
from bd_agent.safety.active_hours import ActiveHoursGuard
from bd_agent.safety.rate_limiter import RateLimiter
from bd_agent.conversation.history import InMemoryHistory
from bd_agent.tools.registry import ToolRegistry

# Fixed "midday Salta" datetime always within default 07:00-22:00 window
_SALTA = ZoneInfo("America/Argentina/Salta")
_MIDDAY_SALTA = datetime(2026, 5, 7, 12, 0, 0, tzinfo=_SALTA)
_NIGHT_SALTA = datetime(2026, 5, 7, 23, 30, 0, tzinfo=_SALTA)


# ---------------------------------------------------------------------------
# Helpers and fakes
# ---------------------------------------------------------------------------

_KNOWN_JID = "5493870000001@s.whatsapp.net"
_UNKNOWN_JID = "9999999999@s.whatsapp.net"


class StaticContactsRepo:
    def __init__(self, contacts: list[Contact]):
        self._data = {c.jid: c for c in contacts}

    def get(self, jid: str) -> Contact | None:
        return self._data.get(jid)

    def list_all(self) -> list[Contact]:
        return list(self._data.values())

    def reload(self) -> None:
        pass


def _make_contact(jid: str = _KNOWN_JID) -> Contact:
    return Contact(
        name="Walter",
        jid=jid,
        daily_message_limit=100,
        permissions=("ventas",),
    )


class RecordingMessagingGateway:
    """Captures send_text() and send_file() calls for assertion."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.sent_files: list[tuple] = []

    def send_text(self, jid: str, text: str) -> None:
        self.sent.append((jid, text))

    def send_file(self, jid: str, file_path, caption=None) -> None:
        self.sent_files.append((jid, file_path, caption))


class ScriptedLLMProvider:
    """Returns a pre-configured sequence of LLMResponse objects."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[tuple] = []

    def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None,
        system_prompt: str,
    ) -> LLMResponse:
        self.calls.append((messages, tools, system_prompt))
        if not self._responses:
            # Fallback: always return text so we don't loop forever
            return LLMResponse(text="fallback", tool_calls=[])
        return self._responses.pop(0)


class InMemoryDatabaseGateway:
    """Fake DB gateway returning canned rows."""

    def __init__(self, rows: list[dict] | None = None):
        self._rows = rows or []

    def execute_select(
        self, query: str, params: dict, max_rows: int
    ) -> list[dict]:
        return self._rows[:max_rows]

    def get_schema_doc(self) -> str:
        return "fake schema doc"


def _make_allowlist(jids: list[str] | None = None) -> AllowlistGuard:
    if jids is None:
        jids = [_KNOWN_JID]
    contacts = [_make_contact(j) for j in jids]
    repo = StaticContactsRepo(contacts)
    return AllowlistGuard(repo=repo)


def _make_active_hours(start: str = "07:00", end: str = "22:00") -> ActiveHoursGuard:
    return ActiveHoursGuard(start=start, end=end)


def _make_rate_limiter(limit: int = 100) -> RateLimiter:
    return RateLimiter(daily_limit_resolver=lambda jid: limit)


def _noop_delay() -> None:
    """No-op delay function for tests (RF-040 injectable)."""
    pass


def _make_registry_with_tool(
    name: str = "test_tool",
    return_value: dict | None = None,
    raises: Exception | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()

    def handler(gateway, **kwargs):
        if raises is not None:
            raise raises
        return return_value or {"ok": True}

    registry.register(
        name=name,
        description="A test tool",
        params_schema={"type": "object", "properties": {}, "required": []},
        handler=handler,
    )
    return registry


def _make_agent(
    *,
    allowlist: AllowlistGuard | None = None,
    active_hours: ActiveHoursGuard | None = None,
    rate_limiter: RateLimiter | None = None,
    history: InMemoryHistory | None = None,
    contacts_repo=None,
    llm: ScriptedLLMProvider | None = None,
    tool_registry: ToolRegistry | None = None,
    messaging: RecordingMessagingGateway | None = None,
    schema_doc_loader: Callable[[], str] | None = None,
    delay_fn: Callable[[], None] | None = None,
    max_tool_iterations: int = 5,
    now_fn=None,
):
    """Build an AgentTurn with sensible defaults for unit tests.

    now_fn defaults to returning _MIDDAY_SALTA so the active-hours check
    always passes in unit tests (no real-time dependency).
    """
    from bd_agent.agent import AgentTurn

    if contacts_repo is None:
        contacts_repo = StaticContactsRepo([_make_contact()])
    if allowlist is None:
        allowlist = _make_allowlist()
    if active_hours is None:
        active_hours = _make_active_hours()
    if rate_limiter is None:
        rate_limiter = _make_rate_limiter()
    if history is None:
        history = InMemoryHistory()
    if llm is None:
        llm = ScriptedLLMProvider(
            [LLMResponse(text="respuesta por defecto", tool_calls=[])]
        )
    if tool_registry is None:
        tool_registry = ToolRegistry()
    if messaging is None:
        messaging = RecordingMessagingGateway()
    if schema_doc_loader is None:
        schema_doc_loader = lambda: "fake schema"
    if delay_fn is None:
        delay_fn = _noop_delay
    if now_fn is None:
        now_fn = lambda: _MIDDAY_SALTA

    return AgentTurn(
        allowlist=allowlist,
        active_hours=active_hours,
        rate_limiter=rate_limiter,
        history=history,
        contacts=contacts_repo,
        llm=llm,
        tool_registry=tool_registry,
        messaging=messaging,
        schema_doc_loader=schema_doc_loader,
        delay_fn=delay_fn,
        max_tool_iterations=max_tool_iterations,
        now_fn=now_fn,
    )


# ---------------------------------------------------------------------------
# T-060 Tests — AgentTurn pipeline
# ---------------------------------------------------------------------------


class TestAgentTurnAllowlistGuard:
    """JID not in allowlist → no LLM call, no message sent (RF-001)."""

    def test_unknown_jid_no_llm_call(self):
        llm = ScriptedLLMProvider([])
        messaging = RecordingMessagingGateway()
        agent = _make_agent(
            allowlist=_make_allowlist(jids=[_KNOWN_JID]),
            llm=llm,
            messaging=messaging,
        )

        agent.handle_incoming(_UNKNOWN_JID, "hola", ts=time.time())

        assert len(llm.calls) == 0
        assert len(messaging.sent) == 0

    def test_unknown_jid_does_not_raise(self):
        agent = _make_agent(allowlist=_make_allowlist(jids=[_KNOWN_JID]))
        # Should be a silent drop — no exception
        agent.handle_incoming(_UNKNOWN_JID, "hola", ts=time.time())


class TestAgentTurnActiveHours:
    """Outside active hours → no reply (RF-042)."""

    def test_outside_active_hours_no_message_sent(self):
        # Inject night-time (23:30 Salta) so the 07:00-22:00 guard blocks the message
        messaging = RecordingMessagingGateway()
        llm = ScriptedLLMProvider([])

        agent = _make_agent(
            active_hours=_make_active_hours(start="07:00", end="22:00"),
            llm=llm,
            messaging=messaging,
            now_fn=lambda: _NIGHT_SALTA,
        )

        agent.handle_incoming(_KNOWN_JID, "hola", ts=time.time())

        assert len(messaging.sent) == 0
        assert len(llm.calls) == 0


class TestAgentTurnRateLimit:
    """Rate limit exceeded → no reply (RF-041)."""

    def test_rate_limit_exceeded_no_message_sent(self):
        messaging = RecordingMessagingGateway()
        llm = ScriptedLLMProvider(
            [LLMResponse(text="respuesta", tool_calls=[]) for _ in range(5)]
        )
        # Limit of 0 means always blocked
        rate_limiter = _make_rate_limiter(limit=0)

        agent = _make_agent(
            rate_limiter=rate_limiter,
            llm=llm,
            messaging=messaging,
        )

        agent.handle_incoming(_KNOWN_JID, "consulta", ts=time.time())

        assert len(messaging.sent) == 0
        assert len(llm.calls) == 0


class TestAgentTurnTextOnlyReply:
    """LLM returns text-only → tool_registry not called, send_text invoked once."""

    def test_text_only_response_sends_once(self):
        expected_text = "Acá están las ventas del cliente 123."
        llm = ScriptedLLMProvider(
            [LLMResponse(text=expected_text, tool_calls=[])]
        )
        messaging = RecordingMessagingGateway()
        registry = ToolRegistry()  # empty — should not be called

        agent = _make_agent(llm=llm, messaging=messaging, tool_registry=registry)

        agent.handle_incoming(_KNOWN_JID, "dame ventas", ts=time.time())

        assert len(messaging.sent) == 1
        assert messaging.sent[0] == (_KNOWN_JID, expected_text)

    def test_text_only_response_llm_called_exactly_once(self):
        llm = ScriptedLLMProvider(
            [LLMResponse(text="ok", tool_calls=[])]
        )
        agent = _make_agent(llm=llm)

        agent.handle_incoming(_KNOWN_JID, "consulta", ts=time.time())

        assert len(llm.calls) == 1


class TestAgentTurnToolCall:
    """LLM returns tool_call → tool executed, result fed back, LLM called again, send_text once."""

    def test_tool_call_flow(self):
        rows = [{"id_cliente": 123, "venta": 500}]
        db_gateway = InMemoryDatabaseGateway(rows=rows)

        registry = _make_registry_with_tool(
            name="get_ventas_cliente",
            return_value={"rows": rows, "row_count": 1, "truncated": False},
        )

        tool_call_response = LLMResponse(
            text=None,
            tool_calls=[
                LLMToolCall(
                    id="call_1",
                    name="get_ventas_cliente",
                    arguments={"id_cliente": 123},
                )
            ],
        )
        final_text = "El cliente 123 tuvo 1 venta."
        text_response = LLMResponse(text=final_text, tool_calls=[])

        llm = ScriptedLLMProvider([tool_call_response, text_response])
        messaging = RecordingMessagingGateway()

        agent = _make_agent(
            llm=llm,
            tool_registry=registry,
            messaging=messaging,
        )

        agent.handle_incoming(_KNOWN_JID, "cuántas ventas tuvo el 123?", ts=time.time())

        # LLM called twice: first with tool_call, then after tool result
        assert len(llm.calls) == 2
        # send_text called once with the final text
        assert len(messaging.sent) == 1
        assert messaging.sent[0] == (_KNOWN_JID, final_text)

    def test_tool_result_fed_into_second_llm_call(self):
        """The second LLM call must include the tool result in its messages."""
        registry = _make_registry_with_tool(
            name="echo_tool",
            return_value={"echo": "pong"},
        )
        tool_call_response = LLMResponse(
            text=None,
            tool_calls=[
                LLMToolCall(id="c1", name="echo_tool", arguments={})
            ],
        )
        text_response = LLMResponse(text="done", tool_calls=[])
        llm = ScriptedLLMProvider([tool_call_response, text_response])

        agent = _make_agent(llm=llm, tool_registry=registry)
        agent.handle_incoming(_KNOWN_JID, "test", ts=time.time())

        # Second call's messages should contain the tool result
        second_call_messages = llm.calls[1][0]  # (messages, tools, system_prompt)
        roles = [m.role for m in second_call_messages]
        assert "tool" in roles


class TestAgentTurnToolError:
    """Tool execution error → LLM gets error message in tool result, can retry or apologize."""

    def test_tool_error_propagated_to_llm(self):
        """When a tool raises, the LLM still receives an error message."""
        registry = _make_registry_with_tool(
            name="broken_tool",
            raises=RuntimeError("DB connection timeout"),
        )

        tool_call_response = LLMResponse(
            text=None,
            tool_calls=[
                LLMToolCall(id="c1", name="broken_tool", arguments={})
            ],
        )
        apology = LLMResponse(text="Lo siento, no pude obtener los datos.", tool_calls=[])
        llm = ScriptedLLMProvider([tool_call_response, apology])
        messaging = RecordingMessagingGateway()

        agent = _make_agent(llm=llm, tool_registry=registry, messaging=messaging)
        agent.handle_incoming(_KNOWN_JID, "consulta", ts=time.time())

        # LLM should have been called twice (once for tool, once after error)
        assert len(llm.calls) == 2
        # Error result must be in the second LLM call's messages
        second_messages = llm.calls[1][0]
        tool_msgs = [m for m in second_messages if m.role == "tool"]
        assert len(tool_msgs) >= 1
        # The tool message content should contain an error indicator
        assert "error" in tool_msgs[0].content.lower() or "broken_tool" in tool_msgs[0].content

    def test_tool_error_still_sends_reply(self):
        """Even after a tool error, the LLM gets to produce a final reply."""
        registry = _make_registry_with_tool(
            name="broken",
            raises=ValueError("bad input"),
        )
        tool_call_response = LLMResponse(
            text=None,
            tool_calls=[LLMToolCall(id="c1", name="broken", arguments={})],
        )
        apology = LLMResponse(text="Hubo un error al procesar.", tool_calls=[])
        llm = ScriptedLLMProvider([tool_call_response, apology])
        messaging = RecordingMessagingGateway()

        agent = _make_agent(llm=llm, tool_registry=registry, messaging=messaging)
        agent.handle_incoming(_KNOWN_JID, "consulta", ts=time.time())

        assert len(messaging.sent) == 1
        assert "error" in messaging.sent[0][1].lower() or len(messaging.sent[0][1]) > 0


class TestAgentTurnMaxIterations:
    """Max iterations exceeded (LLM keeps calling tools) → safe break, send fallback."""

    def test_max_iterations_sends_fallback(self):
        """When LLM always emits tool_calls, the agent must break after max_tool_iterations."""
        registry = _make_registry_with_tool(
            name="looping_tool",
            return_value={"ok": True},
        )
        # LLM always returns another tool call (never text)
        tool_call = LLMResponse(
            text=None,
            tool_calls=[LLMToolCall(id="c1", name="looping_tool", arguments={})],
        )
        llm = ScriptedLLMProvider([tool_call] * 10)
        messaging = RecordingMessagingGateway()

        agent = _make_agent(
            llm=llm,
            tool_registry=registry,
            messaging=messaging,
            max_tool_iterations=3,
        )

        agent.handle_incoming(_KNOWN_JID, "consulta", ts=time.time())

        # Must have stopped and sent exactly one fallback message
        assert len(messaging.sent) == 1
        # LLM was called at most max_tool_iterations times
        assert len(llm.calls) <= 3 + 1  # +1 possible for final text attempt

    def test_max_iterations_fallback_message_non_empty(self):
        """The fallback message sent after max iterations must be non-empty."""
        registry = _make_registry_with_tool(
            name="loop",
            return_value={"ok": True},
        )
        tool_call = LLMResponse(
            text=None,
            tool_calls=[LLMToolCall(id="c1", name="loop", arguments={})],
        )
        llm = ScriptedLLMProvider([tool_call] * 10)
        messaging = RecordingMessagingGateway()

        agent = _make_agent(
            llm=llm,
            tool_registry=registry,
            messaging=messaging,
            max_tool_iterations=2,
        )

        agent.handle_incoming(_KNOWN_JID, "loop forever", ts=time.time())

        sent_text = messaging.sent[0][1]
        assert len(sent_text.strip()) > 0


class TestAgentTurnEmptyTextReply:
    """Empty text reply → don't send (avoid empty WhatsApp message)."""

    def test_empty_text_not_sent(self):
        llm = ScriptedLLMProvider(
            [LLMResponse(text="", tool_calls=[])]
        )
        messaging = RecordingMessagingGateway()

        agent = _make_agent(llm=llm, messaging=messaging)
        agent.handle_incoming(_KNOWN_JID, "hola", ts=time.time())

        assert len(messaging.sent) == 0

    def test_whitespace_only_text_not_sent(self):
        llm = ScriptedLLMProvider(
            [LLMResponse(text="   \n  ", tool_calls=[])]
        )
        messaging = RecordingMessagingGateway()

        agent = _make_agent(llm=llm, messaging=messaging)
        agent.handle_incoming(_KNOWN_JID, "hola", ts=time.time())

        assert len(messaging.sent) == 0

    def test_none_text_not_sent(self):
        # If LLM returns text=None with no tool_calls, don't send
        llm = ScriptedLLMProvider(
            [LLMResponse(text=None, tool_calls=[])]
        )
        messaging = RecordingMessagingGateway()

        agent = _make_agent(llm=llm, messaging=messaging)
        agent.handle_incoming(_KNOWN_JID, "hola", ts=time.time())

        assert len(messaging.sent) == 0


class TestAgentTurnHistoryTracking:
    """History is updated with user message and assistant reply."""

    def test_user_message_appended_to_history(self):
        history = InMemoryHistory()
        llm = ScriptedLLMProvider([LLMResponse(text="reply", tool_calls=[])])

        agent = _make_agent(llm=llm, history=history)
        agent.handle_incoming(_KNOWN_JID, "pregunta", ts=time.time())

        msgs = history.get(_KNOWN_JID)
        user_msgs = [m for m in msgs if m.role == "user"]
        assert len(user_msgs) >= 1
        assert user_msgs[0].content == "pregunta"

    def test_assistant_reply_appended_to_history(self):
        history = InMemoryHistory()
        expected_reply = "Acá está tu respuesta."
        llm = ScriptedLLMProvider([LLMResponse(text=expected_reply, tool_calls=[])])

        agent = _make_agent(llm=llm, history=history)
        agent.handle_incoming(_KNOWN_JID, "pregunta", ts=time.time())

        msgs = history.get(_KNOWN_JID)
        assistant_msgs = [m for m in msgs if m.role == "assistant"]
        assert len(assistant_msgs) >= 1
        assert assistant_msgs[0].content == expected_reply


class TestAgentTurnDelayInjection:
    """delay_fn is called before send_text (RF-040 injectable)."""

    def test_delay_fn_called(self):
        delay_calls = []

        def recording_delay():
            delay_calls.append(1)

        llm = ScriptedLLMProvider([LLMResponse(text="reply", tool_calls=[])])
        agent = _make_agent(llm=llm, delay_fn=recording_delay)
        agent.handle_incoming(_KNOWN_JID, "hola", ts=time.time())

        assert len(delay_calls) == 1

    def test_delay_fn_not_called_when_no_send(self):
        """delay_fn must NOT be called if no message is sent (e.g. empty reply)."""
        delay_calls = []

        def recording_delay():
            delay_calls.append(1)

        llm = ScriptedLLMProvider([LLMResponse(text="", tool_calls=[])])
        agent = _make_agent(llm=llm, delay_fn=recording_delay)
        agent.handle_incoming(_KNOWN_JID, "hola", ts=time.time())

        assert len(delay_calls) == 0


class TestAgentTurnSystemPrompt:
    """System prompt is built with schema_doc_loader and passed to LLM."""

    def test_system_prompt_passed_to_llm(self):
        schema_content = "gold schema content"
        llm = ScriptedLLMProvider([LLMResponse(text="ok", tool_calls=[])])

        agent = _make_agent(
            llm=llm,
            schema_doc_loader=lambda: schema_content,
        )
        agent.handle_incoming(_KNOWN_JID, "consulta", ts=time.time())

        # The system_prompt arg passed to llm.generate must contain schema content
        system_prompt = llm.calls[0][2]  # (messages, tools, system_prompt)
        assert schema_content in system_prompt


class TestAgentTurnNoSrcImports:
    """bd_agent/agent.py must have zero imports from src.* (RF-070)."""

    def test_no_src_imports(self):
        import ast
        import pathlib

        agent_path = pathlib.Path(__file__).parent.parent.parent / "bd_agent" / "agent.py"
        source = agent_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith("src."):
                        violations.append(node.module)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("src."):
                            violations.append(alias.name)

        assert violations == [], f"Forbidden src.* imports found: {violations}"


# ---------------------------------------------------------------------------
# T-061 Integration test — full happy-path with realistic fakes
# ---------------------------------------------------------------------------


class TestAgentTurnHappyPathIntegration:
    """T-061: User asks about ventas, LLM calls tool, tool returns rows, LLM summarizes."""

    def test_full_happy_path(self):
        """
        User: "cuántas ventas tuvo el cliente 123 en mayo?"
        LLM emits: get_ventas_cliente(id_cliente=123, periodo="2026-05")
        FakeDatabaseGateway returns 5 rows
        LLM produces: "Tuvo 5 ventas..."
        send_text called with that summary
        """
        # Build registry with the curated tool wired to a fake DB gateway
        rows = [
            {"fecha": "2026-05-01", "monto": 1000},
            {"fecha": "2026-05-02", "monto": 2000},
            {"fecha": "2026-05-10", "monto": 1500},
            {"fecha": "2026-05-15", "monto": 800},
            {"fecha": "2026-05-20", "monto": 3200},
        ]
        db_gateway = InMemoryDatabaseGateway(rows=rows)

        registry = ToolRegistry()
        registry.register(
            name="get_ventas_cliente",
            description="Ventas de un cliente en un período",
            params_schema={
                "type": "object",
                "properties": {
                    "id_cliente": {"type": "integer"},
                    "periodo": {"type": "string"},
                },
                "required": ["id_cliente", "periodo"],
            },
            handler=lambda gateway, **kwargs: {
                "rows": rows[:5],
                "row_count": 5,
                "truncated": False,
            },
        )

        tool_call_response = LLMResponse(
            text=None,
            tool_calls=[
                LLMToolCall(
                    id="call_abc",
                    name="get_ventas_cliente",
                    arguments={"id_cliente": 123, "periodo": "2026-05"},
                )
            ],
        )
        summary_text = "Tuvo 5 ventas en mayo 2026 por un total de $8.500."
        final_response = LLMResponse(text=summary_text, tool_calls=[])

        llm = ScriptedLLMProvider([tool_call_response, final_response])
        messaging = RecordingMessagingGateway()
        history = InMemoryHistory()

        contacts_repo = StaticContactsRepo([_make_contact()])
        agent = _make_agent(
            contacts_repo=contacts_repo,
            llm=llm,
            tool_registry=registry,
            messaging=messaging,
            history=history,
            schema_doc_loader=lambda: "# Schema doc\nfact_ventas: ...",
        )

        agent.handle_incoming(
            _KNOWN_JID,
            "cuántas ventas tuvo el cliente 123 en mayo?",
            ts=1748304000.0,
        )

        # Assert: LLM was called twice (once for tool, once for final answer)
        assert len(llm.calls) == 2

        # Assert: send_text was called exactly once with the summary
        assert len(messaging.sent) == 1
        jid_sent, text_sent = messaging.sent[0]
        assert jid_sent == _KNOWN_JID
        assert text_sent == summary_text

        # Assert: tool call arguments were passed correctly (visible in LLM call 2 messages)
        second_call_messages = llm.calls[1][0]
        tool_result_msgs = [m for m in second_call_messages if m.role == "tool"]
        assert len(tool_result_msgs) == 1
        payload = json.loads(tool_result_msgs[0].content)
        assert payload["row_count"] == 5

        # Assert: user message in history
        hist = history.get(_KNOWN_JID)
        user_msgs = [m for m in hist if m.role == "user"]
        assert len(user_msgs) >= 1

        # Assert: assistant reply in history
        assistant_msgs = [m for m in hist if m.role == "assistant"]
        assert len(assistant_msgs) >= 1
        assert assistant_msgs[-1].content == summary_text
