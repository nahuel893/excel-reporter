"""
CaptureImageStep - Paso de captura de rango Excel como imagen PNG.
"""
import logging
from pathlib import Path

from src.delivery.pipeline import DeliveryConfig, DeliveryStep, ReportArtifact, StepResult


class CaptureImageStep(DeliveryStep):
    """Captura N rangos de hojas Excel como imagenes PNG (LibreOffice + Pillow).

    Cada captura es aislada: si una falla, las otras se intentan igual.
    Poblar artifact.rutas_imagenes con la lista de PNGs generados.
    """

    def execute(
        self,
        artifact: ReportArtifact,
        config: DeliveryConfig,
        logger: logging.Logger,
    ) -> StepResult:
        # Support either plural capture_images or legacy singular capture_image.
        captures = list(config.capture_images or [])
        if not captures and config.capture_image is not None:
            captures = [config.capture_image]

        if not captures:
            return StepResult(
                status="skipped",
                step_name="CaptureImageStep",
                message="capture_images no configurado",
            )

        from src.core.excel_manager import ExcelManager

        try:
            manager = ExcelManager(artifact.ruta_excel)
        except Exception as exc:  # bad file path etc.
            logger.error("Error abriendo Excel para captura: %s", exc)
            return StepResult(
                status="error",
                step_name="CaptureImageStep",
                message=str(exc),
            )

        produced: list[str] = []
        errores: list[str] = []

        for cfg in captures:
            try:
                png_path = manager.capture_range(
                    sheet_name=cfg.hoja,
                    range_addr=cfg.rango,
                )
                artifact.rutas_imagenes.append(png_path)
                produced.append(f"{cfg.hoja}:{png_path.name}")
            except (RuntimeError, ImportError) as exc:
                # LibreOffice / Pillow no disponible → no tiene sentido seguir
                logger.warning("Dependencia faltante, omitiendo capturas: %s", exc)
                return StepResult(
                    status="skipped",
                    step_name="CaptureImageStep",
                    message=str(exc),
                )
            except Exception as exc:  # per-capture error
                logger.error("Captura fallida [%s]: %s", cfg.hoja, exc)
                errores.append(f"{cfg.hoja}: {exc}")

        if produced and not errores:
            return StepResult(
                status="success",
                step_name="CaptureImageStep",
                message=f"Imagenes generadas: {', '.join(produced)}",
                artifact_path=artifact.rutas_imagenes[0] if artifact.rutas_imagenes else None,
            )
        if produced and errores:
            return StepResult(
                status="partial",
                step_name="CaptureImageStep",
                message=(
                    f"Exito: {', '.join(produced)} | "
                    f"Fallos: {'; '.join(errores)}"
                ),
                artifact_path=artifact.rutas_imagenes[0] if artifact.rutas_imagenes else None,
            )
        return StepResult(
            status="error",
            step_name="CaptureImageStep",
            message=f"Todas las capturas fallaron: {'; '.join(errores)}",
        )
