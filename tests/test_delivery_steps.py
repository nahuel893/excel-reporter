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


def _consuming_whatsapp() -> WhatsAppConfig:
    """A WhatsAppConfig that satisfies CaptureImageStep's images-consumed
    gate (enviar_como='imagen'), for tests that exercise the render/expand
    path and are not themselves testing the gate."""
    return WhatsAppConfig(grupos=["Grupo Test"], enviar_como="imagen")


# ---------------------------------------------------------------------------
# CaptureConfig — caption / caption_anchor fields
# ---------------------------------------------------------------------------


class TestCaptureConfigCaption:
    def test_accepts_optional_caption(self):
        cfg = CaptureConfig(hoja="Avance", rango="A1:AR18", caption="GFLORES")
        assert cfg.caption == "GFLORES"

    def test_caption_defaults_to_none(self):
        cfg = CaptureConfig(hoja="Avance", rango="A1:AR18")
        assert cfg.caption is None

    def test_accepts_optional_caption_anchor(self):
        cfg = CaptureConfig(hoja="Cober Nueva", rango="auto:bordes", caption_anchor="B2")
        assert cfg.caption_anchor == "B2"

    def test_caption_anchor_defaults_to_none(self):
        cfg = CaptureConfig(hoja="Cober Nueva", rango="auto:bordes")
        assert cfg.caption_anchor is None

    def test_accepts_optional_caption_header(self):
        cfg = CaptureConfig(hoja="Avance", rango="auto:bordes", caption_header="Super")
        assert cfg.caption_header == "Super"

    def test_caption_header_defaults_to_none(self):
        cfg = CaptureConfig(hoja="Avance", rango="auto:bordes")
        assert cfg.caption_header is None

    def test_accepts_recortar_true(self):
        cfg = CaptureConfig(hoja="Cober Nueva", rango="A49:R55", recortar=True)
        assert cfg.recortar is True

    def test_recortar_defaults_to_false(self):
        cfg = CaptureConfig(hoja="Cober Nueva", rango="A49:R55")
        assert cfg.recortar is False


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

    def test_skips_when_pillow_missing(self, tmp_path):
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Hoja1", rango="A1:B2"),
            whatsapp=_consuming_whatsapp(),
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
            capture_image=CaptureConfig(hoja="Ventas", rango="A1:H20"),
            whatsapp=_consuming_whatsapp(),
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
            capture_image=CaptureConfig(hoja="Hoja1", rango="A1:B2"),
            whatsapp=_consuming_whatsapp(),
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

    def test_soffice_runtime_error_is_per_region_not_skip(self, tmp_path):
        """A RuntimeError from LibreOffice/pdftoppm is a per-render failure, NOT
        a missing dependency. For a single capture it must surface as status
        'error' (the one region failed), never a misleading 'skipped'."""
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Hoja1", rango="A1:B2"),
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        mock_mgr = MagicMock()
        mock_mgr.capture_range.side_effect = RuntimeError("soffice exit 1")

        with patch(
            "src.core.excel_renderers.libreoffice_renderer.ExcelManager", return_value=mock_mgr
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "error"
        assert "soffice exit 1" in result.message


# ---------------------------------------------------------------------------
# CaptureImageStep — images-consumed gate
#
# Rationale: rendering (auto:bordes expansion + RangeRecognizer workbook
# load + LibreOffice renders) is expensive (~110min for 25 captures). If no
# downstream channel will actually consume the images (WhatsApp off/archivo,
# email without an 'imagen' attachment), the whole render path is a wasted
# cost that must be skipped BEFORE _expand_auto_bordes runs.
# ---------------------------------------------------------------------------


class TestImagesConsumedGate:
    def test_images_consumed_true_when_whatsapp_enviar_como_imagen(self):
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["G"], enviar_como="imagen"),
        )
        assert CaptureImageStep._images_consumed(config) is True

    def test_images_consumed_true_when_whatsapp_enviar_como_ambos(self):
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["G"], enviar_como="ambos"),
        )
        assert CaptureImageStep._images_consumed(config) is True

    def test_images_consumed_false_when_whatsapp_enviar_como_archivo(self):
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["G"], enviar_como="archivo"),
        )
        assert CaptureImageStep._images_consumed(config) is False

    def test_images_consumed_true_when_email_adjuntos_has_imagen(self):
        config = DeliveryConfig(
            email=EmailConfig(destinatarios=["a@b.com"], adjuntos=["excel", "imagen"]),
        )
        assert CaptureImageStep._images_consumed(config) is True

    def test_images_consumed_false_when_email_adjuntos_excel_only(self):
        config = DeliveryConfig(
            email=EmailConfig(destinatarios=["a@b.com"], adjuntos=["excel"]),
        )
        assert CaptureImageStep._images_consumed(config) is False

    def test_images_consumed_false_when_no_whatsapp_and_no_email(self):
        config = DeliveryConfig()
        assert CaptureImageStep._images_consumed(config) is False

    def test_images_consumed_false_when_whatsapp_archivo_and_email_excel_only(self):
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["G"], enviar_como="archivo"),
            email=EmailConfig(destinatarios=["a@b.com"], adjuntos=["excel"]),
        )
        assert CaptureImageStep._images_consumed(config) is False

    def test_images_consumed_true_when_either_channel_alone_satisfies_it(self):
        """Whatsapp archivo-only does NOT consume images, but email WITH
        imagen still does — the rule is an OR across channels."""
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["G"], enviar_como="archivo"),
            email=EmailConfig(destinatarios=["a@b.com"], adjuntos=["imagen"]),
        )
        assert CaptureImageStep._images_consumed(config) is True


