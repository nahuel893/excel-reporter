"""Tests aislados para CaptureImageStep, SendEmailStep, SendWhatsAppStep."""
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.delivery.pipeline import (
    CaptureConfig,
    DeliveryConfig,
    EmailConfig,
    ReportArtifact,
    WhatsAppConfig,
)
from src.delivery.steps.capture_image import CaptureImageStep
from src.delivery.steps.send_email import SendEmailStep, _generar_asunto, _generar_cuerpo
from src.delivery.steps.send_whatsapp import SendWhatsAppStep


def _make_artifact(tmp_path: Path) -> ReportArtifact:
    xlsx = tmp_path / "reporte.xlsx"
    xlsx.write_bytes(b"fake")
    return ReportArtifact(ruta_excel=xlsx)


def _make_artifact_with_image(tmp_path: Path) -> ReportArtifact:
    xlsx = tmp_path / "reporte.xlsx"
    xlsx.write_bytes(b"fake")
    png = tmp_path / "reporte.png"
    png.write_bytes(b"fake-png")
    return ReportArtifact(ruta_excel=xlsx, rutas_imagenes=[png])


# ---------------------------------------------------------------------------
# CaptureImageStep
# ---------------------------------------------------------------------------


class TestCaptureImageStepSkip:
    def test_skips_when_capture_not_configured(self, tmp_path):
        config = DeliveryConfig()
        result = CaptureImageStep().execute(
            _make_artifact(tmp_path), config, logging.getLogger("test")
        )
        assert result.status == "skipped"
        assert "no configurado" in result.message

    def test_skips_when_soffice_missing(self, tmp_path):
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Hoja1", rango="A1:B2")
        )
        artifact = _make_artifact(tmp_path)

        mock_mgr = MagicMock()
        mock_mgr.capture_range.side_effect = RuntimeError("LibreOffice no encontrado")

        with patch(
            "src.core.excel_renderers.libreoffice_renderer.ExcelManager", return_value=mock_mgr
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "skipped"
        assert "LibreOffice" in result.message

    def test_skips_when_pillow_missing(self, tmp_path):
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Hoja1", rango="A1:B2")
        )
        artifact = _make_artifact(tmp_path)

        mock_mgr = MagicMock()
        mock_mgr.capture_range.side_effect = ImportError("Pillow es requerido")

        with patch(
            "src.core.excel_renderers.libreoffice_renderer.ExcelManager", return_value=mock_mgr
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "skipped"
        assert "Pillow" in result.message


class TestCaptureImageStepSuccess:
    def test_success_sets_artifact_ruta_imagen(self, tmp_path):
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Ventas", rango="A1:H20")
        )
        artifact = _make_artifact(tmp_path)
        fake_png = tmp_path / "captura.png"
        fake_png.write_bytes(b"png-data")

        mock_mgr = MagicMock()
        mock_mgr.capture_range.return_value = fake_png

        with patch(
            "src.core.excel_renderers.libreoffice_renderer.ExcelManager", return_value=mock_mgr
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "success"
        assert result.artifact_path == fake_png
        assert artifact.ruta_imagen == fake_png


class TestCaptureImageStepError:
    def test_unexpected_error_returns_error_status(self, tmp_path):
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Hoja1", rango="A1:B2")
        )
        artifact = _make_artifact(tmp_path)

        mock_mgr = MagicMock()
        mock_mgr.capture_range.side_effect = ValueError("Hoja no encontrada")

        with patch(
            "src.core.excel_renderers.libreoffice_renderer.ExcelManager", return_value=mock_mgr
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "error"


# ---------------------------------------------------------------------------
# SendEmailStep
# ---------------------------------------------------------------------------


class TestSendEmailStepSkip:
    def test_skips_when_email_not_configured(self, tmp_path):
        config = DeliveryConfig()
        result = SendEmailStep().execute(
            _make_artifact(tmp_path), config, logging.getLogger("test")
        )
        assert result.status == "skipped"
        assert "no configurado" in result.message


class TestSendEmailStepAdjuntos:
    def test_image_adjunto_skipped_when_ruta_imagen_is_none(self, tmp_path, caplog):
        config = DeliveryConfig(
            email=EmailConfig(
                destinatarios=["a@b.com"],
                adjuntos=["excel", "imagen"],
            )
        )
        artifact = _make_artifact(tmp_path)  # no ruta_imagen

        mock_sender = MagicMock()
        with patch(
            "src.core.email_sender.EmailSender", return_value=mock_sender
        ):
            with caplog.at_level(logging.WARNING):
                result = SendEmailStep().execute(
                    artifact, config, logging.getLogger("test")
                )

        assert result.status == "success"
        # Only excel should be attached, not imagen
        call_args = mock_sender.send.call_args
        adjuntos_sent = call_args[1]["adjuntos"] if "adjuntos" in call_args[1] else call_args[0][3]
        assert len(adjuntos_sent) == 1
        assert adjuntos_sent[0] == artifact.ruta_excel

    def test_both_adjuntos_when_image_exists(self, tmp_path):
        config = DeliveryConfig(
            email=EmailConfig(
                destinatarios=["a@b.com"],
                adjuntos=["excel", "imagen"],
            )
        )
        artifact = _make_artifact_with_image(tmp_path)

        mock_sender = MagicMock()
        with patch(
            "src.core.email_sender.EmailSender", return_value=mock_sender
        ):
            result = SendEmailStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "success"
        call_args = mock_sender.send.call_args
        adjuntos_sent = call_args[1]["adjuntos"] if "adjuntos" in call_args[1] else call_args[0][3]
        assert len(adjuntos_sent) == 2


class TestSendEmailStepError:
    def test_smtp_error_returns_error_status(self, tmp_path):
        config = DeliveryConfig(
            email=EmailConfig(destinatarios=["a@b.com"])
        )
        artifact = _make_artifact(tmp_path)

        mock_sender = MagicMock()
        mock_sender.send.side_effect = RuntimeError("SMTP fail")

        with patch(
            "src.core.email_sender.EmailSender", return_value=mock_sender
        ):
            result = SendEmailStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "error"
        assert "SMTP fail" in result.message


class TestSendEmailStepAsunto:
    def test_uses_configured_asunto(self, tmp_path):
        config = DeliveryConfig(
            email=EmailConfig(destinatarios=["a@b.com"], asunto="Custom Subject")
        )
        artifact = _make_artifact(tmp_path)

        mock_sender = MagicMock()
        with patch(
            "src.core.email_sender.EmailSender", return_value=mock_sender
        ):
            SendEmailStep().execute(artifact, config, logging.getLogger("test"))

        call_args = mock_sender.send.call_args
        asunto_sent = call_args[1]["asunto"] if "asunto" in call_args[1] else call_args[0][1]
        assert asunto_sent == "Custom Subject"

    def test_auto_generates_asunto_from_metadata(self, tmp_path):
        config = DeliveryConfig(
            email=EmailConfig(destinatarios=["a@b.com"])
        )
        artifact = _make_artifact(tmp_path)
        artifact.metadata = {"nombre": "Ventas", "fecha": "2026-04-01"}

        mock_sender = MagicMock()
        with patch(
            "src.core.email_sender.EmailSender", return_value=mock_sender
        ):
            SendEmailStep().execute(artifact, config, logging.getLogger("test"))

        call_args = mock_sender.send.call_args
        asunto_sent = call_args[1]["asunto"] if "asunto" in call_args[1] else call_args[0][1]
        assert "Ventas" in asunto_sent
        assert "2026-04-01" in asunto_sent


class TestGenerarAsunto:
    def test_with_nombre_and_fecha(self):
        artifact = ReportArtifact(
            ruta_excel=Path("/tmp/test.xlsx"),
            metadata={"nombre": "Ventas", "fecha": "2026-01-31"},
        )
        assert _generar_asunto(artifact) == "Reporte Ventas - 2026-01-31"

    def test_without_metadata_uses_stem(self):
        artifact = ReportArtifact(ruta_excel=Path("/tmp/mi_reporte.xlsx"))
        assert "mi_reporte" in _generar_asunto(artifact)


class TestGenerarCuerpo:
    def test_includes_nombre(self):
        artifact = ReportArtifact(
            ruta_excel=Path("/tmp/test.xlsx"),
            metadata={"nombre": "Resumen"},
        )
        cuerpo = _generar_cuerpo(artifact)
        assert "Resumen" in cuerpo
        assert "automaticamente" in cuerpo


# ---------------------------------------------------------------------------
# SendWhatsAppStep
# ---------------------------------------------------------------------------


class TestSendWhatsAppStepSkip:
    def test_skips_when_whatsapp_not_configured(self, tmp_path):
        config = DeliveryConfig()
        result = SendWhatsAppStep().execute(
            _make_artifact(tmp_path), config, logging.getLogger("test")
        )
        assert result.status == "skipped"
        assert "no configurado" in result.message


class TestSendWhatsAppStepSendModes:
    def test_sends_image_when_configured(self, tmp_path):
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["Grupo Ventas"], enviar_como="imagen")
        )
        artifact = _make_artifact_with_image(tmp_path)

        mock_client = MagicMock()
        with (
            patch("src.core.whatsapp_client.WhatsAppClient", return_value=mock_client),
            patch("config.settings.WHATSAPP_SERVICE_URL", "http://localhost:3000"),
        ):
            result = SendWhatsAppStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "success"
        mock_client.send_image.assert_called_once()

    def test_sends_file_when_configured(self, tmp_path):
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["Grupo"], enviar_como="archivo")
        )
        artifact = _make_artifact(tmp_path)

        mock_client = MagicMock()
        with (
            patch("src.core.whatsapp_client.WhatsAppClient", return_value=mock_client),
            patch("config.settings.WHATSAPP_SERVICE_URL", "http://localhost:3000"),
        ):
            result = SendWhatsAppStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "success"
        mock_client.send_file.assert_called_once()

    def test_skips_when_imagen_mode_and_no_image(self, tmp_path):
        """enviar_como='imagen' sin imagen -> omite, no envia nada."""
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["Grupo"], enviar_como="imagen")
        )
        artifact = _make_artifact(tmp_path)  # no ruta_imagen

        mock_client = MagicMock()
        with (
            patch("src.core.whatsapp_client.WhatsAppClient", return_value=mock_client),
            patch("config.settings.WHATSAPP_SERVICE_URL", "http://localhost:3000"),
        ):
            result = SendWhatsAppStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "success"
        mock_client.send_file.assert_not_called()
        mock_client.send_image.assert_not_called()

    def test_sends_file_when_archivo_mode(self, tmp_path):
        """enviar_como='archivo' siempre envia el archivo, sin importar si hay imagen."""
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["Grupo"], enviar_como="archivo")
        )
        artifact = _make_artifact(tmp_path)  # xlsx, no ruta_imagen

        mock_client = MagicMock()
        with (
            patch("src.core.whatsapp_client.WhatsAppClient", return_value=mock_client),
            patch("config.settings.WHATSAPP_SERVICE_URL", "http://localhost:3000"),
        ):
            result = SendWhatsAppStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "success"
        mock_client.send_file.assert_called_once()
        mock_client.send_image.assert_not_called()


