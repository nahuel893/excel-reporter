"""API tests for graficos-cobertura routes."""
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api import app
from src.services.graficos_cobertura.service import GraficosCoberturaResult


@pytest.fixture
def client():
    return TestClient(app)


def _fake_result(tmp_path):
    run_dir = tmp_path / "2026-01"
    png_dir = run_dir / "png"
    png_dir.mkdir(parents=True)
    xlsx = run_dir / "resumen.xlsx"
    xlsx.write_bytes(b"fake xlsx content")
    generico = run_dir / "cobertura_todos.pptx"
    generico.write_bytes(b"fake generico content")
    (png_dir / "cobertura_noa_norte_cervezas.png").write_bytes(b"\x89PNG fake")

    return GraficosCoberturaResult(
        ruta_directorio=run_dir,
        archivo_xlsx=xlsx,
        archivo_generico_pptx=generico,
        graficos_generados=25,
        zonas_incluidas=["NOA NORTE", "SALTA CAPITAL"],
        genericos_incluidos=["CERVEZAS"],
    )


class TestReporteEndpoint:
    """RF-023: POST /graficos-cobertura/reporte returns 200 + JSON metadata."""

    def test_returns_200_with_metadata(self, client, tmp_path):
        result = _fake_result(tmp_path)
        with patch(
            "src.api.routes.graficos_cobertura.GraficosCoberturaService"
        ) as MockSvc:
            MockSvc.return_value.generar_reporte.return_value = result
            response = client.post(
                "/graficos-cobertura/reporte",
                json={
                    "fecha_desde": "2026-01-01",
                    "fecha_hasta": "2026-04-30",
                    "id_fuerza_ventas": 1,
                    "con_aguas": True,
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["archivo_xlsx"].endswith("resumen.xlsx")
        assert body["archivo_generico_pptx"].endswith("cobertura_todos.pptx")
        assert body["graficos_generados"] == 25
        assert "NOA NORTE" in body["zonas_incluidas"]

    def test_invalid_date_returns_422(self, client):
        response = client.post(
            "/graficos-cobertura/reporte",
            json={"fecha_desde": "not-a-date", "fecha_hasta": "2026-04-30"},
        )
        assert response.status_code == 422


class TestDownloadEndpoint:
    """RF-024: POST /graficos-cobertura/reporte/download returns application/zip."""

    def test_returns_zip(self, client, tmp_path):
        result = _fake_result(tmp_path)
        with patch(
            "src.api.routes.graficos_cobertura.GraficosCoberturaService"
        ) as MockSvc:
            MockSvc.return_value.generar_reporte.return_value = result
            response = client.post(
                "/graficos-cobertura/reporte/download",
                json={"fecha_desde": "2026-01-01", "fecha_hasta": "2026-04-30"},
            )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "attachment" in response.headers.get("content-disposition", "")

    def test_zip_contains_expected_files(self, client, tmp_path):
        result = _fake_result(tmp_path)
        with patch(
            "src.api.routes.graficos_cobertura.GraficosCoberturaService"
        ) as MockSvc:
            MockSvc.return_value.generar_reporte.return_value = result
            response = client.post(
                "/graficos-cobertura/reporte/download",
                json={"fecha_desde": "2026-01-01", "fecha_hasta": "2026-04-30"},
            )

        import io
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        names = zf.namelist()
        assert "resumen.xlsx" in names
        assert "cobertura_todos.pptx" in names
        # png subdir preserved
        assert any(n.startswith("png/") for n in names)


class TestCliSubcommandWired:
    """RF-022: main.py has graficos-cobertura subcommand + dispatcher."""

    def test_subparser_registered(self):
        import subprocess

        result = subprocess.run(
            ["python", "main.py", "graficos-cobertura", "--help"],
            capture_output=True, text=True,
            cwd="/home/nahuel/projects/work/Informes Badie",
        )
        assert result.returncode == 0
        assert "--config" in result.stdout

    def test_dispatcher_branch_exists(self):
        """The dispatcher in main._run_reportes must route tipo=graficos-cobertura."""
        import main
        assert main.REPORT_HANDLERS.get("graficos-cobertura") == "_run_graficos_cobertura_report"
        assert hasattr(main, "_run_graficos_cobertura_report")
