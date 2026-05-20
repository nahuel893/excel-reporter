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
    sucursales: list[str] | None = None
    supervisor: str | None = None
    db_name: str | None = None  # Override DB name for multi-DB setups


@dataclass
class StockDiarioResult:
    """Result of stock-diario report generation."""

    archivos_generados: list = field(default_factory=list)  # list[Path]
    fechas_sin_datos: list = field(default_factory=list)  # list[str]


class StockDiarioService(BaseService):
    """Generates daily stock snapshot Excel files, one per date."""

    SERVICE_SLUG = "stock-diario"
    GRANULARITY = "day"

    def _create_data_loader(self, db_name: str | None = None) -> DataLoader:
        """Create a DataLoader with optional DB name override."""
        if db_name:
            return DataLoader(db_name=db_name)
        return DataLoader()

    def generar_reporte(self, config: StockDiarioConfig) -> StockDiarioResult:
        """Generate one Excel file per date in [fecha_desde, fecha_hasta].

        If sucursales is set, filters data to only those sucursales.
        If supervisor is set, names files as "Stock {supervisor} - DD-MM-YYYY".
        If config.db_name is set, uses that database instead of the default.
        """
        desde = pd.to_datetime(config.fecha_desde)
        hasta = pd.to_datetime(config.fecha_hasta)
        result = StockDiarioResult()

        # Create DataLoader with optional DB override
        data_loader = self._create_data_loader(config.db_name)

        nombre_prefijo = f"Stock {config.supervisor}" if config.supervisor else "Stock"

        fecha_actual = desde
        while fecha_actual <= hasta:
            fecha_str = fecha_actual.strftime("%Y-%m-%d")
            df = data_loader.get_stock_diario(fecha_str, config.genericos)

            # Filter by sucursales if specified
            if config.sucursales and not df.empty:
                df = df[df["sucursal"].isin(config.sucursales)]

            if df.empty:
                logger.warning("Sin datos de stock para %s, omitiendo", fecha_str)
                result.fechas_sin_datos.append(fecha_str)
            else:
                out_dir = self._output_dir(fecha_str)
                out_dir.mkdir(parents=True, exist_ok=True)
                ruta = build_excel(fecha_str, df, output_dir=out_dir, nombre_prefijo=nombre_prefijo)
                result.archivos_generados.append(ruta)
                logger.info("Stock generado: %s (%d registros)", ruta.name, len(df))

            fecha_actual += timedelta(days=1)

        return result
