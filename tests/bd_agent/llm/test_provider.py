"""tests/bd_agent/llm/test_provider.py — Tests for LLMProvider Protocol contract + types.

Strict TDD: these tests are written BEFORE the implementation (RED phase).
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from bd_agent.contracts import LLMResponse, Message, ToolCall


# ---------------------------------------------------------------------------
# T-040: LLMProvider Protocol + types
# ---------------------------------------------------------------------------

class TestLLMResponseType:
    """LLMResponse dataclass structure (already in contracts.py, verify here)."""

    def test_text_only_response(self) -> None:
        resp = LLMResponse(
            text="Hola mundo",
            tool_calls=(),
            finish_reason="stop",
            usage_tokens_in=10,
            usage_tokens_out=5,
        )
        assert resp.text == "Hola mundo"
        assert resp.tool_calls == ()
        assert resp.finish_reason == "stop"
        assert resp.usage_tokens_in == 10
        assert resp.usage_tokens_out == 5

    def test_tool_call_response_has_no_text(self) -> None:
        call = ToolCall(id="call_1", name="get_ventas_cliente", arguments={"id": 1})
        resp = LLMResponse(
            text=None,
            tool_calls=(call,),
            finish_reason="tool_calls",
        )
        assert resp.text is None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_ventas_cliente"

    def test_defaults_zero_usage(self) -> None:
        resp = LLMResponse(text="ok", tool_calls=(), finish_reason="stop")
        assert resp.usage_tokens_in == 0
        assert resp.usage_tokens_out == 0

    def test_frozen_immutable(self) -> None:
        resp = LLMResponse(text="ok", tool_calls=(), finish_reason="stop")
        with pytest.raises((AttributeError, TypeError)):
            resp.text = "changed"  # type: ignore[misc]


class TestLLMProviderProtocol:
    """Verify LLMProvider Protocol is runtime_checkable and has the right signature."""

    def test_protocol_is_importable(self) -> None:
        from bd_agent.contracts import LLMProvider  # noqa: F401

    def test_protocol_is_runtime_checkable(self) -> None:
        from bd_agent.contracts import LLMProvider

        # A concrete class with complete() satisfies the protocol at runtime
        class HasComplete:
            def complete(self, messages, tools, max_output_tokens=1024):
                ...

        assert isinstance(HasComplete(), LLMProvider)

    def test_protocol_not_satisfied_without_complete(self) -> None:
        from bd_agent.contracts import LLMProvider

        class BadImpl:
            pass

        assert not isinstance(BadImpl(), LLMProvider)

    def test_complete_method_returns_llm_response(self) -> None:
        """A concrete mock implementing the protocol returns LLMResponse."""
        from bd_agent.contracts import LLMProvider

        class FakeLLM:
            def complete(
                self,
                messages: list[Message],
                tools: list[dict],
                max_output_tokens: int = 1024,
            ) -> LLMResponse:
                return LLMResponse(text="fake", tool_calls=(), finish_reason="stop")

        llm: LLMProvider = FakeLLM()
        msg = Message(role="user", content="dame ventas")
        result = llm.complete(messages=[msg], tools=[], max_output_tokens=512)
        assert isinstance(result, LLMResponse)
        assert result.text == "fake"

    def test_message_type_fields(self) -> None:
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.tool_call_id is None

    def test_tool_call_type_fields(self) -> None:
        tc = ToolCall(id="abc", name="run_sql_select", arguments={"query": "SELECT 1"})
        assert tc.id == "abc"
        assert tc.name == "run_sql_select"
        assert tc.arguments["query"] == "SELECT 1"

    def test_llm_provider_module_importable(self) -> None:
        """bd_agent.llm.provider must export LLMProvider, LLMResponse, LLMMessage, LLMToolCall."""
        from bd_agent.llm.provider import (  # noqa: F401
            LLMMessage,
            LLMProvider,
            LLMResponse,
            LLMToolCall,
        )

    def test_llm_message_has_required_fields(self) -> None:
        from bd_agent.llm.provider import LLMMessage

        msg = LLMMessage(role="user", content="hola")
        assert msg.role == "user"
        assert msg.content == "hola"

    def test_llm_tool_call_has_required_fields(self) -> None:
        from bd_agent.llm.provider import LLMToolCall

        tc = LLMToolCall(id="c1", name="get_ventas", arguments={"x": 1})
        assert tc.id == "c1"
        assert tc.name == "get_ventas"
        assert tc.arguments == {"x": 1}

    def test_llm_response_from_provider_module_text(self) -> None:
        from bd_agent.llm.provider import LLMResponse as ProviderLLMResponse

        resp = ProviderLLMResponse(text="ok", tool_calls=[], usage=None)
        assert resp.text == "ok"
        assert resp.tool_calls == []
        assert resp.usage is None

    def test_llm_response_from_provider_module_tool_calls(self) -> None:
        from bd_agent.llm.provider import LLMResponse as ProviderLLMResponse, LLMToolCall

        tc = LLMToolCall(id="c1", name="func", arguments={})
        resp = ProviderLLMResponse(text=None, tool_calls=[tc], usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        assert resp.text is None
        assert len(resp.tool_calls) == 1
        assert resp.usage["total_tokens"] == 15

    def test_llm_provider_protocol_from_provider_module(self) -> None:
        """LLMProvider from provider.py has generate() method (not complete())."""
        from bd_agent.llm.provider import LLMProvider, LLMMessage, LLMToolCall, LLMResponse

        class FakeProvider:
            def generate(
                self,
                messages: list[LLMMessage],
                tools: list[dict] | None,
                system_prompt: str,
            ) -> LLMResponse:
                return LLMResponse(text="ok", tool_calls=[], usage=None)

        assert isinstance(FakeProvider(), LLMProvider)

    def test_llm_provider_not_satisfied_without_generate(self) -> None:
        from bd_agent.llm.provider import LLMProvider

        class BadProvider:
            pass

        assert not isinstance(BadProvider(), LLMProvider)
