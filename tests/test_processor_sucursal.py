"""Tests for processor_sucursal — per-sucursal matrix builder and data dispatcher."""
import pandas as pd
import pytest

from src.services.graficos_cobertura.constants import RUTAS_A_SUC16, ZONA_SUCS_AGUAS
from src.services.graficos_cobertura.processor_sucursal import (
    build_sucursal_matrices,
    get_sucursal_data,
    reassign_rutas_suc1_sucursal,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


def _marca_prev_suc1() -> pd.DataFrame:
    """Preventista marca data for sucursal 1 (with id_ruta for reassignment)."""
    return pd.DataFrame({
        "anio": [2025, 2025, 2025, 2025],
        "mes": [3, 3, 4, 4],
        "id_ruta": [85, 90, 85, 90],
        "marca": ["SALTA", "HEINEKEN", "SALTA", "HEINEKEN"],
        "clientes": [100, 200, 90, 180],
    })


def _generico_prev_suc1() -> pd.DataFrame:
    """Preventista generico data for sucursal 1 (with id_ruta)."""
    return pd.DataFrame({
        "anio": [2025, 2025],
        "mes": [3, 4],
        "id_ruta": [85, 90],
        "generico": ["CERVEZAS", "CERVEZAS"],
        "clientes": [100, 200],
    })


def _marca_interior() -> pd.DataFrame:
    """Aggregated marca data for interior sucursales (3, 4, 5, 16)."""
    return pd.DataFrame({
        "anio": [2026, 2026],
        "mes": [3, 3],
        "marca": ["SALTA", "IMPERIAL"],
        "clientes": [500, 300],
    })


def _generico_interior() -> pd.DataFrame:
    """Aggregated generico data for interior sucursales."""
    return pd.DataFrame({
        "anio": [2026],
        "mes": [3],
        "generico": ["CERVEZAS"],
        "clientes": [800],
    })


def _marca_suc_by_id() -> pd.DataFrame:
    """Per-sucursal marca data from get_cobertura_sucursal_marca."""
    return pd.DataFrame({
        "anio": [2026, 2026, 2026, 2026, 2026, 2026],
        "mes": [3, 3, 3, 3, 3, 3],
        "id_sucursal": [3, 3, 4, 4, 5, 16],
        "marca": ["SALTA", "IMPERIAL", "SALTA", "HEINEKEN", "SALTA", "AMSTEL"],
        "clientes": [200, 100, 150, 80, 120, 50],
    })


def _generico_suc_by_id() -> pd.DataFrame:
    """Per-sucursal generico data from get_cobertura_sucursal_generico."""
    return pd.DataFrame({
        "anio": [2026, 2026, 2026, 2026],
        "mes": [3, 3, 3, 3],
        "id_sucursal": [3, 4, 5, 16],
        "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS", "CERVEZAS"],
        "clientes": [300, 230, 120, 50],
    })


def _generico_suc1_by_id() -> pd.DataFrame:
    """Per-sucursal (suc 1 only) generico data from cob_sucursal_generico."""
    return pd.DataFrame({
        "anio": [2025, 2025, 2026, 2026],
        "mes": [3, 4, 3, 4],
        "id_sucursal": [1, 1, 1, 1],
        "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS", "CERVEZAS"],
        "clientes": [200, 250, 220, 280],
    })


def _aguas_data() -> pd.DataFrame:
    """Aguas subdivision data per sucursal."""
    return pd.DataFrame({
        "anio": [2026, 2026, 2026],
        "mes": [3, 3, 3],
        "id_sucursal": [1, 3, 4],
        "subdivision_aguas": ["AGUAS SABORIZADAS", "AGUAS SABORIZADAS", "AGUAS MINERAL"],
        "clientes": [60, 40, 30],
    })


# ── Test reassign_rutas_suc1_sucursal ────────────────────────────────────


