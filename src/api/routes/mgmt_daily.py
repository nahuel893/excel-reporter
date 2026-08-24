"""
Management API routes: the read side of the daily-run store.

Endpoints:
    GET /mgmt/daily-runs                              — paginated history
    GET /mgmt/daily-runs/{id}                         — one run, services, artifacts
    GET /mgmt/daily-runs/{id}/services/{orden}/log    — one service's log

Read only. Nothing here writes; the writer is scripts/daily_recorder.py.

The one piece of real logic is rebuilding skips. A service the daily decided
not to run writes no row at all (design decision E5), so a detail response
assembled from rows alone would quietly show 12 services on a day 18 were
configured — and the six missing ones are the six most worth looking at. They
are reconstructed here, at read time, by crossing the service registry against
the overrides snapshot the run stored.

That reconstruction depends on importing scripts.run_daily. When the import
fails, the response says `skips_reconstructed: false` and lists only real rows,
rather than presenting a short list as if it were the whole story.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.daily_store import DailyRun, DailyRunService, RunArtifact

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mgmt")

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# The only directory this route will serve a file from. Rows are written by our
# own recorder and always point here, but a route that hands back whatever
# absolute path a row happens to hold is one bad UPDATE away from being the
# whole problem. Must stay equal to daily_recorder.RUNS_DIR — a test asserts it
# rather than importing across the layer.
_DEFAULT_LOG_ROOT = _PROJECT_ROOT / "data" / "runs" / "daily"
_log_root: Optional[Path] = None


def set_log_root(path: Optional[Path]) -> None:
    """Point log serving at another directory (tests). None restores the default."""
    global _log_root
    _log_root = Path(path) if path is not None else None


def _get_log_root() -> Path:
    return _log_root or _DEFAULT_LOG_ROOT


def _get_engine(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return engine


def _load_service_registry() -> Optional[list]:
    """The daily's service list, or None when it cannot be read.

    Imported lazily and defensively: scripts.run_daily pulls in the CLI and the
    config resolver, and an environment where that import fails should cost the
    panel its skip reconstruction, not its whole runs screen.
    """
    try:
        from scripts.run_daily import SERVICIOS

        return list(SERVICIOS)
    except Exception as exc:  # noqa: BLE001 — any import-time failure degrades the same
        logger.warning(
            "mgmt_daily: could not import the service registry, skips will not "
            "be reconstructed: %r",
            exc,
        )
        return None


def _parse_overrides(raw: Optional[str]) -> Optional[dict]:
    """The snapshot as a dict, or None when it will not parse.

    None means "we could not read it", which is why the caller must not treat
    it as an empty override set.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("mgmt_daily: overrides_snapshot is not valid JSON")
        return None
    return parsed if isinstance(parsed, dict) else None


def _run_summary(row: DailyRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "status": row.status,
        "exit_code": row.exit_code,
        "triggered_by": row.triggered_by,
        "test_mode": bool(row.test_mode),
        "hoy": row.hoy,
        "solo_canal": row.solo_canal,
        "git_branch": row.git_branch,
        "git_sha": row.git_sha,
        # Left as-is, including None: an unread git state is not a clean tree.
        "git_dirty": row.git_dirty,
    }


def _service_row(row: DailyRunService) -> dict[str, Any]:
    return {
        "id": row.id,
        "orden": row.orden,
        "servicio": row.servicio,
        "fecha_modo": row.fecha_modo,
        "fecha_desde": row.fecha_desde,
        "fecha_hasta": row.fecha_hasta,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "duration_ms": row.duration_ms,
        "status": row.status,
        "exit_code": row.exit_code,
        "skip_reason": row.skip_reason,
        "delivery_status": row.delivery_status,
        "delivery_gate": row.delivery_gate,
        "delivery_gate_detail": row.delivery_gate_detail,
        "error_repr": row.error_repr,
        "error_traceback": row.error_traceback,
        "has_log": row.log_path is not None,
        "is_synthetic": False,
    }


def _synthetic_skip(servicio: str, overrides: Optional[dict]) -> dict[str, Any]:
    """A service that wrote no row: it did not run.

    The reason is best-effort. The overrides file is not the only way a service
    gets skipped — a date gate can do it too — so an absent reason means "not
    recorded", never "no reason".
    """
    reason = None
    if isinstance(overrides, dict):
        entry = overrides.get(servicio)
        if isinstance(entry, dict):
            reason = entry.get("razon") or None
    return {
        "id": None,
        # No row, so nothing to address: the log endpoint is keyed by orden.
        "orden": None,
        "servicio": servicio,
        "fecha_modo": None,
        "fecha_desde": None,
        "fecha_hasta": None,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "status": "skipped",
        "exit_code": None,
        "skip_reason": reason,
        "delivery_status": None,
        "delivery_gate": None,
        "delivery_gate_detail": None,
        "error_repr": None,
        "error_traceback": None,
        "has_log": False,
        "is_synthetic": True,
    }


