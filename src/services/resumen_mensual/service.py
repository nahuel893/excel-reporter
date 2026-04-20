"""
ResumenMensualService - Servicio para generacion de reportes de resumen mensual.

Orquesta el flujo completo: extraccion, procesamiento y generacion de Excel.
"""
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

from src.core.base_processor import calcular_info_dias
from src.core.data_loader import DataLoader
from src.core.excel_writer import ExcelWriter, SheetStyle, ColumnFormat
from src.core.zonas import aplicar_zonas_virtuales
from src.services.base_service import BaseService
from src.services.resumen_mensual.processor import procesar_resumen_mensual


@dataclass
class ResumenMensualConfig:
    """Configuracion para el reporte de resumen mensual.

    Standalone dataclass; NO hereda de BaseReporteConfig para evitar que
    __post_init__ sobreescriba nombre_archivo=None con un valor por defecto.
    """
    fecha_desde: str           # "YYYY-MM-DD", primer dia del mes
    fecha_hasta: str           # "YYYY-MM-DD", ultimo dia con ventas (o fin de mes)
    genericos: list[str] | None = None
    nombre_archivo: str | None = None
    con_objetivo: bool = False  # False hasta que exista tabla en BD


@dataclass
class ResumenMensualResult:
    """Resultado de la generacion de un reporte de resumen mensual."""
    ruta_archivo: Path
    registros_procesados: int   # total de filas (sucursal, generico) en el archivo (suma de todas las hojas)
    sucursales: int             # cantidad de sucursales unicas en el resultado
    genericos_incluidos: list[str]
    hojas: list[str]            # nombres de hojas = nombres de genericos


def _nombre_reporte(df_dias: pd.DataFrame, fecha_hasta: str) -> str:
    """Genera nombre de archivo: 'Resumen {dd-mm-yyyy}' usando ultima fecha con ventas.

    Args:
        df_dias: DataFrame con columna 'fecha' (ventas de los ultimos dias habiles).
        fecha_hasta: Fecha limite del rango; se usa como fallback si df_dias esta vacio.

    Returns:
        Nombre de archivo sin extension.
    """
    if not df_dias.empty and "fecha" in df_dias.columns:
        ultima_fecha = pd.to_datetime(df_dias["fecha"]).max().strftime("%d-%m-%Y")
    else:
        ultima_fecha = pd.to_datetime(fecha_hasta).strftime("%d-%m-%Y")
    return f"Resumen - {ultima_fecha}"


def _crear_estilo_resumen(info_dias: dict, col_n1: str, col_n2: str) -> SheetStyle:
    """Crea el SheetStyle para las hojas del reporte de resumen mensual.

    Args:
        info_dias: Diccionario con Dias Habiles, Dias Transcurridos, Dias Faltantes.
        col_n1: Nombre de la columna del ultimo dia con ventas (ej: '28-02 Sabado').
        col_n2: Nombre de la columna del penultimo dia con ventas (ej: '27-02 Viernes').

    Returns:
        SheetStyle configurado para el reporte de resumen mensual.
    """
    return SheetStyle(
        numeric_format="#,##0",
        column_formats={
            "Sucursal":            ColumnFormat(width=22),
            "Generico":            ColumnFormat(width=20),
            col_n1:                ColumnFormat(number_format="#,##0", width=12, font_bold=True),
            col_n2:                ColumnFormat(number_format="#,##0", width=12, font_bold=True),
            "Total Ventas":        ColumnFormat(number_format="#,##0", width=13, font_bold=True),
            "Tendencia":           ColumnFormat(number_format="#,##0", width=13, font_bold=True),
            "Ventas Mes Anterior": ColumnFormat(number_format="#,##0", width=15, font_bold=True),
            "Ventas Mismo Mes AA": ColumnFormat(number_format="#,##0", width=16, font_bold=True),
            "Objetivo":            ColumnFormat(number_format="#,##0", width=12, font_bold=True),
            "Tend vs Obj (%)":     ColumnFormat(number_format="#,##0.0", width=14, font_bold=True),
        },
        summary_rows=info_dias,
        as_table=True,
        table_style="TableStyleMedium9",
    )


