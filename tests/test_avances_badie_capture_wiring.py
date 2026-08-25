"""Wiring tests for configs/avances_badie.json — capturas por SECCION.

Cada hoja se captura con rangos FIJOS. `auto:bordes` no sirve en ninguna de
las tres, verificado corriendo RangeRecognizer contra el workbook real
(2026-08-17):

- "Avance": detecta 3 bloques y se COME el primero (la banda de GFLORES,
  A1:AR18). Ademas corta en la fila 57 y la hoja tiene datos hasta la 61.
- "Cober Nueva": detecta 8 bloques irregulares que dejan afuera Cervezas 2,
  Sidras y todos los totales. Los bordes de la hoja estan fragmentados.
- "Multicategoria": devuelve celdas sueltas (K6:V6, M52:M54, ...), no la tabla.

El corte de "Cober Nueva" es por BLOQUE TEMATICO (columnas), no por
supervisor: cada bloque abarca las cuatro bandas de filas (2:55).

El corte sigue lo VISIBLE, no la estructura logica de la hoja: "Cober Nueva"
tiene 56 columnas ocultas y LibreOffice no imprime lo oculto. Verificado
renderizando (2026-08-17):

- Cervezas 1 (A:R)   18 col,  0 ocultas.
- Cervezas 2 (T:AW)  30 col, 22 ocultas -> solo SCHNEIDER y TOTAL CERVEZAS.
  T y U (su Vendedor/Supervisor) tambien estan ocultas, asi que capturado por
  separado sale sin identificar las filas. Por eso va UNIDO a Cervezas 1 en
  A2:AW55, que aporta las columnas A/B visibles.
- Aguas (AY:BX)      26 col,  0 ocultas.
- Vinos CCU (BZ:CW)  24 col, 24 ocultas -> el bloque entero esta oculto y
  produce un PNG A4 en blanco. NO se captura; sus totales salen igual en el
  bloque Multi CCU. Confirmado con Nahuel: esta oculto a proposito.
- Multi CCU (CY:EB)  30 col,  9 ocultas (DA-DI); CY/CZ visibles.
"""
from pathlib import Path

from src.config.resolver import load_contacts, load_report_config

CONFIG_PATH = Path("configs/avances_badie.json")
CONTACTS_PATH = Path("configs/contactos.json")

# Ground truth verificado contra el workbook real: limites de cada bloque y
# ultima fila/columna con contenido de cada hoja.
FILA_DESDE, FILA_HASTA = 2, 55

COBER_NUEVA_BLOQUES = [
    ("Cervezas", "A", "AW"),   # bloques 1 y 2 juntos: T/U estan ocultas
    ("Aguas", "AY", "BX"),
    ("Multi CCU", "CY", "EB"),
]

# Columnas ocultas verificadas contra el workbook: capturar un rango contenido
# aca entero da una imagen en blanco.
BLOQUE_OCULTO_VINOS_CCU = ("BZ", "CW")

AVANCE_RANGO = "A1:AR61"
MULTICATEGORIA_RANGO = "A1:Z57"