class TestCaptureImageStepConsumedGateShortCircuit:
    def test_not_consumed_returns_skipped_without_rendering(self, tmp_path):
        """No whatsapp, email excel-only -> skipped, renderer never invoked."""
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Ventas", rango="A1:H20"),
            email=EmailConfig(destinatarios=["a@b.com"], adjuntos=["excel"]),
        )
        artifact = _make_artifact(tmp_path)

        mock_renderer = MagicMock()
        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "skipped"
        assert "imagenes" in result.message.lower()
        mock_renderer.render.assert_not_called()

    def test_not_consumed_never_invokes_range_recognizer_for_auto_bordes(self, tmp_path):
        """The expensive path (auto:bordes -> RangeRecognizer workbook load)
        must be short-circuited entirely — RangeRecognizer is never even
        instantiated when nothing will consume the images."""
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")],
            # whatsapp is None (default), email is None (default) -> not consumed
        )
        artifact = _make_artifact(tmp_path)

        mock_recognizer_cls = _mock_recognizer_class({"Avance": [("A1:B2", "Card A")]})
        mock_renderer = MagicMock()

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "skipped"
        mock_recognizer_cls.assert_not_called()
        mock_renderer.render.assert_not_called()
        assert artifact.rutas_imagenes == []

    def test_whatsapp_archivo_and_email_excel_only_returns_skipped(self, tmp_path):
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Ventas", rango="A1:H20"),
            whatsapp=WhatsAppConfig(grupos=["G"], enviar_como="archivo"),
            email=EmailConfig(destinatarios=["a@b.com"], adjuntos=["excel"]),
        )
        artifact = _make_artifact(tmp_path)

        mock_renderer = MagicMock()
        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "skipped"
        mock_renderer.render.assert_not_called()

    def test_consumed_via_whatsapp_imagen_still_renders(self, tmp_path):
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Ventas", rango="A1:H20"),
            whatsapp=WhatsAppConfig(grupos=["G"], enviar_como="imagen"),
        )
        artifact = _make_artifact(tmp_path)
        fake_png = tmp_path / "captura.png"
        fake_png.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.return_value = fake_png
        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "success"
        mock_renderer.render.assert_called_once()

    def test_consumed_via_whatsapp_ambos_still_renders(self, tmp_path):
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Ventas", rango="A1:H20"),
            whatsapp=WhatsAppConfig(grupos=["G"], enviar_como="ambos"),
        )
        artifact = _make_artifact(tmp_path)
        fake_png = tmp_path / "captura.png"
        fake_png.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.return_value = fake_png
        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "success"
        mock_renderer.render.assert_called_once()

    def test_consumed_via_email_adjuntos_imagen_still_renders(self, tmp_path):
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Ventas", rango="A1:H20"),
            email=EmailConfig(destinatarios=["a@b.com"], adjuntos=["excel", "imagen"]),
        )
        artifact = _make_artifact(tmp_path)
        fake_png = tmp_path / "captura.png"
        fake_png.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.return_value = fake_png
        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "success"
        mock_renderer.render.assert_called_once()


