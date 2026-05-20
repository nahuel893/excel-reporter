"""Tests para DeliveryPipeline y modelos relacionados."""
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.delivery.pipeline import (
    CaptureConfig,
    DeliveryConfig,
    DeliveryPipeline,
    DeliveryStep,
    EmailConfig,
    PipelineResult,
    ReportArtifact,
    StepResult,
    WhatsAppConfig,
)


def _make_artifact(tmp_path: Path) -> ReportArtifact:
    xlsx = tmp_path / "reporte.xlsx"
    xlsx.write_bytes(b"fake")
    return ReportArtifact(ruta_excel=xlsx)


def _step(name: str, status: str = "success", raises: Exception | None = None) -> DeliveryStep:
    """Fabrica un step mock con status controlado."""

    class _MockStep(DeliveryStep):
        def execute(self, artifact, config, logger):
            if raises:
                raise raises
            return StepResult(status=status, step_name=name, message="ok")

    return _MockStep()


class TestStepResult:
    def test_fields(self):
        r = StepResult(status="success", step_name="Foo", message="done")
        assert r.status == "success"
        assert r.step_name == "Foo"

    def test_artifact_path_default_none(self):
        r = StepResult(status="skipped", step_name="Bar")
        assert r.artifact_path is None


class TestPipelineResult:
    def test_success_when_all_steps_ok(self):
        result = PipelineResult(steps=[
            StepResult(status="success", step_name="A"),
            StepResult(status="skipped", step_name="B"),
        ])
        assert result.success is True

    def test_not_success_when_any_error(self):
        result = PipelineResult(steps=[
            StepResult(status="success", step_name="A"),
            StepResult(status="error", step_name="B"),
        ])
        assert result.success is False

    def test_empty_steps_is_success(self):
        result = PipelineResult()
        assert result.success is True


class TestDeliveryPipeline:
    def test_runs_steps_in_order(self, tmp_path):
        calls = []

        class TrackedStep(DeliveryStep):
            def __init__(self, name):
                self._name = name

            def execute(self, artifact, config, logger):
                calls.append(self._name)
                return StepResult(status="success", step_name=self._name)

        pipeline = DeliveryPipeline([TrackedStep("A"), TrackedStep("B"), TrackedStep("C")])
        config = DeliveryConfig()
        pipeline.run(_make_artifact(tmp_path), config)

        assert calls == ["A", "B", "C"]

    def test_error_in_one_step_does_not_stop_others(self, tmp_path):
        """Si un step lanza excepcion, los siguientes igual se ejecutan."""
        executed = []

        class FailingStep(DeliveryStep):
            def execute(self, artifact, config, logger):
                raise RuntimeError("boom")

        class TrackingStep(DeliveryStep):
            def execute(self, artifact, config, logger):
                executed.append("ran")
                return StepResult(status="success", step_name="Tracking")

        pipeline = DeliveryPipeline([FailingStep(), TrackingStep()])
        config = DeliveryConfig()
        result = pipeline.run(_make_artifact(tmp_path), config)

        assert len(result.steps) == 2
        assert result.steps[0].status == "error"
        assert result.steps[1].status == "success"
        assert executed == ["ran"]

    def test_pipeline_result_success_false_when_step_errors(self, tmp_path):
        pipeline = DeliveryPipeline([_step("X", status="error")])
        config = DeliveryConfig()
        result = pipeline.run(_make_artifact(tmp_path), config)
        assert result.success is False

    def test_empty_pipeline_returns_empty_result(self, tmp_path):
        pipeline = DeliveryPipeline([])
        config = DeliveryConfig()
        result = pipeline.run(_make_artifact(tmp_path), config)
        assert result.steps == []
        assert result.success is True

    def test_log_steps_false_suppresses_info_logging(self, tmp_path, caplog):
        pipeline = DeliveryPipeline([_step("S", "success")])
        config = DeliveryConfig(log_steps=False)
        with caplog.at_level(logging.INFO, logger="delivery.pipeline"):
            pipeline.run(_make_artifact(tmp_path), config)
        assert "Iniciando paso" not in caplog.text

    def test_log_steps_true_logs_start_and_end(self, tmp_path, caplog):
        pipeline = DeliveryPipeline([_step("TestStep", "success")])
        config = DeliveryConfig(log_steps=True)
        with caplog.at_level(logging.INFO, logger="delivery.pipeline"):
            pipeline.run(_make_artifact(tmp_path), config)
        assert "Iniciando paso" in caplog.text


class TestDeliveryConfig:
    def test_defaults(self):
        cfg = DeliveryConfig()
        assert cfg.capture_image is None
        assert cfg.email is None
        assert cfg.whatsapp is None
        assert cfg.log_steps is True

    def test_full_config(self):
        cfg = DeliveryConfig(
            capture_image=CaptureConfig(hoja="Ventas Bultos", rango="A1:H20"),
            email=EmailConfig(destinatarios=["a@b.com"], asunto="Test"),
            whatsapp=WhatsAppConfig(grupos=["Grupo Ventas"], enviar_como="archivo"),
        )
        assert cfg.capture_image.rango == "A1:H20"
        assert cfg.email.destinatarios == ["a@b.com"]
        assert cfg.whatsapp.enviar_como == "archivo"


class TestEmailConfig:
    def test_adjuntos_default_is_excel(self):
        cfg = EmailConfig(destinatarios=["x@y.com"])
        assert cfg.adjuntos == ["excel"]

    def test_asunto_default_none(self):
        cfg = EmailConfig(destinatarios=["x@y.com"])
        assert cfg.asunto is None

    def test_invalid_adjunto_value_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc_info:
            EmailConfig(destinatarios=["x@y.com"], adjuntos=["pdf"])
        assert "adjuntos" in str(exc_info.value)

    def test_invalid_adjunto_mixed_raises_validation_error(self):
        with pytest.raises(ValidationError):
            EmailConfig(destinatarios=["x@y.com"], adjuntos=["excel", "pdf"])

    def test_empty_adjuntos_raises_validation_error(self):
        with pytest.raises(ValidationError):
            EmailConfig(destinatarios=["x@y.com"], adjuntos=[])


class TestDeliveryConfigModelValidate:
    def test_model_validate_from_dict(self):
        raw = {
            "email": {
                "destinatarios": ["a@b.com"],
                "asunto": "Reporte",
                "adjuntos": ["excel", "imagen"],
            }
        }
        cfg = DeliveryConfig.model_validate(raw)
        assert cfg.email.destinatarios == ["a@b.com"]
        assert cfg.email.adjuntos == ["excel", "imagen"]

    def test_model_validate_invalid_adjunto_raises(self):
        raw = {"email": {"destinatarios": ["a@b.com"], "adjuntos": ["word"]}}
        with pytest.raises(ValidationError):
            DeliveryConfig.model_validate(raw)

    def test_model_validate_absent_delivery_fields_use_defaults(self):
        cfg = DeliveryConfig.model_validate({})
        assert cfg.capture_image is None
        assert cfg.email is None
        assert cfg.whatsapp is None
        assert cfg.log_steps is True


class TestWhatsAppConfig:
    def test_enviar_como_default_imagen(self):
        cfg = WhatsAppConfig(grupos=["Grupo"])
        assert cfg.enviar_como == "imagen"

    def test_accepts_enviar_como_ambos(self):
        cfg = WhatsAppConfig(grupos=["Grupo"], enviar_como="ambos")
        assert cfg.enviar_como == "ambos"

    def test_invalid_enviar_como_raises_validation_error(self):
        with pytest.raises(ValidationError):
            WhatsAppConfig(grupos=["Grupo"], enviar_como="pdf")
