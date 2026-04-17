"""Tests for graficos-cobertura processor (pure pandas transformations)."""
import math

import pandas as pd
import pytest

from src.services.graficos_cobertura.processor import (
    build_gen_marcas_mapping,
    build_matrix_comparativo,
    build_matrix_generico_mensual,
    compute_yoy,
    filtrar_barras_mixtas,
    get_zona_data,
    reassign_rutas_suc1,
    select_marcas_para_grafico,
)


class TestReassignRutasSuc1:
    """RF-008: rows in RUTAS_A_SUC16 move from suc-1 preventista to interior."""

    def _base_marca_prev(self):
        # Rutas 85 (in RUTAS_A_SUC16) and 90 (not)
        return pd.DataFrame({
            "anio": [2026, 2026, 2025, 2026],
            "mes": [3, 3, 3, 3],
            "id_ruta": [85, 90, 85, 90],
            "marca": ["SALTA", "HEINEKEN", "SALTA", "HEINEKEN"],
            "clientes": [100, 200, 90, 180],
        })

    def _base_gen_prev(self):
        return pd.DataFrame({
            "anio": [2026, 2026],
            "mes": [3, 3],
            "id_ruta": [85, 90],
            "generico": ["CERVEZAS", "CERVEZAS"],
            "clientes": [100, 200],
        })

    def _base_marca_interior(self):
        return pd.DataFrame({
            "anio": [2026],
            "mes": [3],
            "marca": ["SALTA"],
            "clientes": [500],
        })

    def _base_gen_interior(self):
        return pd.DataFrame({
            "anio": [2026],
            "mes": [3],
            "generico": ["CERVEZAS"],
            "clientes": [500],
        })

    def test_moves_matching_rutas_out_of_prev(self):
        m_prev, g_prev, m_int, g_int = reassign_rutas_suc1(
            self._base_marca_prev(),
            self._base_gen_prev(),
            self._base_marca_interior(),
            self._base_gen_interior(),
        )
        # After reassignment, no rutas in RUTAS_A_SUC16 remain in prev
        assert not m_prev["id_ruta"].isin([85]).any()
        assert not g_prev["id_ruta"].isin([85]).any()
        # ruta 90 stays in prev (2 rows kept, both HEINEKEN 2026)
        assert (m_prev["id_ruta"] == 90).sum() == 2

    def test_sums_reassigned_rows_into_interior(self):
        m_prev, g_prev, m_int, g_int = reassign_rutas_suc1(
            self._base_marca_prev(),
            self._base_gen_prev(),
            self._base_marca_interior(),
            self._base_gen_interior(),
        )
        # interior[SALTA, 2026, 3] was 500 + 100 reassigned = 600
        salta_2026 = m_int[
            (m_int["marca"] == "SALTA") & (m_int["anio"] == 2026) & (m_int["mes"] == 3)
        ]
        assert salta_2026["clientes"].iloc[0] == 600

    def test_empty_mask_leaves_everything_unchanged(self):
        # All rutas are 999 (not in RUTAS_A_SUC16)
        df_marca = pd.DataFrame({
            "anio": [2026], "mes": [3], "id_ruta": [999],
            "marca": ["X"], "clientes": [10],
        })
        df_gen = pd.DataFrame({
            "anio": [2026], "mes": [3], "id_ruta": [999],
            "generico": ["G"], "clientes": [10],
        })
        m_prev, g_prev, m_int, g_int = reassign_rutas_suc1(
            df_marca, df_gen,
            self._base_marca_interior(),
            self._base_gen_interior(),
        )
        assert len(m_prev) == 1
        assert m_int["clientes"].iloc[0] == 500  # unchanged


class TestBuildGenMarcasMapping:
    """RF-009: mapping of generico -> set of marcas, plus aguas subdivisions."""

    def test_basic_mapping_from_articulos(self):
        df = pd.DataFrame({
            "generico": ["CERVEZAS", "CERVEZAS", "VINOS CCU", "VINOS CCU"],
            "marca": ["SALTA", "HEINEKEN", "LA CELIA", "GRAFFIGNA"],
        })
        result = build_gen_marcas_mapping(df)

        assert result["CERVEZAS"] == {"SALTA", "HEINEKEN"}
        assert result["VINOS CCU"] == {"LA CELIA", "GRAFFIGNA"}

    def test_includes_aguas_subdivisions(self):
        """AGUAS SABORIZADAS and AGUAS MINERAL must be added as pseudo-genericos."""
        df = pd.DataFrame({"generico": ["CERVEZAS"], "marca": ["SALTA"]})
        result = build_gen_marcas_mapping(df)

        assert "AGUAS SABORIZADAS" in result
        assert "AGUAS MINERAL" in result
        assert "LEVITE" in result["AGUAS SABORIZADAS"]
        assert "VILLA DEL SUR" in result["AGUAS MINERAL"]

    def test_empty_articulos_still_has_aguas(self):
        result = build_gen_marcas_mapping(pd.DataFrame({"generico": [], "marca": []}))
        assert "AGUAS SABORIZADAS" in result
        assert "AGUAS MINERAL" in result


