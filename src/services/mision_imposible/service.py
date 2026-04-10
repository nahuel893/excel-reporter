"""
MisionImposibleService - Genera Excel con datos de cobertura para formulas manuales.

Crea un archivo Excel con hojas de datos crudos (cobertura por preventista y sucursal).
El usuario agrega formulas y vistas manualmente sobre estos datos.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config.settings import ZONAS_VIRTUALES
from src.core.data_loader import DataLoader
from src.core.excel_writer import ExcelWriter, SheetStyle, ColumnFormat
from src.core.zonas import aplicar_zonas_virtuales
from src.services.base_service import BaseService

logger = logging.getLogger(__name__)


# Sheet names
SHEET_COB_PREV_GENERICO = "Cob Preventista Generico"
SHEET_COB_PREV_MARCA = "Cob Preventista Marca"
SHEET_COB_SUC_GENERICO = "Cob Sucursal Generico"
SHEET_COB_SUC_MARCA = "Cob Sucursal Marca"

# Column display names
_COB_PREV_GEN_COLUMNS = {
    "periodo": "Periodo",
    "sucursal": "Sucursal",
    "vendedor": "Vendedor",
    "generico": "Generico",
    "clientes_compradores": "Clientes Compradores",
    "volumen_total": "Volumen Total",
}

_COB_PREV_MARCA_COLUMNS = {
    "periodo": "Periodo",
    "sucursal": "Sucursal",
    "vendedor": "Vendedor",
    "marca": "Marca",
    "clientes_compradores": "Clientes Compradores",
    "volumen_total": "Volumen Total",
}

_COB_SUC_GEN_COLUMNS = {
    "periodo": "Periodo",
    "sucursal": "Sucursal",
    "generico": "Generico",
    "clientes_compradores": "Clientes Compradores",
    "volumen_total": "Volumen Total",
}

_COB_SUC_MARCA_COLUMNS = {
    "periodo": "Periodo",
    "sucursal": "Sucursal",
    "marca": "Marca",
    "clientes_compradores": "Clientes Compradores",
    "volumen_total": "Volumen Total",
}

_DATA_STYLE = SheetStyle(
    column_formats={
        "Clientes Compradores": ColumnFormat(number_format="#,##0", width=20),
        "Volumen Total": ColumnFormat(number_format="#,##0.00", width=15),
    },
    as_table=True,
    table_style="TableStyleMedium9",
)


def _fechas_a_periodos(fecha_desde: str, fecha_hasta: str) -> list[str]:
    """Convierte un rango de fechas en lista de primeros dias de mes cubiertos."""
    desde = pd.to_datetime(fecha_desde).replace(day=1)
    hasta = pd.to_datetime(fecha_hasta)
    periodos = pd.date_range(desde, hasta, freq="MS")
    return [p.strftime("%Y-%m-%d") for p in periodos]


def _preparar_hoja(
    df: pd.DataFrame | None,
    sort_cols: list[str],
    rename_map: dict[str, str],
) -> pd.DataFrame | None:
    """Ordena, selecciona y renombra columnas para una hoja de datos."""
    if df is None or df.empty:
        return None
    df = df.sort_values(sort_cols).reset_index(drop=True)
    df = df[list(rename_map.keys())]
    return df.rename(columns=rename_map)


def _aplicar_zonas_categoria(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica zonas virtuales y prepara columnas para pivot de categoria."""
    df = df.copy()
    for zona_nombre, zona_config in ZONAS_VIRTUALES.items():
        mask = (df["sucursal"] == zona_config["sucursal_real"]) & (
            df["id_ruta"].isin(zona_config["rutas"])
        )
        df.loc[mask, "sucursal"] = zona_nombre

    df = df.rename(columns={"sucursal": "zona_virtual"})
    df["articulo_desc"] = df["id_articulo"].astype(str) + " - " + df["des_articulo"]
    return df


def _pivotear_categoria(df: pd.DataFrame) -> pd.DataFrame:
    """Crea pivot table con marca/articulo en columnas y totales por marca."""
    idx_cols = [
        "zona_virtual",
        "id_ruta",
        "id_vendedor",
        "vendedor",
        "id_cliente",
        "cliente",
    ]
    df_pivot = df.pivot_table(
        index=idx_cols,
        columns=["marca", "articulo_desc"],
        values="cantidad",
        aggfunc="sum",
        fill_value=0,
    )

    # Subtotales por marca
    totales_marca = df_pivot.T.groupby(level="marca").sum().T
    totales_marca.columns = pd.MultiIndex.from_product(
        [totales_marca.columns, ["Total"]]
    )

    df_final = pd.concat([df_pivot, totales_marca], axis=1)
    df_final = df_final.sort_index(axis=1, level=0)

    # Aplanar MultiIndex a "Marca\nArticulo" para Excel
    df_final.columns = [f"{col[0]}\n{col[1]}" for col in df_final.columns]
    df_final = df_final.reset_index()

    return df_final


@dataclass
class MisionImposibleConfig:
    """Configuracion para el informe Mision Imposible."""

    fecha_desde: str
    fecha_hasta: str
    genericos: list[str] | None = None
    categorias: dict[str, list[int]] | None = None
    nombre_archivo: str | None = None


@dataclass
class MisionImposibleResult:
    """Resultado de la generacion del informe Mision Imposible."""

    ruta_archivo: Path
    registros_procesados: int
    sucursales: int
    genericos_incluidos: list[str]
    hojas: list[str]


