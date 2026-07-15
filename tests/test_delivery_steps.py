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

    def test_soffice_runtime_error_is_per_region_not_skip(self, tmp_path):
        """A RuntimeError from LibreOffice/pdftoppm is a per-render failure, NOT
        a missing dependency. For a single capture it must surface as status
        'error' (the one region failed), never a misleading 'skipped'."""
        config = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Hoja1", rango="A1:B2")
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
            lambda sheet, caption_anchor=None: regions_by_sheet[sheet]
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
            capture_images=[CaptureConfig(hoja="Cober Nueva", rango="auto:bordes")]
        )
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / f"region_{i}.png" for i in range(20)]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.side_effect = png_paths

        mock_recognizer_cls = _mock_recognizer_class({"Cober Nueva": regions})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "success"
        assert mock_renderer.render.call_count == 20
        assert len(artifact.rutas_imagenes) == 20

    def test_avance_sentinel_expands_to_4_captures(self, tmp_path):
        regions = [(f"A{i}:B{i}", f"Card {i}") for i in range(4)]
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")]
        )
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / f"card_{i}.png" for i in range(4)]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.side_effect = png_paths

        mock_recognizer_cls = _mock_recognizer_class({"Avance": regions})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            result = CaptureImageStep().execute(
                artifact, config, logging.getLogger("test")
            )

        assert result.status == "success"
        assert mock_renderer.render.call_count == 4
        assert len(artifact.rutas_imagenes) == 4

    def test_expansion_never_mutates_shared_delivery_config(self, tmp_path):
        regions = [("A1:B2", "Card 1"), ("A3:B4", "Card 2")]
        original_capture = CaptureConfig(hoja="Avance", rango="auto:bordes")
        config = DeliveryConfig(capture_images=[original_capture])
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / "c1.png", tmp_path / "c2.png"]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.side_effect = png_paths

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
            ]
        )
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / "a1.png", tmp_path / "c1.png"]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.side_effect = png_paths

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
            capture_images=[CaptureConfig(hoja="Multicategoria", rango="A1:H20")]
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

    def test_expanded_regions_render_with_crop_true(self, tmp_path):
        regions = [("A1:B2", "Card A"), ("A3:B4", "Card B")]
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")]
        )
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / "a1.png", tmp_path / "a2.png"]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.side_effect = png_paths

        mock_recognizer_cls = _mock_recognizer_class({"Avance": regions})

        with (
            patch("src.core.range_recognizer.RangeRecognizer", mock_recognizer_cls),
            patch("src.core.excel_renderers.get_renderer", return_value=mock_renderer),
        ):
            CaptureImageStep().execute(artifact, config, logging.getLogger("test"))

        assert mock_renderer.render.call_count == 2
        for call in mock_renderer.render.call_args_list:
            assert call.kwargs["crop"] is True

    def test_captions_pushed_to_nombres_hojas_in_reading_order(self, tmp_path):
        regions = [("A1:B2", "Card A"), ("A3:B4", "Card B"), ("A5:B6", None)]
        config = DeliveryConfig(
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")]
        )
        artifact = _make_artifact(tmp_path)

        png_paths = [tmp_path / "a1.png", tmp_path / "a2.png", tmp_path / "a3.png"]
        for p in png_paths:
            p.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.side_effect = png_paths

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
            ]
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
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")]
        )
        artifact = _make_artifact(tmp_path)

        png1 = tmp_path / "r1.png"
        png1.write_bytes(b"png")
        png3 = tmp_path / "r3.png"
        png3.write_bytes(b"png")

        mock_renderer = MagicMock()
        mock_renderer.render.side_effect = [
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
        # All 3 regions were attempted; regions 1 and 3 rendered successfully.
        assert mock_renderer.render.call_count == 3
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
            capture_images=[CaptureConfig(hoja="Avance", rango="auto:bordes")]
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
