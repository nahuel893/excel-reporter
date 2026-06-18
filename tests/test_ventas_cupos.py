"""
Tests para la feature de cupos en el reporte de ventas.

Cobertura:
1. cupos_dict built correctly from df_cupos
2. Cupo(Gen) appears only on first row (i==0), None on subsequent
3. Cupo(Marca) appears on every row
4. Cupo vs Tend%(Gen) = tend_gen / cupo_gen
5. Cupo vs Tend%(Marca) = tend_marca / cupo_marca
6. None when cupo is 0 or None
7. Empty df_cupos -> all cupo columns None
8. df_cupos=None -> no crash, all None
9. Cupo(Gen) in subtotal_cols, Cupo vs Tend%(Gen) NOT
10. Column order correct
"""
import pytest
import pandas as pd

from config.settings import COLUMN_NAMES
from src.services.ventas.processor import procesar_ventas_diarias
from src.services.ventas.service import _crear_estilo_ventas


# ── Helpers ──────────────────────────────────────────────────────────────────

def _df_ventas_simple():
    """DataFrame minimal con 2 marcas bajo 1 generico en 1 sucursal."""
    return pd.DataFrame({
        "sucursal": ["SUC1", "SUC1"],
        "generico": ["CERVEZAS", "CERVEZAS"],
        "marca": ["CORONA", "QUILMES"],
        "fecha": pd.to_datetime(["2026-04-01", "2026-04-01"]),
        "cantidad": [100, 50],
        "cantidad_htls": [10, 5],
        "monto": [5000, 2500],
    })


def _df_cupos_simple():
    """DataFrame de cupos con cupo para generico y para marcas."""
    return pd.DataFrame({
        "sucursal": ["SUC1", "SUC1", "SUC1"],
        "cupo_generico": ["CERVEZAS", "CORONA", "QUILMES"],
        "cupo": [1000.0, 200.0, 100.0],
    })


