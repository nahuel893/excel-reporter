import pytest
import pandas as pd
from sqlalchemy import text

from src.core.data_loader import DataLoader


class TestDataLoaderClass:
    """Tests para la clase DataLoader."""

    @pytest.fixture
    def loader(self):
        """Crea instancia de DataLoader para tests."""
        return DataLoader()

    def test_engine_created(self, loader):
        """Verifica que el engine se crea correctamente."""
        engine = loader.engine
        assert engine is not None

    def test_connection_successful(self, loader):
        """Verifica que se puede establecer conexión a la BD."""
        conn = loader.get_connection()
        assert conn is not None
        conn.close()

    def test_connection_can_execute_query(self, loader):
        """Verifica que se puede ejecutar una query básica."""
        with loader.get_connection() as conn:
            result = conn.execute(text("SELECT 1"))
            row = result.fetchone()
            assert row[0] == 1

    def test_gold_schema_exists(self, loader):
        """Verifica que el esquema gold existe."""
        with loader.get_connection() as conn:
            result = conn.execute(text("""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name = 'gold'
            """))
            row = result.fetchone()
            assert row is not None, "El esquema 'gold' no existe"

    def test_fact_ventas_exists(self, loader):
        """Verifica que la tabla fact_ventas existe."""
        with loader.get_connection() as conn:
            result = conn.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'gold'
                AND table_name = 'fact_ventas'
            """))
            row = result.fetchone()
            assert row is not None, "La tabla 'gold.fact_ventas' no existe"

    def test_dim_tables_exist(self, loader):
        """Verifica que las tablas de dimensiones existen."""
        dims = ["dim_sucursal", "dim_articulo"]
        with loader.get_connection() as conn:
            for dim in dims:
                result = conn.execute(text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'gold'
                    AND table_name = :tabla
                """), {"tabla": dim})
                row = result.fetchone()
                assert row is not None, f"La tabla 'gold.{dim}' no existe"


class TestDataLoaderMethods:
    """Tests para métodos de DataLoader."""

    @pytest.fixture
    def loader(self):
        return DataLoader()

    def test_get_ventas_returns_dataframe(self, loader):
        """Verifica que get_ventas retorna un DataFrame."""
        df = loader.get_ventas("2025-01-01", "2025-01-31")
        assert isinstance(df, pd.DataFrame)

    def test_get_ventas_has_required_columns(self, loader):
        """Verifica que el DataFrame tiene las columnas esperadas."""
        df = loader.get_ventas("2025-01-01", "2025-01-31")
        expected_columns = ["sucursal", "generico", "marca", "cantidad", "monto"]
        for col in expected_columns:
            assert col in df.columns, f"Falta la columna '{col}'"

    def test_get_ventas_empty_range(self, loader):
        """Verifica comportamiento con rango sin datos."""
        df = loader.get_ventas("1900-01-01", "1900-01-02")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_get_sucursales_returns_dataframe(self, loader):
        """Verifica que get_sucursales retorna un DataFrame."""
        df = loader.get_sucursales()
        assert isinstance(df, pd.DataFrame)
        assert "sucursal" in df.columns

    def test_get_articulos_returns_dataframe(self, loader):
        """Verifica que get_articulos retorna un DataFrame."""
        df = loader.get_articulos()
        assert isinstance(df, pd.DataFrame)
        assert "generico" in df.columns
        assert "marca" in df.columns

    def test_get_articulos_con_filtro(self, loader):
        """Verifica que el filtro de genéricos funciona."""
        df_todos = loader.get_articulos()
        df_filtrado = loader.get_articulos(["CERVEZAS"])

        # El filtrado debe tener menos o igual registros
        assert len(df_filtrado) <= len(df_todos)

        # Si hay resultados, deben ser solo del genérico filtrado
        if len(df_filtrado) > 0:
            assert all(df_filtrado["generico"] == "CERVEZAS")