# ---------------------------------------------------------------------------
# GET /mgmt/daily-runs
# ---------------------------------------------------------------------------


@router.get("/daily-runs")
def list_daily_runs(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, max_length=40),
    desde: Optional[str] = Query(None, max_length=32),
    hasta: Optional[str] = Query(None, max_length=32),
) -> dict:
    """Daily-run history, newest first."""
    engine = _get_engine(request)

    filters = []
    if status:
        filters.append(DailyRun.status == status)
    if desde:
        filters.append(DailyRun.started_at >= desde)
    if hasta:
        # Inclusive of the whole day: started_at is a full ISO timestamp, so a
        # bare date as the upper bound would exclude everything after midnight.
        filters.append(DailyRun.started_at <= f"{hasta}T23:59:59.999999+00:00")

    with Session(engine) as session:
        total = session.execute(
            select(func.count()).select_from(DailyRun).where(*filters)
        ).scalar_one()
        rows = list(
            session.execute(
                select(DailyRun)
                .where(*filters)
                .order_by(DailyRun.started_at.desc())
                .limit(limit)
                .offset(offset)
            ).scalars()
        )
        items = [_run_summary(row) for row in rows]

    return {"total": total, "items": items}


# ---------------------------------------------------------------------------
# GET /mgmt/daily-runs/{run_id}
# ---------------------------------------------------------------------------


@router.get("/daily-runs/{run_id}")
def get_daily_run(run_id: str, request: Request) -> dict:
    """One run, with every configured service accounted for."""
    engine = _get_engine(request)

    with Session(engine) as session:
        run = session.get(DailyRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Daily run '{run_id}' not found")

        summary = _run_summary(run)
        overrides = _parse_overrides(run.overrides_snapshot)
        host_mem = run.host_mem_available_mb

        real_rows = list(
            session.execute(
                select(DailyRunService)
                .where(DailyRunService.run_id == run_id)
                .order_by(DailyRunService.orden)
            ).scalars()
        )
        recorded = {row.servicio: _service_row(row) for row in real_rows}
        row_ids = [row.id for row in real_rows]

        artifacts = []
        if row_ids:
            artifacts = [
                {
                    "id": a.id,
                    "service_row_id": a.service_row_id,
                    "path": a.path,
                    "kind": a.kind,
                    "size_bytes": a.size_bytes,
                    "mtime": a.mtime,
                    "sent": bool(a.sent),
                }
                for a in session.execute(
                    select(RunArtifact).where(RunArtifact.service_row_id.in_(row_ids))
                ).scalars()
            ]

    registry = _load_service_registry()
    if registry is None:
        # Only what actually ran. The flag tells the screen not to present this
        # as the full picture.
        services = list(recorded.values())
        skips_reconstructed = False
    else:
        services = []
        for svc in registry:
            services.append(recorded.pop(svc.nombre, None) or _synthetic_skip(svc.nombre, overrides))
        # Anything recorded that the registry no longer lists still happened.
        # A service deleted today must not erase last month's history.
        services.extend(recorded.values())
        skips_reconstructed = True

    return {
        **summary,
        "overrides_snapshot": overrides,
        "host_mem_available_mb": host_mem,
        "skips_reconstructed": skips_reconstructed,
        "services": services,
        "artifacts": artifacts,
    }


# ---------------------------------------------------------------------------
# GET /mgmt/daily-runs/{run_id}/services/{orden}/log
# ---------------------------------------------------------------------------


@router.get("/daily-runs/{run_id}/services/{orden}/log")
def get_service_log(run_id: str, orden: int, request: Request):
    """One service's log as text/plain."""
    engine = _get_engine(request)

    with Session(engine) as session:
        # first(), not scalar_one_or_none(): the unique index is on
        # (run_id, servicio), not on orden. The recorder numbers sequentially
        # so a duplicate should not exist, but "should not" is not a
        # constraint, and a duplicate must not turn a log request into a 500.
        row = session.execute(
            select(DailyRunService)
            .where(
                DailyRunService.run_id == run_id,
                DailyRunService.orden == orden,
            )
            .order_by(DailyRunService.id)
        ).scalars().first()

    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No service at position {orden} in run '{run_id}'"
        )
    if not row.log_path:
        raise HTTPException(
            status_code=404, detail=f"Service '{row.servicio}' has no log recorded"
        )

    root = _get_log_root()
    log_path = Path(row.log_path)
    if not log_path.is_absolute():
        log_path = _PROJECT_ROOT / log_path
    try:
        inside = log_path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        inside = False
    if not inside:
        raise HTTPException(
            status_code=400, detail="Log path resolves outside the daily log directory"
        )

    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_path}")

    return FileResponse(
        path=str(log_path),
        media_type="text/plain",
        filename=f"{run_id}-{row.servicio}.log",
    )
