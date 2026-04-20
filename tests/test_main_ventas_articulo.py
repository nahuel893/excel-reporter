"""Tests for CLI wiring of ventas-articulo subcommand in main.py."""

from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestCmdVentasArticuloRequiresConfig:
    def test_cmd_ventas_articulo_requires_config(self, capsys):
        """cmd_ventas_articulo with config=None returns 1 and prints error."""
        from main import cmd_ventas_articulo

        args = Namespace(config=None)
        result = cmd_ventas_articulo(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.out or "error" in captured.out.lower()


class TestCmdVentasArticuloDispatch:
    def test_cmd_ventas_articulo_dispatches_to_run_report_config(self, tmp_path):
        """cmd_ventas_articulo with a config path delegates to _run_report_config."""
        from main import cmd_ventas_articulo

        config_file = tmp_path / "test_config.json"
        config_file.write_text('{"tipo": "ventas-articulo", "filtros": {}, "reportes": []}')

        run_report_config_calls = []

        def fake_run_report_config(path, test_mode=False):
            run_report_config_calls.append({"path": path, "test_mode": test_mode})
            return 0

        import main as main_module

        with patch.object(main_module, "_run_report_config", side_effect=fake_run_report_config):
            args = Namespace(config=str(config_file))
            result = cmd_ventas_articulo(args)

        assert len(run_report_config_calls) == 1
        assert run_report_config_calls[0]["path"] == Path(str(config_file))
        assert result == 0


class TestRunReportesRoutesVentasArticulo:
    def test_run_reportes_routes_ventas_articulo_tipo(self):
        """_run_reportes with tipo='ventas-articulo' calls _run_ventas_articulo_report."""
        from src.config.models import GlobalFilters, ReportConfig, ReportEntry

        report_config = MagicMock()
        report_config.tipo = "ventas-articulo"
        report_config.filtros = GlobalFilters(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
            id_articulo=23179,
            id_sucursal=1,
        )
        report_entry = MagicMock()
        report_entry.nombre = "SCHNEIDER ABR"
        report_entry.filtros = None
        report_entry.enviar_a = None
        report_entry.capture_image = None
        report_entry.capture_images = None
        report_config.reportes = [report_entry]

        run_ventas_articulo_calls = []

        def fake_run_ventas_articulo_report(report, merged):
            run_ventas_articulo_calls.append(merged)
            return [(MagicMock(), {})]

        def fake_resolve_delivery(report, contactos, **kwargs):
            return None

        import main as main_module
        import src.config.resolver as resolver_module

        with patch.object(main_module, "_run_ventas_articulo_report", side_effect=fake_run_ventas_articulo_report), \
             patch.object(resolver_module, "resolve_delivery", side_effect=fake_resolve_delivery):
            from main import _run_reportes
            _run_reportes(report_config, contactos={})

        assert len(run_ventas_articulo_calls) == 1
        merged = run_ventas_articulo_calls[0]
        assert merged["id_articulo"] == 23179
        assert merged["id_sucursal"] == 1
