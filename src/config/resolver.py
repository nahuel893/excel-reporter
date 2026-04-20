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
    DeliveryTarget,
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

TEST_CONTACT_NAME = "Nahuel Aguirre"


def _collapse_enviar_a_for_test(
    enviar_a: dict | None,
    contactos: dict,
) -> dict | None:
    """Collapse enviar_a to a single test-safe contact (TEST_CONTACT_NAME).

    Takes the union of all requested channels across all original recipients,
    promoting 'email_cc' to 'email', then returns a new enviar_a dict with
    only TEST_CONTACT_NAME as the recipient.

    Returns None if the resulting channel union is empty (nothing to send).
    Raises ValueError if TEST_CONTACT_NAME is not present in contactos.
    Logs a WARNING and drops 'whatsapp' if the test contact has no telefono
    and no whatsapp_grupo.
    """
    channels: set[str] = set()
    for target in (enviar_a or {}).values():
        for ch in target.via:
            # Promote email_cc -> email so the test contact receives as To:
            channels.add("email" if ch == "email_cc" else ch)

    if not channels:
        return None

    if TEST_CONTACT_NAME not in contactos:
        raise ValueError(
            f"test_mode requires contact '{TEST_CONTACT_NAME}' in contactos catalog, "
            f"but it was not found. Available: {list(contactos.keys())}"
        )

    test_contact = contactos[TEST_CONTACT_NAME]
    if "whatsapp" in channels and not (test_contact.telefono or test_contact.whatsapp_grupo):
        logger.warning(
            "test_mode: contact '%s' has no telefono or whatsapp_grupo; "
            "dropping whatsapp channel",
            TEST_CONTACT_NAME,
        )
        channels.discard("whatsapp")

    if not channels:
        return None

    # Deterministic order: email always before whatsapp
    via_list = [ch for ch in ("email", "whatsapp") if ch in channels]
    return {TEST_CONTACT_NAME: DeliveryTarget(via=via_list)}


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
    test_mode: bool = False,
) -> DeliveryConfig | None:
    """
    Translate named contacts + channels into the concrete DeliveryConfig
    that DeliveryPipeline.run() expects.

    Returns None if report has no enviar_a (and no captures).

    When test_mode=True, collapses enviar_a to a single entry for
    TEST_CONTACT_NAME before processing, so no real recipients are contacted.
    """
    has_captures = bool(report.capture_images or report.capture_image)

    # In test mode, collapse all recipients to the safe test contact BEFORE
    # the main loop. This is the single chokepoint: all channels that would
    # have been sent to real contacts are redirected to TEST_CONTACT_NAME.
    if test_mode and report.enviar_a:
        effective_enviar_a = _collapse_enviar_a_for_test(report.enviar_a, contactos)
    else:
        effective_enviar_a = report.enviar_a

    if not effective_enviar_a and not has_captures:
        return None

    email_recipients: list[str] = []
    email_cc: list[str] = []
    whatsapp_targets: list[str] = []

    for contact_name, target in (effective_enviar_a or {}).items():
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

    # Normalize captures: plural wins, fall back to legacy singular.
    capture_list: list[CaptureConfig] = []
    if report.capture_images:
        capture_list = [
            CaptureConfig(hoja=c.hoja, rango=c.rango, renderer=c.renderer)
            for c in report.capture_images
        ]
    elif report.capture_image:
        capture_list = [
            CaptureConfig(
                hoja=report.capture_image.hoja,
                rango=report.capture_image.rango,
                renderer=report.capture_image.renderer,
            )
        ]

    return DeliveryConfig(
        capture_image=capture_list[0] if capture_list else None,  # legacy field, first only
        capture_images=capture_list,
        email=EmailConfig(destinatarios=email_recipients, cc=email_cc, asunto=report.asunto_email) if email_recipients else None,
        whatsapp=WhatsAppConfig(grupos=whatsapp_targets) if whatsapp_targets else None,
    )


def merge_filters(global_f: GlobalFilters, report_f: ReportFilters | None) -> dict:
    """Merge global filters with per-report overrides. Report wins when set."""
    merged = {
        "fecha_desde": global_f.fecha_desde,
        "fecha_hasta": global_f.fecha_hasta,
        "genericos": global_f.genericos,
        "categorias": global_f.categorias,
        "con_slicers": global_f.con_slicers,
        "con_cobertura": global_f.con_cobertura,
        "enviar_email": global_f.enviar_email,
        "enviar_whatsapp": global_f.enviar_whatsapp,
        "supervisores": None,
        "sucursales": None,
        "archivo_plantilla": global_f.archivo_plantilla,
        "id_sucursal": global_f.id_sucursal,
        "id_fuerza_ventas": global_f.id_fuerza_ventas,
        "id_articulo": global_f.id_articulo,
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
        if report_f.id_articulo is not None:
            merged["id_articulo"] = report_f.id_articulo
        if report_f.id_sucursal is not None:
            merged["id_sucursal"] = report_f.id_sucursal
    return merged