def _bloques_cober_nueva_esperados():
    """[(rango, caption), ...] en el orden en que deben salir las imagenes."""
    return [
        (f"{ini}{FILA_DESDE}:{fin}{FILA_HASTA}", f"Cober Nueva - {nombre}")
        for nombre, ini, fin in COBER_NUEVA_BLOQUES
    ]


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

    def test_cinco_capturas_configuradas(self):
        # 1 Avance + 3 Cober Nueva (un bloque visible cada una) + 1 Multicategoria
        assert len(self._captures()) == 5

    def test_all_captures_use_libreoffice_renderer(self):
        assert all(c.renderer == "libreoffice" for c in self._captures())

    def test_ninguna_captura_usa_auto_bordes(self):
        """auto:bordes esta descartado en las tres hojas — ver docstring."""
        assert all(c.rango != "auto:bordes" for c in self._captures())

    def test_avance_es_una_sola_imagen_que_llega_hasta_la_fila_61(self):
        avance = [c for c in self._captures() if c.hoja == "Avance"]
        assert len(avance) == 1
        assert avance[0].rango == AVANCE_RANGO

    def test_cober_nueva_tiene_un_rango_por_bloque_tematico(self):
        cober = [c for c in self._captures() if c.hoja == "Cober Nueva"]
        assert len(cober) == len(COBER_NUEVA_BLOQUES)
        assert all(c.recortar is True for c in cober)
        assert [(c.rango, c.caption) for c in cober] == _bloques_cober_nueva_esperados()

    def test_cada_bloque_cober_nueva_abarca_las_cuatro_bandas_de_filas(self):
        """Las bandas por supervisor (2-17, 19-32, 34-47) y el resumen (49-55)
        entran todas en la misma imagen: el corte es por columna, no por fila."""
        cober = [c for c in self._captures() if c.hoja == "Cober Nueva"]
        for c in cober:
            ini, fin = c.rango.split(":")
            assert ini.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") == str(FILA_DESDE)
            assert fin.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") == str(FILA_HASTA)

    def test_el_bloque_multi_ccu_llega_hasta_EB_para_no_perder_el_total(self):
        """La columna TOTAL MULTI CCU vive en DY:EB. El corte anterior
        terminaba en DV y la dejaba afuera de toda imagen."""
        cober = [c for c in self._captures() if c.hoja == "Cober Nueva"]
        multi = [c for c in cober if c.caption == "Cober Nueva - Multi CCU"]
        assert len(multi) == 1
        assert multi[0].rango.endswith("EB55")

    def test_no_se_captura_el_bloque_de_vinos_ccu_que_esta_oculto(self):
        """BZ:CW tiene sus 24 columnas ocultas: un rango que empiece ahi
        produce un PNG en blanco. Guard contra reintroducirlo."""
        ini, _ = BLOQUE_OCULTO_VINOS_CCU
        cober = [c for c in self._captures() if c.hoja == "Cober Nueva"]
        assert not any(c.rango.startswith(ini) for c in cober)

    def test_cervezas_arranca_en_A_para_llevarse_vendedor_y_supervisor(self):
        """T y U estan ocultas, asi que el bloque de Cervezas 2 solo queda
        identificado si el rango arranca en A (columnas A/B visibles)."""
        cober = [c for c in self._captures() if c.hoja == "Cober Nueva"]
        cerv = [c for c in cober if c.caption == "Cober Nueva - Cervezas"]
        assert len(cerv) == 1
        assert cerv[0].rango.startswith("A2:")

    def test_multicategoria_llega_hasta_la_columna_Z(self):
        """La hoja tiene contenido hasta Z57; el corte anterior (A1:V57)
        perdia las columnas W a Z."""
        multi = [c for c in self._captures() if c.hoja == "Multicategoria"]
        assert len(multi) == 1
        assert multi[0].rango == MULTICATEGORIA_RANGO
        assert multi[0].recortar is True

    def test_captions_son_unicos_y_no_vacios(self):
        caps = [c.caption for c in self._captures() if c.caption]
        assert len(caps) == len(set(caps))
        assert all(c.strip() for c in caps)


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


class TestAvancesBadieEmailSettingsUnchanged:
    """Regression guard: la entrega por email no se toca al cambiar capturas."""

    def test_enviar_email_still_true(self):
        cfg = load_report_config(CONFIG_PATH)
        assert cfg.filtros.enviar_email is True

    def test_email_adjuntos_still_only_excel(self):
        cfg = load_report_config(CONFIG_PATH)
        assert cfg.filtros.email_adjuntos == ["excel"]

    def test_asunto_email_usa_placeholders_y_no_un_mes_fijo(self):
        """El asunto se resuelve con `_resolver_nombre_periodo` (main.py:243).
        Escrito a mano queda congelado: el 2026-08-20 el mail seguia saliendo
        con asunto 'AVANCE BADIE - JULIO 2026'."""
        cfg = load_report_config(CONFIG_PATH)
        asunto = cfg.reportes[0].asunto_email
        assert "{MES}" in asunto and "{AÑO}" in asunto
        meses = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
                 "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
        assert not any(m in asunto.upper() for m in meses), (
            f"el asunto tiene un mes fijo: {asunto!r}"
        )

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
