"""bd_agent/transport/router.py — FastAPI router for the WhatsApp BD Agent (T-072).

Endpoints:
  POST /agent/message         — Inbound message from Baileys Node service.
                                Deduplicates by (from, ts) within a 60-second window.
                                Invokes AgentTurn.handle_incoming as a BackgroundTask.
                                Returns {ok: true} immediately.
  POST /agent/reload-schema   — Reloads the schema doc from disk (RF-082).
  POST /agent/reload-contacts — Reloads contacts JSON from disk (RF-002).

Design rules:
  - Zero imports from src.* (RF-070).
  - Idempotency: dedup by (from, ts) — 60-second window (RF-011).
    Returns 202 {status: "duplicate"} for repeated (from, ts) pairs.
  - Dedup store is an in-memory LRU-style dict; entries expire after 60 seconds.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dedup store — (jid, ts) → accepted_at; expire after 60 seconds
# ---------------------------------------------------------------------------

_DEDUP_WINDOW_SECONDS = 60
_dedup_store: dict[tuple[str, float], float] = {}


def _is_duplicate(jid: str, ts: float) -> bool:
    """Return True if this (jid, ts) pair was seen within the dedup window."""
    _evict_expired()
    key = (jid, ts)
    if key in _dedup_store:
        return True
    _dedup_store[key] = time.monotonic()
    return False


def _evict_expired() -> None:
    """Remove entries older than _DEDUP_WINDOW_SECONDS from the store."""
    now = time.monotonic()
    expired = [k for k, accepted_at in _dedup_store.items()
               if (now - accepted_at) > _DEDUP_WINDOW_SECONDS]
    for k in expired:
        del _dedup_store[k]


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


from pydantic import Field


class InboundMessage(BaseModel):
    """Body for POST /agent/message.

    The JSON field is ``"from"`` (a Python reserved keyword), mapped via alias.
    """

    model_config = {"populate_by_name": True}

    # 'from' is a reserved keyword in Python; use Field alias
    from_: str = Field(alias="from")
    text: str
    ts: float


class MessageAccepted(BaseModel):
    ok: bool = True


class DuplicateResponse(BaseModel):
    status: str = "duplicate"


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def make_router(
    agent_turn: Any,
    contacts_repo: Any,
    db_gateway: Any,
) -> APIRouter:
    """Create and return the configured FastAPI APIRouter.

    Args:
        agent_turn: AgentTurn instance — has ``handle_incoming(jid, text, ts)``.
        contacts_repo: ContactsRepo instance — has ``reload()``.
        db_gateway: PgDatabaseGateway (or any object with ``reload_schema_doc()``).

    Returns:
        FastAPI APIRouter with three endpoints.
    """
    router = APIRouter(tags=["BD Agent"])

    @router.post(
        "/agent/message",
        summary="Inbound WhatsApp message",
        status_code=200,
    )
    async def post_message(
        msg: InboundMessage,
        background_tasks: BackgroundTasks,
    ):
        """Receive an inbound message from the Baileys Node service.

        Deduplicates by (from, ts) — same pair within 60 seconds returns 202.
        Processing is dispatched as a BackgroundTask to return immediately.
        """
        jid = msg.from_
        if _is_duplicate(jid, msg.ts):
            logger.debug(
                "dedup_rejected",
                extra={"jid_prefix": jid[:12], "ts": msg.ts},
            )
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=202, content={"status": "duplicate"})

        background_tasks.add_task(agent_turn.handle_incoming, jid, msg.text, msg.ts)
        return MessageAccepted()

    @router.post(
        "/agent/reload-schema",
        summary="Reload schema doc from disk",
        status_code=200,
    )
    async def reload_schema():
        """Force a reload of CONTEXT_DATABASE.md from disk (RF-082).

        The next LLM call will use the refreshed schema content.
        """
        db_gateway.reload_schema_doc()
        logger.info("schema_doc_reloaded_via_endpoint")
        return {"ok": True, "action": "schema_reloaded"}

    @router.post(
        "/agent/reload-contacts",
        summary="Reload contacts JSON from disk",
        status_code=200,
    )
    async def reload_contacts():
        """Force a reload of contactos_agente.json from disk (RF-002)."""
        contacts_repo.reload()
        logger.info("contacts_reloaded_via_endpoint")
        return {"ok": True, "action": "contacts_reloaded"}

    @router.get(
        "/agent/metrics",
        summary="BD Agent metrics snapshot",
        status_code=200,
    )
    async def get_metrics_endpoint():
        """Return current in-memory metrics counters (T-111).

        Counters include: messages_received, messages_sent, tool_calls_by_name,
        errors_by_type, tokens_in_total, tokens_out_total, uptime_seconds.
        """
        from bd_agent.observability.metrics import get_metrics
        return get_metrics().snapshot()

    return router
