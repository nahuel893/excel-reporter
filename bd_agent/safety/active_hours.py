"""bd_agent/safety/active_hours.py — Active-hours guard for the BD Agent.

Implements RF-042: the agent only replies between active_hours_start and
active_hours_end in the configured timezone (default America/Argentina/Salta).
Outside this window, messages are dropped (no reply, no queue).

is_active_now(now: datetime) -> bool:
  - Accepts a timezone-aware datetime (any tz; will be converted to configured tz).
  - Returns True iff start <= local_time < end.
  - Boundary: start is INCLUSIVE, end is EXCLUSIVE.

Zero imports from src.* (RF-070). Deps: stdlib (datetime, zoneinfo).
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


def _parse_hhmm(value: str, label: str) -> time:
    """Parse 'HH:MM' string into a time object. Raises ValueError on bad format."""
    try:
        hour, minute = value.split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            f"Invalid {label} format {value!r}; expected 'HH:MM'"
        ) from exc


class ActiveHoursGuard:
    """Enforces a configurable active-hours window in the specified timezone.

    Args:
        start: active window start in 'HH:MM' format (inclusive).
        end: active window end in 'HH:MM' format (exclusive).
        tz: IANA timezone string (e.g. 'America/Argentina/Salta').
    """

    def __init__(
        self,
        start: str = "07:00",
        end: str = "22:00",
        tz: str = "America/Argentina/Salta",
    ) -> None:
        self._tz = ZoneInfo(tz)
        self._start: time = _parse_hhmm(start, "active_hours_start")
        self._end: time = _parse_hhmm(end, "active_hours_end")

    def is_active_now(self, now: datetime) -> bool:
        """Return True iff *now* falls within the configured active-hours window.

        Args:
            now: a timezone-aware datetime (UTC or any tz — will be converted).

        Returns:
            True if start <= local_time < end, False otherwise.
        """
        local_time = now.astimezone(self._tz).time()
        return bool(self._start <= local_time < self._end)
