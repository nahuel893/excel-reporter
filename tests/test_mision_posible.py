"""Tests unitarios para Mision Posible."""
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from src.core.data_loader import DataLoader
from src.services.mision_posible.processor import (
    procesar_cobertura_sucursal,
    procesar_cobertura_vendedor,
    concatenar_tablas,
)
from src.services.mision_posible.service import (
    MisionPosibleConfig,
    MisionPosibleService,
    _normalizar_periodo,
    _nombre_reporte,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _df_cob(rows=None):
    """Crea DataFrame de cobertura tipo cob_preventista_marca."""
    if rows is None:
        rows = [
            {"sucursal": "CASA CENTRAL", "vendedor": "Juan", "id_vendedor": 1, "id_ruta": 1, "marca": "Imperial", "clientes_compradores": 20, "volumen_total": 100, "periodo": "2026-03-01"},
            {"sucursal": "CASA CENTRAL", "vendedor": "Maria", "id_vendedor": 2, "id_ruta": 2, "marca": "Imperial", "clientes_compradores": 25, "volumen_total": 150, "periodo": "2026-03-01"},
            {"sucursal": "SUCURSAL CAFAYATE", "vendedor": "Pedro", "id_vendedor": 3, "id_ruta": 10, "marca": "Imperial", "clientes_compradores": 15, "volumen_total": 80, "periodo": "2026-03-01"},
            {"sucursal": "CASA CENTRAL", "vendedor": "Juan", "id_vendedor": 1, "id_ruta": 1, "marca": "Levite", "clientes_compradores": 10, "volumen_total": 50, "periodo": "2026-03-01"},
        ]
    return pd.DataFrame(rows)


def _mock_loader(df_cob=None, ultima_fecha=date(2026, 3, 6)):
    loader = Mock(spec=DataLoader)
    loader.get_cobertura_preventista_marca.return_value = df_cob if df_cob is not None else _df_cob()
    loader.get_ultima_fecha_venta.return_value = ultima_fecha
    return loader


PORCENTAJES = {"CASA CENTRAL": 30, "SUCURSAL CAFAYATE": 10, "SUCURSAL METAN": 10}


# ── Processor tests ─────────────────────────────────────────────────────────

class TestProcesarCoberturaSucursal:
    """Tests para procesar_cobertura_sucursal."""

    def test_columnas_tabla_sucursal(self):
        """RF-006: columnas exactas."""
        df = procesar_cobertura_sucursal(_df_cob(), "Imperial", 500, PORCENTAJES)
        assert list(df.columns) == ["Sucursal", "Cobertura", "Objetivo", "Faltante", "%"]

    def test_cobertura_sucursal_agrupa_correctamente(self):
        """RF-008: suma clientes_compradores de vendedores en misma sucursal."""
        df = procesar_cobertura_sucursal(_df_cob(), "Imperial", 500, PORCENTAJES)
        cc = df[df["Sucursal"] == "CASA CENTRAL"]["Cobertura"].iloc[0]
        assert cc == 45  # 20 + 25

    def test_objetivo_sucursal_calculo_porcentaje(self):
        """RF-010: objetivo = total * porcentaje / 100."""
        df = procesar_cobertura_sucursal(_df_cob(), "Imperial", 500, PORCENTAJES)
        cc = df[df["Sucursal"] == "CASA CENTRAL"]["Objetivo"].iloc[0]
        caf = df[df["Sucursal"] == "SUCURSAL CAFAYATE"]["Objetivo"].iloc[0]
        assert cc == 150  # 500 * 30 / 100
        assert caf == 50   # 500 * 10 / 100

    def test_objetivo_ausente_queda_none(self):
        """RF-010: sin objetivos, todo None."""
        df = procesar_cobertura_sucursal(_df_cob(), "Imperial", None, PORCENTAJES)
        assert df["Objetivo"].isna().all()
        assert df["Faltante"].isna().all()
        assert df["%"].isna().all()

    def test_sucursal_sin_porcentaje_objetivo_none(self):
        """RF-010: sucursal en datos pero sin porcentaje."""
        pct = {"CASA CENTRAL": 30}  # CAFAYATE no incluida
        df = procesar_cobertura_sucursal(_df_cob(), "Imperial", 500, pct)
        # CAFAYATE no aparece porque no esta en porcentajes_sucursal
        assert "SUCURSAL CAFAYATE" not in df["Sucursal"].values

    def test_todas_sucursales_presentes(self):
        """RF-014: todas las sucursales de porcentajes_sucursal aparecen."""
        pct = {"CASA CENTRAL": 30, "SUCURSAL CAFAYATE": 10, "SUCURSAL METAN": 10, "SUCURSAL PERICO": 10, "SUCURSAL TARTAGAL": 15}
        df = procesar_cobertura_sucursal(_df_cob(), "Imperial", 500, pct)
        assert len(df) == 5
        # METAN tiene Cobertura = 0 (no hay datos)
        metan = df[df["Sucursal"] == "SUCURSAL METAN"]["Cobertura"].iloc[0]
        assert metan == 0

    def test_faltante_negativo_cuando_supera_objetivo(self):
        """RF-012: Faltante negativo si Cobertura > Objetivo."""
        pct = {"CASA CENTRAL": 5}  # 500*5/100 = 25, cobertura = 45
        df = procesar_cobertura_sucursal(_df_cob(), "Imperial", 500, pct)
        faltante = df[df["Sucursal"] == "CASA CENTRAL"]["Faltante"].iloc[0]
        assert faltante == -20  # 25 - 45

    def test_porcentaje_none_cuando_objetivo_cero(self):
        """RF-013: % = None si objetivo = 0."""
        pct = {"CASA CENTRAL": 0}
        df = procesar_cobertura_sucursal(_df_cob(), "Imperial", 500, pct)
        pct_val = df[df["Sucursal"] == "CASA CENTRAL"]["%"].iloc[0]
        assert pct_val is None or pd.isna(pct_val)

    def test_porcentaje_calculado_correctamente(self):
        """RF-013: % = round(Cobertura / Objetivo * 100, 1)."""
        df = procesar_cobertura_sucursal(_df_cob(), "Imperial", 500, PORCENTAJES)
        cc_row = df[df["Sucursal"] == "CASA CENTRAL"]
        pct = cc_row["%"].iloc[0]
        # Cobertura=45, Objetivo=150 → 30.0
        assert pct == 30.0

    def test_orden_filas_sucursal(self):
        """RF-014: filas ordenadas alfabeticamente por sucursal."""
        df = procesar_cobertura_sucursal(_df_cob(), "Imperial", 500, PORCENTAJES)
        assert list(df["Sucursal"]) == sorted(df["Sucursal"])


class TestProcesarCoberturaVendedor:
    """Tests para procesar_cobertura_vendedor."""

    def test_columnas_tabla_vendedor(self):
        """RF-007: columnas exactas."""
        df = procesar_cobertura_vendedor(_df_cob(), "Imperial", 500, PORCENTAJES)
        assert list(df.columns) == ["Vendedor", "Sucursal", "Cobertura", "Objetivo", "Faltante", "%"]

    def test_objetivo_vendedor_reparto_igualitario(self):
        """RF-011: objetivo = objetivo_sucursal / cant_vendedores."""
        df = procesar_cobertura_vendedor(_df_cob(), "Imperial", 500, PORCENTAJES)
        # CASA CENTRAL: obj=150, 2 vendedores → 75 cada uno
        juan = df[(df["Vendedor"] == "Juan") & (df["Sucursal"] == "CASA CENTRAL")]
        assert juan["Objetivo"].iloc[0] == 75

    def test_orden_filas_vendedor(self):
        """RF-015: ordenado por Sucursal, luego Vendedor."""
        df = procesar_cobertura_vendedor(_df_cob(), "Imperial", 500, PORCENTAJES)
        pairs = list(zip(df["Sucursal"], df["Vendedor"]))
        assert pairs == sorted(pairs)

    def test_vendedor_sin_datos_retorna_vacio(self):
        """Marca sin datos → DataFrame vacio."""
        df = procesar_cobertura_vendedor(_df_cob(), "NoExiste", 500, PORCENTAJES)
        assert df.empty
        assert list(df.columns) == ["Vendedor", "Sucursal", "Cobertura", "Objetivo", "Faltante", "%"]


class TestConcatenarTablas:
    """Tests para concatenar_tablas."""

    def test_concatena_con_separador(self):
        """RF-005: dos tablas separadas por fila vacia + titulo."""
        df_suc = procesar_cobertura_sucursal(_df_cob(), "Imperial", 500, PORCENTAJES)
        df_vend = procesar_cobertura_vendedor(_df_cob(), "Imperial", 500, PORCENTAJES)
        result = concatenar_tablas(df_suc, df_vend)
        # Debe tener: filas_suc + 1(sep) + 1(titulo) + 1(header) + filas_vend
        assert len(result) == len(df_suc) + 3 + len(df_vend)
        # Fila titulo contiene "Por Vendedor"
        titulo_row = result.iloc[len(df_suc) + 1]
        assert titulo_row.iloc[0] == "Por Vendedor"


# ── Service tests ────────────────────────────────────────────────────────────

class TestMisionPosibleService:
    """Tests para MisionPosibleService."""

    def _config(self, **overrides):
        defaults = {
            "periodo": "2026-03-01",
            "marcas": ["Imperial", "Levite"],
            "objetivos": {"Imperial": 500, "Levite": 300},
            "porcentajes_sucursal": PORCENTAJES,
        }
        defaults.update(overrides)
        return MisionPosibleConfig(**defaults)

    @patch("src.services.mision_posible.service.ExcelWriter")
    def test_nombre_archivo_formato_mes_anio(self, mock_writer_cls):
        """RF-001: nombre = Mision Posible MM-YYYY."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        service = MisionPosibleService(data_loader=_mock_loader())
        service.generar_reporte(self._config())
        mock_writer_cls.assert_called_once_with("Mision Posible 03-2026")

    @patch("src.services.mision_posible.service.ExcelWriter")
    def test_nombre_archivo_custom(self, mock_writer_cls):
        """RF-002: nombre custom."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        service = MisionPosibleService(data_loader=_mock_loader())
        service.generar_reporte(self._config(nombre_archivo="Mi Mision"))
        mock_writer_cls.assert_called_once_with("Mi Mision")

    @patch("src.services.mision_posible.service.ExcelWriter")
    def test_hojas_por_marca_en_orden(self, mock_writer_cls):
        """RF-003: una hoja por marca en orden."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        service = MisionPosibleService(data_loader=_mock_loader())
        service.generar_reporte(self._config())
        calls = mock_writer.add_sheet.call_args_list
        sheet_names = [c.kwargs.get("sheet_name") or c.args[1] for c in calls]
        assert sheet_names == ["Imperial", "Levite"]

    def test_error_marcas_vacio(self):
        """RF-004: error si marcas esta vacia."""
        service = MisionPosibleService(data_loader=_mock_loader())
        with pytest.raises(ValueError, match="vacia"):
            service.generar_reporte(self._config(marcas=[]))

    @patch("src.services.mision_posible.service.ExcelWriter")
    def test_zonas_virtuales_aplicadas_a_cobertura(self, mock_writer_cls):
        """RF-016: zonas virtuales se aplican al DataFrame."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        # Fila con id_ruta 81 (VALLE SALTA) en CASA CENTRAL
        df = _df_cob([{
            "sucursal": "CASA CENTRAL", "vendedor": "Juan", "id_vendedor": 1,
            "id_ruta": 81, "marca": "Imperial", "clientes_compradores": 20,
            "volumen_total": 100, "periodo": "2026-03-01",
        }])
        loader = _mock_loader(df_cob=df)
        service = MisionPosibleService(data_loader=loader)
        pct = {"VALLE SALTA": 15, "CASA CENTRAL": 30}
        result = service.generar_reporte(self._config(
            marcas=["Imperial"],
            porcentajes_sucursal=pct,
        ))
        # Verify the sheet was written (zonas virtuales applied internally)
        assert mock_writer.add_sheet.call_count == 1

    @patch("src.services.mision_posible.service.ExcelWriter")
    def test_modo_supervisores_genera_un_archivo_por_supervisor(self, mock_writer_cls):
        """RF-017: un archivo por supervisor."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        service = MisionPosibleService(data_loader=_mock_loader())
        supervisores = {"Ana": ["CASA CENTRAL"], "Luis": ["SUCURSAL CAFAYATE"]}
        results = service.generar_reporte_supervisores(self._config(), supervisores)
        assert len(results) == 2
        assert results[0].supervisor == "Ana"
        assert results[1].supervisor == "Luis"

    @patch("src.services.mision_posible.service.ExcelWriter")
    def test_modo_supervisores_una_sola_consulta(self, mock_writer_cls):
        """RF-018: una sola consulta a BD."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        loader = _mock_loader()
        service = MisionPosibleService(data_loader=loader)
        supervisores = {"Ana": ["CASA CENTRAL"], "Luis": ["SUCURSAL CAFAYATE"]}
        service.generar_reporte_supervisores(self._config(), supervisores)
        loader.get_cobertura_preventista_marca.assert_called_once()

    def test_periodo_normalizado_al_primer_dia(self, capsys):
        """Decision 4: periodo se normaliza con warning."""
        periodo = _normalizar_periodo("2026-03-15")
        assert periodo == "2026-03-01"
        captured = capsys.readouterr()
        assert "normalizado" in captured.out.lower() or "⚠" in captured.out

    @patch("src.services.mision_posible.service.ExcelWriter")
    def test_consulta_bd_falla_genera_hojas_vacias(self, mock_writer_cls):
        """RNF-003: si BD falla, genera archivo con tablas vacias."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        loader = Mock(spec=DataLoader)
        loader.get_cobertura_preventista_marca.side_effect = Exception("DB error")
        loader.get_ultima_fecha_venta.side_effect = Exception("DB error")

        service = MisionPosibleService(data_loader=loader)
        result = service.generar_reporte(self._config(marcas=["Imperial"]))
        assert mock_writer.add_sheet.call_count == 1

    @patch("src.services.mision_posible.service.ExcelWriter")
    def test_nombre_hoja_truncado_31_chars(self, mock_writer_cls):
        """OpenPyXL limit: 31 chars max."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        service = MisionPosibleService(data_loader=_mock_loader())
        marca_larga = "A" * 35
        service.generar_reporte(self._config(marcas=[marca_larga]))
        call = mock_writer.add_sheet.call_args
        sheet_name = call.kwargs.get("sheet_name") or call.args[1]
        assert len(sheet_name) == 31

    @patch("src.services.mision_posible.service.ExcelWriter")
    def test_ultima_actualizacion_en_summary_rows(self, mock_writer_cls):
        """RF-023: summary_rows incluye Ult. Actualizacion."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        service = MisionPosibleService(data_loader=_mock_loader(ultima_fecha=date(2026, 3, 6)))
        service.generar_reporte(self._config(marcas=["Imperial"]))
        call = mock_writer.add_sheet.call_args
        style = call.kwargs.get("style") or call.args[2]
        assert "Ult. Actualizacion" in style.summary_rows
        assert style.summary_rows["Ult. Actualizacion"] == "06/03/2026"


class TestNombreReporte:
    def test_sin_supervisor(self):
        assert _nombre_reporte("2026-03-01") == "Mision Posible 03-2026"

    def test_con_supervisor(self):
        assert _nombre_reporte("2026-03-01", "Ana") == "Mision Posible Ana 03-2026"