def _run_processor(df_ventas=None, df_cupos=None, col_cantidad="cantidad"):
    """Wrapper conveniente para llamar al processor."""
    if df_ventas is None:
        df_ventas = _df_ventas_simple()
    return procesar_ventas_diarias(
        df=df_ventas,
        fecha_desde="2026-04-01",
        fecha_hasta="2026-04-30",
        col_cantidad=col_cantidad,
        df_cupos=df_cupos,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCuposDictBuilding:
    """Test 1: cupos_dict built correctly from df_cupos."""

    def test_cupos_dict_maps_sucursal_y_cupo_generico(self):
        """El dict mapea (sucursal, cupo_generico) -> cupo."""
        df = _run_processor(df_cupos=_df_cupos_simple())
        # Si el dict funciona, la columna Cupo(Gen) debería tener 1000.0 en la primera fila
        col = COLUMN_NAMES["cupo_generico"]
        assert col in df.columns
        primera_fila = df[df[COLUMN_NAMES["generico"]] == "CERVEZAS"].iloc[0]
        assert primera_fila[col] == 1000.0

    def test_cupos_dict_ignora_cupo_cero(self):
        """Un cupo == 0 se trata como None (no dividir por cero)."""
        df_cupos_cero = pd.DataFrame({
            "sucursal": ["SUC1"],
            "cupo_generico": ["CERVEZAS"],
            "cupo": [0.0],
        })
        df = _run_processor(df_cupos=df_cupos_cero)
        col = COLUMN_NAMES["cupo_generico"]
        primera_fila = df.iloc[0]
        assert primera_fila[col] is None

    def test_cupos_dict_ignora_cupo_null(self):
        """Un cupo == NaN se trata como None."""
        df_cupos_null = pd.DataFrame({
            "sucursal": ["SUC1"],
            "cupo_generico": ["CERVEZAS"],
            "cupo": [float("nan")],
        })
        df = _run_processor(df_cupos=df_cupos_null)
        col = COLUMN_NAMES["cupo_generico"]
        primera_fila = df.iloc[0]
        assert primera_fila[col] is None


class TestCupoGenericoFirstRowOnly:
    """Test 2: Cupo(Gen) solo en primera fila del grupo sucursal+generico."""

    def test_cupo_generico_en_primera_fila(self):
        """La primera fila de cada grupo tiene el valor de cupo."""
        df = _run_processor(df_cupos=_df_cupos_simple())
        col = COLUMN_NAMES["cupo_generico"]
        # Ordenar para garantizar la primera fila del grupo
        grupo = df[df[COLUMN_NAMES["generico"]] == "CERVEZAS"]
        assert grupo.iloc[0][col] == 1000.0

    def test_cupo_generico_none_en_filas_siguientes(self):
        """Las filas subsiguientes del mismo grupo tienen None/NaN."""
        df = _run_processor(df_cupos=_df_cupos_simple())
        col = COLUMN_NAMES["cupo_generico"]
        grupo = df[df[COLUMN_NAMES["generico"]] == "CERVEZAS"]
        # Si hay 2 marcas, la segunda fila debe ser None/NaN
        if len(grupo) > 1:
            assert pd.isna(grupo.iloc[1][col])


class TestCupoMarcaEveryRow:
    """Test 3: Cupo(Marca) aparece en cada fila."""

    def test_cupo_marca_en_todas_las_filas(self):
        """Cada fila tiene un valor de cupo para la marca correspondiente."""
        df = _run_processor(df_cupos=_df_cupos_simple())
        col = COLUMN_NAMES["cupo_marca"]
        assert col in df.columns
        # CORONA -> 200.0, QUILMES -> 100.0
        corona_row = df[df[COLUMN_NAMES["marca"]] == "CORONA"]
        quilmes_row = df[df[COLUMN_NAMES["marca"]] == "QUILMES"]
        assert len(corona_row) > 0
        assert corona_row.iloc[0][col] == 200.0
        assert len(quilmes_row) > 0
        assert quilmes_row.iloc[0][col] == 100.0

    def test_cupo_marca_none_cuando_marca_sin_cupo(self):
        """Si no hay cupo para la marca, la columna es None."""
        df_cupos_solo_gen = pd.DataFrame({
            "sucursal": ["SUC1"],
            "cupo_generico": ["CERVEZAS"],  # Solo cupo de generico, no de marcas
            "cupo": [1000.0],
        })
        df = _run_processor(df_cupos=df_cupos_solo_gen)
        col = COLUMN_NAMES["cupo_marca"]
        # Todas las filas deben tener None en cupo_marca
        assert df[col].isna().all()


class TestCuposHTLsConversion:
    """Cupos en hoja HTLs se convierten desde bultos con regla de tres."""

    def test_cupo_generico_htls_usa_mix_vendido_del_generico(self):
        df = _run_processor(df_cupos=_df_cupos_simple(), col_cantidad="cantidad_htls")

        primera_fila = df[df[COLUMN_NAMES["generico"]] == "CERVEZAS"].iloc[0]

        # CERVEZAS: cupo_bultos=1000, htl_vendidos=15, bultos_vendidos=150.
        assert primera_fila[COLUMN_NAMES["cupo_generico"]] == 100.0

    def test_cupo_marca_htls_usa_mix_vendido_de_la_marca(self):
        df = _run_processor(df_cupos=_df_cupos_simple(), col_cantidad="cantidad_htls")

        corona = df[df[COLUMN_NAMES["marca"]] == "CORONA"].iloc[0]
        quilmes = df[df[COLUMN_NAMES["marca"]] == "QUILMES"].iloc[0]

        # CORONA: 200 * 10 HTL / 100 bultos = 20 HTL.
        assert corona[COLUMN_NAMES["cupo_marca"]] == 20.0
        # QUILMES: 100 * 5 HTL / 50 bultos = 10 HTL.
        assert quilmes[COLUMN_NAMES["cupo_marca"]] == 10.0

    def test_cupo_vs_tend_htls_usa_cupo_convertido(self):
        df = _run_processor(df_cupos=_df_cupos_simple(), col_cantidad="cantidad_htls")
        primera_fila = df[df[COLUMN_NAMES["generico"]] == "CERVEZAS"].iloc[0]

        ratio = primera_fila[COLUMN_NAMES["cupo_vs_tend_generico"]]
        tend = primera_fila[COLUMN_NAMES["tend_generico"]]
        cupo_convertido = primera_fila[COLUMN_NAMES["cupo_generico"]]

        assert ratio == tend / cupo_convertido

    def test_cupo_htls_none_si_bultos_vendidos_es_cero(self):
        df_ventas = _df_ventas_simple()
        df_ventas["cantidad"] = 0

        df = _run_processor(
            df_ventas=df_ventas,
            df_cupos=_df_cupos_simple(),
            col_cantidad="cantidad_htls",
        )

        assert df[COLUMN_NAMES["cupo_generico"]].isna().all()
        assert df[COLUMN_NAMES["cupo_marca"]].isna().all()
        assert df[COLUMN_NAMES["cupo_vs_tend_generico"]].isna().all()
        assert df[COLUMN_NAMES["cupo_vs_tend_marca"]].isna().all()


class TestCupoVsTendGenerico:
    """Test 4: Cupo vs Tend%(Gen) = tend_gen / cupo_gen."""

    def test_cupo_vs_tend_generico_calculo(self):
        """El ratio se calcula como tend_generico / cupo_generico."""
        df = _run_processor(df_cupos=_df_cupos_simple())
        col_ratio = COLUMN_NAMES["cupo_vs_tend_generico"]
        col_tend = COLUMN_NAMES["tend_generico"]
        col_cupo = COLUMN_NAMES["cupo_generico"]
        assert col_ratio in df.columns

        primera_fila = df.iloc[0]
        tend = primera_fila[col_tend]
        cupo = primera_fila[col_cupo]
        ratio = primera_fila[col_ratio]
        assert ratio is not None
        assert abs(ratio - (tend / cupo)) < 1e-10

    def test_cupo_vs_tend_generico_none_en_filas_siguientes(self):
        """Las filas subsiguientes del grupo tienen None/NaN en el ratio."""
        df = _run_processor(df_cupos=_df_cupos_simple())
        col_ratio = COLUMN_NAMES["cupo_vs_tend_generico"]
        grupo = df[df[COLUMN_NAMES["generico"]] == "CERVEZAS"]
        if len(grupo) > 1:
            assert pd.isna(grupo.iloc[1][col_ratio])


class TestCupoVsTendMarca:
    """Test 5: Cupo vs Tend%(Marca) = tend_marca / cupo_marca."""

    def test_cupo_vs_tend_marca_calculo(self):
        """El ratio de marca se calcula como tend_marca / cupo_marca."""
        df = _run_processor(df_cupos=_df_cupos_simple())
        col_ratio = COLUMN_NAMES["cupo_vs_tend_marca"]
        col_tend = COLUMN_NAMES["tend_marca"]
        col_cupo = COLUMN_NAMES["cupo_marca"]
        assert col_ratio in df.columns

        for _, fila in df.iterrows():
            cupo = fila[col_cupo]
            tend = fila[col_tend]
            ratio = fila[col_ratio]
            if cupo is not None and cupo > 0:
                assert ratio is not None
                assert abs(ratio - (tend / cupo)) < 1e-10
            else:
                assert ratio is None


class TestCupoNoneWhenZeroOrNull:
    """Test 6: None cuando cupo es 0 o None."""

    def test_ratio_none_cuando_cupo_es_cero(self):
        """Cupo vs Tend es None cuando cupo == 0."""
        df_cupos_cero = pd.DataFrame({
            "sucursal": ["SUC1", "SUC1"],
            "cupo_generico": ["CERVEZAS", "CORONA"],
            "cupo": [0.0, 0.0],
        })
        df = _run_processor(df_cupos=df_cupos_cero)
        assert df[COLUMN_NAMES["cupo_vs_tend_generico"]].isna().all()
        assert df[COLUMN_NAMES["cupo_vs_tend_marca"]].isna().all()

    def test_ratio_none_cuando_cupo_es_null(self):
        """Cupo vs Tend es None cuando cupo es NaN."""
        df_cupos_nan = pd.DataFrame({
            "sucursal": ["SUC1", "SUC1"],
            "cupo_generico": ["CERVEZAS", "CORONA"],
            "cupo": [float("nan"), float("nan")],
        })
        df = _run_processor(df_cupos=df_cupos_nan)
        assert df[COLUMN_NAMES["cupo_vs_tend_generico"]].isna().all()
        assert df[COLUMN_NAMES["cupo_vs_tend_marca"]].isna().all()


class TestEmptyCupos:
    """Test 7: DataFrame vacio de cupos -> todas las columnas cupo son None."""

    def test_cupos_vacio_produce_columnas_none(self):
        """Con df_cupos vacio, las 4 columnas de cupo son None para todas las filas."""
        df_cupos_empty = pd.DataFrame(columns=["sucursal", "cupo_generico", "cupo"])
        df = _run_processor(df_cupos=df_cupos_empty)
        for col_key in ["cupo_generico", "cupo_vs_tend_generico", "cupo_marca", "cupo_vs_tend_marca"]:
            col = COLUMN_NAMES[col_key]
            assert col in df.columns, f"Falta columna {col}"
            assert df[col].isna().all(), f"Columna {col} no es toda None"


class TestNoneCupos:
    """Test 8: df_cupos=None -> no crash, todas las columnas son None."""

    def test_cupos_none_no_rompe(self):
        """Pasar df_cupos=None no provoca excepcion."""
        df = _run_processor(df_cupos=None)
        assert df is not None
        assert len(df) > 0

    def test_cupos_none_columnas_none(self):
        """Con df_cupos=None, las 4 columnas de cupo son None para todas las filas."""
        df = _run_processor(df_cupos=None)
        for col_key in ["cupo_generico", "cupo_vs_tend_generico", "cupo_marca", "cupo_vs_tend_marca"]:
            col = COLUMN_NAMES[col_key]
            assert col in df.columns, f"Falta columna {col}"
            assert df[col].isna().all(), f"Columna {col} no es toda None con df_cupos=None"


class TestSubtotalCols:
    """Test 9: Cupo(Gen) en subtotal_cols, Cupo vs Tend%(Gen) NO."""

    def test_cupo_generico_in_subtotal_cols(self):
        """Cupo (Generico) debe estar en subtotal_columns del SheetStyle."""
        # Simular columnas de dias
        columnas_dias = ["01-04 Miercoles", "02-04 Jueves"]
        info_dias = {"Dias Habiles": 20, "Dias Transcurridos": 5, "Dias Faltantes": 15}
        style = _crear_estilo_ventas(columnas_dias, info_dias)
        assert COLUMN_NAMES["cupo_generico"] in style.subtotal_columns

    def test_cupo_vs_tend_generico_not_in_subtotal_cols(self):
        """Cupo vs Tend (Generico) NO debe estar en subtotal_columns."""
        columnas_dias = ["01-04 Miercoles"]
        info_dias = {"Dias Habiles": 20, "Dias Transcurridos": 5, "Dias Faltantes": 15}
        style = _crear_estilo_ventas(columnas_dias, info_dias)
        assert COLUMN_NAMES["cupo_vs_tend_generico"] not in style.subtotal_columns

    def test_cupo_marca_in_subtotal_cols(self):
        """Cupo (Marca) debe estar en subtotal_columns del SheetStyle."""
        columnas_dias = ["01-04 Miercoles"]
        info_dias = {"Dias Habiles": 20, "Dias Transcurridos": 5, "Dias Faltantes": 15}
        style = _crear_estilo_ventas(columnas_dias, info_dias)
        assert COLUMN_NAMES["cupo_marca"] in style.subtotal_columns

    def test_cupo_vs_tend_marca_not_in_subtotal_cols(self):
        """Cupo vs Tend (Marca) NO debe estar en subtotal_columns."""
        columnas_dias = ["01-04 Miercoles"]
        info_dias = {"Dias Habiles": 20, "Dias Transcurridos": 5, "Dias Faltantes": 15}
        style = _crear_estilo_ventas(columnas_dias, info_dias)
        assert COLUMN_NAMES["cupo_vs_tend_marca"] not in style.subtotal_columns


class TestColumnOrder:
    """Test 10: Orden de columnas correcto."""

    def test_cupo_generico_despues_de_cob_generico(self):
        """Cupo (Generico) debe aparecer despues de Cobertura (Generico) y antes de Marca."""
        df = _run_processor(df_cupos=_df_cupos_simple())
        cols = list(df.columns)
        idx_cob_gen = cols.index(COLUMN_NAMES["cob_generico"])
        idx_cupo_gen = cols.index(COLUMN_NAMES["cupo_generico"])
        idx_cupo_vs_tend_gen = cols.index(COLUMN_NAMES["cupo_vs_tend_generico"])
        idx_marca = cols.index(COLUMN_NAMES["marca"])

        assert idx_cob_gen < idx_cupo_gen < idx_cupo_vs_tend_gen < idx_marca

    def test_cupo_marca_despues_de_tend_marca(self):
        """Cupo (Marca) debe aparecer despues de Tendencia (Marca)."""
        df = _run_processor(df_cupos=_df_cupos_simple())
        cols = list(df.columns)
        idx_tend_marca = cols.index(COLUMN_NAMES["tend_marca"])
        idx_cupo_marca = cols.index(COLUMN_NAMES["cupo_marca"])
        idx_cupo_vs_tend_marca = cols.index(COLUMN_NAMES["cupo_vs_tend_marca"])

        assert idx_tend_marca < idx_cupo_marca < idx_cupo_vs_tend_marca

    def test_cupo_generico_is_last_before_marca(self):
        """La columna inmediatamente antes de Marca es Cupo vs Tend (Generico)."""
        df = _run_processor(df_cupos=_df_cupos_simple())
        cols = list(df.columns)
        idx_marca = cols.index(COLUMN_NAMES["marca"])
        assert cols[idx_marca - 1] == COLUMN_NAMES["cupo_vs_tend_generico"]


class TestNoRounding:
    """Verifica que no se usen int() o round() en valores de cupo."""

    def test_cupo_generico_raw_value(self):
        """Cupo (Generico) almacena el valor bruto sin truncar."""
        df_cupos_decimal = pd.DataFrame({
            "sucursal": ["SUC1"],
            "cupo_generico": ["CERVEZAS"],
            "cupo": [1234.56],
        })
        df = _run_processor(df_cupos=df_cupos_decimal)
        col = COLUMN_NAMES["cupo_generico"]
        primera_fila = df.iloc[0]
        # El valor debe ser exactamente 1234.56, no 1234 ni 1235
        assert primera_fila[col] == 1234.56

    def test_cupo_vs_tend_generico_raw_ratio(self):
        """Cupo vs Tend almacena el ratio bruto sin truncar."""
        df_cupos_decimal = pd.DataFrame({
            "sucursal": ["SUC1"],
            "cupo_generico": ["CERVEZAS"],
            "cupo": [777.0],
        })
        df = _run_processor(df_cupos=df_cupos_decimal)
        col_ratio = COLUMN_NAMES["cupo_vs_tend_generico"]
        col_tend = COLUMN_NAMES["tend_generico"]
        primera_fila = df.iloc[0]
        # El ratio no debe ser redondeado
        expected = primera_fila[col_tend] / 777.0
        assert primera_fila[col_ratio] == expected
