"""
SendWhatsAppStep - Paso de envio del reporte por WhatsApp.
"""
import logging

from src.delivery.pipeline import DeliveryConfig, DeliveryStep, ReportArtifact, StepResult


class SendWhatsAppStep(DeliveryStep):
    """Envia el reporte por WhatsApp a grupos o contactos configurados."""

    def execute(
        self,
        artifact: ReportArtifact,
        config: DeliveryConfig,
        logger: logging.Logger,
    ) -> StepResult:
        if config.whatsapp is None:
            return StepResult(
                status="skipped",
                step_name="SendWhatsAppStep",
                message="whatsapp no configurado",
            )

        from config.settings import WHATSAPP_SERVICE_URL
        from src.core.whatsapp_client import WhatsAppClient

        client = WhatsAppClient(WHATSAPP_SERVICE_URL)
        errores = []

        for grupo in config.whatsapp.grupos:
            try:
                caption = artifact.metadata.get("nombre", artifact.ruta_excel.stem)
                if config.whatsapp.enviar_como == "imagen":
                    if artifact.ruta_imagen is None:
                        logger.info(
                            "WhatsApp: sin imagen para '%s', omitiendo.",
                            artifact.ruta_excel.name,
                        )
                        continue
                    client.send_image(grupo, artifact.ruta_imagen, caption=caption)
                elif config.whatsapp.enviar_como == "ambos":
                    if artifact.ruta_imagen is not None:
                        client.send_image(grupo, artifact.ruta_imagen, caption=caption)
                    client.send_file(grupo, artifact.ruta_excel, caption=caption)
                else:
                    client.send_file(grupo, artifact.ruta_excel, caption=caption)
            except Exception as exc:
                logger.error("Error enviando WhatsApp a '%s': %s", grupo, exc)
                errores.append(f"{grupo}: {exc}")

        if errores:
            return StepResult(
                status="error",
                step_name="SendWhatsAppStep",
                message=f"Errores en {len(errores)} grupo(s): {'; '.join(errores)}",
            )

        return StepResult(
            status="success",
            step_name="SendWhatsAppStep",
            message=f"Enviado a {len(config.whatsapp.grupos)} grupo(s): {config.whatsapp.grupos}",
        )
