"""bd_agent/agent.py — AgentTurn: the main incoming-message turn pipeline.

Orchestrates the full life-cycle of a single inbound WhatsApp message:

  1. Validate JID via allowlist guard (RF-001)
  2. Active-hours check (RF-042)
  3. Rate-limit check — record token (RF-041)
  4. History fetch + append user message (RF-030)
  5. Build system prompt (schema doc + tool specs + contact)
  6. LLM loop — max ``max_tool_iterations`` iterations:
       a. Call ``LLMProvider.generate(messages, tools, system_prompt)``
       b. If response has tool_calls: execute each tool via registry,
          append tool results to messages, loop
       c. If response has text only: break
  7. Random delay via ``delay_fn`` (RF-040) — only if a reply will be sent
  8. Send via ``MessagingGateway.send_text`` — only if text is non-empty
  9. History append assistant message
 10. (Audit log — stub; full observability in Slice 12)

Design principles:
  - All dependencies are injected; no globals, no hard-coded imports from src.*
  - ``delay_fn`` defaults to a no-op (injectable in tests to avoid sleeps)
  - Empty or whitespace-only final text is silently dropped (no empty messages)
  - Max-iterations guard prevents infinite tool-call loops; sends a fixed
    fallback message after the cap is exceeded
  - Zero imports from src.* (RF-070)
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Callable

from bd_agent.contracts import (
    Contact,
    Message,
    ToolCall,
)
from bd_agent.conversation.history import InMemoryHistory
from bd_agent.conversation.system_prompt import build_system_prompt
from bd_agent.llm.provider import LLMMessage, LLMProvider, LLMToolCall
from bd_agent.safety.active_hours import ActiveHoursGuard
from bd_agent.safety.allowlist import AllowlistGuard
from bd_agent.safety.rate_limiter import RateLimiter
from bd_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Fallback message sent when the agent exceeds max_tool_iterations.
_MAX_ITERS_FALLBACK = (
    "No pude resolver tu consulta en el límite de pasos permitidos. "
    "Por favor, reformulá la pregunta o hacé una consulta más específica."
)


class AgentTurn:
    """Full incoming-message turn pipeline for the WhatsApp BD Agent.

    Each call to ``handle_incoming()`` is a self-contained turn:  it reads
    the current conversation state, runs the safety checks, calls the LLM
    (possibly multiple times for tool-call loops), and delivers the final
    reply to the contact.

    Args:
        allowlist: AllowlistGuard — JID allowlist enforcement.
        active_hours: ActiveHoursGuard — time-window check.
        rate_limiter: RateLimiter — per-JID daily budget.
        history: InMemoryHistory — per-JID sliding-window message store.
        contacts: ContactsRepo (any object with ``get(jid) -> Contact | None``).
        llm: LLMProvider — generates text or tool calls from messages.
        tool_registry: ToolRegistry — executes tool calls by name.
        messaging: MessagingGateway — delivers outbound text via WhatsApp.
        schema_doc_loader: Callable returning the full schema doc string.
            Called once per turn (caching is the loader's responsibility).
        delay_fn: Optional callable invoked before send_text to introduce
            jitter (RF-040).  Defaults to a no-op so tests don't sleep.
            Pass ``None`` to use the default no-op.
        max_tool_iterations: Maximum number of times the LLM loop may
            execute a tool call before breaking with a fallback message.
    """

    def __init__(
        self,
        allowlist: AllowlistGuard,
        active_hours: ActiveHoursGuard,
        rate_limiter: RateLimiter,
        history: InMemoryHistory,
        contacts,  # ContactsRepo protocol
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        messaging,  # MessagingGateway protocol
        schema_doc_loader: Callable[[], str],
        delay_fn: Callable[[], None] | None = None,
        max_tool_iterations: int = 5,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._allowlist = allowlist
        self._active_hours = active_hours
        self._rate_limiter = rate_limiter
        self._history = history
        self._contacts = contacts
        self._llm = llm
        self._tool_registry = tool_registry
        self._messaging = messaging
        self._schema_doc_loader = schema_doc_loader
        self._delay_fn: Callable[[], None] = delay_fn if delay_fn is not None else _noop
        self._max_tool_iterations = max_tool_iterations
        self._now_fn: Callable[[], datetime] = (
            now_fn if now_fn is not None else (lambda: datetime.now(timezone.utc))
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_incoming(self, jid: str, text: str, ts: float) -> None:
        """Process one inbound message from *jid*.

        Args:
            jid: WhatsApp JID of the sender (``XXXXXXXXXX@s.whatsapp.net``).
            text: Plain-text body of the inbound message.
            ts: Unix timestamp of the message (float seconds).

        Returns:
            None.  Side effects: may send an outbound message, update history,
            and write audit entries.
        """
        # ------------------------------------------------------------------
        # Step 1: Allowlist guard
        # ------------------------------------------------------------------
        if not self._allowlist.is_allowed(jid):
            logger.info(
                "jid_not_allowed",
                extra={"jid_hash": _hash_jid(jid), "reason": "jid_not_allowed"},
            )
            return

        # ------------------------------------------------------------------
        # Step 2: Active-hours check
        # ------------------------------------------------------------------
        now = self._now_fn()
        if not self._active_hours.is_active_now(now):
            logger.info(
                "outside_active_hours",
                extra={"jid_hash": _hash_jid(jid), "reason": "outside_active_hours"},
            )
            return

        # ------------------------------------------------------------------
        # Step 3: Rate-limit check — record token
        # ------------------------------------------------------------------
        if not self._rate_limiter.allow(jid):
            logger.info(
                "daily_limit_reached",
                extra={"jid_hash": _hash_jid(jid), "reason": "daily_limit_reached"},
            )
            return

        # ------------------------------------------------------------------
        # Step 4: History fetch + append user message
        # ------------------------------------------------------------------
        user_msg = Message(role="user", content=text)
        self._history.append(jid, user_msg)
        conversation = self._history.get(jid)

        # ------------------------------------------------------------------
        # Step 5: Build system prompt
        # ------------------------------------------------------------------
        contact: Contact | None = self._contacts.get(jid)
        tool_specs = _tool_specs_text(self._tool_registry)
        schema_doc = self._schema_doc_loader()
        system_prompt = build_system_prompt(
            schema_doc=schema_doc,
            tool_specs=tool_specs,
            contact=contact or _unknown_contact(jid),
        )

        # Convert history to LLMMessage list (exclude the user msg we just added —
        # it is already the last item in conversation, so we pass the full list)
        llm_messages = _to_llm_messages(conversation)
        tool_declarations = self._tool_registry.gemini_function_declarations()

        # ------------------------------------------------------------------
        # Step 6: LLM loop (max max_tool_iterations)
        # ------------------------------------------------------------------
        final_text: str | None = None
        iterations = 0

        while iterations < self._max_tool_iterations:
            response: LLMResponse = self._llm.generate(
                messages=llm_messages,
                tools=tool_declarations or None,
                system_prompt=system_prompt,
            )
            iterations += 1

            if not response.tool_calls:
                # Text-only response or empty response — break
                final_text = response.text
                break

            # Execute each tool call and collect results
            for tc in response.tool_calls:
                domain_call = ToolCall(
                    id=tc.id,
                    name=tc.name,
                    arguments=tc.arguments,
                )
                tool_result = self._tool_registry.invoke(
                    domain_call, gateway=None, context={"_jid": jid}
                )

                # Append tool-call placeholder (assistant role)
                llm_messages.append(
                    LLMMessage(
                        role="assistant",
                        content="",
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                    )
                )
                # Append tool result (tool role)
                llm_messages.append(
                    LLMMessage(
                        role="tool",
                        content=tool_result.content,
                        tool_call_id=tool_result.call_id,
                        tool_name=tool_result.name,
                    )
                )

        else:
            # Exceeded max_tool_iterations — send safe fallback
            final_text = _MAX_ITERS_FALLBACK
            logger.warning(
                "max_tool_iterations_exceeded",
                extra={
                    "jid_hash": _hash_jid(jid),
                    "iterations": iterations,
                },
            )

        # ------------------------------------------------------------------
        # Step 7 + 8: Delay + Send (only if non-empty text)
        # ------------------------------------------------------------------
        if not (final_text and final_text.strip()):
            # Empty or whitespace-only reply — silently drop (no empty messages)
            return

        self._delay_fn()
        self._messaging.send_text(jid, final_text)

        # ------------------------------------------------------------------
        # Step 9: History append assistant message
        # ------------------------------------------------------------------
        assistant_msg = Message(role="assistant", content=final_text)
        self._history.append(jid, assistant_msg)

        # ------------------------------------------------------------------
        # Step 10: Audit log (stub — full observability in Slice 12)
        # ------------------------------------------------------------------
        logger.debug(
            "turn_complete",
            extra={
                "jid_hash": _hash_jid(jid),
                "iterations": iterations,
                "final_chars": len(final_text),
            },
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _noop() -> None:
    """No-op delay function (default — tests never sleep)."""


def _hash_jid(jid: str) -> str:
    """Return a SHA-256 hex digest of the JID for privacy-safe logging (RF-090)."""
    return hashlib.sha256(jid.encode()).hexdigest()[:16]


def _tool_specs_text(registry: ToolRegistry) -> str:
    """Convert registered tool declarations to a human-readable text block."""
    decls = registry.gemini_function_declarations()
    if not decls:
        return "(sin herramientas disponibles)"
    lines = []
    for d in decls:
        lines.append(f"- {d['name']}: {d.get('description', '')}")
    return "\n".join(lines)


def _to_llm_messages(history: list[Message]) -> list[LLMMessage]:
    """Convert domain Message objects to LLMMessage objects for the provider."""
    return [
        LLMMessage(
            role=msg.role,
            content=msg.content,
            tool_call_id=msg.tool_call_id,
            tool_name=msg.tool_name,
        )
        for msg in history
    ]


def _unknown_contact(jid: str) -> Contact:
    """Return a minimal Contact for JIDs not found in the repo.

    In practice this should not happen (allowlist check runs first), but
    having a safe default prevents an AttributeError if the repo returns None.
    """
    return Contact(
        name="Unknown",
        jid=jid,
        daily_message_limit=0,
        permissions=(),
    )
