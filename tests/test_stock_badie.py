"""Tests for DataLoader.get_venta_mes / get_ultima_fecha_stock (RF-01, RF-02)
and the stock_badie pure-pandas processor (RF-03/04/05).

Also locks the existing get_stock_diario() dim_deposito join as a
fan-out regression guard (Phase 1, Task 1.5 — no code change).

Strict TDD — sdd/stock-badie.
PR1 (Phase 1): DataLoader methods, DB access mocked at execute_query level.
PR2 (Phase 2): pure pandas processor, in-memory DataFrame fixtures only —
no DB access anywhere in this file.
"""

import logging
import re
from datetime import date, datetime

import numpy as np
import pandas as pd
from unittest.mock import MagicMock

from src.core.data_loader import DataLoader
from src.services.stock_badie.processor import (
    SUCURSAL_ORDER,
    build_universe,
    compute_dias_venta,
    pivot_wide,
)
from src.services.stock_badie.workbook import (
    DATA_START_ROW,
    HEADER_ROW,
    build_workbook,
)


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


# ── RF-03: build_universe ────────────────────────────────────────────────────
# Strict TDD — Phase 2, Task 2.1 (RED) / 2.2 (GREEN) of sdd/stock-badie PR2.


def _stock_row(id_articulo, sucursal, cant_bultos, cant_htls=0.0, **overrides):
    row = {
        "id_articulo": id_articulo,
        "generico": "CERVEZAS",
        "marca": "QUILMES",
        "des_articulo": f"ARTICULO {id_articulo}",
        "sucursal": sucursal,
        "cant_bultos": cant_bultos,
        "cant_htls": cant_htls,
    }
    row.update(overrides)
    return row


def _venta_row(id_articulo, sucursal, venta_bultos, venta_htls=0.0, id_sucursal=1):
    return {
        "id_sucursal": id_sucursal,
        "sucursal": sucursal,
        "id_articulo": id_articulo,
        "venta_bultos": venta_bultos,
        "venta_htls": venta_htls,
    }


_EMPTY_VENTA_DF = pd.DataFrame(
    columns=["id_sucursal", "sucursal", "id_articulo", "venta_bultos", "venta_htls"]
)


