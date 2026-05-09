"""
SendWhatsAppStep - Paso de envio del reporte por WhatsApp.
"""
import logging
from datetime import datetime

from src.delivery.pipeline import DeliveryConfig, DeliveryStep, ReportArtifact, StepResult


_MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _format_periodo(fecha_iso: str | None) -> str | None:
    """Convierte 'YYYY-MM-DD' a 'Mayo 2026'."""
    if not fecha_iso:
        return None
    try:
        dt = datetime.strptime(str(fecha_iso), "%Y-%m-%d")
        return f"{_MESES_ES[dt.month - 1]} {dt.year}"
    except (ValueError, TypeError):
        return None


def _build_caption(
    *,
    is_group: bool,
    contact_name: str | None,
    periodo: str | None,
    sheet: str | None,
    report_name: str | None,
) -> str:
    """
    Caption personalizado con emojis. Distingue grupo vs contacto individual.
    """
    title = sheet or report_name or "Reporte"
    head = f"📊 *{title}*"
    if periodo:
        head += f" · 🗓️ {periodo}"

    if is_group:
        return f"{head}\n🤖 Bot Informes Badie"

    first_name = (contact_name or "").split()[0] if contact_name else ""
    saludo = f"👋 Hola {first_name}!" if first_name else "👋 Hola!"
    return f"{saludo}\n{head}\n🤖 Bot Informes Badie"


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

        report_name = artifact.metadata.get("nombre", artifact.ruta_excel.stem)
        periodo = _format_periodo(artifact.metadata.get("fecha"))

        for grupo_idx, grupo in enumerate(config.whatsapp.grupos):
            try:
                # Recuperar metadata del destinatario si esta presente
                meta = (
                    config.whatsapp.recipients_meta[grupo_idx]
                    if grupo_idx < len(config.whatsapp.recipients_meta)
                    else None
                )
                is_group = meta.is_group if meta else False
                contact_name = meta.contact_name if meta else None

                def _caption_para_imagen(idx: int) -> str:
                    sheet = (
                        artifact.nombres_hojas[idx]
                        if idx < len(artifact.nombres_hojas)
                        else None
                    )
                    return _build_caption(
                        is_group=is_group,
                        contact_name=contact_name,
                        periodo=periodo,
                        sheet=sheet,
                        report_name=report_name,
                    )

                caption_archivo = _build_caption(
                    is_group=is_group,
                    contact_name=contact_name,
                    periodo=periodo,
                    sheet=None,
                    report_name=report_name,
                )

                if config.whatsapp.enviar_como == "imagen":
                    if not artifact.rutas_imagenes:
                        logger.info(
                            "WhatsApp: sin imagenes para '%s', omitiendo.",
                            artifact.ruta_excel.name,
                        )
                        continue
                    for i, img_path in enumerate(artifact.rutas_imagenes):
                        client.send_image(
                            grupo, img_path, caption=_caption_para_imagen(i)
                        )
                elif config.whatsapp.enviar_como == "ambos":
                    for i, img_path in enumerate(artifact.rutas_imagenes):
                        client.send_image(
                            grupo, img_path, caption=_caption_para_imagen(i)
                        )
                    client.send_file(grupo, artifact.ruta_excel, caption=caption_archivo)
                else:
                    client.send_file(grupo, artifact.ruta_excel, caption=caption_archivo)
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
