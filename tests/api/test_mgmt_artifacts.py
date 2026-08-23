"""
Tests for Unit 10 (RF-15, RF-16, RF-17, RF-18): mgmt_artifacts.py — read-only
artifact browser API.

TDD: written BEFORE implementation.
"""
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def artifacts_root(tmp_path):
    """Build a fake data/output/ tree covering every bucket/edge case."""
    root = tmp_path / "output"
    root.mkdir()

    # ventas/2026-07/ — principal + imagenes (parseable PNG) + backups (both conventions)
    ventas_period = root / "ventas" / "2026-07"
    ventas_period.mkdir(parents=True)
    (ventas_period / "Ventas Test.xlsx").write_bytes(b"fake-xlsx")
    (ventas_period / "Ventas Test_Hoja1_A1_D10.png").write_bytes(b"fake-png")
    (ventas_period / "Ventas Test_backup.xlsx").write_bytes(b"fake-backup")
    (ventas_period / "Ventas Test_backup-20260801-manual.xlsx").write_bytes(b"fake-backup-2")

    # stock-diario/2026-08-11/ — day granularity, must NOT be flagged anomalous
    stock_period = root / "stock-diario" / "2026-08-11"
    stock_period.mkdir(parents=True)
    (stock_period / "stock.xlsx").write_bytes(b"fake-stock")

    # resumen-mensual/2026-06.contaminated/ — known anomalous folder shape
    anomalous_period = root / "resumen-mensual" / "2026-06.contaminated"
    anomalous_period.mkdir(parents=True)
    (anomalous_period / "resumen.xlsx").write_bytes(b"fake-contaminated")

    # graficos-cobertura/2026-07/png/ — the real service writes ~50 PNGs into a
    # png/ subfolder (PNG_SUBDIR). A flat scan would drop every one of them.
    gc_png = root / "graficos-cobertura" / "2026-07" / "png"
    gc_png.mkdir(parents=True)
    (gc_png / "CERVEZAS_zona_NOA.png").write_bytes(b"fake-png")
    (root / "graficos-cobertura" / "2026-07" / "resumen.xlsx").write_bytes(b"fake-gc")

    # _send_log/ is the delivery log, not a report service — must not be listed
    send_log = root / "_send_log"
    send_log.mkdir(parents=True)
    (send_log / "2026-08-11.json").write_text("{}", encoding="utf-8")

    # loose file directly at the root of data/output/ — must land in "unclassified"
    (root / "loose_file.xlsx").write_bytes(b"fake-loose")

    return root


@pytest.fixture
def app(artifacts_root):
    from src.api.routes.mgmt_artifacts import router, set_artifacts_root

    set_artifacts_root(artifacts_root)
    test_app = FastAPI()
    test_app.include_router(router)
    yield test_app
    # Restore, or the module global keeps pointing at a deleted tmp_path for
    # the rest of the session and later callers read from nowhere.
    set_artifacts_root(None)


@pytest.fixture
def client(app):
    return TestClient(app)


def _find_service(tree: dict, slug: str) -> dict:
    return next(s for s in tree["services"] if s["slug"] == slug)


def _find_period(service: dict, periodo: str) -> dict:
    return next(p for p in service["periods"] if p["periodo"] == periodo)


# ---------------------------------------------------------------------------
# GET /mgmt/artifacts/tree
# ---------------------------------------------------------------------------


def test_tree_lists_services_and_periods(client):
    r = client.get("/mgmt/artifacts/tree")
    assert r.status_code == 200
    body = r.json()
    slugs = {s["slug"] for s in body["services"]}
    assert {"ventas", "stock-diario", "resumen-mensual"} <= slugs


def test_tree_groups_files_into_principal_imagenes_backups(client):
    body = client.get("/mgmt/artifacts/tree").json()
    period = _find_period(_find_service(body, "ventas"), "2026-07")

    principal_names = {f["name"] for f in period["principal"]}
    imagenes_names = {f["name"] for f in period["imagenes"]}
    backups_names = {f["name"] for f in period["backups"]}

    assert principal_names == {"Ventas Test.xlsx"}
    assert imagenes_names == {"Ventas Test_Hoja1_A1_D10.png"}
    assert backups_names == {
        "Ventas Test_backup.xlsx",
        "Ventas Test_backup-20260801-manual.xlsx",
    }


