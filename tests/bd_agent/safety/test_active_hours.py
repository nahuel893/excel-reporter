"""T-022: Tests for bd_agent/safety/active_hours.py — active-hours guard.

Design (RF-042):
- is_active_now(now: datetime) -> bool
- Default active window: 07:00–22:00 in America/Argentina/Salta
- Configurable start and end from ContactsRepo settings
- Boundary tests: inside, outside, at exact boundaries

TDD cycle: RED first → GREEN → REFACTOR.
"""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

_SALTA = ZoneInfo("America/Argentina/Salta")
_UTC = ZoneInfo("UTC")


def _dt(hour: int, minute: int = 0, tz=_SALTA) -> datetime:
    """Convenience: create a datetime at the given HH:MM in the given tz."""
    return datetime(2026, 5, 7, hour, minute, 0, tzinfo=tz)


def _make_guard(start="07:00", end="22:00", tz="America/Argentina/Salta"):
    """Construct an ActiveHoursGuard with default Salta settings."""
    from bd_agent.safety.active_hours import ActiveHoursGuard

    return ActiveHoursGuard(start=start, end=end, tz=tz)


class TestActiveHoursGuardDefaults:
    """Default window 07:00–22:00 Salta TZ."""

    def test_inside_window_returns_true(self):
        """is_active_now() returns True for a time well within the window."""
        guard = _make_guard()
        # 12:00 Salta — midday, clearly inside
        assert guard.is_active_now(_dt(12, 0)) is True

    def test_outside_window_before_start_returns_false(self):
        """is_active_now() returns False before 07:00 Salta."""
        guard = _make_guard()
        # 06:59 Salta — one minute before start
        assert guard.is_active_now(_dt(6, 59)) is False

    def test_outside_window_after_end_returns_false(self):
        """is_active_now() returns False at or after 22:00 Salta."""
        guard = _make_guard()
        # 22:00 Salta — exactly at end (exclusive)
        assert guard.is_active_now(_dt(22, 0)) is False

    def test_outside_window_night_returns_false(self):
        """is_active_now() returns False at 23:15 Salta (RF-042/S1)."""
        guard = _make_guard()
        assert guard.is_active_now(_dt(23, 15)) is False


class TestActiveHoursGuardBoundaries:
    """Exact boundary behavior."""

    def test_at_start_boundary_returns_true(self):
        """is_active_now() returns True at exactly 07:00 Salta (inclusive start)."""
        guard = _make_guard()
        assert guard.is_active_now(_dt(7, 0)) is True

    def test_one_minute_after_start_returns_true(self):
        """is_active_now() returns True at 07:01 Salta (RF-042/S2)."""
        guard = _make_guard()
        assert guard.is_active_now(_dt(7, 1)) is True

    def test_one_minute_before_end_returns_true(self):
        """is_active_now() returns True at 21:59 Salta."""
        guard = _make_guard()
        assert guard.is_active_now(_dt(21, 59)) is True

    def test_at_end_boundary_returns_false(self):
        """is_active_now() returns False at exactly 22:00 Salta (exclusive end)."""
        guard = _make_guard()
        assert guard.is_active_now(_dt(22, 0)) is False

    def test_one_minute_after_end_returns_false(self):
        """is_active_now() returns False at 22:01 Salta."""
        guard = _make_guard()
        assert guard.is_active_now(_dt(22, 1)) is False


class TestActiveHoursGuardTimezoneConversion:
    """now argument in UTC must be converted to Salta TZ correctly."""

    def test_utc_time_converted_to_salta(self):
        """A UTC datetime that maps to Salta active hours is accepted."""
        guard = _make_guard()
        # Salta is UTC-3. 10:00 Salta = 13:00 UTC.
        utc_time = datetime(2026, 5, 7, 13, 0, 0, tzinfo=_UTC)
        assert guard.is_active_now(utc_time) is True

    def test_utc_time_outside_salta_window(self):
        """A UTC datetime that maps to outside Salta active hours is rejected."""
        guard = _make_guard()
        # 23:00 Salta = 02:00 UTC next day. Use 02:00 UTC to verify rejection.
        utc_time = datetime(2026, 5, 8, 2, 0, 0, tzinfo=_UTC)
        assert guard.is_active_now(utc_time) is False


class TestActiveHoursGuardConfigurable:
    """Custom start/end/tz are respected."""

    def test_custom_window(self):
        """A custom 09:00–18:00 window is enforced correctly."""
        guard = _make_guard(start="09:00", end="18:00")
        assert guard.is_active_now(_dt(8, 59)) is False  # before start
        assert guard.is_active_now(_dt(9, 0)) is True   # at start (inclusive)
        assert guard.is_active_now(_dt(17, 59)) is True  # before end
        assert guard.is_active_now(_dt(18, 0)) is False  # at end (exclusive)

    def test_is_active_now_is_boolean(self):
        """is_active_now() always returns a plain bool, not a truthy object."""
        guard = _make_guard()
        result = guard.is_active_now(_dt(12, 0))
        assert type(result) is bool
