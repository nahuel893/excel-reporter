"""VentasCoberPreventistaMarcaService — ventas + cobertura por preventista y supervisor.

Para una marca y una sucursal, en un rango de dias, produce una hoja con dos bloques:

- POR PREVENTISTA: vendedor | supervisor | bultos | cobertura (clientes)
- POR SUPERVISOR:  supervisor | bultos | cobertura (clientes)

Cada bloque cierra con una fila TOTAL GENERAL (convencion del proyecto).

Notas clave:
- Cobertura = clientes compradores DISTINTOS (cantidades_total > 0). NO es aditiva:
  la suma por supervisor puede superar el total, porque un cliente atendido por dos
  supervisores se cuenta una sola vez en el total. Por eso se calcula por separado en
  cada nivel desde el grano (vendedor, cliente).
- El match vendedor->supervisor sale del SUPERVISOR_VENDOR_MAP curado (dim_vendedor.
  supervisor NO es confiable); se excluye al gerente (GFARAH). Vendedores no mapeados
  (ej. DIRECTA) caen en "SIN SUPERVISOR".
- El acceso a datos usa clave compuesta (id_vendedor + id_sucursal) — ver DataLoader.
"""
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.core.output_paths import service_output_dir
from src.services.base_service import BaseService
from src.services.rebotes.constants import SUPERVISOR_VENDOR_MAP

logger = logging.getLogger(__name__)

GERENTE_KEY = "GFARAH"
SIN_SUPERVISOR = "SIN SUPERVISOR"
ID_SUCURSAL_CASA_CENTRAL = 1

HEADER_FILL, HEADER_FONT = "90A4AE", "FFFFFF"
SECTION_FILL, SECTION_FONT = "546E7A", "FFFFFF"
TOTAL_FILL = "FFE08A"  # ámbar — fila TOTAL GENERAL
_FMT_BULTOS, _FMT_COB = "#,##0.00", "#,##0"
_SHEET_TITLE = "Ventas Cob x Preventista"


@dataclass
class VentasCoberPreventistaMarcaConfig:
    marca: str
    fecha_desde: str
    fecha_hasta: str
    id_sucursal: int = ID_SUCURSAL_CASA_CENTRAL
    nombre_archivo: str | None = None


@dataclass
class VentasCoberPreventistaMarcaResult:
    ruta_archivo: Path
    preventistas: int
    total_bultos: float
    cobertura_total: int
    fecha_desde: str
    fecha_hasta: str


def _vendor_to_supervisor() -> dict[str, str]:
    """Invierte SUPERVISOR_VENDOR_MAP → {vendedor_upper: supervisor}, sin el gerente."""
    result: dict[str, str] = {}
    for sup, vendors in SUPERVISOR_VENDOR_MAP.items():
        if sup == GERENTE_KEY:
            continue
        for v in vendors:
            result[v.upper()] = sup
    return result


def _thin() -> Border:
    s = Side(style="thin", color="D0D0D0")
    return Border(left=s, right=s, top=s, bottom=s)


