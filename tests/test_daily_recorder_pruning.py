"""
Tests for log pruning (RF-07).

Logs are the bulky half of this instrumentation and the half that ages worst:
a run's outcome stays interesting for months, its stdout for about a week. So
pruning deletes FILES and keeps ROWS — the history of what ran never shrinks,
only the text does.

A row pointing at a log that is gone would be a promise the panel cannot keep,
so pruning also sweeps those pointers to NULL. The sweep is deliberately
file-existence-based rather than a list of what this function just deleted: a
log removed by logrotate, by tmpfiles, or by a human leaves exactly the same
dangling pointer and deserves the same repair.

The thresholds are injected in every test. Waiting 60 days is not a test.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts.daily_recorder import _prune_logs
from src.api.daily_store import (
    DailyRun,
    DailyRunService,
    engine_from_url,
    init_daily_store,
)

_DAY_SECONDS = 86_400


@pytest.fixture
def engine(tmp_path):
    eng = engine_from_url(f"sqlite:///{tmp_path}/daily.db")
    init_daily_store(eng)
    return eng


@pytest.fixture
def shared_dir(tmp_path):
    """data/runs/ — owned by src/api/runner.py, not by this module."""
    d = tmp_path / "runs"
    d.mkdir()
    return d


@pytest.fixture
def runs_dir(shared_dir):
    """data/runs/daily/ — the only directory pruning may touch."""
    d = shared_dir / "daily"
    d.mkdir()
    return d


def _log(runs_dir: Path, stem: str, *, age_days: float = 0, size: int = 32) -> Path:
    path = runs_dir / f"{stem}.log"
    path.write_text("x" * size, encoding="utf-8")
    when = time.time() - age_days * _DAY_SECONDS
    os.utime(path, (when, when))
    return path


def _add_run(engine, run_id: str, log_path: Path | None) -> None:
    with Session(engine) as s:
        s.add(
            DailyRun(
                id=run_id,
                started_at="2026-06-01T00:00:00+00:00",
                status="success",
                triggered_by="schedule",
                test_mode=False,
                hoy="2026-06-01",
                log_path=str(log_path) if log_path else None,
            )
        )
        s.commit()


def _add_service(engine, run_id: str, servicio: str, log_path: Path | None) -> None:
    with Session(engine) as s:
        s.add(
            DailyRunService(
                run_id=run_id,
                orden=1,
                servicio=servicio,
                status="success",
                log_path=str(log_path) if log_path else None,
            )
        )
        s.commit()


def _run_log_path(engine, run_id: str):
    with Session(engine) as s:
        return s.get(DailyRun, run_id).log_path


def _run_ids(engine) -> list[str]:
    with Session(engine) as s:
        return list(s.execute(select(DailyRun.id)).scalars())


# ---------------------------------------------------------------------------
# Age
# ---------------------------------------------------------------------------


def test_a_log_past_the_age_limit_is_deleted(engine, runs_dir):
    old = _log(runs_dir, "old", age_days=90)
    fresh = _log(runs_dir, "fresh", age_days=1)

    _prune_logs(runs_dir, engine, max_age_days=60, max_total_mb=500)

    assert not old.exists()
    assert fresh.exists()


def test_the_row_survives_its_log(engine, runs_dir):
    """Deleting the text must never delete the history."""
    old = _log(runs_dir, "old", age_days=90)
    _add_run(engine, "20260601-070000-daily", old)

    _prune_logs(runs_dir, engine, max_age_days=60, max_total_mb=500)

    assert _run_ids(engine) == ["20260601-070000-daily"]
    assert _run_log_path(engine, "20260601-070000-daily") is None


def test_a_row_whose_log_still_exists_keeps_pointing_at_it(engine, runs_dir):
    fresh = _log(runs_dir, "fresh", age_days=1)
    _add_run(engine, "20260823-070000-daily", fresh)

    _prune_logs(runs_dir, engine, max_age_days=60, max_total_mb=500)

    assert _run_log_path(engine, "20260823-070000-daily") == str(fresh)


def test_service_rows_are_swept_too(engine, runs_dir):
    old = _log(runs_dir, "svc", age_days=90)
    _add_run(engine, "20260601-070000-daily", None)
    _add_service(engine, "20260601-070000-daily", "ventas", old)

    _prune_logs(runs_dir, engine, max_age_days=60, max_total_mb=500)

    with Session(engine) as s:
        row = s.execute(select(DailyRunService)).scalar_one()
    assert row.servicio == "ventas"
    assert row.log_path is None


def test_a_pointer_to_a_log_deleted_by_something_else_is_repaired(engine, runs_dir):
    """logrotate, tmpfiles, a human — the dangling pointer is identical."""
    gone = runs_dir / "vanished.log"
    _add_run(engine, "20260601-070000-daily", gone)

    _prune_logs(runs_dir, engine, max_age_days=60, max_total_mb=500)

    assert _run_log_path(engine, "20260601-070000-daily") is None


# ---------------------------------------------------------------------------
# Total size
# ---------------------------------------------------------------------------


def test_the_size_cap_deletes_oldest_first(engine, runs_dir):
    """Under the cap, the newest logs are the ones worth keeping."""
    mb = 1024 * 1024
    oldest = _log(runs_dir, "a", age_days=3, size=mb)
    middle = _log(runs_dir, "b", age_days=2, size=mb)
    newest = _log(runs_dir, "c", age_days=1, size=mb)

    # Everything is inside the age limit; only the byte cap can fire here.
    _prune_logs(runs_dir, engine, max_age_days=365, max_total_mb=2)

    assert not oldest.exists()
    assert middle.exists()
    assert newest.exists()


def test_nothing_is_deleted_while_under_both_limits(engine, runs_dir):
    kept = [_log(runs_dir, f"{i}", age_days=1, size=1024) for i in range(3)]

    _prune_logs(runs_dir, engine, max_age_days=60, max_total_mb=500)

    assert all(p.exists() for p in kept)


# ---------------------------------------------------------------------------
# Scope and the isolation contract
# ---------------------------------------------------------------------------


def test_only_log_files_are_touched(engine, runs_dir):
    """The runs directory is not this function's to clean out."""
    other = runs_dir / "keep-me.json"
    other.write_text("{}", encoding="utf-8")
    when = time.time() - 900 * _DAY_SECONDS
    os.utime(other, (when, when))

    _prune_logs(runs_dir, engine, max_age_days=60, max_total_mb=1)

    assert other.exists()


