"""Tests for the SUB DISTRIBUIDORES sheet query (Adrian Garcia ventas report).

The sheet must break down sales by individual subdistributor, exposing the
client's ``razon_social`` and ``fantasia`` — not only the origin sucursal.
"""
from unittest.mock import MagicMock

import pandas as pd

from src.core.data_loader import DataLoader


def _call_and_capture(**overrides):
    """Invoke get_ventas_subdistribuidores_sheet with execute_query mocked.

    Returns the captured SQL string (lower-cased) and params dict.
    """
    loader = DataLoader()
    captured: dict = {}

    def fake_execute(query, params=None):
        captured["query"] = query
        captured["params"] = params
        return pd.DataFrame(
            columns=["origen", "razon_social", "fantasia", "generico", "marca", "bultos", "htls"]
        )

    loader.execute_query = MagicMock(side_effect=fake_execute)

    kwargs = dict(
        fecha_desde="2026-06-01",
        fecha_hasta="2026-06-30",
        sucursales_interior=["SUCURSAL METAN"],
        genericos=["CERVEZAS"],
    )
    kwargs.update(overrides)
    loader.get_ventas_subdistribuidores_sheet(**kwargs)
    return captured["query"].lower(), captured["params"]


def test_query_selects_razon_social_and_fantasia():
    """The SELECT clause exposes the subdistributor's razon_social and fantasia."""
    sql, _ = _call_and_capture()
    select_clause = sql.split("from", 1)[0]
    assert "razon_social" in select_clause
    assert "fantasia" in select_clause


def test_query_groups_by_razon_social_and_fantasia():
    """The names participate in GROUP BY so each subdistributor keeps its own rows."""
    sql, _ = _call_and_capture()
    group_by_clause = sql.split("group by", 1)[1]
    assert "razon_social" in group_by_clause
    assert "fantasia" in group_by_clause


def test_query_still_filters_by_generico_and_period():
    """Existing contract preserved: generico filter + period params still present."""
    sql, params = _call_and_capture()
    assert "da.generico in" in sql
    assert params["fecha_desde"] == "2026-06-01"
    assert params["fecha_hasta"] == "2026-06-30"
    assert params["gen_0"] == "CERVEZAS"
