"""
ResumenMensualService - Servicio para generacion de reportes de resumen mensual.

Orquesta el flujo completo: extraccion, procesamiento y generacion de Excel.
"""
import logging
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.core.base_processor import calcular_info_dias
from src.core.data_loader import DataLoader
from src.core.excel_updater import import_xlsx_as_sheet
from src.core.excel_writer import ExcelWriter, SheetStyle, ColumnFormat
from src.core.zonas import aplicar_zonas_virtuales
from src.services.base_service import BaseService
from src.services.resumen_mensual.processor import procesar_resumen_mensual

logger = logging.getLogger(__name__)

# Default genericos when config.genericos is None
_DEFAULT_GENERICOS = ["CERVEZAS", "AGUAS DANONE", "VINOS CCU", "SIDRAS Y LICORES"]

# Row labels for subtotals
_SUBTOTAL_CC = "SUBTOTAL CASA CENTRAL"
_SUC_SIN_DIRECTA = "SUCURSALES SIN DIRECTA"
_TOTAL_SIN_SMK = "TOTAL SIN SMK"

# CC-family sucursales (order matters for display)
_CC_FAMILY = ["CASA CENTRAL", "VALLE SALTA", "SUB DISTRIBUIDORES"]

# Subtotal row fills (one color per label) and matching font colors
_SUBTOTAL_FILLS = {
    _SUBTOTAL_CC:     "548235",  # green
    _SUC_SIN_DIRECTA: "7030A0",  # purple
    _TOTAL_SIN_SMK:   "FF0000",  # red
}
_SUBTOTAL_FONT_COLOR = "FFFFFF"  # white text on all 3 fills

# Header fill + font
_HEADER_FILL_COLOR = "1F4E78"  # dark blue
_HEADER_FONT_COLOR = "FFFFFF"  # white


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
    con_objetivo: bool = True  # True: uses gold.fact_cupos; set False if table is missing
    detalle_movimientos_path: str | None = None  # Path to source xlsx for Detalle Movimientos sheet


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


