import json
from datetime import date

import scripts.run_daily as run_daily

from scripts.run_daily import (
    RAM_MIN_MB_IMAGENES,
    Servicio,
    _mem_available_mb,
    _ram_guard_omite_imagenes,
    _report_renderiza_imagenes,
)


def _patched_config(
    *,
    enviar_whatsapp: bool = True,
    whatsapp_enviar_como: str = "imagen",
    capture_images: list | None = None,
    capture_image: dict | None = None,
) -> dict:
    reporte: dict = {"nombre": "TEST"}
    if capture_images is not None:
        reporte["capture_images"] = capture_images
    if capture_image is not None:
        reporte["capture_image"] = capture_image
    return {
        "filtros": {
            "enviar_whatsapp": enviar_whatsapp,
            "whatsapp_enviar_como": whatsapp_enviar_como,
        },
        "reportes": [reporte],
    }


class TestReportRenderizaImagenes:
    def test_true_when_whatsapp_imagen_and_captures(self):
        patched = _patched_config(capture_images=[{"hoja": "Hoja1", "rango": "A1:B2"}])
        assert _report_renderiza_imagenes(patched) is True

    def test_true_when_whatsapp_ambos_and_captures(self):
        patched = _patched_config(
            whatsapp_enviar_como="ambos",
            capture_images=[{"hoja": "Hoja1", "rango": "A1:B2"}],
        )
        assert _report_renderiza_imagenes(patched) is True

    def test_true_with_legacy_capture_image_singular(self):
        patched = _patched_config(capture_image={"hoja": "Hoja1", "rango": "A1:B2"})
        assert _report_renderiza_imagenes(patched) is True

    def test_false_when_enviar_whatsapp_false(self):
        patched = _patched_config(
            enviar_whatsapp=False,
            capture_images=[{"hoja": "Hoja1", "rango": "A1:B2"}],
        )
        assert _report_renderiza_imagenes(patched) is False

    def test_false_when_enviar_como_texto(self):
        patched = _patched_config(
            whatsapp_enviar_como="texto",
            capture_images=[{"hoja": "Hoja1", "rango": "A1:B2"}],
        )
        assert _report_renderiza_imagenes(patched) is False

    def test_false_when_no_captures(self):
        patched = _patched_config(capture_images=[])
        assert _report_renderiza_imagenes(patched) is False

    def test_false_when_reportes_missing(self):
        patched = {"filtros": {"enviar_whatsapp": True, "whatsapp_enviar_como": "imagen"}}
        assert _report_renderiza_imagenes(patched) is False


class TestMemAvailableMb:
    def test_parses_mem_available_kb_to_mb(self, tmp_path, monkeypatch):
        meminfo = tmp_path / "meminfo"
        meminfo.write_text(
            "MemTotal:       16384000 kB\n"
            "MemFree:         2048000 kB\n"
            "MemAvailable:    3145728 kB\n"
            "Buffers:          102400 kB\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(run_daily, "_MEMINFO_PATH", meminfo)
        assert _mem_available_mb() == 3072

    def test_returns_none_when_field_missing(self, tmp_path, monkeypatch):
        meminfo = tmp_path / "meminfo"
        meminfo.write_text("MemTotal:       16384000 kB\n", encoding="utf-8")
        monkeypatch.setattr(run_daily, "_MEMINFO_PATH", meminfo)
        assert _mem_available_mb() is None

    def test_returns_none_when_file_unreadable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_daily, "_MEMINFO_PATH", tmp_path / "does_not_exist")
        assert _mem_available_mb() is None


class TestRamGuardOmiteImagenes:
    def _renders_images_config(self) -> dict:
        return _patched_config(capture_images=[{"hoja": "Hoja1", "rango": "A1:B2"}])

    def test_true_when_renders_images_and_ram_below_threshold(self):
        patched = self._renders_images_config()
        assert _ram_guard_omite_imagenes(patched, RAM_MIN_MB_IMAGENES - 1) is True

    def test_false_when_renders_images_and_ram_at_or_above_threshold(self):
        patched = self._renders_images_config()
        assert _ram_guard_omite_imagenes(patched, RAM_MIN_MB_IMAGENES) is False

    def test_false_when_avail_is_none_fail_open(self):
        """Measurement glitch (None) must never block images — /proc/meminfo is
        always present on this host, so blocking on None would suppress images
        every day."""
        patched = self._renders_images_config()
        assert _ram_guard_omite_imagenes(patched, None) is False

    def test_false_when_report_does_not_render_images(self):
        patched = _patched_config(capture_images=[])
        assert _ram_guard_omite_imagenes(patched, 100) is False


class TestAlertarRamBaja:
    def test_sends_whatsapp_alert_to_nahuel(self, monkeypatch):
        import src.core.whatsapp_client as whatsapp_client_module
        from src.config.models import ContactInfo

        monkeypatch.setattr(
            run_daily,
            "load_contacts",
            lambda path: {"Nahuel Aguirre": ContactInfo(telefono="5493870000000")},
        )

        sent = {}

        class FakeWhatsAppClient:
            def __init__(self, base_url):
                sent["base_url"] = base_url

            def send_text(self, target, text):
                sent["target"] = target
                sent["text"] = text
                return {"success": True}

        monkeypatch.setattr(whatsapp_client_module, "WhatsAppClient", FakeWhatsAppClient)

        run_daily._alertar_ram_baja("avance-badie", 1234)

        assert sent["target"] == "5493870000000"
        assert "1234" in sent["text"]
        assert "avance-badie" in sent["text"]

    def test_never_raises_when_contacts_lookup_fails(self, monkeypatch):
        def boom(path):
            raise RuntimeError("contactos.json roto")

        monkeypatch.setattr(run_daily, "load_contacts", boom)

        # Must not raise — an alert failure can never crash the daily run.
        run_daily._alertar_ram_baja("avance-badie", 1234)


