"""Tests for GraficosCoberturaService orchestration."""
import re
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import config.settings as _settings
from src.core.data_loader import DataLoader
from src.services.graficos_cobertura.config import GraficosCoberturaConfig
from src.services.graficos_cobertura.service import (
    GraficosCoberturaResult,
    GraficosCoberturaService,
)


def _mock_loader() -> MagicMock:
    """Build a mocked DataLoader returning minimal valid DataFrames."""
    loader = MagicMock(spec=DataLoader)

    # Articulos mapping
    loader.get_articulos.return_value = pd.DataFrame({
        "generico": ["CERVEZAS", "CERVEZAS"],
        "marca": ["SALTA", "HEINEKEN"],
    })

    # Preventista ruta-grained (used by SALTA CAPITAL + reassign)
    loader.get_cobertura_graficos_marca_ruta.return_value = pd.DataFrame({
        "anio": [2026, 2026],
        "mes": [3, 3],
        "id_ruta": [85, 90],
        "marca": ["SALTA", "HEINEKEN"],
        "clientes": [100, 80],
    })
    loader.get_cobertura_graficos_generico_ruta.return_value = pd.DataFrame({
        "anio": [2026, 2026],
        "mes": [3, 3],
        "id_ruta": [85, 90],
        "generico": ["CERVEZAS", "CERVEZAS"],
        "clientes": [100, 80],
    })

    # Sucursal aggregates (used by other zones). Mock returns different data
    # per invocation based on sucursales arg.
    loader.get_cobertura_graficos_marca_sucursal.return_value = pd.DataFrame({
        "anio": [2026, 2026],
        "mes": [3, 3],
        "marca": ["SALTA", "HEINEKEN"],
        "clientes": [200, 150],
    })
    loader.get_cobertura_graficos_generico_sucursal.return_value = pd.DataFrame({
        "anio": [2026, 2025],
        "mes": [3, 3],
        "generico": ["CERVEZAS", "CERVEZAS"],
        "clientes": [500, 400],
    })

    # Aguas (can be empty — pre-check fallback)
    loader.get_cobertura_graficos_aguas_sucursal.return_value = pd.DataFrame(
        columns=["anio", "mes", "id_sucursal", "subdivision_aguas", "clientes"]
    )

    return loader


def _basic_config(tmp_path, con_aguas=True) -> GraficosCoberturaConfig:
    return GraficosCoberturaConfig(
        fecha_desde="2026-01-01",
        fecha_hasta="2026-04-30",
        id_fuerza_ventas=1,
        con_aguas=con_aguas,
    )


class TestOutputDirectory:
    """RF-021: output directory is YYYY-MM period under data/output/graficos-cobertura/."""

    def test_creates_period_dir(self, tmp_path):
        config = _basic_config(tmp_path)
        service = GraficosCoberturaService(data_loader=_mock_loader())

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)

        parent = result.ruta_directorio.parent
        assert parent.name == "graficos-cobertura"
        # New structure: YYYY-MM (derived from fecha_desde="2026-01-01")
        assert re.fullmatch(r"\d{4}-\d{2}", result.ruta_directorio.name)

    def test_creates_png_subdir(self, tmp_path):
        config = _basic_config(tmp_path)
        service = GraficosCoberturaService(data_loader=_mock_loader())

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)

        assert (result.ruta_directorio / "png").is_dir()


class TestDataLoaderCalls:
    """RF-002..RF-007: all 6 DataLoader methods invoked."""

    def test_calls_all_six_methods(self, tmp_path):
        loader = _mock_loader()
        service = GraficosCoberturaService(data_loader=loader)
        config = _basic_config(tmp_path)

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            service.generar_reporte(config)

        assert loader.get_articulos.called
        assert loader.get_cobertura_graficos_marca_ruta.called
        assert loader.get_cobertura_graficos_generico_ruta.called
        assert loader.get_cobertura_graficos_marca_sucursal.called
        assert loader.get_cobertura_graficos_generico_sucursal.called
        assert loader.get_cobertura_graficos_aguas_sucursal.called

    def test_passes_fv_and_anios_from_config(self, tmp_path):
        loader = _mock_loader()
        service = GraficosCoberturaService(data_loader=loader)
        config = GraficosCoberturaConfig(
            fecha_desde="2025-01-01",
            fecha_hasta="2026-04-30",
            id_fuerza_ventas=2,
        )

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            service.generar_reporte(config)

        call = loader.get_cobertura_graficos_marca_sucursal.call_args
        # First positional/keyword: id_fuerza_ventas=2
        kwargs = call.kwargs
        args = call.args
        fv = kwargs.get("id_fuerza_ventas", args[0] if args else None)
        assert fv == 2


class TestAguasConditional:
    """RF-018: con_aguas=False skips aguas DataLoader + pptx slides."""

    def test_aguas_called_when_con_aguas_true(self, tmp_path):
        loader = _mock_loader()
        service = GraficosCoberturaService(data_loader=loader)
        config = _basic_config(tmp_path, con_aguas=True)

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            service.generar_reporte(config)

        assert loader.get_cobertura_graficos_aguas_sucursal.called

    def test_aguas_skipped_when_con_aguas_false(self, tmp_path):
        loader = _mock_loader()
        service = GraficosCoberturaService(data_loader=loader)
        config = _basic_config(tmp_path, con_aguas=False)

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            service.generar_reporte(config)

        # With con_aguas=False, aguas query is not called
        assert not loader.get_cobertura_graficos_aguas_sucursal.called


class TestResultArtifacts:
    """RF-019, RF-020: Result has xlsx + marca.pptx + generico.pptx paths that exist."""

    def test_result_fields_populated(self, tmp_path):
        service = GraficosCoberturaService(data_loader=_mock_loader())
        config = _basic_config(tmp_path)

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)

        assert isinstance(result, GraficosCoberturaResult)
        assert result.archivo_xlsx.exists()
        assert result.archivo_marca_pptx.exists()
        assert result.archivo_generico_pptx.exists()
        assert result.graficos_generados > 0
        assert "CERVEZAS" in result.genericos_incluidos

    def test_xlsx_filename_is_resumen(self, tmp_path):
        service = GraficosCoberturaService(data_loader=_mock_loader())
        config = _basic_config(tmp_path)

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)

        assert result.archivo_xlsx.name == "resumen.xlsx"
        assert result.archivo_marca_pptx.name == "Marca.pptx"
        assert result.archivo_generico_pptx.name == "Generico.pptx"
