"""T-021: Tests for bd_agent/safety/rate_limiter.py — per-JID daily budget counter.

Design:
- allow(jid) -> bool: returns True if under daily limit, increments counter.
- Counter resets at 00:00 Salta TZ.
- default_limit configurable (default 100); per-JID limit from daily_limit_resolver.
- expovariate(1/4) delay clamped to [2, 30] seconds (RF-040 / RF-041).

TDD cycle: RED first → GREEN → REFACTOR.
"""
import pytest
from datetime import date


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

JID_WALTER = "5493870000001@s.whatsapp.net"
JID_ANTONIO = "5493870000002@s.whatsapp.net"


def _make_limiter(daily_limit=3, jid_limits=None, today_fn=None, sleep_fn=None):
    """Construct a RateLimiter with injected dependencies for deterministic tests."""
    from bd_agent.safety.rate_limiter import RateLimiter

    resolver = lambda jid: (jid_limits or {}).get(jid, daily_limit)
    kwargs = {}
    if today_fn is not None:
        kwargs["today_fn"] = today_fn
    if sleep_fn is not None:
        kwargs["sleep_fn"] = sleep_fn
    return RateLimiter(daily_limit_resolver=resolver, **kwargs)


class TestRateLimiterBasicBudget:
    """Core: allow() enforces the daily budget."""

    def test_allow_returns_true_under_limit(self):
        """allow() returns True when counter is below the daily limit."""
        limiter = _make_limiter(daily_limit=3)
        assert limiter.allow(JID_WALTER) is True

    def test_allow_increments_counter(self):
        """allow() increments the counter on each call while under limit."""
        limiter = _make_limiter(daily_limit=3)
        assert limiter.allow(JID_WALTER) is True  # count = 1
        assert limiter.allow(JID_WALTER) is True  # count = 2
        assert limiter.allow(JID_WALTER) is True  # count = 3

    def test_allow_returns_false_at_limit(self):
        """allow() returns False once the daily limit is reached."""
        limiter = _make_limiter(daily_limit=3)
        limiter.allow(JID_WALTER)  # 1
        limiter.allow(JID_WALTER)  # 2
        limiter.allow(JID_WALTER)  # 3 — at limit
        result = limiter.allow(JID_WALTER)  # 4 — over limit
        assert result is False

    def test_allow_does_not_increment_at_limit(self):
        """allow() does NOT increment the counter beyond the limit."""
        limiter = _make_limiter(daily_limit=2)
        limiter.allow(JID_WALTER)  # 1
        limiter.allow(JID_WALTER)  # 2
        limiter.allow(JID_WALTER)  # blocked — should NOT increment to 3
        limiter.allow(JID_WALTER)  # still blocked

        # Exhaust another JID to verify Walter counter is stable
        assert limiter.allow(JID_ANTONIO) is True  # Antonio at 1

    def test_zero_limit_never_allows(self):
        """A JID with daily_limit=0 is always blocked (RF-052/S1 variant)."""
        limiter = _make_limiter(daily_limit=0)
        assert limiter.allow(JID_WALTER) is False

    def test_independent_counters_per_jid(self):
        """Each JID has its own independent counter."""
        limiter = _make_limiter(daily_limit=2)
        assert limiter.allow(JID_WALTER) is True   # Walter: 1
        assert limiter.allow(JID_ANTONIO) is True  # Antonio: 1
        assert limiter.allow(JID_WALTER) is True   # Walter: 2
        assert limiter.allow(JID_ANTONIO) is True  # Antonio: 2
        assert limiter.allow(JID_WALTER) is False  # Walter: blocked
        assert limiter.allow(JID_ANTONIO) is False  # Antonio: blocked


class TestRateLimiterDailyReset:
    """Counter resets at midnight Salta TZ."""

    def test_counter_resets_when_date_changes(self):
        """When today_fn returns a new date, allow() resets the counter."""
        days = [date(2026, 5, 7)]  # mutable via list

        def today_fn():
            return days[0]

        limiter = _make_limiter(daily_limit=1, today_fn=today_fn)

        # Exhaust the budget on day 1
        assert limiter.allow(JID_WALTER) is True
        assert limiter.allow(JID_WALTER) is False

        # Advance to next day
        days[0] = date(2026, 5, 8)

        # Counter must reset — allow() returns True again
        assert limiter.allow(JID_WALTER) is True

    def test_counter_does_not_reset_same_day(self):
        """Counter does NOT reset if the date has not changed."""
        fixed_day = date(2026, 5, 7)
        limiter = _make_limiter(daily_limit=1, today_fn=lambda: fixed_day)

        limiter.allow(JID_WALTER)  # exhaust
        assert limiter.allow(JID_WALTER) is False  # still blocked same day

    def test_different_jids_reset_independently(self):
        """Date-based reset is per-JID state (stored per JID with its date)."""
        days = [date(2026, 5, 7)]

        def today_fn():
            return days[0]

        limiter = _make_limiter(daily_limit=1, today_fn=today_fn)

        # Exhaust Walter on day 1
        limiter.allow(JID_WALTER)

        # Advance day — Walter resets, Antonio has fresh budget
        days[0] = date(2026, 5, 8)
        assert limiter.allow(JID_WALTER) is True   # reset
        assert limiter.allow(JID_ANTONIO) is True  # fresh


class TestRateLimiterJitter:
    """Reply-delay jitter: expovariate(1/4) clamped to [2, 30] seconds."""

    def test_jitter_in_bounds(self):
        """jitter() always returns a value in [2.0, 30.0]."""
        from bd_agent.safety.rate_limiter import RateLimiter

        limiter = RateLimiter(daily_limit_resolver=lambda jid: 100)
        for _ in range(200):
            value = limiter.jitter()
            assert 2.0 <= value <= 30.0, f"jitter() returned {value} which is out of [2, 30]"

    def test_jitter_is_float(self):
        """jitter() returns a float."""
        from bd_agent.safety.rate_limiter import RateLimiter

        limiter = RateLimiter(daily_limit_resolver=lambda jid: 100)
        value = limiter.jitter()
        assert isinstance(value, float)

    def test_jitter_with_injected_expovariate_below_two(self):
        """When expovariate returns < 2, jitter() clamps to 2.0."""
        from bd_agent.safety.rate_limiter import RateLimiter

        limiter = RateLimiter(
            daily_limit_resolver=lambda jid: 100,
            expovariate_fn=lambda lambd: 0.1,  # always < 2
        )
        assert limiter.jitter() == 2.0

    def test_jitter_with_injected_expovariate_above_thirty(self):
        """When expovariate returns > 30, jitter() clamps to 30.0."""
        from bd_agent.safety.rate_limiter import RateLimiter

        limiter = RateLimiter(
            daily_limit_resolver=lambda jid: 100,
            expovariate_fn=lambda lambd: 100.0,  # always > 30
        )
        assert limiter.jitter() == 30.0

    def test_jitter_with_injected_expovariate_in_range(self):
        """When expovariate is in [2, 30], jitter() returns that exact value."""
        from bd_agent.safety.rate_limiter import RateLimiter

        limiter = RateLimiter(
            daily_limit_resolver=lambda jid: 100,
            expovariate_fn=lambda lambd: 10.5,  # within range
        )
        assert limiter.jitter() == 10.5
