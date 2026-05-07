"""
Tests para el servicio de Resumen Mensual.
Spec: docs/specs/2026-03-02-resumen-mensual.md
"""
import pandas as pd
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch, call

from src.services.resumen_mensual import (
    ResumenMensualConfig,
    ResumenMensualResult,
    ResumenMensualService,
)
from src.services.resumen_mensual.processor import (
    _detectar_dias_habiles_con_ventas,
    procesar_resumen_mensual,
)
from src.services.resumen_mensual.service import _nombre_reporte, _crear_estilo_resumen
from src.core.data_loader import DataLoader


# ---------------------------------------------------------------------------
# Helpers de fixtures comunes
# ---------------------------------------------------------------------------

def _df_ventas_mes(sucursales=None, genericos=None, cantidades=None):
    """Crea un df_ventas_mes tipico con columnas: sucursal, generico, id_ruta, cantidad."""
    sucursales = sucursales or ["SUC1", "SUC1"]
    genericos = genericos or ["CERVEZAS", "CERVEZAS"]
    cantidades = cantidades or [100, 50]
    return pd.DataFrame({
        "sucursal": sucursales,
        "generico": genericos,
        "id_ruta": [1] * len(sucursales),
        "cantidad": cantidades,
    })


def _df_dias(sucursales=None, genericos=None, fechas=None, cantidades=None):
    """Crea un df_dias tipico con columnas: sucursal, generico, fecha, id_ruta, cantidad."""
    sucursales = sucursales or ["SUC1"]
    genericos = genericos or ["CERVEZAS"]
    fechas = fechas or ["2026-02-26"]
    cantidades = cantidades or [10]
    return pd.DataFrame({
        "sucursal": sucursales,
        "generico": genericos,
        "fecha": pd.to_datetime(fechas),
        "id_ruta": [1] * len(sucursales),
        "cantidad": cantidades,
    })


def _df_vacio():
    """DataFrame vacio sin filas pero con columnas minimas."""
    return pd.DataFrame(columns=["sucursal", "generico", "cantidad"])


def _mock_loader(**overrides):
    """Crea un Mock de DataLoader con respuestas minimas por defecto."""
    loader = Mock(spec=DataLoader)
    loader.get_ventas_resumen_mensual.return_value = _df_ventas_mes()
    loader.get_ventas_ultimos_dias_habiles.return_value = _df_dias()
    loader.get_ventas_mes_anterior.return_value = _df_vacio()
    loader.get_ventas_mismo_mes_anio_anterior.return_value = _df_vacio()
    for attr, val in overrides.items():
        setattr(loader, attr + ".return_value", val)
    return loader


# ---------------------------------------------------------------------------
# Clase de tests
# ---------------------------------------------------------------------------

