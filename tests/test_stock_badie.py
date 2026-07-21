"""Tests for DataLoader.get_venta_mes / get_ultima_fecha_stock (RF-01, RF-02).

Also locks the existing get_stock_diario() dim_deposito join as a
fan-out regression guard (Phase 1, Task 1.5 — no code change).

Strict TDD — Phase 1 of sdd/stock-badie (WORK UNIT 1 / PR1).
All DB access is mocked at the DataLoader.execute_query level; no real
database connection is made.
"""

from datetime import date, datetime

import pandas as pd
from unittest.mock import MagicMock

from src.core.data_loader import DataLoader


# ── RF-01: get_venta_mes ─────────────────────────────────────────────────────


class TestGetVentaMes:
    def test_get_venta_mes_query_shape(self):
        """Uses fact_ventas, joins dim_sucursal, groups by id_sucursal+id_articulo,
        sums cantidades_total/cantidad_total_htls, and does NOT join/filter by
        id_ruta or id_vendedor (composite-key rule does not apply here)."""
        loader = DataLoader(engine=MagicMock())
        captured_calls = []

        def fake_execute_query(query, params=None):
            captured_calls.append({"query": query, "params": params})
            return pd.DataFrame(
                columns=["id_sucursal", "sucursal", "id_articulo", "venta_bultos", "venta_htls"]
            )

        loader.execute_query = fake_execute_query

        loader.get_venta_mes(fecha_desde="2026-07-01", fecha_hasta="2026-08-01")

        assert len(captured_calls) == 1
        sql = captured_calls[0]["query"]
        params = captured_calls[0]["params"]

        assert "gold.fact_ventas" in sql
        assert "gold.dim_sucursal" in sql
        # LEFT JOIN (not INNER): a sale whose id_sucursal is missing from
        # dim_sucursal must NOT be silently dropped from the aggregate,
        # matching the file-wide fact_ventas -> dim_sucursal convention.
        assert "LEFT JOIN gold.dim_sucursal" in sql
        assert "fv.id_sucursal" in sql
        assert "GROUP BY" in sql
        assert "fv.id_articulo" in sql
        assert "SUM(fv.cantidades_total)" in sql
        assert "SUM(fv.cantidad_total_htls)" in sql

        # composite-key rule does NOT apply — fact_ventas already carries
        # id_sucursal directly, no id_ruta/id_vendedor join needed here.
        assert "id_ruta" not in sql
        assert "id_vendedor" not in sql

        assert params["fecha_desde"] == "2026-07-01"
        assert params["fecha_hasta"] == "2026-08-01"

    def test_get_venta_mes_month_boundary(self):
        """Date window is half-open: fecha_comprobante >= fecha_desde AND
        < fecha_hasta (exclusive upper bound) — never BETWEEN (inclusive)."""
        loader = DataLoader(engine=MagicMock())
        captured = {}

        def fake_execute_query(query, params=None):
            captured["query"] = query
            captured["params"] = params
            return pd.DataFrame(
                columns=["id_sucursal", "sucursal", "id_articulo", "venta_bultos", "venta_htls"]
            )

        loader.execute_query = fake_execute_query

        loader.get_venta_mes(fecha_desde="2026-07-01", fecha_hasta="2026-08-01")

        sql = captured["query"]
        assert "BETWEEN" not in sql
        assert "fecha_comprobante >= :fecha_desde" in sql
        assert "fecha_comprobante < :fecha_hasta" in sql

        # Behavioral proof: with the exact operators emitted above, prior-month
        # last day and next-month first day fall outside [fecha_desde, fecha_hasta).
        raw_rows = pd.DataFrame({
            "fecha_comprobante": ["2026-06-30", "2026-07-15", "2026-08-01"],
            "cantidades_total": [5, 10, 7],
        })
        desde, hasta = captured["params"]["fecha_desde"], captured["params"]["fecha_hasta"]
        mask = (raw_rows["fecha_comprobante"] >= desde) & (raw_rows["fecha_comprobante"] < hasta)
        kept = raw_rows.loc[mask]

        assert len(kept) == 1
        assert kept.iloc[0]["fecha_comprobante"] == "2026-07-15"
        assert "2026-06-30" not in kept["fecha_comprobante"].values
        assert "2026-08-01" not in kept["fecha_comprobante"].values

    def test_get_venta_mes_aggregates_sum_not_duplicate(self):
        """GROUP BY is exactly (id_sucursal, sucursal, id_articulo) — two sales
        rows for the same pair are summed by SQL, not duplicated/fragmented by
        an extra grouping column (e.g. fecha_comprobante)."""
        loader = DataLoader(engine=MagicMock())
        captured = {}

        def fake_execute_query(query, params=None):
            captured["query"] = query
            return pd.DataFrame(
                columns=["id_sucursal", "sucursal", "id_articulo", "venta_bultos", "venta_htls"]
            )

        loader.execute_query = fake_execute_query
        loader.get_venta_mes(fecha_desde="2026-07-01", fecha_hasta="2026-08-01")

        sql = captured["query"]
        # GROUP BY must key only on sucursal + articulo — no fecha_comprobante
        # in the GROUP BY, which would fragment sums per day instead of per month.
        group_by_line = next(line for line in sql.splitlines() if "GROUP BY" in line)
        assert "fv.id_sucursal" in group_by_line
        assert "fv.id_articulo" in group_by_line
        assert "fecha_comprobante" not in group_by_line


