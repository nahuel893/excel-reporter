"""
Unit tests for ReporteGeneralBadieService.

Mocks DataLoader and patches DATA_OUTPUT to a tmp_path.
Verifies that the service:
  - calls the correct DataLoader methods with expanded date range
  - creates an Excel file in the expected output directory
  - returns a ReporteGeneralBadieResult with correct metadata
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import config.settings as _settings
from src.core.data_loader import DataLoader
from src.services.reporte_general_badie.service import (
    ReporteGeneralBadieConfig,
    ReporteGeneralBadieResult,
    ReporteGeneralBadieService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loader() -> MagicMock:
    loader = MagicMock(spec=DataLoader)
    loader.get_sucursales.return_value = pd.DataFrame(
        {"sucursal": ["CASA CENTRAL", "SUCURSAL CAFAYATE"]}
    )
    loader.get_ventas_mensuales_ccu.return_value = pd.DataFrame(
        {
            "sucursal": ["CASA CENTRAL"],
            "generico": ["CERVEZAS"],
            "anio": [2026],
            "trimestre": [2],
            "bultos": [1000],
        }
    )
    loader.get_cobertura_clientes_ccu.return_value = pd.DataFrame(
        {
            "sucursal": ["CASA CENTRAL"],
            "anio": [2026],
            "trimestre": [2],
            "id_cliente": [101],
            "bultos": [10],
            "bultos_sin_regalos": [8],
            "bultos_aguas_danone": [4],
            "bultos_aguas_danone_sin_regalos": [4],
            "meses_con_compra": [3],
        }
    )
    return loader


def _basic_config(nombre: str = "Reporte General Badie") -> ReporteGeneralBadieConfig:
    return ReporteGeneralBadieConfig(
        fecha_desde="2026-04-01",
        fecha_hasta="2026-04-30",
        nombre_archivo=nombre,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_creates_excel_file(self, tmp_path):
        service = ReporteGeneralBadieService(data_loader=_make_loader())
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        assert result.ruta_archivo.exists()
        assert result.ruta_archivo.suffix == ".xlsx"

    def test_result_type(self, tmp_path):
        service = ReporteGeneralBadieService(data_loader=_make_loader())
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        assert isinstance(result, ReporteGeneralBadieResult)

    def test_registros_ventas_count(self, tmp_path):
        service = ReporteGeneralBadieService(data_loader=_make_loader())
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        assert result.registros_ventas == 1

    def test_registros_cobertura_count(self, tmp_path):
        service = ReporteGeneralBadieService(data_loader=_make_loader())
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        assert result.registros_cobertura == 1

    def test_sucursales_count(self, tmp_path):
        service = ReporteGeneralBadieService(data_loader=_make_loader())
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        assert result.sucursales == 2

    def test_trimestres_en_dropdown_minimum(self, tmp_path):
        """Normal dropdown: 2024-Q1 → 2026-Q2 = 10 quarters."""
        service = ReporteGeneralBadieService(data_loader=_make_loader())
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        assert result.trimestres_en_dropdown == 10

    def test_trimestres_extendido(self, tmp_path):
        """Extended dropdown: 2022-Q1 → 2026-Q2 = 18 quarters."""
        service = ReporteGeneralBadieService(data_loader=_make_loader())
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        assert result.trimestres_en_dropdown_extendido == 18

    def test_extended_file_is_created(self, tmp_path):
        service = ReporteGeneralBadieService(data_loader=_make_loader())
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        assert result.ruta_archivo_extendido.exists()
        assert "EXTENDIDO" in result.ruta_archivo_extendido.name

    def test_output_file_named_correctly(self, tmp_path):
        service = ReporteGeneralBadieService(data_loader=_make_loader())
        config = _basic_config("Mi Reporte")
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        assert result.ruta_archivo.name == "Mi Reporte.xlsx"

    def test_output_dir_is_period_scoped(self, tmp_path):
        service = ReporteGeneralBadieService(data_loader=_make_loader())
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        # Should be under reporte-general-badie/YYYY-MM/
        assert result.ruta_archivo.parent.name == "2026-04"
        assert result.ruta_archivo.parent.parent.name == "reporte-general-badie"


# ---------------------------------------------------------------------------
# DataLoader call contract
# ---------------------------------------------------------------------------


class TestDataLoaderCalls:
    def test_calls_get_sucursales(self, tmp_path):
        loader = _make_loader()
        service = ReporteGeneralBadieService(data_loader=loader)
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            service.generar_reporte(config)
        loader.get_sucursales.assert_called_once()

    def test_calls_get_ventas_for_both_normal_and_extended(self, tmp_path):
        """Service must query ventas twice: normal (2024-01-01) and extended (2022-01-01)."""
        loader = _make_loader()
        service = ReporteGeneralBadieService(data_loader=loader)
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            service.generar_reporte(config)
        all_calls = loader.get_ventas_mensuales_ccu.call_args_list
        desdes = {call[0][0] for call in all_calls}
        assert "2024-01-01" in desdes
        assert "2022-01-01" in desdes

    def test_calls_get_cobertura_for_both_normal_and_extended(self, tmp_path):
        """Same dual-call expectation for cobertura."""
        loader = _make_loader()
        service = ReporteGeneralBadieService(data_loader=loader)
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            service.generar_reporte(config)
        all_calls = loader.get_cobertura_clientes_ccu.call_args_list
        desdes = {call[0][0] for call in all_calls}
        assert "2024-01-01" in desdes
        assert "2022-01-01" in desdes


# ---------------------------------------------------------------------------
# Default filename
# ---------------------------------------------------------------------------


class TestDefaultFilename:
    def test_default_nombre_archivo_when_none(self, tmp_path):
        loader = _make_loader()
        service = ReporteGeneralBadieService(data_loader=loader)
        config = ReporteGeneralBadieConfig(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
            nombre_archivo=None,
        )
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        assert result.ruta_archivo.name == "Reporte General Badie.xlsx"


# ---------------------------------------------------------------------------
# Sucursales sorted
# ---------------------------------------------------------------------------


class TestSucursalesSorted:
    def test_sucursales_deduplicated_and_sorted(self, tmp_path):
        """get_sucursales may return duplicates or unsorted — service must sort+dedup."""
        loader = _make_loader()
        loader.get_sucursales.return_value = pd.DataFrame(
            {"sucursal": ["SUCURSAL CAFAYATE", "CASA CENTRAL", "CASA CENTRAL"]}
        )
        service = ReporteGeneralBadieService(data_loader=loader)
        config = _basic_config()
        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)
        # 2 unique sucursales (CASA CENTRAL deduped)
        assert result.sucursales == 2
