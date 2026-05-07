"""bd_agent/safety/guard.py — Aggregate SafetyGuard.

Composes allowlist, active_hours, and rate_limiter checks into a single
check(jid) -> Decision interface used by AgentOrchestrator (RF-001, RF-041, RF-042).

Decision:
  allowed: bool — True iff the message may proceed.
  reason: str — one of 'ok', 'jid_not_allowed', 'outside_active_hours',
                'daily_limit_reached'.

Zero imports from src.* (RF-070).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bd_agent.safety.active_hours import ActiveHoursGuard
from bd_agent.safety.allowlist import AllowlistGuard
from bd_agent.safety.rate_limiter import RateLimiter


@dataclass(frozen=True)
class Decision:
    """Result of SafetyGuard.check()."""

    allowed: bool
    reason: str  # 'ok' | 'jid_not_allowed' | 'outside_active_hours' | 'daily_limit_reached'


class SafetyGuard:
    """Aggregate safety check for inbound messages.

    Evaluation order (first denial wins):
    1. Allowlist check (jid must be in ContactsRepo)
    2. Active-hours check (current time must be within the window)
    3. Rate-limit check (JID must be under daily budget)

    Args:
        allowlist: AllowlistGuard instance.
        active_hours: ActiveHoursGuard instance.
        rate_limiter: RateLimiter instance.
        now_fn: injectable clock for tests; defaults to UTC now.
    """

    def __init__(
        self,
        allowlist: AllowlistGuard,
        active_hours: ActiveHoursGuard,
        rate_limiter: RateLimiter,
        now_fn=None,
    ) -> None:
        self._allowlist = allowlist
        self._active_hours = active_hours
        self._rate_limiter = rate_limiter
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def check(self, jid: str) -> Decision:
        """Run all safety checks for the given JID.

        Returns a Decision with allowed=True only if ALL checks pass.
        """
        if not self._allowlist.is_allowed(jid):
            return Decision(allowed=False, reason="jid_not_allowed")

        if not self._active_hours.is_active_now(self._now_fn()):
            return Decision(allowed=False, reason="outside_active_hours")

        if not self._rate_limiter.allow(jid):
            return Decision(allowed=False, reason="daily_limit_reached")

        return Decision(allowed=True, reason="ok")