def _agg(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Suma bultos + cuenta clientes distintos con compra > 0, agrupado por `keys`."""
    g = df.groupby(keys, as_index=False).agg(bultos=("bultos", "sum"))
    cob = (
        df[df["bultos"] > 0].groupby(keys)["id_cliente"].nunique().rename("cobertura")
    )
    out = g.merge(cob, on=keys, how="left")
    out["cobertura"] = out["cobertura"].fillna(0).astype(int)
    return out.sort_values("bultos", ascending=False)


class VentasCoberPreventistaMarcaService(BaseService):
    SERVICE_SLUG = "ventas-cober-preventista-marca"
    GRANULARITY = "month"

    def generar_reporte(
        self, config: VentasCoberPreventistaMarcaConfig
    ) -> VentasCoberPreventistaMarcaResult:
        raw = self.data_loader.get_ventas_cobertura_por_vendedor(
            marca=config.marca,
            fecha_desde=config.fecha_desde,
            fecha_hasta=config.fecha_hasta,
            id_sucursal=config.id_sucursal,
        )
        if raw.empty:
            logger.warning(
                "Sin ventas para marca=%s fechas=%s..%s suc=%s",
                config.marca, config.fecha_desde, config.fecha_hasta, config.id_sucursal,
            )
            raw = pd.DataFrame(columns=["vendedor", "id_cliente", "bultos"])

        raw = raw.copy()
        raw["vendedor"] = raw["vendedor"].fillna("(sin vendedor)")
        raw["bultos"] = raw["bultos"].fillna(0.0)
        raw["supervisor"] = raw["vendedor"].str.upper().map(_vendor_to_supervisor()).fillna(SIN_SUPERVISOR)

        by_vend = _agg(raw, ["vendedor", "supervisor"])
        by_sup = _agg(raw, ["supervisor"])
        total_bultos = float(raw["bultos"].sum())
        cobertura_total = int(raw[raw["bultos"] > 0]["id_cliente"].nunique())

        nombre = config.nombre_archivo or f"Ventas y Cobertura {config.marca} por Preventista"
        out_dir = service_output_dir(self.SERVICE_SLUG, config.fecha_desde, granularity="month")
        out_dir.mkdir(parents=True, exist_ok=True)
        ruta = out_dir / f"{nombre}.xlsx"

        self._build_workbook(config, by_vend, by_sup, total_bultos, cobertura_total, ruta)

        return VentasCoberPreventistaMarcaResult(
            ruta_archivo=ruta,
            preventistas=len(by_vend),
            total_bultos=total_bultos,
            cobertura_total=cobertura_total,
            fecha_desde=config.fecha_desde,
            fecha_hasta=config.fecha_hasta,
        )

    def _build_workbook(
        self, config, by_vend, by_sup, total_bultos, cobertura_total, ruta: Path
    ) -> None:
        wb = Workbook()
        ws = wb.active
        ws.title = _SHEET_TITLE
        border = _thin()
        header_fill = PatternFill("solid", fgColor=HEADER_FILL)
        section_fill = PatternFill("solid", fgColor=SECTION_FILL)
        total_fill = PatternFill("solid", fgColor=TOTAL_FILL)

        fecha_txt = (
            config.fecha_desde if config.fecha_desde == config.fecha_hasta
            else f"{config.fecha_desde} a {config.fecha_hasta}"
        )
        ws["A1"] = f"Ventas y Cobertura — {config.marca}"
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = f"Sucursal: {config.id_sucursal}  |  {fecha_txt}  |  Cobertura = clientes compradores"
        ws["A2"].font = Font(italic=True, size=10, color="546E7A")

        def section(r: int, title: str, headers: list[str]) -> int:
            ws.cell(r, 1, title).font = Font(bold=True, color=SECTION_FONT, size=12)
            for c in range(1, 5):
                ws.cell(r, c).fill = section_fill
            r += 1
            for c, h in enumerate(headers, 1):
                cell = ws.cell(r, c, h)
                cell.fill = header_fill
                cell.font = Font(bold=True, color=HEADER_FONT)
                cell.alignment = Alignment(horizontal="center")
                cell.border = border
            return r + 1

        def measure_cells(r: int, bultos: float, cob: int) -> None:
            cb = ws.cell(r, 3, float(bultos)); cb.number_format = _FMT_BULTOS
            cb.border = border; cb.alignment = Alignment(horizontal="right")
            cc = ws.cell(r, 4, int(cob)); cc.number_format = _FMT_COB
            cc.border = border; cc.alignment = Alignment(horizontal="right")

        def total_row(r: int) -> int:
            ws.cell(r, 1, "TOTAL GENERAL").font = Font(bold=True)
            for c in range(1, 5):
                ws.cell(r, c).fill = total_fill
                ws.cell(r, c).border = border
                ws.cell(r, c).font = Font(bold=True)
            measure_cells(r, total_bultos, cobertura_total)
            ws.cell(r, 3).fill = total_fill
            ws.cell(r, 4).fill = total_fill
            return r + 2

        r = 4
        r = section(r, "POR PREVENTISTA", ["Vendedor", "Supervisor", "Bultos", "Cobertura"])
        for _, row in by_vend.iterrows():
            ws.cell(r, 1, row["vendedor"]).border = border
            ws.cell(r, 2, row["supervisor"]).border = border
            measure_cells(r, row["bultos"], row["cobertura"])
            r += 1
        r = total_row(r)

        r = section(r, "POR SUPERVISOR", ["Supervisor", "", "Bultos", "Cobertura"])
        for _, row in by_sup.iterrows():
            ws.cell(r, 1, row["supervisor"]).border = border
            ws.cell(r, 2, "").border = border
            measure_cells(r, row["bultos"], row["cobertura"])
            r += 1
        r = total_row(r)

        for c, w in zip(range(1, 5), (26, 16, 12, 12)):
            ws.column_dimensions[get_column_letter(c)].width = w
        ws.freeze_panes = "A5"
        wb.save(ruta)

    def run(self, config):
        return self.generar_reporte(config)
