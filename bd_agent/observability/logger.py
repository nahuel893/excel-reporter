"""bd_agent/observability/logger.py — JSON structured logger (RF-090).

Every inbound message, every tool call, and every outbound message is logged
as a single-line JSON entry.  Raw JIDs are NEVER written to logs; only the
first 8 hex chars of SHA-256 appear (``jid_hash``).

Public API:
    JsonFormatter      — stdlib logging.Formatter; outputs single-line JSON
    BDAgentLogger      — high-level emitter with typed log_* helpers
    get_bd_agent_logger — singleton getter (one per process)

Design rules:
    - Zero imports from src.* (RF-070)
    - ``jid`` field on a LogRecord is masked; only ``jid_hash`` is forwarded
    - Output is always a single line (no embedded newlines)
"""
from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import time
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------

def _hash_jid(jid: str) -> str:
    """Return 8-char SHA-256 hex of *jid* (privacy-safe, RF-090)."""
    return hashlib.sha256(jid.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------

_RESERVED_LOG_ATTRS = frozenset({
    "args", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message",
    "msg", "name", "pathname", "process", "processName", "relativeCreated",
    "stack_info", "thread", "threadName",
})


class JsonFormatter(logging.Formatter):
    """Format a LogRecord as a single-line JSON string.

    All extra fields attached to the record are included in the JSON output,
    EXCEPT for ``jid`` (raw JID) which is silently dropped to prevent
    accidental PII leakage.  Use ``jid_hash`` instead.
    """

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        # Compute the formatted message first (handles %-style args)
        record.message = record.getMessage()

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        # Attach any extra fields added via logger.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_ATTRS:
                continue
            if key.startswith("_"):
                continue
            # Mask raw JID field — never log the actual JID
            if key == "jid":
                continue
            payload[key] = value

        # Ensure output is a single line
        return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# BDAgentLogger
# ---------------------------------------------------------------------------

class BDAgentLogger:
    """High-level structured logger for the BD Agent observability pipeline.

    Each method corresponds to one event type in the audit trail:
      - ``log_inbound``   — a message was received from WhatsApp
      - ``log_tool_call`` — a tool was invoked (curated or sql_fallback)
      - ``log_outbound``  — a reply was sent to WhatsApp

    All methods hash the JID before logging (RF-090).

    Args:
        logger: Optional ``logging.Logger`` to use.  Defaults to a
            ``logging.getLogger("bd_agent.observability")`` instance.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger("bd_agent.observability")

    # ------------------------------------------------------------------
    # Event methods
    # ------------------------------------------------------------------

    def log_inbound(self, *, jid: str, text_len: int) -> None:
        """Log an inbound message event."""
        self._log.info(
            "inbound_message",
            extra={
                "event_type": "inbound_message",
                "jid_hash": _hash_jid(jid),
                "text_len": text_len,
            },
        )

    def log_tool_call(
        self,
        *,
        jid: str,
        tool_name: str,
        duration_ms: int,
        is_error: bool,
    ) -> None:
        """Log a tool-call event (curated tool or sql_fallback)."""
        self._log.info(
            "tool_call",
            extra={
                "event_type": "tool_call",
                "jid_hash": _hash_jid(jid),
                "tool_name": tool_name,
                "duration_ms": duration_ms,
                "is_error": is_error,
            },
        )

    def log_outbound(
        self,
        *,
        jid: str,
        tokens_in: int,
        tokens_out: int,
        duration_ms: int,
    ) -> None:
        """Log an outbound reply event with token counts."""
        self._log.info(
            "outbound_message",
            extra={
                "event_type": "outbound_message",
                "jid_hash": _hash_jid(jid),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "duration_ms": duration_ms,
            },
        )


# ---------------------------------------------------------------------------
# Singleton getter
# ---------------------------------------------------------------------------

_singleton: BDAgentLogger | None = None


def get_bd_agent_logger() -> BDAgentLogger:
    """Return the process-level BDAgentLogger singleton."""
    global _singleton
    if _singleton is None:
        _singleton = BDAgentLogger()
    return _singleton
