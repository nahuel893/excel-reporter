"""bd_agent/llm/opencode.py — OpenCodeProvider implementing LLMProvider Protocol.

OpenCode Go subscription (opencode.ai/zen/go/v1) exposes DeepSeek V4 Pro and
DeepSeek V4 Flash via an OpenAI-compatible /chat/completions endpoint with
function-calling support.

Reads ``OPENCODE_API_KEY`` from the environment. Auth is ``Authorization: Bearer``.

Zero imports from src.* (RF-070).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from bd_agent.llm.provider import LLMMessage, LLMResponse, LLMToolCall

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "deepseek-v4-flash"
_DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Format converters — Gemini-native ↔ OpenAI-compatible
# ---------------------------------------------------------------------------


def _convert_messages_to_openai(
    messages: list[LLMMessage], system_prompt: str
) -> list[dict]:
    """Convert internal LLMMessage list + system prompt to OpenAI message format.

    OpenAI/DeepSeek strict rules:
      - A `tool` message MUST be preceded by an `assistant` message with `tool_calls`.
      - The agent's loop emits assistant tool-call placeholders as
        LLMMessage(role="assistant", content="", tool_call_id=..., tool_name=...).
        We expand those into the OpenAI `tool_calls` shape here.
    """
    out: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in messages:
        if m.role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "content": m.content,
                }
            )
        elif m.role == "assistant" and m.tool_call_id:
            # Tool-call placeholder — expand to OpenAI tool_calls format.
            # Original arguments aren't preserved on LLMMessage; use empty obj.
            out.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": m.tool_call_id,
                            "type": "function",
                            "function": {
                                "name": m.tool_name or "",
                                "arguments": "{}",
                            },
                        }
                    ],
                }
            )
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def _convert_tools_to_openai(tools: list[dict] | None) -> list[dict] | None:
    """Wrap Gemini-format function declarations into OpenAI tools format.

    Gemini format:  {"name": ..., "description": ..., "parameters": {...}}
    OpenAI format:  {"type": "function", "function": {<gemini fields>}}
    """
    if not tools:
        return None
    return [{"type": "function", "function": fn} for fn in tools]


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class OpenCodeProvider:
    """OpenAI-compatible LLM provider backed by OpenCode Go (DeepSeek V4)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("OPENCODE_API_KEY")
        if not key:
            raise EnvironmentError(
                "OPENCODE_API_KEY is not set. Get one from your OpenCode Go subscription."
            )
        self._api_key = key
        self._base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._model = model or _DEFAULT_MODEL
        self._timeout = timeout_seconds
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None,
        system_prompt: str,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": _convert_messages_to_openai(messages, system_prompt),
            # DeepSeek V4 default es thinking-mode (devuelve reasoning_content que rompe
            # multi-turn). Top-level `thinking: disabled` lo desactiva. NOTA: `extra_body`
            # de la doc oficial es para el Python SDK; el endpoint REST espera top-level.
            "thinking": {"type": "disabled"},
        }
        openai_tools = _convert_tools_to_openai(tools)
        if openai_tools:
            body["tools"] = openai_tools
            body["tool_choice"] = "auto"

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise

            if response.status_code == 200:
                return _parse_response(response.json())

            if response.status_code in _RETRYABLE_CODES and attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue

            # Log body antes de raise para diagnostico
            if response.status_code >= 400:
                import logging as _logging
                _logging.getLogger("bd_agent.llm.opencode").error(
                    "OpenCode HTTP %d. Body: %s", response.status_code, response.text[:1000]
                )
            response.raise_for_status()

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("OpenCode request failed with no response")


def _parse_response(data: dict) -> LLMResponse:
    """Parse OpenAI-compatible response into LLMResponse."""
    choices = data.get("choices") or []
    if not choices:
        return LLMResponse(text=None, tool_calls=[], usage=_extract_usage(data))

    msg = choices[0].get("message") or {}
    text = msg.get("content")

    tool_calls_raw = msg.get("tool_calls") or []
    tool_calls: list[LLMToolCall] = []
    for tc in tool_calls_raw:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(
            LLMToolCall(
                id=tc.get("id") or "",
                name=fn.get("name") or "",
                arguments=args,
            )
        )

    return LLMResponse(
        text=text if (text and text.strip()) else None,
        tool_calls=tool_calls,
        usage=_extract_usage(data),
    )


def _extract_usage(data: dict) -> dict[str, int] | None:
    """Extract token usage from OpenAI-format response."""
    usage = data.get("usage")
    if not usage:
        return None
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
        "completion_tokens": int(usage.get("completion_tokens", 0)),
        "total_tokens": int(usage.get("total_tokens", 0)),
    }