class TestFiltrarBarrasMixtas:
    """RF-009: keep (actual, mes<=corte) + (anterior, mes>corte), drop 'anio'."""

    def test_selects_correct_rows(self):
        df = pd.DataFrame({
            "anio": [2026, 2026, 2025, 2025, 2024],
            "mes": [3, 5, 3, 5, 5],
            "marca": ["A", "B", "C", "D", "E"],
            "clientes": [1, 2, 3, 4, 5],
        })
        # actual=2026, anterior=2025, mes_corte=4
        # Keep: (2026, 3) and (2025, 5)
        # Drop: (2026, 5), (2025, 3), (2024, 5)
        result = filtrar_barras_mixtas(df, anio_actual=2026, anio_anterior=2025, mes_corte=4)
        assert len(result) == 2
        assert "anio" not in result.columns
        assert set(result["marca"]) == {"A", "D"}

    def test_boundary_mes_corte_inclusive_for_actual(self):
        """mes == mes_corte belongs to actual year."""
        df = pd.DataFrame({
            "anio": [2026, 2025],
            "mes": [4, 4],
            "marca": ["A", "B"],
            "clientes": [1, 2],
        })
        result = filtrar_barras_mixtas(df, 2026, 2025, 4)
        # 2026-mes4 kept (mes <= 4), 2025-mes4 dropped (not > 4)
        assert list(result["marca"]) == ["A"]

    def test_empty_df_returns_empty_without_anio_col(self):
        df = pd.DataFrame({"anio": [], "mes": [], "marca": [], "clientes": []})
        result = filtrar_barras_mixtas(df, 2026, 2025, 4)
        assert result.empty
        assert "anio" not in result.columns


