"""
ExcelWriter - Generador de archivos Excel.

Proporciona funcionalidad para generar reportes Excel
con formato de tabla profesional.
"""
from pathlib import Path
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Font, Alignment

from config.settings import DATA_OUTPUT


def generar_excel(df: pd.DataFrame, nombre_archivo: str, sheet_name: str = "Datos") -> Path:
    """
    Genera archivo Excel con formato de tabla.

    Args:
        df: DataFrame procesado con el formato de reporte
        nombre_archivo: Nombre del archivo sin extension
        sheet_name: Nombre de la hoja (default: "Datos")

    Returns:
        Path del archivo generado
    """
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    # Escribir datos
    for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=True), 1):
        for c_idx, value in enumerate(row, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=value)

            # Formato de encabezado
            if r_idx == 1:
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="center")

    # Ajustar ancho de columnas
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[column_letter].width = max_length + 2

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

    def __init__(self, nombre_archivo: str, output_dir: Path | None = None):
        """
        Inicializa el writer.

        Args:
            nombre_archivo: Nombre del archivo sin extension
            output_dir: Directorio de salida. Si es None, usa DATA_OUTPUT.
        """
        self.nombre_archivo = nombre_archivo
        self.output_dir = output_dir or DATA_OUTPUT
        self.workbook = Workbook()
        self._first_sheet = True

    def add_sheet(self, df: pd.DataFrame, sheet_name: str = "Datos") -> None:
        """
        Agrega una hoja al workbook.

        Args:
            df: DataFrame con los datos
            sheet_name: Nombre de la hoja
        """
        if self._first_sheet:
            ws = self.workbook.active
            ws.title = sheet_name
            self._first_sheet = False
        else:
            ws = self.workbook.create_sheet(title=sheet_name)

        # Escribir datos
        for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=True), 1):
            for c_idx, value in enumerate(row, 1):
                cell = ws.cell(row=r_idx, column=c_idx, value=value)

                if r_idx == 1:
                    cell.font = Font(bold=True)
                    cell.alignment = Alignment(horizontal="center")

        # Ajustar ancho de columnas
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            ws.column_dimensions[column_letter].width = max_length + 2

    def save(self) -> Path:
        """
        Guarda el archivo Excel.

        Returns:
            Path del archivo generado
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ruta_archivo = self.output_dir / f"{self.nombre_archivo}.xlsx"
        self.workbook.save(ruta_archivo)
        return ruta_archivo
