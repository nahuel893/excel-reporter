"""
VentasService - Servicio para generacion de reportes de ventas.

Orquesta el flujo completo: extraccion, procesamiento y generacion de Excel.
"""
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

from config.settings import COLUMN_NAMES
from src.core.base_processor import calcular_info_dias
from src.core.data_loader import DataLoader
from src.core.excel_writer import generar_excel, SheetStyle, ColumnFormat, ColumnGroup
from src.services.base_service import BaseService
from src.services.ventas.processor import completar_combinaciones, procesar_ventas, procesar_ventas_diarias

# Configuracion base de formatos para ventas
VENTAS_COLUMN_FORMATS = {
    COLUMN_NAMES["cant_generico"]: ColumnFormat(width=15),
    COLUMN_NAMES["tend_generico"]: ColumnFormat(width=15),
    COLUMN_NAMES["monto_generico"]: ColumnFormat(number_format='$ #,##0', width=15),
    COLUMN_NAMES["total_marca"]: ColumnFormat(width=11),
    COLUMN_NAMES["tend_marca"]: ColumnFormat(width=11),
    COLUMN_NAMES["monto_marca"]: ColumnFormat(number_format='$ #,##0', width=15),
}


def _crear_estilo_ventas(
    columnas_dias: list[str],
    info_dias: dict[str, int],
    dias_visibles: int = 2
) -> SheetStyle:
    """
    Crea el estilo para el reporte de ventas con grupos de columnas.

    Args:
        columnas_dias: Lista de nombres de columnas de dias
        info_dias: Diccionario con info de dias habiles para mostrar en encabezado
        dias_visibles: Cantidad de dias al final que no se agrupan (default: 2)

    Returns:
        SheetStyle configurado con el grupo de dias y filas de resumen
    """
    groups = []

    # Solo agrupar si hay mas dias que los visibles
    if len(columnas_dias) > dias_visibles:
        # Agrupar desde el primer dia hasta (total - dias_visibles)
        start_col = columnas_dias[0]
        end_col = columnas_dias[-(dias_visibles + 1)]
        groups.append(ColumnGroup(start_col=start_col, end_col=end_col, collapsed=True))

    return SheetStyle(
        column_formats=VENTAS_COLUMN_FORMATS,
        column_groups=groups,
        summary_rows=info_dias
    )


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
        Genera un reporte de ventas completo con desglose diario.

        Args:
            config: Configuracion del reporte.

        Returns:
            ReporteVentasResult con informacion del reporte generado.
        """
        # 1. Extraer datos diarios
        df_ventas = self.data_loader.get_ventas_diarias(
            config.fecha_desde,
            config.fecha_hasta,
            config.genericos
        )
        df_sucursales = self.data_loader.get_sucursales()
        df_articulos = self.data_loader.get_articulos(config.genericos)

        # 2. Procesar datos (formato final con dias como columnas)
        df_procesado = procesar_ventas_diarias(
            df_ventas,
            config.fecha_desde,
            config.fecha_hasta
        )

        # 3. Detectar columnas de dias (entre Marca y Total)
        columnas = list(df_procesado.columns)
        idx_marca = columnas.index(COLUMN_NAMES["marca"])
        idx_total = columnas.index(COLUMN_NAMES["total_marca"])
        columnas_dias = columnas[idx_marca + 1:idx_total]

        # 4. Calcular info de dias habiles
        info_dias = calcular_info_dias(config.fecha_desde, config.fecha_hasta)

        # 5. Crear estilo con grupo de dias e info de resumen
        style = _crear_estilo_ventas(columnas_dias, info_dias)

        # 6. Generar Excel
        ruta = generar_excel(df_procesado, config.nombre_archivo, sheet_name="Ventas", style=style)

        # 7. Construir resultado
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
