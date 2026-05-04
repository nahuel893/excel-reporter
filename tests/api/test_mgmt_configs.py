"""
Tests for T-107/T-108: mgmt_configs.py — config CRUD + schema + refs.

TDD: written BEFORE implementation.
"""
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def configs_dir(tmp_path):
    """Create a temporary configs directory with a ventas config."""
    d = tmp_path / "configs"
    d.mkdir()

    ventas = {
        "tipo": "ventas",
        "filtros": {
            "fecha_desde": "2026-01-01",
            "fecha_hasta": "2026-01-31",
        },
        "reportes": [{"nombre": "Ventas Test"}]
    }
    (d / "ventas.json").write_text(json.dumps(ventas, indent=2))

    contactos = {
        "Juan Perez": {"email": "juan@example.com"}
    }
    (d / "contactos.json").write_text(json.dumps(contactos, indent=2))
    return d


@pytest.fixture
def app(configs_dir):
    """Create a test FastAPI app with mgmt_configs router."""
    from src.api.routes.mgmt_configs import router, set_configs_dir
    set_configs_dir(configs_dir)

    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


def test_list_configs_returns_all_json_files(app, configs_dir):
    """GET /mgmt/configs returns all .json files in configs dir."""
    client = TestClient(app)
    r = client.get("/mgmt/configs")
    assert r.status_code == 200
    items = r.json()
    filenames = {i["filename"] for i in items}
    assert "ventas.json" in filenames


def test_list_configs_includes_tipo(app, configs_dir):
    """Each config in list includes 'tipo' field."""
    client = TestClient(app)
    r = client.get("/mgmt/configs")
    items = r.json()
    ventas = next(i for i in items if i["filename"] == "ventas.json")
    assert ventas["tipo"] == "ventas"


def test_list_configs_includes_mtime(app, configs_dir):
    """Each config includes mtime in ISO8601 format."""
    client = TestClient(app)
    r = client.get("/mgmt/configs")
    items = r.json()
    ventas = next(i for i in items if i["filename"] == "ventas.json")
    assert "mtime" in ventas
    assert "T" in ventas["mtime"]  # ISO8601 contains T


def test_get_config_returns_content_and_schema(app, configs_dir):
    """GET /mgmt/configs/{filename} returns {content, schema}."""
    client = TestClient(app)
    r = client.get("/mgmt/configs/ventas.json")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body
    assert "schema" in body
    assert body["content"]["tipo"] == "ventas"


def test_get_config_404_for_unknown(app):
    """GET /mgmt/configs/nonexistent.json returns 404."""
    client = TestClient(app)
    r = client.get("/mgmt/configs/nonexistent.json")
    assert r.status_code == 404


def test_put_config_validates_and_writes(app, configs_dir):
    """PUT /mgmt/configs/ventas.json with valid body writes file atomically."""
    client = TestClient(app)
    new_content = {
        "tipo": "ventas",
        "filtros": {
            "fecha_desde": "2026-02-01",
            "fecha_hasta": "2026-02-28",
        },
        "reportes": [{"nombre": "Ventas Febrero"}]
    }
    r = client.put("/mgmt/configs/ventas.json", json=new_content)
    assert r.status_code == 200

    # File on disk should reflect new content
    on_disk = json.loads((configs_dir / "ventas.json").read_text())
    assert on_disk["filtros"]["fecha_desde"] == "2026-02-01"


def test_put_config_returns_422_for_invalid_tipo(app, configs_dir):
    """PUT with wrong tipo returns 422 without touching file."""
    import os
    client = TestClient(app)
    original = (configs_dir / "ventas.json").read_text()
    mtime_before = os.path.getmtime(configs_dir / "ventas.json")

    invalid_content = {
        "tipo": "not-a-real-tipo",
        "filtros": {"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"},
        "reportes": []
    }
    r = client.put("/mgmt/configs/ventas.json", json=invalid_content)
    assert r.status_code == 422

    # File unchanged
    assert (configs_dir / "ventas.json").read_text() == original


def test_schema_endpoint_returns_json_schema(app):
    """GET /mgmt/configs/schema/ventas returns a JSON Schema dict."""
    client = TestClient(app)
    r = client.get("/mgmt/configs/schema/ventas")
    assert r.status_code == 200
    schema = r.json()
    assert "$defs" in schema or "properties" in schema


def test_path_exists_endpoint(app, tmp_path):
    """GET /mgmt/configs/path-exists?path=... returns {exists, is_file}."""
    client = TestClient(app)
    real_file = tmp_path / "test.xlsx"
    real_file.write_text("fake")

    r = client.get(f"/mgmt/configs/path-exists?path={real_file}")
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["is_file"] is True

    r2 = client.get("/mgmt/configs/path-exists?path=/nonexistent/file.xlsx")
    assert r2.status_code == 200
    assert r2.json()["exists"] is False


def test_get_contactos(app, configs_dir):
    """GET /mgmt/contactos returns content of contactos.json."""
    client = TestClient(app)
    r = client.get("/mgmt/contactos")
    assert r.status_code == 200
    body = r.json()
    assert "Juan Perez" in body


def test_put_contactos(app, configs_dir):
    """PUT /mgmt/contactos updates contactos.json."""
    client = TestClient(app)
    new_contactos = {
        "Maria Garcia": {"email": "maria@example.com"},
    }
    r = client.put("/mgmt/contactos", json=new_contactos)
    assert r.status_code == 200

    on_disk = json.loads((configs_dir / "contactos.json").read_text())
    assert "Maria Garcia" in on_disk