def test_tree_parses_sheet_and_range_from_png_filename(client):
    body = client.get("/mgmt/artifacts/tree").json()
    period = _find_period(_find_service(body, "ventas"), "2026-07")
    png = next(f for f in period["imagenes"] if f["name"] == "Ventas Test_Hoja1_A1_D10.png")
    assert png["sheet"] == "Hoja1"
    assert png["range"] == "A1:D10"


def test_tree_resolves_a_sheet_name_containing_underscores(artifacts_root, client):
    """PNG names are `{xlsx_stem}_{sheet}_{topLeft}_{bottomRight}.png`.

    Both the stem and the sheet name may contain underscores, so the split is
    ambiguous on the filename alone. It is resolved against the sibling xlsx
    that produced the capture — greedy matching would report the last segment
    ("1") as the sheet, which is a wrong answer presented as a certain one.
    """
    period = artifacts_root / "ventas" / "2026-07"
    (period / "Reporte Mensual.xlsx").write_bytes(b"x")
    (period / "Reporte Mensual_AVANCE_B2_A1_D10.png").write_bytes(b"x")

    body = client.get("/mgmt/artifacts/tree").json()
    node = _find_period(_find_service(body, "ventas"), "2026-07")
    png = next(
        f for f in node["imagenes"] if f["name"] == "Reporte Mensual_AVANCE_B2_A1_D10.png"
    )
    assert png["sheet"] == "AVANCE_B2"
    assert png["range"] == "A1:D10"


def test_tree_reports_range_but_no_sheet_when_no_sibling_xlsx_confirms_it(
    artifacts_root, client
):
    """Without the source workbook the sheet cannot be determined.

    The range is still unambiguous (the trailing two cell refs), so it is
    reported; the sheet is omitted rather than guessed.
    """
    (artifacts_root / "ventas" / "2026-07" / "Huerfano_Algo_Mas_A1_D10.png").write_bytes(b"x")

    body = client.get("/mgmt/artifacts/tree").json()
    node = _find_period(_find_service(body, "ventas"), "2026-07")
    png = next(f for f in node["imagenes"] if f["name"] == "Huerfano_Algo_Mas_A1_D10.png")
    assert png["range"] == "A1:D10"
    assert "sheet" not in png


def test_tree_flags_loose_root_files_as_unclassified(client):
    body = client.get("/mgmt/artifacts/tree").json()
    names = {f["name"] for f in body["unclassified"]}
    assert "loose_file.xlsx" in names


def test_tree_surfaces_loose_service_level_files(artifacts_root, client):
    """A file sitting in a service dir but outside any period folder.

    It belongs to no period, so it must still reach the unclassified bucket
    rather than disappearing from the tree entirely.
    """
    (artifacts_root / "ventas" / "suelto_sin_periodo.xlsx").write_bytes(b"x")

    body = client.get("/mgmt/artifacts/tree").json()
    names = {f["name"] for f in body["unclassified"]}
    assert "suelto_sin_periodo.xlsx" in names


def test_tree_includes_pngs_from_a_period_subdirectory(client):
    """graficos-cobertura writes its PNGs into a png/ subfolder, not flat."""
    body = client.get("/mgmt/artifacts/tree").json()
    period = _find_period(_find_service(body, "graficos-cobertura"), "2026-07")
    names = {f["name"] for f in period["imagenes"]}
    assert "CERVEZAS_zona_NOA.png" in names


def test_tree_skips_underscore_prefixed_non_service_dirs(client):
    """_send_log holds the delivery log — it is not a report service."""
    body = client.get("/mgmt/artifacts/tree").json()
    assert all(s["slug"] != "_send_log" for s in body["services"])
    assert all(not f["name"].endswith(".json") for f in body["unclassified"])


def test_tree_flags_known_anomalous_period_folder(client):
    body = client.get("/mgmt/artifacts/tree").json()
    period = _find_period(_find_service(body, "resumen-mensual"), "2026-06.contaminated")
    assert period["anomalous"] is True
    # Files inside an anomalous folder are still surfaced, not silently dropped.
    assert {f["name"] for f in period["principal"]} == {"resumen.xlsx"}


