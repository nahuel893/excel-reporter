"""T-011: Tests for bd_agent/contracts.py — Protocols + dataclasses.

Verifies:
- Contact, Message, ToolCall, ToolResult, LLMResponse are frozen dataclasses
- DatabaseGateway, MessagingGateway, ContactsRepo, LLMProvider are runtime_checkable Protocols
- Protocols accept MagicMock (duck typing satisfied)
- Immutability constraints
- Role literals and type safety
"""
import pytest
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock
from datetime import datetime


# ---------------------------------------------------------------------------
# Contact
# ---------------------------------------------------------------------------

class TestContact:
    def test_contact_is_frozen_dataclass(self):
        """Mutation raises FrozenInstanceError."""
        from bd_agent.contracts import Contact
        c = Contact(
            name="Walter Vilte",
            jid="5493870000001@s.whatsapp.net",
            daily_message_limit=100,
            permissions=("ventas", "clientes"),
        )
        with pytest.raises(FrozenInstanceError):
            c.name = "other"  # type: ignore[misc]

    def test_contact_permissions_is_tuple(self):
        from bd_agent.contracts import Contact
        c = Contact(
            name="Test",
            jid="5493870000001@s.whatsapp.net",
            daily_message_limit=10,
            permissions=("ventas",),
        )
        assert isinstance(c.permissions, tuple)


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class TestMessage:
    def test_message_is_frozen_dataclass(self):
        from bd_agent.contracts import Message
        m = Message(role="user", content="hola")
        with pytest.raises(FrozenInstanceError):
            m.content = "other"  # type: ignore[misc]

    def test_message_role_literals(self):
        """Only allowed roles: system, user, assistant, tool."""
        from bd_agent.contracts import Message
        for role in ("system", "user", "assistant", "tool"):
            m = Message(role=role, content="x")  # type: ignore[arg-type]
            assert m.role == role

    def test_message_has_created_at_default(self):
        from bd_agent.contracts import Message
        m = Message(role="user", content="test")
        assert isinstance(m.created_at, datetime)

    def test_message_optional_tool_fields_default_none(self):
        from bd_agent.contracts import Message
        m = Message(role="user", content="test")
        assert m.tool_call_id is None
        assert m.tool_name is None


# ---------------------------------------------------------------------------
# ToolCall
# ---------------------------------------------------------------------------

class TestToolCall:
    def test_toolcall_is_frozen_dataclass(self):
        from bd_agent.contracts import ToolCall
        tc = ToolCall(id="call-1", name="get_ventas_cliente", arguments={"id": 1})
        with pytest.raises(FrozenInstanceError):
            tc.name = "other"  # type: ignore[misc]

    def test_toolcall_arguments_is_dict(self):
        from bd_agent.contracts import ToolCall
        tc = ToolCall(id="call-1", name="test", arguments={"a": 1})
        assert isinstance(tc.arguments, dict)


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------

class TestToolResult:
    def test_toolresult_is_frozen_dataclass(self):
        from bd_agent.contracts import ToolResult
        tr = ToolResult(call_id="call-1", name="test", content="{}", is_error=False)
        with pytest.raises(FrozenInstanceError):
            tr.content = "other"  # type: ignore[misc]

    def test_toolresult_is_error_defaults_false(self):
        from bd_agent.contracts import ToolResult
        tr = ToolResult(call_id="call-1", name="test", content="{}")
        assert tr.is_error is False


# ---------------------------------------------------------------------------
# LLMResponse
# ---------------------------------------------------------------------------

class TestLLMResponse:
    def test_llmresponse_tool_calls_is_tuple(self):
        """tool_calls must be a tuple (immutable), not a list."""
        from bd_agent.contracts import LLMResponse, ToolCall
        tc = ToolCall(id="c1", name="t", arguments={})
        resp = LLMResponse(
            text=None,
            tool_calls=(tc,),
            finish_reason="tool_calls",
        )
        assert isinstance(resp.tool_calls, tuple)

    def test_llmresponse_is_frozen_dataclass(self):
        from bd_agent.contracts import LLMResponse
        resp = LLMResponse(text="hello", tool_calls=(), finish_reason="stop")
        with pytest.raises(FrozenInstanceError):
            resp.text = "other"  # type: ignore[misc]

    def test_llmresponse_token_counts_default_zero(self):
        from bd_agent.contracts import LLMResponse
        resp = LLMResponse(text="hi", tool_calls=(), finish_reason="stop")
        assert resp.usage_tokens_in == 0
        assert resp.usage_tokens_out == 0


# ---------------------------------------------------------------------------
# Protocols — runtime_checkable isinstance
# ---------------------------------------------------------------------------

class TestProtocols:
    """Verify that concrete classes satisfying Protocols pass isinstance checks.

    Python's runtime_checkable checks hasattr for each Protocol method.
    We use lightweight concrete fakes (not MagicMock) so the attr check works.
    """

    def test_database_gateway_protocol_satisfied_by_concrete(self):
        """A class with execute_select + get_schema_doc satisfies DatabaseGateway."""
        from bd_agent.contracts import DatabaseGateway

        class FakeDB:
            def execute_select(self, query, params, max_rows):
                return []

            def get_schema_doc(self):
                return ""

        assert isinstance(FakeDB(), DatabaseGateway)

    def test_messaging_gateway_protocol_satisfied_by_concrete(self):
        from bd_agent.contracts import MessagingGateway

        class FakeMsg:
            def send_text(self, jid, text):
                pass

            def send_file(self, jid, file_path, caption=None):
                pass

        assert isinstance(FakeMsg(), MessagingGateway)

    def test_contacts_repo_protocol_satisfied_by_concrete(self):
        from bd_agent.contracts import ContactsRepo

        class FakeRepo:
            def get(self, jid):
                return None

            def list_all(self):
                return []

            def reload(self):
                pass

        assert isinstance(FakeRepo(), ContactsRepo)

    def test_llm_provider_protocol_satisfied_by_concrete(self):
        from bd_agent.contracts import LLMProvider

        class FakeLLM:
            def complete(self, messages, tools, max_output_tokens=1024):
                from bd_agent.contracts import LLMResponse
                return LLMResponse(text="hi", tool_calls=(), finish_reason="stop")

        assert isinstance(FakeLLM(), LLMProvider)

    def test_database_gateway_missing_method_fails(self):
        """A class missing get_schema_doc does NOT satisfy DatabaseGateway."""
        from bd_agent.contracts import DatabaseGateway

        class IncompleteDB:
            def execute_select(self, query, params, max_rows):
                return []
            # missing get_schema_doc

        assert not isinstance(IncompleteDB(), DatabaseGateway)
