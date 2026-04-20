"""Integration tests for --test-mode / INFORMES_TEST_MODE CLI wiring in main.py.

Tests _resolve_test_mode() helper, the --test-mode argparse flag, the banner,
parameter threading through _run_reportes / _run_report_config / _run_config_dir,
and the legacy-path warning.
"""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# T1-T5: _resolve_test_mode() helper
# ---------------------------------------------------------------------------


class TestResolveTestModeHelper:
    def test_resolve_test_mode_cli_only(self, monkeypatch):
        """cli_flag=True + env unset -> True."""
        monkeypatch.delenv("INFORMES_TEST_MODE", raising=False)
        from main import _resolve_test_mode

        assert _resolve_test_mode(cli_flag=True) is True

    def test_resolve_test_mode_env_only(self, monkeypatch):
        """cli_flag=False + INFORMES_TEST_MODE=1 -> True."""
        monkeypatch.setenv("INFORMES_TEST_MODE", "1")
        from main import _resolve_test_mode

        assert _resolve_test_mode(cli_flag=False) is True

    def test_resolve_test_mode_both(self, monkeypatch):
        """cli_flag=True + INFORMES_TEST_MODE=1 -> True."""
        monkeypatch.setenv("INFORMES_TEST_MODE", "1")
        from main import _resolve_test_mode

        assert _resolve_test_mode(cli_flag=True) is True

    def test_resolve_test_mode_neither(self, monkeypatch):
        """cli_flag=False + env unset -> False."""
        monkeypatch.delenv("INFORMES_TEST_MODE", raising=False)
        from main import _resolve_test_mode

        assert _resolve_test_mode(cli_flag=False) is False

    def test_resolve_test_mode_env_not_1_is_false(self, monkeypatch):
        """Only literal '1' activates; '0', 'true', 'yes' all return False."""
        from main import _resolve_test_mode

        for bad_value in ("0", "true", "yes", "True", "YES", "on"):
            monkeypatch.setenv("INFORMES_TEST_MODE", bad_value)
            assert _resolve_test_mode(cli_flag=False) is False, (
                f"Expected False for INFORMES_TEST_MODE={bad_value!r}"
            )


# ---------------------------------------------------------------------------
# T6-T7: Banner output
# ---------------------------------------------------------------------------


class TestBanner:
    def _call_main_with_test_mode(self, args_list, capsys, monkeypatch):
        """Helper: invoke main() with a controlled arg list."""
        # Patch sys.argv and stub out the heavy config loading so we don't
        # actually hit disk or DB.
        import sys

        monkeypatch.setattr(sys, "argv", ["main.py"] + args_list)
        # Prevent real execution after banner by making config/config-dir missing
        # We just need to observe the banner, then main() can fail with sys.exit.
        from main import main

        try:
            main()
        except SystemExit:
            pass

    def test_banner_printed_when_active(self, capsys, monkeypatch):
        """--test-mode -> stdout contains '[TEST MODE ACTIVO]'."""
        import sys

        monkeypatch.setattr(sys, "argv", ["main.py", "--test-mode", "--config", "/nonexistent/path.json"])
        monkeypatch.delenv("INFORMES_TEST_MODE", raising=False)

        from main import main

        try:
            main()
        except (SystemExit, Exception):
            pass

        captured = capsys.readouterr()
        assert "[TEST MODE ACTIVO]" in captured.out

    def test_banner_not_printed_when_inactive(self, capsys, monkeypatch):
        """No --test-mode + INFORMES_TEST_MODE unset -> no banner in stdout."""
        import sys

        monkeypatch.setattr(sys, "argv", ["main.py", "--config", "/nonexistent/path.json"])
        monkeypatch.delenv("INFORMES_TEST_MODE", raising=False)

        from main import main

        try:
            main()
        except (SystemExit, Exception):
            pass

        captured = capsys.readouterr()
        assert "[TEST MODE ACTIVO]" not in captured.out


# ---------------------------------------------------------------------------
# T8: test_mode propagates to resolve_delivery
# ---------------------------------------------------------------------------


