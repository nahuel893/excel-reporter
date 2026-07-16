"""Wiring tests for configs/avances_badie.json — PR4 activates the dormant
RangeRecognizer/auto:bordes capture pipeline for the AVANCE BADIE report:
- Sheet "Avance": auto:bordes + caption_header "Super" -> 4 supervisor cards.
- Sheet "Cober Nueva": 5 fixed, cropped ranges with explicit captions.
- Sheet "Multicategoria": 1 fixed, cropped range with an explicit caption.
- "Preventa Salta" added as a WhatsApp-only delivery target (WhatsApp itself
  stays globally disabled via filtros.enviar_whatsapp=False until manual
  verification — this only prepares the wiring).
"""
from pathlib import Path

from src.config.resolver import load_contacts, load_report_config

CONFIG_PATH = Path("configs/avances_badie.json")
CONTACTS_PATH = Path("configs/contactos.json")


class TestAvancesBadieConfigLoads:
    def test_config_loads_and_validates(self):
        cfg = load_report_config(CONFIG_PATH)
        contactos = load_contacts(CONTACTS_PATH)
        cfg.validate_contacts(contactos)  # should not raise

    def test_tipo_and_plantilla_unchanged(self):
        cfg = load_report_config(CONFIG_PATH)
        assert cfg.tipo == "avances"
        assert cfg.filtros.tipo_plantilla == "badie"


class TestAvancesBadieCaptureImages:
    def _captures(self):
        cfg = load_report_config(CONFIG_PATH)
        report = cfg.reportes[0]
        assert report.capture_images is not None
        return report.capture_images

    def test_seven_captures_configured(self):
        assert len(self._captures()) == 7

    def test_all_captures_use_libreoffice_renderer(self):
        assert all(c.renderer == "libreoffice" for c in self._captures())

    def test_avance_sheet_uses_auto_bordes_with_super_caption_header(self):
        captures = self._captures()
        avance = [c for c in captures if c.hoja == "Avance"]
        assert len(avance) == 1
        assert avance[0].rango == "auto:bordes"
        assert avance[0].caption_header == "Super"

    def test_cober_nueva_has_five_fixed_cropped_ranges_with_captions(self):
        captures = self._captures()
        cober = [c for c in captures if c.hoja == "Cober Nueva"]
        assert len(cober) == 5
        assert all(c.recortar is True for c in cober)
        assert all(c.rango != "auto:bordes" for c in cober)

        by_rango = {c.rango: c.caption for c in cober}
        assert by_rango == {
            "A49:R55": "Cober Nueva - Cervezas 1",
            "T49:AW55": "Cober Nueva - Cervezas 2",
            "AY49:BX55": "Cober Nueva - ADO",
            "BZ49:CW55": "Cober Nueva - Vinos CCU",
            "CY49:DV55": "Cober Nueva - Sidras y Licores",
        }

    def test_multicategoria_has_one_fixed_cropped_range_with_caption(self):
        captures = self._captures()
        multi = [c for c in captures if c.hoja == "Multicategoria"]
        assert len(multi) == 1
        assert multi[0].rango == "A1:V57"
        assert multi[0].recortar is True
        assert multi[0].caption == "Multicategoria"


class TestAvancesBadiePreventaSaltaWhatsapp:
    def test_preventa_salta_added_as_whatsapp_target(self):
        cfg = load_report_config(CONFIG_PATH)
        report = cfg.reportes[0]
        assert report.enviar_a is not None
        assert "Preventa Salta" in report.enviar_a
        assert report.enviar_a["Preventa Salta"].via == ["whatsapp"]

    def test_preventa_salta_exists_in_contacts_catalog_with_whatsapp_channel(self):
        contactos = load_contacts(CONTACTS_PATH)
        assert "Preventa Salta" in contactos
        contact = contactos["Preventa Salta"]
        assert contact.whatsapp_grupo or contact.telefono

    def test_whatsapp_enviar_como_is_imagen(self):
        cfg = load_report_config(CONFIG_PATH)
        assert cfg.filtros.whatsapp_enviar_como == "imagen"

    def test_whatsapp_stays_globally_disabled_until_manual_verification(self):
        """RF: adding Preventa Salta prepares the wiring but must NOT enable
        actual WhatsApp delivery yet — that is a deliberate manual gate."""
        cfg = load_report_config(CONFIG_PATH)
        assert cfg.filtros.enviar_whatsapp is False


class TestAvancesBadieEmailSettingsUnchanged:
    """Regression guard: email delivery settings must survive PR4 untouched."""

    def test_enviar_email_still_true(self):
        cfg = load_report_config(CONFIG_PATH)
        assert cfg.filtros.enviar_email is True

    def test_email_adjuntos_still_only_excel(self):
        cfg = load_report_config(CONFIG_PATH)
        assert cfg.filtros.email_adjuntos == ["excel"]

    def test_existing_email_recipients_still_present(self):
        cfg = load_report_config(CONFIG_PATH)
        report = cfg.reportes[0]
        for name in [
            "Sebastian Dellamea", "Gonzalo Farah", "Veronica Chapur",
            "Facundo Guantay", "Gustavo Flores",
        ]:
            assert name in report.enviar_a
            assert report.enviar_a[name].via == ["email"]
        assert report.enviar_a["Nahuel Aguirre"].via == ["email_cc"]

    def test_asunto_email_unchanged(self):
        cfg = load_report_config(CONFIG_PATH)
        report = cfg.reportes[0]
        assert report.asunto_email == "AVANCE BADIE - JULIO 2026"
