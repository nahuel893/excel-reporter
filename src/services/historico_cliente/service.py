"""
HistoricoClienteService - Ventas historicas por cliente, una hoja por cliente,
filas = articulos o marcas (segun filtro en config), columnas = meses.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.core.excel_writer import ExcelWriter, SheetStyle, ColumnFormat
from src.core.output_paths import service_output_dir
from src.services.base_service import BaseService

logger = logging.getLogger(__name__)


@dataclass
class HistoricoClienteConfig:
    """Configuracion para el reporte historico por cliente."""
    fecha_desde: str
    fecha_hasta: str
    clientes: list[dict]                  # {"id_cliente": int, "id_sucursal": int}
    articulos: list[int] | None = None    # mutually exclusive with marcas
    marcas: list[str] | None = None       # mutually exclusive with articulos
    # When True: show ALL marcas grouped by generico, with a subtotal row per
    # generico and a grand-total row. No marca/articulo filter required.
    agrupar_por_generico: bool = False
    # When True (requires agrupar_por_generico): fill the FULL marca universe of
    # `genericos_universo` (from dim_articulo), showing 0 for marcas the client
    # did not buy — highlights coverage gaps.
    marcas_completas: bool = False
    genericos_universo: list[str] | None = None
    nombre_archivo: str | None = None


@dataclass
class HistoricoClienteResult:
    """Resultado del reporte historico por cliente."""
    ruta_archivo: Path
    sheets_generated: list[str]
    registros_procesados: int


_STYLE = SheetStyle(
    numeric_format="#,##0.##",
    column_formats={},
    as_table=True,
    table_style="TableStyleMedium9",
)

# Grouped mode uses a plain (non-table) sheet so subtotal/grand-total rows can be
# interleaved. Header styling is applied by ExcelWriter; subtotal/grand rows are
# post-styled below.
_GROUPED_STYLE = SheetStyle(
    numeric_format="#,##0.##",
    column_formats={},
    as_table=False,
)

# Fill colors for interleaved summary rows (readable in a LibreOffice capture).
_SUBTOTAL_FILL = "D6E0F0"   # light blue — per-generico subtotal
_GRAND_FILL = "FFE08A"      # amber — grand total
_ZERO_FILL = "F2F2F2"       # light gray — marca sin venta (hueco de compra)
_ZERO_FONT = "9E9E9E"       # gray font for zero rows
_GENERICO_COL = "Genérico"
_MARCA_COL = "Marca"
_TOTAL_COL = "Total"


class HistoricoClienteService(BaseService):
    """Genera Excel con historico de ventas por cliente, mes a mes."""

    SERVICE_SLUG = "historico-cliente"
    GRANULARITY = "month"

    def generar_reporte(self, config: HistoricoClienteConfig) -> HistoricoClienteResult:
        # 1. Validate filter combination
        if config.articulos and config.marcas:
            raise ValueError("Config tiene 'articulos' Y 'marcas'. Especifica solo uno.")
        # Grouped mode shows all marcas grouped by generico → no filter required.
        if not config.agrupar_por_generico and not config.articulos and not config.marcas:
            raise ValueError(
                "Config debe tener 'articulos' O 'marcas' (o usar 'agrupar_por_generico')."
            )

        # 2. Fetch data
        df = self.data_loader.get_ventas_historico_cliente(
            fecha_desde=config.fecha_desde,
            fecha_hasta=config.fecha_hasta,
            clientes=config.clientes,
            articulos=config.articulos,
            marcas=config.marcas,
            agrupar_por_generico=config.agrupar_por_generico,
        )

        # 2b. Optional: full marca universe (for the "marcas completas" mode)
        universe_df = None
        if config.agrupar_por_generico and config.marcas_completas:
            universe_df = self.data_loader.get_marca_universe(
                config.genericos_universo or []
            )

        # 3. Build full month range from config
        meses = (
            pd.date_range(
                start=config.fecha_desde, end=config.fecha_hasta, freq="MS"
            )
            .strftime("%Y-%m")
            .tolist()
        )

        # 4. Build Excel
        nombre = config.nombre_archivo or "Historico Cliente"
        output_dir = service_output_dir("historico-cliente", config.fecha_desde, granularity="month")
        writer = ExcelWriter(nombre, output_dir=output_dir)

        sheets_generated: list[str] = []
        total_registros = 0

        for cliente_cfg in config.clientes:
            id_cli = cliente_cfg["id_cliente"]
            id_suc = cliente_cfg["id_sucursal"]

            df_cli = df[(df["id_cliente"] == id_cli) & (df["id_sucursal"] == id_suc)]
            if df_cli.empty:
                logger.warning(
                    "Cliente id_cliente=%d id_sucursal=%d sin datos, se omite la hoja.",
                    id_cli, id_suc,
                )
                continue

            # Sheet name: nombre_cliente or fallback, truncated to 31 chars
            nombre_cliente = str(df_cli["nombre_cliente"].iloc[0])
            sheet_name = (nombre_cliente or f"{id_cli}-{id_suc}")[:31]
            # Avoid duplicates if truncated name collides
            base = sheet_name
            counter = 1
            while sheet_name in sheets_generated:
                suffix = f" ({counter})"
                sheet_name = base[: 31 - len(suffix)] + suffix
                counter += 1

            if config.agrupar_por_generico:
                sheet_df, subtotal_rows, grand_row, zero_rows = _build_grouped_frame(
                    df_cli, meses, universe_df
                )
                writer.add_sheet(sheet_df, sheet_name=sheet_name, style=_GROUPED_STYLE)
                _style_summary_rows(
                    writer.workbook[sheet_name], subtotal_rows, grand_row, zero_rows,
                    n_cols=len(sheet_df.columns),
                )
                total_registros += len(sheet_df)
            else:
                # Pivot: rows = row_key, cols = mes, values = bultos
                pivot = df_cli.pivot_table(
                    index="row_key",
                    columns="mes",
                    values="bultos",
                    aggfunc="sum",
                    fill_value=0,
                ).reindex(columns=meses, fill_value=0)

                pivot = pivot.reset_index().rename(
                    columns={"row_key": "Marca" if config.marcas else "Articulo"}
                )
                pivot["Total"] = pivot[meses].sum(axis=1)

                writer.add_sheet(pivot, sheet_name=sheet_name, style=_STYLE)
                total_registros += len(pivot)

            sheets_generated.append(sheet_name)

        ruta = writer.save()

        return HistoricoClienteResult(
            ruta_archivo=ruta,
            sheets_generated=sheets_generated,
            registros_procesados=total_registros,
        )


def _build_grouped_frame(
    df_cli: pd.DataFrame, meses: list[str], universe_df: pd.DataFrame | None = None
) -> tuple[pd.DataFrame, list[int], int, list[int]]:
    """Build the grouped-by-generico sheet frame with interleaved summary rows.

    Rows are: for each generico (ordered by descending total) its marcas (also by
    descending total), followed by a ``TOTAL {generico}`` subtotal row; finally a
    ``TOTAL GENERAL`` grand-total row.

    When ``universe_df`` (columns generico, marca) is provided, the frame is
    reindexed onto the full marca universe so marcas the client never bought
    appear with 0 across every month (coverage-gap view).

    Returns:
        (frame, subtotal_row_indices, grand_row_index, zero_row_indices) where the
        row indices are 0-based positions within the frame's data rows (excluding
        the header). ``zero_row_indices`` are marca rows whose Total is 0.
    """
    # Pivot at (generico, marca) grain, then reindex months to the full range.
    pivot = df_cli.pivot_table(
        index=["generico", "row_key"],
        columns="mes",
        values="bultos",
        aggfunc="sum",
        fill_value=0,
    ).reindex(columns=meses, fill_value=0)

    # Fill the full marca universe with 0 for marcas the client did not buy.
    if universe_df is not None and not universe_df.empty:
        uni_index = pd.MultiIndex.from_frame(
            universe_df.rename(columns={"marca": "row_key"})[["generico", "row_key"]]
        )
        pivot = pivot.reindex(uni_index.union(pivot.index), fill_value=0)

    pivot["Total"] = pivot[meses].sum(axis=1)

    gen_totales = (
        pivot["Total"].groupby(level="generico").sum().sort_values(ascending=False)
    )

    records: list[dict] = []
    subtotal_rows: list[int] = []
    zero_rows: list[int] = []
    for generico in gen_totales.index:
        block = pivot.xs(generico, level="generico").sort_values(
            "Total", ascending=False
        )
        for marca, row in block.iterrows():
            if row[_TOTAL_COL] == 0:
                zero_rows.append(len(records))
            records.append(
                {_GENERICO_COL: generico, _MARCA_COL: marca,
                 **{m: row[m] for m in meses}, _TOTAL_COL: row[_TOTAL_COL]}
            )
        # Subtotal row for this generico
        subtotal_rows.append(len(records))
        records.append(
            {_GENERICO_COL: "", _MARCA_COL: f"TOTAL {generico}",
             **{m: block[m].sum() for m in meses}, _TOTAL_COL: block[_TOTAL_COL].sum()}
        )

    # Grand total
    grand_row = len(records)
    records.append(
        {_GENERICO_COL: "", _MARCA_COL: "TOTAL GENERAL",
         **{m: pivot[m].sum() for m in meses}, _TOTAL_COL: pivot[_TOTAL_COL].sum()}
    )

    frame = pd.DataFrame(records, columns=[_GENERICO_COL, _MARCA_COL, *meses, _TOTAL_COL])
    return frame, subtotal_rows, grand_row, zero_rows


def _style_summary_rows(
    ws, subtotal_rows: list[int], grand_row: int, zero_rows: list[int], n_cols: int
) -> None:
    """Fill the subtotal, grand-total and zero-sale rows of the grouped sheet.

    Row indices are 0-based within the data rows; the worksheet header occupies
    row 1, so data row ``i`` maps to worksheet row ``i + 2``.
    """
    from openpyxl.styles import Font, PatternFill

    def _paint(data_idx: int, color: str, *, bold: bool = True, font_color: str | None = None) -> None:
        excel_row = data_idx + 2
        fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
        for col in range(1, n_cols + 1):
            cell = ws.cell(row=excel_row, column=col)
            cell.fill = fill
            cell.font = Font(bold=bold, color=font_color)

    # Zero-sale rows first (subtotal/grand override if they ever collided).
    for idx in zero_rows:
        _paint(idx, _ZERO_FILL, bold=False, font_color=_ZERO_FONT)
    for idx in subtotal_rows:
        _paint(idx, _SUBTOTAL_FILL)
    _paint(grand_row, _GRAND_FILL)
