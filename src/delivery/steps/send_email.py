"""
SendEmailStep - Paso de envio del reporte por email.
"""
import logging
from pathlib import Path

from src.delivery.pipeline import DeliveryConfig, DeliveryStep, ReportArtifact, StepResult


class SendEmailStep(DeliveryStep):
    """Envia el reporte por email con adjuntos configurables."""

    def execute(
        self,
        artifact: ReportArtifact,
        config: DeliveryConfig,
        logger: logging.Logger,
    ) -> StepResult:
        if config.email is None:
            return StepResult(
                status="skipped",
                step_name="SendEmailStep",
                message="email no configurado",
            )

        from src.core.email_sender import EmailSender

        adjuntos: list[Path] = []
        for item in config.email.adjuntos:
            if item == "excel":
                adjuntos.append(artifact.ruta_excel)
            elif item == "imagen":
                if artifact.ruta_imagen is None:
                    logger.warning(
                        "Se pidio adjuntar imagen pero ruta_imagen es None "
                        "(captura no ejecutada o fallida). Se omite adjunto de imagen."
                    )
                else:
                    adjuntos.append(artifact.ruta_imagen)

        asunto = config.email.asunto or _generar_asunto(artifact)

        try:
            sender = EmailSender()
            sender.send(
                destinatarios=config.email.destinatarios,
                asunto=asunto,
                cuerpo=_generar_cuerpo(artifact),
                adjuntos=adjuntos,
            )
            return StepResult(
                status="success",
                step_name="SendEmailStep",
                message=f"Email enviado a {config.email.destinatarios}",
            )
        except Exception as exc:
            logger.error("Error al enviar email: %s", exc)
            return StepResult(
                status="error",
                step_name="SendEmailStep",
                message=str(exc),
            )


def _generar_asunto(artifact: ReportArtifact) -> str:
    nombre = artifact.metadata.get("nombre", artifact.ruta_excel.stem)
    fecha = artifact.metadata.get("fecha", "")
    if fecha:
        return f"Reporte {nombre} - {fecha}"
    return f"Reporte {nombre}"


def _generar_cuerpo(artifact: ReportArtifact) -> str:
    nombre = artifact.metadata.get("nombre", artifact.ruta_excel.stem)
    return f"Se adjunta el reporte {nombre}.\n\nGenerado automaticamente."