def test_tree_does_not_flag_valid_month_period_as_anomalous(client):
    body = client.get("/mgmt/artifacts/tree").json()
    period = _find_period(_find_service(body, "ventas"), "2026-07")
    assert period["anomalous"] is False


def test_tree_does_not_flag_valid_day_period_as_anomalous(client):
    """stock-diario uses YYYY-MM-DD granularity — must be recognized, not anomalous."""
    body = client.get("/mgmt/artifacts/tree").json()
    period = _find_period(_find_service(body, "stock-diario"), "2026-08-11")
    assert period["anomalous"] is False


def test_tree_filters_by_slug(client):
    body = client.get("/mgmt/artifacts/tree?slug=ventas").json()
    assert {s["slug"] for s in body["services"]} == {"ventas"}


def test_tree_filters_by_slug_and_periodo(client):
    body = client.get("/mgmt/artifacts/tree?slug=ventas&periodo=2026-07").json()
    service = _find_service(body, "ventas")
    assert {p["periodo"] for p in service["periods"]} == {"2026-07"}


def test_tree_on_missing_root_returns_honest_empty_state(tmp_path):
    """data/output/ does not exist in this worktree — must not crash."""
    from src.api.routes.mgmt_artifacts import router, set_artifacts_root

    set_artifacts_root(tmp_path / "does-not-exist")
    try:
        test_app = FastAPI()
        test_app.include_router(router)
        r = TestClient(test_app).get("/mgmt/artifacts/tree")
        assert r.status_code == 200
        assert r.json() == {"services": [], "unclassified": []}
    finally:
        set_artifacts_root(None)


# ---------------------------------------------------------------------------
# GET /mgmt/artifacts/file — RF-15 path traversal
# ---------------------------------------------------------------------------


def test_file_endpoint_serves_valid_path(client):
    r = client.get("/mgmt/artifacts/file?path=ventas/2026-07/Ventas Test.xlsx")
    assert r.status_code == 200
    assert r.content == b"fake-xlsx"


def test_file_endpoint_404_for_missing_file(client):
    r = client.get("/mgmt/artifacts/file?path=ventas/2026-07/nope.xlsx")
    assert r.status_code == 404


def test_file_endpoint_rejects_dotdot_traversal(client):
    r = client.get("/mgmt/artifacts/file?path=../../etc/passwd")
    assert r.status_code == 400


def test_file_endpoint_rejects_absolute_path_outside_root(client):
    r = client.get("/mgmt/artifacts/file?path=/etc/passwd")
    assert r.status_code == 400


def test_file_endpoint_rejects_nested_dotdot_traversal(client):
    r = client.get("/mgmt/artifacts/file?path=ventas/2026-07/../../../../etc/passwd")
    assert r.status_code == 400


def test_file_endpoint_rejects_a_null_byte_instead_of_crashing(client):
    """Path.resolve() raises ValueError on an embedded null byte.

    Unhandled, that reaches the client as a 500 on user-controlled input;
    RF-15 says bad paths are rejected with 4xx.
    """
    r = client.get("/mgmt/artifacts/file", params={"path": "ventas/\x00/x.xlsx"})
    assert r.status_code == 400


@pytest.mark.parametrize("bad_path", ["", ".", "..", "ventas/2026-07"])
def test_file_endpoint_never_500s_on_odd_paths(client, bad_path):
    """Directories and empty paths are 4xx, never an unhandled exception."""
    r = client.get("/mgmt/artifacts/file", params={"path": bad_path})
    assert 400 <= r.status_code < 500


def test_file_endpoint_sets_inline_disposition_only_for_png(artifacts_root, client):
    """RF-16 — PNGs are the inline preview; everything else downloads."""
    png = client.get(
        "/mgmt/artifacts/file",
        params={"path": "ventas/2026-07/Ventas Test_Hoja1_A1_D10.png"},
    )
    assert png.status_code == 200
    assert png.headers["content-disposition"].startswith("inline")

    xlsx = client.get(
        "/mgmt/artifacts/file", params={"path": "ventas/2026-07/Ventas Test.xlsx"}
    )
    assert xlsx.status_code == 200
    assert xlsx.headers["content-disposition"].startswith("attachment")


