"""Matplotlib PNG chart generation (Agg backend, headless-safe).

MUST be imported before any other module does `import matplotlib.pyplot` so
the Agg backend is locked in. All plotting functions close their figures in
a try/finally to bound memory when generating ~50 PNGs per run.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

# pyplot and friends imported AFTER use("Agg") — order matters
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from pathlib import Path  # noqa: E402

from src.services.graficos_cobertura.constants import (  # noqa: E402
    COLORES_LINEAS,
    COLORES_MARCA,
    FALLBACK_COLORS,
    MARCADORES_LINEAS,
    MESES,
    ZONA_SLUGS,
)


def configure_matplotlib() -> None:
    """Ensure matplotlib is using the Agg backend (idempotent)."""
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg", force=True)


def _color_marca(marca: str, idx: int) -> str:
    return COLORES_MARCA.get(marca, FALLBACK_COLORS[idx % len(FALLBACK_COLORS)])


def _slug(text: str) -> str:
    """Normalize zona/generico names into filename-friendly slugs."""
    if text in ZONA_SLUGS:
        return ZONA_SLUGS[text]
    return text.lower().replace(" ", "_").replace("+", "y")


def _format_number(value: float) -> str:
    return f"{int(value):,}".replace(",", ".")


def _fmt_axis():
    return mticker.FuncFormatter(lambda v, _: _format_number(v))


def plot_cobertura_zona(
    zona: str,
    generico: str,
    marcas_plot: list[str],
    df_bars: pd.DataFrame,
    df_gen_lines: pd.DataFrame,
    anios_lineas: list[int],
    output_dir: Path,
    dpi: int = 160,
) -> Path:
    """Combo bar+line chart: bars = marcas × mes, lines = generico × anio.

    Saves to <output_dir>/cobertura_<zona_slug>_<gen_slug>.png and returns
    the Path. plt.close(fig) is called in finally — safe even on errors.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"cobertura_{_slug(zona)}_{_slug(generico)}.png"

    fig, ax = plt.subplots(figsize=(16, 7.5))
    try:
        fig.patch.set_facecolor("white")

        n = max(len(marcas_plot), 1)
        x = np.arange(12)
        total_width = 0.75
        width = total_width / n

        for i, marca in enumerate(marcas_plot):
            df_m = df_bars[df_bars["marca"] == marca]
            vals = pd.Series(0.0, index=range(1, 13))
            for _, row in df_m.iterrows():
                vals[int(row["mes"])] = row["clientes"]
            vals = vals.values
            offset = (i - n / 2 + 0.5) * width
            color = _color_marca(marca, i)
            bars = ax.bar(
                x + offset, vals, width,
                label=marca, color=color, alpha=0.88,
                edgecolor="white", linewidth=0.5, zorder=2,
            )
            # Etiquetas dentro de cada barra (rotadas 90°)
            for bar_obj, val in zip(bars, vals):
                if val > 0:
                    ax.text(
                        bar_obj.get_x() + bar_obj.get_width() / 2,
                        bar_obj.get_height() * 0.5,
                        _format_number(val),
                        ha="center", va="center",
                        fontsize=8, rotation=90, fontweight="bold",
                        color="#333333", zorder=5,
                    )

        ax2 = ax.twinx()
        line_data: dict[int, dict[int, float]] = {}
        all_line_vals: list[float] = []
        for yr in anios_lineas:
            df_line = df_gen_lines[df_gen_lines["anio"] == yr]
            if df_line.empty:
                continue
            series = df_line.groupby("mes")["clientes"].sum().reindex(range(1, 13))
            vals = series.values
            mask = ~pd.isna(vals)
            x_pts = np.where(mask)[0]
            y_pts = vals[mask].astype(float)
            if len(x_pts) == 0:
                continue
            ax2.plot(
                x_pts, y_pts,
                color=COLORES_LINEAS.get(yr, "#888888"),
                marker=MARCADORES_LINEAS.get(yr, "o"),
                markersize=7, linewidth=2.5, label=str(yr), zorder=4,
                markeredgecolor="white", markeredgewidth=0.8,
            )
            line_data[yr] = dict(zip(x_pts.tolist(), y_pts.tolist()))
            all_line_vals.extend(y_pts.tolist())

        # Anotaciones en puntos de línea con offset inteligente para evitar overlaps
        y_range = (max(all_line_vals) - min(all_line_vals)) if all_line_vals else 1
        min_gap = y_range * 0.06
        for xi in range(12):
            points = [(line_data[yr][xi], yr) for yr in line_data if xi in line_data[yr]]
            if not points:
                continue
            points.sort(key=lambda p: p[0])
            offsets: dict[int, int] = {}
            if len(points) == 1:
                offsets[points[0][1]] = 13
            else:
                y_offsets = [13] * len(points)
                for j in range(1, len(points)):
                    if points[j][0] - points[j - 1][0] < min_gap:
                        y_offsets[j - 1] = -16
                        y_offsets[j] = 16
                for j, (_, yr) in enumerate(points):
                    offsets[yr] = y_offsets[j]
            for yr, dy in offsets.items():
                yi = line_data[yr][xi]
                color = COLORES_LINEAS.get(yr, "#888888")
                va = "bottom" if dy > 0 else "top"
                ax2.annotate(
                    _format_number(yi),
                    (xi, yi), textcoords="offset points",
                    xytext=(0, dy),
                    ha="center", va=va,
                    fontsize=12, fontweight="bold", color=color,
                    zorder=5,
                )

        ax.set_title(
            f"{zona}  ({generico})",
            fontsize=17, fontweight="bold", color="#2E7D32", pad=18, loc="center",
        )
        ax.set_xticks(x)
        ax.set_xticklabels(MESES, fontsize=11, fontweight="medium")
        ax.yaxis.set_major_formatter(_fmt_axis())
        ax2.yaxis.set_major_formatter(_fmt_axis())
        ax.tick_params(axis="y", labelsize=9, colors="#555555")
        ax2.tick_params(axis="y", labelsize=9, colors="#555555")

        bar_max = df_bars["clientes"].max() if len(df_bars) else 1
        ax.set_ylim(0, (bar_max or 1) * 1.35)
        line_max = max(all_line_vals) if all_line_vals else 1
        ax2.set_ylim(0, line_max * 1.15)

        ax.grid(axis="y", alpha=0.25, color="#AAAAAA", linewidth=0.6, zorder=0)
        ax.set_axisbelow(True)
        for sp in ("top",):
            ax.spines[sp].set_visible(False)
            ax2.spines[sp].set_visible(False)

        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        if h1 or h2:
            ax.legend(
                h1 + h2, l1 + l2,
                loc="upper center", bbox_to_anchor=(0.5, -0.06),
                ncol=min(len(h1 + h2), 8), fontsize=9.5,
                frameon=True, fancybox=True,
                edgecolor="#DDDDDD", facecolor="#FAFAFA",
            )

        plt.tight_layout(rect=[0, 0.06, 1, 1])
        fig.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    finally:
        plt.close(fig)

    return out_path


