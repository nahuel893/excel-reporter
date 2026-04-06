"""
VentasService - Servicio para generacion de reportes de ventas.

Orquesta el flujo completo: extraccion, procesamiento y generacion de Excel.
"""
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

from config.settings import COLUMN_NAMES, ZONAS_VIRTUALES
from src.core.base_processor import calcular_info_dias
from src.core.data_loader import DataLoader
from src.core.excel_writer import ExcelWriter, SheetStyle, ColumnFormat, ColumnGroup
from src.core.excel_slicers import agregar_slicers, slicers_disponibles
from src.core.zonas import aplicar_zonas_virtuales as _aplicar_zonas_virtuales, expandir_sucursales as _expandir_sucursales
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

# Hojas de cobertura
_COB_GENERICO_SHEET = "Cobertura Generico"
_COB_MARCA_SHEET = "Cobertura Marca"

_COB_GENERICO_COLUMNS = {
    "sucursal": COLUMN_NAMES["sucursal"],
    "generico": COLUMN_NAMES["generico"],
    "clientes_compradores": "Clientes Compradores",
}

_COB_MARCA_COLUMNS = {
    "sucursal": COLUMN_NAMES["sucursal"],
    "marca": COLUMN_NAMES["marca"],
    "clientes_compradores": "Clientes Compradores",
}

_COBERTURA_STYLE = SheetStyle(
    column_formats={
        "Clientes Compradores": ColumnFormat(number_format="#,##0", width=20),
    },
    as_table=True,
    table_style="TableStyleMedium9",
)


def _preparar_cobertura(
    df_cob: pd.DataFrame | None,
    sort_cols: list[str],
    rename_map: dict[str, str],
) -> pd.DataFrame | None:
    """Ordena y renombra un DataFrame de cobertura para escribirlo como hoja Excel."""
    if df_cob is None or df_cob.empty:
        return None
    df = df_cob.sort_values(sort_cols).reset_index(drop=True)
    df = df[list(rename_map.keys())]
    return df.rename(columns=rename_map)


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
        pass  # El nombre se genera en el servicio a partir de la ultima fecha real de ventas


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


def _nombre_reporte(
    df_ventas: pd.DataFrame,
    fecha_hasta: str,
    supervisor: str | None = None,
    nombre_explicito: str | None = None,
) -> str:
    """
    Genera el nombre de archivo para el reporte.

    Formato: 'Ventas {supervisor} - {dd-mm-yyyy}' o 'Ventas - {dd-mm-yyyy}'.
    La fecha es la ultima fecha con ventas reales; si no hay datos, usa fecha_hasta.

    Args:
        df_ventas: DataFrame con columna 'fecha' de las ventas
        fecha_hasta: Fecha limite del rango (fallback si df_ventas esta vacio)
        supervisor: Nombre del supervisor (None para reporte global)
        nombre_explicito: Si el usuario especifico un nombre custom, lo usa tal cual.
    """
    if nombre_explicito:
        return nombre_explicito

    if not df_ventas.empty and "fecha" in df_ventas.columns:
        ultima_fecha = pd.to_datetime(df_ventas["fecha"]).max().strftime("%d-%m-%Y")
    else:
        ultima_fecha = pd.to_datetime(fecha_hasta).strftime("%d-%m-%Y")

    if supervisor:
        return f"Ventas {supervisor} - {ultima_fecha}"
    return f"Ventas - {ultima_fecha}"