class TestImagesConsumedGateRegressionGuard:
    """Regression guard: the gate must NOT silently disable a capture that a
    live production config consumes today. avance-branca and avance-guemes
    both run with enviar_whatsapp=true (daily_overrides.json: enviar=true)
    and neither sets whatsapp_enviar_como, which defaults to 'imagen'
    (GlobalFilters.whatsapp_enviar_como) — so both resolve to a WhatsApp
    channel that DOES consume images. Pinned here via the real resolver so
    a future default change would break this test loudly instead of
    silently turning off a live capture."""

    def test_branca_resolved_delivery_keeps_capture_on(self):
        from src.config.resolver import load_contacts, load_report_config, merge_filters, resolve_delivery

        report_config = load_report_config(Path("configs/avances_branca.json"))
        contactos = load_contacts(Path("configs/contactos.json"))
        report = report_config.reportes[0]
        merged = merge_filters(report_config.filtros, report.filtros)

        delivery = resolve_delivery(
            report,
            contactos,
            enviar_email=merged["enviar_email"],
            enviar_whatsapp=merged["enviar_whatsapp"],
            whatsapp_enviar_como=merged["whatsapp_enviar_como"],
            email_adjuntos=merged["email_adjuntos"],
        )

        assert delivery is not None
        assert delivery.whatsapp is not None
        assert delivery.whatsapp.enviar_como == "imagen"
        assert CaptureImageStep._images_consumed(delivery) is True

    def test_guemes_resolved_delivery_keeps_capture_on(self):
        from src.config.resolver import load_contacts, load_report_config, merge_filters, resolve_delivery

        report_config = load_report_config(Path("configs/avances_guemes.json"))
        contactos = load_contacts(Path("configs/contactos.json"))
        report = report_config.reportes[0]
        merged = merge_filters(report_config.filtros, report.filtros)

        delivery = resolve_delivery(
            report,
            contactos,
            enviar_email=merged["enviar_email"],
            enviar_whatsapp=merged["enviar_whatsapp"],
            whatsapp_enviar_como=merged["whatsapp_enviar_como"],
            email_adjuntos=merged["email_adjuntos"],
        )

        assert delivery is not None
        assert delivery.whatsapp is not None
        assert delivery.whatsapp.enviar_como == "imagen"
        assert CaptureImageStep._images_consumed(delivery) is True

    def test_badie_current_config_is_correctly_not_consumed(self):
        """avance-badie has enviar_whatsapp=false today (PR4 images not yet
        verified) -> the gate SHOULD skip it. This is the exact scenario
        motivating the gate, pinned as a regression guard in the other
        direction."""
        from src.config.resolver import load_contacts, load_report_config, merge_filters, resolve_delivery

        report_config = load_report_config(Path("configs/avances_badie.json"))
        contactos = load_contacts(Path("configs/contactos.json"))
        report = report_config.reportes[0]
        merged = merge_filters(report_config.filtros, report.filtros)

        delivery = resolve_delivery(
            report,
            contactos,
            enviar_email=merged["enviar_email"],
            enviar_whatsapp=merged["enviar_whatsapp"],
            whatsapp_enviar_como=merged["whatsapp_enviar_como"],
            email_adjuntos=merged["email_adjuntos"],
        )

        assert delivery is not None
        assert delivery.whatsapp is None  # enviar_whatsapp=false -> no whatsapp targets resolved
        assert CaptureImageStep._images_consumed(delivery) is False


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

    def test_sends_images_and_file_when_ambos_mode(self, tmp_path):
        config = DeliveryConfig(
            whatsapp=WhatsAppConfig(grupos=["Grupo"], enviar_como="ambos")
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
        mock_client.send_file.assert_called_once()


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
            capture_image=CaptureConfig(hoja="Ventas", rango="A1:H20"),
            whatsapp=_consuming_whatsapp(),
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


# ---------------------------------------------------------------------------
# CaptureImageStep — "auto:bordes" sentinel expansion
# ---------------------------------------------------------------------------


def _mock_recognizer_class(regions_by_sheet: dict[str, list[tuple[str, str | None]]]):
    """Builds a mock RangeRecognizer CLASS whose instances answer
    detect_ranges_with_captions() per-sheet from regions_by_sheet, and
    records how many times the class was INSTANTIATED (constructor calls)."""
    instances = []

    def _factory(xlsx_path):
        instance = MagicMock()
        instance.detect_ranges_with_captions.side_effect = (
            lambda sheet, caption_anchor=None, caption_header=None: regions_by_sheet[sheet]
        )
        instances.append(instance)
        return instance

    mock_cls = MagicMock(side_effect=_factory)
    mock_cls._instances = instances  # test introspection helper
    return mock_cls


class TestCaptureImageStepAutoBordesExpansion:
    def test_cober_nueva_sentinel_expands_to_20_captures_all_rendered(self, tmp_path):
        regions = [(f"R{i}C1:R{i}C2", f"Caption {i}") for i in range(20)]
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Cober Nueva", rango="auto:bordes")],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / f"region_{i}.png" for i in range(20)]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = png_paths

        mock_recognizer_cls = _mock_recognizer_class({"Cober Nueva": regions})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "success"
        # 20 expanded auto:bordes regions, all libreoffice -> ONE render_many
        # call (PR5 batch path), never the per-item render() loop.
        mock_renderer.render_many.assert_called_once()
        mock_renderer.render.assert_not_called()
        assert len(artifact.rutas_imagenes) == 20

    def test_avance_sentinel_expands_to_4_captures(self, tmp_path):
        regions = [(f"A{i}:B{i}", f"Card {i}") for i in range(4)]
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / f"card_{i}.png" for i in range(4)]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = png_paths

        mock_recognizer_cls = _mock_recognizer_class({"Avance": regions})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "success"
        mock_renderer.render_many.assert_called_once()
        mock_renderer.render.assert_not_called()
        assert len(artifact.rutas_imagenes) == 4

    def test_expansion_never_mutates_shared_delivery_config(self, tmp_path):
        regions = [("A1:B2", "Card 1"), ("A3:B4", "Card 2")]
        original_capture = CaptureConfig(hoja="Avance", rango="auto:bordes")
        config = DeliveryConfig(capture_images=[original_capture], whatsapp=_consuming_whatsapp())
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / "c1.png", tmp_path / "c2.png"]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = png_paths

        mock_recognizer_cls = _mock_recognizer_class({"Avance": regions})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        # The original capture entry and the shared config must be untouched.
        assert len(config.capture_images) == 1
        assert config.capture_images[0].rango == "auto:bordes"
        assert config.capture_images[0] is original_capture
        assert original_capture.rango == "auto:bordes"
        assert original_capture.caption is None

    def test_single_recognizer_instance_reused_across_multiple_auto_bordes_entries(self, tmp_path):
        """Two auto:bordes entries (different sheets) in the same run must
        share ONE RangeRecognizer instance (the workbook load is expensive)."""
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Avance", rango="auto:bordes"),
                CaptureConfig(hoja="Cober Nueva", rango="auto:bordes"),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / "a1.png", tmp_path / "c1.png"]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = png_paths

        mock_recognizer_cls = _mock_recognizer_class({
            "Avance": [("A1:B2", "Card A")],
            "Cober Nueva": [("A1:B2", "Card C")],
        })

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert mock_recognizer_cls.call_count == 1, (
            "RangeRecognizer must be instantiated exactly once per report run, "
            "reused across every auto:bordes entry"
        )

    def test_non_sentinel_capture_renders_with_crop_false(self, tmp_path):
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Multicategoria", rango="A1:H20")],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        fake_png = tmp_path / "fixed.png"
        fake_png.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.return_value = fake_png

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        mock_renderer.render.assert_called_once()
        assert mock_renderer.render.call_args.kwargs["crop"] is False

    def test_non_sentinel_capture_with_recortar_true_renders_with_crop_true(self, tmp_path):
        """RF: the `recortar` flag on a fixed-range (non-sentinel) capture
        opts that one range into cropped rendering, without affecting the
        auto:bordes default (always cropped) or other fixed ranges."""
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Cober Nueva", rango="A49:R55", recortar=True),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        fake_png = tmp_path / "fixed_recortado.png"
        fake_png.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.return_value = fake_png

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        mock_renderer.render.assert_called_once()
        assert mock_renderer.render.call_args.kwargs["crop"] is True

    def test_mixed_recortar_and_non_recortar_fixed_ranges_render_independently(self, tmp_path):
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Multicategoria", rango="A1:V57", recortar=True),
                CaptureConfig(hoja="AVANCE", rango="B2:AX35"),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        png_cropped = tmp_path / "cropped.png"
        png_whole = tmp_path / "whole.png"
        png_cropped.write_bytes(b"png")
        png_whole.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = [png_cropped, png_whole]

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        mock_renderer.render_many.assert_called_once()
        specs = mock_renderer.render_many.call_args.kwargs["specs"]
        crops = [crop for (_hoja, _rango, crop) in specs]
        assert crops == [True, False]

    def test_expanded_regions_render_with_crop_true(self, tmp_path):
        regions = [("A1:B2", "Card A"), ("A3:B4", "Card B")]
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / "a1.png", tmp_path / "a2.png"]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = png_paths

        mock_recognizer_cls = _mock_recognizer_class({"Avance": regions})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        mock_renderer.render_many.assert_called_once()
        specs = mock_renderer.render_many.call_args.kwargs["specs"]
        assert len(specs) == 2
        for (_hoja, _rango, crop) in specs:
            assert crop is True

    def test_caption_header_forwarded_to_recognizer(self, tmp_path):
        """The `caption_header` field on an auto:bordes CaptureConfig must be
        forwarded to RangeRecognizer.detect_ranges_with_captions()."""
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Avance", rango="auto:bordes", caption_header="Super"),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        fake_png = tmp_path / "a1.png"
        fake_png.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.return_value = fake_png

        mock_recognizer_cls = _mock_recognizer_class({"Avance": [("A1:B2", "GFLORES")]})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        instance = mock_recognizer_cls._instances[0]
        instance.detect_ranges_with_captions.assert_called_once_with(
            "Avance", caption_anchor=None, caption_header="Super",
        )

    def test_recortar_on_sentinel_capture_does_not_change_always_crop_true(self, tmp_path):
        """Sentinel (auto:bordes) entries always crop=True regardless of the
        `recortar` field's value — recortar only matters for fixed ranges."""
        regions = [("A1:B2", "Card A")]
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Avance", rango="auto:bordes", recortar=True),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        fake_png = tmp_path / "a1.png"
        fake_png.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.return_value = fake_png

        mock_recognizer_cls = _mock_recognizer_class({"Avance": regions})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert mock_renderer.render.call_args.kwargs["crop"] is True

    def test_captions_pushed_to_nombres_hojas_in_reading_order(self, tmp_path):
        regions = [("A1:B2", "Card A"), ("A3:B4", "Card B"), ("A5:B6", None)]
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / "a1.png", tmp_path / "a2.png", tmp_path / "a3.png"]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = png_paths

        mock_recognizer_cls = _mock_recognizer_class({"Avance": regions})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        # First two regions carry an explicit caption; the third region has
        # NO caption -> falls back to the sheet name ("Avance").
        assert artifact.nombres_hojas == ["Card A", "Card B", "Avance"]

    def test_auto_bordes_with_html_playwright_renderer_errors_no_render_attempted(self, tmp_path):
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Avance", rango="auto:bordes", renderer="html_playwright")
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        mock_renderer = MagicMock()
        mock_recognizer_cls = _mock_recognizer_class({"Avance": [("A1:B2", "Card A")]})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "error"
        assert "html_playwright" in result.message
        mock_renderer.render.assert_not_called()
        mock_recognizer_cls.assert_not_called()
        assert artifact.rutas_imagenes == []

    def test_runtime_error_on_one_region_is_isolated_others_still_render(self, tmp_path):
        """auto:bordes expands to 3 regions; region 2's render raises a
        RuntimeError (as ExcelManager does on a non-zero soffice/pdftoppm exit).
        Regions 1 and 3 must STILL render, the overall status is 'partial', and
        the failed region 2 is named in the message (by its A1 range) — one bad
        region no longer aborts the other 19."""
        regions = [("A1:B2", "Card 1"), ("A3:B4", "Card 2"), ("A5:B6", "Card 3")]
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        png1 = tmp_path / "r1.png"
        png1.write_bytes(b"png")
        png3 = tmp_path / "r3.png"
        png3.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = [
            png1,
            RuntimeError("soffice exit 1 on region 2"),
            png3,
        ]

        mock_recognizer_cls = _mock_recognizer_class({"Avance": regions})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "partial"
        # All 3 regions were attempted (ONE render_many batch call); regions
        # 1 and 3 rendered successfully.
        mock_renderer.render_many.assert_called_once()
        assert artifact.rutas_imagenes == [png1, png3]
        # Region 2 is identified in the failure message by its A1 range.
        assert "A3:B4" in result.message
        assert "soffice exit 1 on region 2" in result.message

    def test_auto_bordes_zero_regions_reports_sheet_not_no_configurado(self, tmp_path):
        """auto:bordes detecting ZERO regions (e.g. the template lost its
        border styling) with nothing else captured must NOT report the
        misleading 'no configurado' — it names the sheet so an operator can
        investigate."""
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        mock_renderer = MagicMock()
        mock_recognizer_cls = _mock_recognizer_class({"Avance": []})  # zero regions

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "error"
        assert "Avance" in result.message
        assert "no configurado" not in result.message
        mock_renderer.render.assert_not_called()
        assert artifact.rutas_imagenes == []


