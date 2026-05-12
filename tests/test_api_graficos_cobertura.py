"""API tests for graficos-cobertura per-sucursal endpoints (T-004)."""
from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import app
from src.api.routes.graficos_cobertura import get_data_loader, get_config
from src.services.graficos_cobertura.config import GraficosCoberturaConfig
from src.services.graficos_cobertura.constants import (
    GENERICOS_INCLUIDOS,
    ZONAS,
    ZONA_SLUGS,
    ZONA_SUCS_AGUAS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_mock_loader(sucursal_nombres: dict[int, str] | None = None):
    """Create a mock DataLoader with configurable sucursal nombres."""
    loader = MagicMock()
    default_nombres = {
        1: "CASA CENTRAL",
        3: "SUCURSAL ORAN",
        4: "SUCURSAL TARTAGAL",
        5: "SUCURSAL GENERAL GUEMES",
        6: "SUCURSAL MOLINOS",
        7: "SUCURSAL CAFAYATE",
        9: "SUCURSAL ABIERTA",
        10: "SUCURSAL PERICO",
        11: "SUCURSAL PALPALA",
        12: "SUCURSAL SAN PEDRO",
        13: "SUCURSAL LIBERTADOR",
        14: "SUCURSAL LA QUIACA",
        15: "SUCURSAL ABRA PAMPA",
        16: "SUCURSAL METAN",
    }
    if sucursal_nombres:
        default_nombres.update(sucursal_nombres)
    loader.get_sucursal_nombres.return_value = default_nombres

    # Default mock data for per-sucursal coverage
    marca_df = pd.DataFrame({
        "anio": [2026, 2026],
        "mes": [1, 2],
        "id_sucursal": [1, 1],
        "marca": ["SALTA", "HEINEKEN"],
        "clientes": [150, 120],
    })
    generico_df = pd.DataFrame({
        "anio": [2026, 2026],
        "mes": [1, 2],
        "id_sucursal": [1, 1],
        "generico": ["CERVEZAS", "CERVEZAS"],
        "clientes": [300, 280],
    })

    loader.get_cobertura_sucursal_marca.return_value = marca_df
    loader.get_cobertura_sucursal_generico.return_value = generico_df
    loader.get_cobertura_graficos_aguas_sucursal.return_value = pd.DataFrame(
        columns=["anio", "mes", "id_sucursal", "subdivision_aguas", "clientes"]
    )
    loader.get_cobertura_graficos_marca_ruta.return_value = pd.DataFrame(
        columns=["anio", "mes", "id_ruta", "marca", "clientes"]
    )
    loader.get_cobertura_graficos_generico_ruta.return_value = pd.DataFrame(
        columns=["anio", "mes", "id_ruta", "generico", "clientes"]
    )
    loader.get_cobertura_graficos_generico_sucursal.return_value = pd.DataFrame(
        columns=["anio", "mes", "generico", "clientes"]
    )
    loader.get_articulos.return_value = pd.DataFrame({
        "generico": ["CERVEZAS", "CERVEZAS"],
        "marca": ["SALTA", "HEINEKEN"],
    })

    return loader


@pytest.fixture
def client():
    """TestClient with dependency overrides cleaned up after each test."""
    tc = TestClient(app)
    yield tc
    app.dependency_overrides.clear()


# ── GET /graficos-cobertura/zonas ────────────────────────────────────────────

class TestZonasEndpoint:
    """GET /graficos-cobertura/zonas returns zone→sucursal mapping."""

    def test_returns_200_with_zones_structure(self, client):
        """Zonas response includes expected zone names and sucursal structure."""
        mock_loader = _make_mock_loader()
        app.dependency_overrides[get_data_loader] = lambda: mock_loader
        try:
            response = client.get("/graficos-cobertura/zonas")
        finally:
            app.dependency_overrides.pop(get_data_loader, None)

        assert response.status_code == 200
        body = response.json()
        assert "zonas" in body
        zonas = body["zonas"]
        assert len(zonas) == len(ZONAS)

    def test_each_zone_has_required_fields(self, client):
        """Each zone object has nombre, slug, sucursales."""
        mock_loader = _make_mock_loader()
        app.dependency_overrides[get_data_loader] = lambda: mock_loader
        try:
            response = client.get("/graficos-cobertura/zonas")
        finally:
            app.dependency_overrides.pop(get_data_loader, None)

        body = response.json()
        for zona in body["zonas"]:
            assert "nombre" in zona
            assert "slug" in zona
            assert "sucursales" in zona
            assert isinstance(zona["sucursales"], list)
            for suc in zona["sucursales"]:
                assert "id" in suc
                assert "nombre" in suc

    def test_sucursal_nombre_from_database(self, client):
        """Sucursal nombres come from dim_sucursal via DataLoader."""
        mock_loader = _make_mock_loader({1: "CASA CENTRAL MODIFICADA"})
        app.dependency_overrides[get_data_loader] = lambda: mock_loader
        try:
            response = client.get("/graficos-cobertura/zonas")
        finally:
            app.dependency_overrides.pop(get_data_loader, None)

        body = response.json()
        salta_capital = next(
            z for z in body["zonas"] if z["nombre"] == "SALTA CAPITAL"
        )
        suc_names = [s["nombre"] for s in salta_capital["sucursales"]]
        assert "CASA CENTRAL MODIFICADA" in suc_names
        mock_loader.get_sucursal_nombres.assert_called_once()

    def test_noa_norte_includes_all_sucursales(self, client):
        """NOA NORTE (None in ZONA_SUCS_AGUAS) returns all sucursales from DB."""
        mock_loader = _make_mock_loader()
        app.dependency_overrides[get_data_loader] = lambda: mock_loader
        try:
            response = client.get("/graficos-cobertura/zonas")
        finally:
            app.dependency_overrides.pop(get_data_loader, None)

        body = response.json()
        noa_norte = next(
            z for z in body["zonas"] if z["nombre"] == "NOA NORTE"
        )
        # NOA NORTE has None in ZONA_SUCS_AGUAS → should return ALL sucursales from DB
        assert len(noa_norte["sucursales"]) > 0


# ── GET /graficos-cobertura/cobertura-sucursal ───────────────────────────────

class TestCoberturaSucursalEndpoint:
    """GET /graficos-cobertura/cobertura-sucursal returns Chart.js data."""

    def _override_deps(self, mock_loader, fecha_desde="2026-01-01", fecha_hasta="2026-04-30"):
        """Override both get_data_loader and get_config dependencies."""
        config = GraficosCoberturaConfig(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        app.dependency_overrides[get_data_loader] = lambda: mock_loader
        app.dependency_overrides[get_config] = lambda: config
        return config

    def _cleanup_deps(self):
        """Clear dependency overrides."""
        app.dependency_overrides.pop(get_data_loader, None)
        app.dependency_overrides.pop(get_config, None)

    def test_valid_params_returns_200(self, client):
        """Valid zona, generico, id_sucursal, and dates returns 200."""
        mock_loader = _make_mock_loader()
        self._override_deps(mock_loader)
        try:
            response = client.get(
                "/graficos-cobertura/cobertura-sucursal",
                params={
                    "zona": "SALTA CAPITAL",
                    "generico": "CERVEZAS",
                    "id_sucursal": 1,
                    "fecha_desde": "2026-01-01",
                    "fecha_hasta": "2026-04-30",
                },
            )
        finally:
            self._cleanup_deps()

        assert response.status_code == 200
        body = response.json()
        assert "sucursal" in body
        assert "generico" in body
        assert "chart_cobertura" in body
        assert "chart_comparacion" in body
        assert body["generico"] == "CERVEZAS"
        assert body["sucursal"]["id"] == 1
        assert body["sucursal"]["nombre"] == "CASA CENTRAL"

    def test_cobertura_chart_is_chartjs_format(self, client):
        """chart_cobertura dict has type, data, and options keys."""
        mock_loader = _make_mock_loader()
        self._override_deps(mock_loader)
        try:
            response = client.get(
                "/graficos-cobertura/cobertura-sucursal",
                params={
                    "zona": "SALTA CAPITAL",
                    "generico": "CERVEZAS",
                    "id_sucursal": 1,
                    "fecha_desde": "2026-01-01",
                    "fecha_hasta": "2026-04-30",
                },
            )
        finally:
            self._cleanup_deps()

        body = response.json()
        chart = body["chart_cobertura"]
        assert "type" in chart
        assert "data" in chart
        assert "labels" in chart["data"] or "datasets" in chart["data"]

    def test_invalid_zona_returns_404(self, client):
        """A zona name not in ZONAS returns 404."""
        mock_loader = _make_mock_loader()
        self._override_deps(mock_loader)
        try:
            response = client.get(
                "/graficos-cobertura/cobertura-sucursal",
                params={
                    "zona": "ZONA INEXISTENTE",
                    "generico": "CERVEZAS",
                    "id_sucursal": 1,
                    "fecha_desde": "2026-01-01",
                    "fecha_hasta": "2026-04-30",
                },
            )
        finally:
            self._cleanup_deps()

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_sucursal_not_in_zona_returns_404(self, client):
        """An id_sucursal that does not belong to the zona returns 404."""
        mock_loader = _make_mock_loader()
        self._override_deps(mock_loader)
        try:
            # id_sucursal=9 (JUJUY) is not in SALTA CAPITAL ([1])
            response = client.get(
                "/graficos-cobertura/cobertura-sucursal",
                params={
                    "zona": "SALTA CAPITAL",
                    "generico": "CERVEZAS",
                    "id_sucursal": 9,
                    "fecha_desde": "2026-01-01",
                    "fecha_hasta": "2026-04-30",
                },
            )
        finally:
            self._cleanup_deps()

        assert response.status_code == 404
        assert "does not belong" in response.json()["detail"].lower()

    def test_missing_required_params_returns_422(self, client):
        """Missing required query params returns 422 validation error."""
        response = client.get("/graficos-cobertura/cobertura-sucursal")
        assert response.status_code == 422

    def test_missing_fecha_desde_returns_422(self, client):
        """Missing fecha_desde returns 422."""
        response = client.get(
            "/graficos-cobertura/cobertura-sucursal",
            params={
                "zona": "SALTA CAPITAL",
                "generico": "CERVEZAS",
                "id_sucursal": 1,
                "fecha_hasta": "2026-04-30",
            },
        )
        assert response.status_code == 422

    def test_invalid_date_format_returns_422(self, client):
        """Invalid date format returns 422."""
        # Note: This test doesn't need DB mocks because 422 happens before DB access
        response = client.get(
            "/graficos-cobertura/cobertura-sucursal",
            params={
                "zona": "SALTA CAPITAL",
                "generico": "CERVEZAS",
                "id_sucursal": 1,
                "fecha_desde": "not-a-date",
                "fecha_hasta": "2026-04-30",
            },
        )
        assert response.status_code == 422

    def test_noa_norte_accepts_any_sucursal(self, client):
        """NOA NORTE (all sucursales) accepts any id_sucursal present in DB."""
        mock_loader = _make_mock_loader()
        self._override_deps(mock_loader)
        try:
            response = client.get(
                "/graficos-cobertura/cobertura-sucursal",
                params={
                    "zona": "NOA NORTE",
                    "generico": "CERVEZAS",
                    "id_sucursal": 1,
                    "fecha_desde": "2026-01-01",
                    "fecha_hasta": "2026-04-30",
                },
            )
        finally:
            self._cleanup_deps()

        assert response.status_code == 200


class TestDashboardRoute:
    """Tests for GET /dashboard/graficos-cobertura."""

    def test_dashboard_returns_html(self, client):
        """Dashboard route returns the HTML template with 200."""
        response = client.get("/dashboard/graficos_cobertura")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        body = response.text
        assert "Cobertura por Sucursal" in body
        assert "chart.js" in body.lower() or "Chart.js" in body

    def test_dashboard_contains_generico_dropdown(self, client):
        """Dashboard HTML contains the generico dropdown populated with GENERICOS_INCLUIDOS."""
        response = client.get("/dashboard/graficos_cobertura")
        assert response.status_code == 200
        body = response.text
        for generico in GENERICOS_INCLUIDOS:
            assert generico in body, f"Generico {generico} not found in dashboard HTML"