def plot_comparacion_marca(
    zona: str,
    generico: str,
    marcas_plot: list[str],
    df_anterior: pd.DataFrame,
    df_actual: pd.DataFrame,
    mes_corte: int,
    anio_actual: int,
    anio_anterior: int,
    output_dir: Path,
    dpi: int = 160,
) -> Path:
    """Side-by-side bar chart comparing two years for the cutoff month.

    Saves to <output_dir>/comparacion_<zona_slug>_<gen_slug>.png.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"comparacion_{_slug(zona)}_{_slug(generico)}.png"

    fig, ax = plt.subplots(figsize=(16, 7.5))
    try:
        fig.patch.set_facecolor("white")
        x = np.arange(len(marcas_plot))
        width = 0.35

        vals_prev: list[int] = []
        vals_actual: list[int] = []
        for marca in marcas_plot:
            v_p = (
                df_anterior[df_anterior["marca"] == marca]["clientes"].sum()
                if not df_anterior.empty else 0
            )
            v_a = (
                df_actual[df_actual["marca"] == marca]["clientes"].sum()
                if not df_actual.empty else 0
            )
            vals_prev.append(int(v_p))
            vals_actual.append(int(v_a))

        color_prev = COLORES_LINEAS.get(anio_anterior, "#E65100")
        color_actual = COLORES_LINEAS.get(anio_actual, "#2E7D32")
        bars_prev = ax.bar(
            x - width / 2, vals_prev, width,
            label=str(anio_anterior), color=color_prev,
            alpha=0.88, edgecolor="white", linewidth=0.5, zorder=2,
        )
        bars_actual = ax.bar(
            x + width / 2, vals_actual, width,
            label=str(anio_actual), color=color_actual,
            alpha=0.88, edgecolor="white", linewidth=0.5, zorder=2,
        )

        # Etiquetas sobre cada barra
        for bars in (bars_prev, bars_actual):
            for bar_obj in bars:
                h = bar_obj.get_height()
                if h > 0:
                    ax.text(
                        bar_obj.get_x() + bar_obj.get_width() / 2,
                        h + 0.5,
                        _format_number(h),
                        ha="center", va="bottom",
                        fontsize=10, fontweight="bold",
                        color="#333333", zorder=5,
                    )

        mes_nombre = MESES[mes_corte - 1] if 1 <= mes_corte <= 12 else ""
        ax.set_title(
            f"{zona} — {generico}  (Comparativo {mes_nombre} {anio_anterior} vs {anio_actual})",
            fontsize=17, fontweight="bold", color="#2E7D32", pad=18, loc="center",
        )
        ax.set_xticks(x)
        ax.set_xticklabels(marcas_plot, fontsize=11, fontweight="medium")
        ax.yaxis.set_major_formatter(_fmt_axis())
        ax.tick_params(axis="y", labelsize=9, colors="#555555")

        max_val = max(max(vals_prev, default=1), max(vals_actual, default=1), 1)
        ax.set_ylim(0, max_val * 1.25)

        ax.grid(axis="y", alpha=0.25, color="#AAAAAA", linewidth=0.6, zorder=0)
        ax.set_axisbelow(True)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)

        ax.legend(
            loc="upper center", bbox_to_anchor=(0.5, -0.06),
            ncol=2, fontsize=10, frameon=True, fancybox=True,
            edgecolor="#DDDDDD", facecolor="#FAFAFA",
        )

        plt.tight_layout(rect=[0, 0.06, 1, 1])
        fig.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    finally:
        plt.close(fig)

    return out_path
