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
from src.core.excel_writer import ExcelWriter, SheetStyle, ColumnFormat, ColumnGroup
from src.core.excel_slicers import agregar_slicers, slicers_disponibles
from src.services.base_service import BaseService
from src.services.ventas.processor import completar_combinaciones, procesar_ventas, procesar_ventas_diarias

# Columnas para slicers en reporte de ventas
SLICER_COLUMNS = [
    COLUMN_NAMES["sucursal"],
    COLUMN_NAMES["generico"],
    COLUMN_NAMES["marca"],
]

# Configuracion base de formatos para ventas
VENTAS_COLUMN_FORMATS = {
    COLUMN_NAMES["cant_generico"]: ColumnFormat(number_format='#,##0', width=15, font_bold=True),
    COLUMN_NAMES["tend_generico"]: ColumnFormat(number_format='#,##0', width=15, font_bold=True),
    COLUMN_NAMES["monto_generico"]: ColumnFormat(number_format='$ #,##0', width=15, font_bold=True),
    COLUMN_NAMES["cob_generico"]: ColumnFormat(number_format='#,##0', width=13, font_bold=True),
    COLUMN_NAMES["total_marca"]: ColumnFormat(number_format='#,##0', width=11, font_bold=True),
    COLUMN_NAMES["tend_marca"]: ColumnFormat(number_format='#,##0', width=11, font_bold=True),
    COLUMN_NAMES["monto_marca"]: ColumnFormat(number_format='$ #,##0', width=15, font_bold=True),
    COLUMN_NAMES["cob_marca"]: ColumnFormat(number_format='#,##0', width=13, font_bold=True),
}


def _fechas_a_periodos(fecha_desde: str, fecha_hasta: str) -> list[str]:
    """Convierte un rango de fechas en lista de primeros dias de mes cubiertos."""
    desde = pd.to_datetime(fecha_desde).replace(day=1)
    hasta = pd.to_datetime(fecha_hasta)
    periodos = pd.date_range(desde, hasta, freq="MS")
    return [p.strftime("%Y-%m-%d") for p in periodos]


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

    # Formato de columnas: base + dias con ancho fijo
    column_formats = dict(VENTAS_COLUMN_FORMATS)
    for col_dia in columnas_dias:
        column_formats[col_dia] = ColumnFormat(number_format='#,##0', width=9.3)

    return SheetStyle(
        column_formats=column_formats,
        column_groups=groups,
        summary_rows=info_dias
    )


# Unidades disponibles
UNIDAD_BULTOS = "bultos"
UNIDAD_HTLS = "htls"

# Mapeo unidad -> columna de cantidad en el DataFrame
_COL_CANTIDAD = {
    UNIDAD_BULTOS: "cantidad",
    UNIDAD_HTLS: "cantidad_htls",
}

_UNIDADES = [
    (UNIDAD_BULTOS, "Ventas Bultos"),
    (UNIDAD_HTLS, "Ventas HTLs"),
]


@dataclass
class ReporteVentasConfig:
    """Configuracion para generar un reporte de ventas."""
    fecha_desde: str
    fecha_hasta: str
    genericos: list[str] | None = None
    nombre_archivo: str | None = None
    con_slicers: bool = True
    con_cobertura: bool = True

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
    hojas: list[str] = None
    slicers_agregados: bool = False
    supervisor: str | None = None


