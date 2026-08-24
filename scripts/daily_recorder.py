"""
Instrumentation for the daily flow: records what ran, what it produced, and
what went out — into data/mgmt.db, for the admin panel to read back.

THE ONE RULE (RF-01): this module must never be the reason a report fails.

Everything here is best-effort. A dead database, a schema that drifted, a field
nobody defined — all of it is caught, logged at WARNING, and dropped. The daily
keeps running. The contract is enforced in exactly ONE place, RunRecorder.emit(),
so the call sites inside run_daily.py stay one line each and carry no try/except
of their own (design decision E2).

The one thing it does NOT swallow is the daily's own failure: an exception
raised inside `with recording_run(...)` is re-raised untouched. The only
difference instrumentation makes is that a row now says it happened.

Two axes, never merged (RF-04):
    status          — what happened to GENERATION (running/success/error/…)
    delivery_status — what happened to DELIVERY, plus delivery_gate saying
                      which gate blocked it

A report that was built correctly and then held back by the RAM guard is a
success that was suppressed. Collapsing that into one column loses the half
that tells you whether to go fix something.

NOT WIRED UP YET. `scripts/run_daily.py` does not import this module: adding
the hooks means editing the script systemd runs at 07:00, which is its own
work unit. Until that lands, nothing here executes outside the test suite, and
run_artifacts (RF-05) stays empty — artifact discovery belongs to the
service_done hook.

Intended use from run_daily.py (design decision E1 — a ContextVar handle, so
no existing function signature has to change):

    with recording_run(hoy=hoy, test_mode=test_mode, solo_canal=...) as rec:
        emit("run_meta", overrides=overrides)
        ...
        emit("service_start", service=svc.nombre, fecha_modo=svc.fecha_modo)
        emit("gate", service=svc.nombre, delivery_gate="ram_guard_whatsapp")
        emit("service_done", service=svc.nombre, exit_code=code, enviar=enviar)
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.daily_store import (
    DailyRun,
    DailyRunService,
    init_daily_store,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

# Local git reads; anything slower than this is a hung command, not a slow one.
_GIT_TIMEOUT_SECONDS = 5

# Retention for the daily's own logs (RF-07).
#
# Its own SUBDIRECTORY, not data/runs/ itself. That directory belongs to
# src/api/runner.py, which writes {timestamp}-{slug}.log for manual panel runs
# and records the path in runs.log_path — a NOT NULL column no sweep can
# repair. And the two names are not distinguishable: runner builds its slug
# from a config's "tipo" field, which is editable through /mgmt/configs, so a
# config named "daily" would produce a filename identical to ours. A pattern
# cannot separate them; a directory can.
RUNS_DIR = ROOT / "data" / "runs" / "daily"
_LOG_MAX_AGE_DAYS = 60
_LOG_MAX_TOTAL_MB = 500
_SECONDS_PER_DAY = 86_400

# Fields a call site may write directly. Everything else about a row —
# status, timestamps, duration, delivery_status, orden — is derived here, so a
# hook cannot claim an outcome the recorder did not observe.
_SERVICE_WRITABLE = frozenset({
    "fecha_modo",
    "fecha_desde",
    "fecha_hasta",
    "exit_code",
    # No event sets status='skipped': a skipped service writes no row at all,
    # and the read side rebuilds it from overrides_snapshot (design decision
    # E5). skip_reason stays writable for that read side and for a future
    # explicit skip hook — the recorder itself never fills it.
    "skip_reason",
    "delivery_gate",
    "delivery_gate_detail",
    "error_repr",
    "error_traceback",
    "log_path",
})

_RUN_WRITABLE = frozenset({"exit_code", "log_path"})

_FAILED_STATUSES = frozenset({"error", "exception"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mem_available_mb() -> Optional[int]:
    """MemAvailable in MB, or None where /proc/meminfo cannot be read.

    Read here rather than imported from run_daily.py: the recorder must not
    depend on the module it instruments.
    """
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _git(*args: str) -> Optional[str]:
    """Run a read-only git command against THIS repository.

    Always `-C <ROOT>`: systemd chooses the working directory this process
    starts in, and reading whatever repository happens to sit under it would
    record the state of the wrong tree.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            shell=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("daily_recorder: git %s failed (non-fatal): %r", args, exc)
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _git_metadata() -> dict[str, Any]:
    """Branch, sha and dirtiness — each column independently None on failure."""
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    sha = _git("rev-parse", "HEAD")
    porcelain = _git("status", "--porcelain")
    return {
        "git_branch": branch,
        "git_sha": sha,
        # None, not False: "we could not look" is not "the tree is clean".
        "git_dirty": None if porcelain is None else bool(porcelain),
    }


