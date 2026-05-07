"""bd_agent/wiring.py — Dependency-injection factory for the BD Agent (T-073).

``build_agent_runtime(config)`` assembles the full dependency graph:

  1. Reads ``GEMINI_API_KEY`` and ``AGENT_DB_URL`` from the environment.
  2. Returns ``None`` (with a warning log) if either is missing — the caller
     (api.py) should skip mounting the /agent router in that case.
  3. On success, returns an ``AgentRuntime`` dataclass containing:
       - ``agent_turn``    — AgentTurn (the orchestrator)
       - ``contacts_repo`` — JsonContactsRepo (the allowlist)
       - ``db_gateway``    — PgDatabaseGateway
       - ``router``        — FastAPI APIRouter (ready to mount)

Isolation rules:
  - This is the ONLY module inside bd_agent/ allowed to read ``os.environ``
    for ``GEMINI_API_KEY`` and ``AGENT_DB_URL``.
  - Zero imports from src.* (RF-070).
"""
from __future__ import annotations

import dataclasses
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default paths (relative to the project root, resolved at runtime)
_DEFAULT_CONTACTS_PATH = Path(__file__).parent.parent / "configs" / "contactos_agente.json"
_DEFAULT_SCHEMA_DOC_PATH = Path(__file__).parent.parent / "CONTEXT_DATABASE.md"


@dataclasses.dataclass
class AgentRuntime:
    """Container for the fully-wired BD Agent runtime components.

    Attributes:
        agent_turn:    The AgentTurn orchestrator — call handle_incoming().
        contacts_repo: JsonContactsRepo — the live allowlist.
        db_gateway:    PgDatabaseGateway — DB access + schema doc.
        router:        FastAPI APIRouter — ready to mount at ``/agent``.
        messaging:     MessagingGateway — outbound WhatsApp transport (shared
                       between AgentTurn and GreetingJob).
    """

    agent_turn: object
    contacts_repo: object
    db_gateway: object
    router: object
    messaging: object = dataclasses.field(default=None)