class ResumenMensualService(BaseService):
    """
    Servicio para generacion de reportes de resumen mensual.

    Orquesta el flujo completo: extraccion de los 4 DataFrames, aplicacion de
    zonas virtuales, procesamiento y generacion del Excel con una hoja por generico.
    """

    SERVICE_SLUG = "resumen-mensual"
    GRANULARITY = "month"

    def generar_reporte(self, config: ResumenMensualConfig) -> ResumenMensualResult:
        """
        Genera un reporte de resumen mensual.

        Genera un archivo Excel con una hoja por cada generico presente en los datos.
        Cada hoja contiene: Vtas Dia N-1, N-2, Total Ventas, Tendencia,
        Ventas Mes Anterior, Ventas Mismo Mes AA, Objetivo, Tend vs Obj (%).

        Args:
            config: Configuracion del reporte.

        Returns:
            ResumenMensualResult con informacion del reporte generado.
        """
        # Normalizar genericos: lista vacia se trata como None (traer todos)
        genericos = config.genericos if config.genericos else None

        # -----------------------------------------------------------------
        # 1. Fetch de los 4 DataFrames
        # -----------------------------------------------------------------
        df_ventas_mes = self.data_loader.get_ventas_resumen_mensual(
            config.fecha_desde, config.fecha_hasta, genericos
        )
        df_dias = self.data_loader.get_ventas_ultimos_dias_habiles(
            config.fecha_desde, config.fecha_hasta, genericos
        )

        try:
            df_ventas_ma = self.data_loader.get_ventas_mes_anterior(
                config.fecha_desde, genericos
            )
        except Exception:
            df_ventas_ma = pd.DataFrame(columns=["sucursal", "generico", "cantidad"])

        try:
            df_ventas_aa = self.data_loader.get_ventas_mismo_mes_anio_anterior(
                config.fecha_desde, config.fecha_hasta, genericos
            )
        except Exception:
            df_ventas_aa = pd.DataFrame(columns=["sucursal", "generico", "cantidad"])

        # -----------------------------------------------------------------
        # 2. Aplicar zonas virtuales a los 4 DataFrames
        #    Para df_ventas_mes, df_ventas_ma, df_ventas_aa: solo tienen 'cantidad',
        #    por lo que aplicar_zonas_virtuales no hara reagrupamiento interno.
        #    Se necesita un groupby explicito despues.
        # -----------------------------------------------------------------
        df_ventas_mes = aplicar_zonas_virtuales(df_ventas_mes)
        if not df_ventas_mes.empty:
            df_ventas_mes = df_ventas_mes.groupby(
                ["sucursal", "generico"], as_index=False
            )["cantidad"].sum()

        df_dias = aplicar_zonas_virtuales(df_dias)
        if not df_dias.empty:
            df_dias = df_dias.groupby(
                ["sucursal", "generico", "fecha"], as_index=False
            )["cantidad"].sum()

        df_ventas_ma = aplicar_zonas_virtuales(df_ventas_ma)
        if not df_ventas_ma.empty:
            df_ventas_ma = df_ventas_ma.groupby(
                ["sucursal", "generico"], as_index=False
            )["cantidad"].sum()

        df_ventas_aa = aplicar_zonas_virtuales(df_ventas_aa)
        if not df_ventas_aa.empty:
            df_ventas_aa = df_ventas_aa.groupby(
                ["sucursal", "generico"], as_index=False
            )["cantidad"].sum()

        # -----------------------------------------------------------------
        # 3. Calcular info de dias habiles
        # -----------------------------------------------------------------
        info_dias = calcular_info_dias(config.fecha_desde, config.fecha_hasta)

        # -----------------------------------------------------------------
        # 4. Procesar datos (una llamada para todos los genericos)
        # -----------------------------------------------------------------
        df_resultado = procesar_resumen_mensual(
            df_ventas_mes,
            df_dias,
            df_ventas_ma,
            df_ventas_aa,
            config.fecha_desde,
            config.fecha_hasta,
            config.con_objetivo,
        )

        # -----------------------------------------------------------------
        # 5. Generar Excel: una hoja por generico
        # -----------------------------------------------------------------
        nombre = config.nombre_archivo or _nombre_reporte(df_dias, config.fecha_hasta)
        out = self._output_dir(config.fecha_desde)
        out.mkdir(parents=True, exist_ok=True)
        writer = ExcelWriter(nombre, output_dir=out)
        genericos_resultado = (
            df_resultado["Generico"].unique().tolist() if not df_resultado.empty else []
        )

        # Detectar nombres dinámicos de columnas N-1 y N-2 (posiciones 2 y 3)
        cols = list(df_resultado.columns)
        col_n1 = cols[2] if len(cols) > 2 else "Vtas Dia N-1"
        col_n2 = cols[3] if len(cols) > 3 else "Vtas Dia N-2"

        style = _crear_estilo_resumen(info_dias, col_n1, col_n2)

        for generico in genericos_resultado:
            df_hoja = df_resultado[df_resultado["Generico"] == generico].copy()
            sheet_name = generico[:31]  # Excel max 31 caracteres
            writer.add_sheet(df_hoja, sheet_name=sheet_name, style=style)

        ruta = writer.save()

        # -----------------------------------------------------------------
        # 6. Construir y retornar resultado
        # -----------------------------------------------------------------
        sucursales_unicas = (
            df_resultado["Sucursal"].nunique() if not df_resultado.empty else 0
        )

        return ResumenMensualResult(
            ruta_archivo=ruta,
            registros_procesados=len(df_resultado),
            sucursales=sucursales_unicas,
            genericos_incluidos=genericos_resultado,
            hojas=[g[:31] for g in genericos_resultado],
        )
