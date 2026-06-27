"""StockSuriaService — generates Stock SURIA Excel from matched article list + SURIA DB."""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text

from src.services.base_service import BaseService
from src.services.stock_suria.processor import build_excel

logger = logging.getLogger(__name__)

# Frozen match list lives alongside the configs
_CONFIG_JSON = Path(__file__).resolve().parents[3] / "configs" / "stock_suria_articulos.json"


def _normalize_sucursal(name: str | None) -> str:
    """Strip a leading 'SUCURSAL ' prefix from a deposit's sucursal name.

    The SURIA ``gold.dim_deposito.des_sucursal`` values are stored as
    ``"SUCURSAL ABRA PAMPA"``, but the report columns (``processor.SUCURSALES``)
    use the short form ``"ABRA PAMPA"``. Without this normalization every stock
    value falls through the lookup and the report renders all zeros.
    """
    if not name:
        return ""
    name = name.strip()
    if name.upper().startswith("SUCURSAL "):
        name = name[len("SUCURSAL "):].strip()
    return name


@dataclass
class StockSuriaConfig:
    """Configuration for stock-suria report."""

    fecha: str  # YYYY-MM-DD — used only for output dir; actual stock date = latest in DB
    nombre_archivo: str | None = None


@dataclass
class StockSuriaResult:
    """Result of stock-suria report generation."""

    ruta_archivo: Path
    fecha_stock: str
    articulos_con_stock: int


class StockSuriaService(BaseService):
    """Generates the Stock SURIA Excel report from the SURIA database."""

    SERVICE_SLUG = "stock-suria"
    GRANULARITY = "day"

    def _build_suria_engine(self):
        """Create a SQLAlchemy engine for the SURIA database."""
        host = os.environ.get("DB_HOST", "localhost")
        port = os.environ.get("DB_PORT", "5432")
        user = os.environ.get("DB_USER", "")
        password = os.environ.get("DB_PASSWORD", "")
        db_name = os.environ.get("DB_NAME_SURIA", "medallion_db_suria")
        url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
        return create_engine(url)

    def _load_config_data(self) -> dict:
        """Load the frozen article match list from configs/stock_suria_articulos.json."""
        with open(_CONFIG_JSON, encoding="utf-8") as fh:
            return json.load(fh)

    def generar_reporte(self, config: StockSuriaConfig) -> StockSuriaResult:
        """Generate the Stock SURIA Excel and return a result with path + metadata."""
        config_data = self._load_config_data()

        # Collect all article IDs to query
        matched_ids = [a["id_articulo"] for a in config_data["articulos"]]
        closest_ids = [s["closest_id"] for s in config_data["sin_match"]]
        all_ids = list(set(matched_ids + closest_ids))

        engine = self._build_suria_engine()
        with engine.connect() as conn:
            # 1. Latest stock date
            row = conn.execute(text("SELECT MAX(date_stock) FROM gold.fact_stock")).fetchone()
            fecha_stock = row[0].isoformat() if row and row[0] else config.fecha
            logger.info("Fecha stock mas reciente en SURIA: %s", fecha_stock)

            # 2. Stock aggregated by article and deposit/sucursal
            result = conn.execute(
                text(
                    """
                    SELECT f.id_articulo,
                           d.des_sucursal,
                           SUM(f.cant_bultos)         AS cant_bultos,
                           SUM(f.cantidad_total_htls) AS htls
                    FROM   gold.fact_stock f
                    JOIN   gold.dim_deposito d ON d.id_deposito = f.id_deposito
                    WHERE  f.date_stock = :date
                      AND  f.id_articulo = ANY(:ids)
                    GROUP BY f.id_articulo, d.des_sucursal
                    """
                ),
                {"date": fecha_stock, "ids": all_ids},
            )
            stock_rows = result.fetchall()

            # 3. Generico for matched articles (column is 'generico' in SURIA dim_articulo)
            result_gen = conn.execute(
                text(
                    """
                    SELECT id_articulo, generico
                    FROM   gold.dim_articulo
                    WHERE  id_articulo = ANY(:ids)
                    """
                ),
                {"ids": matched_ids},
            )
            generico_rows = result_gen.fetchall()

        # Build lookup: {id_articulo: {sucursal: {bultos, htls}}}
        stock_data: dict = {}
        for row in stock_rows:
            id_art = row[0]
            suc = _normalize_sucursal(row[1])
            bultos = row[2]
            htls = row[3]
            if id_art not in stock_data:
                stock_data[id_art] = {}
            stock_data[id_art][suc] = {"bultos": bultos, "htls": htls}

        generico_map: dict = {row[0]: row[1] for row in generico_rows}

        # Count articles with any stock > 0
        articulos_con_stock = sum(
            1 for id_art in matched_ids
            if any(
                (stock_data.get(id_art, {}).get(suc, {}) or {}).get("bultos", 0)
                for suc in stock_data.get(id_art, {})
            )
        )

        # Build output path and Excel
        out_dir = self._output_dir(config.fecha)
        out_path = build_excel(
            config_data=config_data,
            stock_data=stock_data,
            generico_map=generico_map,
            fecha_str=config.fecha,
            output_dir=out_dir,
        )

        return StockSuriaResult(
            ruta_archivo=out_path,
            fecha_stock=fecha_stock,
            articulos_con_stock=articulos_con_stock,
        )
