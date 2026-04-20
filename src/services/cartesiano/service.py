"""
CartesianoService - Genera Excel con producto cartesiano de rutas × genéricos.

Output: una fila por cada combinación (ruta, preventista, genérico)
para una sucursal dada.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.core.data_loader import DataLoader
from src.core.excel_writer import ExcelWriter, SheetStyle, ColumnFormat
from src.services.base_service import BaseService

logger = logging.getLogger(__name__)


@dataclass
class CartesianoConfig:
    """Configuracion para el reporte cartesiano."""

    id_sucursal: int = 1
    genericos: list[str] | None = None
    nombre_archivo: str | None = None


@dataclass
class CartesianoResult:
    """Resultado de la generacion del reporte cartesiano."""

    ruta_archivo: Path
    registros_procesados: int
    rutas: int
    genericos: int


_STYLE = SheetStyle(
    column_formats={
        "Ruta": ColumnFormat(number_format="#,##0", width=8),
        "Preventista": ColumnFormat(width=25),
        "Generico": ColumnFormat(width=20),
    },
    as_table=True,
    table_style="TableStyleMedium9",
    table_name="Tbl_Cartesiano",
)


class CartesianoService(BaseService):
    """Genera producto cartesiano de rutas × genéricos."""

    SERVICE_SLUG = "cartesiano"
    GRANULARITY = "month"

    def generar_reporte(self, config: CartesianoConfig) -> CartesianoResult:
        """Genera el Excel con el producto cartesiano."""
        # Obtener rutas únicas con preventista
        df_rutas = self.data_loader.execute_query(
            """
            SELECT DISTINCT id_ruta_fv1 AS ruta, des_personal_fv1 AS preventista
            FROM gold.dim_cliente
            WHERE anulado = false
              AND id_sucursal = :id_sucursal
              AND id_ruta_fv1 IS NOT NULL
            ORDER BY id_ruta_fv1
            """,
            {"id_sucursal": config.id_sucursal},
        )

        # Obtener genéricos
        if config.genericos:
            df_genericos = pd.DataFrame({"generico": config.genericos})
        else:
            df_genericos = self.data_loader.execute_query(
                "SELECT DISTINCT generico FROM gold.dim_articulo WHERE generico IS NOT NULL ORDER BY generico"
            )

        # Producto cartesiano
        df_rutas["_key"] = 1
        df_genericos["_key"] = 1
        df_cartesiano = df_rutas.merge(df_genericos, on="_key").drop("_key", axis=1)

        # Renombrar columnas para el Excel
        df_cartesiano = df_cartesiano.rename(columns={
            "ruta": "Ruta",
            "preventista": "Preventista",
            "generico": "Generico",
        })

        # Escribir Excel
        nombre = config.nombre_archivo or "Cartesiano Rutas x Genericos"
        out = self._output_dir(None)
        out.mkdir(parents=True, exist_ok=True)
        writer = ExcelWriter(nombre, output_dir=out)
        writer.add_sheet(df_cartesiano, sheet_name="Cartesiano", style=_STYLE)
        ruta = writer.save()

        return CartesianoResult(
            ruta_archivo=ruta,
            registros_procesados=len(df_cartesiano),
            rutas=len(df_rutas),
            genericos=len(df_genericos),
        )
