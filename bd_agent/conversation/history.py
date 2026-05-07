"""bd_agent/conversation/history.py — In-memory per-JID conversation history.

Maintains a sliding window of the last N user-assistant pairs per JID.
Idle JIDs (no activity within idle_timeout_seconds) are swept out by
sweep_idle(), which is meant to be called periodically by the orchestrator.

Design:
    - Zero imports from src.* (RF-070)
    - now_fn is injectable for deterministic testing
    - Thread-safety: not guaranteed (single-threaded async context assumed)
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable

from bd_agent.contracts import Message


class InMemoryHistory:
    """Sliding-window conversation history keyed by WhatsApp JID.

    Args:
        max_pairs: Maximum number of user-assistant pairs to retain per JID.
            When exceeded, the oldest pair (two messages) is dropped.
        idle_timeout_seconds: Seconds of inactivity after which a JID's
            history is considered stale and removed by sweep_idle().
        now_fn: Callable returning the current time as a float (monotonic
            seconds).  Defaults to time.monotonic.  Override in tests.
    """

    def __init__(
        self,
        max_pairs: int = 10,
        idle_timeout_seconds: int = 3600,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_pairs = max_pairs
        self._idle_timeout = idle_timeout_seconds
        self._now = now_fn
        # JID -> deque of Message
        self._store: dict[str, deque[Message]] = {}
        # JID -> last-active timestamp (from now_fn)
        self._last_active: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, jid: str, message: Message) -> None:
        """Append a message for jid, enforcing the sliding window.

        The window is counted in *pairs* (user + assistant).  When the buffer
        holds more than max_pairs pairs the oldest pair (first two messages)
        is dropped.

        Calling append() also refreshes the last-active timestamp for jid.
        """
        if jid not in self._store:
            self._store[jid] = deque()

        self._store[jid].append(message)
        self._last_active[jid] = self._now()

        # Trim: drop oldest pair (two messages) while over budget
        buf = self._store[jid]
        while len(buf) > self._max_pairs * 2:
            buf.popleft()
            if buf:
                buf.popleft()

    def get(self, jid: str) -> list[Message]:
        """Return the current message history for jid, oldest first.

        Returns an empty list if jid has no history.
        """
        if jid not in self._store:
            return []
        return list(self._store[jid])

    def clear(self, jid: str) -> None:
        """Remove all history for jid.  No-op if jid is unknown."""
        self._store.pop(jid, None)
        self._last_active.pop(jid, None)

    def sweep_idle(self) -> int:
        """Remove JIDs that have been idle for >= idle_timeout_seconds.

        Returns:
            Number of JIDs cleared.
        """
        now = self._now()
        to_remove = [
            jid
            for jid, last in self._last_active.items()
            if (now - last) >= self._idle_timeout
        ]
        for jid in to_remove:
            self.clear(jid)
        return len(to_remove)
