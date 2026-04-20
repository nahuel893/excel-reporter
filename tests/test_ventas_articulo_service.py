"""Tests for VentasArticuloService."""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest


def _make_loader(ventas_rows=None, descripcion="SCHNEIDER 710"):
    """Build a mock DataLoader that returns given ventas rows and descripcion."""
    loader = MagicMock()
    if ventas_rows is None:
        ventas_rows = []
    df = pd.DataFrame(ventas_rows, columns=["fecha_comprobante", "bultos"])
    loader.get_ventas_diarias_articulo.return_value = df
    loader.get_articulo_descripcion.return_value = descripcion
    return loader


def _make_config(tmp_path, id_articulo=23179, id_sucursal=1,
                 fecha_desde="2026-04-01", fecha_hasta="2026-04-30"):
    from src.services.ventas_articulo.service import VentasArticuloConfig
    return VentasArticuloConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        id_articulo=id_articulo,
        id_sucursal=id_sucursal,
        nombre_archivo="test_articulo",
        output_dir=tmp_path,
    )


class TestHappyPath:
    def test_service_happy_path_month_with_sales(self, tmp_path):
        """Mock loader with 5 rows → result has expected stats and file exists."""
        from src.services.ventas_articulo.service import VentasArticuloService

        rows = [
            (date(2026, 4, 2), 100.0),
            (date(2026, 4, 3), 50.0),
            (date(2026, 4, 7), 75.0),
            (date(2026, 4, 9), 30.0),
            (date(2026, 4, 14), 20.0),
        ]
        loader = _make_loader(rows)
        config = _make_config(tmp_path)

        service = VentasArticuloService(data_loader=loader)
        result = service.generar_reporte(config)

        assert result.dias_con_venta >= 1
        assert result.registros_procesados == 30
        assert result.total_bultos > 0
        assert len(result.hojas) == 1
        assert Path(result.ruta_archivo).exists()


class TestEmptyMonth:
    def test_service_empty_month(self, tmp_path):
        """Loader returns empty df → dias_con_venta=0, total_bultos=0.0, file created."""
        from src.services.ventas_articulo.service import VentasArticuloService

        loader = _make_loader([], descripcion="FOO")
        config = _make_config(tmp_path)

        service = VentasArticuloService(data_loader=loader)
        result = service.generar_reporte(config)

        assert result.dias_con_venta == 0
        assert result.total_bultos == 0.0
        assert Path(result.ruta_archivo).exists()


class TestUnknownArticle:
    def test_service_unknown_article(self, tmp_path):
        """Loader returns None for descripcion → articulo_nombre fallback."""
        from src.services.ventas_articulo.service import VentasArticuloService, VentasArticuloConfig

        loader = _make_loader([], descripcion=None)
        config = VentasArticuloConfig(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
            id_articulo=99999,
            id_sucursal=1,
            nombre_archivo="test_unknown",
            output_dir=tmp_path,
        )

        service = VentasArticuloService(data_loader=loader)
        result = service.generar_reporte(config)

        assert result.articulo_nombre == "Articulo 99999"


class TestMissingIdValidation:
    def test_service_missing_id_articulo_raises(self, tmp_path):
        """Config with id_articulo=None → ValueError mentioning id_articulo."""
        from src.services.ventas_articulo.service import VentasArticuloService, VentasArticuloConfig

        loader = _make_loader()
        config = VentasArticuloConfig(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
            id_articulo=None,
            id_sucursal=1,
            output_dir=tmp_path,
        )

        service = VentasArticuloService(data_loader=loader)
        with pytest.raises(ValueError, match="id_articulo"):
            service.generar_reporte(config)

    def test_service_missing_id_sucursal_raises(self, tmp_path):
        """Config with id_sucursal=None → ValueError mentioning id_sucursal."""
        from src.services.ventas_articulo.service import VentasArticuloService, VentasArticuloConfig

        loader = _make_loader()
        config = VentasArticuloConfig(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
            id_articulo=23179,
            id_sucursal=None,
            output_dir=tmp_path,
        )

        service = VentasArticuloService(data_loader=loader)
        with pytest.raises(ValueError, match="id_sucursal"):
            service.generar_reporte(config)


class TestPrimaryRule:
    def test_service_returns_float_not_int(self, tmp_path):
        """PRIMARY RULE: total_bultos must be float, never int or bool."""
        from src.services.ventas_articulo.service import VentasArticuloService

        rows = [(date(2026, 4, 2), 100.0)]
        loader = _make_loader(rows)
        config = _make_config(tmp_path)

        service = VentasArticuloService(data_loader=loader)
        result = service.generar_reporte(config)

        assert isinstance(result.total_bultos, float)
        assert not isinstance(result.total_bultos, bool)
