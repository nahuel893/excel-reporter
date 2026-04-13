import pytest
import pandas as pd
from datetime import date
from unittest.mock import patch

from src.core.base_processor import calcular_dias_habiles
from src.services.ventas.processor import completar_combinaciones, procesar_ventas
from config.settings import COLUMN_NAMES


class TestCalcularDiasHabiles:
    """Tests para calcular_dias_habiles."""

    @patch("src.core.base_processor.FERIADOS", [])
    def test_mes_completo_sin_feriados(self):
        """Enero 2026 sin feriados: 31 dias - 4 domingos = 27 dias habiles."""
        desde = date(2026, 1, 1)
        hasta = date(2026, 1, 31)
        transcurridos, totales = calcular_dias_habiles(desde, hasta)
        # Enero 2026: domingos son 4, 11, 18, 25 = 4 domingos
        assert totales == 27
        assert transcurridos == 27

    @patch("src.core.base_processor.FERIADOS", [])
    def test_mitad_de_mes(self):
        """Primera mitad de enero 2026."""
        desde = date(2026, 1, 1)
        hasta = date(2026, 1, 15)
        transcurridos, totales = calcular_dias_habiles(desde, hasta)
        # Dias 1-15, domingos: 4, 11 = 2 domingos
        # Transcurridos: 15 - 2 = 13
        assert transcurridos == 13
        assert totales == 27  # Total del mes

    @patch("src.core.base_processor.FERIADOS", ["2026-01-01"])
    def test_con_feriado(self):
        """Enero 2026 con 1 de enero feriado."""
        desde = date(2026, 1, 1)
        hasta = date(2026, 1, 31)
        transcurridos, totales = calcular_dias_habiles(desde, hasta)
        # 27 dias habiles - 1 feriado = 26
        assert totales == 26
        assert transcurridos == 26

    @patch("src.core.base_processor.FERIADOS", [])
    def test_excluye_domingos(self):
        """Verifica que los domingos no se cuentan."""
        # 4 de enero 2026 es domingo
        desde = date(2026, 1, 4)
        hasta = date(2026, 1, 4)
        transcurridos, totales = calcular_dias_habiles(desde, hasta)
        assert transcurridos == 0  # Domingo no cuenta

    @patch("src.core.base_processor.FERIADOS", [])
    def test_dia_habil_individual(self):
        """Un solo dia habil."""
        # 5 de enero 2026 es lunes
        desde = date(2026, 1, 5)
        hasta = date(2026, 1, 5)
        transcurridos, totales = calcular_dias_habiles(desde, hasta)
        assert transcurridos == 1


class TestCompletarCombinaciones:
    """Tests para completar_combinaciones."""

    def test_agrega_combinaciones_faltantes(self):
        """Verifica que se agregan combinaciones sin ventas."""
        df_ventas = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"],
            "cantidad": [100],
            "monto": [5000]
        })
        df_sucursales = pd.DataFrame({"sucursal": ["SUC1", "SUC2"]})
        df_articulos = pd.DataFrame({
            "generico": ["CERVEZAS", "CERVEZAS"],
            "marca": ["CORONA", "HEINEKEN"]
        })

        resultado = completar_combinaciones(df_ventas, df_sucursales, df_articulos)

        # 2 sucursales × 2 marcas = 4 combinaciones
        assert len(resultado) == 4

    def test_rellena_con_cero(self):
        """Verifica que las ventas faltantes se rellenan con 0."""
        df_ventas = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"],
            "cantidad": [100],
            "monto": [5000]
        })
        df_sucursales = pd.DataFrame({"sucursal": ["SUC1"]})
        df_articulos = pd.DataFrame({
            "generico": ["CERVEZAS", "CERVEZAS"],
            "marca": ["CORONA", "HEINEKEN"]
        })

        resultado = completar_combinaciones(df_ventas, df_sucursales, df_articulos)

        # HEINEKEN debe tener cantidad y monto = 0
        heineken = resultado[resultado["marca"] == "HEINEKEN"].iloc[0]
        assert heineken["cantidad"] == 0
        assert heineken["monto"] == 0

    def test_mantiene_ventas_existentes(self):
        """Verifica que las ventas existentes se mantienen."""
        df_ventas = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"],
            "cantidad": [100],
            "monto": [5000]
        })
        df_sucursales = pd.DataFrame({"sucursal": ["SUC1"]})
        df_articulos = pd.DataFrame({
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"]
        })

        resultado = completar_combinaciones(df_ventas, df_sucursales, df_articulos)

        corona = resultado[resultado["marca"] == "CORONA"].iloc[0]
        assert corona["cantidad"] == 100
        assert corona["monto"] == 5000

    def test_producto_cartesiano_correcto(self):
        """Verifica el producto cartesiano sucursales × artículos."""
        df_ventas = pd.DataFrame(columns=["sucursal", "generico", "marca", "cantidad", "monto"])
        df_sucursales = pd.DataFrame({"sucursal": ["A", "B", "C"]})
        df_articulos = pd.DataFrame({
            "generico": ["G1", "G2"],
            "marca": ["M1", "M2"]
        })

        resultado = completar_combinaciones(df_ventas, df_sucursales, df_articulos)

        # 3 sucursales × 2 artículos = 6 combinaciones
        assert len(resultado) == 6


