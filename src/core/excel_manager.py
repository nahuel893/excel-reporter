"""
ExcelManager - Operaciones sobre archivos Excel existentes.

A diferencia de ExcelWriter (que crea archivos), ExcelManager opera sobre
archivos .xlsx ya guardados en disco: captura rangos como imagen PNG,
lee rangos como DataFrame, etc.

Requiere:
  - LibreOffice (soffice) para renderizado headless
  - Pillow (PIL) para recorte de imagen
  - openpyxl para lectura de dimensiones de celdas
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import openpyxl
import pandas as pd

from config.settings import DATA_OUTPUT


def _col_letter_to_index(letter: str) -> int:
    """Convierte letra de columna Excel a indice 1-based (A→1, Z→26, AA→27)."""
    result = 0
    for char in letter.upper():
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result


def _parse_range(range_addr: str) -> tuple[int, int, int, int]:
    """
    Parsea rango Excel tipo "A1:H20" a (col_inicio, fila_inicio, col_fin, fila_fin).
    Los indices son 1-based.
    """
    parts = range_addr.upper().split(":")
    if len(parts) != 2:
        raise ValueError(f"Rango invalido: {range_addr!r}. Formato esperado: 'A1:H20'")

    def parse_cell(cell: str) -> tuple[int, int]:
        col_str = "".join(c for c in cell if c.isalpha())
        row_str = "".join(c for c in cell if c.isdigit())
        return _col_letter_to_index(col_str), int(row_str)

    col1, row1 = parse_cell(parts[0])
    col2, row2 = parse_cell(parts[1])
    return col1, row1, col2, row2


class ExcelManager:
    """Operaciones sobre un archivo .xlsx existente en disco."""

    DEFAULT_COL_WIDTH_CHARS = 8.43  # Ancho por defecto de columna en Excel
    DEFAULT_ROW_HEIGHT_PTS = 15.0   # Altura por defecto de fila en Excel

    def __init__(self, ruta_excel: Path):
        if not Path(ruta_excel).exists():
            raise FileNotFoundError(f"Archivo no encontrado: {ruta_excel}")
        self.ruta_excel = Path(ruta_excel)

    def capture_range(
        self,
        sheet_name: str,
        range_addr: str,
        output_dir: Path | None = None,
    ) -> Path:
        """
        Captura un rango de una hoja como imagen PNG.

        Proceso:
        1. Convierte el xlsx a PNG con LibreOffice headless
        2. Lee dimensiones de columnas/filas con openpyxl
        3. Calcula bounding box del rango en pixeles
        4. Recorta la imagen con Pillow

        Args:
            sheet_name: Nombre de la hoja del Excel
            range_addr: Rango en formato "A1:H20"
            output_dir: Directorio de salida (por defecto DATA_OUTPUT)

        Returns:
            Path al archivo PNG generado

        Raises:
            ValueError: Si la hoja no existe en el archivo
            RuntimeError: Si LibreOffice no esta instalado
        """
        # Validar hoja primero (antes de verificar dependencias opcionales)
        wb = openpyxl.load_workbook(self.ruta_excel, data_only=True)
        if sheet_name not in wb.sheetnames:
            raise ValueError(
                f"Hoja '{sheet_name}' no encontrada en {self.ruta_excel.name}. "
                f"Hojas disponibles: {wb.sheetnames}"
            )
        ws = wb[sheet_name]

        try:
            from PIL import Image
        except ImportError as exc:
            raise ImportError(
                "Pillow es requerido para capture_range. Instalar con: pip install Pillow"
            ) from exc

        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            raise RuntimeError(
                "LibreOffice no encontrado. Instalar con: sudo apt install libreoffice"
            )

        col1, row1, col2, row2 = _parse_range(range_addr)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [soffice, "--headless", "--convert-to", "png", "--outdir", tmpdir, str(self.ruta_excel)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"LibreOffice fallo al convertir el archivo: {result.stderr}"
                )

            png_candidates = list(Path(tmpdir).glob("*.png"))
            if not png_candidates:
                raise RuntimeError("LibreOffice no genero ningun archivo PNG")

            full_image = Image.open(png_candidates[0])

            crop_box = self._calculate_crop_box(ws, col1, row1, col2, row2)
            cropped = full_image.crop(crop_box)

            output_dir = Path(output_dir) if output_dir else DATA_OUTPUT
            output_dir.mkdir(parents=True, exist_ok=True)

            stem = self.ruta_excel.stem
            range_slug = range_addr.replace(":", "_")
            out_path = output_dir / f"{stem}_{sheet_name}_{range_slug}.png"
            cropped.save(out_path, "PNG")

        return out_path

    def _calculate_crop_box(
        self,
        ws,
        col1: int,
        row1: int,
        col2: int,
        row2: int,
    ) -> tuple[int, int, int, int]:
        """
        Calcula (x1, y1, x2, y2) en pixeles para recortar la imagen PNG.

        Conversion:
          - Ancho columna (chars Excel) → px = int(width * 7.0 + 5)
          - Alto fila (puntos Excel) → px = int(height * 96.0 / 72.0)
        """
        from openpyxl.utils import get_column_letter

        def col_px(col_idx: int) -> int:
            letter = get_column_letter(col_idx)
            dim = ws.column_dimensions.get(letter)
            width = dim.width if (dim and dim.width) else self.DEFAULT_COL_WIDTH_CHARS
            return int(width * 7.0 + 5)

        def row_px(row_idx: int) -> int:
            dim = ws.row_dimensions.get(row_idx)
            height = dim.height if (dim and dim.height) else self.DEFAULT_ROW_HEIGHT_PTS
            return int(height * 96.0 / 72.0)

        x1 = sum(col_px(c) for c in range(1, col1))
        x2 = x1 + sum(col_px(c) for c in range(col1, col2 + 1))
        y1 = sum(row_px(r) for r in range(1, row1))
        y2 = y1 + sum(row_px(r) for r in range(row1, row2 + 1))

        return x1, y1, x2, y2

    def get_dataframe(self, sheet_name: str, range_addr: str) -> pd.DataFrame:
        """
        Lee un rango de una hoja como DataFrame.

        La primera fila del rango se usa como encabezados.

        Args:
            sheet_name: Nombre de la hoja
            range_addr: Rango en formato "A1:H20"

        Returns:
            DataFrame con los datos del rango

        Raises:
            ValueError: Si la hoja no existe
        """
        wb = openpyxl.load_workbook(self.ruta_excel, data_only=True)
        if sheet_name not in wb.sheetnames:
            raise ValueError(
                f"Hoja '{sheet_name}' no encontrada en {self.ruta_excel.name}. "
                f"Hojas disponibles: {wb.sheetnames}"
            )
        ws = wb[sheet_name]

        col1, row1, col2, row2 = _parse_range(range_addr)

        rows = []
        for r in range(row1, row2 + 1):
            row_data = []
            for c in range(col1, col2 + 1):
                cell = ws.cell(row=r, column=c)
                row_data.append(cell.value)
            rows.append(row_data)

        if not rows:
            return pd.DataFrame()

        headers = rows[0]
        data = rows[1:]
        return pd.DataFrame(data, columns=headers)
