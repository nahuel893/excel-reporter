"""
Test for T-10: main.py wiring of detalle_movimientos_path.

Verifies that _run_resumen_report passes detalle_movimientos_path from
the merged dict to the ResumenMensualConfig.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call


class TestMainResumenDetalleMovimientosWiring:
    """T-10: _run_resumen_report passes detalle_movimientos_path to config."""

    def test_main_passes_detalle_movimientos_path_to_config(self):
        """T-10: When merged dict has detalle_movimientos_path, ResumenMensualConfig gets the same value."""
        from main import _run_resumen_report
        from src.services.resumen_mensual import ResumenMensualConfig

        report = MagicMock()
        report.nombre = "Test Report"

        merged = {
            "fecha_desde": "2026-04-01",
            "fecha_hasta": "2026-04-30",
            "genericos": ["CERVEZAS"],
            "detalle_movimientos_path": "/path/to/detalle.xlsx",
        }

        captured_config = {}

        def fake_generar_reporte(config):
            captured_config["config"] = config
            result = MagicMock()
            result.ruta_archivo = Path("/tmp/test.xlsx")
            result.hojas = ["CERVEZAS"]
            result.registros_procesados = 10
            result.sucursales = 2
            result.genericos_incluidos = ["CERVEZAS"]
            return result

        with patch("main.ResumenMensualService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.generar_reporte.side_effect = fake_generar_reporte
            mock_svc_cls.return_value = mock_svc

            _run_resumen_report(report, merged)

        assert "config" in captured_config
        config = captured_config["config"]
        assert isinstance(config, ResumenMensualConfig)
        assert config.detalle_movimientos_path == "/path/to/detalle.xlsx"

    def test_main_passes_none_when_detalle_movimientos_path_absent(self):
        """T-10: When merged dict has no detalle_movimientos_path, config gets None."""
        from main import _run_resumen_report
        from src.services.resumen_mensual import ResumenMensualConfig

        report = MagicMock()
        report.nombre = "Test Report"

        merged = {
            "fecha_desde": "2026-04-01",
            "fecha_hasta": "2026-04-30",
            "genericos": None,
            # no detalle_movimientos_path key
        }

        captured_config = {}

        def fake_generar_reporte(config):
            captured_config["config"] = config
            result = MagicMock()
            result.ruta_archivo = Path("/tmp/test.xlsx")
            result.hojas = []
            result.registros_procesados = 0
            result.sucursales = 0
            result.genericos_incluidos = []
            return result

        with patch("main.ResumenMensualService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.generar_reporte.side_effect = fake_generar_reporte
            mock_svc_cls.return_value = mock_svc

            _run_resumen_report(report, merged)

        config = captured_config["config"]
        assert config.detalle_movimientos_path is None