class TestGetZonaData:
    """RF-009: dispatch per zone. Returns (df_bars, df_gen)."""

    def _dfs_dict(self):
        """Minimal fixture of all DataFrames needed by get_zona_data."""
        return {
            "df_marca_prev": pd.DataFrame({
                "mes": [3, 3],
                "marca": ["SALTA", "HEINEKEN"],
                "clientes": [50, 40],
            }),
            "df_gen_prev": pd.DataFrame({
                "anio": [2024, 2024],
                "mes": [3, 4],
                "generico": ["CERVEZAS", "CERVEZAS"],
                "clientes": [200, 300],
            }),
            "df_marca_interior": pd.DataFrame({
                "mes": [3],
                "marca": ["SALTA"],
                "clientes": [100],
            }),
            "df_gen_interior": pd.DataFrame({
                "anio": [2026],
                "mes": [3],
                "generico": ["CERVEZAS"],
                "clientes": [500],
            }),
            "df_marca_snorte": pd.DataFrame({
                "mes": [3],
                "marca": ["SALTA"],
                "clientes": [20],
            }),
            "df_gen_snorte": pd.DataFrame({
                "anio": [2026],
                "mes": [3],
                "generico": ["CERVEZAS"],
                "clientes": [80],
            }),
            "df_marca_jujuy": pd.DataFrame({
                "mes": [3],
                "marca": ["SALTA"],
                "clientes": [10],
            }),
            "df_gen_jujuy": pd.DataFrame({
                "anio": [2026],
                "mes": [3],
                "generico": ["CERVEZAS"],
                "clientes": [40],
            }),
            "df_marca_todas": pd.DataFrame({
                "mes": [3, 3],
                "marca": ["SALTA", "HEINEKEN"],
                "clientes": [180, 130],
            }),
            "df_gen_todas": pd.DataFrame({
                "anio": [2026, 2025],
                "mes": [3, 3],
                "generico": ["CERVEZAS", "CERVEZAS"],
                "clientes": [700, 600],
            }),
            "df_gen_suc1": pd.DataFrame({
                "anio": [2025, 2026],
                "mes": [3, 3],
                "generico": ["CERVEZAS", "CERVEZAS"],
                "clientes": [200, 250],
            }),
            "df_aguas": pd.DataFrame({
                "anio": [2026],
                "mes": [3],
                "id_sucursal": [1],
                "subdivision_aguas": ["AGUAS SABORIZADAS"],
                "clientes": [60],
            }),
        }

    def test_noa_norte_uses_todas(self):
        gen_marcas = {"CERVEZAS": {"SALTA", "HEINEKEN"}}
        df_bars, df_gen = get_zona_data(
            zona="NOA NORTE", generico="CERVEZAS",
            gen_marcas=gen_marcas,
            **self._dfs_dict(),
        )
        # Bars should be filtered to the marcas for CERVEZAS
        assert set(df_bars["marca"]) == {"SALTA", "HEINEKEN"}
        # Gen should come from df_gen_todas
        assert df_gen["clientes"].sum() == 1300

    def test_interior_salta_sur_uses_interior_dfs(self):
        gen_marcas = {"CERVEZAS": {"SALTA"}}
        df_bars, df_gen = get_zona_data(
            zona="INTERIOR SALTA SUR", generico="CERVEZAS",
            gen_marcas=gen_marcas,
            **self._dfs_dict(),
        )
        assert df_bars["clientes"].iloc[0] == 100
        assert df_gen["clientes"].iloc[0] == 500

    def test_jujuy_uses_jujuy_dfs(self):
        gen_marcas = {"CERVEZAS": {"SALTA"}}
        df_bars, df_gen = get_zona_data(
            zona="JUJUY INTERIOR", generico="CERVEZAS",
            gen_marcas=gen_marcas,
            **self._dfs_dict(),
        )
        assert df_bars["clientes"].iloc[0] == 10
        assert df_gen["clientes"].iloc[0] == 40

    def test_salta_capital_splits_pre_and_post_2025(self):
        """SALTA CAPITAL: anio<2025 from preventista, anio>=2025 from suc1."""
        gen_marcas = {"CERVEZAS": {"SALTA", "HEINEKEN"}}
        df_bars, df_gen = get_zona_data(
            zona="SALTA CAPITAL", generico="CERVEZAS",
            gen_marcas=gen_marcas,
            **self._dfs_dict(),
        )
        # Bars from preventista, grouped by (mes, marca)
        assert df_bars["clientes"].sum() == 90  # 50 + 40
        # Gen: 2024 from prev (500), 2025/2026 from suc1 (200+250=450) → 950
        assert df_gen["clientes"].sum() == 950

    def test_aguas_subdivision_filters_by_zone_sucs(self):
        """Aguas subdivision: filter df_aguas by subdivision + zone sucursal list."""
        gen_marcas = {"AGUAS SABORIZADAS": {"LEVITE"}}
        df_bars, df_gen = get_zona_data(
            zona="SALTA CAPITAL", generico="AGUAS SABORIZADAS",
            gen_marcas=gen_marcas,
            **self._dfs_dict(),
        )
        # df_aguas has 1 row with id_sucursal=1, subdivision=AGUAS SABORIZADAS
        # SALTA CAPITAL sucs = [1], so row is kept
        assert df_gen["clientes"].sum() == 60


class TestBuildMatrixGenericoMensual:
    """RF-009: pivot for excel mensual sheet."""

    def test_pivot_zona_mes_generico(self):
        """Build matrix: rows=zona, columns=(anio, mes), values=cantidad."""
        df = pd.DataFrame({
            "zona": ["NOA NORTE", "NOA NORTE", "SALTA CAPITAL"],
            "anio": [2026, 2026, 2026],
            "mes": [1, 2, 1],
            "clientes": [100, 150, 80],
        })
        result = build_matrix_generico_mensual(df, anios=[2025, 2026])
        # Index = zonas
        assert "NOA NORTE" in result.index
        # Columns cover (2025, 1..12) + (2026, 1..12) = 24 columns
        assert result.shape[1] == 24
        # Known cells
        assert result.loc["NOA NORTE", (2026, 1)] == 100
        assert result.loc["NOA NORTE", (2026, 2)] == 150
        # Missing cells filled with 0
        assert result.loc["NOA NORTE", (2025, 1)] == 0
        assert result.loc["SALTA CAPITAL", (2026, 2)] == 0

    def test_empty_df_returns_empty_matrix(self):
        df = pd.DataFrame({"zona": [], "anio": [], "mes": [], "clientes": []})
        result = build_matrix_generico_mensual(df, anios=[2025, 2026])
        assert result.empty


