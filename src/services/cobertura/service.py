"""
CoberturaService - Servicio para generacion de reportes de cobertura.

Orquesta el flujo completo: extraccion, procesamiento y generacion de Excel
para reportes de cobertura de preventistas por ruta.
"""
from dataclasses import dataclass
from pathlib import Path

from src.core.excel_writer import generar_excel, SheetStyle, ColumnFormat
from src.core.excel_slicers import agregar_slicers, slicers_disponibles
from src.services.base_service import BaseService
from src.services.cobertura.processor import procesar_cobertura

# Tipos de reporte de cobertura
TIPO_PREVENTISTA_GENERICO = "preventista_generico"
TIPO_PREVENTISTA_MARCA = "preventista_marca"
TIPO_SUCURSAL_MARCA = "sucursal_marca"

# Columnas index por tipo (las que no son periodos)
_INDEX_COLUMNS = {
    TIPO_PREVENTISTA_GENERICO: ["sucursal", "vendedor", "id_ruta", "generico"],
    TIPO_PREVENTISTA_MARCA: ["sucursal", "vendedor", "id_ruta", "marca"],
    TIPO_SUCURSAL_MARCA: ["sucursal", "marca"],
}

# Columnas para slicers por tipo
_SLICER_COLUMNS = {
    TIPO_PREVENTISTA_GENERICO: ["sucursal", "vendedor", "generico"],
    TIPO_PREVENTISTA_MARCA: ["sucursal", "vendedor", "marca"],
    TIPO_SUCURSAL_MARCA: ["sucursal", "marca"],
}

# Nombres de hoja por tipo
_SHEET_NAMES = {
    TIPO_PREVENTISTA_GENERICO: "Cob Prev Generico",
    TIPO_PREVENTISTA_MARCA: "Cob Prev Marca",
    TIPO_SUCURSAL_MARCA: "Cob Sucursal Marca",
}


@dataclass
class ReporteCoberturaConfig:
    """Configuracion para generar un reporte de cobertura."""
    periodos: list[str]  # Lista de periodos especificos ['2025-02-01', '2026-01-01']
    tipo: str = TIPO_PREVENTISTA_GENERICO
    sucursales: list[str] | None = None
    nombre_archivo: str | None = None
    con_slicers: bool = True

    def __post_init__(self):
        if self.nombre_archivo is None:
            self.nombre_archivo = f"cobertura_{self.tipo}"


@dataclass
class ReporteCoberturaResult:
    """Resultado de la generacion de un reporte de cobertura."""
    ruta_archivo: Path
    registros_raw: int
    registros_procesados: int
    tipo: str
    slicers_agregados: bool = False


class CoberturaService(BaseService):
    """
    Servicio para generacion de reportes de cobertura.

    Soporta dos tipos de reporte:
    - preventista_generico: Cobertura por vendedor, ruta y generico
    - preventista_marca: Cobertura por vendedor, ruta y marca
    """

    def generar_reporte(self, config: ReporteCoberturaConfig) -> ReporteCoberturaResult:
        """Genera un reporte de cobertura."""
        # 1. Extraer datos con joins
        df_raw = self._extraer_datos(config)

        # 2. Pivotear periodos como columnas
        index_cols = _INDEX_COLUMNS[config.tipo]
        df_procesado = procesar_cobertura(df_raw, index_cols)

        # 3. Crear estilo
        style = self._crear_estilo(df_procesado, config.tipo)

        # 4. Generar Excel
        sheet_name = _SHEET_NAMES[config.tipo]
        ruta = generar_excel(
            df_procesado, config.nombre_archivo,
            sheet_name=sheet_name, style=style
        )

        # 5. Agregar slicers
        slicers_ok = False
        if config.con_slicers and slicers_disponibles():
            nombre_tabla = f"Tabla_{sheet_name.replace(' ', '_')}"
            columnas_slicer = _SLICER_COLUMNS.get(config.tipo, [])
            slicers_ok = agregar_slicers(ruta, nombre_tabla, columnas_slicer)

        return ReporteCoberturaResult(
            ruta_archivo=ruta,
            registros_raw=len(df_raw),
            registros_procesados=len(df_procesado),
            tipo=config.tipo,
            slicers_agregados=slicers_ok
        )

    def _extraer_datos(self, config: ReporteCoberturaConfig):
        """Extrae datos de cobertura segun el tipo."""
        if config.tipo == TIPO_PREVENTISTA_GENERICO:
            return self.data_loader.get_cobertura_preventista_generico(
                periodos=config.periodos, sucursales=config.sucursales
            )
        elif config.tipo == TIPO_PREVENTISTA_MARCA:
            return self.data_loader.get_cobertura_preventista_marca(
                periodos=config.periodos, sucursales=config.sucursales
            )
        elif config.tipo == TIPO_SUCURSAL_MARCA:
            return self.data_loader.get_cobertura_sucursal_marca(
                periodos=config.periodos, sucursales=config.sucursales
            )
        else:
            raise ValueError(f"Tipo de reporte no valido: {config.tipo}")

    def _crear_estilo(self, df, tipo: str) -> SheetStyle:
        """Crea estilo Excel para el reporte de cobertura."""
        index_cols = _INDEX_COLUMNS[tipo]
        columnas = list(df.columns)

        # Columnas de periodos = todas las que no son index
        columnas_periodos = [c for c in columnas if c not in index_cols]

        column_formats = {}
        for col in columnas_periodos:
            column_formats[col] = ColumnFormat(number_format='#,##0')

        return SheetStyle(
            column_formats=column_formats,
            as_table=True,
            table_style="TableStyleMedium9"
        )

    def listar_sucursales(self) -> list[str]:
        """Obtiene lista de sucursales disponibles."""
        df = self.data_loader.get_sucursales()
        return df["sucursal"].tolist()
