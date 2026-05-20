"""Tests for subdistribuidores service: processor functions."""

import pytest
import pandas as pd

from src.services.subdistribuidores.processor import procesar_subdistribuidores


class TestProcesarSubdistribuidores:
    """Tests para procesar_subdistribuidores()."""

    def test_bultos_una_fila_por_articulo(self):
        """6-level groupby produce una fila por article."""
        df = pd.DataFrame({
            "id_cliente": [1, 1, 1],
            "fantasia": ["CLIENTE A", "CLIENTE A", "CLIENTE A"],
            "razon_social": ["RAZON A", "RAZON A", "RAZON A"],
            "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS"],
            "marca": ["QUILMES", "QUILMES", "QUILMES"],
            "des_articulo": ["Cerveza 1L", "Cerveza 1L", "Cerveza 1L"],
            "cantidad": [10, 20, 30],
        })

        df_bultos, _ = procesar_subdistribuidores(df)

        assert len(df_bultos) == 1
        assert df_bultos["Bultos"].iloc[0] == 60

    def test_bultos_multiple_articulos_diferentes_marcas(self):
        """Different marca = different row in Bultos (6-level hierarchy)."""
        df = pd.DataFrame({
            "id_cliente": [1, 1, 1, 1],
            "fantasia": ["CLIENTE A", "CLIENTE A", "CLIENTE A", "CLIENTE A"],
            "razon_social": ["RAZON A"] * 4,
            "generico": ["CERVEZAS", "CERVEZAS", "AGUAS", "AGUAS"],
            "marca": ["QUILMES", "BRAHMA", "水源", "水源"],
            "des_articulo": ["Cerveza 1L", "Cerveza 1L", "Agua 1.5L", "Agua 1.5L"],
            "cantidad": [10, 5, 100, 50],
        })

        df_bultos, _ = procesar_subdistribuidores(df)

        # Three unique (generico, marca, des_articulo) combinations:
        # CERVEZAS/QUILMES, CERVEZAS/BRAHMA, AGUAS/水源
        assert len(df_bultos) == 3
        bultos_values = sorted(df_bultos["Bultos"].tolist())
        assert bultos_values == [5, 10, 150]

    def test_totales_5_niveles_agregacion(self):
        """Totales sheet must have rows at each of the 5 levels."""
        df = pd.DataFrame({
            "id_cliente": [1, 1, 1, 2],
            "fantasia": ["CLIENTE A", "CLIENTE A", "CLIENTE B", "CLIENTE B"],
            "razon_social": ["RAZON A", "RAZON A", "RAZON B", "RAZON B"],
            "generico": ["CERVEZAS", "AGUAS", "CERVEZAS", "CERVEZAS"],
            "marca": ["QUILMES", "水源", "BRAHMA", "BRAHMA"],
            "des_articulo": ["Cerveza 1L", "Agua 1L", "Cerveza 1L", "Cerveza 1L"],
            "cantidad": [100, 200, 50, 50],
        })

        _, df_totales = procesar_subdistribuidores(df)

        niveles = df_totales["Nivel"].unique().tolist()
        assert "Cliente" in niveles
        assert "Fantasia" in niveles
        assert "Razon Social" in niveles
        assert "Generico" in niveles
        assert "Marca" in niveles

    def test_totales_cliente_suma_correcta(self):
        """Nivel Cliente = SUM(cantidad) por id_cliente."""
        df = pd.DataFrame({
            "id_cliente": [1, 1, 2],
            "fantasia": ["CLIENTE A", "CLIENTE A", "CLIENTE B"],
            "razon_social": ["RAZON A", "RAZON A", "RAZON B"],
            "generico": ["CERVEZAS", "AGUAS", "CERVEZAS"],
            "marca": ["QUILMES", "水源", "BRAHMA"],
            "des_articulo": ["Cerveza 1L", "Agua 1L", "Cerveza 1L"],
            "cantidad": [100, 200, 50],
        })

        _, df_totales = procesar_subdistribuidores(df)

        cliente_rows = df_totales[df_totales["Nivel"] == "Cliente"]
        assert len(cliente_rows) == 2

        c1 = cliente_rows[cliente_rows["Cliente"] == 1]["Bultos"].iloc[0]
        c2 = cliente_rows[cliente_rows["Cliente"] == 2]["Bultos"].iloc[0]
        assert c1 == 300  # 100 + 200
        assert c2 == 50

    def test_totales_fantasia_agrupa_cliente_fantasia(self):
        """Nivel Fantasia agrupa por (Cliente, Fantasia)."""
        df = pd.DataFrame({
            "id_cliente": [1, 1, 1],
            "fantasia": ["CLIENTE A", "CLIENTE A", "CLIENTE A"],
            "razon_social": ["RAZON A", "RAZON A", "RAZON B"],
            "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS"],
            "marca": ["QUILMES", "QUILMES", "QUILMES"],
            "des_articulo": ["Cerveza 1L", "Cerveza 1L", "Cerveza 1L"],
            "cantidad": [10, 20, 30],
        })

        _, df_totales = procesar_subdistribuidores(df)

        fantasia_rows = df_totales[df_totales["Nivel"] == "Fantasia"]
        assert len(fantasia_rows) == 1
        assert fantasia_rows["Bultos"].iloc[0] == 60

    def test_totales_marca_agrupa_5_niveles(self):
        """Nivel Marca agrupa por (Cliente, Fantasia, Razon Social, Generico, Marca)."""
        df = pd.DataFrame({
            "id_cliente": [1, 1],
            "fantasia": ["CLIENTE A", "CLIENTE A"],
            "razon_social": ["RAZON A", "RAZON A"],
            "generico": ["CERVEZAS", "CERVEZAS"],
            "marca": ["QUILMES", "QUILMES"],
            "des_articulo": ["Cerveza 1L", "Cerveza 1L"],
            "cantidad": [100, 50],
        })

        _, df_totales = procesar_subdistribuidores(df)

        marca_rows = df_totales[df_totales["Nivel"] == "Marca"]
        assert len(marca_rows) == 1
        assert marca_rows["Bultos"].iloc[0] == 150

    def test_empty_dataframe_sin_crash(self):
        """Empty DF returns headers-only Bultos and Totales (no exception)."""
        df = pd.DataFrame(columns=[
            "id_cliente", "fantasia", "razon_social",
            "generico", "marca", "des_articulo", "cantidad"
        ])

        df_bultos, df_totales = procesar_subdistribuidores(df)

        # Should have headers but no data rows
        assert "Cliente" in df_bultos.columns
        assert "Fantasia" in df_bultos.columns
        assert "Razon Social" in df_bultos.columns
        assert "Generico" in df_bultos.columns
        assert "Marca" in df_bultos.columns
        assert "Articulo" in df_bultos.columns
        assert "Bultos" in df_bultos.columns
        assert df_bultos.empty

        assert "Nivel" in df_totales.columns
        assert "Bultos" in df_totales.columns
        assert df_totales.empty

    def test_fantasia_null_se_trata_como_vacio(self):
        """NULL fantasia values are replaced with empty string."""
        df = pd.DataFrame({
            "id_cliente": [1, 1],
            "fantasia": [None, None],
            "razon_social": ["RAZON A", "RAZON A"],
            "generico": ["CERVEZAS", "CERVEZAS"],
            "marca": ["QUILMES", "QUILMES"],
            "des_articulo": ["Cerveza 1L", "Cerveza 1L"],
            "cantidad": [100, 200],
        })

        df_bultos, _ = procesar_subdistribuidores(df)

        assert df_bultos.iloc[0]["Fantasia"] == ""

    def test_razon_social_null_se_trata_como_vacio(self):
        """NULL razon_social values are replaced with empty string."""
        df = pd.DataFrame({
            "id_cliente": [1],
            "fantasia": ["CLIENTE A"],
            "razon_social": [None],
            "generico": ["CERVEZAS"],
            "marca": ["QUILMES"],
            "des_articulo": ["Cerveza 1L"],
            "cantidad": [100],
        })

        df_bultos, _ = procesar_subdistribuidores(df)

        assert df_bultos.iloc[0]["Razon Social"] == ""