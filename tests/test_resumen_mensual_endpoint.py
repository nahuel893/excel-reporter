"""
TDD tests for POST /resumen-mensual/datos endpoint (T04).

Written BEFORE the endpoint implementation (RED → GREEN cycle).

Tests:
  1. Valid request → HTTP 200 + schema shape (mock/inject service)
  2. Missing fecha_desde → HTTP 422
  3. New request fields (marca_splits, cupos_manuales, genericos_sin_prvta) flow into service
  4. Service raises exception → HTTP 500 with {"detail": ...}
  5. Service returns empty → HTTP 200, sheets: []
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# Import the app; the test uses TestClient for in-process requests
from api import app


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


def _minimal_datos_response() -> dict:
    """A minimal valid /datos response dict (returned by a mocked service)."""
    return {
        "meta": {
            "col_n1": "09-06 Martes",
            "col_n2": "08-06 Lunes",
            "info_dias": {"Dias Habiles": 22, "Dias Transcurridos": 7, "Dias Faltantes": 15},
            "con_objetivo": True,
        },
        "sheets": [
            {
                "generico": "CERVEZAS",
                "note": None,
                "sections": [
                    {
                        "label": "CERVEZAS",
                        "rows": [
                            {
                                "Sucursal": "CASA CENTRAL",
                                "col_n2": 450.0,
                                "col_n1": 512.0,
                                "Total Ventas": 12345.0,
                                "Tendencia": 38800.0,
                                "MMAA": 30000.0,
                                "MA": 28000.0,
                                "Objetivo": None,
                                "Tend vs Obj (%)": None,
                                "is_subtotal": False,
                            }
                        ],
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# TC-01: Valid request → HTTP 200 + schema shape
# ---------------------------------------------------------------------------

class TestValidRequest:
    def test_valid_request_returns_200(self, client):
        """Valid request body → HTTP 200."""
        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.return_value = _minimal_datos_response()
            mock_cls.return_value = mock_svc

            response = client.post(
                "/resumen-mensual/datos",
                json={
                    "fecha_desde": "2026-06-01",
                    "fecha_hasta": "2026-06-30",
                    "genericos": ["CERVEZAS"],
                    "con_objetivo": True,
                },
            )

        assert response.status_code == 200

    def test_valid_request_response_has_meta_and_sheets(self, client):
        """Valid request → response body has top-level 'meta' and 'sheets'."""
        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.return_value = _minimal_datos_response()
            mock_cls.return_value = mock_svc

            response = client.post(
                "/resumen-mensual/datos",
                json={
                    "fecha_desde": "2026-06-01",
                    "fecha_hasta": "2026-06-30",
                },
            )

        body = response.json()
        assert "meta" in body
        assert "sheets" in body

    def test_valid_request_meta_has_required_fields(self, client):
        """Valid request → meta has col_n1, col_n2, info_dias, con_objetivo."""
        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.return_value = _minimal_datos_response()
            mock_cls.return_value = mock_svc

            response = client.post(
                "/resumen-mensual/datos",
                json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-30"},
            )

        meta = response.json()["meta"]
        for key in ("col_n1", "col_n2", "info_dias", "con_objetivo"):
            assert key in meta, f"meta must have '{key}'"

    def test_valid_request_sheets_is_list(self, client):
        """Valid request → sheets is a list."""
        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.return_value = _minimal_datos_response()
            mock_cls.return_value = mock_svc

            response = client.post(
                "/resumen-mensual/datos",
                json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-30"},
            )

        assert isinstance(response.json()["sheets"], list)


# ---------------------------------------------------------------------------
# TC-02: Missing required fields → HTTP 422
# ---------------------------------------------------------------------------

class TestValidation:
    def test_missing_fecha_desde_returns_422(self, client):
        """Missing fecha_desde → HTTP 422 (validation error)."""
        response = client.post(
            "/resumen-mensual/datos",
            json={"fecha_hasta": "2026-06-30"},
        )
        assert response.status_code == 422

    def test_missing_fecha_hasta_returns_422(self, client):
        """Missing fecha_hasta → HTTP 422."""
        response = client.post(
            "/resumen-mensual/datos",
            json={"fecha_desde": "2026-06-01"},
        )
        assert response.status_code == 422

    def test_empty_body_returns_422(self, client):
        """Empty body → HTTP 422."""
        response = client.post("/resumen-mensual/datos", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# TC-03: New request fields flow into ResumenMensualConfig
# ---------------------------------------------------------------------------

class TestNewRequestFields:
    def test_marca_splits_flows_into_config(self, client):
        """marca_splits in request body flows into ResumenMensualConfig."""
        marca_splits = {"VINOS FINOS": ["QUARA"]}

        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.return_value = _minimal_datos_response()
            mock_cls.return_value = mock_svc

            client.post(
                "/resumen-mensual/datos",
                json={
                    "fecha_desde": "2026-06-01",
                    "fecha_hasta": "2026-06-30",
                    "marca_splits": marca_splits,
                },
            )

        call_config = mock_svc.generar_datos.call_args[0][0]
        assert call_config.marca_splits == marca_splits

    def test_cupos_manuales_flows_into_config(self, client):
        """cupos_manuales in request body flows into ResumenMensualConfig."""
        cupos_manuales = {"GUEMES": {"CERVEZAS": 500.0}}

        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.return_value = _minimal_datos_response()
            mock_cls.return_value = mock_svc

            client.post(
                "/resumen-mensual/datos",
                json={
                    "fecha_desde": "2026-06-01",
                    "fecha_hasta": "2026-06-30",
                    "cupos_manuales": cupos_manuales,
                },
            )

        call_config = mock_svc.generar_datos.call_args[0][0]
        assert call_config.cupos_manuales == cupos_manuales

    def test_genericos_sin_prvta_flows_into_config(self, client):
        """genericos_sin_prvta in request body flows into ResumenMensualConfig."""
        genericos_sin_prvta = ["FRATELLI B"]

        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.return_value = _minimal_datos_response()
            mock_cls.return_value = mock_svc

            client.post(
                "/resumen-mensual/datos",
                json={
                    "fecha_desde": "2026-06-01",
                    "fecha_hasta": "2026-06-30",
                    "genericos_sin_prvta": genericos_sin_prvta,
                },
            )

        call_config = mock_svc.generar_datos.call_args[0][0]
        assert call_config.genericos_sin_prvta == genericos_sin_prvta

    def test_all_new_fields_optional_with_defaults(self, client):
        """All new fields are optional; endpoint works without them."""
        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.return_value = _minimal_datos_response()
            mock_cls.return_value = mock_svc

            response = client.post(
                "/resumen-mensual/datos",
                json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-30"},
            )

        assert response.status_code == 200
        call_config = mock_svc.generar_datos.call_args[0][0]
        # Defaults should be None (will be resolved inside service)
        assert call_config.marca_splits is None
        assert call_config.cupos_manuales is None
        assert call_config.genericos_sin_prvta is None


# ---------------------------------------------------------------------------
# TC-04: Service raises exception → HTTP 500 with "detail"
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_service_exception_returns_500(self, client):
        """When service raises an exception → HTTP 500."""
        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.side_effect = RuntimeError("DB connection failed")
            mock_cls.return_value = mock_svc

            response = client.post(
                "/resumen-mensual/datos",
                json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-30"},
            )

        assert response.status_code == 500

    def test_service_exception_response_has_detail(self, client):
        """When service raises an exception → response body has 'detail' key."""
        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.side_effect = RuntimeError("DB connection failed")
            mock_cls.return_value = mock_svc

            response = client.post(
                "/resumen-mensual/datos",
                json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-30"},
            )

        body = response.json()
        assert "detail" in body

    def test_service_exception_detail_contains_message(self, client):
        """detail field carries the exception message."""
        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.side_effect = RuntimeError("DB connection failed")
            mock_cls.return_value = mock_svc

            response = client.post(
                "/resumen-mensual/datos",
                json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-30"},
            )

        assert "DB connection failed" in response.json()["detail"]


# ---------------------------------------------------------------------------
# TC-05: Service returns empty → HTTP 200 with sheets: []
# ---------------------------------------------------------------------------

class TestEmptyResponse:
    def test_empty_sheets_returns_200(self, client):
        """When service returns empty sheets → HTTP 200."""
        empty_response = {
            "meta": {
                "col_n1": "09-06 Martes",
                "col_n2": "08-06 Lunes",
                "info_dias": {"Dias Habiles": 22, "Dias Transcurridos": 7, "Dias Faltantes": 15},
                "con_objetivo": True,
            },
            "sheets": [],
        }

        with patch("src.api.routes.resumen_mensual.ResumenMensualService") as mock_cls:
            mock_svc = MagicMock()
            mock_svc.generar_datos.return_value = empty_response
            mock_cls.return_value = mock_svc

            response = client.post(
                "/resumen-mensual/datos",
                json={"fecha_desde": "2026-06-01", "fecha_hasta": "2026-06-30"},
            )

        assert response.status_code == 200
        assert response.json()["sheets"] == []
