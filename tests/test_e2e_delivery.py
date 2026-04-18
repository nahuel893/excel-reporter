"""
Test end-to-end del flujo completo: config → contactos → generacion → delivery.

Mockea SOLO las dependencias externas (BD, SMTP, WhatsApp, LibreOffice).
Ejercita REAL: config parsing, contact resolution, filter merging, pipeline orchestration.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.services.ventas import ReporteVentasResult


def _write_contactos(tmp_path: Path) -> Path:
    path = tmp_path / "contactos.json"
    path.write_text(json.dumps({
        "Walter Vilte": {"email": "walter@empresa.com", "telefono": "+5491155000001"},
        "Antonio Cabrerizo": {"email": "antonio@empresa.com"},
        "Grupo Gerencia": {"whatsapp_grupo": "Gerencia CCU"},
    }))
    return path


def _write_ventas_config(tmp_path: Path) -> Path:
    path = tmp_path / "ventas.json"
    path.write_text(json.dumps({
        "tipo": "ventas",
        "filtros": {
            "fecha_desde": "2026-02-01",
            "fecha_hasta": "2026-02-28",
            "genericos": ["CERVEZAS", "AGUAS DANONE"],
            "con_slicers": False,
            "con_cobertura": True,
        },
        "reportes": [
            {
                "nombre": "Ventas Walter Vilte",
                "filtros": {
                    "supervisores": ["Walter Vilte"],
                    "sucursales": ["SUCURSAL CAFAYATE", "CASA CENTRAL"],
                },
                "capture_image": {"hoja": "Ventas Bultos", "rango": "A1:H20"},
                "enviar_a": {
                    "Walter Vilte": {"via": ["email", "whatsapp"]},
                    "Grupo Gerencia": {"via": ["whatsapp"]},
                },
            },
            {
                "nombre": "Ventas Antonio Cabrerizo",
                "filtros": {
                    "supervisores": ["Antonio Cabrerizo"],
                    "sucursales": ["CASA CENTRAL"],
                },
                "enviar_a": {
                    "Antonio Cabrerizo": {"via": ["email"]},
                },
            },
        ],
    }))
    return path


def _make_fake_excel(tmp_path: Path, name: str) -> Path:
    xlsx = tmp_path / f"{name}.xlsx"
    xlsx.write_bytes(b"fake-excel")
    return xlsx


def _make_ventas_result(tmp_path: Path, supervisor: str) -> ReporteVentasResult:
    xlsx = _make_fake_excel(tmp_path, f"Ventas {supervisor}")
    return ReporteVentasResult(
        ruta_archivo=xlsx,
        registros_ventas=100,
        registros_procesados=50,
        sucursales=3,
        genericos_incluidos=["CERVEZAS", "AGUAS DANONE"],
        hojas=["Ventas Bultos", "Ventas HTLs"],
        slicers_agregados=False,
        supervisor=supervisor,
    )


class TestE2EDeliveryPipeline:
    """Test end-to-end: config file → contact resolution → report gen → delivery."""

    def test_full_flow_two_reports_with_delivery(self, tmp_path):
        """
        Config con 2 reportes:
        - Walter: email + whatsapp a Walter, whatsapp a Grupo Gerencia, con captura
        - Antonio: solo email a Antonio, sin captura

        Verifica que:
        1. Ambos reportes se generan con los filtros correctos
        2. El delivery pipeline se ejecuta POR CADA reporte
        3. Los contactos se resuelven correctamente a emails/grupos
        4. La captura de imagen se configura solo para Walter
        """
        _write_contactos(tmp_path)
        config_path = _write_ventas_config(tmp_path)

        # Mock del servicio de ventas
        mock_service = MagicMock()
        mock_service.generar_reporte_supervisores.side_effect = [
            [_make_ventas_result(tmp_path, "Walter Vilte")],
            [_make_ventas_result(tmp_path, "Antonio Cabrerizo")],
        ]

        # Mock del EmailSender
        mock_email_sender = MagicMock()

        # Mock del WhatsAppClient
        mock_wa_client = MagicMock()

        # Mock del ExcelManager (para capture_image)
        mock_excel_mgr = MagicMock()
        fake_png = tmp_path / "captura.png"
        fake_png.write_bytes(b"fake-png")
        mock_excel_mgr.capture_range.return_value = fake_png

        with (
            patch("main.VentasService", return_value=mock_service),
            patch("src.core.email_sender.EmailSender.send", mock_email_sender.send),
            patch("src.core.whatsapp_client.WhatsAppClient.send_image", mock_wa_client.send_image),
            patch("src.core.whatsapp_client.WhatsAppClient.send_file", mock_wa_client.send_file),
            patch("src.core.excel_renderers.libreoffice_renderer.ExcelManager", return_value=mock_excel_mgr),
        ):
            from main import _run_report_config
            result = _run_report_config(config_path)

        assert result == 0

        # Verify service was called twice (once per report entry)
        assert mock_service.generar_reporte_supervisores.call_count == 2

        # Verify first call filters (Walter: 2 sucursales)
        first_call = mock_service.generar_reporte_supervisores.call_args_list[0]
        first_config = first_call[0][0]  # ReporteVentasConfig
        first_supervisores = first_call[0][1]  # dict
        assert first_config.fecha_desde == "2026-02-01"
        assert first_config.genericos == ["CERVEZAS", "AGUAS DANONE"]
        assert first_config.con_slicers is False
        assert "Walter Vilte" in first_supervisores
        assert "SUCURSAL CAFAYATE" in first_supervisores["Walter Vilte"]

        # Verify second call filters (Antonio: 1 sucursal)
        second_call = mock_service.generar_reporte_supervisores.call_args_list[1]
        second_supervisores = second_call[0][1]
        assert "Antonio Cabrerizo" in second_supervisores
        assert second_supervisores["Antonio Cabrerizo"] == ["CASA CENTRAL"]

        # Verify email was called for BOTH reports
        email_calls = mock_email_sender.send.call_args_list
        assert len(email_calls) == 2

        # Walter's email
        walter_email_call = email_calls[0]
        assert walter_email_call[1]["destinatarios"] == ["walter@empresa.com"]

        # Antonio's email
        antonio_email_call = email_calls[1]
        assert antonio_email_call[1]["destinatarios"] == ["antonio@empresa.com"]

        # Verify WhatsApp was called only for Walter's report
        # Walter has whatsapp via telefono + Grupo Gerencia via whatsapp_grupo
        # CaptureImage produces a PNG, so send_image should be called
        wa_image_calls = mock_wa_client.send_image.call_args_list
        assert len(wa_image_calls) == 2  # one for Walter's telefono, one for Grupo
        groups_sent = {c[0][0] for c in wa_image_calls}
        assert "+5491155000001" in groups_sent
        assert "Gerencia CCU" in groups_sent

    def test_report_without_delivery_skips_pipeline(self, tmp_path):
        """Un reporte sin enviar_a no ejecuta el pipeline."""
        _write_contactos(tmp_path)
        config_path = tmp_path / "resumen.json"
        config_path.write_text(json.dumps({
            "tipo": "resumen-mensual",
            "filtros": {
                "fecha_desde": "2026-02-01",
                "fecha_hasta": "2026-02-28",
            },
            "reportes": [
                {"nombre": "Resumen Febrero"},
            ],
        }))

        mock_result = MagicMock()
        mock_result.ruta_archivo = tmp_path / "resumen.xlsx"
        mock_result.hojas = ["CERVEZAS"]
        mock_result.registros_procesados = 10
        mock_result.sucursales = 5
        mock_result.genericos_incluidos = ["CERVEZAS"]
        (tmp_path / "resumen.xlsx").write_bytes(b"fake")

        mock_service = MagicMock()
        mock_service.generar_reporte.return_value = mock_result

        mock_email = MagicMock()

        with (
            patch("main.ResumenMensualService", return_value=mock_service),
            patch("src.core.email_sender.EmailSender.send", mock_email.send),
        ):
            from main import _run_report_config
            result = _run_report_config(config_path)

        assert result == 0
        mock_email.send.assert_not_called()

    def test_unknown_contact_fails_validation(self, tmp_path):
        """Si enviar_a referencia un contacto que no existe, falla."""
        _write_contactos(tmp_path)
        config_path = tmp_path / "bad.json"
        config_path.write_text(json.dumps({
            "tipo": "ventas",
            "filtros": {
                "fecha_desde": "2026-02-01",
                "fecha_hasta": "2026-02-28",
            },
            "reportes": [
                {
                    "nombre": "Test",
                    "enviar_a": {
                        "No Existe": {"via": ["email"]},
                    },
                },
            ],
        }))

        from main import _run_report_config
        result = _run_report_config(config_path)
        assert result == 1  # validation error

    def test_config_dir_processes_all_files(self, tmp_path):
        """--config-dir procesa todos los JSON del directorio."""
        _write_contactos(tmp_path)

        # Write a simple ventas config
        ventas_path = tmp_path / "ventas.json"
        ventas_path.write_text(json.dumps({
            "tipo": "ventas",
            "filtros": {"fecha_desde": "2026-02-01", "fecha_hasta": "2026-02-28"},
            "reportes": [{"nombre": "Ventas Global"}],
        }))

        # Write a simple resumen config
        resumen_path = tmp_path / "resumen.json"
        resumen_path.write_text(json.dumps({
            "tipo": "resumen-mensual",
            "filtros": {"fecha_desde": "2026-02-01", "fecha_hasta": "2026-02-28"},
            "reportes": [{"nombre": "Resumen Global"}],
        }))

        mock_ventas_service = MagicMock()
        mock_ventas_result = MagicMock()
        mock_ventas_result.ruta_archivo = tmp_path / "ventas.xlsx"
        mock_ventas_result.hojas = ["Ventas Bultos", "Ventas HTLs"]
        mock_ventas_result.registros_ventas = 50
        mock_ventas_result.registros_procesados = 25
        mock_ventas_result.sucursales = 3
        mock_ventas_result.genericos_incluidos = ["CERVEZAS"]
        mock_ventas_result.slicers_agregados = False
        mock_ventas_result.supervisor = None
        (tmp_path / "ventas.xlsx").write_bytes(b"fake")
        mock_ventas_service.generar_reporte.return_value = mock_ventas_result

        mock_resumen_service = MagicMock()
        mock_resumen_result = MagicMock()
        mock_resumen_result.ruta_archivo = tmp_path / "resumen.xlsx"
        mock_resumen_result.hojas = ["CERVEZAS"]
        mock_resumen_result.registros_procesados = 10
        mock_resumen_result.sucursales = 5
        mock_resumen_result.genericos_incluidos = ["CERVEZAS"]
        (tmp_path / "resumen.xlsx").write_bytes(b"fake")
        mock_resumen_service.generar_reporte.return_value = mock_resumen_result

        with (
            patch("main.VentasService", return_value=mock_ventas_service),
            patch("main.ResumenMensualService", return_value=mock_resumen_service),
        ):
            from main import _run_config_dir
            result = _run_config_dir(tmp_path)

        assert result == 0
        mock_ventas_service.generar_reporte.assert_called_once()
        mock_resumen_service.generar_reporte.assert_called_once()

    def test_filter_merge_global_plus_report(self, tmp_path):
        """Filtros por reporte sobreescriben los globales."""
        _write_contactos(tmp_path)
        config_path = tmp_path / "ventas.json"
        config_path.write_text(json.dumps({
            "tipo": "ventas",
            "filtros": {
                "fecha_desde": "2026-02-01",
                "fecha_hasta": "2026-02-28",
                "genericos": ["CERVEZAS", "AGUAS DANONE"],
                "con_slicers": True,
            },
            "reportes": [
                {
                    "nombre": "Solo Cervezas",
                    "filtros": {
                        "genericos": ["CERVEZAS"],
                        "con_slicers": False,
                    },
                },
            ],
        }))

        mock_service = MagicMock()
        mock_result = MagicMock()
        mock_result.ruta_archivo = tmp_path / "test.xlsx"
        mock_result.hojas = ["Ventas Bultos", "Ventas HTLs"]
        mock_result.registros_ventas = 10
        mock_result.registros_procesados = 5
        mock_result.sucursales = 1
        mock_result.genericos_incluidos = ["CERVEZAS"]
        mock_result.slicers_agregados = False
        mock_result.supervisor = None
        (tmp_path / "test.xlsx").write_bytes(b"fake")
        mock_service.generar_reporte.return_value = mock_result

        with patch("main.VentasService", return_value=mock_service):
            from main import _run_report_config
            _run_report_config(config_path)

        config_used = mock_service.generar_reporte.call_args[0][0]
        assert config_used.genericos == ["CERVEZAS"]  # report override
        assert config_used.con_slicers is False  # report override
        assert config_used.fecha_desde == "2026-02-01"  # global

    def test_multi_supervisor_entry_delivers_to_each_file(self, tmp_path):
        """Un ReportEntry con 2 supervisores genera 2 archivos, delivery corre para ambos."""
        _write_contactos(tmp_path)
        config_path = tmp_path / "ventas.json"
        config_path.write_text(json.dumps({
            "tipo": "ventas",
            "filtros": {
                "fecha_desde": "2026-02-01",
                "fecha_hasta": "2026-02-28",
                "con_slicers": False,
            },
            "reportes": [
                {
                    "nombre": "Ventas Equipo Norte",
                    "filtros": {
                        "supervisores": ["Walter Vilte", "Antonio Cabrerizo"],
                        "sucursales": ["CASA CENTRAL"],
                    },
                    "enviar_a": {
                        "Walter Vilte": {"via": ["email"]},
                    },
                },
            ],
        }))

        mock_service = MagicMock()
        mock_service.generar_reporte_supervisores.return_value = [
            _make_ventas_result(tmp_path, "Walter Vilte"),
            _make_ventas_result(tmp_path, "Antonio Cabrerizo"),
        ]

        mock_email_sender = MagicMock()

        with (
            patch("main.VentasService", return_value=mock_service),
            patch("src.core.email_sender.EmailSender.send", mock_email_sender.send),
        ):
            from main import _run_report_config
            result = _run_report_config(config_path)

        assert result == 0

        # 2 supervisors → 2 files → 2 delivery runs → 2 emails
        assert mock_email_sender.send.call_count == 2

        # Both emails go to walter (he's the only contact in enviar_a)
        for email_call in mock_email_sender.send.call_args_list:
            assert email_call[1]["destinatarios"] == ["walter@empresa.com"]