# ── RF-02: get_ultima_fecha_stock ────────────────────────────────────────────


class TestGetUltimaFechaStock:
    def test_get_ultima_fecha_stock_query_shape(self):
        """Emits MAX(date_stock) FROM gold.fact_stock."""
        loader = DataLoader(engine=MagicMock())
        captured = {}

        def fake_execute_query(query, params=None):
            captured["query"] = query
            captured["params"] = params
            return pd.DataFrame({"ultima_fecha": [date(2026, 7, 20)]})

        loader.execute_query = fake_execute_query
        loader.get_ultima_fecha_stock()

        assert "MAX(date_stock)" in captured["query"]
        assert "gold.fact_stock" in captured["query"]

    def test_get_ultima_fecha_stock_returns_latest_date(self):
        loader = DataLoader(engine=MagicMock())
        loader.execute_query = lambda q, p=None: pd.DataFrame({"ultima_fecha": [date(2026, 7, 20)]})

        result = loader.get_ultima_fecha_stock()

        assert result == date(2026, 7, 20)

    def test_get_ultima_fecha_stock_normalizes_timestamp_to_date(self):
        """pandas may return a Timestamp for a DATE column; normalize to plain date."""
        loader = DataLoader(engine=MagicMock())
        loader.execute_query = lambda q, p=None: pd.DataFrame({"ultima_fecha": [pd.Timestamp("2026-07-20")]})

        result = loader.get_ultima_fecha_stock()

        assert result == date(2026, 7, 20)
        assert isinstance(result, date) and not isinstance(result, datetime)

    def test_get_ultima_fecha_stock_returns_none_when_empty(self):
        loader = DataLoader(engine=MagicMock())
        loader.execute_query = lambda q, p=None: pd.DataFrame({"ultima_fecha": [None]})

        result = loader.get_ultima_fecha_stock()

        assert result is None


# ── Task 1.5: regression lock — no fan-out on existing get_stock_diario ─────


class TestStockNoFanout:
    """Regression lock (NO code change): get_stock_diario() must keep rolling
    gold.fact_stock up to sucursal via gold.dim_deposito, joined on the plain
    id_deposito key. Unlike id_vendedor/id_ruta, id_deposito is globally
    unique, so no (id + id_sucursal) composite key is required here — this
    test pins that design choice so a future edit can't silently reintroduce
    a fan-out-prone composite join."""

    def test_stock_diario_rolls_to_sucursal_via_dim_deposito(self):
        loader = DataLoader(engine=MagicMock())
        captured = {}

        def fake_execute_query(query, params=None):
            captured["query"] = query
            captured["params"] = params
            return pd.DataFrame(
                columns=[
                    "id_articulo", "generico", "marca", "des_articulo",
                    "sucursal", "cant_bultos", "cant_htls",
                ]
            )

        loader.execute_query = fake_execute_query
        loader.get_stock_diario(fecha="2026-07-20")

        sql = captured["query"]
        assert "gold.fact_stock" in sql
        assert "gold.dim_deposito" in sql
        assert "d.id_deposito = f.id_deposito" in sql
        assert "d.des_sucursal" in sql
