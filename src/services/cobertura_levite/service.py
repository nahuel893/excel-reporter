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
    procesar_clientes_compradores,
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
        self, fecha_desde: str, fecha_hasta: str, marcas: list[str] | None = None
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
        df = self.data_loader.execute_query(
            query,
            {"desde": fecha_desde, "hasta": fecha_hasta, "marcas": list(marcas or ["LEVITE"])},
        )
        if not df.empty:
            df["calibre"] = df["des_articulo"].apply(extraer_calibre)
        else:
            df["calibre"] = pd.Series(dtype=str)
        return df

    def _fetch_padron(self) -> pd.DataFrame:
        """Obtiene el padron de clientes activos (no anulados) por sucursal."""
        query = """
        SELECT 
            dc.id_sucursal,
            ds.descripcion AS sucursal,
            COUNT(DISTINCT dc.id_cliente) AS padron
        FROM gold.dim_cliente dc
        JOIN gold.dim_sucursal ds ON dc.id_sucursal = ds.id_sucursal
        WHERE dc.anulado = false
        GROUP BY dc.id_sucursal, ds.descripcion
        ORDER BY ds.descripcion
        """
        return self.data_loader.execute_query(query)

    def generar_reporte(self, config: CoberturaLeviteConfig) -> CoberturaLeviteResult:
        """Ejecuta la extraccion, transformacion y generacion del workbook Excel."""
        logger.info("Generando reporte Cobertura Levite por Calibre (%s a %s)...", config.fecha_desde, config.fecha_hasta)
        
        # Una sola consulta con TODO el universo; cada hoja filtra lo suyo.
        marcas_universo = [m for _, ms in CATEGORIAS for m in ms]
        df_todo = self._fetch_ventas(config.fecha_desde, config.fecha_hasta, marcas_universo)
        df_ventas = df_todo[df_todo["marca"] == "LEVITE"].copy()
        df_padron = self._fetch_padron()
        
        calibres_presentes = ordenar_calibres(list(df_ventas["calibre"].unique())) if not df_ventas.empty else ["500cc", "1500cc", "2250cc"]
        calibres_activos = [c for c in calibres_presentes if c != "OTRO"]
        
        df_matriz, df_resumen_cal = procesar_cobertura_sucursal_calibre(df_ventas, df_padron, calibres_activos)
        df_clientes = procesar_clientes_compradores(df_ventas, calibres_activos)
        
        out_dir = service_output_dir(self.SERVICE_SLUG, config.fecha_hasta, granularity="month")
        out_dir.mkdir(parents=True, exist_ok=True)
        
        nombre = config.nombre_archivo or f"Cobertura Levite por Calibre - {config.fecha_hasta}"
        ruta_archivo = out_dir / f"{nombre}.xlsx"
        
        wb = Workbook()
        ws_cob = wb.active
        ws_cob.title = "Cobertura por Calibre"
        ws_cal_marca = wb.create_sheet(title="Calibre x Marca")
        ws_cli = wb.create_sheet(title="Clientes Compradores")
        
        self._build_hoja_cobertura(ws_cob, config, calibres_activos, df_matriz, df_resumen_cal)
        df_cal_marca, bloques = matriz_calibre_marca(
            df_todo[df_todo["calibre"] != "OTRO"], CATEGORIAS, config.umbral
        )
        if not df_cal_marca.empty:
            self._build_hoja_calibre_marca(ws_cal_marca, config, df_cal_marca, bloques)
        self._build_hoja_clientes(ws_cli, config, calibres_activos, df_clientes)
        
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

    def _build_hoja_cobertura(
        self,
        ws: Worksheet,
        config: CoberturaLeviteConfig,
        calibres: list[str],
        df_matriz: pd.DataFrame,
        df_resumen_cal: pd.DataFrame,
    ) -> None:
        """Construye la hoja de Cobertura por Calibre."""
        border = _thin_border()
        
        # Titulo y Subtitulo
        ws["A1"] = "COBERTURA LEVITÉ POR CALIBRE"
        ws["A1"].font = Font(bold=True, size=15, color="1F4E78")
        ws["A2"] = (
            f"Período: {config.fecha_desde} al {config.fecha_hasta}  |  "
            f"Fuerza de Ventas: Preventa (FV=1)  |  "
            f"Criterio: Compra neta > {config.umbral:g} bultos  |  "
            f"Categorización automática por descripción de artículo"
        )
        ws["A2"].font = Font(italic=True, size=9, color="595959")
        
        # --- TABLA 1: MATRIZ DE COBERTURA POR SUCURSAL Y CALIBRE ---
        r = 4
        ws.cell(r, 1, "1. Cobertura por Sucursal y Calibre").font = Font(bold=True, size=12, color="1F4E78")
        r += 1
        
        # Headers Tabla 1
        headers_t1 = ["Sucursal", "Padrón"]
        for cal in calibres:
            headers_t1.extend([f"Cob {cal}", f"% s/ Pad {cal}"])
        headers_t1.extend(["TOTAL LEVITÉ", "% Cob Total", "Vol Total (Bultos)"])
        
        fila_h1 = r
        for j, h in enumerate(headers_t1, 1):
            c = ws.cell(r, j, h)
            c.fill = PatternFill("solid", start_color=HEADER_FILL, end_color=HEADER_FILL)
            c.font = Font(bold=True, color=HEADER_FONT, size=10)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = border
        ws.row_dimensions[r].height = 28
        r += 1
        
        for _, fila in df_matriz.iterrows():
            es_tg = bool(fila["es_total_general"])
            valores = [fila["sucursal"], int(fila["padron"])]
            for cal in calibres:
                valores.extend([int(fila[f"cob_{cal}"]), float(fila[f"pct_{cal}"])])
            valores.extend([int(fila["cob_total"]), float(fila["pct_cob_total"]), float(fila["vol_total"])])
            
            for j, v in enumerate(valores, 1):
                c = ws.cell(r, j, v)
                c.border = border
                if j == 1:
                    c.alignment = Alignment(horizontal="left")
                else:
                    c.alignment = Alignment(horizontal="right")
                    
                # Formatos numericos
                if isinstance(v, float):
                    if headers_t1[j - 1].startswith("%"):
                        c.number_format = "0.0%"
                    else:
                        c.number_format = "#,##0.00"
                elif isinstance(v, int):
                    c.number_format = "#,##0"
                    
                if es_tg:
                    c.font = Font(bold=True)
                    c.fill = PatternFill("solid", start_color=TOTAL_GRAL_FILL, end_color=TOTAL_GRAL_FILL)
                elif headers_t1[j - 1] in ("TOTAL LEVITÉ", "% Cob Total"):
                    c.fill = PatternFill("solid", start_color=TOTAL_SUC_FILL, end_color=TOTAL_SUC_FILL)
                    c.font = Font(bold=True)
                    
            r += 1
            
        # --- TABLA 2: RESUMEN CONSOLIDADO POR CALIBRE ---
        r += 2
        ws.cell(r, 1, "2. Resumen Consolidado por Calibre (Total Empresa)").font = Font(bold=True, size=12, color="1F4E78")
        r += 1
        
        headers_t2 = [
            "Calibre",
            "SKUs Activos",
            "Clientes Compradores",
            "% Penetración Levité",
            "% Cobertura s/ Padrón",
            "Volumen (Bultos)",
            "% Mix Volumen",
            "Drop Size (Bultos/Cli)",
        ]
        
        for j, h in enumerate(headers_t2, 1):
            c = ws.cell(r, j, h)
            c.fill = PatternFill("solid", start_color=HEADER_FILL, end_color=HEADER_FILL)
            c.font = Font(bold=True, color=HEADER_FONT, size=10)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = border
        ws.row_dimensions[r].height = 28
        r += 1
        
        for _, fila in df_resumen_cal.iterrows():
            es_tot = fila["calibre"] == "TOTAL LEVITÉ"
            valores = [
                fila["calibre"],
                int(fila["articulos"]),
                int(fila["cobertura"]),
                float(fila["pct_penetracion_levite"]),
                float(fila["pct_cobertura_padron"]),
                float(fila["volumen_bultos"]),
                float(fila["pct_mix_volumen"]),
                float(fila["drop_size"]),
            ]
            
            for j, v in enumerate(valores, 1):
                c = ws.cell(r, j, v)
                c.border = border
                if j == 1:
                    c.alignment = Alignment(horizontal="left")
                else:
                    c.alignment = Alignment(horizontal="right")
                    
                if j in (4, 5, 7):
                    c.number_format = "0.0%"
                elif j in (6, 8):
                    c.number_format = "#,##0.00"
                elif isinstance(v, int):
                    c.number_format = "#,##0"
                    
                if es_tot:
                    c.font = Font(bold=True)
                    c.fill = PatternFill("solid", start_color=TOTAL_GRAL_FILL, end_color=TOTAL_GRAL_FILL)
            r += 1
            
        # Ajustar anchos
        ws.column_dimensions["A"].width = 30
        for j in range(2, len(headers_t1) + 1):
            ws.column_dimensions[get_column_letter(j)].width = 16

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

    def _build_hoja_clientes(
        self,
        ws: Worksheet,
        config: CoberturaLeviteConfig,
        calibres: list[str],
        df_clientes: pd.DataFrame,
    ) -> None:
        """Construye la hoja detallada de Clientes Compradores."""
        border = _thin_border()
        
        ws["A1"] = "CLIENTES COMPRADORES — LEVITÉ POR CALIBRE"
        ws["A1"].font = Font(bold=True, size=15, color="1F4E78")
        ws["A2"] = (
            f"Período: {config.fecha_desde} al {config.fecha_hasta}  |  "
            f"Clientes con compra neta positiva en el período  |  "
            f"Volúmenes expresados en Bultos"
        )
        ws["A2"].font = Font(italic=True, size=9, color="595959")
        
        headers = ["ID Suc", "Sucursal", "ID Cliente", "Cliente / Razón Social", "Ruta", "Preventista"]
        headers.extend(calibres)
        headers.extend(["Total Bultos", "Cant Calibres"])
        
        r = 4
        fila_header = r
        for j, h in enumerate(headers, 1):
            c = ws.cell(r, j, h)
            c.fill = PatternFill("solid", start_color=HEADER_FILL, end_color=HEADER_FILL)
            c.font = Font(bold=True, color=HEADER_FONT, size=10)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = border
        ws.row_dimensions[r].height = 26
        r += 1
        
        col_total_idx = len(headers) - 1
        col_cant_idx = len(headers)
        
        for _, fila in df_clientes.iterrows():
            valores = [
                int(fila["id_sucursal"]),
                str(fila["sucursal"]),
                int(fila["id_cliente"]),
                str(fila["cliente"]),
                int(fila["id_ruta"]),
                str(fila["vendedor"]),
            ]
            for cal in calibres:
                valores.append(float(fila[cal]))
            valores.extend([float(fila["total_bultos"]), int(fila["calibres_comprados"])])
            
            for j, v in enumerate(valores, 1):
                c = ws.cell(r, j, v)
                c.border = border
                
                # Alineacion
                if j in (1, 3, 5, col_cant_idx):
                    c.alignment = Alignment(horizontal="center")
                elif j in (2, 4, 6):
                    c.alignment = Alignment(horizontal="left")
                else:
                    c.alignment = Alignment(horizontal="right")
                    
                # Formatos
                if j in (1, 3, 5, col_cant_idx):
                    c.number_format = "#,##0"
                elif isinstance(v, (int, float)) and j >= 7:
                    c.number_format = "#,##0.00"
                    
                # Resaltar total
                if j == col_total_idx:
                    c.fill = PatternFill("solid", start_color=TOTAL_SUC_FILL, end_color=TOTAL_SUC_FILL)
                    c.font = Font(bold=True)
            r += 1
            
        # Anchos de columna
        anchos = {
            1: 10,   # ID Suc
            2: 24,   # Sucursal
            3: 13,   # ID Cliente
            4: 40,   # Cliente
            5: 10,   # Ruta
            6: 24,   # Preventista
        }
        for j in range(1, len(headers) + 1):
            w = anchos.get(j, 15)
            ws.column_dimensions[get_column_letter(j)].width = w
            
        # Filtro y congelar paneles
        ws.freeze_panes = ws.cell(row=fila_header + 1, column=4).coordinate
        ws.auto_filter.ref = f"A{fila_header}:{get_column_letter(len(headers))}{r - 1}"