# ---------------------------------------------------------------------------
# Symlinks — a link inside the tree must not expose its target
# ---------------------------------------------------------------------------


def test_tree_omits_symlinks_pointing_outside_the_root(artifacts_root, client, tmp_path):
    """A symlink escaping the root is dropped from the tree entirely.

    Listing it would publish the target's name, size and mtime (stat follows
    the link) and offer a download the file endpoint then rejects with 400 —
    a file the UI shows but can never open.
    """
    secret = tmp_path / "secret.xlsx"
    secret.write_bytes(b"outside-the-root")
    (artifacts_root / "ventas" / "2026-07" / "escape.xlsx").symlink_to(secret)

    body = client.get("/mgmt/artifacts/tree").json()
    period = _find_period(_find_service(body, "ventas"), "2026-07")
    all_names = {
        f["name"]
        for bucket in ("principal", "imagenes", "backups")
        for f in period[bucket]
    }
    assert "escape.xlsx" not in all_names


def test_file_endpoint_rejects_a_symlink_escaping_the_root(artifacts_root, client, tmp_path):
    secret = tmp_path / "secret.xlsx"
    secret.write_bytes(b"outside-the-root")
    (artifacts_root / "ventas" / "2026-07" / "escape.xlsx").symlink_to(secret)

    r = client.get("/mgmt/artifacts/file?path=ventas/2026-07/escape.xlsx")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# RF-17 — no DELETE exposed anywhere under /mgmt/artifacts/*
# ---------------------------------------------------------------------------


def test_openapi_schema_has_no_delete_method_under_artifacts(app):
    schema = app.openapi()
    for path, methods in schema["paths"].items():
        if path.startswith("/artifacts") or path.startswith("/mgmt/artifacts"):
            assert "delete" not in methods, f"unexpected DELETE on {path}"


# ---------------------------------------------------------------------------
# RF-16 — no LibreOffice/soffice invocation anywhere under mgmt routes
# ---------------------------------------------------------------------------


def test_no_libreoffice_invocation_in_mgmt_routes():
    routes_dir = REPO_ROOT / "src" / "api" / "routes"
    forbidden = re.compile(r"soffice|libreoffice", re.IGNORECASE)
    offenders = []
    for path in sorted(routes_dir.glob("mgmt_*.py")):
        text = path.read_text(encoding="utf-8")
        if forbidden.search(text):
            offenders.append(path.name)
    assert offenders == []


# ---------------------------------------------------------------------------
# Artifacts root resolution — env override
# ---------------------------------------------------------------------------


def test_artifacts_root_honors_env_override(tmp_path, monkeypatch):
    """ADMIN_PANEL_ARTIFACTS_ROOT lets the panel read a data/output/ tree that
    lives outside this checkout (e.g. reviewing the production tree from a
    worktree) without editing the untouchable config/settings.py."""
    from src.api.routes import mgmt_artifacts

    external = tmp_path / "elsewhere"
    (external / "ventas" / "2026-07").mkdir(parents=True)

    mgmt_artifacts.set_artifacts_root(None)
    monkeypatch.setenv("ADMIN_PANEL_ARTIFACTS_ROOT", str(external))
    assert mgmt_artifacts._get_artifacts_root() == external


def test_explicit_root_override_wins_over_env(tmp_path, monkeypatch):
    """set_artifacts_root() is what the tests use; it must not be silently
    overridden by an env var left set in the developer's shell."""
    from src.api.routes import mgmt_artifacts

    explicit = tmp_path / "explicit"
    explicit.mkdir()
    monkeypatch.setenv("ADMIN_PANEL_ARTIFACTS_ROOT", str(tmp_path / "from-env"))
    mgmt_artifacts.set_artifacts_root(explicit)
    try:
        assert mgmt_artifacts._get_artifacts_root() == explicit
    finally:
        mgmt_artifacts.set_artifacts_root(None)