def _segregar_directa_sucursales(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renombra a 'DIRECTA SUCURSALES' las filas cuyo id_ruta == 100 y cuya
    sucursal no es 'CASA CENTRAL'.

    Debe llamarse ANTES del groupby que descarta id_ruta, y DESPUÉS de
    aplicar_zonas_virtuales (que ya separó VALLE SALTA y SUB DISTRIBUIDORES).

    Args:
        df: DataFrame con columnas 'sucursal', 'id_ruta' (y otras).

    Returns:
        Copia del DataFrame con las filas afectadas renombradas.
    """
    if "id_ruta" not in df.columns:
        return df
    df = df.copy()
    mask = (df["id_ruta"] == 100) & (df["sucursal"] != "CASA CENTRAL")
    df.loc[mask, "sucursal"] = "DIRECTA SUCURSALES"
    return df


def _crear_estilo_resumen(info_dias: dict, col_n1: str, col_n2: str) -> SheetStyle:
    """Crea el SheetStyle para las hojas del reporte de resumen mensual.

    Args:
        info_dias: Diccionario con Dias Habiles, Dias Transcurridos, Dias Faltantes.
        col_n1: Nombre de la columna del ultimo dia con ventas (ej: '28-02 Sabado').
        col_n2: Nombre de la columna del penultimo dia con ventas (ej: '27-02 Viernes').

    Returns:
        SheetStyle configurado para el reporte de resumen mensual.
    """
    _DASH_FMT = '#,##0;-#,##0;"-"'
    return SheetStyle(
        numeric_format="#,##0",
        column_formats={
            "Sucursal":        ColumnFormat(width=30.375, font_bold=True),
            "Generico":        ColumnFormat(width=14.125, font_bold=True),
            col_n1:            ColumnFormat(number_format=_DASH_FMT, width=9.125, font_bold=True),
            col_n2:            ColumnFormat(number_format=_DASH_FMT, width=13.0, font_bold=True),
            "Total Ventas":    ColumnFormat(number_format=_DASH_FMT, width=13.0, font_bold=True),
            "Tendencia":       ColumnFormat(number_format=_DASH_FMT, width=13.0, font_bold=True),
            # T-021: MMAA = dark red, MA = olive, Objetivo = light blue
            "MMAA":            ColumnFormat(number_format=_DASH_FMT, width=13.0, font_bold=True, font_color="C00000"),
            "MA":              ColumnFormat(number_format=_DASH_FMT, width=13.0, font_bold=True, font_color="808000"),
            "Objetivo":        ColumnFormat(number_format=_DASH_FMT, width=13.0, font_bold=True, font_color="4472C4"),
            "Tend vs Obj (%)": ColumnFormat(number_format="0.0%", width=9.625, font_bold=True),
        },
        summary_rows=info_dias,
        as_table=False,
    )


def _ordenar_e_inyectar_subtotales(df_hoja: pd.DataFrame) -> pd.DataFrame:
    """
    Ordena las filas del DataFrame de una hoja e inyecta las 3 filas de subtotales
    como filas con valores None (se rellenan con formulas SUM en post-write).

    Orden de salida:
        CASA CENTRAL → VALLE SALTA → SUB DISTRIBUIDORES
        → SUBTOTAL CASA CENTRAL
        → sucursales numeradas (alfa)
        → SUCURSALES SIN DIRECTA
        → DIRECTA SUCURSALES
        → TOTAL SIN SMK

    Args:
        df_hoja: DataFrame con columna 'Sucursal' y columnas numericas.

    Returns:
        DataFrame reordenado con filas de subtotales inyectadas (valores None
        en columnas numericas; 'Sucursal' = etiqueta del subtotal).
    """
    if df_hoja.empty:
        return df_hoja

    cols = list(df_hoja.columns)

    def _empty_row(label: str) -> dict:
        row = {c: None for c in cols}
        row["Sucursal"] = label
        if "Generico" in cols:
            # Keep the generico consistent so the filter in the loop still matches
            genericos = df_hoja["Generico"].dropna().unique()
            row["Generico"] = genericos[0] if len(genericos) == 1 else None
        return row

    suc_col = df_hoja["Sucursal"]

    # CC family (in fixed order)
    cc_rows = []
    for label in _CC_FAMILY:
        mask = suc_col == label
        if mask.any():
            cc_rows.append(df_hoja[mask])

    # Numbered sucursales: everything that is NOT cc_family, DIRECTA SUCURSALES, subtotal labels
    _special = set(_CC_FAMILY) | {"DIRECTA SUCURSALES", _SUBTOTAL_CC, _SUC_SIN_DIRECTA, _TOTAL_SIN_SMK}
    numbered_mask = ~suc_col.isin(_special)
    numbered = df_hoja[numbered_mask].sort_values("Sucursal")

    # DIRECTA SUCURSALES
    directa_mask = suc_col == "DIRECTA SUCURSALES"
    directa = df_hoja[directa_mask]

    # Build ordered list
    parts = []
    if cc_rows:
        parts.extend(cc_rows)
    subtotal_cc_row = pd.DataFrame([_empty_row(_SUBTOTAL_CC)])
    parts.append(subtotal_cc_row)
    if not numbered.empty:
        parts.append(numbered)
    suc_sin_directa_row = pd.DataFrame([_empty_row(_SUC_SIN_DIRECTA)])
    parts.append(suc_sin_directa_row)
    if not directa.empty:
        parts.append(directa)
    total_sin_smk_row = pd.DataFrame([_empty_row(_TOTAL_SIN_SMK)])
    parts.append(total_sin_smk_row)

    result = pd.concat(parts, ignore_index=True)
    return result


def _post_write_subtotals_and_heatmap(
    ws,
    df_hoja_ordered: pd.DataFrame,
    summary_rows_count: int,
):
    """
    Post-write step: resolves subtotal placeholder rows to real =SUM(...) formulas,
    applies bold+fill to subtotal rows, and adds a ColorScaleRule on Tend vs Obj (%).

    This function is called after ExcelWriter.add_sheet() returns the Worksheet.

    Args:
        ws: openpyxl Worksheet (returned by ExcelWriter.add_sheet)
        df_hoja_ordered: The ordered DataFrame (same order as what was written to the sheet,
                         including subtotal placeholder rows)
        summary_rows_count: Number of summary rows written before the header
                            (from SheetStyle.summary_rows). Used to compute row offsets.
    """
    # Guard: if ws is not a real openpyxl Worksheet (e.g. a Mock in unit tests),
    # skip post-write silently.
    if not hasattr(ws, "iter_rows") or not callable(getattr(ws, "iter_rows", None)):
        return
    try:
        # Confirm it's a real worksheet by checking if iter_rows yields tuples of cells
        test_iter = ws.iter_rows(min_row=1, max_row=1)
        next(test_iter)  # will raise StopIteration on empty ws but not TypeError on Mock
    except (TypeError, AttributeError):
        return

    # -------------------------------------------------------------------
    # Compute layout offsets
    # -------------------------------------------------------------------
    # ExcelWriter._write_summary_rows writes `len(summary_rows) + 1` rows
    # before the header (the +1 is an empty separator row).
    header_row = summary_rows_count + 1 + 1  # summary rows + separator + header
    data_start_row = header_row + 1
    n_data_rows = len(df_hoja_ordered)
    data_end_row = data_start_row + n_data_rows - 1

    # -------------------------------------------------------------------
    # Build column name → letter map from the actual header row in the sheet
    # -------------------------------------------------------------------
    header_cells = list(ws.iter_rows(min_row=header_row, max_row=header_row))[0]
    col_map = {}  # col_name -> column_letter
    for cell in header_cells:
        if cell.value:
            col_map[cell.value] = get_column_letter(cell.column)

    # -------------------------------------------------------------------
    # Numeric columns to include in SUM formulas (all except Sucursal, Generico)
    _NON_SUM_COLS = {"Sucursal", "Generico", "Tend vs Obj (%)"}
    sum_cols = [c for c in df_hoja_ordered.columns if c not in _NON_SUM_COLS]

    # -------------------------------------------------------------------
    # Build a map: subtotal_label -> list of (start_row, end_row) to sum
    # and their actual sheet row numbers
    # -------------------------------------------------------------------
    # Sheet row for each df row: data_start_row + df_index
    rows_by_label = {}  # label -> sheet_row_number
    for df_idx, sucursal in enumerate(df_hoja_ordered["Sucursal"]):
        sheet_row = data_start_row + df_idx
        rows_by_label[sucursal] = sheet_row

    # Ranges to SUM for each subtotal
    def _rows_for_group(group_labels):
        """Return sorted sheet row numbers for the given sucursal labels."""
        return sorted(
            rows_by_label[lbl]
            for lbl in group_labels
            if lbl in rows_by_label
        )

    cc_group_labels = [l for l in _CC_FAMILY if l in rows_by_label]
    numbered_labels = [
        s for s in df_hoja_ordered["Sucursal"]
        if s not in set(_CC_FAMILY) | {"DIRECTA SUCURSALES", _SUBTOTAL_CC, _SUC_SIN_DIRECTA, _TOTAL_SIN_SMK}
        and s is not None
    ]
    # Deduplicate keeping order
    seen = set()
    numbered_labels_unique = []
    for lbl in numbered_labels:
        if lbl not in seen:
            seen.add(lbl)
            numbered_labels_unique.append(lbl)

    directa_labels = ["DIRECTA SUCURSALES"] if "DIRECTA SUCURSALES" in rows_by_label else []

    subtotal_definitions = {
        _SUBTOTAL_CC: _rows_for_group(cc_group_labels),
        _SUC_SIN_DIRECTA: _rows_for_group(numbered_labels_unique),
        _TOTAL_SIN_SMK: (
            ([rows_by_label[_SUBTOTAL_CC]] if _SUBTOTAL_CC in rows_by_label else [])
            + ([rows_by_label[_SUC_SIN_DIRECTA]] if _SUC_SIN_DIRECTA in rows_by_label else [])
            + _rows_for_group(directa_labels)
        ),
    }

    # -------------------------------------------------------------------
    # Write SUM formulas and styling on subtotal rows
    # -------------------------------------------------------------------
    n_cols = len(header_cells)
    thin_side = Side(style="thin")
    thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    for subtotal_label, source_rows in subtotal_definitions.items():
        if subtotal_label not in rows_by_label:
            continue
        subtotal_sheet_row = rows_by_label[subtotal_label]

        fill_color = _SUBTOTAL_FILLS.get(subtotal_label, "D9D9D9")
        subtotal_fill = PatternFill(
            start_color=fill_color, end_color=fill_color, fill_type="solid",
        )
        subtotal_font = Font(bold=True, color=_SUBTOTAL_FONT_COLOR)

        # Write SUM formulas for numeric columns
        for col_name in sum_cols:
            col_letter = col_map.get(col_name)
            if col_letter is None:
                continue
            if not source_rows:
                formula = None
            elif len(source_rows) == 1:
                formula = f"=SUM({col_letter}{source_rows[0]})"
            else:
                # Use individual cell references (non-contiguous in general)
                refs = ",".join(f"{col_letter}{r}" for r in source_rows)
                formula = f"=SUM({refs})"

            if formula and col_letter:
                cell = ws[f"{col_letter}{subtotal_sheet_row}"]
                cell.value = formula

        # Write Tend vs Obj (%) formula: =IF(Objetivo=0,"",Tendencia/Objetivo)
        tend_col = col_map.get("Tend vs Obj (%)")
        tend_col_num = col_map.get("Tendencia")
        obj_col_num = col_map.get("Objetivo")
        if tend_col and tend_col_num and obj_col_num:
            formula_tend = (
                f"=IF({obj_col_num}{subtotal_sheet_row}=0,\"\","
                f"{tend_col_num}{subtotal_sheet_row}/{obj_col_num}{subtotal_sheet_row})"
            )
            cell_tend = ws[f"{tend_col}{subtotal_sheet_row}"]
            cell_tend.value = formula_tend

        # Apply bold + fill + border to the entire subtotal row
        for col_idx in range(1, n_cols + 1):
            cell = ws.cell(row=subtotal_sheet_row, column=col_idx)
            cell.font = subtotal_font
            cell.fill = subtotal_fill
            cell.border = thin_border

    # -------------------------------------------------------------------
    # Header styling: dark blue fill, white bold font, thin border
    # -------------------------------------------------------------------
    header_fill = PatternFill(
        start_color=_HEADER_FILL_COLOR, end_color=_HEADER_FILL_COLOR, fill_type="solid",
    )
    header_font = Font(bold=True, color=_HEADER_FONT_COLOR)
    for col_idx in range(1, n_cols + 1):
        cell = ws.cell(row=header_row, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin_border

    # -------------------------------------------------------------------
    # Thin borders on every data cell (preserving existing fonts/colors)
    # -------------------------------------------------------------------
    subtotal_rows_set = {rows_by_label[lbl] for lbl in _SUBTOTAL_FILLS if lbl in rows_by_label}
    for row_num in range(data_start_row, data_end_row + 1):
        if row_num in subtotal_rows_set:
            continue  # already styled above
        for col_idx in range(1, n_cols + 1):
            ws.cell(row=row_num, column=col_idx).border = thin_border

    # -------------------------------------------------------------------
    # T-022: Apply ColorScaleRule on Tend vs Obj (%) column
    # -------------------------------------------------------------------
    tend_obj_col_letter = col_map.get("Tend vs Obj (%)")
    if tend_obj_col_letter and data_start_row <= data_end_row:
        heatmap_range = f"{tend_obj_col_letter}{data_start_row}:{tend_obj_col_letter}{data_end_row}"
        color_scale = ColorScaleRule(
            start_type="num",   start_value=0,   start_color="FF0000",  # red
            mid_type="num",     mid_value=1.0,   mid_color="FFFF00",    # yellow
            end_type="num",     end_value=1.2,   end_color="00B050",    # green
        )
        ws.conditional_formatting.add(heatmap_range, color_scale)


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
        # 2. Segregar DIRECTA SUCURSALES y aplicar zonas virtuales.
        #    IMPORTANTE: segregar PRIMERO (necesita id_ruta), zonas DESPUÉS
        #    (drops id_ruta). Orden inverso pierde la segregación.
        # -----------------------------------------------------------------
        df_ventas_mes = _segregar_directa_sucursales(df_ventas_mes)
        df_ventas_mes = aplicar_zonas_virtuales(df_ventas_mes)
        if not df_ventas_mes.empty:
            df_ventas_mes = df_ventas_mes.groupby(
                ["sucursal", "generico"], as_index=False
            )["cantidad"].sum()

        df_dias = _segregar_directa_sucursales(df_dias)
        df_dias = aplicar_zonas_virtuales(df_dias)
        if not df_dias.empty:
            df_dias = df_dias.groupby(
                ["sucursal", "generico", "fecha"], as_index=False
            )["cantidad"].sum()

        df_ventas_ma = _segregar_directa_sucursales(df_ventas_ma)
        df_ventas_ma = aplicar_zonas_virtuales(df_ventas_ma)
        if not df_ventas_ma.empty:
            df_ventas_ma = df_ventas_ma.groupby(
                ["sucursal", "generico"], as_index=False
            )["cantidad"].sum()

        df_ventas_aa = _segregar_directa_sucursales(df_ventas_aa)
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
        # 4. T-019: Fetch cupos and pass to processor
        # -----------------------------------------------------------------
        periodo = config.fecha_desde[:7]  # "YYYY-MM-DD" → "YYYY-MM"
        genericos_for_cupos = genericos if genericos else _DEFAULT_GENERICOS
        try:
            df_cupos_raw = self.data_loader.get_cupos_resumen_mensual(
                periodo, genericos_for_cupos
            )
        except Exception as exc:
            logger.warning("get_cupos_resumen_mensual failed (%s) — Objetivo column will be blank", exc)
            df_cupos_raw = pd.DataFrame(columns=["sucursal", "generico", "cupo"])

        # Apply segregar + zonas to cupos (segregar PRIMERO; ver nota arriba)
        if not df_cupos_raw.empty and "id_ruta" in df_cupos_raw.columns:
            df_cupos_raw = _segregar_directa_sucursales(df_cupos_raw)
            df_cupos_raw = aplicar_zonas_virtuales(df_cupos_raw)
            df_cupos_raw = df_cupos_raw.groupby(
                ["sucursal", "generico"], as_index=False
            )["cupo"].sum()
        elif not df_cupos_raw.empty:
            # No id_ruta present — just groupby to be safe
            df_cupos_raw = df_cupos_raw.groupby(
                ["sucursal", "generico"], as_index=False
            )["cupo"].sum()

        # -----------------------------------------------------------------
        # 5. Procesar datos (una llamada para todos los genericos)
        # -----------------------------------------------------------------
        df_resultado = procesar_resumen_mensual(
            df_ventas_mes,
            df_dias,
            df_ventas_ma,
            df_ventas_aa,
            config.fecha_desde,
            config.fecha_hasta,
            config.con_objetivo,
            df_cupos=df_cupos_raw,
        )

        # -----------------------------------------------------------------
        # 6. Generar Excel: una hoja por generico
        # -----------------------------------------------------------------
        nombre = config.nombre_archivo or _nombre_reporte(df_dias, config.fecha_hasta)
        out = self._output_dir(config.fecha_desde)
        out.mkdir(parents=True, exist_ok=True)

        # Merge mode: find existing xlsx in the output folder
        existing_files = list(out.glob("*.xlsx"))
        if len(existing_files) > 1:
            raise RuntimeError(
                f"Found {len(existing_files)} xlsx files in {out}, expected at most 1. "
                f"Please clean up old files: {[str(p.name) for p in existing_files]}"
            )
        merge_target = existing_files[0] if existing_files else None

        # When merging, preserve the existing filename
        if merge_target:
            nombre = merge_target.stem

        writer = ExcelWriter(nombre, output_dir=out, merge_with=merge_target)

        genericos_resultado = (
            df_resultado["Generico"].unique().tolist() if not df_resultado.empty else []
        )

        # Detectar nombres dinámicos de columnas N-1 y N-2 (posiciones 2 y 3)
        cols = list(df_resultado.columns)
        col_n1 = cols[2] if len(cols) > 2 else "Vtas Dia N-1"
        col_n2 = cols[3] if len(cols) > 3 else "Vtas Dia N-2"

        style = _crear_estilo_resumen(info_dias, col_n1, col_n2)
        summary_rows_count = len(info_dias)  # used for row offset calculation

        for generico in genericos_resultado:
            df_hoja = df_resultado[df_resultado["Generico"] == generico].copy()
            # T-020: inject subtotal rows (ordered)
            df_hoja_ordered = _ordenar_e_inyectar_subtotales(df_hoja)
            sheet_name = generico[:31]  # Excel max 31 caracteres
            ws = writer.add_sheet(df_hoja_ordered, sheet_name=sheet_name, style=style)
            # T-020/T-022/T-023: post-write — resolve SUM formulas, heatmap, subtotal styling
            _post_write_subtotals_and_heatmap(ws, df_hoja_ordered, summary_rows_count)

        # T-09: Import Detalle Movimientos sheet from external source
        if config.detalle_movimientos_path:
            src_path = Path(config.detalle_movimientos_path)
            try:
                rows_imported = import_xlsx_as_sheet(
                    writer.workbook, src_path, "Detalle Movimientos"
                )
                logger.info(
                    "Detalle Movimientos imported: %d rows from %s", rows_imported, src_path
                )
            except FileNotFoundError:
                logger.warning(
                    "detalle_movimientos source not found: %s — skipping", src_path
                )
            except Exception as exc:
                logger.warning(
                    "detalle_movimientos import failed (%s) — skipping", exc
                )

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