class TestProcesarVentas:
    """Tests para procesar_ventas."""

    @patch("src.core.base_processor.FERIADOS", [])
    def test_retorna_dataframe_vacio_si_no_hay_datos(self):
        """DataFrame vacio retorna DataFrame con columnas correctas."""
        df = pd.DataFrame(columns=["sucursal", "generico", "marca", "cantidad", "monto"])
        resultado = procesar_ventas(df, "2026-01-01", "2026-01-31")

        assert isinstance(resultado, pd.DataFrame)
        assert list(resultado.columns) == list(COLUMN_NAMES.values())

    @patch("src.core.base_processor.FERIADOS", [])
    def test_columnas_correctas(self):
        """Verifica que el resultado tiene las columnas esperadas."""
        df = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"],
            "cantidad": [100],
            "monto": [5000]
        })
        resultado = procesar_ventas(df, "2026-01-01", "2026-01-31")

        # procesar_ventas es la version legacy sin columnas de cobertura, MMAA ni cupos
        cols_sin_cobertura = [v for k, v in COLUMN_NAMES.items() if k not in (
            "cob_generico", "cob_marca", "mmaa_marca", "var_mmaa_marca",
            "cupo_generico", "cupo_vs_tend_generico", "cupo_marca", "cupo_vs_tend_marca",
            "desc_generico", "desc_pct_generico", "desc_marca", "desc_pct_marca",
        )]
        assert list(resultado.columns) == cols_sin_cobertura

    @patch("src.core.base_processor.FERIADOS", [])
    def test_totales_generico_en_primera_fila(self):
        """Total del generico solo aparece en la primera fila del grupo."""
        df = pd.DataFrame({
            "sucursal": ["SUC1", "SUC1"],
            "generico": ["CERVEZAS", "CERVEZAS"],
            "marca": ["CORONA", "HEINEKEN"],
            "cantidad": [100, 50],
            "monto": [5000, 2500]
        })
        resultado = procesar_ventas(df, "2026-01-01", "2026-01-31")

        # Primera fila debe tener totales
        primera = resultado.iloc[0]
        assert primera[COLUMN_NAMES["cant_generico"]] == 150  # 100 + 50

        # Segunda fila no debe tener totales
        segunda = resultado.iloc[1]
        assert pd.isna(segunda[COLUMN_NAMES["cant_generico"]])

    @patch("src.core.base_processor.FERIADOS", [])
    def test_calcula_tendencia(self):
        """Verifica el calculo de tendencia."""
        df = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"],
            "cantidad": [100],
            "monto": [5000]
        })
        # Mitad del mes: factor aprox 2
        resultado = procesar_ventas(df, "2026-01-01", "2026-01-15")

        tendencia = resultado.iloc[0][COLUMN_NAMES["tend_marca"]]
        # Con 13 dias transcurridos de 27 totales, factor aprox 2.08
        assert tendencia > 100  # Debe ser mayor que la cantidad actual

    @patch("src.core.base_processor.FERIADOS", [])
    def test_ordena_por_monto_descendente(self):
        """Marcas ordenadas por monto descendente dentro de cada generico."""
        df = pd.DataFrame({
            "sucursal": ["SUC1", "SUC1", "SUC1"],
            "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS"],
            "marca": ["CORONA", "HEINEKEN", "BUDWEISER"],
            "cantidad": [50, 100, 75],
            "monto": [2500, 5000, 3750]
        })
        resultado = procesar_ventas(df, "2026-01-01", "2026-01-31")

        # Orden esperado: HEINEKEN (5000), BUDWEISER (3750), CORONA (2500)
        marcas = resultado[COLUMN_NAMES["marca"]].tolist()
        assert marcas == ["HEINEKEN", "BUDWEISER", "CORONA"]

    @patch("src.core.base_processor.FERIADOS", [])
    def test_multiples_sucursales(self):
        """Procesa correctamente multiples sucursales."""
        df = pd.DataFrame({
            "sucursal": ["SUC1", "SUC1", "SUC2"],
            "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS"],
            "marca": ["CORONA", "HEINEKEN", "CORONA"],
            "cantidad": [100, 50, 200],
            "monto": [5000, 2500, 10000]
        })
        resultado = procesar_ventas(df, "2026-01-01", "2026-01-31")

        # 3 filas: 2 de SUC1 + 1 de SUC2
        assert len(resultado) == 3

        # Verificar totales por sucursal
        suc1_total = resultado[resultado[COLUMN_NAMES["sucursal"]] == "SUC1"].iloc[0]
        assert suc1_total[COLUMN_NAMES["cant_generico"]] == 150

        suc2_total = resultado[resultado[COLUMN_NAMES["sucursal"]] == "SUC2"].iloc[0]
        assert suc2_total[COLUMN_NAMES["cant_generico"]] == 200
