"""CoberturaLeviteService — Reporte de cobertura de Levite abierta por calibre.

Genera un archivo Excel con dos hojas:
1. Cobertura por Calibre: Matriz de sucursales con cobertura por calibre + Resumen consolidado.
2. Clientes Compradores: Detalle de todos los clientes compradores con volumen por calibre en columnas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from datetime import date, datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.core.data_loader import DataLoader
from src.core.output_paths import service_output_dir
from src.services.base_service import BaseService

from .processor import (
    CATEGORIAS,
    extraer_calibre,
    matriz_calibre_marca,
    ordenar_calibres,
    procesar_cobertura_sucursal_calibre,
)

logger = logging.getLogger(__name__)

# Paleta de colores institucional
HEADER_FILL = "1F4E78"       # Azul corporativo oscuro
HEADER_FONT = "FFFFFF"       # Blanco
SUC_FILL = "DDEBF7"          # Azul claro
SUBTOTAL_FILL = "F2F2F2"     # Gris suave
TOTAL_SUC_FILL = "FFF2CC"    # Amarillo pastel
TOTAL_GRAL_FILL = "FFE08A"   # Dorado / Ambar para totales generales
ACCENT_FILL = "E2EFDA"       # Verde pastel para totales de fila


@dataclass
class CoberturaLeviteConfig:
    """Configuracion del reporte de cobertura de Levite por calibre."""
    fecha_desde: str
    fecha_hasta: str
    umbral: float = 0.0
    nombre_archivo: str | None = None
    # Sucursales del informe, por id. None = todas. El padron se filtra con el
    # MISMO criterio: es el denominador del % y tiene que salir del mismo
    # universo que las ventas.
    sucursales: list[int] | None = None


@dataclass
class CoberturaLeviteResult:
    """Resultado de la generacion del reporte."""
    ruta_archivo: Path
    sucursales: int
    clientes_compradores: int
    volumen_total: float
    padron_total: int


def _thin_border() -> Border:
    s = Side(style="thin", color="D9D9D9")
    return Border(left=s, right=s, top=s, bottom=s)


class CoberturaLeviteService(BaseService):
    """Servicio para generar el reporte de cobertura de Levite por calibre."""

    SERVICE_SLUG = "cobertura-levite"
    GRANULARITY = "month"

    def _fetch_ventas(
        self, fecha_desde: str, fecha_hasta: str,
        marcas: list[str] | None = None, sucursales: list[int] | None = None,
    ) -> pd.DataFrame:
        """Ventas con joins compuestos y clasificacion por calibre.

        `marcas` por defecto es solo LEVITE, que es lo que consumen las dos
        primeras hojas. La matriz calibre x marca pide el universo de aguas
        entero, asi que la consulta se hace UNA vez con todas y cada hoja
        filtra lo suyo: doce consultas iguales salvo el WHERE serian doce veces
        el mismo trabajo, y podrian caer en momentos distintos y no cerrar.
        """
        query = """
        SELECT 
            fv.id_sucursal,
            ds.descripcion AS sucursal,
            fv.id_cliente,
            COALESCE(
                NULLIF(TRIM(dc.fantasia), ''),
                NULLIF(TRIM(dc.razon_social), ''),
                CONCAT('CLIENTE ', fv.id_cliente)
            ) AS cliente,
            COALESCE(dc.id_ruta_fv1, 0) AS id_ruta,
            COALESCE(dv.des_vendedor, 'SIN VENDEDOR') AS vendedor,
            fv.id_articulo,
            da.des_articulo,
            da.marca,
            SUM(fv.cantidades_total) AS bultos
        FROM gold.fact_ventas fv
        JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
        JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
        JOIN gold.dim_vendedor dv ON fv.id_vendedor = dv.id_vendedor AND fv.id_sucursal = dv.id_sucursal
        LEFT JOIN gold.dim_cliente dc ON fv.id_cliente = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
        WHERE da.marca = ANY(:marcas)
          {filtro_suc}
          AND fv.anulado = false
          AND dv.id_fuerza_ventas = 1
          AND fv.fecha_comprobante >= :desde
          AND fv.fecha_comprobante <= :hasta
        GROUP BY 
            fv.id_sucursal, ds.descripcion, fv.id_cliente, 
            COALESCE(
                NULLIF(TRIM(dc.fantasia), ''),
                NULLIF(TRIM(dc.razon_social), ''),
                CONCAT('CLIENTE ', fv.id_cliente)
            ),
            COALESCE(dc.id_ruta_fv1, 0), COALESCE(dv.des_vendedor, 'SIN VENDEDOR'),
            fv.id_articulo, da.des_articulo, da.marca
        """
        params = {
            "desde": fecha_desde, "hasta": fecha_hasta,
            "marcas": list(marcas or ["LEVITE"]),
        }
        if sucursales:
            query = query.replace("{filtro_suc}", "AND fv.id_sucursal = ANY(:sucursales)")
            params["sucursales"] = list(sucursales)
        else:
            query = query.replace("{filtro_suc}", "")
        df = self.data_loader.execute_query(query, params)
        if not df.empty:
            df["calibre"] = df["des_articulo"].apply(extraer_calibre)
        else:
            df["calibre"] = pd.Series(dtype=str)
        return df

    def _fetch_padron(self, sucursales: list[int] | None = None) -> pd.DataFrame:
        """Obtiene el padron de clientes activos (no anulados) por sucursal."""
        query = """
        SELECT 
            dc.id_sucursal,
            ds.descripcion AS sucursal,
            COUNT(DISTINCT dc.id_cliente) AS padron
        FROM gold.dim_cliente dc
        JOIN gold.dim_sucursal ds ON dc.id_sucursal = ds.id_sucursal
        WHERE dc.anulado = false
          {filtro_suc}
        GROUP BY dc.id_sucursal, ds.descripcion
        ORDER BY ds.descripcion
        """
        # El MISMO recorte que las ventas: el padron es el denominador del % y
        # con otro universo el porcentaje compara cosas distintas.
        params: dict = {}
        if sucursales:
            query = query.replace("{filtro_suc}", "AND dc.id_sucursal = ANY(:sucursales)")
            params["sucursales"] = list(sucursales)
        else:
            query = query.replace("{filtro_suc}", "")
        return self.data_loader.execute_query(query, params)

    def generar_reporte(self, config: CoberturaLeviteConfig) -> CoberturaLeviteResult:
        """Ejecuta la extraccion, transformacion y generacion del workbook Excel."""
        logger.info("Generando reporte Cobertura Levite por Calibre (%s a %s)...", config.fecha_desde, config.fecha_hasta)
        
        # Una sola consulta con TODO el universo; cada hoja filtra lo suyo.
        marcas_universo = [m for _, ms in CATEGORIAS for m in ms]
        df_todo = self._fetch_ventas(
            config.fecha_desde, config.fecha_hasta, marcas_universo, config.sucursales
        )
        df_ventas = df_todo[df_todo["marca"] == "LEVITE"].copy()
        df_padron = self._fetch_padron(config.sucursales)
        
        calibres_presentes = ordenar_calibres(list(df_ventas["calibre"].unique())) if not df_ventas.empty else ["500cc", "1500cc", "2250cc"]
        calibres_activos = [c for c in calibres_presentes if c != "OTRO"]
        
        df_matriz, df_resumen_cal = procesar_cobertura_sucursal_calibre(df_ventas, df_padron, calibres_activos)
        
        out_dir = service_output_dir(self.SERVICE_SLUG, config.fecha_hasta, granularity="month")
        out_dir.mkdir(parents=True, exist_ok=True)
        
        nombre = config.nombre_archivo or f"Cobertura Levite por Calibre - {config.fecha_hasta}"
        ruta_archivo = out_dir / f"{nombre}.xlsx"
        
        # El informe es UN cuadro. Las hojas de matriz por sucursal y de detalle
        # de clientes se sacaron el 2026-08-19 a pedido de Nahuel: lo que se
        # mira es la apertura calibre x marca, y el resto solo agrandaba el
        # archivo que va por mail todos los dias.
        wb = Workbook()
        ws_cal_marca = wb.active
        ws_cal_marca.title = "Calibre x Marca"

        df_cal_marca, bloques = matriz_calibre_marca(
            df_todo[df_todo["calibre"] != "OTRO"], CATEGORIAS, config.umbral
        )
        if df_cal_marca.empty:
            raise ValueError(
                f"Sin ventas de aguas entre {config.fecha_desde} y "
                f"{config.fecha_hasta} para las sucursales {config.sucursales or 'todas'}"
            )
        self._build_hoja_calibre_marca(ws_cal_marca, config, df_cal_marca, bloques)
        
        wb.save(ruta_archivo)
        logger.info("Reporte guardado en %s", ruta_archivo)
        
        total_gen = df_matriz[df_matriz["es_total_general"]].iloc[0] if not df_matriz.empty else None
        
        return CoberturaLeviteResult(
            ruta_archivo=ruta_archivo,
            sucursales=len(df_padron),
            clientes_compradores=int(total_gen["cob_total"]) if total_gen is not None else 0,
            volumen_total=float(total_gen["vol_total"]) if total_gen is not None else 0.0,
            padron_total=int(df_padron["padron"].sum()),
        )

    def _build_hoja_calibre_marca(
        self, ws: Worksheet, config: "CoberturaLeviteConfig",
        df: pd.DataFrame, bloques: list[tuple[str, list[str]]],
    ) -> None:
        """Calibre en filas, marcas en columnas, agrupadas por categoria.

        La celda es cobertura: clientes DISTINTOS que compraron ese calibre de
        esa marca. Ningun total sale de sumar la fila o la columna — todos se
        recalculan en el processor, porque el mismo cliente compra varios
        calibres y varias marcas.
        """
        ws.cell(1, 1, "Cobertura por Calibre y Marca").font = Font(bold=True, size=14)
        ws.cell(
            2, 1,
            f"Clientes distintos con compra neta > 0 | {config.fecha_desde} a "
            f"{config.fecha_hasta} | Los totales NO son la suma de la fila ni de "
            f"la columna: se recalculan, porque el mismo cliente compra varios "
            f"calibres y varias marcas",
        ).font = Font(italic=True, size=9, color="546E7A")

        columnas: list[str] = []
        for etiqueta, marcas in bloques:
            columnas += list(marcas) + [f"TOTAL {etiqueta}"]
        columnas.append("TOTAL AGUAS")

        banda, header, primera = 4, 5, 6
        borde = _thin_border()

        # Banda de categorias sobre sus marcas
        col = 2
        for etiqueta, marcas in bloques:
            ancho = len(marcas) + 1
            ws.merge_cells(start_row=banda, start_column=col, end_row=banda, end_column=col + ancho - 1)
            c = ws.cell(banda, col, etiqueta)
            c.fill = PatternFill("solid", fgColor=SUC_FILL)
            c.font = Font(bold=True, size=10)
            c.alignment = Alignment(horizontal="center")
            for j in range(col, col + ancho):
                ws.cell(banda, j).border = borde
            col += ancho
        ws.cell(banda, col, "").border = borde

        for j, nombre in enumerate(["Calibre"] + columnas, start=1):
            c = ws.cell(header, j, nombre)
            c.fill = PatternFill("solid", fgColor=HEADER_FILL)
            c.font = Font(bold=True, color=HEADER_FONT)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = borde

        r = primera
        for _, fila in df.iterrows():
            es_total = fila["calibre"] == "TOTAL"
            for j, nombre in enumerate(["calibre"] + columnas, start=1):
                clave = "calibre" if j == 1 else nombre
                c = ws.cell(r, j, fila.get(clave))
                if j > 1:
                    c.number_format = "#,##0"
                c.border = borde
                if es_total:
                    c.fill = PatternFill("solid", fgColor=TOTAL_GRAL_FILL)
                    c.font = Font(bold=True)
                elif nombre.startswith("TOTAL"):
                    c.fill = PatternFill("solid", fgColor=ACCENT_FILL)
                    c.font = Font(bold=True)
            r += 1

        ws.column_dimensions["A"].width = 12
        for j in range(2, len(columnas) + 2):
            ws.column_dimensions[get_column_letter(j)].width = 15
        ws.freeze_panes = f"B{primera}"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