def test_pruning_never_climbs_out_of_its_own_directory(engine, shared_dir, runs_dir):
    """data/runs/ belongs to src/api/runner.py and cannot be repaired.

    It stores manual-run log paths in runs.log_path, a NOT NULL column, so a
    log deleted from under it leaves a pointer no sweep can fix. And the names
    are not distinguishable: runner builds its id as {timestamp}-{slug} where
    slug is a config's "tipo" field, editable through /mgmt/configs — a config
    named "daily" yields exactly the shape this module produces. Hence a
    separate directory rather than a filename pattern.
    """
    manual = _log(shared_dir, "20260101-070000-daily", age_days=900)
    ours = _log(runs_dir, "20260101-070000-daily", age_days=900)

    _prune_logs(runs_dir, engine, max_age_days=60, max_total_mb=1)

    assert manual.exists(), "pruning reached into the shared runs directory"
    assert not ours.exists()


def test_a_missing_runs_directory_is_not_an_error(engine, tmp_path):
    _prune_logs(tmp_path / "does-not-exist", engine, max_age_days=60, max_total_mb=500)


def test_pruning_never_raises_when_the_store_is_broken(tmp_path, runs_dir):
    """Same contract as emit(): housekeeping must not take the daily down."""
    broken = engine_from_url(f"sqlite:///{tmp_path}/no-such-dir/daily.db")
    old = _log(runs_dir, "old", age_days=90)

    _prune_logs(runs_dir, broken, max_age_days=60, max_total_mb=500)

    # The file half still worked; only the database sweep failed.
    assert not old.exists()


def test_an_undeletable_log_does_not_stop_the_rest(engine, runs_dir, monkeypatch):
    old_a = _log(runs_dir, "a", age_days=90)
    old_b = _log(runs_dir, "b", age_days=90)

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "a.log":
            raise PermissionError("read-only filesystem")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    _prune_logs(runs_dir, engine, max_age_days=60, max_total_mb=500)

    assert old_a.exists()
    assert not old_b.exists()


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_opening_a_run_prunes_first(tmp_path, monkeypatch):
    """Pruning has to run somewhere, and a daily run is the natural moment."""
    from scripts import daily_recorder

    calls = []
    monkeypatch.setattr(
        daily_recorder,
        "_prune_logs",
        lambda *a, **kw: calls.append((a, kw)),
    )

    eng = engine_from_url(f"sqlite:///{tmp_path}/daily.db")
    with daily_recorder.recording_run(hoy="2026-08-24", test_mode=False, engine=eng):
        pass

    assert len(calls) == 1
