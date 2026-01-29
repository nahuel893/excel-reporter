"""
VentasService - Servicio para generacion de reportes de ventas.

Orquesta el flujo completo: extraccion, procesamiento y generacion de Excel.
"""
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

from src.core.data_loader import DataLoader
from src.core.excel_writer import generar_excel
from src.services.base_service import BaseService
from src.services.ventas.processor import completar_combinaciones, procesar_ventas


@dataclass
class ReporteVentasConfig:
    """Configuracion para generar un reporte de ventas."""
    fecha_desde: str
    fecha_hasta: str
    genericos: list[str] | None = None
    nombre_archivo: str | None = None

    def __post_init__(self):
        if self.nombre_archivo is None:
            self.nombre_archivo = f"ventas_{self.fecha_desde}_{self.fecha_hasta}"


@dataclass
class ReporteVentasResult:
    """Resultado de la generacion de un reporte."""
    ruta_archivo: Path
    registros_ventas: int
    registros_procesados: int
    sucursales: int
    genericos_incluidos: list[str]


class VentasService(BaseService):
    """
    Servicio para generacion de reportes de ventas.

    Orquesta el flujo completo: extraccion, procesamiento y generacion de Excel.
    """

    def generar_reporte(self, config: ReporteVentasConfig) -> ReporteVentasResult:
        """
        Genera un reporte de ventas completo.

        Args:
            config: Configuracion del reporte.

        Returns:
            ReporteVentasResult con informacion del reporte generado.
        """
        # 1. Extraer datos
        df_ventas = self.data_loader.get_ventas(
            config.fecha_desde,
            config.fecha_hasta,
            config.genericos
        )
        df_sucursales = self.data_loader.get_sucursales()
        df_articulos = self.data_loader.get_articulos(config.genericos)

        # 2. Completar combinaciones faltantes
        df_completo = completar_combinaciones(df_ventas, df_sucursales, df_articulos)

        # 3. Procesar datos (formato final con tendencias)
        df_procesado = procesar_ventas(
            df_completo,
            config.fecha_desde,
            config.fecha_hasta
        )

        # 4. Generar Excel
        ruta = generar_excel(df_procesado, config.nombre_archivo, sheet_name="Ventas")

        # 5. Construir resultado
        genericos_incluidos = df_articulos["generico"].unique().tolist() if not df_articulos.empty else []

        return ReporteVentasResult(
            ruta_archivo=ruta,
            registros_ventas=len(df_ventas),
            registros_procesados=len(df_procesado),
            sucursales=len(df_sucursales),
            genericos_incluidos=genericos_incluidos
        )

    def obtener_ventas(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        genericos: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Obtiene datos de ventas procesados sin generar Excel.

        util para analisis programatico o integracion con otros sistemas.

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD'
            genericos: Lista de genericos a filtrar.

        Returns:
            DataFrame con ventas procesadas.
        """
        df_ventas = self.data_loader.get_ventas(fecha_desde, fecha_hasta, genericos)
        df_sucursales = self.data_loader.get_sucursales()
        df_articulos = self.data_loader.get_articulos(genericos)

        df_completo = completar_combinaciones(df_ventas, df_sucursales, df_articulos)

        return procesar_ventas(df_completo, fecha_desde, fecha_hasta)

    def listar_genericos_disponibles(self) -> list[str]:
        """Obtiene lista de genericos disponibles en la base de datos."""
        df = self.data_loader.get_articulos()
        return sorted(df["generico"].unique().tolist())

    def listar_sucursales(self) -> list[str]:
        """Obtiene lista de sucursales disponibles."""
        df = self.data_loader.get_sucursales()
        return df["sucursal"].tolist()