def build_agent_runtime(
    contacts_path: Optional[Path] = None,
    schema_doc_path: Optional[Path] = None,
) -> Optional[AgentRuntime]:
    """Build the full BD Agent dependency graph.

    Returns:
        ``AgentRuntime`` if all required env vars are present and all components
        initialise successfully, or ``None`` if any required env var is missing.

    Args:
        contacts_path: Override path to ``contactos_agente.json``.
            Defaults to ``configs/contactos_agente.json`` relative to the project root.
        schema_doc_path: Override path to ``CONTEXT_DATABASE.md``.
            Defaults to the project root ``CONTEXT_DATABASE.md``.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY")
    agent_db_url = os.environ.get("AGENT_DB_URL")

    missing = []
    if not gemini_key:
        missing.append("GEMINI_API_KEY")
    if not agent_db_url:
        missing.append("AGENT_DB_URL")

    if missing:
        logger.warning(
            "BD Agent not started: missing env vars %s. "
            "Set them in .env to enable the /agent router.",
            ", ".join(missing),
        )
        return None

    contacts_path = contacts_path or _DEFAULT_CONTACTS_PATH
    schema_doc_path = schema_doc_path or _DEFAULT_SCHEMA_DOC_PATH

    try:
        return _build(
            gemini_key=gemini_key,
            contacts_path=contacts_path,
            schema_doc_path=schema_doc_path,
        )
    except Exception as exc:
        logger.warning(
            "BD Agent failed to initialise: %s — /agent router will NOT be mounted.",
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Private implementation
# ---------------------------------------------------------------------------


def _build(
    gemini_key: str,
    contacts_path: Path,
    schema_doc_path: Path,
) -> AgentRuntime:
    """Construct the full dependency graph. Raises on any initialisation error."""
    # Lazy imports to avoid slow startup when the agent is not configured
    from bd_agent.contacts.repo import JsonContactsRepo
    from bd_agent.contacts.schema import ContactsFile
    from bd_agent.conversation.history import InMemoryHistory
    from bd_agent.conversation.system_prompt import build_system_prompt
    from bd_agent.integrations.database import PgDatabaseGateway
    from bd_agent.integrations.messaging import WhatsAppMessagingGateway
    from bd_agent.llm.gemini import GeminiProvider
    from bd_agent.safety.active_hours import ActiveHoursGuard
    from bd_agent.safety.allowlist import AllowlistGuard
    from bd_agent.safety.guard import SafetyGuard
    from bd_agent.safety.rate_limiter import RateLimiter
    from bd_agent.tools.curated import register_all_into
    from bd_agent.tools.registry import ToolRegistry
    from bd_agent.tools.sql_fallback import register_into as register_sql_fallback
    from bd_agent.transport.router import make_router
    from bd_agent.agent import AgentTurn  # noqa: F401 (used below)

    # ------------------------------------------------------------------
    # 0. Install rotating error log handler (RF-091)
    # ------------------------------------------------------------------
    from bd_agent.observability.logger import setup_error_log_handler

    _errors_log_path = Path(__file__).parent / "errors.log"
    _error_handler = setup_error_log_handler(log_path=_errors_log_path)
    _bd_agent_root_logger = logging.getLogger("bd_agent")
    # Install only once (avoid duplicates on repeated calls, e.g. during tests)
    from logging.handlers import RotatingFileHandler as _RFH
    if not any(isinstance(h, _RFH) for h in _bd_agent_root_logger.handlers):
        _bd_agent_root_logger.addHandler(_error_handler)

    # ------------------------------------------------------------------
    # 1. Contacts repo — parses JSON and builds the allowlist
    # ------------------------------------------------------------------
    contacts_repo = JsonContactsRepo(path=contacts_path)

    # Read active-hours settings from the loaded contacts file
    import json
    raw = json.loads(contacts_path.read_text(encoding="utf-8"))
    settings = raw.get("settings", {})
    active_hours_start = settings.get("active_hours_start", "07:00")
    active_hours_end = settings.get("active_hours_end", "22:00")
    timezone_str = settings.get("timezone", "America/Argentina/Salta")

    # ------------------------------------------------------------------
    # 2. Safety layer
    # ------------------------------------------------------------------
    active_hours = ActiveHoursGuard(
        start=active_hours_start,
        end=active_hours_end,
        tz=timezone_str,
    )
    allowlist = AllowlistGuard(contacts_repo)
    rate_limiter = RateLimiter(
        daily_limit_resolver=lambda jid: (
            c.daily_message_limit
            if (c := contacts_repo.get(jid)) is not None
            else 100  # default per design
        )
    )

    # ------------------------------------------------------------------
    # 3. DB gateway + schema doc
    # ------------------------------------------------------------------
    db_gateway = PgDatabaseGateway(schema_doc_path=schema_doc_path)

    # ------------------------------------------------------------------
    # 4. Messaging gateway
    # ------------------------------------------------------------------
    baileys_base_url = os.environ.get("BAILEYS_BASE_URL", "http://localhost:3000")
    messaging = WhatsAppMessagingGateway(base_url=baileys_base_url)

    # ------------------------------------------------------------------
    # 5. Conversation history
    # ------------------------------------------------------------------
    history = InMemoryHistory(max_pairs=10, idle_timeout_seconds=3600)

    # ------------------------------------------------------------------
    # 6. Tool registry — curated + sql_fallback
    # ------------------------------------------------------------------
    tool_registry = ToolRegistry()
    register_all_into(tool_registry)
    register_sql_fallback(tool_registry)

    # ------------------------------------------------------------------
    # 7. LLM provider
    # ------------------------------------------------------------------
    # GeminiProvider reads GEMINI_API_KEY from os.environ automatically
    llm = GeminiProvider()

    # ------------------------------------------------------------------
    # 8. Schema doc loader (cached via db_gateway)
    # ------------------------------------------------------------------
    def schema_doc_loader() -> str:
        return db_gateway.get_schema_doc()

    # ------------------------------------------------------------------
    # 9. AgentTurn (orchestrator)
    # ------------------------------------------------------------------
    import time as _time

    def _production_delay_fn() -> None:
        """Real jitter delay (RF-040): expovariate(1/4) clamped [2, 30] seconds."""
        _time.sleep(rate_limiter.jitter())

    agent_turn = AgentTurn(
        allowlist=allowlist,
        active_hours=active_hours,
        rate_limiter=rate_limiter,
        history=history,
        contacts=contacts_repo,
        llm=llm,
        tool_registry=tool_registry,
        messaging=messaging,
        schema_doc_loader=schema_doc_loader,
        delay_fn=_production_delay_fn,
    )

    # ------------------------------------------------------------------
    # 10. FastAPI router
    # ------------------------------------------------------------------
    router = make_router(
        agent_turn=agent_turn,
        contacts_repo=contacts_repo,
        db_gateway=db_gateway,
    )

    return AgentRuntime(
        agent_turn=agent_turn,
        contacts_repo=contacts_repo,
        db_gateway=db_gateway,
        router=router,
        messaging=messaging,
    )


# ---------------------------------------------------------------------------
# Greeting job registration (T-091)
# ---------------------------------------------------------------------------


def register_greeting_job(scheduler, runtime: Optional[AgentRuntime]) -> None:
    """Register the daily greeting cron job on *scheduler*.

    If *runtime* is None (agent not configured), this is a safe no-op.

    Args:
        scheduler: An APScheduler BackgroundScheduler instance.
        runtime:   The AgentRuntime built by build_agent_runtime(), or None.

    The job fires at 08:00 Mon–Fri in Salta TZ (``greeting-agent`` ID).
    """
    if runtime is None:
        logger.warning(
            "register_greeting_job: runtime is None — greeting job NOT registered."
        )
        return

    try:
        from apscheduler.triggers.cron import CronTrigger

        from bd_agent.safety.active_hours import ActiveHoursGuard
        from bd_agent.safety.rate_limiter import RateLimiter
        from bd_agent.scheduler.greeting import (
            InMemoryLastActivityStore,
            build_greeting_job,
        )

        # Read active-hours settings from the contacts JSON (same as _build)
        import json
        from pathlib import Path

        contacts_path = _DEFAULT_CONTACTS_PATH
        try:
            raw = json.loads(contacts_path.read_text(encoding="utf-8"))
            settings = raw.get("settings", {})
        except Exception:
            settings = {}

        active_hours_start = settings.get("active_hours_start", "07:00")
        active_hours_end = settings.get("active_hours_end", "22:00")
        timezone_str = settings.get("timezone", "America/Argentina/Salta")

        active_hours = ActiveHoursGuard(
            start=active_hours_start,
            end=active_hours_end,
            tz=timezone_str,
        )

        rate_limiter = RateLimiter(
            daily_limit_resolver=lambda jid: (
                c.daily_message_limit
                if (c := runtime.contacts_repo.get(jid)) is not None
                else 100
            )
        )

        activity_store = InMemoryLastActivityStore()

        greeting_job = build_greeting_job(
            contacts_repo=runtime.contacts_repo,
            messaging=runtime.messaging,
            active_hours=active_hours,
            rate_limiter=rate_limiter,
            activity_store=activity_store,
        )

        trigger = CronTrigger(
            hour=8,
            minute=0,
            day_of_week="mon-fri",
            timezone=timezone_str,
        )

        scheduler.add_job(
            func=greeting_job.run,
            trigger=trigger,
            id="greeting-agent",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Registered 'greeting-agent' cron job at 08:00 Mon-Fri Salta TZ")

    except Exception as exc:
        logger.warning(
            "register_greeting_job: failed to register — %s. Greeting job NOT active.",
            exc,
        )