class MisionImposibleService(BaseService):
    """Servicio para generar el informe Mision Imposible con datos de cobertura."""

    def generar_reporte(self, config: MisionImposibleConfig) -> MisionImposibleResult:
        """Genera el Excel con hojas de cobertura y categorias."""
        periodos = _fechas_a_periodos(config.fecha_desde, config.fecha_hasta)

        # Fetch all cobertura data
        df_prev_gen = self._fetch_preventista_generico(periodos)
        df_prev_marca = self._fetch_preventista_marca(periodos)
        df_suc_gen = self._fetch_sucursal_generico(periodos)
        df_suc_marca = self._fetch_sucursal_marca(periodos)

        # Filter by genericos if specified
        if config.genericos:
            df_prev_gen = self._filtrar_genericos(
                df_prev_gen, config.genericos, "generico"
            )
            df_suc_gen = self._filtrar_genericos(
                df_suc_gen, config.genericos, "generico"
            )

        # Build workbook
        nombre = config.nombre_archivo or f"Mision Imposible {config.fecha_hasta}"
        writer = ExcelWriter(nombre)
        hojas = []
        total = 0

        # Escribir hojas base de cobertura
        sheets = [
            (
                df_prev_gen,
                ["sucursal", "vendedor", "generico"],
                _COB_PREV_GEN_COLUMNS,
                SHEET_COB_PREV_GENERICO,
            ),
            (
                df_prev_marca,
                ["sucursal", "vendedor", "marca"],
                _COB_PREV_MARCA_COLUMNS,
                SHEET_COB_PREV_MARCA,
            ),
            (
                df_suc_gen,
                ["sucursal", "generico"],
                _COB_SUC_GEN_COLUMNS,
                SHEET_COB_SUC_GENERICO,
            ),
            (
                df_suc_marca,
                ["sucursal", "marca"],
                _COB_SUC_MARCA_COLUMNS,
                SHEET_COB_SUC_MARCA,
            ),
        ]

        for df, sort_cols, rename_map, sheet_name in sheets:
            df_sheet = _preparar_hoja(df, sort_cols, rename_map)
            if df_sheet is not None:
                writer.add_sheet(df_sheet, sheet_name=sheet_name, style=_DATA_STYLE)
                hojas.append(sheet_name)
                total += len(df_sheet)

        # Escribir hojas de categorias
        if config.categorias:
            for cat_name, art_ids in config.categorias.items():
                try:
                    df_cat = self._procesar_categoria(
                        config.fecha_desde, config.fecha_hasta, art_ids
                    )
                except Exception as exc:
                    logger.error("Error procesando categoria '%s': %s", cat_name, exc)
                    continue
                if df_cat is not None and not df_cat.empty:
                    sheet_name = f"Cat {cat_name}"[:31]
                    writer.add_sheet(
                        df_cat, sheet_name=sheet_name, style=SheetStyle(as_table=False)
                    )
                    hojas.append(sheet_name)
                    total += len(df_cat)

        ruta = writer.save()

        # Collect genericos from data
        genericos = []
        if df_prev_gen is not None and not df_prev_gen.empty:
            genericos = sorted(df_prev_gen["generico"].unique().tolist())

        # Count unique sucursales
        sucursales = 0
        if df_prev_gen is not None and not df_prev_gen.empty:
            sucursales = df_prev_gen["sucursal"].nunique()

        return MisionImposibleResult(
            ruta_archivo=ruta,
            registros_procesados=total,
            sucursales=sucursales,
            genericos_incluidos=genericos,
            hojas=hojas,
        )

    def _fetch_preventista_generico(self, periodos: list[str]) -> pd.DataFrame | None:
        """Fetch cobertura preventista generico with zonas virtuales."""
        try:
            df = self.data_loader.get_cobertura_preventista_generico(periodos=periodos)
            if not df.empty:
                return aplicar_zonas_virtuales(df)
        except Exception:
            pass
        return None

    def _fetch_preventista_marca(self, periodos: list[str]) -> pd.DataFrame | None:
        """Fetch cobertura preventista marca with zonas virtuales."""
        try:
            df = self.data_loader.get_cobertura_preventista_marca(periodos=periodos)
            if not df.empty:
                return aplicar_zonas_virtuales(df)
        except Exception:
            pass
        return None

    def _fetch_sucursal_generico(self, periodos: list[str]) -> pd.DataFrame | None:
        """Fetch cobertura sucursal generico."""
        try:
            df = self.data_loader.get_cobertura_sucursal_generico(periodos=periodos)
            if not df.empty:
                return df
        except Exception:
            pass
        return None

    def _fetch_sucursal_marca(self, periodos: list[str]) -> pd.DataFrame | None:
        """Fetch cobertura sucursal marca."""
        try:
            df = self.data_loader.get_cobertura_sucursal_marca(periodos=periodos)
            if not df.empty:
                return df
        except Exception:
            pass
        return None

    def _procesar_categoria(
        self, fecha_desde: str, fecha_hasta: str, art_ids: list[int]
    ) -> pd.DataFrame | None:
        """Obtiene y pivotea las ventas de una categoria."""
        df = self.data_loader.get_ventas_mision_imposible_categorias(
            fecha_desde, fecha_hasta, art_ids
        )
        if df.empty:
            return None

        df = _aplicar_zonas_categoria(df)
        return _pivotear_categoria(df)

    @staticmethod
    def _filtrar_genericos(
        df: pd.DataFrame | None, genericos: list[str], col: str
    ) -> pd.DataFrame | None:
        """Filter DataFrame by genericos list."""
        if df is None or df.empty:
            return df
        return df[df[col].isin(genericos)]
