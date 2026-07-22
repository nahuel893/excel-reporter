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
