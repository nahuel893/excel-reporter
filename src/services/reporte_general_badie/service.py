"""
ReporteGeneralBadieService — monthly CCU report with interactive month dropdown.

Generates an Excel workbook with:
- Reporte sheet: formula-driven pivot with DataValidation dropdown for month selection
- VentasCCU: raw monthly sales data (openpyxl Table)
- CoberturaCCU: raw client coverage data for the 4 CCU genericos (openpyxl Table)
- _Meses: hidden sheet with the list of YYYY-MM months for the dropdown
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.services.base_service import BaseService
from src.services.reporte_general_badie.processor import _generar_trimestres, build_workbook


@dataclass
class ReporteGeneralBadieConfig:
    """Configuration for the Reporte General Badie report."""

    fecha_desde: str  # "YYYY-MM-DD"
    fecha_hasta: str  # "YYYY-MM-DD"
    nombre_archivo: str | None = None


@dataclass
class ReporteGeneralBadieResult:
    """Result of generating the Reporte General Badie report."""

    ruta_archivo: Path
    ruta_archivo_extendido: Path
    registros_ventas: int
    registros_ventas_extendido: int
    registros_cobertura: int
    registros_cobertura_extendido: int
    sucursales: int
    trimestres_en_dropdown: int
    trimestres_en_dropdown_extendido: int


class ReporteGeneralBadieService(BaseService):
    """Service that generates the Reporte General Badie Excel workbook."""

    SERVICE_SLUG = "reporte-general-badie"
    GRANULARITY = "month"

    def generar_reporte(
        self, config: ReporteGeneralBadieConfig
    ) -> ReporteGeneralBadieResult:
        """
        Generate two workbooks: normal (since 2024-01) and extended (since 2022-01).

        Both files are written to the same output dir; the extended adds " EXTENDIDO"
        to the filename. Dropdowns and raw data span their respective ranges.

        Args:
            config: Report configuration with date range and optional filename.

        Returns:
            ReporteGeneralBadieResult with paths and per-file record counts.
        """
        sucursales_df = self.data_loader.get_sucursales()
        sucursales_all = sucursales_df["sucursal"].dropna().unique().tolist()

        out = self._output_dir(config.fecha_desde)
        out.mkdir(parents=True, exist_ok=True)
        nombre_base = config.nombre_archivo or "Reporte General Badie"

        # Normal: desde 2024-01-01 (covers YoY back to 2024 minimum)
        normal = self._generar_un_workbook(
            sucursales_all, config, "2024-01-01",
            ruta=out / f"{nombre_base}.xlsx",
        )

        # Extendido: desde 2022-01-01 (full historical view)
        extendido = self._generar_un_workbook(
            sucursales_all, config, "2022-01-01",
            ruta=out / f"{nombre_base} EXTENDIDO.xlsx",
        )

        return ReporteGeneralBadieResult(
            ruta_archivo=normal["ruta"],
            ruta_archivo_extendido=extendido["ruta"],
            registros_ventas=normal["registros_ventas"],
            registros_ventas_extendido=extendido["registros_ventas"],
            registros_cobertura=normal["registros_cobertura"],
            registros_cobertura_extendido=extendido["registros_cobertura"],
            sucursales=normal["sucursales"],
            trimestres_en_dropdown=normal["trimestres"],
            trimestres_en_dropdown_extendido=extendido["trimestres"],
        )

    def _generar_un_workbook(
        self,
        sucursales_all: list[str],
        config: ReporteGeneralBadieConfig,
        desde: str,
        ruta: Path,
    ) -> dict:
        """Build and save one workbook for the given start date."""
        df_ventas = self.data_loader.get_ventas_mensuales_ccu(desde, config.fecha_hasta)
        df_cob = self.data_loader.get_cobertura_clientes_ccu(desde, config.fecha_hasta)
        trimestres = _generar_trimestres(desde, config.fecha_hasta)
        sucursales = _ordenar_sucursales_por_total(
            sucursales_all, df_ventas, config.fecha_hasta
        )
        wb = build_workbook(sucursales, df_ventas, df_cob, trimestres)
        wb.save(ruta)
        return {
            "ruta": ruta,
            "registros_ventas": len(df_ventas),
            "registros_cobertura": len(df_cob),
            "sucursales": len(sucursales),
            "trimestres": len(trimestres),
        }


def _ordenar_sucursales_por_total(
    sucursales_all: list[str], df_ventas, fecha_hasta: str
) -> list[str]:
    """Sort sucursales by Total CCU (sum of bultos) of the quarter that
    contains `fecha_hasta`, descending. Sucursales not present in df_ventas
    for that quarter go last in alphabetical order.
    """
    anio = int(fecha_hasta[:4])
    mes = int(fecha_hasta[5:7])
    trimestre = (mes - 1) // 3 + 1

    if df_ventas.empty:
        return sorted(sucursales_all)

    mask = (df_ventas["anio"] == anio) & (df_ventas["trimestre"] == trimestre)
    totales = df_ventas.loc[mask].groupby("sucursal")["bultos"].sum()

    with_sales = sorted(totales.index.tolist(), key=lambda s: -totales[s])
    without_sales = sorted(set(sucursales_all) - set(with_sales))
    return with_sales + without_sales
