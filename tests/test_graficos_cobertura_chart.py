"""Tests for chart_generator — smoke tests for PNG rendering + matplotlib hygiene."""
import matplotlib
import pandas as pd
import pytest

from src.services.graficos_cobertura import chart_generator
from src.services.graficos_cobertura.chart_generator import (
    configure_matplotlib,
    plot_cobertura_zona,
    plot_comparacion_marca,
)


class TestMatplotlibBackend:
    """RF-011, RF-012, RNF-001: Agg backend + plt.close hygiene."""

    def test_backend_is_agg_after_import(self):
        """Module import must set Agg backend (headless-safe)."""
        assert matplotlib.get_backend().lower() == "agg"

    def test_configure_matplotlib_idempotent(self):
        """configure_matplotlib() can be called many times without error."""
        configure_matplotlib()
        configure_matplotlib()
        assert matplotlib.get_backend().lower() == "agg"


class TestPlotCoberturaZona:
    """RF-013: plot_cobertura_zona produces a valid PNG at output_dir."""

    def _df_bars(self):
        return pd.DataFrame({
            "mes": [1, 2, 3, 1, 2, 3],
            "marca": ["SALTA", "SALTA", "SALTA", "HEINEKEN", "HEINEKEN", "HEINEKEN"],
            "clientes": [100, 150, 200, 80, 90, 120],
        })

    def _df_gen_lines(self):
        return pd.DataFrame({
            "anio": [2024, 2024, 2025, 2025, 2026, 2026],
            "mes": [1, 2, 1, 2, 1, 2],
            "clientes": [500, 550, 600, 650, 700, 750],
        })

    def test_creates_png_file(self, tmp_path):
        import matplotlib.pyplot as plt
        plt.close("all")

        out = plot_cobertura_zona(
            zona="NOA NORTE", generico="CERVEZAS",
            marcas_plot=["SALTA", "HEINEKEN"],
            df_bars=self._df_bars(),
            df_gen_lines=self._df_gen_lines(),
            anios_lineas=[2024, 2025, 2026],
            output_dir=tmp_path,
        )

        assert out.exists()
        assert out.suffix == ".png"
        # PNG magic bytes
        with open(out, "rb") as f:
            assert f.read(8)[:4] == b"\x89PNG"
        # No figures leaked
        assert plt.get_fignums() == []

    def test_filename_uses_slug(self, tmp_path):
        out = plot_cobertura_zona(
            zona="SALTA CAPITAL", generico="AGUAS SABORIZADAS",
            marcas_plot=["LEVITE"],
            df_bars=pd.DataFrame({"mes": [1], "marca": ["LEVITE"], "clientes": [50]}),
            df_gen_lines=pd.DataFrame({"anio": [2026], "mes": [1], "clientes": [60]}),
            anios_lineas=[2024, 2025, 2026],
            output_dir=tmp_path,
        )
        assert out.name == "cobertura_salta_capital_aguas_saborizadas.png"

    def test_empty_bars_does_not_raise(self, tmp_path):
        import matplotlib.pyplot as plt
        plt.close("all")

        out = plot_cobertura_zona(
            zona="NOA NORTE", generico="CERVEZAS",
            marcas_plot=[],
            df_bars=pd.DataFrame({"mes": [], "marca": [], "clientes": []}),
            df_gen_lines=pd.DataFrame({"anio": [], "mes": [], "clientes": []}),
            anios_lineas=[2024, 2025, 2026],
            output_dir=tmp_path,
        )
        assert out.exists()
        assert plt.get_fignums() == []


class TestPlotComparacionMarca:
    """RF-014: plot_comparacion_marca produces a valid PNG."""

    def test_creates_png_file(self, tmp_path):
        import matplotlib.pyplot as plt
        plt.close("all")

        df_anterior = pd.DataFrame({
            "marca": ["SALTA", "HEINEKEN"],
            "clientes": [100, 80],
        })
        df_actual = pd.DataFrame({
            "marca": ["SALTA", "HEINEKEN"],
            "clientes": [150, 90],
        })
        out = plot_comparacion_marca(
            zona="NOA NORTE", generico="CERVEZAS",
            marcas_plot=["SALTA", "HEINEKEN"],
            df_anterior=df_anterior,
            df_actual=df_actual,
            mes_corte=3,
            anio_actual=2026, anio_anterior=2025,
            output_dir=tmp_path,
        )

        assert out.exists()
        with open(out, "rb") as f:
            assert f.read(8)[:4] == b"\x89PNG"
        assert plt.get_fignums() == []

    def test_filename_has_comparacion_prefix(self, tmp_path):
        out = plot_comparacion_marca(
            zona="JUJUY INTERIOR", generico="VINOS CCU",
            marcas_plot=["LA CELIA"],
            df_anterior=pd.DataFrame({"marca": ["LA CELIA"], "clientes": [10]}),
            df_actual=pd.DataFrame({"marca": ["LA CELIA"], "clientes": [15]}),
            mes_corte=3, anio_actual=2026, anio_anterior=2025,
            output_dir=tmp_path,
        )
        assert out.name == "comparacion_jujuy_interior_vinos_ccu.png"

    def test_empty_dfs_do_not_raise(self, tmp_path):
        import matplotlib.pyplot as plt
        plt.close("all")

        out = plot_comparacion_marca(
            zona="NOA NORTE", generico="CERVEZAS",
            marcas_plot=["SALTA"],
            df_anterior=pd.DataFrame({"marca": [], "clientes": []}),
            df_actual=pd.DataFrame({"marca": [], "clientes": []}),
            mes_corte=3, anio_actual=2026, anio_anterior=2025,
            output_dir=tmp_path,
        )
        assert out.exists()
        assert plt.get_fignums() == []
