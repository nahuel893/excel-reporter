"""bd_agent/safety/rate_limiter.py — Per-JID daily budget counter + reply-delay jitter.

Implements RF-040 (reply delay jitter) and RF-041 (per-JID daily message budget):
- allow(jid) -> bool: True if under daily limit, False otherwise. Increments on success.
- Counter resets at 00:00 Salta TZ (detected via today_fn, injectable for tests).
- jitter() -> float: expovariate(1/4) clamped to [2.0, 30.0] seconds.

Dependencies injected for deterministic testing:
- today_fn: callable() -> date (default: real date in Salta TZ)
- expovariate_fn: callable(lambd: float) -> float (default: random.expovariate)

Zero imports from src.* (RF-070). Deps: stdlib only.
"""
from __future__ import annotations

import random
from datetime import date
from typing import Callable
from zoneinfo import ZoneInfo

_SALTA_TZ = ZoneInfo("America/Argentina/Salta")

# Jitter parameters per RF-040
_JITTER_MEAN = 4.0        # expovariate lambd = 1/4
_JITTER_MIN = 2.0
_JITTER_MAX = 30.0


def _salta_today() -> date:
    """Return the current date in Salta timezone."""
    from datetime import datetime
    return datetime.now(_SALTA_TZ).date()


class RateLimiter:
    """Per-JID daily budget counter with configurable dependencies.

    Args:
        daily_limit_resolver: callable(jid: str) -> int — returns the daily message
            limit for a given JID. Default fallback is AGENT_DAILY_LIMIT_DEFAULT.
        today_fn: callable() -> date — injected for tests; defaults to Salta TZ today.
        expovariate_fn: callable(lambd: float) -> float — injected for tests;
            defaults to random.expovariate.
        sleep_fn: not used internally; kept for API symmetry if callers want to inject.
    """

    def __init__(
        self,
        daily_limit_resolver: Callable[[str], int],
        today_fn: Callable[[], date] | None = None,
        expovariate_fn: Callable[[float], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._resolver = daily_limit_resolver
        self._today_fn = today_fn or _salta_today
        self._expovariate_fn = expovariate_fn or random.expovariate
        # _counters: dict[jid, (date, count)]
        self._counters: dict[str, tuple[date, int]] = {}

    def allow(self, jid: str) -> bool:
        """Return True and increment counter if the JID is under its daily limit.

        Returns False (without incrementing) if the limit is reached or zero.
        """
        today = self._today_fn()
        stored_date, count = self._counters.get(jid, (today, 0))

        # Reset counter if the date has changed
        if stored_date != today:
            count = 0

        limit = self._resolver(jid)
        if limit == 0 or count >= limit:
            # Store with today's date (preserves reset detection)
            self._counters[jid] = (today, count)
            return False

        # Increment and allow
        self._counters[jid] = (today, count + 1)
        return True

    def jitter(self) -> float:
        """Return a random delay in [2.0, 30.0] seconds (RF-040).

        Uses expovariate(1 / JITTER_MEAN) clamped to [JITTER_MIN, JITTER_MAX].
        """
        raw = self._expovariate_fn(1.0 / _JITTER_MEAN)
        return max(_JITTER_MIN, min(_JITTER_MAX, raw))
