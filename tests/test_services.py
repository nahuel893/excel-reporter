import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch

from src.services.ventas import VentasService, ReporteVentasConfig, ReporteVentasResult
from src.core.data_loader import DataLoader


class TestReporteVentasConfig:
    """Tests para ReporteVentasConfig."""

    def test_nombre_archivo_none_por_defecto(self):
        """Si no se especifica nombre, queda None (el servicio lo genera con la fecha real)."""
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31"
        )
        assert config.nombre_archivo is None

    def test_sin_unidad(self):
        """Config ya no tiene campo unidad (se generan ambas hojas)."""
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31"
        )
        assert not hasattr(config, "unidad")

    def test_nombre_archivo_personalizado(self):
        """Se puede especificar nombre personalizado."""
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            nombre_archivo="mi_reporte"
        )
        assert config.nombre_archivo == "mi_reporte"

    def test_genericos_none_por_defecto(self):
        """Genericos es None por defecto."""
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31"
        )
        assert config.genericos is None

    def test_genericos_como_lista(self):
        """Se pueden pasar genericos como lista."""
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            genericos=["CERVEZAS", "AGUAS"]
        )
        assert config.genericos == ["CERVEZAS", "AGUAS"]


class TestVentasServiceUnit:
    """Tests unitarios para VentasService (con mocks)."""

    @pytest.fixture
    def mock_loader(self):
        """Crea un mock de DataLoader."""
        loader = Mock(spec=DataLoader)

        # Configurar respuestas de los metodos
        loader.get_ventas_diarias.return_value = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"],
            "fecha": pd.to_datetime(["2026-01-15"]),
            "cantidad": [100],
            "cantidad_htls": [50],
            "monto": [5000]
        })

        loader.get_ventas.return_value = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"],
            "cantidad": [100],
            "monto": [5000]
        })

        loader.get_sucursales.return_value = pd.DataFrame({
            "sucursal": ["SUC1"]
        })

        loader.get_articulos.return_value = pd.DataFrame({
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"]
        })

        return loader

    def test_service_acepta_data_loader(self, mock_loader):
        """Verifica que el servicio acepta un DataLoader inyectado."""
        service = VentasService(data_loader=mock_loader)
        assert service.data_loader is mock_loader

    def test_service_crea_loader_por_defecto(self):
        """Si no se pasa DataLoader, se crea uno por defecto."""
        service = VentasService()
        assert isinstance(service.data_loader, DataLoader)

    @patch("src.services.ventas.service.ExcelWriter")
    def test_generar_reporte_crea_dos_hojas(self, mock_writer_cls, mock_loader):
        """Verifica que generar_reporte crea ambas hojas (Bultos y HTLs)."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        service = VentasService(data_loader=mock_loader)
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31"
        )
        result = service.generar_reporte(config)

        # Verificar que se crearon 2 hojas
        assert mock_writer.add_sheet.call_count == 2
        sheet_names = [call.kwargs.get("sheet_name") or call.args[1] for call in mock_writer.add_sheet.call_args_list]
        assert "Ventas Bultos" in sheet_names
        assert "Ventas HTLs" in sheet_names

    @patch("src.services.ventas.service.ExcelWriter")
    def test_generar_reporte_retorna_result(self, mock_writer_cls, mock_loader):
        """Verifica que generar_reporte retorna ReporteVentasResult."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        service = VentasService(data_loader=mock_loader)
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31"
        )
        result = service.generar_reporte(config)

        assert isinstance(result, ReporteVentasResult)
        assert result.ruta_archivo == Path("/tmp/test.xlsx")
        assert result.registros_ventas == 1
        assert result.sucursales == 1
        assert result.hojas == ["Ventas Bultos", "Ventas HTLs"]

    @patch("src.services.ventas.service.ExcelWriter")
    def test_generar_reporte_con_genericos(self, mock_writer_cls, mock_loader):
        """Verifica que los genericos se pasan correctamente."""
        mock_writer = Mock()
        mock_writer.save.return_value = Path("/tmp/test.xlsx")
        mock_writer_cls.return_value = mock_writer

        service = VentasService(data_loader=mock_loader)
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            genericos=["CERVEZAS", "AGUAS"]
        )
        service.generar_reporte(config)

        # Verificar que los genericos se pasaron
        mock_loader.get_ventas_diarias.assert_called_once_with(
            "2026-01-01", "2026-01-31", ["CERVEZAS", "AGUAS"]
        )
        mock_loader.get_articulos.assert_called_once_with(["CERVEZAS", "AGUAS"])


class TestVentasServiceIntegration:
    """Tests de integracion para VentasService (requieren BD)."""

    @pytest.fixture
    def service(self):
        return VentasService()

    def test_listar_genericos_disponibles(self, service):
        """Verifica que se pueden listar genericos."""
        genericos = service.listar_genericos_disponibles()
        assert isinstance(genericos, list)

    def test_listar_sucursales(self, service):
        """Verifica que se pueden listar sucursales."""
        sucursales = service.listar_sucursales()
        assert isinstance(sucursales, list)

    def test_obtener_ventas_retorna_dataframe(self, service):
        """Verifica que obtener_ventas retorna DataFrame."""
        df = service.obtener_ventas("2025-01-01", "2025-01-31")
        assert isinstance(df, pd.DataFrame)
