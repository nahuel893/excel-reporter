"""Tests for DataLoader.get_ventas_diarias_articulo and get_articulo_descripcion."""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch


class TestGetVentasDiariasArticulo:
    def test_get_ventas_diarias_articulo_sql_shape(self):
        """execute_query is called with correct SQL and params."""
        from src.core.data_loader import DataLoader

        loader = DataLoader(engine=MagicMock())
        captured_calls = []

        def fake_execute_query(query, params=None):
            captured_calls.append({"query": query, "params": params})
            return pd.DataFrame(columns=["fecha_comprobante", "bultos"])

        loader.execute_query = fake_execute_query

        loader.get_ventas_diarias_articulo(
            id_articulo=23179,
            id_sucursal=1,
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
        )

        assert len(captured_calls) == 1
        call = captured_calls[0]
        sql = call["query"]
        params = call["params"]

        assert "id_articulo = :id_articulo" in sql
        assert "id_sucursal = :id_sucursal" in sql
        assert "BETWEEN :desde AND :hasta" in sql
        assert "SUM(fv.cantidades_total)" in sql
        assert "GROUP BY fv.fecha_comprobante" in sql

        assert params["id_articulo"] == 23179
        assert params["id_sucursal"] == 1
        assert params["desde"] == "2026-04-01"
        assert params["hasta"] == "2026-04-30"


class TestGetArticuloDescripcion:
    def test_get_articulo_descripcion_returns_none_when_missing(self):
        """Returns None when execute_query returns empty DataFrame."""
        from src.core.data_loader import DataLoader

        loader = DataLoader(engine=MagicMock())
        loader.execute_query = lambda q, p=None: pd.DataFrame(columns=["des_articulo"])

        result = loader.get_articulo_descripcion(99999)
        assert result is None

    def test_get_articulo_descripcion_returns_string_when_found(self):
        """Returns the des_articulo string when a row is found."""
        from src.core.data_loader import DataLoader

        loader = DataLoader(engine=MagicMock())
        loader.execute_query = lambda q, p=None: pd.DataFrame(
            {"des_articulo": ["SCHNEIDER 710"]}
        )

        result = loader.get_articulo_descripcion(23179)
        assert result == "SCHNEIDER 710"