class TestBuildUniverse:
    def test_dormant_stock_kept_with_venta_coalesced_to_zero(self):
        """stock=5, no sales this month -> kept, venta coalesced to 0, 'dormant'."""
        stock_df = pd.DataFrame([_stock_row(1, "CASA CENTRAL", cant_bultos=5, cant_htls=0.5)])

        result = build_universe(stock_df, _EMPTY_VENTA_DF)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["stock_bultos"] == 5
        assert row["venta_bultos"] == 0
        assert not pd.isna(row["venta_bultos"])
        assert row["estado"] == "dormant"

    def test_quiebre_stock_zero_with_sales_is_kept(self):
        """stock=0, sales=10 this month -> kept (row exists because fact_stock
        emits zero rows), 'quiebre'."""
        stock_df = pd.DataFrame([_stock_row(2, "CASA CENTRAL", cant_bultos=0, cant_htls=0)])
        venta_df = pd.DataFrame([_venta_row(2, "CASA CENTRAL", venta_bultos=10, venta_htls=1.0)])

        result = build_universe(stock_df, venta_df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["stock_bultos"] == 0
        assert row["venta_bultos"] == 10
        assert row["estado"] == "quiebre"

    def test_zero_stock_no_sales_is_dropped(self):
        """stock=0, no sales -> excluded (the ~91% zero noise)."""
        stock_df = pd.DataFrame([_stock_row(3, "CASA CENTRAL", cant_bultos=0, cant_htls=0)])

        result = build_universe(stock_df, _EMPTY_VENTA_DF)

        assert result.empty

    def test_normal_stock_with_sales_is_kept(self):
        """stock>0 and sales>0 -> kept, 'normal' (neither dormant nor quiebre)."""
        stock_df = pd.DataFrame([_stock_row(4, "CASA CENTRAL", cant_bultos=20, cant_htls=2.0)])
        venta_df = pd.DataFrame([_venta_row(4, "CASA CENTRAL", venta_bultos=15, venta_htls=1.5)])

        result = build_universe(stock_df, venta_df)

        assert len(result) == 1
        assert result.iloc[0]["estado"] == "normal"

    def test_output_columns(self):
        stock_df = pd.DataFrame([_stock_row(5, "CASA CENTRAL", cant_bultos=5, cant_htls=0.5)])

        result = build_universe(stock_df, _EMPTY_VENTA_DF)

        assert list(result.columns) == [
            "id_articulo", "des_articulo", "generico", "marca", "sucursal",
            "stock_bultos", "stock_htls", "venta_bultos", "venta_htls", "estado",
        ]

    def test_merges_stock_and_venta_by_sucursal_name_and_id_articulo(self):
        """Sales for a DIFFERENT sucursal (same articulo) must not leak onto a
        stock row for another sucursal — the merge key is (sucursal, id_articulo)."""
        stock_df = pd.DataFrame([_stock_row(6, "CASA CENTRAL", cant_bultos=5, cant_htls=0.5)])
        venta_df = pd.DataFrame([_venta_row(6, "SUCURSAL METAN", venta_bultos=99, venta_htls=9.9)])

        result = build_universe(stock_df, venta_df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["sucursal"] == "CASA CENTRAL"
        assert row["venta_bultos"] == 0
        assert row["estado"] == "dormant"

    # ── FIX 2: NaN stock coalesce (CRITICAL) ────────────────────────────────

    def test_nan_stock_bultos_coalesced_to_zero_and_classified(self):
        """gold.fact_stock SUM(...) can return NaN; a NaN stock_bultos must be
        coalesced to 0 (like venta_bultos already is), not left as NaN — a raw
        NaN would make the `!= 0` keep-filter always True (NaN != 0) and would
        never classify as 'normal'."""
        stock_df = pd.DataFrame([_stock_row(7, "CASA CENTRAL", cant_bultos=np.nan, cant_htls=np.nan)])
        venta_df = pd.DataFrame([_venta_row(7, "CASA CENTRAL", venta_bultos=10, venta_htls=1.0)])

        result = build_universe(stock_df, venta_df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["stock_bultos"] == 0
        assert not pd.isna(row["stock_bultos"])
        assert row["estado"] == "quiebre"

    # ── FIX 3: total estado classification with negative venta (CORRECTNESS) ─

    def test_negative_venta_with_zero_stock_is_quiebre_not_normal(self):
        """get_venta_mes does not filter anulado, so venta_bultos can be
        negative (net returns). stock=0 & venta=-3 must classify as
        'quiebre', not fall through to the 'normal' default."""
        stock_df = pd.DataFrame([_stock_row(8, "CASA CENTRAL", cant_bultos=0, cant_htls=0)])
        venta_df = pd.DataFrame([_venta_row(8, "CASA CENTRAL", venta_bultos=-3, venta_htls=-0.3)])

        result = build_universe(stock_df, venta_df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["stock_bultos"] == 0
        assert row["venta_bultos"] == -3
        assert row["estado"] == "quiebre"
        assert row["estado"] != "normal"

    def test_negative_venta_with_positive_stock_is_dormant(self):
        """stock=5 & venta=-2 (net returns) must classify as 'dormant', not
        'normal' — venta_bultos <= 0 covers both zero and negative sales."""
        stock_df = pd.DataFrame([_stock_row(9, "CASA CENTRAL", cant_bultos=5, cant_htls=0.5)])
        venta_df = pd.DataFrame([_venta_row(9, "CASA CENTRAL", venta_bultos=-2, venta_htls=-0.2)])

        result = build_universe(stock_df, venta_df)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["estado"] == "dormant"

    # ── FIX 6: log unmatched / NaN-sucursal venta rows (CRITICAL) ───────────

    def test_unmatched_venta_row_logs_warning_with_count(self, caplog):
        """A venta row whose (sucursal, id_articulo) key is absent from
        stock_df is an anti-join miss (fact_stock lag / sucursal-name drift)
        — it must not crash, and must emit a warning naming the count."""
        stock_df = pd.DataFrame([_stock_row(10, "CASA CENTRAL", cant_bultos=5, cant_htls=0.5)])
        venta_df = pd.DataFrame(
            [_venta_row(10, "SUCURSAL QUE NO EXISTE EN STOCK", venta_bultos=7, venta_htls=0.7)]
        )

        with caplog.at_level(logging.WARNING):
            result = build_universe(stock_df, venta_df)

        assert isinstance(result, pd.DataFrame)  # did not crash
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("1" in w.getMessage() and "did not match" in w.getMessage() for w in warnings)


# ── RF-04: SUCURSAL_ORDER + pivot_wide ───────────────────────────────────────
# Strict TDD — Phase 2, Task 2.3 (RED) / 2.4 (GREEN) of sdd/stock-badie PR2.


def _universe_row(id_articulo, sucursal, stock_bultos, venta_bultos, estado="normal"):
    return {
        "id_articulo": id_articulo,
        "des_articulo": f"ARTICULO {id_articulo}",
        "generico": "CERVEZAS",
        "marca": "QUILMES",
        "sucursal": sucursal,
        "stock_bultos": stock_bultos,
        "stock_htls": stock_bultos * 0.1,
        "venta_bultos": venta_bultos,
        "venta_htls": venta_bultos * 0.1,
        "estado": estado,
    }


class TestPivotWide:
    def test_sucursal_order_has_14_entries(self):
        assert len(SUCURSAL_ORDER) == 14
        assert SUCURSAL_ORDER[0] == "CASA CENTRAL"
        assert SUCURSAL_ORDER[-1] == "SUCURSAL PERICO"

    def test_articulo_present_only_in_one_sucursal_shows_zero_elsewhere(self):
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )

        result = pivot_wide(universe_df)

        assert len(result) == 1
        assert result.loc[0, ("CASA CENTRAL", "Stock")] == 5
        for sucursal in SUCURSAL_ORDER:
            if sucursal == "CASA CENTRAL":
                continue
            value = result.loc[0, (sucursal, "Stock")]
            assert value == 0
            assert not pd.isna(value)

    def test_column_order_matches_sucursal_order_regardless_of_input_row_order(self):
        # Feed rows in REVERSE sucursal order to prove pivot_wide does not
        # inherit column order from input row order.
        rows = [
            _universe_row(1, sucursal, stock_bultos=1, venta_bultos=1)
            for sucursal in reversed(SUCURSAL_ORDER)
        ]
        universe_df = pd.DataFrame(rows)

        result = pivot_wide(universe_df)

        expected_columns = [("", col) for col in ["idArticulo", "dsArticulo", "GENERICO", "MARCA"]]
        for sucursal in SUCURSAL_ORDER:
            expected_columns += [
                (sucursal, "Stock"), (sucursal, "VENTA"), (sucursal, "PEDIDO"), (sucursal, "ALCANCE"),
            ]
        expected_columns += [
            ("Total", "Total"), ("Total", "VENTA TOTAL"), ("Total", "PEDIDO TOTAL"), ("Total", "ALCANCE TOTAL"),
        ]

        assert result.columns.tolist() == expected_columns

    def test_total_column_count_is_64(self):
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=1, venta_bultos=1)]
        )

        result = pivot_wide(universe_df)

        assert result.shape[1] == 64

    def test_pedido_alcance_and_total_block_are_placeholders(self):
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )

        result = pivot_wide(universe_df)

        pedido_cols = result.loc[:, result.columns.get_level_values(1) == "PEDIDO"]
        alcance_cols = result.loc[:, result.columns.get_level_values(1) == "ALCANCE"]
        total_block_cols = result.loc[:, result.columns.get_level_values(0) == "Total"]

        assert pedido_cols.iloc[0].isna().all()
        assert alcance_cols.iloc[0].isna().all()
        assert total_block_cols.iloc[0].isna().all()

    def test_one_row_per_articulo(self):
        universe_df = pd.DataFrame(
            [
                _universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10),
                _universe_row(1, "SUCURSAL METAN", stock_bultos=3, venta_bultos=0, estado="dormant"),
                _universe_row(2, "CASA CENTRAL", stock_bultos=0, venta_bultos=7, estado="quiebre"),
            ]
        )

        result = pivot_wide(universe_df)

        assert len(result) == 2
        assert sorted(result[("", "idArticulo")].tolist()) == [1, 2]
        art1 = result[result[("", "idArticulo")] == 1].iloc[0]
        assert art1[("CASA CENTRAL", "Stock")] == 5
        assert art1[("SUCURSAL METAN", "Stock")] == 3

    # ── FIX 7: unambiguous columns (CRITICAL) ────────────────────────────────

    def test_columns_are_unique_labels_no_silent_overwrite(self):
        """The 14 repeated VENTA/PEDIDO/ALCANCE blocks must be unique
        (block, suffix) tuples — df[("<sucursal>", "PEDIDO")] = x must set
        exactly ONE column, not silently overwrite all 14 like a flat
        'PEDIDO' label would."""
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )

        result = pivot_wide(universe_df)

        assert result.columns.is_unique
        result[("CASA CENTRAL", "PEDIDO")] = 999
        assert result.loc[0, ("CASA CENTRAL", "PEDIDO")] == 999
        # Every other sucursal's PEDIDO placeholder must stay untouched (NaN).
        for sucursal in SUCURSAL_ORDER:
            if sucursal == "CASA CENTRAL":
                continue
            assert pd.isna(result.loc[0, (sucursal, "PEDIDO")])

    # ── FIX 4: identity text-field NaN coalesce (WARNING) ────────────────────

    def test_nan_generico_coalesced_to_empty_string(self):
        row = _universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)
        row["generico"] = np.nan
        universe_df = pd.DataFrame([row])

        result = pivot_wide(universe_df)

        value = result.loc[0, ("", "GENERICO")]
        assert value == ""
        assert not pd.isna(value)

    # ── FIX 5: log sucursales outside SUCURSAL_ORDER (CRITICAL) ─────────────

    def test_sucursal_outside_order_logs_warning_and_is_excluded(self, caplog):
        universe_df = pd.DataFrame(
            [
                _universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10),
                _universe_row(1, "SUCURSAL NUEVA", stock_bultos=3, venta_bultos=1),
            ]
        )

        with caplog.at_level(logging.WARNING):
            result = pivot_wide(universe_df)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("SUCURSAL NUEVA" in w.getMessage() for w in warnings)
        assert "SUCURSAL NUEVA" not in result.columns.get_level_values(0)


