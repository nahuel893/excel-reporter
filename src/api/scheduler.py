"""
APScheduler integration for the management UI.

Provides:
    build_scheduler(engine) — BackgroundScheduler with SQLAlchemyJobStore
    prune_old_runs(engine, max_runs) — log rotation (keep last N)
    daily_master_job(runner, engine, configs_dir) — sequential daily runs
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from src.api.runner import RunRegistry

logger = logging.getLogger(__name__)

_DEFAULT_TIMEZONE = "America/Argentina/Salta"
_DEFAULT_CONFIGS_DIR = Path("configs")
_SKIP_CONFIG_FILES = {"daily_overrides.json", "contactos.json", "daily_overrides.example.json"}


def build_scheduler(engine=None) -> BackgroundScheduler:
    """Create a BackgroundScheduler with SQLAlchemyJobStore backed by data/mgmt.db.

    On first startup, seeds the 'daily-master' job at 0 7 * * 1-5.
    """
    if engine is None:
        from src.api.db import get_default_engine
        engine = get_default_engine()

    jobstores = {
        "default": SQLAlchemyJobStore(engine=engine, tablename="apscheduler_jobs"),
    }

    sched = BackgroundScheduler(
        jobstores=jobstores,
        timezone=_DEFAULT_TIMEZONE,
    )

    return sched


def seed_daily_master_job(sched: BackgroundScheduler) -> None:
    """Add the 'daily-master' job if it doesn't already exist."""
    if sched.get_job("daily-master") is None:
        sched.add_job(
            func=_daily_master_placeholder,
            trigger="cron",
            id="daily-master",
            hour=7,
            minute=0,
            day_of_week="mon-fri",
            replace_existing=True,
        )
        logger.info("Seeded 'daily-master' cron job at 0 7 * * 1-5")


def _daily_master_placeholder():
    """Placeholder function for daily-master job.

    The actual daily_master_job() is called by the FastAPI startup hook
    with the RunRegistry instance injected.
    """
    logger.info("daily-master fired (placeholder — use daily_master_job() directly)")


async def daily_master_job(
    runner: RunRegistry,
    engine=None,
    configs_dir: Path | None = None,
) -> None:
    """Sequential daily orchestrator.

    Reads configs/daily_overrides.json, iterates configs/*.json,
    skips if ejecutar=false, runs each config sequentially.
    """
    configs_dir = configs_dir or _DEFAULT_CONFIGS_DIR
    overrides = _load_overrides(configs_dir)

    config_files = sorted(
        p for p in configs_dir.glob("*.json")
        if p.name not in _SKIP_CONFIG_FILES
    )

    for config_path in config_files:
        entry = overrides.get(config_path.name, {})

        if entry.get("ejecutar") is False:
            reason = entry.get("razon", "no reason given")
            logger.info(
                "Daily: skipping %s (ejecutar=false, razon=%s)",
                config_path.name, reason,
            )
            continue

        no_delivery = entry.get("enviar") is False

        try:
            run_id = await runner.trigger(
                config_filename=str(config_path),
                triggered_by="schedule",
                no_delivery=no_delivery,
                test_mode=False,
            )
            logger.info("Daily: started %s → run_id=%s", config_path.name, run_id)
            await runner.wait_for(run_id)
            logger.info("Daily: completed %s → run_id=%s", config_path.name, run_id)
        except Exception as exc:
            logger.warning(
                "Daily: error running %s: %s", config_path.name, exc
            )


def _load_overrides(configs_dir: Path) -> dict:
    """Load daily_overrides.json, returning {} if not found or invalid."""
    path = configs_dir / "daily_overrides.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Filter out comment keys (starting with _)
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception as e:
        logger.warning("Could not load daily_overrides.json: %s", e)
        return {}


def prune_old_runs(engine=None, max_runs: int = 200) -> int:
    """Delete oldest runs beyond max_runs. Also deletes their log files.

    Returns the number of rows deleted.
    """
    if engine is None:
        from src.api.db import get_default_engine
        engine = get_default_engine()

    with Session(engine) as session:
        count_row = session.execute(text("SELECT COUNT(*) FROM runs")).fetchone()
        total = count_row[0] if count_row else 0

        if total <= max_runs:
            return 0

        excess = total - max_runs
        oldest = session.execute(
            text(
                "SELECT id, log_path FROM runs ORDER BY started_at ASC LIMIT :n"
            ),
            {"n": excess},
        ).fetchall()

        for run_id, log_path in oldest:
            # Delete log file
            if log_path:
                p = Path(log_path)
                if p.exists():
                    try:
                        p.unlink()
                    except Exception as e:
                        logger.warning("Could not delete log %s: %s", log_path, e)
            # Delete DB row
            session.execute(
                text("DELETE FROM runs WHERE id = :id"),
                {"id": run_id},
            )

        session.commit()
        logger.info("Pruned %d old run(s)", len(oldest))
        return len(oldest)
