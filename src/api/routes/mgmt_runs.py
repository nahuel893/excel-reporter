"""
Management API routes: runs (trigger, history, SSE streaming, log retrieval).

Endpoints:
    POST   /mgmt/runs                  — trigger a run
    GET    /mgmt/runs                  — paginated run history
    GET    /mgmt/runs/{run_id}         — run detail
    GET    /mgmt/runs/{run_id}/log     — full log as text/plain
    GET    /mgmt/runs/{run_id}/stream  — SSE live log stream
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from src.api.runner import RunBusyError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mgmt")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TriggerRunRequest(BaseModel):
    config_filename: str
    test_mode: bool = False
    no_delivery: bool = False


class TriggerRunResponse(BaseModel):
    run_id: str
    status: str = "running"


# ---------------------------------------------------------------------------
# Helper: get runner and engine from app.state
# ---------------------------------------------------------------------------


def _get_runner(request: Request):
    runner = getattr(request.app.state, "runner", None)
    if runner is None:
        raise HTTPException(status_code=503, detail="Run registry not initialized")
    return runner


def _get_engine(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        # Fall back to default engine
        from src.api.db import get_default_engine
        return get_default_engine()
    return engine


# ---------------------------------------------------------------------------
# POST /mgmt/runs — trigger
# ---------------------------------------------------------------------------


@router.post("/runs", status_code=202)
async def trigger_run(body: TriggerRunRequest, request: Request):
    """Trigger a new report run."""
    runner = _get_runner(request)
    try:
        run_id = await runner.trigger(
            config_filename=body.config_filename,
            triggered_by="manual",
            no_delivery=body.no_delivery,
            test_mode=body.test_mode,
        )
    except RunBusyError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "a run is already active",
                "run_id": exc.active_run_id,
            },
        )
    except Exception as exc:
        logger.exception("Failed to trigger run")
        raise HTTPException(status_code=500, detail=str(exc))

    return {"run_id": run_id, "status": "running"}


# ---------------------------------------------------------------------------
# GET /mgmt/runs — paginated history
# ---------------------------------------------------------------------------


@router.get("/runs")
def list_runs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    config: Optional[str] = None,
):
    """Return paginated run history."""
    engine = _get_engine(request)
    with Session(engine) as session:
        where_clauses = []
        params: dict = {}
        if status:
            where_clauses.append("status = :status")
            params["status"] = status
        if config:
            where_clauses.append("config_file = :config")
            params["config"] = config

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        total_row = session.execute(
            text(f"SELECT COUNT(*) FROM runs {where_sql}"), params
        ).fetchone()
        total = total_row[0] if total_row else 0

        params["limit"] = limit
        params["offset"] = offset
        rows = session.execute(
            text(
                f"""
                SELECT id, config_file, slug, started_at, finished_at,
                       status, exit_code, triggered_by, test_mode
                FROM runs
                {where_sql}
                ORDER BY started_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).fetchall()

    items = [
        {
            "id": r[0],
            "config_file": r[1],
            "slug": r[2],
            "started_at": r[3],
            "finished_at": r[4],
            "status": r[5],
            "exit_code": r[6],
            "triggered_by": r[7],
            "test_mode": bool(r[8]),
        }
        for r in rows
    ]

    return {"total": total, "items": items}


# ---------------------------------------------------------------------------
# GET /mgmt/runs/{run_id} — detail
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    """Return a single run row."""
    engine = _get_engine(request)
    with Session(engine) as session:
        row = session.execute(
            text(
                """
                SELECT id, config_file, slug, started_at, finished_at,
                       status, exit_code, log_path, triggered_by, test_mode
                FROM runs WHERE id = :id
                """
            ),
            {"id": run_id},
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return {
        "id": row[0],
        "config_file": row[1],
        "slug": row[2],
        "started_at": row[3],
        "finished_at": row[4],
        "status": row[5],
        "exit_code": row[6],
        "log_path": row[7],
        "triggered_by": row[8],
        "test_mode": bool(row[9]),
    }


# ---------------------------------------------------------------------------
# GET /mgmt/runs/{run_id}/log — full log as text/plain
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/log")
def get_run_log(run_id: str, request: Request):
    """Return the full log file as text/plain."""
    engine = _get_engine(request)
    with Session(engine) as session:
        row = session.execute(
            text("SELECT log_path FROM runs WHERE id = :id"),
            {"id": run_id},
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    log_path = Path(row[0])
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_path}")

    return FileResponse(
        path=str(log_path),
        media_type="text/plain",
        filename=f"{run_id}.log",
    )


# ---------------------------------------------------------------------------
# GET /mgmt/runs/{run_id}/stream — SSE
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/stream")
async def stream_run_log(run_id: str, request: Request):
    """Stream run log via SSE (replay + live tail)."""
    runner = _get_runner(request)
    engine = _get_engine(request)

    session = runner.get_session(run_id)

    if session is None:
        # Run is not active — check DB for finished run and replay from log file
        with Session(engine) as db_session:
            row = db_session.execute(
                text("SELECT log_path, status FROM runs WHERE id = :id"),
                {"id": run_id},
            ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

        log_path = Path(row[0])

        async def replay_finished():
            if log_path.exists():
                with open(log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        yield {"event": "log", "data": line.rstrip("\n")}
            yield {"event": "done", "data": '{"exit_code": null}'}

        return EventSourceResponse(replay_finished())

    async def stream_active():
        async for event in runner.subscribe(run_id):
            if event["type"] == "log":
                yield {"event": "log", "data": event["line"]}
            elif event["type"] == "done":
                import json
                yield {"event": "done", "data": json.dumps({"exit_code": event["exit_code"]})}
                break

    return EventSourceResponse(stream_active())
