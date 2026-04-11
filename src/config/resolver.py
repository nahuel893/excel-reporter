"""
Contact resolution: translates named contacts into concrete DeliveryConfig.

This is the thin layer between the new config format (named contacts + channels)
and the existing delivery pipeline models (EmailConfig, WhatsAppConfig).
"""

import json
import logging
from pathlib import Path

from src.config.models import (
    ContactInfo,
    GlobalFilters,
    ReportConfig,
    ReportEntry,
    ReportFilters,
)
from src.delivery.pipeline import (
    CaptureConfig,
    DeliveryConfig,
    EmailConfig,
    WhatsAppConfig,
)

logger = logging.getLogger(__name__)


def load_contacts(path: Path) -> dict[str, ContactInfo]:
    """Load and validate contactos.json."""
    if not path.exists():
        raise FileNotFoundError(f"Contacts file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {name: ContactInfo.model_validate(info) for name, info in raw.items()}


def load_report_config(path: Path) -> ReportConfig:
    """Load and validate a report config file (e.g. ventas.json)."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ReportConfig.model_validate(raw)


def resolve_delivery(
    report: ReportEntry,
    contactos: dict[str, ContactInfo],
    enviar_email: bool = True,
    enviar_whatsapp: bool = True,
) -> DeliveryConfig | None:
    """
    Translate named contacts + channels into the concrete DeliveryConfig
    that DeliveryPipeline.run() expects.

    Returns None if report has no enviar_a.
    """
    if not report.enviar_a:
        return None

    email_recipients: list[str] = []
    email_cc: list[str] = []
    whatsapp_targets: list[str] = []

    for contact_name, target in report.enviar_a.items():
        contact = contactos.get(contact_name)
        if contact is None:
            logger.warning("Contact '%s' not found in catalog, skipping", contact_name)
            continue

        if "email" in target.via and enviar_email:
            if contact.email:
                email_recipients.append(contact.email)
            else:
                logger.warning(
                    "Contact '%s' has via 'email' but no email address", contact_name
                )

        if "email_cc" in target.via and enviar_email:
            if contact.email:
                email_cc.append(contact.email)
            else:
                logger.warning(
                    "Contact '%s' has via 'email_cc' but no email address", contact_name
                )

        if "whatsapp" in target.via and enviar_whatsapp:
            if contact.whatsapp_grupo:
                whatsapp_targets.append(contact.whatsapp_grupo)
            elif contact.telefono:
                whatsapp_targets.append(contact.telefono)
            else:
                logger.warning(
                    "Contact '%s' has via 'whatsapp' but no telefono or whatsapp_grupo",
                    contact_name,
                )

    capture = None
    if report.capture_image:
        capture = CaptureConfig(
            hoja=report.capture_image.hoja,
            rango=report.capture_image.rango,
        )

    return DeliveryConfig(
        capture_image=capture,
        email=EmailConfig(destinatarios=email_recipients, cc=email_cc) if email_recipients else None,
        whatsapp=WhatsAppConfig(grupos=whatsapp_targets) if whatsapp_targets else None,
    )


def merge_filters(global_f: GlobalFilters, report_f: ReportFilters | None) -> dict:
    """Merge global filters with per-report overrides. Report wins when set."""
    merged = {
        "fecha_desde": global_f.fecha_desde,
        "fecha_hasta": global_f.fecha_hasta,
        "genericos": global_f.genericos,
        "categorias": getattr(global_f, "categorias", None),
        "con_slicers": global_f.con_slicers,
        "con_cobertura": global_f.con_cobertura,
        "enviar_email": global_f.enviar_email,
        "enviar_whatsapp": global_f.enviar_whatsapp,
        "supervisores": None,
        "sucursales": None,
    }
    if report_f:
        if report_f.genericos is not None:
            merged["genericos"] = report_f.genericos
        if getattr(report_f, "categorias", None) is not None:
            merged["categorias"] = report_f.categorias
        if report_f.con_slicers is not None:
            merged["con_slicers"] = report_f.con_slicers
        if report_f.con_cobertura is not None:
            merged["con_cobertura"] = report_f.con_cobertura
        if report_f.enviar_email is not None:
            merged["enviar_email"] = report_f.enviar_email
        if report_f.enviar_whatsapp is not None:
            merged["enviar_whatsapp"] = report_f.enviar_whatsapp
        if report_f.supervisores is not None:
            merged["supervisores"] = report_f.supervisores
        if report_f.sucursales is not None:
            merged["sucursales"] = report_f.sucursales
    return merged
