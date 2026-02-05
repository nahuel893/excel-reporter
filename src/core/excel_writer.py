"""
ExcelWriter - Generador de archivos Excel.

Proporciona funcionalidad para generar reportes Excel
con formato de tabla profesional y sistema de formatos modular.
"""
from pathlib import Path
from dataclasses import dataclass, field
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Font, Alignment, numbers

from config.settings import DATA_OUTPUT


@dataclass
class ColumnFormat:
    """Formato configurable para una columna."""
    number_format: str | None = None
    alignment: str | None = None
    font_bold: bool = False
    width: int | None = None


@dataclass
class SheetStyle:
    """Estilos configurables para una hoja Excel.

    Attributes:
        header_bold: Encabezados en negrita
        header_center: Encabezados centrados
        auto_width: Ajustar ancho automaticamente
        numeric_format: Formato para columnas numericas (ej: '#,##0' sin decimales)
        column_formats: Formatos especificos por nombre de columna
    """
    header_bold: bool = True
    header_center: bool = True
    auto_width: bool = True
    numeric_format: str = "#,##0"
    column_formats: dict[str, ColumnFormat] = field(default_factory=dict)


# Estilo por defecto
DEFAULT_STYLE = SheetStyle()


def _detect_numeric_columns(df: pd.DataFrame) -> list[str]:
    """Detecta columnas numericas en un DataFrame."""
    return [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]


def _apply_cell_format(cell, col_name: str, style: SheetStyle, is_header: bool = False):
    """
    Aplica formato a una celda segun el estilo y tipo de columna.

    Args:
        cell: Celda de openpyxl
        col_name: Nombre de la columna
        style: Estilo de la hoja
        is_header: Si es celda de encabezado
    """
    if is_header:
        if style.header_bold:
            cell.font = Font(bold=True)
        if style.header_center:
            cell.alignment = Alignment(horizontal="center")
        return

    # Formato especifico por columna
    if col_name in style.column_formats:
        fmt = style.column_formats[col_name]
        if fmt.number_format:
            cell.number_format = fmt.number_format
        if fmt.alignment:
            cell.alignment = Alignment(horizontal=fmt.alignment)
        if fmt.font_bold:
            cell.font = Font(bold=True)
        return

    # Formato generico para numericos
    if isinstance(cell.value, (int, float)) and cell.value is not None:
        cell.number_format = style.numeric_format


def _auto_fit_columns(ws, style: SheetStyle, column_formats: dict[str, ColumnFormat] = None):
    """Ajusta el ancho de columnas automaticamente o segun configuracion."""
    if not style.auto_width:
        return

    headers = [cell.value for cell in ws[1]]

    for col_idx, column in enumerate(ws.columns):
        col_name = headers[col_idx] if col_idx < len(headers) else None
        column_letter = column[0].column_letter

        # Ancho fijo si esta configurado
        if col_name and col_name in style.column_formats:
            fmt = style.column_formats[col_name]
            if fmt.width:
                ws.column_dimensions[column_letter].width = fmt.width
                continue

        # Auto-fit
        max_length = 0
        for cell in column:
            if cell.value is not None:
                max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[column_letter].width = max_length + 2


def _write_sheet(ws, df: pd.DataFrame, style: SheetStyle):
    """Escribe datos y aplica formato a una hoja."""
    headers = list(df.columns)

    for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=True), 1):
        for c_idx, value in enumerate(row, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=value)
            col_name = headers[c_idx - 1] if c_idx <= len(headers) else ""
            _apply_cell_format(cell, col_name, style, is_header=(r_idx == 1))

    _auto_fit_columns(ws, style)


def generar_excel(
    df: pd.DataFrame,
    nombre_archivo: str,
    sheet_name: str = "Datos",
    style: SheetStyle | None = None
) -> Path:
    """
    Genera archivo Excel con formato de tabla.

    Args:
        df: DataFrame procesado con el formato de reporte
        nombre_archivo: Nombre del archivo sin extension
        sheet_name: Nombre de la hoja (default: "Datos")
        style: Estilo personalizado. Si es None, usa DEFAULT_STYLE.

    Returns:
        Path del archivo generado
    """
    style = style or DEFAULT_STYLE
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    _write_sheet(ws, df, style)

    # Guardar archivo
    DATA_OUTPUT.mkdir(parents=True, exist_ok=True)
    ruta_archivo = DATA_OUTPUT / f"{nombre_archivo}.xlsx"
    wb.save(ruta_archivo)

    return ruta_archivo


class ExcelWriter:
    """
    Clase para generar Excel con mayor control.

    Permite configurar estilos, multiples hojas, etc.
    """

    def __init__(self, nombre_archivo: str, output_dir: Path | None = None, style: SheetStyle | None = None):
        self.nombre_archivo = nombre_archivo
        self.output_dir = output_dir or DATA_OUTPUT
        self.default_style = style or DEFAULT_STYLE
        self.workbook = Workbook()
        self._first_sheet = True

    def add_sheet(self, df: pd.DataFrame, sheet_name: str = "Datos", style: SheetStyle | None = None) -> None:
        """Agrega una hoja al workbook con formato."""
        style = style or self.default_style

        if self._first_sheet:
            ws = self.workbook.active
            ws.title = sheet_name
            self._first_sheet = False
        else:
            ws = self.workbook.create_sheet(title=sheet_name)

        _write_sheet(ws, df, style)

    def save(self) -> Path:
        """Guarda el archivo Excel."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ruta_archivo = self.output_dir / f"{self.nombre_archivo}.xlsx"
        self.workbook.save(ruta_archivo)
        return ruta_archivo
