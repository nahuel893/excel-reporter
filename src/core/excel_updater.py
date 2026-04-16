"""
excel_updater - Reemplazo de datos en hojas Excel existentes.

Proporciona funcionalidad para actualizar datos en worksheets existentes
preservando columnas de formulas y definiciones de tablas Excel.
"""
import logging
from datetime import datetime

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils import column_index_from_string, get_column_letter

logger = logging.getLogger(__name__)


def _coerce_value(val):
    """Convierte tipos pandas/numpy a Python nativo para openpyxl."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        if np.isnan(val):
            return None
        return float(val)
    if isinstance(val, float) and np.isnan(val):
        return None
    if isinstance(val, pd.Timestamp):
        return val.to_pydatetime()
    if val is pd.NaT:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        return val
    return val


def replace_sheet_data(
    wb: Workbook,
    sheet_name: str,
    df: pd.DataFrame,
    data_columns: list[str],
    header_row: int = 1,
) -> int:
    """
    Reemplaza datos en columnas especificas de una hoja Excel existente,
    preservando columnas de formulas y definiciones de tablas.

    Args:
        wb: Workbook de openpyxl (ya cargado)
        sheet_name: Nombre de la hoja a actualizar
        df: DataFrame con los nuevos datos
        data_columns: Lista de nombres de columnas a reemplazar
        header_row: Fila del encabezado (1-based, default: 1)

    Returns:
        Numero de filas escritas

    Raises:
        KeyError: Si la hoja no existe en el workbook
        ValueError: Si alguna columna de data_columns no existe en el header o en el DataFrame
    """
    # 1. Obtener worksheet
    if sheet_name not in wb.sheetnames:
        raise KeyError(f"Hoja '{sheet_name}' no encontrada en el workbook")
    ws = wb[sheet_name]

    # 2. Leer header y construir mapa: nombre_columna -> col_index (1-based)
    header_cells = ws[header_row]
    col_map: dict[str, int] = {}
    for cell in header_cells:
        if cell.value is not None:
            col_map[str(cell.value)] = cell.column

    # 3. Validar que todas las data_columns existen en header Y en DataFrame
    missing_in_header = [c for c in data_columns if c not in col_map]
    missing_in_df = [c for c in data_columns if c not in df.columns]

    errors = []
    if missing_in_header:
        errors.append(f"Columnas no encontradas en el header de la hoja: {missing_in_header}")
    if missing_in_df:
        errors.append(f"Columnas no encontradas en el DataFrame: {missing_in_df}")
    if errors:
        raise ValueError(" | ".join(errors))

    # 4. Limpiar datos existentes (solo celdas en data_columns)
    for row_idx in range(header_row + 1, ws.max_row + 1):
        for col_name in data_columns:
            col_idx = col_map[col_name]
            ws.cell(row=row_idx, column=col_idx).value = None

    # 5. Escribir nuevos datos fila por fila
    rows_written = 0
    for df_row_idx, (_, row) in enumerate(df.iterrows()):
        data_row = header_row + 1 + df_row_idx
        for col_name in data_columns:
            col_idx = col_map[col_name]
            raw_val = row[col_name]
            ws.cell(row=data_row, column=col_idx, value=_coerce_value(raw_val))
        rows_written += 1

    # 6. Redimensionar ref de tabla Excel si existe
    tables = list(ws.tables.values())
    if len(tables) > 1:
        logger.warning(
            "Hoja '%s' tiene %d tablas; se actualizara solo la primera: '%s'",
            sheet_name,
            len(tables),
            tables[0].displayName,
        )

    if tables:
        table = tables[0]
        current_ref = table.ref  # ej: "A3:Z100"

        # Extraer letras de columna del ref existente (preservar span completo)
        ref_start, ref_end = current_ref.split(":")
        # Separar letra de numero en cada extremo
        start_col_letter = "".join(c for c in ref_start if c.isalpha())
        end_col_letter = "".join(c for c in ref_end if c.isalpha())

        new_end_row = header_row + rows_written
        table.ref = f"{start_col_letter}{header_row}:{end_col_letter}{new_end_row}"
        logger.debug(
            "Tabla '%s' ref actualizada: %s -> %s",
            table.displayName,
            current_ref,
            table.ref,
        )

    return rows_written