# ── RF-05: compute_dias_venta ────────────────────────────────────────────────
# Strict TDD — Phase 2, Task 2.5 (RED) / 2.6 (GREEN) of sdd/stock-badie PR2.
#
# July 2026 calendar reference: 2026-07-04 = Saturday, 2026-07-05 = Sunday,
# 2026-07-09 = FERIADO (Dia de la Independencia, also a Thursday).


class TestComputeDiasVenta:
    def test_sunday_in_window_does_not_increment(self):
        dias_before_sunday = compute_dias_venta(date(2026, 7, 4))  # Saturday
        dias_including_sunday = compute_dias_venta(date(2026, 7, 5))  # Sunday

        assert dias_including_sunday == dias_before_sunday

    def test_feriado_in_window_does_not_increment(self):
        dias_before_feriado = compute_dias_venta(date(2026, 7, 8))  # Wednesday
        dias_including_feriado = compute_dias_venta(date(2026, 7, 9))  # FERIADO (Thursday)

        assert dias_including_feriado == dias_before_feriado

    def test_saturday_does_increment(self):
        dias_before_saturday = compute_dias_venta(date(2026, 7, 3))  # Friday
        dias_including_saturday = compute_dias_venta(date(2026, 7, 4))  # Saturday

        assert dias_including_saturday == dias_before_saturday + 1

    def test_full_first_week_of_july_2026(self):
        # Jul 1 (Wed) .. Jul 4 (Sat) are habiles = 4; Jul 5 (Sun) excluded.
        assert compute_dias_venta(date(2026, 7, 1)) == 1
        assert compute_dias_venta(date(2026, 7, 4)) == 4
        assert compute_dias_venta(date(2026, 7, 5)) == 4

    # ── FIX 1: floor at 1 (CRITICAL — div/0) ─────────────────────────────────

    def test_zero_raw_business_days_floors_to_one(self):
        """Jan 1, 2026 is both a FERIADO (Año Nuevo) and day 1 of its month,
        so the raw NETWORKDAYS-style count is 0. compute_dias_venta must
        floor that at 1: it feeds the downstream PEDIDO formula
        MAX((Venta/$DiasVenta$)*$DiasStock$ - Stock, 0), which has NO
        IFERROR — a raw 0 would produce #DIV/0! across every PEDIDO cell."""
        assert compute_dias_venta(date(2026, 1, 1)) == 1