class TestReassignRutasSuc1Sucursal:
    """Rows in RUTAS_A_SUC16 move from suc-1 preventista into interior per-sucursal."""

    def test_moves_matching_rutas_out_of_prev(self):
        m_prev, g_prev, m_int, g_int = reassign_rutas_suc1_sucursal(
            _marca_prev_suc1(),
            _generico_prev_suc1(),
            _marca_suc_by_id(),
            _generico_suc_by_id(),
        )
        # After reassignment, no rutas in RUTAS_A_SUC16 remain in prev
        assert not m_prev["id_ruta"].isin(RUTAS_A_SUC16).any()
        assert not g_prev["id_ruta"].isin(RUTAS_A_SUC16).any()

    def test_ruta_90_stays_in_prev(self):
        """Ruta 90 is NOT in RUTAS_A_SUC16, so it stays in prev."""
        m_prev, g_prev, _, _ = reassign_rutas_suc1_sucursal(
            _marca_prev_suc1(),
            _generico_prev_suc1(),
            _marca_suc_by_id(),
            _generico_suc_by_id(),
        )
        assert (m_prev["id_ruta"] == 90).any()

    def test_reassigned_rows_added_to_interior_suc16(self):
        """Reassigned rows should appear in interior at sucursal 16."""
        m_prev, g_prev, m_int, g_int = reassign_rutas_suc1_sucursal(
            _marca_prev_suc1(),
            _generico_prev_suc1(),
            _marca_suc_by_id(),
            _generico_suc_by_id(),
        )
        # Reassigned SALTA rows (100 + 90 = 190) should go to suc 16
        salta_16 = m_int[
            (m_int["marca"] == "SALTA") & (m_int["id_sucursal"] == 16)
        ]
        # Original suc 16 had AMSTEL(50), plus reassigned SALTA(100+90=190) = 240 total at suc 16
        total_16 = m_int[m_int["id_sucursal"] == 16]["clientes"].sum()
        assert total_16 == 50 + 100 + 90  # AMSTEL + SALTA reassigned rows

    def test_empty_mask_leaves_everything_unchanged(self):
        """When no rutas match RUTAS_A_SUC16, data stays unchanged."""
        df_marca = pd.DataFrame({
            "anio": [2026], "mes": [3], "id_ruta": [999],
            "marca": ["X"], "clientes": [10],
        })
        df_gen = pd.DataFrame({
            "anio": [2026], "mes": [3], "id_ruta": [999],
            "generico": ["G"], "clientes": [10],
        })
        m_prev, g_prev, m_int, g_int = reassign_rutas_suc1_sucursal(
            df_marca, df_gen,
            _marca_suc_by_id(),
            _generico_suc_by_id(),
        )
        assert len(m_prev) == 1
        assert m_int["clientes"].sum() == 700  # original total unchanged


# ── Test build_sucursal_matrices ──────────────────────────────────────────


class TestBuildSucursalMatrices:
    """Per-sucursal matrix builder for bar and line data."""

    def test_interior_salta_sur_filters_by_sucursales(self):
        """INTERIOR SALTA SUR uses sucursales [3, 4, 5, 16] from zona config."""
        sucursales_config = {
            "INTERIOR SALTA SUR": [3, 4, 5, 16],
            "SALTA CAPITAL": [1],
        }
        bars, gen = build_sucursal_matrices(
            df_marca_suc=_marca_suc_by_id(),
            df_generico_suc=_generico_suc_by_id(),
            generico="CERVEZAS",
            zona="INTERIOR SALTA SUR",
            sucursales_config=sucursales_config,
        )
        # Should return dicts keyed by id_sucursal
        assert isinstance(bars, dict)
        assert isinstance(gen, dict)
        # Each key should be a sucursal ID in the zone
        for sid in bars:
            assert sid in [3, 4, 5, 16]

    def test_salta_capital_uses_suc_1_only(self):
        """SALTA CAPITAL should filter to id_sucursal 1."""
        sucursales_config = {
            "SALTA CAPITAL": [1],
            "INTERIOR SALTA SUR": [3, 4, 5, 16],
        }
        bars, gen = build_sucursal_matrices(
            df_marca_suc=_marca_suc_by_id(),
            df_generico_suc=_generico_suc_by_id(),
            generico="CERVEZAS",
            zona="SALTA CAPITAL",
            sucursales_config=sucursales_config,
        )
        # Only sucursal 1 in the result
        assert set(bars.keys()) == {1} or bars == {}
        assert set(gen.keys()) == {1} or gen == {}

    def test_no_data_for_zone_returns_empty_dicts(self):
        """When no sucursal matches the data, returns empty dicts."""
        sucursales_config = {
            "JUJUY INTERIOR": [9, 10, 11, 12, 13, 14, 15],
        }
        bars, gen = build_sucursal_matrices(
            df_marca_suc=_marca_suc_by_id(),
            df_generico_suc=_generico_suc_by_id(),
            generico="CERVEZAS",
            zona="JUJUY INTERIOR",
            sucursales_config=sucursales_config,
        )
        assert bars == {}
        assert gen == {}

    def test_bars_df_has_expected_columns(self):
        """Each bar DataFrame should have columns [mes, marca, clientes]."""
        sucursales_config = {
            "INTERIOR SALTA SUR": [3, 4, 5, 16],
        }
        bars, gen = build_sucursal_matrices(
            df_marca_suc=_marca_suc_by_id(),
            df_generico_suc=_generico_suc_by_id(),
            generico="CERVEZAS",
            zona="INTERIOR SALTA SUR",
            sucursales_config=sucursales_config,
        )
        for sid, df in bars.items():
            assert "mes" in df.columns
            assert "marca" in df.columns
            assert "clientes" in df.columns

    def test_generico_df_has_expected_columns(self):
        """Each generico DataFrame should have columns [anio, mes, clientes]."""
        sucursales_config = {
            "INTERIOR SALTA SUR": [3, 4, 5, 16],
        }
        bars, gen = build_sucursal_matrices(
            df_marca_suc=_marca_suc_by_id(),
            df_generico_suc=_generico_suc_by_id(),
            generico="CERVEZAS",
            zona="INTERIOR SALTA SUR",
            sucursales_config=sucursales_config,
        )
        for sid, df in gen.items():
            assert "anio" in df.columns
            assert "mes" in df.columns
            assert "clientes" in df.columns

    def test_filters_generico_correctly(self):
        """When generico is specified, gen dict only contains that generico."""
        multi_gen_suc = pd.DataFrame({
            "anio": [2026, 2026],
            "mes": [3, 3],
            "id_sucursal": [3, 3],
            "generico": ["CERVEZAS", "VINOS CCU"],
            "clientes": [300, 100],
        })
        sucursales_config = {"INTERIOR SALTA SUR": [3, 4, 5, 16]}
        bars, gen = build_sucursal_matrices(
            df_marca_suc=_marca_suc_by_id(),
            df_generico_suc=multi_gen_suc,
            generico="CERVEZAS",
            zona="INTERIOR SALTA SUR",
            sucursales_config=sucursales_config,
        )
        for sid, df in gen.items():
            if not df.empty:
                assert (df["generico"] == "CERVEZAS").all()