def _derive_delivery_status(
    delivery_gate: Optional[str],
    fields: dict,
    *,
    test_mode: bool = False,
    solo_canal: Optional[str] = None,
) -> str:
    """Answer the second question: did this actually reach anyone?

    test_mode and solo_canal are properties of the RUN, and the run already
    knows them — they are taken from the recorder, not from the hook. Reading
    them out of the per-event fields made a whole test-mode run record
    delivery_status='sent' for every service while nothing left the building,
    because the call site had no reason to repeat what it already passed to
    recording_run(). Per-event values still win when a hook supplies one.

    Order matters: test_mode beats everything, because nothing reached a real
    recipient regardless of what the config said.
    """
    if fields.get("test_mode", test_mode):
        return "test_redirect"
    if not fields.get("enviar"):
        # A gate blocked it, or nothing was ever configured to send. Those are
        # different problems and lead to different fixes.
        return "suppressed" if delivery_gate else "none_configured"
    if fields.get("solo_canal", solo_canal):
        return "partial"
    return "sent"


class RunRecorder:
    """Writes one daily run and its services. Never raises."""

    def __init__(
        self,
        engine,
        run_id: str,
        started_at: datetime,
        *,
        test_mode: bool = False,
        solo_canal: Optional[str] = None,
    ):
        self._engine = engine
        self.run_id = run_id
        self.started_at = started_at
        # Run-level delivery context. Held here so the hooks do not have to
        # repeat what recording_run() was already told — see
        # _derive_delivery_status().
        self._test_mode = bool(test_mode)
        self._solo_canal = solo_canal

    # -- the isolation contract lives here, and only here (E2) --------------

    def emit(self, event: str, service: Optional[str] = None, **fields: Any) -> None:
        try:
            if service is None:
                self._update_run(event, fields)
            else:
                self._upsert_service(event, service, fields)
        except Exception as exc:  # noqa: BLE001 — deliberate: see module docstring
            logger.warning(
                "daily_recorder: emit(%s, service=%s) failed (non-fatal): %r",
                event,
                service,
                exc,
            )

    # -- run-level ----------------------------------------------------------

    def _update_run(self, event: str, fields: dict) -> None:
        values: dict[str, Any] = {}

        if event == "run_meta":
            overrides = fields.get("overrides")
            if overrides is not None:
                values["overrides_snapshot"] = json.dumps(
                    overrides, default=str, ensure_ascii=False
                )
            values.update(_git_metadata())
            values["host_mem_available_mb"] = _mem_available_mb()

        values.update({k: v for k, v in fields.items() if k in _RUN_WRITABLE})
        if not values:
            return

        with Session(self._engine) as session:
            row = session.get(DailyRun, self.run_id)
            if row is None:
                return
            for key, value in values.items():
                setattr(row, key, value)
            session.commit()

    # -- service-level ------------------------------------------------------

    def _upsert_service(self, event: str, servicio: str, fields: dict) -> None:
        """One row per (run_id, servicio) — every later event updates it (E4)."""
        now = _utcnow()

        with Session(self._engine) as session:
            row = session.execute(
                select(DailyRunService).where(
                    DailyRunService.run_id == self.run_id,
                    DailyRunService.servicio == servicio,
                )
            ).scalar_one_or_none()

            if row is None:
                next_orden = session.execute(
                    select(func.max(DailyRunService.orden)).where(
                        DailyRunService.run_id == self.run_id
                    )
                ).scalar()
                row = DailyRunService(
                    run_id=self.run_id,
                    servicio=servicio,
                    orden=(next_orden or 0) + 1,
                    status="running",
                )
                session.add(row)

            for key, value in fields.items():
                if key in _SERVICE_WRITABLE:
                    setattr(row, key, value)

            if event == "service_start":
                row.status = "running"
                row.started_at = now.isoformat()

            elif event == "service_done":
                # Delivery is answered even when generation is unclear: the two
                # axes are independent and one missing reading must not blank
                # out the other.
                row.delivery_status = _derive_delivery_status(
                    row.delivery_gate,
                    fields,
                    test_mode=self._test_mode,
                    solo_canal=self._solo_canal,
                )
                exit_code = fields.get("exit_code")
                if exit_code is None:
                    # A done hook that could not report a code told us nothing.
                    # The row stays 'running' — literally true, and it makes the
                    # run close 'partial' so someone goes looking.
                    logger.warning(
                        "daily_recorder: service_done for %s carried no exit code",
                        servicio,
                    )
                else:
                    row.status = "success" if exit_code == 0 else "error"
                    self._finish(row, now)

            elif event == "service_exception":
                row.status = "exception"
                self._finish(row, now)
                # delivery_status is deliberately left as it stands. This hook
                # fires from an except block that knows nothing about whether
                # anything was sent, and a crash can land on either side of the
                # send. NULL reads as "we never got that far", which is true;
                # any value here would be invented. If a gate already fired,
                # delivery_gate still says so.

            session.commit()

    @staticmethod
    def _finish(row: DailyRunService, now: datetime) -> None:
        row.finished_at = now.isoformat()
        if row.started_at:
            started = datetime.fromisoformat(row.started_at)
            row.duration_ms = int((now - started).total_seconds() * 1000)

    # -- closing ------------------------------------------------------------

    def _safe_close(self, status: Optional[str] = None, exit_code: Optional[int] = None) -> None:
        try:
            self._close(status, exit_code)
        except Exception as exc:  # noqa: BLE001 — same contract as emit()
            logger.warning("daily_recorder: closing run %s failed (non-fatal): %r", self.run_id, exc)

    def _close(self, status: Optional[str], exit_code: Optional[int]) -> None:
        now = _utcnow()
        with Session(self._engine) as session:
            row = session.get(DailyRun, self.run_id)
            if row is None:
                return
            if status is None:
                status = self._aggregate_status(session)
            row.status = status
            row.finished_at = now.isoformat()
            if exit_code is not None:
                row.exit_code = exit_code
            session.commit()

    def _aggregate_status(self, session: Session) -> str:
        """Derive the run's outcome from its children (E6).

        A service still 'running' at closing time never reported back. That is
        neither a success nor a failure, and calling it either would be the
        exact kind of guess this panel exists to stop making — so it counts as
        "not everything is accounted for".
        """
        statuses = list(
            session.execute(
                select(DailyRunService.status).where(
                    DailyRunService.run_id == self.run_id
                )
            ).scalars()
        )
        failed = sum(1 for s in statuses if s in _FAILED_STATUSES)
        succeeded = sum(1 for s in statuses if s == "success")
        unreported = sum(1 for s in statuses if s == "running")

        if failed:
            return "partial" if succeeded else "error"
        if unreported:
            return "partial" if succeeded else "interrupted"
        return "success"


