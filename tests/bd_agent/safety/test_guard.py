"""T-023 (continued): Tests for bd_agent/safety/guard.py — SafetyGuard aggregate.

Tests the composition of allowlist + active_hours + rate_limiter into
a single check(jid) -> Decision interface.

TDD cycle: RED phase is already satisfied by allowlist/rate_limiter/active_hours
imports failing. GREEN: guard.py implemented → all tests pass.
"""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from bd_agent.contracts import Contact


_SALTA = ZoneInfo("America/Argentina/Salta")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class StaticContactsRepo:
    def __init__(self, contacts):
        self._data = {c.jid: c for c in contacts}

    def get(self, jid):
        return self._data.get(jid)

    def list_all(self):
        return list(self._data.values())

    def reload(self):
        pass


def _make_contact(jid="5493870000001@s.whatsapp.net"):
    return Contact(
        name="Walter",
        jid=jid,
        daily_message_limit=100,
        permissions=("ventas",),
    )


def _make_guard(
    *,
    jids: list[str] | None = None,
    limit: int = 100,
    start: str = "07:00",
    end: str = "22:00",
    now_dt: datetime | None = None,
):
    """Build a SafetyGuard with injected fakes."""
    from bd_agent.safety.allowlist import AllowlistGuard
    from bd_agent.safety.active_hours import ActiveHoursGuard
    from bd_agent.safety.rate_limiter import RateLimiter
    from bd_agent.safety.guard import SafetyGuard

    if jids is None:
        jids = ["5493870000001@s.whatsapp.net"]

    contacts = [_make_contact(j) for j in jids]
    repo = StaticContactsRepo(contacts)

    allowlist = AllowlistGuard(repo=repo)
    active = ActiveHoursGuard(start=start, end=end)
    rate = RateLimiter(daily_limit_resolver=lambda jid: limit)

    now_fn = (lambda: now_dt) if now_dt is not None else None
    return SafetyGuard(allowlist=allowlist, active_hours=active, rate_limiter=rate, now_fn=now_fn)


KNOWN_JID = "5493870000001@s.whatsapp.net"
_MIDDAY_SALTA = datetime(2026, 5, 7, 12, 0, 0, tzinfo=_SALTA)
_NIGHT_SALTA = datetime(2026, 5, 7, 23, 0, 0, tzinfo=_SALTA)


class TestSafetyGuardAllowed:
    """check() returns allowed=True when all checks pass."""

    def test_known_jid_during_active_hours_under_limit_is_allowed(self):
        from bd_agent.safety.guard import Decision

        guard = _make_guard(now_dt=_MIDDAY_SALTA)
        result = guard.check(KNOWN_JID)
        assert isinstance(result, Decision)
        assert result.allowed is True
        assert result.reason == "ok"


class TestSafetyGuardAllowlistDenial:
    """check() returns jid_not_allowed for unlisted JIDs."""

    def test_unknown_jid_is_denied(self):
        guard = _make_guard(now_dt=_MIDDAY_SALTA)
        result = guard.check("9999999999@s.whatsapp.net")
        assert result.allowed is False
        assert result.reason == "jid_not_allowed"

    def test_allowlist_check_takes_priority(self):
        """Even during off-hours, jid_not_allowed is returned for unknown JIDs."""
        guard = _make_guard(now_dt=_NIGHT_SALTA)
        result = guard.check("9999999999@s.whatsapp.net")
        assert result.reason == "jid_not_allowed"


class TestSafetyGuardActiveHoursDenial:
    """check() returns outside_active_hours for known JIDs outside the window."""

    def test_known_jid_outside_active_hours_is_denied(self):
        guard = _make_guard(now_dt=_NIGHT_SALTA)
        result = guard.check(KNOWN_JID)
        assert result.allowed is False
        assert result.reason == "outside_active_hours"


class TestSafetyGuardRateLimitDenial:
    """check() returns daily_limit_reached when budget is exhausted."""

    def test_known_jid_at_rate_limit_is_denied(self):
        """After consuming all budget, the next check returns daily_limit_reached."""
        guard = _make_guard(limit=2, now_dt=_MIDDAY_SALTA)
        # Consume the 2-message budget
        assert guard.check(KNOWN_JID).allowed is True
        assert guard.check(KNOWN_JID).allowed is True
        # Third check must be denied
        result = guard.check(KNOWN_JID)
        assert result.allowed is False
        assert result.reason == "daily_limit_reached"


class TestSafetyGuardDecision:
    """Decision dataclass properties."""

    def test_decision_is_frozen(self):
        """Decision is a frozen dataclass — no mutation."""
        from bd_agent.safety.guard import Decision

        d = Decision(allowed=True, reason="ok")
        with pytest.raises((AttributeError, TypeError)):
            d.allowed = False  # type: ignore[misc]

    def test_decision_denied_has_reason(self):
        """Decision with allowed=False must have a non-empty reason."""
        from bd_agent.safety.guard import Decision

        d = Decision(allowed=False, reason="jid_not_allowed")
        assert d.reason
        assert d.allowed is False