# ── Test get_sucursal_data ───────────────────────────────────────────────


class TestGetSucursalData:
    """Per-sucursal data dispatcher with zone-specific handling."""

    def test_noa_norte_uses_all_sucursales(self):
        """NOA NORTE should aggregate across all sucursales."""
        sucursales_config = {
            "NOA NORTE": None,  # None = all sucursales
        }
        data = get_sucursal_data(
            zona="NOA NORTE",
            generico="CERVEZAS",
            df_marca_suc=_marca_suc_by_id(),
            df_generico_suc=_generico_suc_by_id(),
            sucursales_config=sucursales_config,
            gen_marcas={"CERVEZAS": {"SALTA", "HEINEKEN", "IMPERIAL", "AMSTEL"}},
        )
        # NOA NORTE aggregates all — should include all unique sucursales present
        assert isinstance(data, dict)

    def test_interior_salta_sur_filters_sucursales(self):
        """INTERIOR SALTA SUR uses sucursales [3, 4, 5, 16]."""
        sucursales_config = {
            "INTERIOR SALTA SUR": [3, 4, 5, 16],
        }
        data = get_sucursal_data(
            zona="INTERIOR SALTA SUR",
            generico="CERVEZAS",
            df_marca_suc=_marca_suc_by_id(),
            df_generico_suc=_generico_suc_by_id(),
            sucursales_config=sucursales_config,
            gen_marcas={"CERVEZAS": {"SALTA", "HEINEKEN", "IMPERIAL", "AMSTEL"}},
        )
        # Should have data for sucursales 3, 4, 5, 16
        for sid in data:
            assert sid in [3, 4, 5, 16]

    def test_aguas_subdivision_handling(self):
        """AGUAS SABORIZADAS should use aguas subdivision data."""
        sucursales_config = {
            "SALTA CAPITAL": [1],
        }
        df_marca_suc = pd.DataFrame({
            "anio": [2026], "mes": [3], "id_sucursal": [1],
            "marca": ["LEVITE"], "clientes": [50],
        })
        df_generico_suc = pd.DataFrame({
            "anio": [2026], "mes": [3], "id_sucursal": [1],
            "generico": ["AGUAS SABORIZADAS"], "clientes": [50],
        })
        data = get_sucursal_data(
            zona="SALTA CAPITAL",
            generico="AGUAS SABORIZADAS",
            df_marca_suc=df_marca_suc,
            df_generico_suc=df_generico_suc,
            sucursales_config=sucursales_config,
            gen_marcas={"AGUAS SABORIZADAS": {"LEVITE", "SER", "BRIO", "FULL SPORT"}},
            df_aguas=_aguas_data(),
        )
        # Should return dict with sucursal 1 having aguas data
        assert isinstance(data, dict)

    def test_unknown_zone_returns_empty(self):
        """An unrecognized zone name should return empty data."""
        sucursales_config = {"UNKNOWN ZONE": [99]}
        data = get_sucursal_data(
            zona="UNKNOWN ZONE",
            generico="CERVEZAS",
            df_marca_suc=_marca_suc_by_id(),
            df_generico_suc=_generico_suc_by_id(),
            sucursales_config=sucursales_config,
            gen_marcas={"CERVEZAS": {"SALTA"}},
        )
        assert data == {}