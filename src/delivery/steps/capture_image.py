"""
CaptureImageStep - Paso de captura de rango Excel como imagen PNG.
"""
import logging
from pathlib import Path

from src.delivery.pipeline import DeliveryConfig, DeliveryStep, ReportArtifact, StepResult


class CaptureImageStep(DeliveryStep):
    """Captura un rango de la hoja Excel como imagen PNG usando LibreOffice + Pillow."""

    def execute(
        self,
        artifact: ReportArtifact,
        config: DeliveryConfig,
        logger: logging.Logger,
    ) -> StepResult:
        if config.capture_image is None:
            return StepResult(
                status="skipped",
                step_name="CaptureImageStep",
                message="capture_image no configurado",
            )

        from src.core.excel_manager import ExcelManager

        try:
            manager = ExcelManager(artifact.ruta_excel)
            png_path = manager.capture_range(
                sheet_name=config.capture_image.hoja,
                range_addr=config.capture_image.rango,
            )
            artifact.ruta_imagen = png_path
            return StepResult(
                status="success",
                step_name="CaptureImageStep",
                message=f"Imagen generada: {png_path.name}",
                artifact_path=png_path,
            )
        except RuntimeError as exc:
            # LibreOffice no disponible → degradar silenciosamente
            logger.warning("LibreOffice no disponible, omitiendo captura: %s", exc)
            return StepResult(
                status="skipped",
                step_name="CaptureImageStep",
                message=str(exc),
            )
        except ImportError as exc:
            logger.warning("Pillow no disponible, omitiendo captura: %s", exc)
            return StepResult(
                status="skipped",
                step_name="CaptureImageStep",
                message=str(exc),
            )
        except Exception as exc:
            logger.error("Error en CaptureImageStep: %s", exc)
            return StepResult(
                status="error",
                step_name="CaptureImageStep",
                message=str(exc),
            )
