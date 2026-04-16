"""
AvancesService - Refreshes raw DB data in existing avances Excel files,
preserving formulas and table definitions.
"""

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from config.settings import DATA_OUTPUT
from src.core.excel_updater import replace_sheet_data
from src.services.base_service import BaseService

logger = logging.getLogger(__name__)


@dataclass
class SheetConfig:
    """Maps an Excel sheet to its DB query and writable columns."""

    sheet_name: str
    query_method: str  # DataLoader method name
    query_params: list[str] = field(default_factory=list)  # param names from AvancesConfig
    data_columns: list[str] = field(default_factory=list)
    header_row: int = 1


SHEET_CONFIGS = [
    SheetConfig(
        sheet_name="gold fact_ventas",
        query_method="get_fact_ventas_raw",
        query_params=["fecha_desde", "fecha_hasta"],
        data_columns=[
            "id_cliente", "id_articulo", "id_vendedor", "id_sucursal",
            "fecha_comprobante", "id_documento", "letra", "serie", "nro_doc",
            "anulado", "cantidades_total", "bonificacion",
        ],
        header_row=1,
    ),
    SheetConfig(
        sheet_name="gold dim_articulo",
        query_method="get_dim_articulo_raw",
        data_columns=[
            "id_articulo", "des_articulo", "marca", "generico", "calibre",
            "proveedor", "unidad_negocio", "factor_hectolitros",
        ],
        header_row=1,
    ),
    SheetConfig(
        sheet_name="gold dim_cliente",
        query_method="get_dim_cliente_raw",
        data_columns=[
            "id_cliente", "fantasia", "razon_social", "des_sucursal", "id_sucursal",
            "id_ruta_fv1", "des_personal_fv1", "id_ruta_fv4", "des_personal_fv4",
        ],
        header_row=2,
    ),
    SheetConfig(
        sheet_name="cob_preventista_generico",
        query_method="get_cob_preventista_generico_raw",
        query_params=["fecha_desde", "fecha_hasta"],
        data_columns=[
            "id", "periodo", "id_fuerza_ventas", "id_vendedor", "id_ruta",
            "id_sucursal", "ds_sucursal", "generico", "clientes_compradores",
            "volumen_total",
        ],
        header_row=1,
    ),
    SheetConfig(
        sheet_name="cob_preventista_marca",
        query_method="get_cob_preventista_marca_raw",
        query_params=["fecha_desde", "fecha_hasta"],
        data_columns=[
            "id", "periodo", "id_fuerza_ventas", "id_vendedor", "id_ruta",
            "id_sucursal", "ds_sucursal", "marca", "clientes_compradores",
            "volumen_total",
        ],
        header_row=1,
    ),
]


@dataclass
class AvancesConfig:
    """Configuracion para el reporte de avances."""

    archivo_plantilla: str  # path to template Excel
    fecha_desde: str
    fecha_hasta: str
    nombre_archivo: str | None = None


@dataclass
class AvancesResult:
    """Resultado de la generacion del reporte de avances."""

    ruta_archivo: Path
    registros_por_hoja: dict[str, int]


class AvancesService(BaseService):
    """Refreshes raw DB data in existing avances Excel files."""

    def generar_reporte(self, config: AvancesConfig) -> AvancesResult:
        plantilla = Path(config.archivo_plantilla)
        if not plantilla.exists():
            raise FileNotFoundError(f"Template not found: {plantilla}")

        # Output path — copy template to data/output
        nombre = config.nombre_archivo or plantilla.stem
        output_path = DATA_OUTPUT / f"{nombre}.xlsx"

        if output_path.resolve() == plantilla.resolve():
            raise ValueError("Output path must differ from template")

        shutil.copy2(plantilla, output_path)

        logger.info("Cargando workbook %s ...", output_path.name)
        t0 = time.perf_counter()
        wb = load_workbook(output_path, data_only=False, keep_links=False)
        logger.info("Workbook cargado en %.1fs", time.perf_counter() - t0)

        registros = {}

        for sc in SHEET_CONFIGS:
            if sc.sheet_name not in wb.sheetnames:
                logger.info("Sheet '%s' not found, creating", sc.sheet_name)
                ws = wb.create_sheet(sc.sheet_name)
                for col_idx, col_name in enumerate(sc.data_columns, 1):
                    ws.cell(row=sc.header_row, column=col_idx, value=col_name)

            # Build query params from config
            params = {p: getattr(config, p) for p in sc.query_params}
            method = getattr(self.data_loader, sc.query_method)

            logger.info("Query %s(%s) ...", sc.query_method, params or "")
            t1 = time.perf_counter()
            df = method(**params) if params else method()
            logger.info("Query %s: %d filas en %.1fs", sc.query_method, len(df), time.perf_counter() - t1)

            t2 = time.perf_counter()
            rows = replace_sheet_data(
                wb, sc.sheet_name, df, sc.data_columns, sc.header_row
            )
            logger.info("Sheet '%s': %d filas escritas en %.1fs", sc.sheet_name, rows, time.perf_counter() - t2)
            registros[sc.sheet_name] = rows

        logger.info("Guardando workbook ...")
        t3 = time.perf_counter()
        wb.save(output_path)
        wb.close()
        logger.info("Guardado en %.1fs -> %s", time.perf_counter() - t3, output_path)

        return AvancesResult(ruta_archivo=output_path, registros_por_hoja=registros)
