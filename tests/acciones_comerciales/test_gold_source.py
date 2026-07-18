"""RED tests — S1.1: gold datasource for acciones-comerciales (RF-01).

Covers:
  - DataLoader.get_aexcel_equivalent(): composite-key join (id_cliente AND
    id_sucursal), NO id_fuerza_ventas / dim_vendedor join, bonificacion/100,
    anulado=false, zero DDL.
  - gold_source.collapse_to_terna_grain(): deterministic non-additive
    grain-collapse (Decision 14) — precio/Bonific = ACTUAL picked-line
    value (greatest Cantidades Totales, tie-break greatest Precio, tie-break
    lowest _id_linea), additive SUM columns, multi-price terna flagging.
  - gold_source.load_aexcel_equivalent(): thin orchestration wrapper.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy import Engine

from src.core.data_loader import DataLoader
from src.services.acciones_comerciales.gold_source import (
    TERNA_COLS,
    AexcelEquivalentResult,
    collapse_to_terna_grain,
    load_aexcel_equivalent,
    load_sucursal_por_cliente,
)


def _make_loader_with_mock_engine(query_result_df: pd.DataFrame) -> DataLoader:
    mock_engine = MagicMock(spec=Engine)
    loader = DataLoader(engine=mock_engine)
    loader.execute_query = MagicMock(return_value=query_result_df)
    return loader


# ─────────────────────────────────────────────────────────────────────────
# DataLoader.get_aexcel_equivalent() — SQL-text assertions (RF-01, RF-25)
# ─────────────────────────────────────────────────────────────────────────


class TestGetAexcelEquivalentSQL:
    def test_calls_execute_query_with_composite_key_join(self):
        loader = _make_loader_with_mock_engine(pd.DataFrame())
        loader.get_aexcel_equivalent("2026-07-01", "2026-07-31")

        sql, params = loader.execute_query.call_args[0]
        # dim_cliente joined on BOTH id_cliente AND id_sucursal (GOLDEN RULE)
        assert "fv.id_cliente = dc.id_cliente" in sql
        assert "fv.id_sucursal = dc.id_sucursal" in sql

    def test_does_not_join_dim_vendedor_or_use_id_fuerza_ventas(self):
        loader = _make_loader_with_mock_engine(pd.DataFrame())
        loader.get_aexcel_equivalent("2026-07-01", "2026-07-31")

        sql, _ = loader.execute_query.call_args[0]
        assert "dim_vendedor" not in sql
        assert "id_fuerza_ventas" not in sql

    def test_bonificacion_divided_by_100(self):
        loader = _make_loader_with_mock_engine(pd.DataFrame())
        loader.get_aexcel_equivalent("2026-07-01", "2026-07-31")

        sql, _ = loader.execute_query.call_args[0]
        assert "bonificacion / 100.0" in sql

    def test_anulado_false_filter(self):
        loader = _make_loader_with_mock_engine(pd.DataFrame())
        loader.get_aexcel_equivalent("2026-07-01", "2026-07-31")

        sql, _ = loader.execute_query.call_args[0]
        assert "anulado = false" in sql

    def test_params_are_the_date_range(self):
        loader = _make_loader_with_mock_engine(pd.DataFrame())
        loader.get_aexcel_equivalent("2026-07-01", "2026-07-31")

        _, params = loader.execute_query.call_args[0]
        assert params == {"fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-31"}

    def test_no_ddl_keywords_in_sql(self):
        """RF-25: zero DDL against production gold."""
        loader = _make_loader_with_mock_engine(pd.DataFrame())
        loader.get_aexcel_equivalent("2026-07-01", "2026-07-31")

        sql, _ = loader.execute_query.call_args[0]
        upper = sql.upper()
        for forbidden in ("CREATE ", "ALTER ", "DROP ", "TRUNCATE ", "INSERT ", "UPDATE ", "DELETE "):
            assert forbidden not in upper, f"DDL/DML keyword {forbidden!r} found in gold_source SQL"

    def test_returns_execute_query_result(self):
        expected = pd.DataFrame({"Cod. Cliente": [1]})
        loader = _make_loader_with_mock_engine(expected)

        result = loader.get_aexcel_equivalent("2026-07-01", "2026-07-31")

        assert result is expected


# ─────────────────────────────────────────────────────────────────────────
# gold_source.collapse_to_terna_grain() — deterministic pick (Decision 14)
# ─────────────────────────────────────────────────────────────────────────


def _line(
    fecha="2026-07-01",
    cliente=100,
    articulo=900,
    precio=10.0,
    bonific=0.1,
    cantidad=5.0,
    facturacion=50.0,
    descuentos=5.0,
    id_linea=1,
    descripcion="CLIENTE UNO",
    sucursal="1 - CASA CENTRAL",
    des_articulo="ARTICULO UNO",
    marca="MARCA UNO",
    unidad_negocio="CERVEZAS",
) -> dict:
    return {
        "_id_linea": id_linea,
        "Descripción Período": fecha,
        "Cod. Cliente": cliente,
        "Descripción": descripcion,
        "Sucursal": sucursal,
        "Código": articulo,
        "Descripción_2": des_articulo,
        "Descripción_3": marca,
        "Descripción_12": unidad_negocio,
        "Precio": precio,
        "Bonific": bonific,
        "Cantidades Totales": cantidad,
        "Facturacion Neta": facturacion,
        "Descuentos": descuentos,
    }


class TestCollapseToTernaGrainSingleLine:
    def test_single_line_terna_passthrough(self):
        df = pd.DataFrame([_line()])

        result = collapse_to_terna_grain(df)

        assert isinstance(result, AexcelEquivalentResult)
        assert len(result.data) == 1
        row = result.data.iloc[0]
        assert row["Precio"] == 10.0
        assert row["Bonific"] == 0.1
        assert row["Cantidades Totales"] == 5.0
        assert result.multi_price_ternas == []

    def test_empty_input_returns_empty_result(self):
        df = pd.DataFrame(columns=list(_line().keys()))

        result = collapse_to_terna_grain(df)

        assert result.data.empty
        assert result.multi_price_ternas == []


class TestCollapseToTernaGrainAdditiveSums:
    def test_same_price_multi_line_sums_additive_cols_not_flagged(self):
        """Two lines, SAME price/bonific -> sums additive, no ambiguity flag."""
        df = pd.DataFrame(
            [
                _line(id_linea=1, cantidad=3.0, facturacion=30.0, descuentos=3.0),
                _line(id_linea=2, cantidad=2.0, facturacion=20.0, descuentos=2.0),
            ]
        )

        result = collapse_to_terna_grain(df)

        assert len(result.data) == 1
        row = result.data.iloc[0]
        assert row["Cantidades Totales"] == 5.0
        assert row["Facturacion Neta"] == 50.0
        assert row["Descuentos"] == 5.0
        # Same price on both lines -> real, unambiguous value, never averaged
        assert row["Precio"] == 10.0
        assert result.multi_price_ternas == []

    def test_two_ternas_kept_separate(self):
        df = pd.DataFrame(
            [
                _line(articulo=900, cantidad=3.0),
                _line(articulo=901, cantidad=2.0),
            ]
        )

        result = collapse_to_terna_grain(df)

        assert len(result.data) == 2
        assert set(result.data["Código"]) == {900, 901}


class TestCollapseToTernaGrainDeterministicPick:
    def test_multi_price_terna_picks_actual_line_never_average(self):
        """Two lines, DIFFERENT price. Greatest Cantidades Totales wins.
        The picked Precio must be an ACTUAL source value — never the
        average (Decision 14: (10+20)/2=15 must NEVER appear)."""
        df = pd.DataFrame(
            [
                _line(id_linea=1, precio=10.0, bonific=0.05, cantidad=2.0),
                _line(id_linea=2, precio=20.0, bonific=0.15, cantidad=8.0),
            ]
        )

        result = collapse_to_terna_grain(df)

        row = result.data.iloc[0]
        assert row["Precio"] == 20.0  # line 2 has the greatest Cantidades Totales
        assert row["Bonific"] == 0.15
        assert row["Precio"] != 15.0  # never an average
        assert row["Cantidades Totales"] == 10.0  # additive sum still correct

    def test_tie_break_greatest_precio_when_cantidad_tied(self):
        df = pd.DataFrame(
            [
                _line(id_linea=1, precio=10.0, cantidad=5.0),
                _line(id_linea=2, precio=25.0, cantidad=5.0),
            ]
        )

        result = collapse_to_terna_grain(df)

        row = result.data.iloc[0]
        assert row["Precio"] == 25.0  # tie on Cantidades -> greatest Precio wins

    def test_tie_break_lowest_id_linea_when_cantidad_and_precio_tied(self):
        df = pd.DataFrame(
            [
                _line(id_linea=5, precio=10.0, cantidad=5.0, descripcion="LINEA B"),
                _line(id_linea=2, precio=10.0, cantidad=5.0, descripcion="LINEA A"),
            ]
        )

        result = collapse_to_terna_grain(df)

        row = result.data.iloc[0]
        # Both Cantidades and Precio tied -> lowest _id_linea (2) wins
        assert row["Descripción"] == "LINEA A"

    def test_picked_line_nan_survives_not_borrowed_from_sibling_line(self):
        """Regression guard: groupby(...).first() returns the first
        NON-NULL value PER COLUMN (not the first row), which would
        silently splice a value from a DIFFERENT source line into the
        picked row whenever the winner has a NaN — exactly the fabricated
        value Decision 14 forbids. The picked line's actual NaN must
        survive untouched, never backfilled from a sibling line."""
        df = pd.DataFrame(
            [
                _line(id_linea=1, precio=float("nan"), bonific=0.05, cantidad=8.0),
                _line(id_linea=2, precio=20.0, bonific=0.15, cantidad=2.0),
            ]
        )

        result = collapse_to_terna_grain(df)

        row = result.data.iloc[0]
        # line 1 (cantidad=8.0) wins the pick — its Precio is NaN, and that
        # NaN must survive, NOT be silently replaced by line 2's 20.0.
        assert pd.isna(row["Precio"])
        assert row["Cantidades Totales"] == 10.0  # additive sum unaffected

    def test_deterministic_pick_is_reproducible(self):
        """Running the collapse twice on the same input yields the same pick."""
        df = pd.DataFrame(
            [
                _line(id_linea=1, precio=10.0, cantidad=2.0),
                _line(id_linea=2, precio=20.0, cantidad=8.0),
                _line(id_linea=3, precio=30.0, cantidad=1.0),
            ]
        )

        result_a = collapse_to_terna_grain(df)
        result_b = collapse_to_terna_grain(df)

        assert result_a.data.iloc[0]["Precio"] == result_b.data.iloc[0]["Precio"] == 20.0


class TestCollapseToTernaGrainMultiPriceFlagging:
    def test_multi_price_terna_is_flagged(self):
        df = pd.DataFrame(
            [
                _line(id_linea=1, precio=10.0, bonific=0.05, cantidad=2.0),
                _line(id_linea=2, precio=20.0, bonific=0.15, cantidad=8.0),
            ]
        )

        result = collapse_to_terna_grain(df)

        assert len(result.multi_price_ternas) == 1
        flagged = result.multi_price_ternas[0]
        assert flagged.id_cliente == 100
        assert flagged.id_articulo == 900
        assert sorted(flagged.candidate_precios) == [10.0, 20.0]
        assert flagged.picked_precio == 20.0
        assert flagged.picked_bonific == 0.15
        assert flagged.pick_reason  # non-empty audit trail

    def test_multi_bonific_same_price_still_flagged(self):
        """Differing Bonific alone (even with identical Precio) must flag —
        the pick discipline covers both non-additive columns."""
        df = pd.DataFrame(
            [
                _line(id_linea=1, precio=10.0, bonific=0.05, cantidad=8.0),
                _line(id_linea=2, precio=10.0, bonific=0.20, cantidad=2.0),
            ]
        )

        result = collapse_to_terna_grain(df)

        assert len(result.multi_price_ternas) == 1

    def test_unflagged_terna_not_in_multi_price_list(self):
        df = pd.DataFrame(
            [
                _line(articulo=900, id_linea=1, precio=10.0, cantidad=2.0),
                _line(articulo=900, id_linea=2, precio=10.0, cantidad=3.0),
                _line(articulo=901, id_linea=3, precio=15.0, cantidad=1.0),
                _line(articulo=901, id_linea=4, precio=25.0, cantidad=9.0),
            ]
        )

        result = collapse_to_terna_grain(df)

        flagged_articulos = {t.id_articulo for t in result.multi_price_ternas}
        assert flagged_articulos == {901}


# ─────────────────────────────────────────────────────────────────────────
# gold_source.load_aexcel_equivalent() — orchestration wrapper
# ─────────────────────────────────────────────────────────────────────────


class TestLoadAexcelEquivalent:
    def test_fetches_from_loader_and_collapses(self):
        df_lineas = pd.DataFrame(
            [
                _line(id_linea=1, precio=10.0, cantidad=2.0),
                _line(id_linea=2, precio=20.0, cantidad=8.0),
            ]
        )
        loader = MagicMock(spec=DataLoader)
        loader.get_aexcel_equivalent.return_value = df_lineas

        result = load_aexcel_equivalent(loader, "2026-07-01", "2026-07-31")

        loader.get_aexcel_equivalent.assert_called_once_with("2026-07-01", "2026-07-31")
        assert len(result.data) == 1
        assert result.data.iloc[0]["Precio"] == 20.0
        assert len(result.multi_price_ternas) == 1

    def test_terna_cols_constant_matches_grain(self):
        assert TERNA_COLS == ["Descripción Período", "Cod. Cliente", "Código"]


# ─────────────────────────────────────────────────────────────────────────
# S3 — DataLoader.get_clientes_sucursal() — fresh SUCURSAL lookup (RF-04)
# ─────────────────────────────────────────────────────────────────────────


class TestGetClientesSucursalSQL:
    def test_selects_distinct_on_id_cliente(self):
        loader = _make_loader_with_mock_engine(pd.DataFrame())
        loader.get_clientes_sucursal()

        sql = loader.execute_query.call_args[0][0]
        assert "DISTINCT ON (dc.id_cliente)" in sql

    def test_anulado_false_filter(self):
        loader = _make_loader_with_mock_engine(pd.DataFrame())
        loader.get_clientes_sucursal()

        sql = loader.execute_query.call_args[0][0]
        assert "anulado = false" in sql

    def test_sucursal_label_is_bare_name_matching_zonas_config(self):
        """RF-07's own scenario keys ZONA off a BARE sucursal name
        (``SUCURSAL = "CASA CENTRAL"``, no id prefix) — matching
        ``configs/acciones_comerciales_zonas.json``'s bare keys. This is a
        DIFFERENT convention from aexcel's own '{id} - {DESC}' Sucursal
        field (FACT_NET row field) — the two are independent contracts."""
        loader = _make_loader_with_mock_engine(pd.DataFrame())
        loader.get_clientes_sucursal()

        sql = loader.execute_query.call_args[0][0]
        assert 'dc.des_sucursal' in sql and 'AS "Sucursal"' in sql
        assert "id_sucursal || ' - '" not in sql

    def test_no_ddl_keywords_in_sql(self):
        loader = _make_loader_with_mock_engine(pd.DataFrame())
        loader.get_clientes_sucursal()

        sql = loader.execute_query.call_args[0][0]
        upper = sql.upper()
        for forbidden in ("CREATE ", "ALTER ", "DROP ", "TRUNCATE ", "INSERT ", "UPDATE ", "DELETE "):
            assert forbidden not in upper

    def test_returns_execute_query_result(self):
        expected = pd.DataFrame({"Cod. Cliente": [1], "Sucursal": ["1 - CASA CENTRAL"]})
        loader = _make_loader_with_mock_engine(expected)

        result = loader.get_clientes_sucursal()

        assert result is expected


# ─────────────────────────────────────────────────────────────────────────
# S3 — gold_source.load_sucursal_por_cliente() — orchestration wrapper
# ─────────────────────────────────────────────────────────────────────────


class TestLoadSucursalPorCliente:
    def test_builds_dict_from_loader_result(self):
        df = pd.DataFrame(
            {
                "Cod. Cliente": [100, 101],
                "Sucursal": ["1 - CASA CENTRAL", "2 - SUCURSAL CAFAYATE"],
            }
        )
        loader = MagicMock(spec=DataLoader)
        loader.get_clientes_sucursal.return_value = df

        mapping = load_sucursal_por_cliente(loader)

        loader.get_clientes_sucursal.assert_called_once_with()
        assert mapping == {100: "1 - CASA CENTRAL", 101: "2 - SUCURSAL CAFAYATE"}
