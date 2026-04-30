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


class HistoricoClienteService(BaseService):
    """Genera Excel con historico de ventas por cliente, mes a mes."""

    SERVICE_SLUG = "historico-cliente"
    GRANULARITY = "month"

    def generar_reporte(self, config: HistoricoClienteConfig) -> HistoricoClienteResult:
        # 1. Validate mutual exclusivity
        if config.articulos and config.marcas:
            raise ValueError("Config tiene 'articulos' Y 'marcas'. Especifica solo uno.")
        if not config.articulos and not config.marcas:
            raise ValueError("Config debe tener 'articulos' O 'marcas'.")

        # 2. Fetch data
        df = self.data_loader.get_ventas_historico_cliente(
            fecha_desde=config.fecha_desde,
            fecha_hasta=config.fecha_hasta,
            clientes=config.clientes,
            articulos=config.articulos,
            marcas=config.marcas,
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

            # Pivot: rows = row_key, cols = mes, values = bultos
            pivot = df_cli.pivot_table(
                index="row_key",
                columns="mes",
                values="bultos",
                aggfunc="sum",
                fill_value=0,
            ).reindex(columns=meses, fill_value=0)

            # Flatten index so row_key becomes a column
            pivot = pivot.reset_index().rename(
                columns={"row_key": "Marca" if config.marcas else "Articulo"}
            )

            # Total column
            pivot["Total"] = pivot[meses].sum(axis=1)

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

            writer.add_sheet(pivot, sheet_name=sheet_name, style=_STYLE)
            sheets_generated.append(sheet_name)
            total_registros += len(pivot)

        ruta = writer.save()

        return HistoricoClienteResult(
            ruta_archivo=ruta,
            sheets_generated=sheets_generated,
            registros_procesados=total_registros,
        )
