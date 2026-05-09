"""Tests for bd_agent/llm/opencode.py — OpenCodeProvider."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import httpx
import pytest

from bd_agent.llm.opencode import (
    OpenCodeProvider,
    _convert_messages_to_openai,
    _convert_tools_to_openai,
    _parse_response,
)
from bd_agent.llm.provider import LLMMessage


# ---------------------------------------------------------------------------
# Format converter tests
# ---------------------------------------------------------------------------


class TestConvertMessages:
    def test_empty_messages_only_system(self):
        out = _convert_messages_to_openai([], "you are X")
        assert out == [{"role": "system", "content": "you are X"}]

    def test_user_and_assistant(self):
        msgs = [
            LLMMessage(role="user", content="hi"),
            LLMMessage(role="assistant", content="hello!"),
        ]
        out = _convert_messages_to_openai(msgs, "sys")
        assert out == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
        ]

    def test_tool_message_includes_id_and_content(self):
        msgs = [
            LLMMessage(
                role="tool",
                content='{"ok": true}',
                tool_call_id="call_xyz",
                tool_name="get_ventas_cliente",
            )
        ]
        out = _convert_messages_to_openai(msgs, "sys")
        # OpenAI/DeepSeek tool messages: only tool_call_id + content (NO name field)
        assert out[1] == {
            "role": "tool",
            "tool_call_id": "call_xyz",
            "content": '{"ok": true}',
        }

    def test_assistant_tool_call_placeholder_expands_to_tool_calls(self):
        """An assistant LLMMessage with tool_call_id is a placeholder for a tool-call turn.

        DeepSeek requires this to be expanded into OpenAI's tool_calls format so the
        following `tool` message has a valid preceding context.
        """
        msgs = [
            LLMMessage(role="user", content="dame ventas"),
            LLMMessage(
                role="assistant",
                content="",
                tool_call_id="call_abc",
                tool_name="get_ventas_cliente",
            ),
            LLMMessage(
                role="tool",
                content='{"rows": [...]}',
                tool_call_id="call_abc",
                tool_name="get_ventas_cliente",
            ),
        ]
        out = _convert_messages_to_openai(msgs, "sys")
        assert out[2] == {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {
                        "name": "get_ventas_cliente",
                        "arguments": "{}",
                    },
                }
            ],
        }
        assert out[3] == {
            "role": "tool",
            "tool_call_id": "call_abc",
            "content": '{"rows": [...]}',
        }


class TestConvertTools:
    def test_none_returns_none(self):
        assert _convert_tools_to_openai(None) is None

    def test_empty_list_returns_none(self):
        assert _convert_tools_to_openai([]) is None

    def test_wraps_with_function_envelope(self):
        gemini_fn = {
            "name": "get_clientes_sucursal",
            "description": "Trae clientes",
            "parameters": {"type": "object", "properties": {"id_sucursal": {"type": "integer"}}},
        }
        out = _convert_tools_to_openai([gemini_fn])
        assert out == [{"type": "function", "function": gemini_fn}]


# ---------------------------------------------------------------------------
# Response parser tests
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_text_only_response(self):
        data = {
            "choices": [{"message": {"content": "Hola Nahuel!"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
        }
        r = _parse_response(data)
        assert r.text == "Hola Nahuel!"
        assert r.tool_calls == []
        assert r.usage == {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}

    def test_tool_call_response(self):
        data = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "get_ventas_cliente",
                                    "arguments": '{"id_cliente": 123, "periodo": "2026-04"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }
        r = _parse_response(data)
        assert r.text is None
        assert len(r.tool_calls) == 1
        tc = r.tool_calls[0]
        assert tc.id == "call_1"
        assert tc.name == "get_ventas_cliente"
        assert tc.arguments == {"id_cliente": 123, "periodo": "2026-04"}

    def test_empty_text_treated_as_none(self):
        data = {"choices": [{"message": {"content": "   "}}]}
        r = _parse_response(data)
        assert r.text is None

    def test_malformed_arguments_default_to_empty_dict(self):
        data = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "x",
                                "function": {"name": "f", "arguments": "not json"},
                            }
                        ]
                    }
                }
            ]
        }
        r = _parse_response(data)
        assert r.tool_calls[0].arguments == {}

    def test_no_choices_returns_empty(self):
        r = _parse_response({"choices": []})
        assert r.text is None
        assert r.tool_calls == []


# ---------------------------------------------------------------------------
# OpenCodeProvider tests
# ---------------------------------------------------------------------------


class TestOpenCodeProvider:
    def test_init_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="OPENCODE_API_KEY"):
            OpenCodeProvider()

    def test_init_uses_explicit_api_key(self):
        client = MagicMock(spec=httpx.Client)
        p = OpenCodeProvider(api_key="explicit-key", client=client)
        assert p._api_key == "explicit-key"
        assert p._model == "deepseek-v4-flash"

    def test_init_uses_env_when_no_explicit_key(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "from-env")
        p = OpenCodeProvider(client=MagicMock())
        assert p._api_key == "from-env"

    def test_generate_text_only(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": "respuesta"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        }
        client.post.return_value = response

        p = OpenCodeProvider(api_key="k", client=client)
        result = p.generate(
            messages=[LLMMessage(role="user", content="hi")],
            tools=None,
            system_prompt="you are X",
        )

        assert result.text == "respuesta"
        assert result.tool_calls == []
        client.post.assert_called_once()
        call = client.post.call_args
        assert call.args[0] == "https://opencode.ai/zen/go/v1/chat/completions"
        body = call.kwargs["json"]
        assert body["model"] == "deepseek-v4-flash"
        assert body["messages"][0] == {"role": "system", "content": "you are X"}
        assert "tools" not in body
        headers = call.kwargs["headers"]
        assert headers["Authorization"] == "Bearer k"

    def test_generate_with_tools(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        client.post.return_value = response

        p = OpenCodeProvider(api_key="k", client=client)
        tools = [{"name": "f", "description": "d", "parameters": {"type": "object"}}]
        p.generate(messages=[], tools=tools, system_prompt="s")

        body = client.post.call_args.kwargs["json"]
        assert body["tools"] == [{"type": "function", "function": tools[0]}]
        assert body["tool_choice"] == "auto"

    def test_retry_on_429(self):
        client = MagicMock(spec=httpx.Client)
        # First response: 429. Second: 200.
        bad = MagicMock(status_code=429)
        good = MagicMock(status_code=200)
        good.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        client.post.side_effect = [bad, good]

        p = OpenCodeProvider(api_key="k", client=client)
        # Patch sleep to avoid actual delay
        import bd_agent.llm.opencode as opencode_mod
        original_sleep = opencode_mod.time.sleep
        opencode_mod.time.sleep = lambda _: None
        try:
            result = p.generate(messages=[], tools=None, system_prompt="s")
        finally:
            opencode_mod.time.sleep = original_sleep

        assert result.text == "ok"
        assert client.post.call_count == 2

    def test_no_retry_on_400(self):
        client = MagicMock(spec=httpx.Client)
        bad = MagicMock(status_code=400)
        bad.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=bad
        )
        client.post.return_value = bad

        p = OpenCodeProvider(api_key="k", client=client)
        with pytest.raises(httpx.HTTPStatusError):
            p.generate(messages=[], tools=None, system_prompt="s")

        assert client.post.call_count == 1