# ── RF-06/RF-07: build_workbook ──────────────────────────────────────────────
# Strict TDD — Phase 3, Task 3.1 (RED) / 3.2 (GREEN) and 3.3 (RED) / 3.4 (GREEN)
# of sdd/stock-badie PR3.
#
# Column map (fixed, per design spec §3): identity A-D, then 14 sucursal
# blocks of 4 cols [Stock, VENTA, PEDIDO, ALCANCE] starting at col 5 (E),
# then the Total block at cols 61-64 (BI-BL). CASA CENTRAL (block 0) sits at
# E-H; the Total block's Stock/VENTA/PEDIDO/ALCANCE columns are BI/BJ/BK/BL.


def _is_formula(value) -> bool:
    return isinstance(value, str) and value.startswith("=")


class TestBuildWorkbookFormulas:
    def test_dias_stock_and_dias_venta_are_plain_values(self):
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )
        wide_df = pivot_wide(universe_df)

        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)
        ws = wb["STOCK"]

        assert ws["B1"].value == 15
        assert ws["B2"].value == 20
        assert not _is_formula(ws["B1"].value)
        assert not _is_formula(ws["B2"].value)

    def test_named_ranges_point_at_param_cells(self):
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )
        wide_df = pivot_wide(universe_df)

        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)

        assert "DiasStock" in wb.defined_names
        assert "DiasVenta" in wb.defined_names
        assert wb.defined_names["DiasStock"].attr_text == "'STOCK'!$B$1"
        assert wb.defined_names["DiasVenta"].attr_text == "'STOCK'!$B$2"

    def test_header_row_has_sucursal_name_and_block_labels(self):
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )
        wide_df = pivot_wide(universe_df)

        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)
        ws = wb["STOCK"]

        assert ws.cell(row=HEADER_ROW, column=1).value == "idArticulo"
        assert ws.cell(row=HEADER_ROW, column=2).value == "dsArticulo"
        assert ws.cell(row=HEADER_ROW, column=3).value == "GENERICO"
        assert ws.cell(row=HEADER_ROW, column=4).value == "MARCA"
        # CASA CENTRAL block = col 5 (E): Stock header = sucursal name.
        assert ws.cell(row=HEADER_ROW, column=5).value == "CASA CENTRAL"
        assert ws.cell(row=HEADER_ROW, column=6).value == "VENTA"
        assert ws.cell(row=HEADER_ROW, column=7).value == "PEDIDO"
        assert ws.cell(row=HEADER_ROW, column=8).value == "ALCANCE"
        # Total block = cols 61-64 (BI-BL).
        assert ws.cell(row=HEADER_ROW, column=61).value == "Total"
        assert ws.cell(row=HEADER_ROW, column=62).value == "VENTA TOTAL"
        assert ws.cell(row=HEADER_ROW, column=63).value == "PEDIDO TOTAL"
        assert ws.cell(row=HEADER_ROW, column=64).value == "ALCANCE TOTAL"

    def test_stock_and_venta_cells_are_values_not_formulas(self):
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )
        wide_df = pivot_wide(universe_df)

        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)
        ws = wb["STOCK"]
        r = DATA_START_ROW

        stock_cell = ws.cell(row=r, column=5)  # E: CASA CENTRAL Stock
        venta_cell = ws.cell(row=r, column=6)  # F: CASA CENTRAL VENTA

        assert stock_cell.value == 5
        assert venta_cell.value == 10
        assert not _is_formula(stock_cell.value)
        assert not _is_formula(venta_cell.value)

    def test_pedido_formula_references_named_ranges_and_row_cells(self):
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )
        wide_df = pivot_wide(universe_df)

        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)
        ws = wb["STOCK"]
        r = DATA_START_ROW

        pedido_cell = ws.cell(row=r, column=7).value  # G: CASA CENTRAL PEDIDO

        assert _is_formula(pedido_cell)
        assert "DiasVenta" in pedido_cell
        assert "DiasStock" in pedido_cell
        assert f"F{r}" in pedido_cell  # VENTA cell of this row/block
        assert f"E{r}" in pedido_cell  # Stock cell of this row/block
        assert pedido_cell == f"=MAX((F{r}/DiasVenta)*DiasStock-E{r},0)"

    def test_alcance_formula_references_named_range_and_row_cells(self):
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )
        wide_df = pivot_wide(universe_df)

        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)
        ws = wb["STOCK"]
        r = DATA_START_ROW

        alcance_cell = ws.cell(row=r, column=8).value  # H: CASA CENTRAL ALCANCE

        assert _is_formula(alcance_cell)
        assert "DiasVenta" in alcance_cell
        assert alcance_cell == f"=IFERROR(E{r}/(F{r}/DiasVenta),0)"

    def test_last_block_perico_formulas_reference_correct_cells(self):
        """Formulas are generated per-block, not hardcoded to CASA CENTRAL.
        PERICO is the 14th/last block (BE stock, BF venta, BG pedido, BH alcance)."""
        universe_df = pd.DataFrame(
            [_universe_row(1, "SUCURSAL PERICO", stock_bultos=7, venta_bultos=3)]
        )
        wide_df = pivot_wide(universe_df)
        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)
        ws = wb["STOCK"]
        r = DATA_START_ROW

        pedido_perico = ws.cell(row=r, column=59).value   # BG
        alcance_perico = ws.cell(row=r, column=60).value  # BH

        assert pedido_perico == f"=MAX((BF{r}/DiasVenta)*DiasStock-BE{r},0)"
        assert alcance_perico == f"=IFERROR(BE{r}/(BF{r}/DiasVenta),0)"

    def test_empty_wide_df_produces_header_only_sheet(self):
        """No kept pairs -> 0-row wide frame -> valid header-only STOCK sheet,
        not a crash (guards the PR4 row-shifting edits near this loop)."""
        wide_df = pivot_wide(pd.DataFrame())  # empty universe -> 0-row, 64-col

        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)
        ws = wb["STOCK"]

        assert ws.cell(row=HEADER_ROW, column=1).value is not None
        assert ws.cell(row=DATA_START_ROW, column=1).value is None