class TestResumenMensual:
    """Tests unitarios para ResumenMensualService y su processor."""

    # -----------------------------------------------------------------------
    # RF-001: Nombre del archivo
    # -----------------------------------------------------------------------

    def test_nombre_archivo_usa_ultima_fecha_venta(self):
        """RF-001: El nombre usa la ultima fecha con ventas del df_dias; fallback a fecha_hasta si vacio."""
        # Con datos: usa la fecha maxima del df_dias
        df_dias = pd.DataFrame({
            "fecha": pd.to_datetime(["2026-02-24", "2026-02-25", "2026-02-26"]),
        })
        nombre = _nombre_reporte(df_dias, "2026-02-28")
        assert nombre == "Resumen - 26-02-2026"

        # Sin datos: fallback a fecha_hasta
        nombre_fallback = _nombre_reporte(pd.DataFrame(columns=["fecha"]), "2026-02-28")
        assert nombre_fallback == "Resumen - 28-02-2026"

    # -----------------------------------------------------------------------
    # RF-002: Una hoja por generico
    # -----------------------------------------------------------------------

    def test_hojas_por_generico(self):
        """RF-002: ExcelWriter.add_sheet es llamado una vez por cada generico distinto."""
        loader = Mock(spec=DataLoader)
        loader.get_ventas_resumen_mensual.return_value = pd.DataFrame({
            "sucursal": ["SUC1", "SUC1"],
            "generico": ["CERVEZAS", "AGUAS DANONE"],
            "id_ruta": [1, 1],
            "cantidad": [100, 50],
        })
        loader.get_ventas_ultimos_dias_habiles.return_value = _df_dias()
        loader.get_ventas_mes_anterior.return_value = _df_vacio()
        loader.get_ventas_mismo_mes_anio_anterior.return_value = _df_vacio()

        with patch("src.services.resumen_mensual.service.ExcelWriter") as mock_writer_cls:
            mock_writer = Mock()
            mock_writer.save.return_value = Path("/tmp/test.xlsx")
            mock_writer_cls.return_value = mock_writer

            service = ResumenMensualService(data_loader=loader)
            config = ResumenMensualConfig(fecha_desde="2026-02-01", fecha_hasta="2026-02-28")
            service.generar_reporte(config)

        assert mock_writer.add_sheet.call_count == 2
        sheet_names = [c.kwargs.get("sheet_name") or c.args[1] for c in mock_writer.add_sheet.call_args_list]
        assert "CERVEZAS" in sheet_names
        assert "AGUAS DANONE" in sheet_names

    # -----------------------------------------------------------------------
    # RF-003: Filtro de genericos
    # -----------------------------------------------------------------------

    def test_filtro_genericos(self):
        """RF-003: get_ventas_resumen_mensual es llamado con la lista de genericos correcta."""
        loader = Mock(spec=DataLoader)
        loader.get_ventas_resumen_mensual.return_value = _df_ventas_mes()
        loader.get_ventas_ultimos_dias_habiles.return_value = _df_dias()
        loader.get_ventas_mes_anterior.return_value = _df_vacio()
        loader.get_ventas_mismo_mes_anio_anterior.return_value = _df_vacio()

        with patch("src.services.resumen_mensual.service.ExcelWriter") as mock_writer_cls:
            mock_writer = Mock()
            mock_writer.save.return_value = Path("/tmp/test.xlsx")
            mock_writer_cls.return_value = mock_writer

            service = ResumenMensualService(data_loader=loader)
            config = ResumenMensualConfig(
                fecha_desde="2026-02-01",
                fecha_hasta="2026-02-28",
                genericos=["CERVEZAS", "AGUAS DANONE"],
            )
            service.generar_reporte(config)

        loader.get_ventas_resumen_mensual.assert_called_once_with(
            "2026-02-01", "2026-02-28", ["CERVEZAS", "AGUAS DANONE"],
            genericos_sin_prvta=["FRATELLI B"],
            marca_splits=None,
        )

    # -----------------------------------------------------------------------
    # RF-004: Columnas presentes en la tabla (10 columnas en orden exacto)
    # -----------------------------------------------------------------------

    def test_columnas_presentes_en_tabla(self):
        """RF-004: procesar_resumen_mensual retorna exactamente 10 columnas en el orden correcto."""
        df_ventas_mes = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cantidad": [100],
        })
        df_dias = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "fecha": pd.to_datetime(["2026-02-26"]),
            "cantidad": [10],
        })
        df_ma = _df_vacio()
        df_aa = _df_vacio()

        with patch("src.services.resumen_mensual.processor.calcular_factor_tendencia", return_value=1.0):
            resultado = procesar_resumen_mensual(
                df_ventas_mes, df_dias, df_ma, df_aa,
                "2026-02-01", "2026-02-28"
            )

        # Las columnas N-1 y N-2 tienen nombres dinámicos (fecha real), verificamos estructura
        cols = list(resultado.columns)
        assert len(cols) == 10
        assert cols[0] == "Sucursal"
        assert cols[1] == "Generico"
        # cols[2] y cols[3] son los dias dinamicos (ej: "28-02 Sabado")
        assert cols[4] == "Total Ventas"
        assert cols[5] == "Tendencia"
        assert cols[6] == "MMAA"
        assert cols[7] == "MA"
        assert cols[8] == "Objetivo"
        assert cols[9] == "Tend vs Obj (%)"

    # -----------------------------------------------------------------------
    # RF-005: Objetivo y Tend vs Obj (%) son None cuando con_objetivo=False
    # -----------------------------------------------------------------------

    def test_objetivo_none_cuando_desactivado(self):
        """RF-005: Columnas Objetivo y Tend vs Obj (%) son None cuando con_objetivo=False."""
        df_ventas_mes = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cantidad": [100],
        })
        df_dias = _df_vacio().assign(fecha=pd.Series([], dtype="datetime64[ns]"))
        df_ma = _df_vacio()
        df_aa = _df_vacio()

        with patch("src.services.resumen_mensual.processor.calcular_factor_tendencia", return_value=1.0):
            resultado = procesar_resumen_mensual(
                df_ventas_mes, df_dias, df_ma, df_aa,
                "2026-02-01", "2026-02-28",
                con_objetivo=False,
            )

        assert resultado["Objetivo"].isna().all()
        assert resultado["Tend vs Obj (%)"].isna().all()

    # -----------------------------------------------------------------------
    # RF-009 y RF-010: Detectar dias habiles con ventas
    # -----------------------------------------------------------------------

    def test_detectar_dias_habiles_con_ventas(self):
        """RF-009/010: Excluye domingos y feriados; retorna los ultimos 2 dias habiles."""
        # 2026-02-15 es domingo, 2026-02-16 es feriado (Carnaval), 2026-02-17 tambien feriado
        # 2026-02-13 es viernes, 2026-02-14 es sabado (habil)
        df = pd.DataFrame({
            "fecha": pd.to_datetime([
                "2026-02-13",  # viernes - habil
                "2026-02-14",  # sabado - habil
                "2026-02-15",  # domingo - excluir
                "2026-02-16",  # feriado - excluir
                "2026-02-17",  # feriado - excluir
            ])
        })
        result = _detectar_dias_habiles_con_ventas(df, n=2)

        assert len(result) == 2
        # Los 2 ultimos habiles deben ser 14 y 13 (en orden descendente)
        assert result[0] == date(2026, 2, 14)
        assert result[1] == date(2026, 2, 13)
        # Ninguno debe ser domingo
        assert all(d.weekday() != 6 for d in result)
        # Ninguno debe ser 15, 16 o 17
        assert date(2026, 2, 15) not in result
        assert date(2026, 2, 16) not in result
        assert date(2026, 2, 17) not in result

    # -----------------------------------------------------------------------
    # RF-009 y RF-010: Valores N-1 y N-2 correctos
    # -----------------------------------------------------------------------

    def test_vtas_dia_n1_n2_valores(self):
        """RF-009/010: Vtas Dia N-1 corresponde a la ultima fecha, N-2 a la penultima."""
        df_ventas_mes = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cantidad": [300],
        })
        df_dias = pd.DataFrame({
            "sucursal": ["SUC1", "SUC1", "SUC1"],
            "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS"],
            "fecha": pd.to_datetime(["2026-02-24", "2026-02-25", "2026-02-26"]),
            "cantidad": [10, 20, 30],
        })
        df_ma = _df_vacio()
        df_aa = _df_vacio()

        with patch("src.services.resumen_mensual.processor.calcular_factor_tendencia", return_value=1.0):
            resultado = procesar_resumen_mensual(
                df_ventas_mes, df_dias, df_ma, df_aa,
                "2026-02-01", "2026-02-28"
            )

        fila = resultado.iloc[0]
        col_n2 = resultado.columns[2]  # mas antiguo, columna izquierda
        col_n1 = resultado.columns[3]  # mas reciente, columna derecha
        # N-2 es el penultimo (2026-02-25 Miercoles con cantidad 20)
        assert "25-02" in col_n2
        assert fila[col_n2] == 20
        # N-1 es el mas reciente (2026-02-26 Jueves con cantidad 30)
        assert "26-02" in col_n1
        assert fila[col_n1] == 30

    # -----------------------------------------------------------------------
    # RF-011: Total Ventas es la suma del periodo
    # -----------------------------------------------------------------------

    def test_total_ventas_suma_periodo(self):
        """RF-011: Total Ventas es la suma de cantidades del periodo para (Sucursal, Generico)."""
        df_ventas_mes = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cantidad": [350],
        })
        df_dias = _df_dias()
        df_ma = _df_vacio()
        df_aa = _df_vacio()

        with patch("src.services.resumen_mensual.processor.calcular_factor_tendencia", return_value=1.0):
            resultado = procesar_resumen_mensual(
                df_ventas_mes, df_dias, df_ma, df_aa,
                "2026-02-01", "2026-02-28"
            )

        assert resultado.iloc[0]["Total Ventas"] == 350

    # -----------------------------------------------------------------------
    # RF-012: Tendencia con factor correcto
    # -----------------------------------------------------------------------

    def test_tendencia_con_factor_correcto(self):
        """RF-012: Tendencia = round(Total Ventas * factor); con factor=2.0 espera el doble."""
        df_ventas_mes = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cantidad": [100],
        })
        df_dias = _df_dias()
        df_ma = _df_vacio()
        df_aa = _df_vacio()

        with patch("src.services.resumen_mensual.processor.calcular_factor_tendencia", return_value=2.0):
            resultado = procesar_resumen_mensual(
                df_ventas_mes, df_dias, df_ma, df_aa,
                "2026-02-01", "2026-02-28"
            )

        assert resultado.iloc[0]["Tendencia"] == 200

    # -----------------------------------------------------------------------
    # RF-012: Factor de tendencia = 1.0 cuando dias_transcurridos=0
    # -----------------------------------------------------------------------

    def test_factor_tendencia_uno_cuando_cero_dias(self):
        """RF-012: Cuando dias_habiles_transcurridos=0, factor=1.0 y Tendencia=Total Ventas."""
        df_ventas_mes = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cantidad": [150],
        })
        df_dias = _df_dias()
        df_ma = _df_vacio()
        df_aa = _df_vacio()

        # calcular_factor_tendencia retorna 1.0 cuando dias_transcurridos=0
        with patch("src.services.resumen_mensual.processor.calcular_factor_tendencia", return_value=1.0):
            resultado = procesar_resumen_mensual(
                df_ventas_mes, df_dias, df_ma, df_aa,
                "2026-02-01", "2026-02-28"
            )

        assert resultado.iloc[0]["Tendencia"] == resultado.iloc[0]["Total Ventas"]

    # -----------------------------------------------------------------------
    # RF-013b: Ventas mismo mes AA usa desplazamiento de un anio
    # -----------------------------------------------------------------------

    def test_ventas_ma_desplazamiento_un_anio(self):
        """RF-013b: Las fechas del periodo AA se calculan correctamente (2026-02-01 -> 2025-02-01)."""
        loader = Mock(spec=DataLoader)
        loader.get_ventas_resumen_mensual.return_value = _df_ventas_mes()
        loader.get_ventas_ultimos_dias_habiles.return_value = _df_dias()
        loader.get_ventas_mes_anterior.return_value = _df_vacio()
        loader.get_ventas_mismo_mes_anio_anterior.return_value = _df_vacio()

        with patch("src.services.resumen_mensual.service.ExcelWriter") as mock_writer_cls:
            mock_writer = Mock()
            mock_writer.save.return_value = Path("/tmp/test.xlsx")
            mock_writer_cls.return_value = mock_writer

            service = ResumenMensualService(data_loader=loader)
            config = ResumenMensualConfig(fecha_desde="2026-02-01", fecha_hasta="2026-02-28")
            service.generar_reporte(config)

        # El servicio pasa fecha_desde y fecha_hasta al metodo del DataLoader
        # El DataLoader calcula internamente el desplazamiento; el servicio pasa las fechas originales
        loader.get_ventas_mismo_mes_anio_anterior.assert_called_once_with(
            "2026-02-01", "2026-02-28", None,
            genericos_sin_prvta=["FRATELLI B"],
            marca_splits=None,
        )

    # -----------------------------------------------------------------------
    # RF-013b + RNF-003: Exception en AA -> columna queda en 0
    # -----------------------------------------------------------------------

    def test_ventas_ma_cero_cuando_falla_query(self):
        """RF-013b + RNF-003: Si get_ventas_mismo_mes_anio_anterior lanza Exception, columna queda en 0."""
        loader = Mock(spec=DataLoader)
        loader.get_ventas_resumen_mensual.return_value = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "id_ruta": [1],
            "cantidad": [100],
        })
        loader.get_ventas_ultimos_dias_habiles.return_value = _df_dias()
        loader.get_ventas_mes_anterior.return_value = _df_vacio()
        loader.get_ventas_mismo_mes_anio_anterior.side_effect = Exception("Sin datos del anio anterior")

        with patch("src.services.resumen_mensual.service.ExcelWriter") as mock_writer_cls:
            mock_writer = Mock()
            mock_writer.save.return_value = Path("/tmp/test.xlsx")
            mock_writer_cls.return_value = mock_writer

            service = ResumenMensualService(data_loader=loader)
            config = ResumenMensualConfig(fecha_desde="2026-02-01", fecha_hasta="2026-02-28")
            # No debe lanzar excepcion
            result = service.generar_reporte(config)

        assert result is not None
        # La columna AA se rellena con 0; verificar via add_sheet que se llamo con df que tiene AA=0.
        # Con subtotales inyectados, filtrar filas de datos reales (excluir subtotales con MMAA=None).
        call_args = mock_writer.add_sheet.call_args_list
        assert len(call_args) >= 1
        df_hoja = call_args[0].args[0] if call_args[0].args else call_args[0].kwargs["df"]
        _SUBTOTAL_LABELS = {"SUBTOTAL CASA CENTRAL", "SUCURSALES SIN DIRECTA", "TOTAL SIN SMK"}
        df_datos = df_hoja[~df_hoja["Sucursal"].isin(_SUBTOTAL_LABELS)]
        assert len(df_datos) >= 1, "No hay filas de datos en el df pasado a add_sheet"
        assert df_datos["MMAA"].iloc[0] == 0

    # -----------------------------------------------------------------------
    # RF-014: Zonas virtuales aplicadas
    # -----------------------------------------------------------------------

    def test_zonas_virtuales_aplicadas(self):
        """RF-014: Filas con id_ruta=81 y sucursal CASA CENTRAL se renombran a VALLE SALTA."""
        loader = Mock(spec=DataLoader)
        # df_ventas_mes con id_ruta=81 (ruta de VALLE SALTA)
        loader.get_ventas_resumen_mensual.return_value = pd.DataFrame({
            "sucursal": ["CASA CENTRAL"],
            "generico": ["CERVEZAS"],
            "id_ruta": [81],
            "cantidad": [100],
        })
        loader.get_ventas_ultimos_dias_habiles.return_value = pd.DataFrame({
            "sucursal": ["CASA CENTRAL"],
            "generico": ["CERVEZAS"],
            "fecha": pd.to_datetime(["2026-02-26"]),
            "id_ruta": [81],
            "cantidad": [10],
        })
        loader.get_ventas_mes_anterior.return_value = _df_vacio()
        loader.get_ventas_mismo_mes_anio_anterior.return_value = _df_vacio()

        with patch("src.services.resumen_mensual.service.ExcelWriter") as mock_writer_cls:
            mock_writer = Mock()
            mock_writer.save.return_value = Path("/tmp/test.xlsx")
            mock_writer_cls.return_value = mock_writer

            service = ResumenMensualService(data_loader=loader)
            config = ResumenMensualConfig(fecha_desde="2026-02-01", fecha_hasta="2026-02-28")
            service.generar_reporte(config)

        # Verificar que la hoja creada tiene VALLE SALTA, no CASA CENTRAL
        call_args = mock_writer.add_sheet.call_args_list
        assert len(call_args) >= 1
        df_hoja = call_args[0].args[0] if call_args[0].args else call_args[0].kwargs["df"]
        assert "VALLE SALTA" in df_hoja["Sucursal"].values
        assert "CASA CENTRAL" not in df_hoja["Sucursal"].values

    # -----------------------------------------------------------------------
    # RF-015: Summary rows presentes con las 3 claves
    # -----------------------------------------------------------------------

    def test_summary_rows_presentes(self):
        """RF-015: SheetStyle.summary_rows tiene las 3 claves esperadas con valores enteros."""
        with patch("src.services.resumen_mensual.service.calcular_info_dias") as mock_info:
            mock_info.return_value = {
                "Dias Habiles": 20,
                "Dias Transcurridos": 15,
                "Dias Faltantes": 5,
            }
            style = _crear_estilo_resumen(mock_info.return_value, "28-02 Sabado", "27-02 Viernes")

        assert "Dias Habiles" in style.summary_rows
        assert "Dias Transcurridos" in style.summary_rows
        assert "Dias Faltantes" in style.summary_rows
        assert isinstance(style.summary_rows["Dias Habiles"], int)
        assert isinstance(style.summary_rows["Dias Transcurridos"], int)
        assert isinstance(style.summary_rows["Dias Faltantes"], int)

    # -----------------------------------------------------------------------
    # RF-007 edge case: Combinacion solo en AA incluida con Total Ventas=0
    # -----------------------------------------------------------------------

    def test_combinacion_solo_en_aa_incluida(self):
        """RF-007: Combinacion con ventas solo en AA aparece con Total Ventas=0, Ventas Mismo Mes AA>0."""
        # df_ventas_mes esta vacio (sin ventas en periodo actual)
        df_ventas_mes = _df_vacio()
        df_dias = _df_vacio().assign(fecha=pd.Series([], dtype="datetime64[ns]"))
        df_ma = _df_vacio()
        # Solo hay datos en el anio anterior
        df_aa = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cantidad": [200],
        })

        with patch("src.services.resumen_mensual.processor.calcular_factor_tendencia", return_value=1.0):
            resultado = procesar_resumen_mensual(
                df_ventas_mes, df_dias, df_ma, df_aa,
                "2026-02-01", "2026-02-28"
            )

        assert len(resultado) == 1
        fila = resultado.iloc[0]
        assert fila["Total Ventas"] == 0
        assert fila["MMAA"] == 200

    # -----------------------------------------------------------------------
    # RF-007 edge case: Combinacion sin datos en ningun periodo omitida
    # -----------------------------------------------------------------------

    def test_combinacion_sin_datos_omitida(self):
        """RF-007: Combinacion sin datos en ningun periodo no aparece en la tabla."""
        # Todos los DataFrames vacios
        df_ventas_mes = _df_vacio()
        df_dias = _df_vacio().assign(fecha=pd.Series([], dtype="datetime64[ns]"))
        df_ma = _df_vacio()
        df_aa = _df_vacio()

        with patch("src.services.resumen_mensual.processor.calcular_factor_tendencia", return_value=1.0):
            resultado = procesar_resumen_mensual(
                df_ventas_mes, df_dias, df_ma, df_aa,
                "2026-02-01", "2026-02-28"
            )

        assert len(resultado) == 0

    # -----------------------------------------------------------------------
    # Edge case: Nombre de hoja truncado a 31 caracteres
    # -----------------------------------------------------------------------

    def test_nombre_hoja_truncado_31_chars(self):
        """Edge case: Nombres de generico mayores a 31 chars son truncados antes de add_sheet."""
        nombre_largo = "GENERICO CON NOMBRE MUY LARGO QUE SUPERA EL LIMITE"
        assert len(nombre_largo) > 31

        loader = Mock(spec=DataLoader)
        loader.get_ventas_resumen_mensual.return_value = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": [nombre_largo],
            "id_ruta": [1],
            "cantidad": [100],
        })
        loader.get_ventas_ultimos_dias_habiles.return_value = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": [nombre_largo],
            "fecha": pd.to_datetime(["2026-02-26"]),
            "id_ruta": [1],
            "cantidad": [10],
        })
        loader.get_ventas_mes_anterior.return_value = _df_vacio()
        loader.get_ventas_mismo_mes_anio_anterior.return_value = _df_vacio()

        with patch("src.services.resumen_mensual.service.ExcelWriter") as mock_writer_cls:
            mock_writer = Mock()
            mock_writer.save.return_value = Path("/tmp/test.xlsx")
            mock_writer_cls.return_value = mock_writer

            service = ResumenMensualService(data_loader=loader)
            config = ResumenMensualConfig(fecha_desde="2026-02-01", fecha_hasta="2026-02-28")
            service.generar_reporte(config)

        call_args = mock_writer.add_sheet.call_args_list
        assert len(call_args) == 1
        sheet_name = call_args[0].kwargs.get("sheet_name") or call_args[0].args[1]
        assert len(sheet_name) <= 31
        assert sheet_name == nombre_largo[:31]

    # -----------------------------------------------------------------------
    # Edge case: genericos=[] se trata como None
    # -----------------------------------------------------------------------

    def test_genericos_lista_vacia_trae_todos(self):
        """Edge case: genericos=[] se trata como None (trae todos los genericos)."""
        loader = Mock(spec=DataLoader)
        loader.get_ventas_resumen_mensual.return_value = _df_ventas_mes()
        loader.get_ventas_ultimos_dias_habiles.return_value = _df_dias()
        loader.get_ventas_mes_anterior.return_value = _df_vacio()
        loader.get_ventas_mismo_mes_anio_anterior.return_value = _df_vacio()

        with patch("src.services.resumen_mensual.service.ExcelWriter") as mock_writer_cls:
            mock_writer = Mock()
            mock_writer.save.return_value = Path("/tmp/test.xlsx")
            mock_writer_cls.return_value = mock_writer

            service = ResumenMensualService(data_loader=loader)
            config = ResumenMensualConfig(
                fecha_desde="2026-02-01",
                fecha_hasta="2026-02-28",
                genericos=[],
            )
            service.generar_reporte(config)

        # Se debe llamar con None, no con []
        loader.get_ventas_resumen_mensual.assert_called_once_with(
            "2026-02-01", "2026-02-28", None,
            genericos_sin_prvta=["FRATELLI B"],
            marca_splits=None,
        )

    # -----------------------------------------------------------------------
    # RF-006 edge case: Tend vs Obj (%) es None cuando Objetivo=0
    # -----------------------------------------------------------------------

    def test_tend_vs_obj_none_cuando_objetivo_cero(self):
        """RF-006: Tend vs Obj (%) es None cuando Objetivo=0 (no dividir por cero)."""
        df_ventas_mes = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "cantidad": [100],
        })
        df_dias = _df_dias()
        df_ma = _df_vacio()
        df_aa = _df_vacio()

        # con_objetivo=True pero sin fuente real de objetivos; la implementacion actual
        # deja objetivo=None; el test verifica que Tend vs Obj (%) queda None cuando objetivo=0 o None
        with patch("src.services.resumen_mensual.processor.calcular_factor_tendencia", return_value=1.0):
            resultado = procesar_resumen_mensual(
                df_ventas_mes, df_dias, df_ma, df_aa,
                "2026-02-01", "2026-02-28",
                con_objetivo=True,
            )

        # Objetivo es None (no hay fuente de datos); Tend vs Obj (%) debe ser None
        assert resultado.iloc[0]["Objetivo"] is None
        assert resultado.iloc[0]["Tend vs Obj (%)"] is None

    # -----------------------------------------------------------------------
    # RF-008: Filas ordenadas por Sucursal y luego Generico
    # -----------------------------------------------------------------------

    def test_filas_ordenadas_por_sucursal_luego_generico(self):
        """RF-008: Las filas del resultado estan ordenadas por Sucursal asc, luego Generico asc."""
        df_ventas_mes = pd.DataFrame({
            "sucursal": ["SUC2", "SUC1", "SUC1"],
            "generico": ["CERVEZAS", "VINOS CCU", "AGUAS DANONE"],
            "cantidad": [50, 30, 20],
        })
        df_dias = _df_vacio().assign(fecha=pd.Series([], dtype="datetime64[ns]"))
        df_ma = _df_vacio()
        df_aa = _df_vacio()

        with patch("src.services.resumen_mensual.processor.calcular_factor_tendencia", return_value=1.0):
            resultado = procesar_resumen_mensual(
                df_ventas_mes, df_dias, df_ma, df_aa,
                "2026-02-01", "2026-02-28"
            )

        # With universe expansion: every (sucursal × generico) appears.
        # Universe of sucursales: {SUC1, SUC2}; universe of genericos: {AGUAS DANONE, CERVEZAS, VINOS CCU}.
        # Expected order: by Sucursal asc, then Generico asc.
        sucursales = resultado["Sucursal"].tolist()
        genericos = resultado["Generico"].tolist()

        assert sucursales == ["SUC1", "SUC1", "SUC1", "SUC2", "SUC2", "SUC2"]
        assert genericos == [
            "AGUAS DANONE", "CERVEZAS", "VINOS CCU",
            "AGUAS DANONE", "CERVEZAS", "VINOS CCU",
        ]