class TestBuildMatrixComparativo:
    """RF-009: pivot for comparativo sheet."""

    def test_comparativo_zona_anio_rows_marcas_cols(self):
        df = pd.DataFrame({
            "zona": ["NOA NORTE", "NOA NORTE", "NOA NORTE"],
            "anio": [2025, 2025, 2026],
            "marca": ["SALTA", "HEINEKEN", "SALTA"],
            "clientes": [100, 80, 150],
        })
        result = build_matrix_comparativo(df)
        # Rows = (zona, anio) combinations
        assert ("NOA NORTE", 2025) in result.index
        assert ("NOA NORTE", 2026) in result.index
        # Columns = marcas
        assert "SALTA" in result.columns
        assert "HEINEKEN" in result.columns
        # Cells
        assert result.loc[("NOA NORTE", 2025), "SALTA"] == 100
        assert result.loc[("NOA NORTE", 2026), "SALTA"] == 150

    def test_missing_marca_is_zero(self):
        df = pd.DataFrame({
            "zona": ["NOA NORTE"],
            "anio": [2025],
            "marca": ["SALTA"],
            "clientes": [100],
        })
        result = build_matrix_comparativo(df)
        # Only SALTA in data, no HEINEKEN to fill
        assert result.loc[("NOA NORTE", 2025), "SALTA"] == 100


class TestSelectMarcasParaGrafico:
    """RF-009: pick marcas for a chart — fixed list, aguas subdivision, or top-N."""

    def test_fixed_list_when_in_marcas_por_generico(self):
        """CERVEZAS uses MARCAS_POR_GENERICO fixed list."""
        df_bars = pd.DataFrame({
            "marca": ["SALTA", "HEINEKEN", "IMPERIAL", "OTRA"],
            "clientes": [100, 80, 60, 200],
        })
        result = select_marcas_para_grafico(
            generico="CERVEZAS",
            gen_marcas_set={"SALTA", "HEINEKEN", "IMPERIAL", "SCHNEIDER", "AMSTEL", "OTRA"},
            df_bars=df_bars,
        )
        # Fixed list from MARCAS_POR_GENERICO, filtered to those present
        assert result == ["SALTA", "HEINEKEN", "IMPERIAL"]

    def test_subdivision_list_for_aguas(self):
        """AGUAS SABORIZADAS uses SUBDIVISION_AGUAS list."""
        df_bars = pd.DataFrame({
            "marca": ["LEVITE", "SER"],
            "clientes": [100, 80],
        })
        result = select_marcas_para_grafico(
            generico="AGUAS SABORIZADAS",
            gen_marcas_set={"LEVITE", "SER", "BRIO", "FULL SPORT"},
            df_bars=df_bars,
        )
        assert result[:2] == ["LEVITE", "SER"]

    def test_top_n_by_clientes_when_unknown_generico(self):
        """Unknown generico: top-N by clientes desc."""
        df_bars = pd.DataFrame({
            "marca": ["A", "B", "C", "D"],
            "clientes": [50, 200, 100, 80],
        })
        result = select_marcas_para_grafico(
            generico="OTRO",
            gen_marcas_set={"A", "B", "C", "D"},
            df_bars=df_bars,
        )
        # Sorted by clientes desc
        assert result == ["B", "C", "D", "A"]


class TestComputeYoy:
    """RF-010: YoY formula with zero-handling."""

    def test_normal_yoy(self):
        """((100 - 80) / 80) * 100 = 25.0"""
        assert compute_yoy(actual=100, anterior=80) == pytest.approx(25.0)

    def test_negative_yoy(self):
        """((60 - 100) / 100) * 100 = -40.0"""
        assert compute_yoy(actual=60, anterior=100) == pytest.approx(-40.0)

    def test_zero_denominator_zero_numerator(self):
        """0/0 → 0.0 (no growth, no prior)."""
        assert compute_yoy(actual=0, anterior=0) == 0.0

    def test_zero_denominator_positive_numerator(self):
        """0/0 but actual>0 → 100.0 (new coverage)."""
        assert compute_yoy(actual=50, anterior=0) == 100.0

    def test_nan_inputs_treated_as_zero(self):
        assert compute_yoy(actual=float("nan"), anterior=80) == pytest.approx(-100.0)
        assert compute_yoy(actual=100, anterior=float("nan")) == 100.0

    def test_no_rounding_applied(self):
        """33.333... must be preserved (no int cast)."""
        result = compute_yoy(actual=400, anterior=300)
        assert result == pytest.approx(33.3333333, abs=0.001)
        assert isinstance(result, float)