class TestTotalBlockAlcance:
    def test_total_stock_venta_pedido_are_sums_over_14_blocks(self):
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )
        wide_df = pivot_wide(universe_df)

        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)
        ws = wb["STOCK"]
        r = DATA_START_ROW

        total_stock = ws.cell(row=r, column=61).value  # BI
        total_venta = ws.cell(row=r, column=62).value  # BJ
        total_pedido = ws.cell(row=r, column=63).value  # BK

        assert _is_formula(total_stock) and total_stock.startswith("=SUM(")
        assert _is_formula(total_venta) and total_venta.startswith("=SUM(")
        assert _is_formula(total_pedido) and total_pedido.startswith("=SUM(")
        # 14 sucursal blocks -> 14 comma-separated cell refs inside SUM(...).
        assert total_stock.count(",") == 13
        assert total_venta.count(",") == 13
        assert total_pedido.count(",") == 13

        # Robust ref check: parse the EXACT column letters summed and compare
        # to the hand-derived expected columns (block i Stock at 5+4*i, Venta
        # +1, Pedido +2). Catches a stock/venta/pedido ref swap or a
        # duplicated/omitted sucursal column that the format + comma-count
        # checks above would silently miss (per PR3 reliability review).
        def _sum_cols(formula):
            return sorted(re.findall(r"([A-Z]{1,3})" + str(r) + r"(?!\d)", formula))

        expected_stock = sorted(
            ["E", "I", "M", "Q", "U", "Y", "AC", "AG", "AK", "AO", "AS", "AW", "BA", "BE"]
        )
        expected_venta = sorted(
            ["F", "J", "N", "R", "V", "Z", "AD", "AH", "AL", "AP", "AT", "AX", "BB", "BF"]
        )
        expected_pedido = sorted(
            ["G", "K", "O", "S", "W", "AA", "AE", "AI", "AM", "AQ", "AU", "AY", "BC", "BG"]
        )
        assert _sum_cols(total_stock) == expected_stock
        assert _sum_cols(total_venta) == expected_venta
        assert _sum_cols(total_pedido) == expected_pedido

    def test_alcance_total_is_ratio_of_sums_not_sum_of_alcances(self):
        """The legacy xlsm sums the 14 per-sucursal ALCANCE cells for the
        total (mathematically wrong: sum of ratios != ratio of sums). This
        report's ALCANCE TOTAL must instead divide the row's total-stock
        cell by (total-venta cell / DiasVenta) — i.e. NOT a SUM of the 14
        alcance cells (H, L, P, ... columns)."""
        universe_df = pd.DataFrame(
            [_universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10)]
        )
        wide_df = pivot_wide(universe_df)

        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)
        ws = wb["STOCK"]
        r = DATA_START_ROW

        alcance_total = ws.cell(row=r, column=64).value  # BL

        assert _is_formula(alcance_total)
        assert not alcance_total.startswith("=SUM(")
        assert "DiasVenta" in alcance_total
        # Must reference the row's Total-block Stock (BI) and VENTA TOTAL (BJ)
        # cells — the ratio-of-sums inputs — not any per-sucursal ALCANCE cell.
        assert f"BI{r}" in alcance_total
        assert f"BJ{r}" in alcance_total
        assert alcance_total == f"=IFERROR(BI{r}/(BJ{r}/DiasVenta),0)"

    def test_multiple_article_rows_get_independent_formulas(self):
        universe_df = pd.DataFrame(
            [
                _universe_row(1, "CASA CENTRAL", stock_bultos=5, venta_bultos=10),
                _universe_row(2, "SUCURSAL METAN", stock_bultos=3, venta_bultos=6),
            ]
        )
        wide_df = pivot_wide(universe_df)

        wb = build_workbook(wide_df, dias_venta=20, dias_stock=15)
        ws = wb["STOCK"]

        row1, row2 = DATA_START_ROW, DATA_START_ROW + 1

        alcance_total_row1 = ws.cell(row=row1, column=64).value
        alcance_total_row2 = ws.cell(row=row2, column=64).value

        assert alcance_total_row1 == f"=IFERROR(BI{row1}/(BJ{row1}/DiasVenta),0)"
        assert alcance_total_row2 == f"=IFERROR(BI{row2}/(BJ{row2}/DiasVenta),0)"
        assert alcance_total_row1 != alcance_total_row2
