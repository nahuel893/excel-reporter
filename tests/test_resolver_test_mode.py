"""Unit tests for test-mode collapse logic in src/config/resolver.py.

Tests resolve_delivery(test_mode=True) behaviour:
- enviar_a is collapsed to a single entry (Nahuel Aguirre) with union of channels
- email_cc is promoted to email in the collapse
- channel gates (enviar_email / enviar_whatsapp) are still respected
- missing test contact raises ValueError
- whatsapp without telefono logs WARNING and is dropped
- non-delivery paths (captures only, empty enviar_a) are handled correctly
- test_mode=False is a noop (existing behaviour unchanged)
"""

import logging

import pytest

from src.config.models import (
    CaptureImageConfig,
    ContactInfo,
    DeliveryTarget,
    ReportEntry,
)
from src.config.resolver import TEST_CONTACT_NAME, resolve_delivery


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NAHUEL_CONTACT = ContactInfo(email="naguirre@danielmanzur.com", telefono="5493876008331")

CONTACTOS_WITH_NAHUEL: dict[str, ContactInfo] = {
    "Walter Vilte": ContactInfo(email="wvilte@ccu.com.ar"),
    "Adrian Garcia": ContactInfo(email="agarcia@ccu.com.ar"),
    "Sebastian Dellamea": ContactInfo(
        email="sdellamea@danielmanzur.com", telefono="5493885099320"
    ),
    TEST_CONTACT_NAME: NAHUEL_CONTACT,
}

CONTACTOS_WITHOUT_NAHUEL: dict[str, ContactInfo] = {
    "Walter Vilte": ContactInfo(email="wvilte@ccu.com.ar"),
}


def _report(enviar_a=None, capture_image=None, capture_images=None, asunto=None):
    """Build a minimal ReportEntry for testing."""
    return ReportEntry(
        nombre="Test Report",
        enviar_a=enviar_a,
        capture_image=capture_image,
        capture_images=capture_images,
        asunto_email=asunto,
    )


# ---------------------------------------------------------------------------
# T12 — Export constant
# ---------------------------------------------------------------------------


class TestExportConstant:
    def test_export_TEST_CONTACT_NAME_is_nahuel(self):
        assert TEST_CONTACT_NAME == "Nahuel Aguirre"


# ---------------------------------------------------------------------------
# Collapse logic tests
# ---------------------------------------------------------------------------


class TestCollapseSingleContact:
    def test_collapse_single_contact_email_only(self):
        """One contact with via=['email'] -> Nahuel gets via=['email']."""
        report = _report(
            enviar_a={"Walter Vilte": DeliveryTarget(via=["email"])}
        )
        result = resolve_delivery(
            report, CONTACTOS_WITH_NAHUEL, test_mode=True
        )

        assert result is not None
        assert result.email is not None
        assert "naguirre@danielmanzur.com" in result.email.destinatarios
        # Walter must NOT appear
        assert "wvilte@ccu.com.ar" not in result.email.destinatarios
        assert result.whatsapp is None

    def test_collapse_single_contact_whatsapp_only(self):
        """One contact with via=['whatsapp'] -> Nahuel gets via=['whatsapp']."""
        report = _report(
            enviar_a={"Walter Vilte": DeliveryTarget(via=["whatsapp"])}
        )
        result = resolve_delivery(
            report, CONTACTOS_WITH_NAHUEL, test_mode=True
        )

        assert result is not None
        assert result.whatsapp is not None
        # Nahuel's telefono is used because he has no whatsapp_grupo
        assert "5493876008331" in result.whatsapp.grupos
        assert result.email is None


class TestCollapseMultiContact:
    def test_collapse_multi_contact_union(self):
        """3 contacts mixing email/whatsapp -> Nahuel gets via=['email', 'whatsapp']."""
        report = _report(
            enviar_a={
                "Walter Vilte": DeliveryTarget(via=["email"]),
                "Adrian Garcia": DeliveryTarget(via=["email"]),
                "Sebastian Dellamea": DeliveryTarget(via=["whatsapp"]),
            }
        )
        result = resolve_delivery(
            report, CONTACTOS_WITH_NAHUEL, test_mode=True
        )

        assert result is not None
        assert result.email is not None
        assert result.whatsapp is not None
        assert "naguirre@danielmanzur.com" in result.email.destinatarios
        assert "5493876008331" in result.whatsapp.grupos
        # Original contacts must NOT appear
        assert "wvilte@ccu.com.ar" not in result.email.destinatarios
        assert "agarcia@ccu.com.ar" not in result.email.destinatarios

    def test_collapse_email_cc_promoted_to_email(self):
        """One contact with via=['email_cc'] -> Nahuel gets via=['email'] (NOT email_cc)."""
        report = _report(
            enviar_a={"Walter Vilte": DeliveryTarget(via=["email_cc"])}
        )
        result = resolve_delivery(
            report, CONTACTOS_WITH_NAHUEL, test_mode=True
        )

        assert result is not None
        assert result.email is not None
        # Must be in destinatarios (To:), NOT in cc
        assert "naguirre@danielmanzur.com" in result.email.destinatarios
        assert "naguirre@danielmanzur.com" not in result.email.cc

    def test_collapse_email_and_email_cc_deduplicated(self):
        """via=['email', 'email_cc'] on same contact -> email appears once, not twice."""
        report = _report(
            enviar_a={"Walter Vilte": DeliveryTarget(via=["email", "email_cc"])}
        )
        result = resolve_delivery(
            report, CONTACTOS_WITH_NAHUEL, test_mode=True
        )

        assert result is not None
        assert result.email is not None
        assert result.email.destinatarios.count("naguirre@danielmanzur.com") == 1


