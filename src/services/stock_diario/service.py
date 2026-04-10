"""StockDiarioService — generates daily stock snapshot Excel files."""

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pandas as pd

from src.core.data_loader import DataLoader
from src.services.base_service import BaseService
from src.services.stock_diario.processor import build_excel

logger = logging.getLogger(__name__)


@dataclass
class StockDiarioConfig:
    """Configuration for stock-diario report."""

    fecha_desde: str
    fecha_hasta: str
    genericos: list[str] | None = None
    nombre_archivo: str | None = None
    supervisores: dict[str, list[str]] | None = None


@dataclass
class StockDiarioResult:
    """Result of stock-diario report generation."""

    archivos_generados: list = field(default_factory=list)  # list[Path]
    fechas_sin_datos: list = field(default_factory=list)  # list[str]


class StockDiarioService(BaseService):
    """Generates daily stock snapshot Excel files, one per date."""

    def generar_reporte(self, config: StockDiarioConfig) -> StockDiarioResult:
        """Generate one Excel file per date in [fecha_desde, fecha_hasta].

        If supervisores is set, generates one file per supervisor per date,
        filtering by the supervisor's sucursales.
        """
        desde = pd.to_datetime(config.fecha_desde)
        hasta = pd.to_datetime(config.fecha_hasta)
        result = StockDiarioResult()

        fecha_actual = desde
        while fecha_actual <= hasta:
            fecha_str = fecha_actual.strftime("%Y-%m-%d")
            df = self.data_loader.get_stock_diario(fecha_str, config.genericos)

            if df.empty:
                logger.warning("Sin datos de stock para %s, omitiendo", fecha_str)
                result.fechas_sin_datos.append(fecha_str)
            elif config.supervisores:
                self._generar_por_supervisor(fecha_str, df, config.supervisores, result)
            else:
                ruta = build_excel(fecha_str, df)
                result.archivos_generados.append(ruta)
                logger.info("Stock generado: %s (%d registros)", ruta.name, len(df))

            fecha_actual += timedelta(days=1)

        return result

    def _generar_por_supervisor(
        self,
        fecha_str: str,
        df: pd.DataFrame,
        supervisores: dict[str, list[str]],
        result: StockDiarioResult,
    ) -> None:
        """Generate one file per supervisor, filtering df by sucursales."""
        for supervisor, sucursales in supervisores.items():
            df_sup = df[df["sucursal"].isin(sucursales)]
            if df_sup.empty:
                logger.warning(
                    "Sin datos de stock para %s - %s, omitiendo", supervisor, fecha_str
                )
                continue
            ruta = build_excel(fecha_str, df_sup, nombre_prefijo=f"Stock {supervisor}")
            result.archivos_generados.append(ruta)
            logger.info(
                "Stock %s generado: %s (%d registros)",
                supervisor, ruta.name, len(df_sup),
            )