class NullRecorder(RunRecorder):
    """What you get when the store could not be opened. Records nothing.

    Subclasses RunRecorder so the call sites cannot tell the difference — the
    daily behaves identically whether or not instrumentation is working.
    """

    def __init__(self, run_id: str, started_at: datetime):
        super().__init__(engine=None, run_id=run_id, started_at=started_at)

    def emit(self, event: str, service: Optional[str] = None, **fields: Any) -> None:
        return

    def _safe_close(self, status: Optional[str] = None, exit_code: Optional[int] = None) -> None:
        return

    # Every inherited path that would touch self._engine is stubbed out too.
    # emit() and _safe_close() are the only entry points today, but leaving
    # live database code reachable on an object whose engine is None is a trap
    # for whoever adds the next one.
    def _update_run(self, event: str, fields: dict) -> None:
        return

    def _upsert_service(self, event: str, servicio: str, fields: dict) -> None:
        return

    def _close(self, status: Optional[str], exit_code: Optional[int]) -> None:
        return


# ---------------------------------------------------------------------------
# Log pruning (RF-07)
# ---------------------------------------------------------------------------


def _unlink(path: Path) -> bool:
    """Delete one log. A file we cannot remove must not stop the others."""
    try:
        path.unlink()
        return True
    except OSError as exc:
        logger.warning("daily_recorder: could not delete %s (non-fatal): %r", path, exc)
        return False


def _resolve_log(stored: str) -> Path:
    """Rows may hold a path relative to the project root."""
    path = Path(stored)
    return path if path.is_absolute() else ROOT / path


def _delete_stale_logs(runs_dir: Path, max_age_days: float, max_total_mb: float) -> None:
    """Age first, then total size — whichever bites, oldest goes first."""
    if not runs_dir.is_dir():
        return

    entries: list[tuple[float, int, Path]] = []
    for path in runs_dir.glob("*.log"):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
    entries.sort(key=lambda entry: entry[0])  # oldest first

    cutoff = time.time() - max_age_days * _SECONDS_PER_DAY
    survivors: list[tuple[float, int, Path]] = []
    for entry in entries:
        mtime, _, path = entry
        if mtime < cutoff and _unlink(path):
            continue
        survivors.append(entry)

    budget = max_total_mb * 1024 * 1024
    total = sum(size for _, size, _ in survivors)
    for _, size, path in survivors:
        if total <= budget:
            break
        if _unlink(path):
            total -= size


