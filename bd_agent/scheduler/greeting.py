"""bd_agent/scheduler/greeting.py — Daily greeting job for the BD Agent (T-090).

GreetingJob iterates all contacts and sends a morning greeting to those who:
  1. Have not received a message in the last 1 hour (LastActivityStore check — RF-053)
  2. Are within active hours (ActiveHoursGuard — RF-052)
  3. Are within their daily rate limit (RateLimiter — RF-052)

Per-contact errors are caught and logged; they do NOT stop the loop.

Design principles:
  - Zero imports from src.* (RF-070)
  - All dependencies injected (testable with fakes/mocks)
  - APScheduler coupling lives in bd_agent/wiring.py, NOT here
  - now_fn is injectable for frozen-clock tests

Factory:
  build_greeting_job(contacts_repo, messaging, active_hours, rate_limiter,
                     activity_store, now_fn=None) -> GreetingJob

InMemoryLastActivityStore provides a simple in-memory implementation of the
LastActivityStore Protocol (defined in bd_agent.contracts).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Minimum inactivity window before sending a greeting (RF-053)
_MIN_INACTIVE_SECONDS = 3600  # 1 hour

# Greeting template (Rioplatense Spanish, as per T-090 spec)
_GREETING_TEMPLATE = """\
👋 Buen día, {first_name}!

Soy el *Asistente de Análisis de Datos de Badie*. Estoy disponible para responder consultas sobre ventas, clientes, artículos y cobertura.

Preguntame lo que necesités — por ejemplo:
• "¿Cuántas ventas tuvo el cliente 1234 en mayo?"
• "Listame los artículos del genérico CERVEZAS"
• "Cobertura del mes pasado en Salta"

🤖 Bot de Análisis de Datos"""


# ---------------------------------------------------------------------------
# InMemoryLastActivityStore
# ---------------------------------------------------------------------------

class InMemoryLastActivityStore:
    """Simple in-memory implementation of the LastActivityStore Protocol.

    Thread-safety: designed for single-process use. No locking.
    """

    def __init__(self) -> None:
        self._store: dict[str, datetime] = {}

    def last_seen(self, jid: str) -> Optional[datetime]:
        """Return the last recorded activity datetime for *jid*, or None."""
        return self._store.get(jid)

    def record(self, jid: str, when: datetime) -> None:
        """Record *when* as the most recent activity for *jid*."""
        self._store[jid] = when


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _first_name(full_name: str) -> str:
    """Extract the first word from a full name string.

    Examples:
        "Walter Vilte"       -> "Walter"
        "Maria De Los Angeles" -> "Maria"
        "Walter"             -> "Walter"
        ""                   -> ""
    """
    if not full_name:
        return ""
    return full_name.split()[0]


def _render_greeting(first_name: str) -> str:
    """Render the greeting template with the contact's first name."""
    return _GREETING_TEMPLATE.format(first_name=first_name)


# ---------------------------------------------------------------------------
# GreetingJob
# ---------------------------------------------------------------------------

class GreetingJob:
    """Sends a daily morning greeting to all eligible contacts.

    Args:
        contacts_repo: ContactsRepo — provides list_all() for iteration.
        messaging:     MessagingGateway — delivers outbound text.
        active_hours:  ActiveHoursGuard — active-hours check per RF-052.
        rate_limiter:  RateLimiter — daily budget check per RF-052.
        activity_store: LastActivityStore — tracks last outbound activity per RF-053.
        now_fn: Injectable clock (defaults to UTC now). Useful for frozen-clock tests.
    """

    def __init__(
        self,
        contacts_repo,         # ContactsRepo protocol
        messaging,             # MessagingGateway protocol
        active_hours,          # ActiveHoursGuard
        rate_limiter,          # RateLimiter
        activity_store,        # LastActivityStore protocol
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._contacts_repo = contacts_repo
        self._messaging = messaging
        self._active_hours = active_hours
        self._rate_limiter = rate_limiter
        self._activity_store = activity_store
        self._now_fn: Callable[[], datetime] = (
            now_fn if now_fn is not None else (lambda: datetime.now(timezone.utc))
        )

    def run(self) -> None:
        """Execute the greeting run — iterates all contacts and sends greetings.

        Errors on individual contacts are caught and logged; the loop continues
        to process the remaining contacts.
        """
        now = self._now_fn()

        # Check active hours once before the loop — if we're outside, skip all
        if not self._active_hours.is_active_now(now):
            logger.info(
                "greeting_skipped_outside_active_hours",
                extra={"reason": "outside_active_hours"},
            )
            return

        contacts = self._contacts_repo.list_all()
        logger.info("greeting_job_start", extra={"contact_count": len(contacts)})

        for contact in contacts:
            try:
                self._send_to_contact(contact, now)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "greeting_contact_error",
                    extra={
                        "jid": contact.jid[:8] + "...",  # partial for privacy
                        "error": str(exc),
                    },
                )

        logger.info("greeting_job_done")

    def _send_to_contact(self, contact, now: datetime) -> None:
        """Attempt to send a greeting to a single contact.

        Skips silently (with a log entry) if any guard rejects.
        """
        jid = contact.jid

        # RF-053: skip if already contacted in the last hour
        last = self._activity_store.last_seen(jid)
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < _MIN_INACTIVE_SECONDS:
                logger.debug(
                    "greeting_skipped_recent_activity",
                    extra={"jid": jid[:8] + "...", "elapsed_s": int(elapsed)},
                )
                return

        # RF-052: rate limit check
        if not self._rate_limiter.allow(jid):
            logger.info(
                "greeting_skipped_rate_limit",
                extra={"jid": jid[:8] + "...", "reason": "daily_limit_reached"},
            )
            return

        # Render and send
        first = _first_name(contact.name)
        text = _render_greeting(first)
        self._messaging.send_text(jid, text)

        logger.debug(
            "greeting_sent",
            extra={"jid": jid[:8] + "..."},
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_greeting_job(
    contacts_repo,
    messaging,
    active_hours,
    rate_limiter,
    activity_store,
    now_fn: Optional[Callable[[], datetime]] = None,
) -> GreetingJob:
    """Factory: build and return a GreetingJob with the given dependencies.

    This is the DI entry-point used by wiring.py. APScheduler registers
    ``job.run`` as the cron callable — no APScheduler import here.
    """
    return GreetingJob(
        contacts_repo=contacts_repo,
        messaging=messaging,
        active_hours=active_hours,
        rate_limiter=rate_limiter,
        activity_store=activity_store,
        now_fn=now_fn,
    )