class VentasService(BaseService):
    """
    Servicio para generacion de reportes de ventas.

    Orquesta el flujo completo: extraccion, procesamiento y generacion de Excel.
    """

    def _fetch_data(self, config: ReporteVentasConfig) -> tuple:
        """
        Extrae todos los datos necesarios para el reporte.

        Usa get_ventas_diarias_con_ruta() para incluir id_ruta y poder splitear
        zonas virtuales (ej: CASA CENTRAL → CASA CENTRAL + VALLE SALTA).

        Returns:
            (df_ventas, df_sucursales, df_articulos, df_cob_generico, df_cob_marca, info_dias)
        """
        df_ventas = self.data_loader.get_ventas_diarias_con_ruta(
            config.fecha_desde,
            config.fecha_hasta,
            config.genericos
        )
        df_ventas = _aplicar_zonas_virtuales(df_ventas)

        df_sucursales = self.data_loader.get_sucursales()
        # Agregar zonas virtuales a la lista de sucursales (solo si la sucursal real existe)
        for zona_nombre, zona_config in ZONAS_VIRTUALES.items():
            if (
                zona_config["sucursal_real"] in df_sucursales["sucursal"].values
                and zona_nombre not in df_sucursales["sucursal"].values
            ):
                df_sucursales = pd.concat(
                    [df_sucursales, pd.DataFrame({"sucursal": [zona_nombre]})],
                    ignore_index=True,
                )

        df_articulos = self.data_loader.get_articulos(config.genericos)
        info_dias = calcular_info_dias(config.fecha_desde, config.fecha_hasta)

        df_cob_generico = None
        df_cob_marca = None

        if config.con_cobertura:
            periodos = _fechas_a_periodos(config.fecha_desde, config.fecha_hasta)
            try:
                df_cg = self.data_loader.get_cobertura_preventista_generico(periodos=periodos)
                if not df_cg.empty:
                    df_cg = _aplicar_zonas_virtuales(df_cg)
                    df_cob_generico = (
                        df_cg.groupby(["sucursal", "generico"])["clientes_compradores"]
                        .sum()
                        .reset_index()
                    )
            except Exception:
                pass

            try:
                df_cm = self.data_loader.get_cobertura_preventista_marca(periodos=periodos)
                if not df_cm.empty:
                    df_cm = _aplicar_zonas_virtuales(df_cm)
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
    ) -> tuple[Path, int, bool, list[str]]:
        """
        Genera el archivo Excel con hojas de ventas y cobertura.

        Returns:
            (ruta_archivo, total_procesados, slicers_ok, hojas)
        """
        writer = ExcelWriter(nombre_archivo)
        total_procesados = 0
        hojas = []

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
            hojas.append(sheet_label)

        # Hojas de cobertura
        df_cob_gen_sheet = _preparar_cobertura(
            df_cob_generico, ["sucursal", "generico"], _COB_GENERICO_COLUMNS
        )
        if df_cob_gen_sheet is not None:
            writer.add_sheet(df_cob_gen_sheet, sheet_name=_COB_GENERICO_SHEET, style=_COBERTURA_STYLE)
            hojas.append(_COB_GENERICO_SHEET)

        df_cob_marca_sheet = _preparar_cobertura(
            df_cob_marca, ["sucursal", "marca"], _COB_MARCA_COLUMNS
        )
        if df_cob_marca_sheet is not None:
            writer.add_sheet(df_cob_marca_sheet, sheet_name=_COB_MARCA_SHEET, style=_COBERTURA_STYLE)
            hojas.append(_COB_MARCA_SHEET)

        ruta = writer.save()

        slicers_ok = False
        if con_slicers and slicers_disponibles():
            for _, sheet_label in _UNIDADES:
                nombre_tabla = f"Tabla_{sheet_label.replace(' ', '_')}"
                agregar_slicers(ruta, nombre_tabla, SLICER_COLUMNS)
            slicers_ok = True

        return ruta, total_procesados, slicers_ok, hojas

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

        nombre = _nombre_reporte(df_ventas, config.fecha_hasta, nombre_explicito=config.nombre_archivo)

        ruta, total_procesados, slicers_ok, hojas = self._build_workbook(
            nombre,
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
            hojas=hojas,
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
            # Expandir zonas virtuales (CASA CENTRAL → CASA CENTRAL + VALLE SALTA)
            sucursales_expandidas = _expandir_sucursales(sucursales_list)

            # Filtrar datos al universo de este supervisor
            df_ventas_sup = df_ventas[df_ventas["sucursal"].isin(sucursales_expandidas)]
            df_sucursales_sup = pd.DataFrame({"sucursal": sucursales_expandidas})

            df_cob_gen_sup = None
            if df_cob_gen is not None:
                df_cob_gen_sup = df_cob_gen[df_cob_gen["sucursal"].isin(sucursales_expandidas)]

            df_cob_marca_sup = None
            if df_cob_marca is not None:
                df_cob_marca_sup = df_cob_marca[df_cob_marca["sucursal"].isin(sucursales_expandidas)]

            # Nombre de archivo: "Ventas {supervisor} - {ultima_fecha}"
            nombre = _nombre_reporte(df_ventas_sup, config.fecha_hasta, supervisor=supervisor)

            ruta, total_procesados, slicers_ok, hojas = self._build_workbook(
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
                sucursales=len(sucursales_expandidas),
                genericos_incluidos=genericos_incluidos,
                hojas=hojas,
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