class VentasService(BaseService):
    """
    Servicio para generacion de reportes de ventas.

    Orquesta el flujo completo: extraccion, procesamiento y generacion de Excel.
    """

    def _fetch_data(self, config: ReporteVentasConfig) -> tuple:
        """
        Extrae todos los datos necesarios para el reporte.

        Returns:
            (df_ventas, df_sucursales, df_articulos, df_cob_generico, df_cob_marca, info_dias)
        """
        df_ventas = self.data_loader.get_ventas_diarias(
            config.fecha_desde,
            config.fecha_hasta,
            config.genericos
        )
        df_sucursales = self.data_loader.get_sucursales()
        df_articulos = self.data_loader.get_articulos(config.genericos)
        info_dias = calcular_info_dias(config.fecha_desde, config.fecha_hasta)

        df_cob_generico = None
        df_cob_marca = None

        if config.con_cobertura:
            periodos = _fechas_a_periodos(config.fecha_desde, config.fecha_hasta)
            try:
                df_cg = self.data_loader.get_cobertura_sucursal_generico(periodos=periodos)
                if not df_cg.empty:
                    df_cob_generico = (
                        df_cg.groupby(["sucursal", "generico"])["clientes_compradores"]
                        .sum()
                        .reset_index()
                    )
            except Exception:
                pass

            try:
                df_cm = self.data_loader.get_cobertura_sucursal_marca(periodos=periodos)
                if not df_cm.empty:
                    df_cob_marca = (
                        df_cm.groupby(["sucursal", "marca"])["clientes_compradores"]
                        .sum()
                        .reset_index()
                    )
            except Exception:
                pass

        return df_ventas, df_sucursales, df_articulos, df_cob_generico, df_cob_marca, info_dias

    def _build_workbook(
        self,
        nombre_archivo: str,
        fecha_desde: str,
        fecha_hasta: str,
        df_ventas: pd.DataFrame,
        df_sucursales: pd.DataFrame,
        df_articulos: pd.DataFrame,
        df_cob_generico: pd.DataFrame | None,
        df_cob_marca: pd.DataFrame | None,
        info_dias: dict,
        con_slicers: bool,
    ) -> tuple[Path, int, bool]:
        """
        Genera el archivo Excel con ambas hojas (Bultos y HTLs).

        Returns:
            (ruta_archivo, total_procesados, slicers_ok)
        """
        writer = ExcelWriter(nombre_archivo)
        total_procesados = 0

        for unidad, sheet_label in _UNIDADES:
            col_cantidad = _COL_CANTIDAD[unidad]
            df_procesado = procesar_ventas_diarias(
                df_ventas,
                fecha_desde,
                fecha_hasta,
                df_sucursales,
                df_articulos,
                col_cantidad=col_cantidad,
                df_cob_generico=df_cob_generico,
                df_cob_marca=df_cob_marca,
            )

            # Detectar columnas de dias (entre Marca y Total)
            columnas = list(df_procesado.columns)
            idx_marca = columnas.index(COLUMN_NAMES["marca"])
            idx_total = columnas.index(COLUMN_NAMES["total_marca"])
            columnas_dias = columnas[idx_marca + 1:idx_total]

            style = _crear_estilo_ventas(columnas_dias, info_dias)
            writer.add_sheet(df_procesado, sheet_name=sheet_label, style=style)
            total_procesados += len(df_procesado)

        ruta = writer.save()

        slicers_ok = False
        if con_slicers and slicers_disponibles():
            for _, sheet_label in _UNIDADES:
                nombre_tabla = f"Tabla_{sheet_label.replace(' ', '_')}"
                agregar_slicers(ruta, nombre_tabla, SLICER_COLUMNS)
            slicers_ok = True

        return ruta, total_procesados, slicers_ok

    def generar_reporte(self, config: ReporteVentasConfig) -> ReporteVentasResult:
        """
        Genera un reporte de ventas completo con desglose diario.

        Genera un archivo Excel con dos hojas: Ventas Bultos y Ventas HTLs.
        Incluye columnas de cobertura (Generico y Marca) cruzando con tablas de cobertura.

        Args:
            config: Configuracion del reporte.

        Returns:
            ReporteVentasResult con informacion del reporte generado.
        """
        df_ventas, df_sucursales, df_articulos, df_cob_gen, df_cob_marca, info_dias = (
            self._fetch_data(config)
        )

        ruta, total_procesados, slicers_ok = self._build_workbook(
            config.nombre_archivo,
            config.fecha_desde,
            config.fecha_hasta,
            df_ventas,
            df_sucursales,
            df_articulos,
            df_cob_gen,
            df_cob_marca,
            info_dias,
            config.con_slicers,
        )

        genericos_incluidos = (
            df_articulos["generico"].unique().tolist() if not df_articulos.empty else []
        )

        return ReporteVentasResult(
            ruta_archivo=ruta,
            registros_ventas=len(df_ventas),
            registros_procesados=total_procesados,
            sucursales=len(df_sucursales),
            genericos_incluidos=genericos_incluidos,
            hojas=[label for _, label in _UNIDADES],
            slicers_agregados=slicers_ok,
        )

    def generar_reporte_supervisores(
        self,
        config: ReporteVentasConfig,
        supervisores: dict[str, list[str]],
    ) -> list[ReporteVentasResult]:
        """
        Genera un archivo Excel por supervisor, filtrado por sus sucursales.

        Realiza una sola consulta a BD y luego filtra los datos por supervisor.

        Args:
            config: Configuracion base del reporte (fechas, genericos, etc.)
            supervisores: Mapeo {nombre_supervisor: [lista_de_sucursales]}

        Returns:
            Lista de ReporteVentasResult, uno por supervisor.
        """
        # Una sola consulta para todos los supervisores
        df_ventas, _, df_articulos, df_cob_gen, df_cob_marca, info_dias = (
            self._fetch_data(config)
        )

        results = []
        for supervisor, sucursales_list in supervisores.items():
            # Filtrar datos al universo de este supervisor
            df_ventas_sup = df_ventas[df_ventas["sucursal"].isin(sucursales_list)]
            df_sucursales_sup = pd.DataFrame({"sucursal": sucursales_list})

            df_cob_gen_sup = None
            if df_cob_gen is not None:
                df_cob_gen_sup = df_cob_gen[df_cob_gen["sucursal"].isin(sucursales_list)]

            df_cob_marca_sup = None
            if df_cob_marca is not None:
                df_cob_marca_sup = df_cob_marca[df_cob_marca["sucursal"].isin(sucursales_list)]

            # Nombre de archivo: ventas_DESDE_HASTA_supervisor
            sup_slug = supervisor.lower().replace(" ", "_")
            nombre = f"{config.nombre_archivo}_{sup_slug}"

            ruta, total_procesados, slicers_ok = self._build_workbook(
                nombre,
                config.fecha_desde,
                config.fecha_hasta,
                df_ventas_sup,
                df_sucursales_sup,
                df_articulos,
                df_cob_gen_sup,
                df_cob_marca_sup,
                info_dias,
                config.con_slicers,
            )

            genericos_incluidos = (
                df_articulos["generico"].unique().tolist() if not df_articulos.empty else []
            )

            results.append(ReporteVentasResult(
                ruta_archivo=ruta,
                registros_ventas=len(df_ventas_sup),
                registros_procesados=total_procesados,
                sucursales=len(sucursales_list),
                genericos_incluidos=genericos_incluidos,
                hojas=[label for _, label in _UNIDADES],
                slicers_agregados=slicers_ok,
                supervisor=supervisor,
            ))

        return results

    def obtener_ventas(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        genericos: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Obtiene datos de ventas procesados sin generar Excel.

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
