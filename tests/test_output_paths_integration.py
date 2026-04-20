"""Integration tests: per-service folder assertions and capture sibling."""
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import config.settings as _settings
from src.core.data_loader import DataLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ventas_loader() -> MagicMock:
    """Minimal DataLoader mock for VentasService."""
    loader = MagicMock(spec=DataLoader)

    loader.get_ventas_diarias_con_ruta.return_value = pd.DataFrame({
        "sucursal": ["CASA CENTRAL"],
        "generico": ["CERVEZAS"],
        "marca": ["SALTA"],
        "fecha": pd.to_datetime(["2026-04-15"]),
        "id_ruta": [85],
        "cantidad": [100],
        "cantidad_htls": [50],
        "monto": [5000],
        "descuentos": [0],
        "cupo_generico": ["CERVEZAS"],
    })
    loader.get_sucursales.return_value = pd.DataFrame({"sucursal": ["CASA CENTRAL"]})
    loader.get_articulos.return_value = pd.DataFrame({
        "generico": ["CERVEZAS"],
        "marca": ["SALTA"],
    })
    loader.get_cobertura_preventista_generico.return_value = pd.DataFrame(
        columns=["sucursal", "generico", "clientes_compradores", "id_ruta"]
    )
    loader.get_cobertura_preventista_marca.return_value = pd.DataFrame(
        columns=["sucursal", "marca", "clientes_compradores", "id_ruta"]
    )
    loader.get_ventas_historico_mmaa.side_effect = Exception("no data")
    loader.get_cupos.side_effect = Exception("no data")
    return loader


def _make_stock_loader() -> MagicMock:
    """Minimal DataLoader mock for StockDiarioService."""
    loader = MagicMock(spec=DataLoader)
    loader.get_stock_diario.return_value = pd.DataFrame({
        "sucursal": ["CASA CENTRAL"],
        "id_articulo": [1],
        "generico": ["CERVEZAS"],
        "marca": ["SALTA"],
        "des_articulo": ["SALTA 1L"],
        "cant_bultos": [100],
        "cant_htls": [10],
    })
    return loader


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVentasWritesUnderSlugAndPeriod:
    def test_ventas_writes_under_slug_and_period(self, tmp_path):
        """VentasService writes to data/output/ventas/YYYY-MM/."""
        from src.services.ventas.service import VentasService, ReporteVentasConfig

        config = ReporteVentasConfig(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
            con_slicers=False,
            con_cobertura=False,
        )
        service = VentasService(data_loader=_make_ventas_loader())

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)

        expected_parent = tmp_path / "ventas" / "2026-04"
        assert result.ruta_archivo.parent == expected_parent
        assert result.ruta_archivo.exists()


class TestStockDiarioDaySubfolder:
    def test_stock_diario_day_subfolder(self, tmp_path):
        """StockDiarioService writes to data/output/stock-diario/YYYY-MM-DD/."""
        from src.services.stock_diario.service import StockDiarioService, StockDiarioConfig

        config = StockDiarioConfig(
            fecha_desde="2026-04-15",
            fecha_hasta="2026-04-15",
        )
        service = StockDiarioService(data_loader=_make_stock_loader())

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)

        assert len(result.archivos_generados) == 1
        ruta = result.archivos_generados[0]
        assert ruta.parent == tmp_path / "stock-diario" / "2026-04-15"
        assert ruta.exists()


class TestGraficosCoberturaNoTimestamp:
    def test_graficos_cobertura_no_timestamp(self, tmp_path):
        """GraficosCoberturaService uses YYYY-MM dir, not timestamp subdir."""
        from src.services.graficos_cobertura.service import GraficosCoberturaService
        from src.services.graficos_cobertura.config import GraficosCoberturaConfig

        loader = MagicMock(spec=DataLoader)
        loader.get_articulos.return_value = pd.DataFrame({
            "generico": ["CERVEZAS"],
            "marca": ["SALTA"],
        })
        loader.get_cobertura_graficos_marca_ruta.return_value = pd.DataFrame({
            "anio": [2026], "mes": [3], "id_ruta": [85],
            "marca": ["SALTA"], "clientes": [100],
        })
        loader.get_cobertura_graficos_generico_ruta.return_value = pd.DataFrame({
            "anio": [2026], "mes": [3], "id_ruta": [85],
            "generico": ["CERVEZAS"], "clientes": [100],
        })
        loader.get_cobertura_graficos_marca_sucursal.return_value = pd.DataFrame({
            "anio": [2026], "mes": [3], "marca": ["SALTA"], "clientes": [200],
        })
        loader.get_cobertura_graficos_generico_sucursal.return_value = pd.DataFrame({
            "anio": [2026], "mes": [3], "generico": ["CERVEZAS"], "clientes": [500],
        })
        loader.get_cobertura_graficos_aguas_sucursal.return_value = pd.DataFrame(
            columns=["anio", "mes", "id_sucursal", "subdivision_aguas", "clientes"]
        )

        config = GraficosCoberturaConfig(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
            con_aguas=False,
        )
        service = GraficosCoberturaService(data_loader=loader)

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)

        # Should be directly tmp_path/graficos-cobertura/2026-04 (no timestamp)
        expected = tmp_path / "graficos-cobertura" / "2026-04"
        assert result.ruta_directorio == expected
        import re
        assert not re.search(r"\d{4}-\d{2}-\d{2}_\d{6}", str(result.ruta_directorio))


class TestRerunOverwrites:
    def test_rerun_overwrites(self, tmp_path):
        """Running VentasService twice for same period produces same path (overwrite)."""
        from src.services.ventas.service import VentasService, ReporteVentasConfig

        config = ReporteVentasConfig(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
            nombre_archivo="test-overwrite",
            con_slicers=False,
            con_cobertura=False,
        )
        service = VentasService(data_loader=_make_ventas_loader())

        with patch.object(_settings, "DATA_OUTPUT", tmp_path):
            result1 = service.generar_reporte(config)
            result2 = service.generar_reporte(config)

        assert result1.ruta_archivo == result2.ruta_archivo
