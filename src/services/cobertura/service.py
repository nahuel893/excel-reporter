"""
CoberturaService - Servicio para generacion de reportes de cobertura.

Orquesta el flujo completo: extraccion, procesamiento y generacion de Excel
para reportes de cobertura de preventistas y sucursales.
"""
from dataclasses import dataclass
from pathlib import Path

from src.core.excel_writer import generar_excel, SheetStyle, ColumnFormat
from src.core.excel_slicers import agregar_slicers, slicers_disponibles
from src.services.base_service import BaseService
from src.services.cobertura.processor import (
    procesar_cobertura_preventista_generico,
    procesar_cobertura_preventista_marca,
    procesar_cobertura_sucursal_marca,
)

# Tipos de reporte de cobertura disponibles
TIPO_PREVENTISTA_GENERICO = "preventista_generico"
TIPO_PREVENTISTA_MARCA = "preventista_marca"
TIPO_SUCURSAL_MARCA = "sucursal_marca"


@dataclass
class ReporteCoberturaConfig:
    """Configuracion para generar un reporte de cobertura."""
    periodo_desde: str
    periodo_hasta: str
    tipo: str = TIPO_PREVENTISTA_GENERICO
    sucursales: list[str] | None = None
    nombre_archivo: str | None = None
    con_slicers: bool = True

    def __post_init__(self):
        if self.nombre_archivo is None:
            self.nombre_archivo = f"cobertura_{self.tipo}_{self.periodo_desde}_{self.periodo_hasta}"


@dataclass
class ReporteCoberturaResult:
    """Resultado de la generacion de un reporte de cobertura."""
    ruta_archivo: Path
    registros_raw: int
    registros_procesados: int
    tipo: str
    slicers_agregados: bool = False


# Columnas de slicer por tipo de reporte
_SLICER_COLUMNS = {
    TIPO_PREVENTISTA_GENERICO: ["sucursal", "vendedor", "generico"],
    TIPO_PREVENTISTA_MARCA: ["sucursal", "vendedor", "marca"],
    TIPO_SUCURSAL_MARCA: ["sucursal", "marca"],
}

# Columnas index (no son periodos) por tipo
_INDEX_COLUMNS = {
    TIPO_PREVENTISTA_GENERICO: ["sucursal", "vendedor", "generico"],
    TIPO_PREVENTISTA_MARCA: ["sucursal", "vendedor", "marca"],
    TIPO_SUCURSAL_MARCA: ["sucursal", "marca"],
}


class CoberturaService(BaseService):
    """
    Servicio para generacion de reportes de cobertura.

    Soporta tres tipos de reporte:
    - preventista_generico: Cobertura por vendedor y generico
    - preventista_marca: Cobertura por vendedor y marca
    - sucursal_marca: Cobertura agregada por sucursal y marca
    """

    def generar_reporte(self, config: ReporteCoberturaConfig) -> ReporteCoberturaResult:
        """
        Genera un reporte de cobertura.

        Args:
            config: Configuracion del reporte.

        Returns:
            ReporteCoberturaResult con informacion del reporte generado.
        """
        # 1. Extraer datos segun tipo
        df_raw = self._extraer_datos(config)

        # 2. Procesar (pivotear periodos como columnas)
        df_procesado = self._procesar_datos(df_raw, config.tipo)

        # 3. Crear estilo
        style = self._crear_estilo(df_procesado, config.tipo)

        # 4. Generar Excel
        sheet_name = self._sheet_name(config.tipo)
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
                config.periodo_desde, config.periodo_hasta, config.sucursales
            )
        elif config.tipo == TIPO_PREVENTISTA_MARCA:
            return self.data_loader.get_cobertura_preventista_marca(
                config.periodo_desde, config.periodo_hasta, config.sucursales
            )
        elif config.tipo == TIPO_SUCURSAL_MARCA:
            return self.data_loader.get_cobertura_sucursal_marca(
                config.periodo_desde, config.periodo_hasta, config.sucursales
            )
        else:
            raise ValueError(f"Tipo de reporte no valido: {config.tipo}")

    def _procesar_datos(self, df, tipo: str):
        """Procesa datos segun el tipo de reporte."""
        if tipo == TIPO_PREVENTISTA_GENERICO:
            return procesar_cobertura_preventista_generico(df)
        elif tipo == TIPO_PREVENTISTA_MARCA:
            return procesar_cobertura_preventista_marca(df)
        elif tipo == TIPO_SUCURSAL_MARCA:
            return procesar_cobertura_sucursal_marca(df)

    def _crear_estilo(self, df, tipo: str) -> SheetStyle:
        """Crea estilo Excel para el reporte de cobertura."""
        index_cols = _INDEX_COLUMNS[tipo]
        columnas = list(df.columns)

        # Columnas de periodos = todas las que no son index
        columnas_periodos = [c for c in columnas if c not in index_cols]

        # Formato numerico para columnas de periodos
        column_formats = {}
        for col in columnas_periodos:
            column_formats[col] = ColumnFormat(number_format='#,##0')

        return SheetStyle(
            column_formats=column_formats,
            as_table=True,
            table_style="TableStyleMedium9"
        )

    def _sheet_name(self, tipo: str) -> str:
        """Retorna el nombre de hoja segun el tipo."""
        nombres = {
            TIPO_PREVENTISTA_GENERICO: "Cob Preventista Generico",
            TIPO_PREVENTISTA_MARCA: "Cob Preventista Marca",
            TIPO_SUCURSAL_MARCA: "Cob Sucursal Marca",
        }
        return nombres.get(tipo, "Cobertura")

    def listar_sucursales(self) -> list[str]:
        """Obtiene lista de sucursales disponibles."""
        df = self.data_loader.get_sucursales()
        return df["sucursal"].tolist()
