"""bd_agent/contracts.py — All Protocols + dataclasses for the WhatsApp BD Agent.

This module has ZERO imports from src.*. All cross-boundary dependencies flow
through these Protocols (RF-070, RF-071).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Permission = Literal["ventas", "clientes", "cobertura", "stock"]
Role = Literal["system", "user", "assistant", "tool"]
FinishReason = Literal["stop", "tool_calls", "length", "error"]

# ---------------------------------------------------------------------------
# Frozen dataclasses — domain value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Contact:
    """A whitelisted contact with permissions and daily budget (RF-080)."""

    name: str
    jid: str
    daily_message_limit: int
    permissions: tuple[Permission, ...]


@dataclass(frozen=True)
class Message:
    """A single message in a conversation turn."""

    role: Role
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ToolCall:
    """A function/tool call emitted by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]

    def __hash__(self) -> int:
        # dict is not hashable; use id as unique key
        return hash(self.id)


@dataclass(frozen=True)
class ToolResult:
    """The result of executing a tool call."""

    call_id: str
    name: str
    content: str  # JSON-serialized payload or error message
    is_error: bool = False


@dataclass(frozen=True)
class LLMResponse:
    """Response from an LLM provider, which may contain text or tool calls."""

    text: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: FinishReason
    usage_tokens_in: int = 0
    usage_tokens_out: int = 0

# ---------------------------------------------------------------------------
# Protocols — injectable boundary interfaces
# ---------------------------------------------------------------------------


@runtime_checkable
class DatabaseGateway(Protocol):
    """Read-only access to gold.* schema.

    Implementations MUST enforce SELECT-only via DB role + connection-level
    read_only and MUST cap rows (RF-060, RF-063).
    """

    def execute_select(
        self, query: str, params: dict[str, Any], max_rows: int
    ) -> list[dict]: ...

    def get_schema_doc(self) -> str: ...


@runtime_checkable
class MessagingGateway(Protocol):
    """Outbound message transport.

    send_text MUST be synchronous from the caller's perspective and raise on
    transport failure (caller handles retry).
    """

    def send_text(self, jid: str, text: str) -> None: ...


@runtime_checkable
class ContactsRepo(Protocol):
    """Allowlist + per-contact metadata.

    reload() MUST be safe to call from a non-orchestrator thread
    (e.g. /agent/reload-schema).
    """

    def get(self, jid: str) -> Contact | None: ...

    def list_all(self) -> list[Contact]: ...

    def reload(self) -> None: ...


@runtime_checkable
class LLMProvider(Protocol):
    """Tool-calling LLM.

    complete() returns either a final text or tool calls to invoke;
    orchestrator loops until finish_reason == 'stop' or max iters.
    """

    def complete(
        self,
        messages: list[Message],
        tools: list[dict],  # provider-native tool spec
        max_output_tokens: int = 1024,
    ) -> LLMResponse: ...


@runtime_checkable
class LastActivityStore(Protocol):
    """Tracks the last time a JID was contacted by the agent.

    Used by GreetingJob to avoid double-greeting a contact who already received
    a reply in the last hour (RF-053).
    """

    def last_seen(self, jid: str) -> datetime | None: ...

    def record(self, jid: str, when: datetime) -> None: ...