# ---------------------------------------------------------------------------
# CaptureImageStep — batch routing via render_many (PR5 render optimization)
#
# When the fully-expanded capture list has 2+ entries, ALL using renderer
# 'libreoffice', AND that renderer exposes render_many, CaptureImageStep
# calls render_many ONCE instead of looping per-item render() calls — this
# is what makes the recalc-once optimization reach production (branca 2
# captures, guemes 2 captures, badie 25 captures all qualify). A SINGLE
# libreoffice capture deliberately stays on the per-item path (batching one
# item has no recalc-amortization benefit). Mixed renderer types, or a
# 'libreoffice' renderer without render_many, fall back to the ORIGINAL
# per-item loop unchanged.
# ---------------------------------------------------------------------------


class TestCaptureImageStepBatchRouting:
    def test_all_libreoffice_multi_item_uses_render_many_once(self, tmp_path):
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Multicategoria", rango="A1:H20"),
                CaptureConfig(hoja="Avance", rango="B2:AX35"),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        png1 = tmp_path / "p1.png"
        png2 = tmp_path / "p2.png"
        png1.write_bytes(b"png")
        png2.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = [png1, png2]

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "success"
        mock_renderer.render_many.assert_called_once()
        mock_renderer.render.assert_not_called()
        assert artifact.rutas_imagenes == [png1, png2]

    def test_render_many_called_with_hoja_rango_crop_spec_tuples(self, tmp_path):
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Multicategoria", rango="A1:H20", recortar=True),
                CaptureConfig(hoja="Avance", rango="B2:AX35"),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        png1 = tmp_path / "p1.png"
        png2 = tmp_path / "p2.png"
        png1.write_bytes(b"png")
        png2.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = [png1, png2]

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        mock_renderer.render_many.assert_called_once()
        call_kwargs = mock_renderer.render_many.call_args.kwargs
        assert call_kwargs["specs"] == [
            ("Multicategoria", "A1:H20", True),
            ("Avance", "B2:AX35", False),
        ]
        assert call_kwargs["xlsx_path"] == artifact.ruta_excel
        assert call_kwargs["output_dir"] == artifact.ruta_excel.parent

    def test_mixed_renderer_types_falls_back_to_per_item_loop(self, tmp_path):
        """When NOT all entries are 'libreoffice' (e.g. one is
        html_playwright), the whole step falls back to the ORIGINAL
        per-item render() loop — render_many is never invoked, even for
        the libreoffice entries."""
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Multicategoria", rango="A1:H20", renderer="libreoffice"),
                CaptureConfig(hoja="Otros", rango="A1:H20", renderer="html_playwright"),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        png_lo = tmp_path / "lo.png"
        png_hp = tmp_path / "hp.png"
        png_lo.write_bytes(b"png")
        png_hp.write_bytes(b"png")

        mock_lo = MagicMock()
        mock_lo.render.return_value = png_lo
        mock_hp = MagicMock()
        mock_hp.render.return_value = png_hp

        def _get_renderer(name):
            return {"libreoffice": mock_lo, "html_playwright": mock_hp}[name]

        with patch("src.core.excel_renderers.get_renderer", side_effect=_get_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "success"
        mock_lo.render_many.assert_not_called()
        mock_lo.render.assert_called_once()
        mock_hp.render.assert_called_once()

    def test_render_many_absent_falls_back_to_per_item_loop(self, tmp_path):
        """If the resolved 'libreoffice' renderer doesn't expose
        render_many, fall back to the per-item loop even when all entries
        are libreoffice and there are multiple."""
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Multicategoria", rango="A1:H20"),
                CaptureConfig(hoja="Avance", rango="B2:AX35"),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        png1 = tmp_path / "p1.png"
        png2 = tmp_path / "p2.png"
        png1.write_bytes(b"png")
        png2.write_bytes(b"png")

        mock_renderer = MagicMock(spec=["render", "name"])  # no render_many
        mock_renderer.render.side_effect = [png1, png2]

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "success"
        assert mock_renderer.render.call_count == 2

    def test_single_libreoffice_item_uses_per_item_path_not_render_many(self, tmp_path):
        """A SINGLE all-libreoffice capture deliberately stays on the
        per-item render() path — batching one item has no recalc-
        amortization benefit."""
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Ventas", rango="A1:H20"),
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        fake_png = tmp_path / "captura.png"
        fake_png.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.return_value = fake_png

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "success"
        mock_renderer.render.assert_called_once()
        mock_renderer.render_many.assert_not_called()

    def test_render_many_import_error_returns_skipped(self, tmp_path):
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Multicategoria", rango="A1:H20"),
                CaptureConfig(hoja="Avance", rango="B2:AX35"),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        mock_renderer = MagicMock()
        mock_renderer.render_many.side_effect = ImportError("Pillow es requerido")

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "skipped"
        assert "Pillow" in result.message
        mock_renderer.render.assert_not_called()

    def test_render_many_general_exception_marks_all_specs_as_errors(self, tmp_path):
        """A batch-wide failure (e.g. the shared recalc itself fails) must
        still report status='error' naming every spec, matching what would
        happen if each spec's own recalc failed individually in the old
        per-item path."""
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Multicategoria", rango="A1:H20"),
                CaptureConfig(hoja="Avance", rango="B2:AX35"),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)

        mock_renderer = MagicMock()
        mock_renderer.render_many.side_effect = RuntimeError("LibreOffice fallo al recalcular")

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "error"
        assert "Todas las capturas fallaron" in result.message
        assert "Multicategoria" in result.message
        assert "Avance" in result.message
        assert "LibreOffice fallo al recalcular" in result.message

    def test_render_many_partial_failure_returns_partial_status(self, tmp_path):
        config = DeliveryConfig(
            capture_images=[
                CaptureConfig(hoja="Multicategoria", rango="A1:H20"),
                CaptureConfig(hoja="Avance", rango="B2:AX35"),
                CaptureConfig(hoja="Otros", rango="A1:B2"),
            ],
            whatsapp=_consuming_whatsapp(),
        )
        artifact = _make_artifact(tmp_path)
        png1 = tmp_path / "p1.png"
        png3 = tmp_path / "p3.png"
        png1.write_bytes(b"png")
        png3.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render_many.return_value = [
            png1,
            RuntimeError("LibreOffice fallo al exportar PDF"),
            png3,
        ]

        with patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer):
            result = CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert result.status == "partial"
        assert artifact.rutas_imagenes == [png1, png3]
        assert "Avance" in result.message
        assert "LibreOffice fallo al exportar PDF" in result.message
