"""Tests for the `solo_con_cargo` option of the historico-cliente report.

When enabled, the report must count only billed units (`cantidades_con_cargo`),
leaving out 100%-discount lines (gifts). Verified against the whole fact table:
`cantidades_con_cargo + cantidades_sin_cargo = cantidades_total` always, and
`bonificacion >= 100` is equivalent to `cantidades_con_cargo = 0`.
"""
from unittest.mock import MagicMock, patch

import pandas as pd

from src.core.data_loader import DataLoader
from src.services.historico_cliente import (
    HistoricoClienteConfig,
    HistoricoClienteService,
)


def _captured_sql(**kwargs) -> str:
    """Run the loader query with execute_query stubbed, return the emitted SQL."""
    loader = DataLoader.__new__(DataLoader)  # no DB connection needed
    captured = {}

    def _fake(query, params=None):
        captured["sql"] = query
        return pd.DataFrame()

    loader.execute_query = _fake
    loader.get_ventas_historico_cliente(
        fecha_desde="2026-01-01",
        fecha_hasta="2026-01-31",
        clientes=[{"id_cliente": 8564, "id_sucursal": 1}],
        agrupar_por_generico=True,
        **kwargs,
    )
    return captured["sql"]


def test_solo_con_cargo_suma_cantidades_con_cargo():
    """With the flag on, the SUM is over cantidades_con_cargo, not the total."""
    sql = _captured_sql(solo_con_cargo=True)
    assert "SUM(fv.cantidades_con_cargo)" in sql
    assert "SUM(fv.cantidades_total)" not in sql


def test_por_defecto_suma_el_total():
    """Default stays backward compatible: gifts included."""
    sql = _captured_sql()
    assert "SUM(fv.cantidades_total)" in sql
    assert "SUM(fv.cantidades_con_cargo)" not in sql


def test_service_propaga_el_flag_al_loader(tmp_path):
    """The service forwards its config flag to the data loader."""
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_historico_cliente.return_value = pd.DataFrame({
        "id_cliente": [8564], "id_sucursal": [1], "nombre_cliente": ["F5"],
        "generico": ["CERVEZAS"], "row_key": ["SALTA"],
        "mes": ["2026-01"], "bultos": [10.0],
    })

    service = HistoricoClienteService(data_loader=loader)
    config = HistoricoClienteConfig(
        fecha_desde="2026-01-01",
        fecha_hasta="2026-01-31",
        clientes=[{"id_cliente": 8564, "id_sucursal": 1}],
        agrupar_por_generico=True,
        solo_con_cargo=True,
        nombre_archivo="Test",
    )

    with patch("src.services.historico_cliente.service.service_output_dir", return_value=tmp_path):
        service.generar_reporte(config)

    assert loader.get_ventas_historico_cliente.call_args.kwargs["solo_con_cargo"] is True


def test_merge_filters_propaga_el_flag_del_reporte():
    """Regression: the flag must survive merge_filters.

    Adding the field to ReportFilters is not enough — merge_filters copies each
    per-report key explicitly, so a missing branch there silently drops it and
    the report comes out with gifts included.
    """
    from src.config.models import GlobalFilters, ReportFilters
    from src.config.resolver import merge_filters

    global_f = GlobalFilters(fecha_desde="2026-01-01", fecha_hasta="2026-01-31")

    assert merge_filters(global_f, ReportFilters(solo_con_cargo=True))["solo_con_cargo"] is True
    assert merge_filters(global_f, ReportFilters())["solo_con_cargo"] is False
    assert merge_filters(global_f, None)["solo_con_cargo"] is False
