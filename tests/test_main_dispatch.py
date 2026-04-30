"""Safety-net dispatch tests for `_run_reportes`.

Parametrized across every registered report type. Each test mocks the
target handler function and verifies `_run_reportes` routes `tipo` to the
right `_run_X_report`. Protects the registry refactor: if someone breaks
dispatch, these fail before the behavior reaches a real service.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.config.models import GlobalFilters


DISPATCH_MATRIX = [
    ("ventas", "_run_ventas_report"),
    ("resumen-mensual", "_run_resumen_report"),
    ("champions-league", "_run_mision_report"),
    ("historico-fratelli", "_run_historico_fratelli_report"),
    ("stock-diario", "_run_stock_diario_report"),
    ("cartesiano", "_run_cartesiano_report"),
    ("avances", "_run_avances_report"),
    ("graficos-cobertura", "_run_graficos_cobertura_report"),
    ("ventas-articulo", "_run_ventas_articulo_report"),
    ("reporte-general-badie", "_run_reporte_general_badie_report"),
]


def _make_report_config(tipo: str):
    """Build a minimal MagicMock report_config with one report entry."""
    report_config = MagicMock()
    report_config.tipo = tipo
    report_config.filtros = GlobalFilters(
        fecha_desde="2026-04-01",
        fecha_hasta="2026-04-30",
    )
    report_entry = MagicMock()
    report_entry.nombre = f"TEST {tipo}"
    report_entry.filtros = None
    report_entry.enviar_a = None
    report_entry.capture_image = None
    report_entry.capture_images = None
    report_config.reportes = [report_entry]
    return report_config


@pytest.mark.parametrize("tipo,handler_name", DISPATCH_MATRIX)
def test_run_reportes_dispatches_tipo_to_handler(tipo, handler_name):
    import main as main_module
    import src.config.resolver as resolver_module

    calls = []

    def fake_handler(report, merged):
        calls.append((report, merged))
        return [(MagicMock(), {})]

    with patch.object(main_module, handler_name, side_effect=fake_handler), \
         patch.object(resolver_module, "resolve_delivery", return_value=None):
        from main import _run_reportes
        report_config = _make_report_config(tipo)
        result = _run_reportes(report_config, contactos={})

    assert result == 0, f"_run_reportes returned {result} for tipo={tipo}"
    assert len(calls) == 1, f"Handler {handler_name} not called exactly once for tipo={tipo}"


def test_run_reportes_unknown_tipo_returns_error(capsys):
    """Unknown tipo returns exit code 1 and prints error."""
    from main import _run_reportes

    report_config = _make_report_config("tipo-inexistente")
    result = _run_reportes(report_config, contactos={})

    assert result == 1
    captured = capsys.readouterr()
    assert "desconocido" in captured.out.lower()