def _sweep_missing_log_pointers(engine) -> None:
    """NULL every log_path whose file is gone, whoever removed it.

    A row promising a log that does not exist is a 404 waiting to happen in the
    panel. Checking existence rather than replaying what this function just
    deleted also repairs logs taken by logrotate, tmpfiles or a human.
    """
    with Session(engine) as session:
        for model in (DailyRun, DailyRunService):
            rows = session.execute(
                select(model).where(model.log_path.is_not(None))
            ).scalars()
            for row in rows:
                if not _resolve_log(row.log_path).exists():
                    row.log_path = None
        session.commit()


def _prune_logs(
    runs_dir: Path,
    engine,
    max_age_days: float = _LOG_MAX_AGE_DAYS,
    max_total_mb: float = _LOG_MAX_TOTAL_MB,
) -> None:
    """Housekeeping: delete old log FILES, keep every ROW.

    A run's outcome stays interesting for months; its stdout for about a week.
    So the history never shrinks — only the text does.

    Two independent try/excepts on purpose: a database that cannot be swept is
    no reason to let the disk keep filling.
    """
    try:
        _delete_stale_logs(Path(runs_dir), max_age_days, max_total_mb)
    except Exception as exc:  # noqa: BLE001 — same contract as emit()
        logger.warning("daily_recorder: log pruning failed (non-fatal): %r", exc)

    try:
        _sweep_missing_log_pointers(engine)
    except Exception as exc:  # noqa: BLE001 — same contract as emit()
        logger.warning("daily_recorder: log pointer sweep failed (non-fatal): %r", exc)


_current: ContextVar[Optional[RunRecorder]] = ContextVar("_current_recorder", default=None)


def _new_run_id(started_at: datetime) -> str:
    return f"{started_at.strftime('%Y%m%d-%H%M%S')}-daily"


def _default_engine():
    from src.api.db import get_default_engine

    return get_default_engine()


def _open_recorder(
    *,
    hoy: str,
    test_mode: bool,
    triggered_by: str,
    solo_canal: Optional[str],
    engine,
) -> RunRecorder:
    """Open the run row. Degrades to NullRecorder rather than raising."""
    started_at = _utcnow()
    run_id = _new_run_id(started_at)

    try:
        if engine is None:
            engine = _default_engine()
        init_daily_store(engine)
        # Housekeeping rides the run that is about to start: it is the one
        # moment this code is guaranteed to execute, and it never raises.
        _prune_logs(RUNS_DIR, engine)
        with Session(engine) as session:
            session.add(
                DailyRun(
                    id=run_id,
                    started_at=started_at.isoformat(),
                    status="running",
                    triggered_by=triggered_by,
                    test_mode=bool(test_mode),
                    hoy=hoy,
                    solo_canal=solo_canal,
                )
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001 — same contract as emit()
        logger.warning(
            "daily_recorder: could not open the run store (non-fatal, "
            "instrumentation disabled for this run): %r",
            exc,
        )
        return NullRecorder(run_id=run_id, started_at=started_at)

    return RunRecorder(
        engine=engine,
        run_id=run_id,
        started_at=started_at,
        test_mode=test_mode,
        solo_canal=solo_canal,
    )


@contextmanager
def recording_run(
    *,
    hoy: str,
    test_mode: bool,
    triggered_by: str = "schedule",
    solo_canal: Optional[str] = None,
    engine=None,
):
    """Record one daily run.

    An exception from the wrapped body is recorded and then re-raised
    unchanged: the daily still fails exactly as it did before this module
    existed.
    """
    rec = _open_recorder(
        hoy=hoy,
        test_mode=test_mode,
        triggered_by=triggered_by,
        solo_canal=solo_canal,
        engine=engine,
    )
    token = _current.set(rec)
    try:
        yield rec
    except BaseException:
        rec._safe_close(status="error")
        raise
    else:
        rec._safe_close(status=None)  # None -> aggregate from the services
    finally:
        _current.reset(token)


def emit(event: str, service: Optional[str] = None, **fields: Any) -> None:
    """Record one event against the run currently being recorded.

    Inert outside `recording_run()`, so run_daily.py can call it
    unconditionally — including from a manual invocation nobody is recording.
    """
    rec = _current.get()
    if rec is not None:
        rec.emit(event, service, **fields)
