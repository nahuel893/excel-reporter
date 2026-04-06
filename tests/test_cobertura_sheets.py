"""Tests para las hojas de cobertura en el reporte de ventas."""
import pandas as pd
import pytest

from src.services.ventas.service import (
    _preparar_cobertura,
    _COB_GENERICO_COLUMNS,
    _COB_MARCA_COLUMNS,
)


class TestPrepararCobertura:
    def test_ordena_y_renombra_generico(self):
        df = pd.DataFrame({
            "sucursal": ["SUC B", "SUC A", "SUC A"],
            "generico": ["VINOS", "CERVEZAS", "AGUAS"],
            "clientes_compradores": [10, 20, 15],
        })
        result = _preparar_cobertura(df, ["sucursal", "generico"], _COB_GENERICO_COLUMNS)

        assert list(result.columns) == ["Sucursal", "Generico", "Clientes Compradores"]
        assert result.iloc[0]["Sucursal"] == "SUC A"
        assert result.iloc[0]["Generico"] == "AGUAS"
        assert result.iloc[2]["Sucursal"] == "SUC B"

    def test_ordena_y_renombra_marca(self):
        df = pd.DataFrame({
            "sucursal": ["SUC B", "SUC A"],
            "marca": ["QUILMES", "BRAHMA"],
            "clientes_compradores": [100, 200],
        })
        result = _preparar_cobertura(df, ["sucursal", "marca"], _COB_MARCA_COLUMNS)

        assert list(result.columns) == ["Sucursal", "Marca", "Clientes Compradores"]
        assert result.iloc[0]["Sucursal"] == "SUC A"
        assert result.iloc[0]["Marca"] == "BRAHMA"

    def test_none_input_returns_none(self):
        assert _preparar_cobertura(None, ["sucursal"], _COB_GENERICO_COLUMNS) is None

    def test_empty_dataframe_returns_none(self):
        df = pd.DataFrame(columns=["sucursal", "generico", "clientes_compradores"])
        assert _preparar_cobertura(df, ["sucursal", "generico"], _COB_GENERICO_COLUMNS) is None

    def test_preserves_all_rows(self):
        df = pd.DataFrame({
            "sucursal": ["A", "B", "C"],
            "generico": ["X", "Y", "Z"],
            "clientes_compradores": [1, 2, 3],
        })
        result = _preparar_cobertura(df, ["sucursal", "generico"], _COB_GENERICO_COLUMNS)
        assert len(result) == 3

    def test_only_includes_mapped_columns(self):
        """Extra columns in the DataFrame are not included in the output."""
        df = pd.DataFrame({
            "sucursal": ["A"],
            "generico": ["X"],
            "clientes_compradores": [10],
            "volumen_total": [999],
        })
        result = _preparar_cobertura(df, ["sucursal", "generico"], _COB_GENERICO_COLUMNS)
        assert "volumen_total" not in result.columns
        assert len(result.columns) == 3