# ---------------------------------------------------------------------------
# Channel gate tests
# ---------------------------------------------------------------------------


class TestChannelGates:
    def test_gate_enviar_email_false_still_respected(self):
        """test_mode=True + enviar_email=False -> email is suppressed."""
        report = _report(
            enviar_a={"Walter Vilte": DeliveryTarget(via=["email"])}
        )
        result = resolve_delivery(
            report, CONTACTOS_WITH_NAHUEL, enviar_email=False, test_mode=True
        )

        # email must be absent (gate takes precedence)
        assert result is None or result.email is None

    def test_gate_enviar_whatsapp_false_still_respected(self):
        """test_mode=True + enviar_whatsapp=False -> whatsapp is suppressed."""
        report = _report(
            enviar_a={"Sebastian Dellamea": DeliveryTarget(via=["whatsapp"])}
        )
        result = resolve_delivery(
            report, CONTACTOS_WITH_NAHUEL, enviar_whatsapp=False, test_mode=True
        )

        assert result is None or result.whatsapp is None


# ---------------------------------------------------------------------------
# Error / warning cases
# ---------------------------------------------------------------------------


class TestContactResolutionErrors:
    def test_missing_test_contact_raises(self):
        """contactos without 'Nahuel Aguirre' + test_mode=True -> raises ValueError."""
        report = _report(
            enviar_a={"Walter Vilte": DeliveryTarget(via=["email"])}
        )
        with pytest.raises(ValueError, match="Nahuel Aguirre"):
            resolve_delivery(report, CONTACTOS_WITHOUT_NAHUEL, test_mode=True)

    def test_whatsapp_dropped_when_no_phone(self, caplog):
        """Nahuel has no telefono/whatsapp_grupo -> whatsapp channel logged as WARNING and dropped."""
        nahuel_no_phone = ContactInfo(email="naguirre@danielmanzur.com")
        contactos = {
            "Walter Vilte": ContactInfo(email="wvilte@ccu.com.ar"),
            TEST_CONTACT_NAME: nahuel_no_phone,
        }
        report = _report(
            enviar_a={"Walter Vilte": DeliveryTarget(via=["whatsapp"])}
        )

        with caplog.at_level(logging.WARNING, logger="src.config.resolver"):
            result = resolve_delivery(report, contactos, test_mode=True)

        # Channel dropped -> no whatsapp delivery
        assert result is None or result.whatsapp is None
        # WARNING must have been logged
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("whatsapp" in m.lower() or "phone" in m.lower() or "telefono" in m.lower()
                   for m in warning_msgs)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestCaptureCaptionThreading:
    """resolve_delivery must propagate caption/caption_anchor from
    CaptureImageConfig into the concrete pipeline.CaptureConfig."""

    def test_capture_images_threads_caption_and_caption_anchor(self):
        report = _report(
            capture_images=[
                CaptureImageConfig(
                    hoja="Avance",
                    rango="auto:bordes",
                    caption="GFLORES",
                    caption_anchor="B2",
                )
            ],
        )
        result = resolve_delivery(report, CONTACTOS_WITH_NAHUEL)

        assert result is not None
        assert len(result.capture_images) == 1
        assert result.capture_images[0].caption == "GFLORES"
        assert result.capture_images[0].caption_anchor == "B2"

    def test_capture_image_legacy_singular_threads_caption(self):
        report = _report(
            capture_image=CaptureImageConfig(
                hoja="Ventas Bultos", rango="A1:H20", caption="Zona Norte"
            ),
        )
        result = resolve_delivery(report, CONTACTOS_WITH_NAHUEL)

        assert result is not None
        assert result.capture_image.caption == "Zona Norte"


class TestEdgeCases:
    def test_empty_enviar_a_returns_none(self):
        """enviar_a={} + test_mode=True -> still returns None (no captures)."""
        report = _report(enviar_a={})
        result = resolve_delivery(report, CONTACTOS_WITH_NAHUEL, test_mode=True)
        assert result is None

    def test_captures_without_enviar_a_unchanged(self):
        """enviar_a=None but captures present + test_mode=True -> captures flow through."""
        report = _report(
            enviar_a=None,
            capture_image=CaptureImageConfig(hoja="Ventas Bultos", rango="A1:H20"),
        )
        result = resolve_delivery(report, CONTACTOS_WITH_NAHUEL, test_mode=True)

        # Captures must still be present
        assert result is not None
        assert result.capture_image is not None
        assert result.capture_image.hoja == "Ventas Bultos"
        # No delivery channels (no enviar_a)
        assert result.email is None
        assert result.whatsapp is None

    def test_test_mode_false_is_noop(self):
        """test_mode=False preserves original contacts (existing behaviour unchanged)."""
        report = _report(
            enviar_a={
                "Walter Vilte": DeliveryTarget(via=["email"]),
                "Adrian Garcia": DeliveryTarget(via=["email"]),
            }
        )
        result = resolve_delivery(report, CONTACTOS_WITH_NAHUEL, test_mode=False)

        assert result is not None
        assert result.email is not None
        # Both originals present, Nahuel NOT forced in
        assert "wvilte@ccu.com.ar" in result.email.destinatarios
        assert "agarcia@ccu.com.ar" in result.email.destinatarios
