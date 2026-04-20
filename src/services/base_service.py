"""
BaseService - Clase base para servicios de reportes.
Proporciona funcionalidad comun para todos los servicios:
- Inyeccion de dependencias (DataLoader)
- Metodos utilitarios compartidos
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from src.core.data_loader import DataLoader
from src.core.output_paths import Granularity, service_output_dir


@dataclass
class BaseReporteConfig:
    """Configuracion base para reportes."""
    fecha_desde: str
    fecha_hasta: str
    nombre_archivo: str | None = None

    def __post_init__(self):
        if self.nombre_archivo is None:
            self.nombre_archivo = f"reporte_{self.fecha_desde}_{self.fecha_hasta}"


@dataclass
class BaseReporteResult:
    """Resultado base de generacion de reporte."""
    ruta_archivo: Path
    registros_procesados: int


class BaseService(ABC):
    """
    Clase base abstracta para servicios de reportes.

    Todos los servicios de reportes deben heredar de esta clase
    e implementar el metodo generar_reporte.
    """

    SERVICE_SLUG: ClassVar[str] = ""
    GRANULARITY: ClassVar[Granularity] = "month"

    def __init__(self, data_loader: DataLoader | None = None):
        """
        Inicializa el servicio.

        Args:
            data_loader: DataLoader para acceso a datos. Si es None, crea uno por defecto.
        """
        self._data_loader = data_loader

    @property
    def data_loader(self) -> DataLoader:
        """Obtiene el DataLoader, creandolo si no existe."""
        if self._data_loader is None:
            self._data_loader = DataLoader()
        return self._data_loader

    @abstractmethod
    def generar_reporte(self, config: Any) -> Any:
        """
        Genera un reporte.

        Args:
            config: Configuracion del reporte (especifica de cada servicio)

        Returns:
            Resultado del reporte (especifico de cada servicio)
        """
        pass

    def _output_dir(self, fecha_desde: str | None) -> Path:
        """Compute the service-scoped output directory path (does NOT create it).

        Args:
            fecha_desde: Date string (YYYY-MM-DD or ISO format) or None for today.

        Returns:
            Path under DATA_OUTPUT/{SERVICE_SLUG}/{period}.

        Raises:
            NotImplementedError: If subclass has not set SERVICE_SLUG.
        """
        if not self.SERVICE_SLUG:
            raise NotImplementedError(
                f"{type(self).__name__} must set SERVICE_SLUG class attribute"
            )
        return service_output_dir(self.SERVICE_SLUG, fecha_desde, self.GRANULARITY)

    def validar_fechas(self, fecha_desde: str, fecha_hasta: str) -> bool:
        """
        Valida que las fechas tengan formato correcto.

        Args:
            fecha_desde: Fecha inicio
            fecha_hasta: Fecha fin

        Returns:
            True si las fechas son validas
        """
        from datetime import datetime
        try:
            datetime.strptime(fecha_desde, "%Y-%m-%d")
            datetime.strptime(fecha_hasta, "%Y-%m-%d")
            return True
        except ValueError:
            return False
