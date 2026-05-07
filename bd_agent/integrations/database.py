"""bd_agent/integrations/database.py — PgDatabaseGateway (T-070).

Concrete implementation of DatabaseGateway using a dedicated SQLAlchemy engine
that reads from AGENT_DB_URL (separate from the main DB_URL used by reports).

Design rules:
  - Only reads AGENT_DB_URL from env (RF-061). Raises EnvironmentError if absent.
  - Uses SQLAlchemy text() with bound params; fetchmany(max_rows) enforces row cap.
  - Curated query names (e.g. "get_ventas_cliente") are resolved to their full
    parameterised SQL via _CURATED_QUERIES dict before execution.
  - Raw SQL strings (not in _CURATED_QUERIES) are passed through directly.
  - Returns list[dict] — row proxy objects are mapped eagerly so callers never
    receive SQLAlchemy internal objects.
  - Zero imports from src.* (RF-070).

Statement timeout is applied via SQLAlchemy execution options (30 s).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Curated parameterised queries (T-070 spec — named-query convention)
# ---------------------------------------------------------------------------

_CURATED_QUERIES: dict[str, str] = {
    "get_ventas_cliente": """
        SELECT fv.fecha_comprobante, fv.cantidades_total, fv.subtotal_neto,
               da.descripcion AS articulo
        FROM gold.fact_ventas fv
        LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
        WHERE fv.id_cliente = :id_cliente
          AND TO_CHAR(fv.fecha_comprobante, 'YYYY-MM') = :periodo
        ORDER BY fv.fecha_comprobante
        LIMIT :max_rows
    """,
    "get_clientes_sucursal": """
        SELECT id_cliente, fantasia, anulado
        FROM gold.dim_cliente
        WHERE id_sucursal = :id_sucursal
        ORDER BY id_cliente
        LIMIT :max_rows
    """,
    "get_articulos_generico": """
        SELECT id_articulo, des_articulo, marca
        FROM gold.dim_articulo
        WHERE generico = :generico
        ORDER BY des_articulo
        LIMIT :max_rows
    """,
    "get_cobertura_periodo": """
        SELECT periodo, ds_sucursal, generico, clientes_compradores, volumen_total
        FROM gold.cob_preventista_generico
        WHERE periodo = :periodo
          AND (CAST(:sucursales AS TEXT) IS NULL
               OR ds_sucursal = ANY(STRING_TO_ARRAY(:sucursales, ',')))
        ORDER BY ds_sucursal, generico
        LIMIT :max_rows
    """,
    "get_ventas_articulo": """
        SELECT fv.fecha_comprobante, ds.descripcion AS sucursal,
               fv.cantidades_total, fv.subtotal_neto
        FROM gold.fact_ventas fv
        LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
        WHERE fv.id_articulo = :id_articulo
          AND fv.fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
        ORDER BY fv.fecha_comprobante
        LIMIT :max_rows
    """,
}

# ---------------------------------------------------------------------------
# Gateway implementation
# ---------------------------------------------------------------------------


class PgDatabaseGateway:
    """Postgres-backed DatabaseGateway using a dedicated read-only connection.

    Reads ``AGENT_DB_URL`` from the environment at construction time.
    Raises ``EnvironmentError`` if the variable is absent (RF-061).

    Args:
        schema_doc_path: Path to ``CONTEXT_DATABASE.md``.  Content is loaded
            lazily on first ``get_schema_doc()`` call.
        engine: Optional pre-built SQLAlchemy engine (used in tests to inject
            a mock engine without a real DB connection).
    """

    def __init__(
        self,
        schema_doc_path: Path,
        engine: Engine | None = None,
    ) -> None:
        dsn = os.environ.get("AGENT_DB_URL")
        if not dsn:
            raise EnvironmentError(
                "AGENT_DB_URL is not set. "
                "Add it to your .env file before starting the BD Agent."
            )
        self._engine: Engine = engine if engine is not None else create_engine(
            dsn,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=2,
        )
        self._schema_doc_path = Path(schema_doc_path)
        self._schema_doc_cache: str | None = None

    # ------------------------------------------------------------------
    # DatabaseGateway Protocol
    # ------------------------------------------------------------------

    def execute_select(
        self,
        query: str,
        params: dict[str, Any],
        max_rows: int,
    ) -> list[dict]:
        """Execute a SELECT query and return at most *max_rows* rows as dicts.

        If *query* is one of the named curated queries in ``_CURATED_QUERIES``,
        the corresponding parameterised SQL is executed with *params* merged with
        ``{"max_rows": max_rows}``.

        Otherwise *query* is treated as raw SQL and executed directly with *params*.

        Args:
            query: Either a curated query name or raw SQL text.
            params: Bound parameters for the query.
            max_rows: Maximum number of rows to return.

        Returns:
            list[dict] — one dict per row, with column names as keys.
        """
        if query in _CURATED_QUERIES:
            sql_text = _CURATED_QUERIES[query]
            bound_params = {**params, "max_rows": max_rows}
        else:
            sql_text = query
            bound_params = dict(params)

        stmt = text(sql_text)
        with self._engine.connect() as conn:
            result = conn.execute(stmt, bound_params)
            rows = result.fetchmany(max_rows)

        return [dict(row._mapping) for row in rows]

    def get_schema_doc(self) -> str:
        """Return the content of CONTEXT_DATABASE.md.

        Cached after first read. Call ``reload_schema_doc()`` to force a re-read.

        Raises:
            FileNotFoundError: if the schema doc file does not exist.
        """
        if self._schema_doc_cache is None:
            if not self._schema_doc_path.exists():
                raise FileNotFoundError(
                    f"Schema doc not found at {self._schema_doc_path}. "
                    "Create CONTEXT_DATABASE.md before starting the BD Agent."
                )
            self._schema_doc_cache = self._schema_doc_path.read_text(encoding="utf-8")
        return self._schema_doc_cache

    def reload_schema_doc(self) -> None:
        """Force re-read of CONTEXT_DATABASE.md on next get_schema_doc() call."""
        self._schema_doc_cache = None
        logger.info("schema_doc_cache_invalidated")
