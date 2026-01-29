import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch

from src.services.ventas import VentasService, ReporteVentasConfig, ReporteVentasResult
from src.core.data_loader import DataLoader


class TestReporteVentasConfig:
    """Tests para ReporteVentasConfig."""

    def test_nombre_archivo_por_defecto(self):
        """Si no se especifica nombre, se genera automaticamente."""
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31"
        )
        assert config.nombre_archivo == "ventas_2026-01-01_2026-01-31"

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

    @patch("src.services.ventas.service.generar_excel")
    @patch("src.services.ventas.service.procesar_ventas")
    @patch("src.services.ventas.service.completar_combinaciones")
    def test_generar_reporte_llama_funciones_correctamente(
        self, mock_completar, mock_procesar, mock_excel, mock_loader
    ):
        """Verifica que generar_reporte orquesta correctamente."""
        # Configurar mocks
        mock_completar.return_value = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"],
            "cantidad": [100],
            "monto": [5000]
        })
        mock_procesar.return_value = pd.DataFrame({"col": [1, 2]})
        mock_excel.return_value = Path("/tmp/test.xlsx")

        # Ejecutar
        service = VentasService(data_loader=mock_loader)
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31"
        )
        result = service.generar_reporte(config)

        # Verificar llamadas
        mock_loader.get_ventas.assert_called_once_with("2026-01-01", "2026-01-31", None)
        mock_loader.get_sucursales.assert_called_once()
        mock_loader.get_articulos.assert_called_once_with(None)
        mock_completar.assert_called_once()
        mock_procesar.assert_called_once()
        mock_excel.assert_called_once()

    @patch("src.services.ventas.service.generar_excel")
    @patch("src.services.ventas.service.procesar_ventas")
    @patch("src.services.ventas.service.completar_combinaciones")
    def test_generar_reporte_retorna_result(
        self, mock_completar, mock_procesar, mock_excel, mock_loader
    ):
        """Verifica que generar_reporte retorna ReporteVentasResult."""
        mock_completar.return_value = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"],
            "cantidad": [100],
            "monto": [5000]
        })
        mock_procesar.return_value = pd.DataFrame({"col": [1, 2]})
        mock_excel.return_value = Path("/tmp/test.xlsx")

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

    @patch("src.services.ventas.service.generar_excel")
    @patch("src.services.ventas.service.procesar_ventas")
    @patch("src.services.ventas.service.completar_combinaciones")
    def test_generar_reporte_con_genericos(
        self, mock_completar, mock_procesar, mock_excel, mock_loader
    ):
        """Verifica que los genericos se pasan correctamente."""
        mock_completar.return_value = pd.DataFrame({
            "sucursal": ["SUC1"],
            "generico": ["CERVEZAS"],
            "marca": ["CORONA"],
            "cantidad": [100],
            "monto": [5000]
        })
        mock_procesar.return_value = pd.DataFrame({"col": [1]})
        mock_excel.return_value = Path("/tmp/test.xlsx")

        service = VentasService(data_loader=mock_loader)
        config = ReporteVentasConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-01-31",
            genericos=["CERVEZAS", "AGUAS"]
        )
        service.generar_reporte(config)

        # Verificar que los genericos se pasaron
        mock_loader.get_ventas.assert_called_once_with(
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