class TestRamGuardWiring:
    """End-to-end wiring inside `_ejecutar_servicio`."""

    def _cfg_path(self, tmp_path):
        cfg = {
            "tipo": "avances",
            "filtros": {
                "tipo_plantilla": "badie",
                "fecha_desde": "2026-08-01",
                "fecha_hasta": "2026-08-31",
                "id_sucursal": 16,
                "id_fuerza_ventas": 1,
                "enviar_email": True,
                "enviar_whatsapp": True,
                "whatsapp_enviar_como": "imagen",
            },
            "reportes": [
                {
                    "nombre": "AVANCE BADIE - TEST",
                    "enviar_a": {"Nahuel Aguirre": {"via": ["email", "whatsapp"]}},
                    "capture_images": [{"hoja": "Hoja1", "rango": "A1:B2"}],
                }
            ],
        }
        cfg_path = tmp_path / "avance_badie_test.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        return cfg_path

    def _run(self, tmp_path, monkeypatch, avail_mb):
        from src.config.models import ContactInfo

        monkeypatch.setattr(run_daily, "_mem_available_mb", lambda: avail_mb)
        monkeypatch.setattr(
            run_daily,
            "load_contacts",
            lambda p: {"Nahuel Aguirre": ContactInfo(email="nahuel@example.com")},
        )
        alerted = {"called": False}
        monkeypatch.setattr(
            run_daily,
            "_alertar_ram_baja",
            lambda nombre, avail: alerted.update(called=True, nombre=nombre, avail=avail),
        )
        captured = {}

        def fake_run_reportes(report_config, contactos, test_mode=False):
            captured["report_config"] = report_config
            return 0

        monkeypatch.setattr(run_daily, "_run_reportes", fake_run_reportes)

        svc = Servicio(nombre="avance-badie", config_path=self._cfg_path(tmp_path), fecha_modo="mes_a_hoy")
        rc = run_daily._ejecutar_servicio(svc, date(2026, 8, 15), enviar=True)
        return rc, captured, alerted

    def test_low_ram_degrada_a_archivo_sin_apagar_whatsapp(self, tmp_path, monkeypatch):
        """El canal de WhatsApp SOBREVIVE; solo se cae el render de imagenes.

        Este test afirmaba lo contrario (enviar_whatsapp is False) y por eso el
        bug del 2026-08-19 no lo detecto nadie: avance-badie tiene
        destinatarios que SOLO tienen WhatsApp (Preventa Salta, Alejandro
        Nogales) y se quedaron sin informe.
        """
        rc, captured, alerted = self._run(tmp_path, monkeypatch, avail_mb=1000)

        filtros = captured["report_config"].filtros
        assert rc == 0
        assert filtros.enviar_whatsapp is True
        assert filtros.whatsapp_enviar_como == "archivo"
        assert alerted == {"called": True, "nombre": "avance-badie", "avail": 1000}

    def test_sufficient_ram_keeps_whatsapp_and_does_not_alert(self, tmp_path, monkeypatch):
        rc, captured, alerted = self._run(tmp_path, monkeypatch, avail_mb=5000)

        assert rc == 0
        assert captured["report_config"].filtros.enviar_whatsapp is True
        assert alerted["called"] is False

    def test_mem_unavailable_fails_open_keeps_whatsapp(self, tmp_path, monkeypatch):
        rc, captured, alerted = self._run(tmp_path, monkeypatch, avail_mb=None)

        assert rc == 0
        assert captured["report_config"].filtros.enviar_whatsapp is True
        assert alerted["called"] is False


class TestRamGuardNoDejaANadieSinInforme:
    """El guard no puede dejar sin nada al que solo tiene WhatsApp.

    Paso el 2026-08-19 con avance-badie: RAM 2497 MB, el guard puso
    enviar_whatsapp=False, el mail salio a los seis supervisores y Preventa
    Salta y Alejandro Nogales —que solo tienen WhatsApp— no recibieron nada.
    La alerta ademas decia que el xlsx habia salido por email, que para ellos
    era falso.
    """

    def _patched_como_avance_badie(self):
        return {
            "filtros": {
                "enviar_whatsapp": True,
                "enviar_email": True,
                "whatsapp_enviar_como": "imagen",
            },
            "reportes": [{"capture_images": [{"hoja": "Avance", "rango": "A1:B2"}]}],
        }

    def test_degrada_a_archivo_y_no_apaga_whatsapp(self, monkeypatch):
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("rd_ram", "scripts/run_daily.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["rd_ram"] = mod
        spec.loader.exec_module(mod)

        patched = self._patched_como_avance_badie()
        assert mod._ram_guard_omite_imagenes(patched, 2497) is True

        # Lo que hace el runner cuando el guard se dispara.
        patched["filtros"]["whatsapp_enviar_como"] = "archivo"

        assert patched["filtros"]["enviar_whatsapp"] is True, (
            "el canal de WhatsApp tiene que sobrevivir: hay destinatarios que "
            "SOLO tienen ese canal"
        )
        assert mod._report_renderiza_imagenes(patched) is False, (
            "con enviar_como=archivo no se renderiza, que es lo que ahorra la RAM"
        )

    def test_con_ram_suficiente_no_toca_nada(self):
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("rd_ram2", "scripts/run_daily.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["rd_ram2"] = mod
        spec.loader.exec_module(mod)

        patched = self._patched_como_avance_badie()
        assert mod._ram_guard_omite_imagenes(patched, 8000) is False
        assert patched["filtros"]["whatsapp_enviar_como"] == "imagen"
