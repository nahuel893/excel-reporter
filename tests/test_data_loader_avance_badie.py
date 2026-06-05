"""Integration tests for Avance Badie DataLoader methods.

Verifies the pivot_badie aggregated queries are consistent with the raw
queries: SUM(cantidades_total) over the same period+sucursal+anulado=false
must match between get_fact_ventas_raw and get_fact_ventas_pivot_badie.

This catches drift between the two queries when one is edited (e.g. a
new JOIN filter accidentally drops rows, or the anulado filter changes).
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest


def _has_db_access() -> bool:
    if os.environ.get("AGENT_TEST_DB_URL"):
        return True
    return all(os.environ.get(k) for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"))


@pytest.fixture(scope="module")
def data_loader():
    from src.core.data_loader import DataLoader
    return DataLoader()


@pytest.fixture(scope="module")
def date_range():
    """Small recent window — 7 days back from yesterday — to keep tests fast."""
    yesterday = date.today() - timedelta(days=1)
    return (yesterday - timedelta(days=7)).isoformat(), yesterday.isoformat()


@pytest.mark.integration
@pytest.mark.skipif(not _has_db_access(), reason="No DB credentials in environment")
class TestFactVentasGrainConsistency:
    """Pivot Badie must equal raw fact_ventas in total cantidades (anulado=false)."""

    ID_SUCURSAL = 1
    ID_FUERZA_VENTAS = 1

    def test_sum_cantidades_matches_raw(self, data_loader, date_range):
        """SUM(cantidades_total) over non-anulado must be identical.

        Raw method does NOT filter anulado, so we apply the filter in pandas
        for parity with the pivot method (which filters in SQL).
        """
        fecha_desde, fecha_hasta = date_range

        df_raw = data_loader.get_fact_ventas_raw(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_sucursal=self.ID_SUCURSAL,
        )
        df_pivot = data_loader.get_fact_ventas_pivot_badie(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_sucursal=self.ID_SUCURSAL,
            id_fuerza_ventas=self.ID_FUERZA_VENTAS,
        )

        # Raw includes anulado=true — filter for parity
        anulado_mask = df_raw["anulado"].astype(bool)
        raw_total = df_raw.loc[~anulado_mask, "cantidades_total"].sum()
        pivot_total = df_pivot["Cantidades Totales"].sum()

        # Float tolerance for SUM accumulator drift
        assert abs(raw_total - pivot_total) < 0.01, (
            f"Grain consistency failure: raw SUM={raw_total} vs pivot SUM={pivot_total} "
            f"(delta={raw_total - pivot_total})"
        )

    def test_pivot_row_count_le_raw_row_count(self, data_loader, date_range):
        """Aggregation can only reduce or maintain row count, never increase it."""
        fecha_desde, fecha_hasta = date_range

        df_raw = data_loader.get_fact_ventas_raw(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_sucursal=self.ID_SUCURSAL,
        )
        df_pivot = data_loader.get_fact_ventas_pivot_badie(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_sucursal=self.ID_SUCURSAL,
            id_fuerza_ventas=self.ID_FUERZA_VENTAS,
        )

        anulado_mask = df_raw["anulado"].astype(bool)
        raw_non_anulado = (~anulado_mask).sum()

        assert len(df_pivot) <= raw_non_anulado, (
            f"Pivot has more rows ({len(df_pivot)}) than non-anulado raw ({raw_non_anulado})"
        )

    def test_pivot_has_all_expected_columns(self, data_loader, date_range):
        """Schema sanity check — Excel headers must match exactly."""
        fecha_desde, fecha_hasta = date_range

        df_pivot = data_loader.get_fact_ventas_pivot_badie(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_sucursal=self.ID_SUCURSAL,
            id_fuerza_ventas=self.ID_FUERZA_VENTAS,
        )

        expected = {
            "Sucursal",
            "Descripcion Período",
            "Descripcion Vendedor",
            "Ruta",
            "Descripcion_Ruta",
            "Descripcion_Marca",
            "GENERICO",
            "Código_Articulo",
            "Descripcion_Articulo",
            "Cantidades Totales",
        }
        assert set(df_pivot.columns) == expected, (
            f"Column mismatch: extra={set(df_pivot.columns) - expected}, "
            f"missing={expected - set(df_pivot.columns)}"
        )


@pytest.mark.integration
@pytest.mark.skipif(not _has_db_access(), reason="No DB credentials in environment")
class TestCoberturaGrainConsistency:
    """Pivot Badie cob queries must equal raw cob queries in total clientes_compradores."""

    ID_SUCURSAL = 1
    ID_FUERZA_VENTAS = 1

    @pytest.fixture
    def cob_date_range(self):
        """Cob tables are periodo-indexed (first-of-month). Use last month."""
        today = date.today()
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start.isoformat(), last_month_end.isoformat()

    def test_generico_sum_clientes_matches_raw(self, data_loader, cob_date_range):
        fecha_desde, fecha_hasta = cob_date_range

        df_raw = data_loader.get_cob_preventista_generico_raw(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_fuerza_ventas=self.ID_FUERZA_VENTAS,
            id_sucursal=self.ID_SUCURSAL,
        )
        df_pivot = data_loader.get_cob_preventista_generico_pivot_badie(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_fuerza_ventas=self.ID_FUERZA_VENTAS,
            id_sucursal=self.ID_SUCURSAL,
        )

        assert df_raw["clientes_compradores"].sum() == df_pivot["Numero_Clientes"].sum(), (
            f"cob_gen total mismatch: raw={df_raw['clientes_compradores'].sum()} "
            f"vs pivot={df_pivot['Numero_Clientes'].sum()}"
        )
        # Row count must also match — pivot only renames/joins, no aggregation
        assert len(df_raw) == len(df_pivot), (
            f"cob_gen row count mismatch: raw={len(df_raw)} vs pivot={len(df_pivot)}"
        )

    def test_marca_sum_clientes_matches_raw(self, data_loader, cob_date_range):
        fecha_desde, fecha_hasta = cob_date_range

        df_raw = data_loader.get_cob_preventista_marca_raw(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_fuerza_ventas=self.ID_FUERZA_VENTAS,
            id_sucursal=self.ID_SUCURSAL,
        )
        df_pivot = data_loader.get_cob_preventista_marca_pivot_badie(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            id_fuerza_ventas=self.ID_FUERZA_VENTAS,
            id_sucursal=self.ID_SUCURSAL,
        )

        assert df_raw["clientes_compradores"].sum() == df_pivot["Numero_Clientes"].sum(), (
            f"cob_marca total mismatch: raw={df_raw['clientes_compradores'].sum()} "
            f"vs pivot={df_pivot['Numero_Clientes'].sum()}"
        )
        assert len(df_raw) == len(df_pivot), (
            f"cob_marca row count mismatch: raw={len(df_raw)} vs pivot={len(df_pivot)}"
        )
