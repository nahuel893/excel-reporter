"""bd_agent/observability/metrics.py — in-memory metrics counters (T-111).

Thread-safe counter store exposed via ``GET /agent/metrics`` endpoint.

Public API:
    MetricsCollector — thread-safe metric store
    get_metrics      — process-level singleton getter

Design rules:
    - Zero imports from src.* (RF-070)
    - All mutations protected by threading.Lock
    - ``snapshot()`` returns a deep copy — mutating it is safe
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any


class MetricsCollector:
    """Thread-safe in-memory metrics store.

    Tracks:
        messages_received     — total inbound messages
        messages_sent         — total outbound messages
        tool_calls_by_name    — dict[tool_name, count]
        errors_by_type        — dict[error_type, count]
        errors_total          — sum of all error counts
        tokens_in_total       — cumulative LLM input tokens
        tokens_out_total      — cumulative LLM output tokens
        uptime_seconds        — seconds since this instance was created
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._messages_received = 0
        self._messages_sent = 0
        self._tokens_in_total = 0
        self._tokens_out_total = 0
        self._tool_calls_by_name: dict[str, int] = {}
        self._errors_by_type: dict[str, int] = {}
        self._errors_total = 0
        # Sandbox counters (T-203, RF-172)
        self._sandbox_executions_total = 0
        self._sandbox_failures_total = 0
        self._sandbox_duration_seconds: list[float] = []

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def record_inbound(self) -> None:
        """Increment ``messages_received`` counter."""
        with self._lock:
            self._messages_received += 1

    def record_outbound(self, *, tokens_in: int, tokens_out: int) -> None:
        """Increment ``messages_sent`` and accumulate token counts."""
        with self._lock:
            self._messages_sent += 1
            self._tokens_in_total += tokens_in
            self._tokens_out_total += tokens_out

    def record_tool_call(self, tool_name: str) -> None:
        """Increment the per-name tool-call counter."""
        with self._lock:
            self._tool_calls_by_name[tool_name] = (
                self._tool_calls_by_name.get(tool_name, 0) + 1
            )

    def record_error(self, error_type: str) -> None:
        """Increment the per-type error counter and the total."""
        with self._lock:
            self._errors_by_type[error_type] = (
                self._errors_by_type.get(error_type, 0) + 1
            )
            self._errors_total += 1

    def record_sandbox_execution(
        self,
        reason: str | None,
        duration_seconds: float,
    ) -> None:
        """Record one sandbox execution attempt (T-203, RF-172).

        Args:
            reason: Failure phase name ("validation", "sql", "staging", "execution",
                "timeout", "output", "send"), or None for a successful execution.
            duration_seconds: Total execution wall-clock time in seconds.
        """
        with self._lock:
            self._sandbox_executions_total += 1
            if reason is not None:
                self._sandbox_failures_total += 1
            self._sandbox_duration_seconds.append(duration_seconds)

    # ------------------------------------------------------------------
    # Snapshot (read-only copy)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a deep-copy snapshot of all current metrics.

        Safe to mutate — changes do NOT affect internal state.
        """
        with self._lock:
            return {
                "messages_received": self._messages_received,
                "messages_sent": self._messages_sent,
                "tokens_in_total": self._tokens_in_total,
                "tokens_out_total": self._tokens_out_total,
                "tool_calls_by_name": copy.deepcopy(self._tool_calls_by_name),
                "errors_by_type": copy.deepcopy(self._errors_by_type),
                "errors_total": self._errors_total,
                "uptime_seconds": time.monotonic() - self._started_at,
                # Sandbox metrics (T-203, RF-172)
                "sandbox_executions_total": self._sandbox_executions_total,
                "sandbox_failures_total": self._sandbox_failures_total,
                "sandbox_duration_seconds": list(self._sandbox_duration_seconds),
            }

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all counters to zero (does not reset uptime)."""
        with self._lock:
            self._messages_received = 0
            self._messages_sent = 0
            self._tokens_in_total = 0
            self._tokens_out_total = 0
            self._tool_calls_by_name = {}
            self._errors_by_type = {}
            self._errors_total = 0
            self._sandbox_executions_total = 0
            self._sandbox_failures_total = 0
            self._sandbox_duration_seconds = []


# ---------------------------------------------------------------------------
# Singleton getter
# ---------------------------------------------------------------------------

_singleton: MetricsCollector | None = None
_singleton_lock = threading.Lock()


def get_metrics() -> MetricsCollector:
    """Return the process-level MetricsCollector singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = MetricsCollector()
    return _singleton
