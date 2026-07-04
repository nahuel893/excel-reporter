"""VentasMarcaService — cantidad vendida por marca de un generico.

Reporte simple: una fila por marca del generico con la cantidad vendida (bultos)
en un rango de dias, ordenado de mayor a menor, con una fila TOTAL GENERAL
(convencion del proyecto: todo informe lleva fila de totales).
"""
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from src.core.output_paths import service_output_dir
from src.services.base_service import BaseService

logger = logging.getLogger(__name__)

HEADER_FILL, HEADER_FONT = "4472C4", "FFFFFF"
TOTAL_FILL = "FFE08A"  # ámbar — fila TOTAL GENERAL
ID_SUCURSAL_CASA_CENTRAL = 1


@dataclass
class VentasMarcaConfig:
    """Config del reporte de ventas por marca.

    Args:
        generico: Nombre exacto del generico (ej. 'PERNOD RICARD').
        fecha: Dia desde (YYYY-MM-DD).
        fecha_hasta: Dia hasta (YYYY-MM-DD). None → mismo dia que `fecha`.
        id_sucursal: Sucursal a filtrar (default 1 = CASA CENTRAL).
        nombre_archivo: nombre de salida (sin extension).
    """
    generico: str
    fecha: str
    fecha_hasta: str | None = None
    id_sucursal: int = ID_SUCURSAL_CASA_CENTRAL
    nombre_archivo: str | None = None


@dataclass
class VentasMarcaResult:
    """Resultado del reporte."""
    ruta_archivo: Path
    marcas: int
    total_bultos: float
    fecha_desde: str
    fecha_hasta: str


def _thin_border() -> Border:
    s = Side(style="thin", color="D9D9D9")
    return Border(left=s, right=s, top=s, bottom=s)


class VentasMarcaService(BaseService):
    """Genera el reporte de cantidad vendida por marca de un generico."""

    SERVICE_SLUG = "ventas-marca"
    GRANULARITY = "month"

    def generar_reporte(self, config: VentasMarcaConfig) -> VentasMarcaResult:
        fecha_desde = config.fecha
        fecha_hasta = config.fecha_hasta or config.fecha

        df = self.data_loader.get_ventas_por_marca(
            generico=config.generico,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_sucursal=config.id_sucursal,
        )
        if df.empty:
            logger.warning(
                "Sin ventas para generico=%s fechas=%s..%s suc=%s",
                config.generico, fecha_desde, fecha_hasta, config.id_sucursal,
            )
            df = pd.DataFrame(columns=["marca", "bultos"])

        df = df.copy()
        df["marca"] = df["marca"].fillna("(sin marca)")
        df["bultos"] = df["bultos"].fillna(0.0)
        total = float(df["bultos"].sum())

        nombre = config.nombre_archivo or f"Venta por Marca {config.generico} - {config.fecha}"
        out_dir = service_output_dir(self.SERVICE_SLUG, config.fecha, granularity="month")
        out_dir.mkdir(parents=True, exist_ok=True)
        ruta = out_dir / f"{nombre}.xlsx"

        self._build_workbook(config, fecha_desde, fecha_hasta, df, total, ruta)

        return VentasMarcaResult(
            ruta_archivo=ruta,
            marcas=len(df),
            total_bultos=total,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )

    def _build_workbook(
        self, config: VentasMarcaConfig, fecha_desde: str, fecha_hasta: str,
        df: pd.DataFrame, total: float, ruta: Path,
    ) -> None:
        wb = Workbook()
        ws = wb.active
        ws.title = "Venta x Marca"
        border = _thin_border()

        ws.column_dimensions["A"].width = 26
        ws.column_dimensions["B"].width = 14

        ws["A1"] = f"Venta por Marca — {config.generico}"
        ws["A1"].font = Font(bold=True, size=13)
        fecha_txt = fecha_desde if fecha_desde == fecha_hasta else f"{fecha_desde} a {fecha_hasta}"
        ws["A2"] = f"Fecha: {fecha_txt}  |  Sucursal: {config.id_sucursal}  |  Cantidad vendida (bultos)"
        ws["A2"].font = Font(italic=True, size=10, color="546E7A")

        # Header
        for j, h in enumerate(["Marca", "Cantidad"], 1):
            hc = ws.cell(4, j, h)
            hc.fill = PatternFill(start_color=HEADER_FILL, end_color=HEADER_FILL, fill_type="solid")
            hc.font = Font(bold=True, color=HEADER_FONT)
            hc.alignment = Alignment(horizontal="center")
            hc.border = border

        row = 5
        for _, r in df.iterrows():
            ca = ws.cell(row, 1, r["marca"])
            ca.border = border
            ca.font = Font(bold=True)
            cb = ws.cell(row, 2, float(r["bultos"]))
            cb.number_format = "#,##0.00"
            cb.border = border
            cb.alignment = Alignment(horizontal="right")
            row += 1

        # TOTAL GENERAL (convencion: todo informe lleva fila de totales)
        tot_fill = PatternFill(start_color=TOTAL_FILL, end_color=TOTAL_FILL, fill_type="solid")
        cta = ws.cell(row, 1, "TOTAL GENERAL")
        cta.font = Font(bold=True)
        cta.fill = tot_fill
        cta.border = border
        ctb = ws.cell(row, 2, total)
        ctb.number_format = "#,##0.00"
        ctb.font = Font(bold=True)
        ctb.fill = tot_fill
        ctb.border = border
        ctb.alignment = Alignment(horizontal="right")

        wb.save(ruta)

    def run(self, config: VentasMarcaConfig) -> VentasMarcaResult:
        return self.generar_reporte(config)
