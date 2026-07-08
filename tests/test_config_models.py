"""Tests para src/config/models.py y src/config/resolver.py."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config.models import (
    CaptureImageConfig,
    ContactInfo,
    DeliveryTarget,
    GlobalFilters,
    ReportConfig,
    ReportEntry,
    ReportFilters,
)
from src.config.resolver import (
    load_contacts,
    load_report_config,
    merge_filters,
    resolve_delivery,
)
from src.delivery.pipeline import DeliveryConfig


# ---------------------------------------------------------------------------
# ContactInfo
# ---------------------------------------------------------------------------


class TestContactInfo:
    def test_valid_email_only(self):
        c = ContactInfo(email="test@example.com")
        assert c.email == "test@example.com"
        assert c.telefono is None

    def test_valid_whatsapp_grupo(self):
        c = ContactInfo(whatsapp_grupo="Grupo Ventas")
        assert c.whatsapp_grupo == "Grupo Ventas"

    def test_valid_all_fields(self):
        c = ContactInfo(email="a@b.com", telefono="+5491155", whatsapp_grupo="Grupo")
        assert c.email == "a@b.com"

    def test_no_channels_raises(self):
        with pytest.raises(ValidationError, match="at least one"):
            ContactInfo()

    def test_all_none_raises(self):
        with pytest.raises(ValidationError):
            ContactInfo(email=None, telefono=None, whatsapp_grupo=None)


# ---------------------------------------------------------------------------
# DeliveryTarget
# ---------------------------------------------------------------------------


class TestDeliveryTarget:
    def test_valid_email(self):
        t = DeliveryTarget(via=["email"])
        assert t.via == ["email"]

    def test_valid_both(self):
        t = DeliveryTarget(via=["email", "whatsapp"])
        assert len(t.via) == 2

    def test_invalid_channel_raises(self):
        with pytest.raises(ValidationError):
            DeliveryTarget(via=["sms"])

    def test_empty_via_raises(self):
        with pytest.raises(ValidationError):
            DeliveryTarget(via=[])


# ---------------------------------------------------------------------------
# CaptureImageConfig
# ---------------------------------------------------------------------------


class TestCaptureImageConfigCaption:
    def test_accepts_optional_caption_and_caption_anchor(self):
        cfg = CaptureImageConfig(
            hoja="Avance",
            rango="auto:bordes",
            caption="GFLORES",
            caption_anchor="B2",
        )
        assert cfg.caption == "GFLORES"
        assert cfg.caption_anchor == "B2"

    def test_caption_and_caption_anchor_default_to_none(self):
        cfg = CaptureImageConfig(hoja="Ventas Bultos", rango="A1:H20")
        assert cfg.caption is None
        assert cfg.caption_anchor is None


# ---------------------------------------------------------------------------
# GlobalFilters
# ---------------------------------------------------------------------------


class TestGlobalFilters:
    def test_minimal(self):
        f = GlobalFilters(fecha_desde="2026-01-01", fecha_hasta="2026-01-31")
        assert f.genericos is None
        assert f.con_slicers is True
        assert f.con_cobertura is True

    def test_full(self):
        f = GlobalFilters(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            genericos=["CERVEZAS"],
            con_slicers=False,
            con_cobertura=False,
        )
        assert f.genericos == ["CERVEZAS"]
        assert f.con_slicers is False

    def test_accepts_whatsapp_enviar_como_ambos(self):
        f = GlobalFilters(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            whatsapp_enviar_como="ambos",
        )
        assert f.whatsapp_enviar_como == "ambos"


# ---------------------------------------------------------------------------
# ReportConfig
# ---------------------------------------------------------------------------


class TestReportConfig:
    def test_minimal_config(self):
        cfg = ReportConfig(
            tipo="ventas",
            filtros=GlobalFilters(fecha_desde="2026-01-01", fecha_hasta="2026-01-31"),
            reportes=[ReportEntry(nombre="Test")],
        )
        assert cfg.tipo == "ventas"
        assert len(cfg.reportes) == 1

    def test_invalid_tipo_raises(self):
        with pytest.raises(ValidationError):
            ReportConfig(
                tipo="invalid",
                filtros=GlobalFilters(fecha_desde="2026-01-01", fecha_hasta="2026-01-31"),
                reportes=[],
            )

    def test_validate_contacts_passes_with_valid_refs(self):
        cfg = ReportConfig(
            tipo="ventas",
            filtros=GlobalFilters(fecha_desde="2026-01-01", fecha_hasta="2026-01-31"),
            reportes=[
                ReportEntry(
                    nombre="Test",
                    enviar_a={"Walter": DeliveryTarget(via=["email"])},
                )
            ],
        )
        contactos = {"Walter": ContactInfo(email="w@test.com")}
        cfg.validate_contacts(contactos)  # should not raise

    def test_validate_contacts_fails_with_unknown_ref(self):
        cfg = ReportConfig(
            tipo="ventas",
            filtros=GlobalFilters(fecha_desde="2026-01-01", fecha_hasta="2026-01-31"),
            reportes=[
                ReportEntry(
                    nombre="Test",
                    enviar_a={"Unknown": DeliveryTarget(via=["email"])},
                )
            ],
        )
        with pytest.raises(ValueError, match="Unknown"):
            cfg.validate_contacts({"Walter": ContactInfo(email="w@test.com")})

    def test_validate_contacts_passes_with_no_enviar_a(self):
        cfg = ReportConfig(
            tipo="ventas",
            filtros=GlobalFilters(fecha_desde="2026-01-01", fecha_hasta="2026-01-31"),
            reportes=[ReportEntry(nombre="Test")],
        )
        cfg.validate_contacts({})  # should not raise

    def test_model_validate_from_dict(self):
        raw = {
            "tipo": "ventas",
            "filtros": {"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"},
            "reportes": [{"nombre": "Test"}],
        }
        cfg = ReportConfig.model_validate(raw)
        assert cfg.tipo == "ventas"


# ---------------------------------------------------------------------------
# load_contacts / load_report_config
# ---------------------------------------------------------------------------


class TestLoadContacts:
    def test_loads_valid_file(self, tmp_path):
        path = tmp_path / "contactos.json"
        path.write_text(json.dumps({
            "Walter": {"email": "w@test.com"},
            "Grupo": {"whatsapp_grupo": "Grupo Ventas"},
        }))
        contactos = load_contacts(path)
        assert "Walter" in contactos
        assert contactos["Walter"].email == "w@test.com"
        assert contactos["Grupo"].whatsapp_grupo == "Grupo Ventas"

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_contacts(tmp_path / "no_existe.json")

    def test_invalid_contact_raises(self, tmp_path):
        path = tmp_path / "contactos.json"
        path.write_text(json.dumps({"Bad": {}}))
        with pytest.raises(ValidationError):
            load_contacts(path)


class TestLoadReportConfig:
    def test_loads_valid_file(self, tmp_path):
        path = tmp_path / "ventas.json"
        path.write_text(json.dumps({
            "tipo": "ventas",
            "filtros": {"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"},
            "reportes": [{"nombre": "Test"}],
        }))
        cfg = load_report_config(path)
        assert cfg.tipo == "ventas"

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_report_config(tmp_path / "no_existe.json")

    def test_loads_config_with_whatsapp_enviar_como_ambos(self, tmp_path):
        path = tmp_path / "rebotes.json"
        path.write_text(json.dumps({
            "tipo": "reporte-rebotes",
            "filtros": {
                "fecha_desde": "2026-01-01",
                "fecha_hasta": "2026-01-31",
                "whatsapp_enviar_como": "ambos",
            },
            "reportes": [{"nombre": "Test"}],
        }))

        cfg = load_report_config(path)

        assert cfg.filtros.whatsapp_enviar_como == "ambos"


# ---------------------------------------------------------------------------
# resolve_delivery
# ---------------------------------------------------------------------------


class TestResolveDelivery:
    def test_returns_none_when_no_enviar_a(self):
        report = ReportEntry(nombre="Test")
        result = resolve_delivery(report, {})
        assert result is None

    def test_resolves_email_contact(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={"Walter": DeliveryTarget(via=["email"])},
        )
        contactos = {"Walter": ContactInfo(email="w@test.com")}
        result = resolve_delivery(report, contactos)

        assert isinstance(result, DeliveryConfig)
        assert result.email is not None
        assert result.email.destinatarios == ["w@test.com"]
        assert result.whatsapp is None

    def test_resolves_whatsapp_grupo(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={"Grupo": DeliveryTarget(via=["whatsapp"])},
        )
        contactos = {"Grupo": ContactInfo(whatsapp_grupo="Grupo Ventas")}
        result = resolve_delivery(report, contactos)

        assert result.whatsapp is not None
        assert result.whatsapp.grupos == ["Grupo Ventas"]
        assert result.email is None

    def test_resolves_whatsapp_telefono(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={"Walter": DeliveryTarget(via=["whatsapp"])},
        )
        contactos = {"Walter": ContactInfo(telefono="+5491155")}
        result = resolve_delivery(report, contactos)

        assert result.whatsapp is not None
        assert result.whatsapp.grupos == ["+5491155"]

    def test_resolves_both_channels(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={"Walter": DeliveryTarget(via=["email", "whatsapp"])},
        )
        contactos = {"Walter": ContactInfo(email="w@test.com", telefono="+5491155")}
        result = resolve_delivery(report, contactos)

        assert result.email is not None
        assert result.whatsapp is not None

    def test_multiple_contacts(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={
                "Walter": DeliveryTarget(via=["email"]),
                "Hernan": DeliveryTarget(via=["email"]),
            },
        )
        contactos = {
            "Walter": ContactInfo(email="w@test.com"),
            "Hernan": ContactInfo(email="h@test.com"),
        }
        result = resolve_delivery(report, contactos)

        assert len(result.email.destinatarios) == 2
        assert "w@test.com" in result.email.destinatarios
        assert "h@test.com" in result.email.destinatarios

    def test_skips_missing_contact(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={"Ghost": DeliveryTarget(via=["email"])},
        )
        result = resolve_delivery(report, {})

        # No email recipients → email config is None
        assert result.email is None

    def test_skips_contact_without_email(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={"Grupo": DeliveryTarget(via=["email"])},
        )
        contactos = {"Grupo": ContactInfo(whatsapp_grupo="Grupo Ventas")}
        result = resolve_delivery(report, contactos)

        assert result.email is None

    def test_capture_image_resolved(self):
        report = ReportEntry(
            nombre="Test",
            capture_image=CaptureImageConfig(hoja="Ventas Bultos", rango="A1:H20"),
            enviar_a={"W": DeliveryTarget(via=["email"])},
        )
        contactos = {"W": ContactInfo(email="w@test.com")}
        result = resolve_delivery(report, contactos)

        assert result.capture_image is not None
        assert result.capture_image.hoja == "Ventas Bultos"
        assert result.capture_image.rango == "A1:H20"

    def test_propagates_whatsapp_enviar_como_ambos(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={"Grupo": DeliveryTarget(via=["whatsapp"])},
        )
        contactos = {"Grupo": ContactInfo(whatsapp_grupo="Grupo Ventas")}

        result = resolve_delivery(report, contactos, whatsapp_enviar_como="ambos")

        assert result.whatsapp is not None
        assert result.whatsapp.enviar_como == "ambos"


# ---------------------------------------------------------------------------
# merge_filters
# ---------------------------------------------------------------------------


class TestMergeFilters:
    def test_global_only(self):
        gf = GlobalFilters(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            genericos=["CERVEZAS"],
        )
        merged = merge_filters(gf, None)
        assert merged["fecha_desde"] == "2026-01-01"
        assert merged["genericos"] == ["CERVEZAS"]
        assert merged["con_slicers"] is True
        assert merged["supervisores"] is None
        assert merged["sucursales"] is None

    def test_report_overrides_genericos(self):
        gf = GlobalFilters(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            genericos=["CERVEZAS", "AGUAS"],
        )
        rf = ReportFilters(genericos=["VINOS"])
        merged = merge_filters(gf, rf)
        assert merged["genericos"] == ["VINOS"]

    def test_report_overrides_con_slicers(self):
        gf = GlobalFilters(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            con_slicers=True,
        )
        rf = ReportFilters(con_slicers=False)
        merged = merge_filters(gf, rf)
        assert merged["con_slicers"] is False

    def test_report_none_fields_keep_global(self):
        gf = GlobalFilters(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            genericos=["CERVEZAS"],
            con_slicers=True,
        )
        rf = ReportFilters()  # all None
        merged = merge_filters(gf, rf)
        assert merged["genericos"] == ["CERVEZAS"]
        assert merged["con_slicers"] is True

    def test_report_sets_supervisores_and_sucursales(self):
        gf = GlobalFilters(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
        )
        rf = ReportFilters(
            supervisores=["Walter Vilte"],
            sucursales=["CASA CENTRAL", "SUCURSAL CAFAYATE"],
        )
        merged = merge_filters(gf, rf)
        assert merged["supervisores"] == ["Walter Vilte"]
        assert merged["sucursales"] == ["CASA CENTRAL", "SUCURSAL CAFAYATE"]

    def test_enviar_flags_default_true(self):
        gf = GlobalFilters(fecha_desde="2026-01-01", fecha_hasta="2026-01-31")
        merged = merge_filters(gf, None)
        assert merged["enviar_email"] is True
        assert merged["enviar_whatsapp"] is True

    def test_global_enviar_flags_false(self):
        gf = GlobalFilters(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            enviar_email=False,
            enviar_whatsapp=False,
        )
        merged = merge_filters(gf, None)
        assert merged["enviar_email"] is False
        assert merged["enviar_whatsapp"] is False

    def test_report_overrides_enviar_flags(self):
        gf = GlobalFilters(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            enviar_email=True,
            enviar_whatsapp=True,
        )
        rf = ReportFilters(enviar_email=False)
        merged = merge_filters(gf, rf)
        assert merged["enviar_email"] is False
        assert merged["enviar_whatsapp"] is True


class TestResolveDeliveryFlags:
    def test_enviar_email_false_skips_email(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={"W": DeliveryTarget(via=["email", "whatsapp"])},
        )
        contactos = {"W": ContactInfo(email="w@test.com", telefono="+5491155")}
        result = resolve_delivery(report, contactos, enviar_email=False)

        assert result.email is None
        assert result.whatsapp is not None

    def test_enviar_whatsapp_false_skips_whatsapp(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={"W": DeliveryTarget(via=["email", "whatsapp"])},
        )
        contactos = {"W": ContactInfo(email="w@test.com", telefono="+5491155")}
        result = resolve_delivery(report, contactos, enviar_whatsapp=False)

        assert result.email is not None
        assert result.whatsapp is None

    def test_both_false_returns_empty_delivery(self):
        report = ReportEntry(
            nombre="Test",
            enviar_a={"W": DeliveryTarget(via=["email", "whatsapp"])},
        )
        contactos = {"W": ContactInfo(email="w@test.com", telefono="+5491155")}
        result = resolve_delivery(
            report, contactos, enviar_email=False, enviar_whatsapp=False
        )

        assert result.email is None
        assert result.whatsapp is None


# ---------------------------------------------------------------------------
# tipo_plantilla survives the full load + merge pipeline (regression guard)
# ---------------------------------------------------------------------------


class TestTipoPlantillaPropagation:
    """End-to-end: tipo_plantilla from the config must survive
    load_report_config (Pydantic) + merge_filters, not be silently dropped."""

    def test_badie_config_propagates_tipo_plantilla(self):
        report_config = load_report_config(Path("configs/avances_badie.json"))
        merged = merge_filters(report_config.filtros, report_config.reportes[0].filtros)
        assert merged["tipo_plantilla"] == "badie", (
            "tipo_plantilla debe sobrevivir el merge; si no, avance-badie corre como branca"
        )

    def test_default_tipo_plantilla_is_branca(self):
        f = GlobalFilters(fecha_desde="2026-06-01", fecha_hasta="2026-06-30")
        merged = merge_filters(f, None)
        assert merged["tipo_plantilla"] == "branca"
