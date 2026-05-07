"""bd_agent/llm/provider.py — LLMProvider Protocol + message/response types.

This module defines the public interface that all LLM implementations must
satisfy.  It intentionally has no imports from src.* and no dependency on
any specific LLM SDK (RF-070).

Types:
    LLMMessage  — a single message in a conversation turn (role + content)
    LLMToolCall — a tool call emitted by the LLM (id, name, arguments)
    LLMResponse — the LLM output (text | tool_calls, optional usage dict)
    LLMProvider — Protocol that all LLM implementations must satisfy

Design note:
    This module defines its *own* lightweight types rather than re-using the
    domain-level Message / ToolCall / LLMResponse from bd_agent.contracts so
    that the LLM layer can evolve independently.  The orchestrator is
    responsible for mapping between the two type sets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass
class LLMMessage:
    """A single message in a conversation.

    Attributes:
        role: One of "system", "user", "assistant", "tool".
        content: Text content of the message.
        tool_call_id: For role=="tool" responses, the id of the preceding call.
        tool_name: For role=="tool" responses, the name of the called tool.
    """

    role: str
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass
class LLMToolCall:
    """A tool / function call emitted by the LLM.

    Attributes:
        id: Unique identifier for this call (from the LLM response).
        name: The function/tool name to invoke.
        arguments: Dict of argument name → value as parsed from the LLM output.
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Response from an LLM provider.

    Attributes:
        text: Final reply text.  None when tool_calls is non-empty.
        tool_calls: List of tool calls requested by the LLM.  Empty when
            the LLM produced a textual reply.
        usage: Optional token-usage dict with keys:
            ``prompt_tokens``, ``completion_tokens``, ``total_tokens``.
            None when the provider does not report usage.
    """

    text: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    usage: dict[str, int] | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for tool-calling LLM providers.

    Any class that implements ``generate()`` with this signature satisfies
    the protocol at runtime (runtime_checkable).

    Usage::

        provider: LLMProvider = GeminiProvider(api_key=...)
        response = provider.generate(
            messages=[LLMMessage(role="user", content="dame ventas")],
            tools=[...],
            system_prompt="Sos el Asistente de Badie...",
        )
    """

    def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None,
        system_prompt: str,
    ) -> LLMResponse:
        """Call the LLM and return text or tool calls.

        Args:
            messages: Ordered conversation history (without the system prompt).
                Each message has a ``role`` and ``content``.
            tools: List of Gemini-format function declarations, or None if no
                tools are available.
            system_prompt: Instructions injected as the system turn.

        Returns:
            LLMResponse with either text content or a list of tool calls.
        """
        ...
