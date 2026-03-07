"""
MisionPosibleService - Servicio para generacion de reportes de cobertura.

Genera un reporte Excel con una hoja por marca, mostrando tablas de cobertura
por sucursal y por vendedor con objetivos, faltantes y porcentajes.
"""
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from src.core.data_loader import DataLoader
from src.core.excel_writer import ExcelWriter, SheetStyle, ColumnFormat
from src.core.zonas import aplicar_zonas_virtuales, expandir_sucursales
from src.services.base_service import BaseService
from src.services.mision_posible.processor import (
    procesar_cobertura_sucursal,
    procesar_cobertura_vendedor,
    concatenar_tablas,
)


@dataclass
class MisionPosibleConfig:
    """Configuracion para el reporte Mision Posible."""
    periodo: str                                # "YYYY-MM-DD", primer dia del mes
    marcas: list[str]                           # ["Imperial", "Levite", "Villa del Sur"]
    objetivos: dict[str, int] = field(default_factory=dict)
    porcentajes_sucursal: dict[str, float] = field(default_factory=dict)
    nombre_archivo: str | None = None
    supervisores: dict[str, list[str]] | None = None


@dataclass
class MisionPosibleResult:
    """Resultado de la generacion de un reporte Mision Posible."""
    ruta_archivos: list[Path]
    marcas_incluidas: list[str]
    hojas: list[str]
    supervisor: str | None = None


def _normalizar_periodo(periodo: str) -> str:
    """Normaliza periodo al primer dia del mes. Imprime warning si difiere."""
    d = pd.to_datetime(periodo)
    normalizado = d.replace(day=1).strftime("%Y-%m-%d")
    if normalizado != periodo:
        print(f"⚠ Periodo normalizado de {periodo} a {normalizado}")
    return normalizado


def _nombre_reporte(periodo: str, supervisor: str | None = None) -> str:
    """Genera nombre de archivo: 'Mision Posible [supervisor] MM-YYYY'."""
    d = pd.to_datetime(periodo)
    mm_yyyy = d.strftime("%m-%Y")
    if supervisor:
        return f"Mision Posible {supervisor} {mm_yyyy}"
    return f"Mision Posible {mm_yyyy}"


def _crear_estilo(summary_rows: dict | None = None) -> SheetStyle:
    """Crea SheetStyle para las hojas del reporte."""
    return SheetStyle(
        numeric_format="#,##0",
        column_formats={
            "Sucursal":  ColumnFormat(width=25),
            "Cobertura": ColumnFormat(number_format="#,##0", width=12),
            "Objetivo":  ColumnFormat(number_format="#,##0", width=12),
            "Faltante":  ColumnFormat(number_format="#,##0", width=12),
            "%":         ColumnFormat(number_format="#,##0.0", width=10),
        },
        as_table=False,
        summary_rows=summary_rows or {},
    )


class MisionPosibleService(BaseService):
    """Servicio para generar reportes de cobertura Mision Posible."""

    def generar_reporte(self, config: MisionPosibleConfig) -> MisionPosibleResult:
        """Genera un unico archivo con una hoja por marca."""
        if not config.marcas:
            raise ValueError("La lista de marcas no puede estar vacia.")

        periodo = _normalizar_periodo(config.periodo)
        df_cob, ultima_fecha = self._fetch_data(periodo)

        nombre = config.nombre_archivo or _nombre_reporte(periodo)
        summary_rows = {}
        if ultima_fecha:
            summary_rows["Ult. Actualizacion"] = ultima_fecha.strftime("%d/%m/%Y")

        writer = ExcelWriter(nombre)
        estilo = _crear_estilo(summary_rows)

        for marca in config.marcas:
            objetivo_total = config.objetivos.get(marca)
            df_suc = procesar_cobertura_sucursal(
                df_cob, marca, objetivo_total, config.porcentajes_sucursal
            )
            df_vend = procesar_cobertura_vendedor(
                df_cob, marca, objetivo_total, config.porcentajes_sucursal
            )
            df_hoja = concatenar_tablas(df_suc, df_vend)
            sheet_name = marca[:31]
            writer.add_sheet(df_hoja, sheet_name=sheet_name, style=estilo)

        ruta = writer.save()
        return MisionPosibleResult(
            ruta_archivos=[ruta],
            marcas_incluidas=list(config.marcas),
            hojas=[m[:31] for m in config.marcas],
        )

    def generar_reporte_supervisores(
        self,
        config: MisionPosibleConfig,
        supervisores: dict[str, list[str]],
    ) -> list[MisionPosibleResult]:
        """Genera un archivo por supervisor con una sola consulta a BD."""
        if not config.marcas:
            raise ValueError("La lista de marcas no puede estar vacia.")

        periodo = _normalizar_periodo(config.periodo)
        df_cob, ultima_fecha = self._fetch_data(periodo)

        summary_rows = {}
        if ultima_fecha:
            summary_rows["Ult. Actualizacion"] = ultima_fecha.strftime("%d/%m/%Y")

        results = []
        for supervisor, sucursales in supervisores.items():
            sucursales_exp = expandir_sucursales(sucursales)
            df_cob_sup = df_cob[df_cob["sucursal"].isin(sucursales_exp)] if not df_cob.empty else df_cob

            nombre = config.nombre_archivo or _nombre_reporte(periodo, supervisor)
            writer = ExcelWriter(nombre)
            estilo = _crear_estilo(summary_rows)

            for marca in config.marcas:
                objetivo_total = config.objetivos.get(marca)
                df_suc = procesar_cobertura_sucursal(
                    df_cob_sup, marca, objetivo_total, config.porcentajes_sucursal
                )
                df_vend = procesar_cobertura_vendedor(
                    df_cob_sup, marca, objetivo_total, config.porcentajes_sucursal
                )
                df_hoja = concatenar_tablas(df_suc, df_vend)
                sheet_name = marca[:31]
                writer.add_sheet(df_hoja, sheet_name=sheet_name, style=estilo)

            ruta = writer.save()
            results.append(MisionPosibleResult(
                ruta_archivos=[ruta],
                marcas_incluidas=list(config.marcas),
                hojas=[m[:31] for m in config.marcas],
                supervisor=supervisor,
            ))

        return results

    def _fetch_data(self, periodo: str) -> tuple[pd.DataFrame, date | None]:
        """Fetches cobertura data and ultima fecha venta.

        Returns:
            Tuple of (df_cob post zonas virtuales, ultima_fecha_venta).
        """
        df_cob = pd.DataFrame()
        try:
            df_cob_raw = self.data_loader.get_cobertura_preventista_marca(
                periodos=[periodo]
            )
            if not df_cob_raw.empty:
                df_cob = aplicar_zonas_virtuales(df_cob_raw)
        except Exception:
            pass

        ultima_fecha = None
        try:
            ultima_fecha = self.data_loader.get_ultima_fecha_venta()
        except Exception:
            pass

        return df_cob, ultima_fecha