class TestTestModePropagation:
    def test_test_mode_propagates_to_resolve_delivery(self, monkeypatch):
        """_run_reportes called with test_mode=True passes test_mode=True to resolve_delivery."""
        from src.config.models import GlobalFilters, ReportConfig, ReportEntry

        # Build a minimal valid ReportConfig using real objects so spec-mocks don't
        # block attribute access inside the function.
        report_config = MagicMock()
        report_config.tipo = "ventas"
        report_config.filtros = GlobalFilters(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
        )
        report_entry = MagicMock()
        report_entry.nombre = "Test Ventas"
        report_entry.filtros = None
        report_entry.enviar_a = {"Walter Vilte": MagicMock()}
        report_entry.capture_image = None
        report_entry.capture_images = None
        report_config.reportes = [report_entry]

        resolve_delivery_calls = []

        def fake_resolve_delivery(report, contactos, **kwargs):
            resolve_delivery_calls.append(kwargs)
            return None  # no delivery, pipeline skipped

        def fake_merge_filters(global_f, report_f):
            return {
                "fecha_desde": "2026-01-01",
                "fecha_hasta": "2026-01-31",
                "genericos": None,
                "con_slicers": False,
                "con_cobertura": False,
                "enviar_email": True,
                "enviar_whatsapp": True,
                "supervisores": None,
                "sucursales": None,
            }

        def fake_run_ventas_report(report, merged):
            return [(MagicMock(), {})]

        import main as main_module

        monkeypatch.setattr(main_module, "_run_ventas_report", fake_run_ventas_report)

        # _run_reportes does `from src.config.resolver import merge_filters, resolve_delivery`
        # inside the function — patch both at the source module so the local import binds
        # to our fakes.
        import src.config.resolver as resolver_module

        monkeypatch.setattr(resolver_module, "resolve_delivery", fake_resolve_delivery)
        monkeypatch.setattr(resolver_module, "merge_filters", fake_merge_filters)

        from main import _run_reportes
        _run_reportes(report_config, contactos={}, test_mode=True)

        assert len(resolve_delivery_calls) == 1
        assert resolve_delivery_calls[0].get("test_mode") is True


# ---------------------------------------------------------------------------
# T9: Legacy flow emits WARNING and continues
# ---------------------------------------------------------------------------


class TestLegacyWarning:
    def test_legacy_flow_emits_warning_and_continues(self, caplog):
        """_cmd_ventas_legacy with test_mode=True logs WARNING about legacy path."""
        from main import _cmd_ventas_legacy

        args = MagicMock()
        args.desde = "2026-01-01"
        args.hasta = "2026-01-31"
        args.genericos = None
        args.output = None
        args.slicers = False

        cfg = {}

        # Stub out VentasService so no real DB call happens
        mock_result = MagicMock()
        mock_result.ruta_archivo = "/tmp/test.xlsx"
        mock_result.hojas = ["Ventas Bultos"]
        mock_result.registros_ventas = 0
        mock_result.registros_procesados = 0
        mock_result.sucursales = []
        mock_result.genericos_incluidos = []
        mock_result.slicers_agregados = False

        with patch("main.VentasService") as MockVentasService, \
             patch("main._ejecutar_pipeline"), \
             caplog.at_level(logging.WARNING, logger="main"):
            mock_service_instance = MockVentasService.return_value
            mock_service_instance.generar_reporte.return_value = mock_result

            result = _cmd_ventas_legacy(args, cfg, test_mode=True)

        # Must not raise, must return 0
        assert result == 0

        # Must have a WARNING about test_mode + legacy
        warning_texts = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "test" in m.lower() and ("legacy" in m.lower() or "efecto" in m.lower())
            for m in warning_texts
        ), f"Expected test_mode/legacy warning, got: {warning_texts}"

    def test_resumen_legacy_flow_emits_warning_and_continues(self, caplog):
        """_cmd_resumen_legacy with test_mode=True logs WARNING about legacy path."""
        from main import _cmd_resumen_legacy

        args = MagicMock()
        args.desde = "2026-01-01"
        args.hasta = "2026-01-31"
        args.genericos = None
        args.output = None

        cfg = {"con_objetivo": False}

        mock_result = MagicMock()
        mock_result.ruta_archivo = "/tmp/resumen.xlsx"
        mock_result.hojas = ["Resumen"]
        mock_result.registros_procesados = 0
        mock_result.sucursales = []
        mock_result.genericos_incluidos = []

        with patch("main.ResumenMensualService") as MockResumenService, \
             patch("main._ejecutar_pipeline"), \
             caplog.at_level(logging.WARNING, logger="main"):
            mock_service_instance = MockResumenService.return_value
            mock_service_instance.generar_reporte.return_value = mock_result

            result = _cmd_resumen_legacy(args, cfg, test_mode=True)

        assert result == 0

        warning_texts = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "test" in m.lower() and ("legacy" in m.lower() or "efecto" in m.lower())
            for m in warning_texts
        ), f"Expected test_mode/legacy warning, got: {warning_texts}"
