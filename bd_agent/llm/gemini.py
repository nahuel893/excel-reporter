"""bd_agent/llm/gemini.py — GeminiProvider implementing LLMProvider Protocol.

Uses the ``google-genai`` SDK (``google.genai``).  Reads ``GEMINI_API_KEY``
from the environment.  Implements naive 3x exponential backoff on 429 / 5xx.

Zero imports from src.* (RF-070).

Usage::

    provider = GeminiProvider()
    result = provider.generate(
        messages=[LLMMessage(role="user", content="dame ventas de hoy")],
        tools=[...],            # Gemini function-declaration dicts from ToolRegistry
        system_prompt="...",
    )
"""
from __future__ import annotations

import os
import time
from typing import Any

from google import genai
from google.genai import errors, types

from bd_agent.llm.provider import LLMMessage, LLMResponse, LLMToolCall

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "gemini-2.0-flash-lite"

# HTTP status codes that are considered transient and eligible for retry
_RETRYABLE_CODES = {429, 500, 502, 503, 504}

# Backoff parameters: initial wait 1s, multiplier 2, max 3 retries
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MULTIPLIER = 2.0
_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Message conversion helpers
# ---------------------------------------------------------------------------


def _to_gemini_role(role: str) -> str:
    """Map LLMMessage role to Gemini API role string."""
    if role in ("user", "tool"):
        return "user"
    if role == "assistant":
        return "model"
    # system role is handled via system_instruction, not in contents
    return "user"


def _messages_to_contents(messages: list[LLMMessage]) -> list[types.Content]:
    """Convert a list of LLMMessage objects to Gemini Content objects.

    Gemini API roles are either "user" or "model".  Tool responses are
    represented as function_response parts in a "user" role turn.
    """
    contents: list[types.Content] = []

    for msg in messages:
        if msg.role == "tool":
            # Tool result: send as FunctionResponse part
            import json

            try:
                response_data = json.loads(msg.content)
            except (json.JSONDecodeError, TypeError):
                response_data = {"result": msg.content}

            part = types.Part.from_function_response(
                name=msg.tool_name or "unknown_tool",
                response=response_data,
            )
            contents.append(types.Content(role="user", parts=[part]))
        elif msg.role == "assistant" and msg.tool_call_id:
            # Assistant turn that was a tool call request; skip (already handled)
            pass
        else:
            gemini_role = _to_gemini_role(msg.role)
            part = types.Part(text=msg.content)
            contents.append(types.Content(role=gemini_role, parts=[part]))

    return contents


def _parse_tool_calls(response: types.GenerateContentResponse) -> list[LLMToolCall]:
    """Extract tool calls from a Gemini response."""
    raw_calls = response.function_calls
    if not raw_calls:
        return []

    tool_calls: list[LLMToolCall] = []
    for fc in raw_calls:
        tool_calls.append(
            LLMToolCall(
                id=getattr(fc, "id", None) or f"call_{fc.name}",
                name=fc.name,
                arguments=dict(fc.args) if fc.args else {},
            )
        )
    return tool_calls


def _parse_usage(response: types.GenerateContentResponse) -> dict[str, int] | None:
    """Extract token usage from a Gemini response, or None if not available."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None

    prompt = getattr(meta, "prompt_token_count", 0) or 0
    candidates = getattr(meta, "candidates_token_count", 0) or 0
    total = getattr(meta, "total_token_count", None)
    if total is None:
        total = prompt + candidates

    return {
        "prompt_tokens": prompt,
        "completion_tokens": candidates,
        "total_tokens": total,
    }


# ---------------------------------------------------------------------------
# GeminiProvider
# ---------------------------------------------------------------------------


class GeminiProvider:
    """LLMProvider implementation backed by Google Gemini Flash Lite.

    Attributes:
        model: Gemini model ID (default: ``gemini-2.0-flash-lite``).
        max_retries: Maximum number of retries on transient errors (default: 3).

    Raises:
        EnvironmentError: If ``GEMINI_API_KEY`` is not set at construction time.
    """

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY environment variable is required but not set. "
                "Set it before instantiating GeminiProvider."
            )

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # LLMProvider Protocol implementation
    # ------------------------------------------------------------------

    def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None,
        system_prompt: str,
    ) -> LLMResponse:
        """Call the Gemini API and return text or tool calls.

        Args:
            messages: Ordered conversation history.
            tools: Gemini-format function declarations from ToolRegistry, or None.
            system_prompt: System instruction sent to the model.

        Returns:
            LLMResponse with text or tool_calls populated.

        Raises:
            google.genai.errors.APIError: After exhausting retries on transient
                errors, or immediately on non-retryable errors (400, 401, etc.).
        """
        contents = _messages_to_contents(messages)

        # Build the tools config
        gemini_tools = None
        if tools:
            from google.genai.types import FunctionDeclaration

            func_decls = [
                FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=t.get("parameters"),
                )
                for t in tools
            ]
            gemini_tools = types.Tool(function_declarations=func_decls)

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[gemini_tools] if gemini_tools else None,
        )

        return self._call_with_retry(contents=contents, config=config)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_with_retry(
        self,
        *,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> LLMResponse:
        """Execute the API call with exponential backoff on transient errors.

        Retries up to ``self._max_retries`` times on 429 / 5xx status codes.
        Non-retryable errors (4xx except 429) are re-raised immediately.
        """
        last_exc: Exception | None = None
        delay = _BACKOFF_BASE_SECONDS

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=config,
                )
                return self._parse_response(response)

            except errors.APIError as exc:
                if exc.code not in _RETRYABLE_CODES:
                    # Non-retryable: bad request, auth error, etc.
                    raise

                last_exc = exc
                if attempt < self._max_retries:
                    time.sleep(delay)
                    delay *= _BACKOFF_MULTIPLIER

        # Exhausted retries
        raise last_exc  # type: ignore[misc]

    def _parse_response(
        self, response: types.GenerateContentResponse
    ) -> LLMResponse:
        """Convert a Gemini SDK response into our LLMResponse type."""
        tool_calls = _parse_tool_calls(response)
        usage = _parse_usage(response)

        if tool_calls:
            text = None
        else:
            text = getattr(response, "text", None)

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            usage=usage,
        )