class TestSendWhatsAppStepErrors:
    def test_connection_error_per_group(self, tmp_path):
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["OK", "Fail"])
        )
        artifact = _make_artifact_with_image(tmp_path)

        mock_client = MagicMock()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ConnectionError("refused")

        mock_client.send_image.side_effect = side_effect

        with (
            patch("src.core.whatsapp_client.WhatsAppClient", return_value=mock_client),
            patch("config.settings.WHATSAPP_SERVICE_URL", "http://localhost:3000"),
        ):
            result = SendWhatsAppStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "error"
        assert "1 grupo(s)" in result.message

    def test_catches_non_connection_errors(self, tmp_path):
        """Verifica que Exception generico tambien se captura (no solo ConnectionError)."""
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["Grupo"])
        )
        artifact = _make_artifact_with_image(tmp_path)

        mock_client = MagicMock()
        mock_client.send_image.side_effect = ValueError("unexpected json")

        with (
            patch("src.core.whatsapp_client.WhatsAppClient", return_value=mock_client),
            patch("config.settings.WHATSAPP_SERVICE_URL", "http://localhost:3000"),
        ):
            result = SendWhatsAppStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "error"
        assert "unexpected json" in result.message

    def test_all_groups_fail_reports_all(self, tmp_path):
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["G1", "G2", "G3"])
        )
        artifact = _make_artifact_with_image(tmp_path)

        mock_client = MagicMock()
        mock_client.send_image.side_effect = ConnectionError("down")

        with (
            patch("src.core.whatsapp_client.WhatsAppClient", return_value=mock_client),
            patch("config.settings.WHATSAPP_SERVICE_URL", "http://localhost:3000"),
        ):
            result = SendWhatsAppStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "error"
        assert "3 grupo(s)" in result.message


# ---------------------------------------------------------------------------
# CaptureImageStep — output_dir sibling of xlsx
# ---------------------------------------------------------------------------


class TestCaptureImageStepOutputDir:
    def test_captures_written_next_to_xlsx(self, tmp_path):
        """output_dir passed to renderer must equal artifact.ruta_excel.parent."""
        xlsx = tmp_path / "sub" / "reporte.xlsx"
        xlsx.parent.mkdir(parents=True)
        xlsx.write_bytes(b"fake")
        artifact = ReportArtifact(ruta_excel=xlsx)

        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Ventas", rango="A1:H20")
        )

        fake_png = xlsx.parent / "captura.png"
        fake_png.write_bytes(b"png-data")

        mock_renderer = MagicMock()
        mock_renderer.render.return_value = fake_png

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        call_kwargs = mock_renderer.render.call_args
        received_output_dir = call_kwargs.kwargs.get(
            "output_dir",
            call_kwargs.args[3] if len(call_kwargs.args) > 3 else None,
        )
        assert received_output_dir == xlsx.parent