# ---------------------------------------------------------------------------
# Backup-name classification edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("Ventas.bak.20260801-1200.xlsx", "backups"),
        ("Ventas.bak", "backups"),
        ("Ventas_backup.xlsx", "backups"),
        ("Ventas_backup-20260801-manual.xlsx", "backups"),
        # "bak" counts only as the backup marker, never as a word fragment.
        ("informe.bakery.xlsx", "principal"),
        ("bakery_ventas.xlsx", "principal"),
        ("Ventas.xlsx", "principal"),
        ("Ventas_Hoja1_A1_D10.png", "imagenes"),
    ],
)
def test_bucket_for_classifies_backup_conventions(filename, expected):
    from src.api.routes.mgmt_artifacts import _bucket_for

    assert _bucket_for(Path(filename)) == expected


# ---------------------------------------------------------------------------
# Resilience — data/output/ is written by the daily while the panel reads it
# ---------------------------------------------------------------------------


def test_tree_survives_a_file_vanishing_mid_scan(artifacts_root, client, monkeypatch):
    """The daily pipeline writes into data/output/ while the panel reads it.

    A file removed between listing and stat() must cost that one entry, not
    the whole tree — a 500 would blank the entire Archivos screen.
    """
    real_stat = Path.stat
    doomed = "Ventas Test.xlsx"

    def flaky_stat(self, *args, **kwargs):
        if self.name == doomed:
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)

    r = client.get("/mgmt/artifacts/tree")
    assert r.status_code == 200
    period = _find_period(_find_service(r.json(), "ventas"), "2026-07")
    assert doomed not in {f["name"] for f in period["principal"]}
    # The rest of the period survives.
    assert {f["name"] for f in period["backups"]} == {
        "Ventas Test_backup.xlsx",
        "Ventas Test_backup-20260801-manual.xlsx",
    }


def test_tree_survives_an_unreadable_directory(artifacts_root, client, monkeypatch):
    """A permission-denied directory must not take down the whole tree."""
    real_iterdir = Path.iterdir

    def flaky_iterdir(self, *args, **kwargs):
        if self.name == "2026-07" and self.parent.name == "ventas":
            raise PermissionError(13, "Permission denied", str(self))
        return real_iterdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "iterdir", flaky_iterdir)

    r = client.get("/mgmt/artifacts/tree")
    assert r.status_code == 200
    body = r.json()
    # Reported as unreadable, not silently shown as an empty period.
    period = _find_period(_find_service(body, "ventas"), "2026-07")
    assert period["unreadable"] is True
    # Other services are unaffected.
    assert _find_period(_find_service(body, "stock-diario"), "2026-08-11")


def test_tree_flags_a_whole_service_that_cannot_be_listed(artifacts_root, client, monkeypatch):
    """The service directory itself is unreadable — its periods are unknown."""
    real_iterdir = Path.iterdir

    def flaky_iterdir(self, *args, **kwargs):
        if self.name == "ventas":
            raise PermissionError(13, "Permission denied", str(self))
        return real_iterdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "iterdir", flaky_iterdir)

    body = client.get("/mgmt/artifacts/tree").json()
    ventas = _find_service(body, "ventas")
    assert ventas["unreadable"] is True
    assert ventas["periods"] == []
    assert _find_service(body, "stock-diario")["unreadable"] is False


# ---------------------------------------------------------------------------
# Filter consistency
# ---------------------------------------------------------------------------


def test_periodo_filter_also_narrows_the_unclassified_bucket(artifacts_root, client):
    """A service-level stray belongs to no period, so a period-filtered
    request must not return it — otherwise the two buckets answer different
    questions for the same query."""
    (artifacts_root / "ventas" / "suelto_sin_periodo.xlsx").write_bytes(b"x")

    body = client.get("/mgmt/artifacts/tree?slug=ventas&periodo=2026-07").json()
    assert body["unclassified"] == []

    # Without the filter it is still surfaced.
    unfiltered = client.get("/mgmt/artifacts/tree?slug=ventas").json()
    assert "suelto_sin_periodo.xlsx" in {f["name"] for f in unfiltered["unclassified"]}
