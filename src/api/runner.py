"""
Run management: RunSession + RunRegistry.

RunSession: owns one Popen subprocess + log file + asyncio.Queue(s) for SSE fanout.
RunRegistry: per-config asyncio.Lock, active sessions dict, attached to app.state.

Design decisions:
- Reader thread (threading.Thread) reads popen.stdout line-by-line
- Bridge to asyncio via loop.call_soon_threadsafe(broadcast, event)
- Per-config lock: fails fast with RunBusyError if locked
- Slug derived from config JSON 'tipo' field at trigger time
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from src.api.db import Run, get_default_engine, init_db
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_DEFAULT_RUNS_DIR = Path("data/runs")


class RunBusyError(Exception):
    """Raised when a trigger is attempted for a config that is already running."""

    def __init__(self, config_filename: str, active_run_id: str):
        self.config_filename = config_filename
        self.active_run_id = active_run_id
        super().__init__(
            f"Config '{config_filename}' already has an active run: {active_run_id}"
        )


@dataclass
class RunSession:
    """Owns one subprocess + log file + subscriber queues."""

    run_id: str
    config_filename: str
    log_path: Path
    popen: subprocess.Popen | None = None
    _queues: list[asyncio.Queue] = field(default_factory=list)
    _done_event: asyncio.Event = field(default_factory=asyncio.Event)
    _reader_thread: threading.Thread | None = None
    _log_file = None

    def subscribe(self) -> asyncio.Queue:
        """Register a new subscriber queue and return it."""
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    def broadcast(self, event: dict) -> None:
        """Put event into all subscriber queues (called from reader thread via call_soon_threadsafe)."""
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Subscriber queue full for run %s — dropping slow subscriber",
                    self.run_id,
                )
                self._queues.remove(q)

    def terminate(self, grace: float = 5.0) -> None:
        """Send SIGTERM to the subprocess (best-effort)."""
        if self.popen and self.popen.poll() is None:
            try:
                self.popen.terminate()
            except Exception:
                pass

    def wait_done(self) -> asyncio.Event:
        """Return the asyncio.Event set when the run finishes."""
        return self._done_event


class RunRegistry:
    """
    Manages all active runs and per-config locks.

    Must be attached to app.state so it survives request lifetime:
        app.state.runner = RunRegistry(loop=asyncio.get_running_loop())
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, runs_dir: Path | None = None, engine=None):
        self._loop = loop
        self._runs_dir = runs_dir or _DEFAULT_RUNS_DIR
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._engine = engine  # SQLAlchemy engine (None = use default)
        self._locks: dict[str, asyncio.Lock] = {}
        self._sessions: dict[str, RunSession] = {}

    @property
    def sessions(self) -> dict[str, RunSession]:
        return self._sessions

    def get_session(self, run_id: str) -> RunSession | None:
        return self._sessions.get(run_id)

    def _get_lock(self, config_filename: str) -> asyncio.Lock:
        if config_filename not in self._locks:
            self._locks[config_filename] = asyncio.Lock()
        return self._locks[config_filename]

    def _make_run_id(self, slug: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"{ts}-{slug}"

    def _read_slug_from_config(self, config_filename: str) -> str:
        """Read the 'tipo' field from a config JSON and use it as the slug."""
        try:
            path = Path(config_filename)
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("tipo", path.stem)
        except Exception:
            return Path(config_filename).stem

    async def trigger(
        self,
        config_filename: str,
        triggered_by: str = "manual",
        no_delivery: bool = False,
        test_mode: bool = False,
    ) -> str:
        """Spawn a new subprocess for the given config.

        Returns run_id immediately (non-blocking).
        Raises RunBusyError if the config is already running.
        """
        lock = self._get_lock(config_filename)

        if lock.locked():
            # Find which run_id holds this config
            for run_id, sess in self._sessions.items():
                if sess.config_filename == config_filename:
                    raise RunBusyError(config_filename, run_id)
            raise RunBusyError(config_filename, "unknown")

        await lock.acquire()

        slug = self._read_slug_from_config(config_filename)
        run_id = self._make_run_id(slug)
        log_path = self._runs_dir / f"{run_id}.log"

        session = RunSession(
            run_id=run_id,
            config_filename=config_filename,
            log_path=log_path,
        )
        self._sessions[run_id] = session

        # Build subprocess command
        cmd = self._build_cmd(config_filename, no_delivery, test_mode)

        # Persist run row to DB (if engine available)
        engine = self._engine or self._try_get_engine()
        if engine:
            try:
                with Session(engine) as db_session:
                    run_row = Run(
                        id=run_id,
                        config_file=Path(config_filename).name,
                        slug=slug,
                        started_at=datetime.now(timezone.utc).isoformat(),
                        status="running",
                        log_path=str(log_path),
                        triggered_by=triggered_by,
                        test_mode=test_mode,
                    )
                    db_session.add(run_row)
                    db_session.commit()
            except Exception as e:
                logger.warning("Could not persist run to DB: %s", e)

        # Spawn subprocess
        popen = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        session.popen = popen

        # Start reader thread
        reader_thread = threading.Thread(
            target=self._reader_thread_fn,
            args=(session, lock, engine),
            daemon=True,
            name=f"runner-reader-{run_id}",
        )
        session._reader_thread = reader_thread
        reader_thread.start()

        return run_id

    def _build_cmd(self, config_filename: str, no_delivery: bool, test_mode: bool) -> list[str]:
        """Build the subprocess command. Override in tests to inject a fake script."""
        cmd = ["python", "main.py", "--config", config_filename]
        if no_delivery:
            cmd.append("--no-delivery")
        if test_mode:
            cmd.append("--test-mode")
        return cmd

    def _try_get_engine(self):
        """Try to get the default DB engine, return None on failure."""
        try:
            return get_default_engine()
        except Exception:
            return None

    def _reader_thread_fn(
        self,
        session: RunSession,
        lock: asyncio.Lock,
        engine,
    ) -> None:
        """Read subprocess stdout line-by-line, write to log, broadcast events."""
        try:
            with open(session.log_path, "w", encoding="utf-8", buffering=1) as log_file:
                session._log_file = log_file
                for line in session.popen.stdout:
                    log_file.write(line)
                    log_file.flush()
                    event = {"type": "log", "line": line.rstrip("\n")}
                    self._loop.call_soon_threadsafe(session.broadcast, event)

            session.popen.wait()
            exit_code = session.popen.returncode
        except Exception as e:
            logger.exception("Reader thread error for run %s: %s", session.run_id, e)
            exit_code = -1

        # Finalize via asyncio event loop
        try:
            self._loop.call_soon_threadsafe(
                self._finalize_sync, session, exit_code, lock, engine
            )
        except RuntimeError as e:
            logger.warning(
                "Could not schedule finalize for run %s — event loop closed: %s",
                session.run_id,
                e,
            )

    def _finalize_sync(
        self,
        session: RunSession,
        exit_code: int,
        lock: asyncio.Lock,
        engine,
    ) -> None:
        """Called from the event loop after reader thread EOF."""
        run_id = session.run_id
        status = "success" if exit_code == 0 else "error"

        # Update DB
        if engine:
            try:
                with Session(engine) as db_session:
                    db_session.execute(
                        __import__("sqlalchemy").text(
                            "UPDATE runs SET status=:s, exit_code=:e, finished_at=:f WHERE id=:i"
                        ),
                        {
                            "s": status,
                            "e": exit_code,
                            "f": datetime.now(timezone.utc).isoformat(),
                            "i": run_id,
                        },
                    )
                    db_session.commit()
            except Exception as e:
                logger.warning("Could not update run %s in DB: %s", run_id, e)

        # Broadcast done event
        done_event = {"type": "done", "exit_code": exit_code}
        session.broadcast(done_event)

        # Close all subscriber queues by sending None sentinel
        for q in list(session._queues):
            try:
                q.put_nowait(None)  # None = stream closed
            except asyncio.QueueFull:
                pass
        session._queues.clear()

        # Mark done event
        session._done_event.set()

        # Remove from active sessions
        del self._sessions[run_id]

        # Release the per-config lock
        try:
            lock.release()
        except RuntimeError:
            pass  # Already released

        logger.info("Run %s finished with status=%s exit_code=%d", run_id, status, exit_code)

    async def subscribe(self, run_id: str) -> AsyncIterator[dict]:
        """Yield log events for a run: replay existing log then tail live queue.

        Yields dicts with type='log'|'done'.
        """
        session = self._sessions.get(run_id)

        if session is None:
            # Run may have finished — replay from log file if it exists
            # (handled by caller via GET /log endpoint)
            return

        # Register subscriber BEFORE reading existing log to avoid missing lines
        q = session.subscribe()

        # Replay existing log lines first
        try:
            with open(session.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    yield {"type": "log", "line": line.rstrip("\n")}
        except FileNotFoundError:
            pass

        # Tail live queue
        while True:
            event = await q.get()
            if event is None:
                break  # Stream closed
            yield event

        session.unsubscribe(q)

    async def wait_for(self, run_id: str) -> None:
        """Wait until a run finishes (used by daily orchestrator for sequential execution)."""
        session = self._sessions.get(run_id)
        if session is None:
            return  # Already finished
        await session._done_event.wait()
