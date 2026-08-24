"""
Tests for Unit 8 (RF-09): mgmt_daily.py — the read side of the daily-run store.

TDD: written BEFORE implementation.

The interesting half is not the pagination. It is the reconstruction of skips:
a service the daily decided not to run writes no row at all (design decision
E5), so a detail response built only from rows would quietly show 12 services
on a day 18 were configured. The six that did not run are the six most worth
seeing.

The other theme is the same one running through this whole feature: never let
"we could not read it" render as "it did not happen". A registry we cannot
import, an overrides snapshot that will not parse, a log the row promises and
the disk does not have — each says so distinctly instead of collapsing into an
empty list.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.daily_store import (
    DailyRun,
    DailyRunService,
    RunArtifact,
    engine_from_url,
    init_daily_store,
)
from src.api.routes.mgmt_daily import router as mgmt_daily_router, set_log_root


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path):
    eng = engine_from_url(f"sqlite:///{tmp_path}/mgmt.db")
    init_daily_store(eng)
    return eng


@pytest.fixture
def log_root(tmp_path):
    """Serve logs from a temp directory instead of the real data/runs/daily/."""
    d = tmp_path / "logs"
    d.mkdir()
    set_log_root(d)
    yield d
    set_log_root(None)


@pytest.fixture
def client(engine, log_root):
    app = FastAPI()
    app.include_router(mgmt_daily_router)
    app.state.engine = engine
    return TestClient(app)


def _add_run(engine, run_id: str, **kwargs) -> None:
    defaults = dict(
        started_at="2026-08-24T07:00:00+00:00",
        finished_at="2026-08-24T07:12:00+00:00",
        status="success",
        triggered_by="schedule",
        test_mode=False,
        hoy="2026-08-24",
    )
    defaults.update(kwargs)
    with Session(engine) as s:
        s.add(DailyRun(id=run_id, **defaults))
        s.commit()


def _add_service(engine, run_id: str, orden: int, servicio: str, **kwargs) -> int:
    defaults = dict(status="success")
    defaults.update(kwargs)
    with Session(engine) as s:
        row = DailyRunService(run_id=run_id, orden=orden, servicio=servicio, **defaults)
        s.add(row)
        s.commit()
        return row.id


# ---------------------------------------------------------------------------
# GET /mgmt/daily-runs — history
# ---------------------------------------------------------------------------


def test_an_empty_store_is_an_empty_list_not_an_error(client):
    res = client.get("/mgmt/daily-runs")
    assert res.status_code == 200
    assert res.json() == {"total": 0, "items": []}


def test_history_is_newest_first(client, engine):
    _add_run(engine, "20260822-070000-daily", started_at="2026-08-22T07:00:00+00:00")
    _add_run(engine, "20260824-070000-daily", started_at="2026-08-24T07:00:00+00:00")
    _add_run(engine, "20260823-070000-daily", started_at="2026-08-23T07:00:00+00:00")

    items = client.get("/mgmt/daily-runs").json()["items"]

    assert [i["id"] for i in items] == [
        "20260824-070000-daily",
        "20260823-070000-daily",
        "20260822-070000-daily",
    ]


def test_total_counts_every_row_not_just_the_page(client, engine):
    for day in range(1, 6):
        _add_run(engine, f"202608{day:02d}-070000-daily",
                 started_at=f"2026-08-{day:02d}T07:00:00+00:00")

    body = client.get("/mgmt/daily-runs?limit=2").json()

    assert body["total"] == 5
    assert len(body["items"]) == 2


def test_offset_walks_the_history(client, engine):
    for day in range(1, 4):
        _add_run(engine, f"202608{day:02d}-070000-daily",
                 started_at=f"2026-08-{day:02d}T07:00:00+00:00")

    page = client.get("/mgmt/daily-runs?limit=1&offset=1").json()["items"]

    assert [i["id"] for i in page] == ["20260802-070000-daily"]


def test_history_can_be_filtered_by_status(client, engine):
    _add_run(engine, "20260823-070000-daily", status="success")
    _add_run(engine, "20260824-070000-daily", status="error")

    items = client.get("/mgmt/daily-runs?status=error").json()["items"]

    assert [i["id"] for i in items] == ["20260824-070000-daily"]


def test_history_can_be_bounded_by_date(client, engine):
    _add_run(engine, "20260801-070000-daily", started_at="2026-08-01T07:00:00+00:00")
    _add_run(engine, "20260815-070000-daily", started_at="2026-08-15T07:00:00+00:00")
    _add_run(engine, "20260824-070000-daily", started_at="2026-08-24T07:00:00+00:00")

    items = client.get(
        "/mgmt/daily-runs?desde=2026-08-10&hasta=2026-08-20"
    ).json()["items"]

    assert [i["id"] for i in items] == ["20260815-070000-daily"]


def test_a_summary_row_carries_what_the_table_shows(client, engine):
    _add_run(
        engine,
        "20260824-070000-daily",
        status="partial",
        exit_code=1,
        test_mode=True,
        solo_canal="whatsapp",
        git_branch="main",
        git_dirty=True,
    )

    item = client.get("/mgmt/daily-runs").json()["items"][0]

    assert item["status"] == "partial"
    assert item["exit_code"] == 1
    assert item["test_mode"] is True
    assert item["solo_canal"] == "whatsapp"
    assert item["git_branch"] == "main"
    assert item["git_dirty"] is True


def test_an_unread_git_state_stays_null_in_the_response(client, engine):
    """None must not become False on the way out — same lie, one layer later."""
    _add_run(engine, "20260824-070000-daily")

    item = client.get("/mgmt/daily-runs").json()["items"][0]

    assert item["git_dirty"] is None


# ---------------------------------------------------------------------------
# GET /mgmt/daily-runs/{id} — detail, with skips rebuilt
# ---------------------------------------------------------------------------


def test_an_unknown_run_is_a_404(client):
    assert client.get("/mgmt/daily-runs/nope").status_code == 404


def test_detail_lists_the_services_that_actually_ran(client, engine):
    _add_run(engine, "20260824-070000-daily")
    _add_service(engine, "20260824-070000-daily", 1, "stock-diario",
                 delivery_status="sent", duration_ms=4200)

    body = client.get("/mgmt/daily-runs/20260824-070000-daily").json()
    real = [s for s in body["services"] if not s["is_synthetic"]]

    assert len(real) == 1
    assert real[0]["servicio"] == "stock-diario"
    assert real[0]["delivery_status"] == "sent"
    assert real[0]["duration_ms"] == 4200
    assert real[0]["orden"] == 1


def test_a_service_that_never_ran_is_rebuilt_as_skipped(client, engine):
    """No row means it did not run, and that is the row worth seeing."""
    _add_run(engine, "20260824-070000-daily")
    _add_service(engine, "20260824-070000-daily", 1, "stock-diario")

    body = client.get("/mgmt/daily-runs/20260824-070000-daily").json()
    by_name = {s["servicio"]: s for s in body["services"]}

    assert body["skips_reconstructed"] is True
    assert len(body["services"]) > 1, "only the one row that ran came back"
    assert by_name["stock-diario"]["is_synthetic"] is False

    synthetic = [s for s in body["services"] if s["is_synthetic"]]
    assert synthetic, "no skips were rebuilt"
    assert all(s["status"] == "skipped" for s in synthetic)
    # A synthetic row has no database row, so it can address no log.
    assert all(s["orden"] is None for s in synthetic)


def test_a_rebuilt_skip_carries_the_reason_from_the_overrides(client, engine):
    from scripts.run_daily import SERVICIOS

    skipped = SERVICIOS[0].nombre
    _add_run(
        engine,
        "20260824-070000-daily",
        overrides_snapshot=json.dumps(
            {skipped: {"ejecutar": False, "razon": "pedido de Nahuel"}}
        ),
    )

    body = client.get("/mgmt/daily-runs/20260824-070000-daily").json()
    row = next(s for s in body["services"] if s["servicio"] == skipped)

    assert row["is_synthetic"] is True
    assert row["skip_reason"] == "pedido de Nahuel"


def test_a_skip_with_no_recorded_reason_says_nothing_rather_than_inventing(client, engine):
    from scripts.run_daily import SERVICIOS

    _add_run(engine, "20260824-070000-daily", overrides_snapshot=json.dumps({}))

    body = client.get("/mgmt/daily-runs/20260824-070000-daily").json()
    row = next(s for s in body["services"] if s["servicio"] == SERVICIOS[0].nombre)

    assert row["status"] == "skipped"
    assert row["skip_reason"] is None


def test_an_unparseable_overrides_snapshot_does_not_take_the_page_down(client, engine):
    _add_run(engine, "20260824-070000-daily", overrides_snapshot="{not json")

    res = client.get("/mgmt/daily-runs/20260824-070000-daily")

    assert res.status_code == 200
    assert res.json()["overrides_snapshot"] is None


def test_services_follow_the_registry_order(client, engine):
    from scripts.run_daily import SERVICIOS

    _add_run(engine, "20260824-070000-daily")
    # Recorded out of registry order on purpose.
    _add_service(engine, "20260824-070000-daily", 1, SERVICIOS[3].nombre)
    _add_service(engine, "20260824-070000-daily", 2, SERVICIOS[0].nombre)

    body = client.get("/mgmt/daily-runs/20260824-070000-daily").json()
    names = [s["servicio"] for s in body["services"]]

    assert names[:4] == [s.nombre for s in SERVICIOS[:4]]


def test_a_service_no_longer_in_the_registry_is_still_reported(client, engine):
    """History does not disappear because someone deleted a service today."""
    _add_run(engine, "20260824-070000-daily")
    _add_service(engine, "20260824-070000-daily", 1, "servicio-que-ya-no-existe")

    body = client.get("/mgmt/daily-runs/20260824-070000-daily").json()
    names = [s["servicio"] for s in body["services"]]

    assert "servicio-que-ya-no-existe" in names


def test_detail_includes_the_artifacts_of_each_service(client, engine):
    _add_run(engine, "20260824-070000-daily")
    row_id = _add_service(engine, "20260824-070000-daily", 1, "stock-diario")
    with Session(engine) as s:
        s.add(
            RunArtifact(
                service_row_id=row_id,
                path="stock-diario/2026-08-24/stock.xlsx",
                kind="xlsx",
                size_bytes=8192,
                sent=True,
            )
        )
        s.commit()

    body = client.get("/mgmt/daily-runs/20260824-070000-daily").json()

    assert len(body["artifacts"]) == 1
    assert body["artifacts"][0]["path"] == "stock-diario/2026-08-24/stock.xlsx"
    assert body["artifacts"][0]["sent"] is True
    assert body["artifacts"][0]["service_row_id"] == row_id


def test_the_error_traceback_survives_to_the_response(client, engine):
    """It exists exactly once, at the except site. Losing it here wastes it."""
    _add_run(engine, "20260824-070000-daily", status="partial")
    _add_service(
        engine, "20260824-070000-daily", 1, "stock-diario",
        status="exception",
        error_repr="ValueError('boom')",
        error_traceback="Traceback...\nValueError: boom",
    )

    body = client.get("/mgmt/daily-runs/20260824-070000-daily").json()
    row = next(s for s in body["services"] if s["servicio"] == "stock-diario")

    assert "ValueError: boom" in row["error_traceback"]


def test_an_unreadable_registry_says_so_instead_of_hiding_the_skips(client, engine, monkeypatch):
    """If the service list cannot be imported, the panel must not imply completeness."""
    import src.api.routes.mgmt_daily as mod

    monkeypatch.setattr(mod, "_load_service_registry", lambda: None)

    _add_run(engine, "20260824-070000-daily")
    _add_service(engine, "20260824-070000-daily", 1, "stock-diario")

    body = client.get("/mgmt/daily-runs/20260824-070000-daily").json()

    assert body["skips_reconstructed"] is False
    assert [s["servicio"] for s in body["services"]] == ["stock-diario"]


# ---------------------------------------------------------------------------
# GET /mgmt/daily-runs/{id}/services/{orden}/log
# ---------------------------------------------------------------------------


def test_a_service_log_is_served_as_plain_text(client, engine, log_root):
    log = log_root / "svc.log"
    log.write_text("linea uno\nlinea dos\n", encoding="utf-8")
    _add_run(engine, "20260824-070000-daily")
    _add_service(engine, "20260824-070000-daily", 1, "stock-diario", log_path=str(log))

    res = client.get("/mgmt/daily-runs/20260824-070000-daily/services/1/log")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert "linea dos" in res.text


def test_a_service_with_no_log_is_a_404_not_an_empty_file(client, engine):
    _add_run(engine, "20260824-070000-daily")
    _add_service(engine, "20260824-070000-daily", 1, "stock-diario", log_path=None)

    res = client.get("/mgmt/daily-runs/20260824-070000-daily/services/1/log")

    assert res.status_code == 404


def test_a_log_the_row_promises_and_the_disk_lacks_is_a_404(client, engine, log_root):
    _add_run(engine, "20260824-070000-daily")
    _add_service(
        engine, "20260824-070000-daily", 1, "stock-diario",
        log_path=str(log_root / "gone.log"),
    )

    res = client.get("/mgmt/daily-runs/20260824-070000-daily/services/1/log")

    assert res.status_code == 404


def test_an_unknown_service_position_is_a_404(client, engine):
    _add_run(engine, "20260824-070000-daily")

    res = client.get("/mgmt/daily-runs/20260824-070000-daily/services/99/log")

    assert res.status_code == 404


@pytest.mark.parametrize(
    "poisoned",
    ["/etc/passwd", "../../../../etc/passwd", "data/runs/daily/../../../etc/passwd"],
)
def test_a_log_path_outside_the_log_directory_is_refused(client, engine, poisoned):
    """The column is ours, but a route that hands back whatever path a row
    holds is one bad UPDATE away from being the whole problem."""
    _add_run(engine, "20260824-070000-daily")
    _add_service(engine, "20260824-070000-daily", 1, "stock-diario", log_path=poisoned)

    res = client.get("/mgmt/daily-runs/20260824-070000-daily/services/1/log")

    assert res.status_code == 400


def test_the_default_log_root_matches_what_the_recorder_writes():
    """Two constants describing one directory drift. This is the tripwire."""
    from scripts.daily_recorder import RUNS_DIR
    from src.api.routes.mgmt_daily import _DEFAULT_LOG_ROOT

    assert _DEFAULT_LOG_ROOT.resolve() == RUNS_DIR.resolve()


# ---------------------------------------------------------------------------
# Read-only surface (RF-17)
# ---------------------------------------------------------------------------


def test_the_daily_routes_expose_no_write_methods(client):
    schema = client.get("/openapi.json").json()

    for path, methods in schema["paths"].items():
        if not path.startswith("/mgmt/daily-runs"):
            continue
        assert set(methods) <= {"get"}, f"{path} exposes {sorted(methods)}"


def test_a_missing_engine_is_a_503_not_a_crash():
    app = FastAPI()
    app.include_router(mgmt_daily_router)
    res = TestClient(app, raise_server_exceptions=False).get("/mgmt/daily-runs")
    assert res.status_code == 503
