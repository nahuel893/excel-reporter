"""GraficosCoberturaService — orchestrates chart + xlsx + pptx generation."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.services.base_service import BaseService
from src.services.graficos_cobertura import chart_generator, excel_builder, pptx_builder
from src.services.graficos_cobertura.config import GraficosCoberturaConfig
from src.services.graficos_cobertura.constants import (
    GENERICOS_INCLUIDOS,
    MESES,
    PPTX_GENERICO_FILENAME,
    PNG_SUBDIR,
    SUCS_INTERIOR,
    SUCS_SALTA_NORTE,
    SUCS_JUJUY,
    XLSX_FILENAME,
    ZONA_SUCURSALES,
    ZONAS,
    ZONA_SLUGS,
    ZONA_SUCS_AGUAS,
)
from src.services.graficos_cobertura.constants import (
    MARCAS_POR_GENERICO,
    MAX_MARCAS,
    SUBDIVISION_AGUAS,
)
from src.services.graficos_cobertura.processor import (
    build_gen_marcas_mapping,
    filtrar_barras_mixtas,
    get_zona_data,
    reassign_rutas_suc1,
    select_marcas_para_grafico,
)

import pandas as pd  # noqa: E402  (re-imported for type hints; already imported above)


logger = logging.getLogger(__name__)


@dataclass
class GraficosCoberturaResult:
    """Artifacts produced by a graficos-cobertura run."""
    ruta_directorio: Path
    archivo_xlsx: Path
    archivo_generico_pptx: Path
    graficos_generados: int
    zonas_incluidas: list[str] = field(default_factory=list)
    genericos_incluidos: list[str] = field(default_factory=list)
    sucursal_pptx_paths: dict[str, Path] = field(default_factory=dict)


class GraficosCoberturaService(BaseService):
    """Generates the complete coverage visual package.

    Per run: ~50 PNGs + 1 XLSX + 2 PPTX decks under
    data/output/graficos-cobertura/{YYYY-MM}/.
    """

    SERVICE_SLUG = "graficos-cobertura"
    GRANULARITY = "month"

    def generar_reporte(
        self, config: GraficosCoberturaConfig
    ) -> GraficosCoberturaResult:
        run_dir, png_dir = self._resolve_output_dir(config.fecha_desde)
        data = self._fetch_data(config)
        data = self._apply_zonas(data)

        gen_marcas = build_gen_marcas_mapping(data["articulos"])

        # Keep marca data WITH anio column for comparison charts (needed before filtrar_barras_mixtas)
        comp_sources = self._build_comparacion_sources(data)
        graficos = self._build_comparacion_charts(comp_sources, gen_marcas, config, png_dir)

        # Filter bar-sources to the mixed (current-up-to-corte + prior-after-corte) window
        for key in (
            "marca_prev", "marca_interior", "marca_snorte", "marca_jujuy", "marca_todas",
        ):
            df = data[key]
            if key == "marca_prev":
                # For prev (still has id_ruta column), aggregate to (anio, mes, marca) first
                df = df.groupby(["anio", "mes", "marca"])["clientes"].sum().reset_index()
            data[key] = filtrar_barras_mixtas(
                df, config.anio_actual, config.anio_anterior, config.mes_corte
            )

        graficos += self._build_charts(data, gen_marcas, config, png_dir)

        # Build xlsx sheet DataFrames
        marca_por_zona_actual = self._fetch_marca_por_zona_anio(config, config.anio_actual)
        marca_por_zona_anterior = self._fetch_marca_por_zona_anio(config, config.anio_anterior)
        sheets_por_generico = self._build_sheets_por_generico(data, gen_marcas, config)
        sheets_mensuales = self._build_sheets_mensuales(
            data, gen_marcas, marca_por_zona_actual, config
        )
        sheet_comparativo = self._build_sheet_comparativo(
            marca_por_zona_anterior, marca_por_zona_actual, gen_marcas, config
        )

        xlsx_path = excel_builder.build_resumen_xlsx(
            output_path=run_dir / XLSX_FILENAME,
            sheets_por_generico=sheets_por_generico,
            sheets_mensuales=sheets_mensuales,
            sheet_comparativo=sheet_comparativo,
        )

        pptx_paths = pptx_builder.build_decks(
            png_dir=png_dir,
            output_dir=run_dir,
            con_aguas=config.con_aguas,
        )

        # Per-sucursal PPTX decks (optional)
        sucursal_pptx: dict[str, Path] = {}
        if config.con_sucursal_slides:
            sucursal_pptx = self._build_sucursal_decks(
                config, gen_marcas, data, png_dir, run_dir,
            )
            graficos += sucursal_pptx.get("__extra_pngs__", 0)  # type: ignore[arg-type]
            sucursal_pptx.pop("__extra_pngs__", None)

        return GraficosCoberturaResult(
            ruta_directorio=run_dir,
            archivo_xlsx=xlsx_path,
            archivo_generico_pptx=pptx_paths["generico"],
            graficos_generados=graficos,
            zonas_incluidas=list(ZONAS),
            genericos_incluidos=[g for g in GENERICOS_INCLUIDOS if g in gen_marcas],
            sucursal_pptx_paths=sucursal_pptx,
        )

    # ── Private helpers ──

    def _resolve_output_dir(self, fecha_desde: str) -> tuple[Path, Path]:
        run_dir = self._output_dir(fecha_desde)
        png_dir = run_dir / PNG_SUBDIR
        run_dir.mkdir(parents=True, exist_ok=True)
        png_dir.mkdir(parents=True, exist_ok=True)
        return run_dir, png_dir

    def _fetch_data(self, config: GraficosCoberturaConfig) -> dict:
        fv = config.id_fuerza_ventas
        anios_barras = list(config.anios_barras)
        anios_lineas = config.anios_lineas

        loader = self.data_loader
        return {
            "articulos": loader.get_articulos(),
            "marca_prev": loader.get_cobertura_graficos_marca_ruta(fv, anios_barras, 1),
            "gen_prev": loader.get_cobertura_graficos_generico_ruta(fv, anios_lineas, 1),
            "marca_interior": loader.get_cobertura_graficos_marca_sucursal(
                fv, anios_barras, sucursales=SUCS_INTERIOR
            ),
            "gen_interior": loader.get_cobertura_graficos_generico_sucursal(
                fv, anios_lineas, sucursales=SUCS_INTERIOR
            ),
            "marca_snorte": loader.get_cobertura_graficos_marca_sucursal(
                fv, anios_barras, sucursales=SUCS_SALTA_NORTE
            ),
            "gen_snorte": loader.get_cobertura_graficos_generico_sucursal(
                fv, anios_lineas, sucursales=SUCS_SALTA_NORTE
            ),
            "marca_jujuy": loader.get_cobertura_graficos_marca_sucursal(
                fv, anios_barras, sucursales=SUCS_JUJUY
            ),
            "gen_jujuy": loader.get_cobertura_graficos_generico_sucursal(
                fv, anios_lineas, sucursales=SUCS_JUJUY
            ),
            "marca_todas": loader.get_cobertura_graficos_marca_sucursal(fv, anios_barras),
            "gen_todas": loader.get_cobertura_graficos_generico_sucursal(fv, anios_lineas),
            "gen_suc1": loader.get_cobertura_graficos_generico_sucursal(
                fv, anios_lineas, sucursales=[1]
            ),
            "aguas": (
                loader.get_cobertura_graficos_aguas_sucursal(fv, anios_lineas)
                if config.con_aguas
                else pd.DataFrame(columns=[
                    "anio", "mes", "id_sucursal", "subdivision_aguas", "clientes"
                ])
            ),
        }

    def _apply_zonas(self, data: dict) -> dict:
        m_prev, g_prev, m_int, g_int = reassign_rutas_suc1(
            data["marca_prev"], data["gen_prev"],
            data["marca_interior"], data["gen_interior"],
        )
        data["marca_prev"] = m_prev
        data["gen_prev"] = g_prev
        data["marca_interior"] = m_int
        data["gen_interior"] = g_int
        return data

    def _build_charts(
        self,
        data: dict,
        gen_marcas: dict[str, set[str]],
        config: GraficosCoberturaConfig,
        png_dir: Path,
    ) -> int:
        """Render PNGs for every (zona, generico) pair with non-empty bar data.

        Returns the number of PNG files produced.
        """
        count = 0
        for zona in ZONAS:
            for generico in GENERICOS_INCLUIDOS:
                if generico not in gen_marcas:
                    continue
                if not config.con_aguas and generico in ("AGUAS SABORIZADAS", "AGUAS MINERAL"):
                    continue

                df_bars, df_gen = get_zona_data(
                    zona=zona, generico=generico, gen_marcas=gen_marcas,
                    df_marca_prev=data["marca_prev"],
                    df_gen_prev=data["gen_prev"],
                    df_marca_interior=data["marca_interior"],
                    df_gen_interior=data["gen_interior"],
                    df_marca_snorte=data["marca_snorte"],
                    df_gen_snorte=data["gen_snorte"],
                    df_marca_jujuy=data["marca_jujuy"],
                    df_gen_jujuy=data["gen_jujuy"],
                    df_marca_todas=data["marca_todas"],
                    df_gen_todas=data["gen_todas"],
                    df_gen_suc1=data["gen_suc1"],
                    df_aguas=data["aguas"],
                )

                if df_bars.empty or df_bars["clientes"].sum() == 0:
                    logger.info("Skipping %s / %s: no bar data", zona, generico)
                    continue

                marcas_plot = select_marcas_para_grafico(generico, gen_marcas[generico], df_bars)
                if not marcas_plot:
                    continue

                chart_generator.plot_cobertura_zona(
                    zona=zona, generico=generico,
                    marcas_plot=marcas_plot,
                    df_bars=df_bars, df_gen_lines=df_gen,
                    anios_lineas=config.anios_lineas,
                    output_dir=png_dir,
                )
                count += 1
        return count

    def _build_comparacion_sources(self, data: dict) -> dict[str, pd.DataFrame]:
        """Build zone-keyed marca DataFrames (with anio column) for comparacion charts.

        Comparacion needs (anio, mes, marca, clientes) — called BEFORE filtrar_barras_mixtas.
        """
        prev_grouped = (
            data["marca_prev"].groupby(["anio", "mes", "marca"])["clientes"]
            .sum().reset_index()
        )
        return {
            "NOA NORTE": data["marca_todas"],
            "SALTA CAPITAL": prev_grouped,
            "INTERIOR SALTA SUR": data["marca_interior"],
            "INTERIOR SALTA NORTE": data["marca_snorte"],
            "JUJUY INTERIOR": data["marca_jujuy"],
        }

    def _build_comparacion_charts(
        self,
        comp_sources: dict[str, pd.DataFrame],
        gen_marcas: dict[str, set[str]],
        config: GraficosCoberturaConfig,
        png_dir: Path,
    ) -> int:
        """Render comparacion_* PNGs: bar-per-marca comparing anio_anterior vs anio_actual at mes_corte."""
        count = 0
        for zona in ZONAS:
            src = comp_sources.get(zona)
            if src is None or src.empty:
                continue

            for generico in GENERICOS_INCLUIDOS:
                if generico not in gen_marcas:
                    continue
                if not config.con_aguas and generico in ("AGUAS SABORIZADAS", "AGUAS MINERAL"):
                    continue

                marcas_gen = gen_marcas[generico]
                df_prev = self._slice_marca_mes(src, marcas_gen, config.anio_anterior, config.mes_corte)
                df_act = self._slice_marca_mes(src, marcas_gen, config.anio_actual, config.mes_corte)

                if df_act.empty or df_act["clientes"].sum() == 0:
                    continue

                # Pick marcas_plot (fixed list | subdivision | top-N from anio_actual)
                if generico in MARCAS_POR_GENERICO:
                    marcas_plot = list(MARCAS_POR_GENERICO[generico])
                elif generico in SUBDIVISION_AGUAS:
                    marcas_plot = list(SUBDIVISION_AGUAS[generico])
                else:
                    marcas_plot = (
                        df_act.groupby("marca")["clientes"].sum()
                        .sort_values(ascending=False)
                        .head(MAX_MARCAS).index.tolist()
                    )

                # Filter marcas_plot to those with data in either year
                marcas_con_datos = set(df_prev["marca"].tolist()) | set(df_act["marca"].tolist())
                marcas_plot = [m for m in marcas_plot if m in marcas_con_datos]
                if not marcas_plot:
                    continue

                chart_generator.plot_comparacion_marca(
                    zona=zona, generico=generico,
                    marcas_plot=marcas_plot,
                    df_anterior=df_prev, df_actual=df_act,
                    mes_corte=config.mes_corte,
                    anio_actual=config.anio_actual,
                    anio_anterior=config.anio_anterior,
                    output_dir=png_dir,
                )
                count += 1
        return count

    @staticmethod
    def _slice_marca_mes(
        src: pd.DataFrame, marcas: set[str], anio: int, mes: int
    ) -> pd.DataFrame:
        """Filter a (anio, mes, marca, clientes) df to a specific (anio, mes) slice."""
        if src.empty:
            return pd.DataFrame(columns=["marca", "clientes"])
        filtered = src[
            (src["anio"] == anio) & (src["mes"] == mes) & (src["marca"].isin(marcas))
        ]
        return filtered[["marca", "clientes"]].groupby("marca", as_index=False)["clientes"].sum()

    # ── XLSX helpers ──────────────────────────────────────────────

    def _fetch_marca_por_zona_anio(
        self, config: GraficosCoberturaConfig, anio: int
    ) -> dict[str, pd.DataFrame]:
        """Fetch marca data for a single year across all 5 zones.

        Returns {zona: DataFrame[mes, marca, clientes]}. Equivalent to the
        standalone's fetch_marca_por_anio(anio).
        """
        fv = config.id_fuerza_ventas
        loader = self.data_loader
        zone_to_sucs: dict[str, list[int] | None] = {
            "SALTA CAPITAL": [1],
            "INTERIOR SALTA SUR": SUCS_INTERIOR,
            "INTERIOR SALTA NORTE": SUCS_SALTA_NORTE,
            "JUJUY INTERIOR": SUCS_JUJUY,
            "NOA NORTE": None,
        }
        out: dict[str, pd.DataFrame] = {}
        for zona, sucs in zone_to_sucs.items():
            df = loader.get_cobertura_graficos_marca_sucursal(fv, [anio], sucursales=sucs)
            # Drop anio since we filtered to one; match standalone's [mes, marca, clientes]
            out[zona] = df[["mes", "marca", "clientes"]].copy() if not df.empty else df
        return out

    @staticmethod
    def _marcas_order_for_generico(
        generico: str, gen_marcas: dict[str, set[str]]
    ) -> list[str]:
        """Column order for a per-generico sheet: fixed list, subdivision, or sorted."""
        if generico in MARCAS_POR_GENERICO:
            return list(MARCAS_POR_GENERICO[generico])
        if generico in SUBDIVISION_AGUAS:
            return list(SUBDIVISION_AGUAS[generico])
        return sorted(gen_marcas.get(generico, set()))

    @staticmethod
    def _all_marcas_order(gen_marcas: dict[str, set[str]]) -> list[str]:
        """All marcas in generico order — for mensual and comparativo sheets."""
        out: list[str] = []
        for generico in GENERICOS_INCLUIDOS:
            if generico in MARCAS_POR_GENERICO:
                out.extend(MARCAS_POR_GENERICO[generico])
            elif generico in SUBDIVISION_AGUAS:
                out.extend(SUBDIVISION_AGUAS[generico])
            elif generico in gen_marcas:
                out.extend(sorted(gen_marcas[generico]))
        return out

    def _build_sheets_por_generico(
        self,
        data: dict,
        gen_marcas: dict[str, set[str]],
        config: GraficosCoberturaConfig,
    ) -> dict[str, pd.DataFrame]:
        """One sheet per generico: rows=(zona, mes), cols=marcas + Total {anio} per anios_lineas."""
        sheets: dict[str, pd.DataFrame] = {}
        for generico in GENERICOS_INCLUIDOS:
            if generico not in gen_marcas:
                continue
            marcas_order = self._marcas_order_for_generico(generico, gen_marcas)

            rows: list[dict] = []
            for zona in ZONAS:
                df_bars, df_gen = get_zona_data(
                    zona=zona, generico=generico, gen_marcas=gen_marcas,
                    df_marca_prev=data["marca_prev"],
                    df_gen_prev=data["gen_prev"],
                    df_marca_interior=data["marca_interior"],
                    df_gen_interior=data["gen_interior"],
                    df_marca_snorte=data["marca_snorte"],
                    df_gen_snorte=data["gen_snorte"],
                    df_marca_jujuy=data["marca_jujuy"],
                    df_gen_jujuy=data["gen_jujuy"],
                    df_marca_todas=data["marca_todas"],
                    df_gen_todas=data["gen_todas"],
                    df_gen_suc1=data["gen_suc1"],
                    df_aguas=data["aguas"],
                )
                for mes in range(1, 13):
                    row: dict = {"Zona": zona, "Mes": MESES[mes - 1]}
                    for marca in marcas_order:
                        sub = df_bars[(df_bars["mes"] == mes) & (df_bars["marca"] == marca)]
                        val = int(sub["clientes"].sum()) if not sub.empty else 0
                        row[marca] = val if val > 0 else ""
                    for yr in config.anios_lineas:
                        sub = df_gen[(df_gen["anio"] == yr) & (df_gen["mes"] == mes)]
                        val = int(sub["clientes"].sum()) if not sub.empty else 0
                        row[f"Total {yr}"] = val if val > 0 else ""
                    rows.append(row)
            sheets[generico] = pd.DataFrame(rows)
        return sheets

    def _build_sheets_mensuales(
        self,
        data: dict,
        gen_marcas: dict[str, set[str]],
        marca_por_zona_actual: dict[str, pd.DataFrame],
        config: GraficosCoberturaConfig,
    ) -> dict[str, pd.DataFrame]:
        """One sheet per mes_con_datos: rows=zona, cols=genericos + all_marcas."""
        anio_actual = config.anio_actual

        # Pre-compute gen_data per zona x generico for anio_actual
        gen_cache: dict[str, dict[str, pd.DataFrame]] = {}
        for zona in ZONAS:
            gen_cache[zona] = {}
            for generico in GENERICOS_INCLUIDOS:
                if generico not in gen_marcas:
                    continue
                _, df_gen = get_zona_data(
                    zona=zona, generico=generico, gen_marcas=gen_marcas,
                    df_marca_prev=data["marca_prev"], df_gen_prev=data["gen_prev"],
                    df_marca_interior=data["marca_interior"], df_gen_interior=data["gen_interior"],
                    df_marca_snorte=data["marca_snorte"], df_gen_snorte=data["gen_snorte"],
                    df_marca_jujuy=data["marca_jujuy"], df_gen_jujuy=data["gen_jujuy"],
                    df_marca_todas=data["marca_todas"], df_gen_todas=data["gen_todas"],
                    df_gen_suc1=data["gen_suc1"], df_aguas=data["aguas"],
                )
                gen_cache[zona][generico] = df_gen[df_gen["anio"] == anio_actual] if not df_gen.empty else df_gen

        # Collect meses with data
        meses_con_datos: set[int] = set()
        for zona in ZONAS:
            z_df = marca_por_zona_actual.get(zona)
            if z_df is not None and not z_df.empty:
                meses_con_datos.update(z_df["mes"].unique().tolist())
            for df in gen_cache[zona].values():
                if not df.empty:
                    meses_con_datos.update(df["mes"].unique().tolist())

        all_marcas = self._all_marcas_order(gen_marcas)

        sheets: dict[str, pd.DataFrame] = {}
        for mes in sorted(meses_con_datos):
            sheet_name = f"{MESES[mes - 1]} {anio_actual}"
            rows: list[dict] = []
            for zona in ZONAS:
                row: dict = {"Zona": zona}
                for generico in GENERICOS_INCLUIDOS:
                    if generico not in gen_marcas:
                        continue
                    df_g = gen_cache[zona].get(generico, pd.DataFrame())
                    val = int(df_g[df_g["mes"] == mes]["clientes"].sum()) if not df_g.empty else 0
                    row[generico] = val if val > 0 else ""
                df_z = marca_por_zona_actual.get(zona, pd.DataFrame())
                for marca in all_marcas:
                    if df_z.empty:
                        row[marca] = ""
                        continue
                    sub = df_z[(df_z["mes"] == mes) & (df_z["marca"] == marca)]
                    val = int(sub["clientes"].sum()) if not sub.empty else 0
                    row[marca] = val if val > 0 else ""
                rows.append(row)
            sheets[sheet_name] = pd.DataFrame(rows)
        return sheets

    def _build_sheet_comparativo(
        self,
        marca_por_zona_anterior: dict[str, pd.DataFrame],
        marca_por_zona_actual: dict[str, pd.DataFrame],
        gen_marcas: dict[str, set[str]],
        config: GraficosCoberturaConfig,
    ) -> pd.DataFrame:
        """One row per (zona, anio): (anio_anterior, anio_actual) for mes_corte."""
        all_marcas = self._all_marcas_order(gen_marcas)
        rows: list[dict] = []
        for zona in ZONAS:
            for anio_label, src in (
                (config.anio_anterior, marca_por_zona_anterior),
                (config.anio_actual, marca_por_zona_actual),
            ):
                row: dict = {"Zona": zona, "Año": anio_label}
                df_z = src.get(zona, pd.DataFrame())
                for marca in all_marcas:
                    if df_z.empty:
                        row[marca] = ""
                        continue
                    sub = df_z[(df_z["mes"] == config.mes_corte) & (df_z["marca"] == marca)]
                    val = int(sub["clientes"].sum()) if not sub.empty else 0
                    row[marca] = val if val > 0 else ""
                rows.append(row)
        return pd.DataFrame(rows)

    # ── Per-sucursal helpers ────────────────────────────────────

    def _build_sucursal_decks(
        self,
        config: GraficosCoberturaConfig,
        gen_marcas: dict[str, set[str]],
        data: dict,
        png_dir: Path,
        run_dir: Path,
    ) -> dict[str, Path]:
        """Generate per-sucursal PPTX decks when con_sucursal_slides=True.

        For each (zona, generico, sucursal), creates a PPTX with:
          - Zone-level overview slides
          - Per-sucursal detail slides

        Returns {key: Path} where key is "{zona_slug}_suc{id}_{gen_slug}".
        """
        sucursal_decks: dict[str, Path] = {}
        extra_pngs = 0
        suc_dir = run_dir / "sucursales"
        suc_dir.mkdir(parents=True, exist_ok=True)

        sucursal_data = self._fetch_sucursal_data(config)

        for zona in ZONAS:
            if zona not in ZONA_SUCURSALES:
                continue
            zona_slug = ZONA_SLUGS[zona]

            for generico in GENERICOS_INCLUIDOS:
                if generico not in gen_marcas:
                    continue
                if not config.con_aguas and generico in ("AGUAS SABORIZADAS", "AGUAS MINERAL"):
                    continue

                # Zone-level PNG paths (already generated by _build_charts)
                gen_slug = generico.lower().replace(" ", "_").replace("+", "y")
                png_paths_zone: dict[str, Path] = {
                    "cobertura": png_dir / f"cobertura_{zona_slug}_{gen_slug}.png",
                }
                comp_png = png_dir / f"comparacion_{zona_slug}_{gen_slug}.png"
                if comp_png.exists():
                    png_paths_zone["comparacion"] = comp_png

                for suc_id, suc_nombre in ZONA_SUCURSALES[zona]:
                    # Generate per-sucursal charts
                    png_paths_sucursal: dict[str, Path] = {}
                    filename_suf = f"_suc{suc_id}"

                    # Build per-sucursal bar data
                    df_suc_bars = self._get_sucursal_bars(
                        zona, generico, gen_marcas, suc_id, sucursal_data,
                    )
                    if df_suc_bars.empty or df_suc_bars["clientes"].sum() == 0:
                        logger.info("Skipping %s / %s / suc %d: no data", zona, generico, suc_id)
                        continue

                    # Build per-sucursal line data (generico trend)
                    df_suc_gen = self._get_sucursal_gen(
                        zona, generico, suc_id, sucursal_data,
                    )

                    marcas_plot = select_marcas_para_grafico(generico, gen_marcas[generico], df_suc_bars)
                    if not marcas_plot:
                        continue

                    title_pfx = f"{suc_nombre} — "

                    # Cobertura chart
                    chart_generator.plot_cobertura_zona(
                        zona=zona,
                        generico=generico,
                        marcas_plot=marcas_plot,
                        df_bars=df_suc_bars,
                        df_gen_lines=df_suc_gen,
                        anios_lineas=config.anios_lineas,
                        output_dir=png_dir,
                        title_prefix=title_pfx,
                        filename_suffix=filename_suf,
                    )
                    png_paths_sucursal["cobertura"] = (
                        png_dir / f"cobertura_{zona_slug}{filename_suf}_{gen_slug}.png"
                    )
                    extra_pngs += 1

                    # Comparacion chart
                    marca_suc = sucursal_data["marca_sucursal"]
                    if not marca_suc.empty and "id_sucursal" in marca_suc.columns:
                        df_prev_suc = marca_suc[
                            (marca_suc["anio"] == config.anio_anterior)
                            & (marca_suc["mes"] == config.mes_corte)
                            & (marca_suc["id_sucursal"] == suc_id)
                            & (marca_suc["marca"].isin(gen_marcas[generico]))
                        ][["marca", "clientes"]].groupby("marca", as_index=False)["clientes"].sum()

                        df_act_suc = marca_suc[
                            (marca_suc["anio"] == config.anio_actual)
                            & (marca_suc["mes"] == config.mes_corte)
                            & (marca_suc["id_sucursal"] == suc_id)
                            & (marca_suc["marca"].isin(gen_marcas[generico]))
                        ][["marca", "clientes"]].groupby("marca", as_index=False)["clientes"].sum()
                    else:
                        df_prev_suc = pd.DataFrame(columns=["marca", "clientes"])
                        df_act_suc = pd.DataFrame(columns=["marca", "clientes"])

                    if not df_act_suc.empty and df_act_suc["clientes"].sum() > 0:
                        chart_generator.plot_comparacion_marca(
                            zona=zona,
                            generico=generico,
                            marcas_plot=marcas_plot,
                            df_anterior=df_prev_suc,
                            df_actual=df_act_suc,
                            mes_corte=config.mes_corte,
                            anio_actual=config.anio_actual,
                            anio_anterior=config.anio_anterior,
                            output_dir=png_dir,
                            title_prefix=title_pfx,
                            filename_suffix=filename_suf,
                        )
                        png_paths_sucursal["comparacion"] = (
                            png_dir / f"comparacion_{zona_slug}{filename_suf}_{gen_slug}.png"
                        )
                        extra_pngs += 1

                    # Build per-sucursal PPTX deck
                    deck_key = f"{zona_slug}_suc{suc_id}_{gen_slug}"
                    suc_slug = f"suc{suc_id}"
                    deck_path = suc_dir / f"cobertura_{zona_slug}_{suc_slug}.pptx"

                    pptx_builder.build_deck_sucursal(
                        zona_slug=zona_slug,
                        generico=generico,
                        sucursal_id=suc_id,
                        sucursal_nombre=suc_nombre,
                        png_paths_zone=png_paths_zone,
                        png_paths_sucursal=png_paths_sucursal,
                        output_path=deck_path,
                    )
                    sucursal_decks[deck_key] = deck_path

        sucursal_decks["__extra_pngs__"] = extra_pngs  # type: ignore[assignment]
        return sucursal_decks

    def _fetch_sucursal_data(self, config: GraficosCoberturaConfig) -> dict[str, pd.DataFrame]:
        """Fetch per-sucursal marca and generico data for all zones."""
        fv = config.id_fuerza_ventas
        loader = self.data_loader
        all_suc_ids: list[int] = []
        for sucs in ZONA_SUCURSALES.values():
            all_suc_ids.extend(suc_id for suc_id, _ in sucs)
        all_suc_ids = sorted(set(all_suc_ids))

        marca_suc = loader.get_cobertura_sucursal_marca(fv, list(config.anios_barras), all_suc_ids)
        gen_suc = loader.get_cobertura_sucursal_generico(fv, config.anios_lineas, all_suc_ids)

        return {
            "marca_sucursal": marca_suc,
            "gen_sucursal": gen_suc,
        }

    @staticmethod
    def _get_sucursal_bars(
        zona: str,
        generico: str,
        gen_marcas: dict[str, set[str]],
        suc_id: int,
        sucursal_data: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """Filter per-sucursal marca data to one sucursal + generico."""
        marcas_gen = gen_marcas.get(generico, set())
        df = sucursal_data["marca_sucursal"]
        if df.empty:
            return pd.DataFrame(columns=["mes", "marca", "clientes"])
        mask = (
            (df["id_sucursal"] == suc_id)
            & (df["marca"].isin(marcas_gen))
        )
        filtered = df[mask].copy()
        if filtered.empty:
            return pd.DataFrame(columns=["mes", "marca", "clientes"])
        return filtered.groupby(["mes", "marca"], as_index=False)["clientes"].sum()

    @staticmethod
    def _get_sucursal_gen(
        zona: str,
        generico: str,
        suc_id: int,
        sucursal_data: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """Filter per-sucursal generico data to one sucursal + generico."""
        df = sucursal_data["gen_sucursal"]
        if df.empty:
            return pd.DataFrame(columns=["anio", "mes", "clientes"])
        mask = (
            (df["id_sucursal"] == suc_id)
            & (df["generico"] == generico)
        )
        filtered = df[mask].copy()
        if filtered.empty:
            return pd.DataFrame(columns=["anio", "mes", "clientes"])
        return filtered.groupby(["anio", "mes"], as_index=False)["clientes"].sum()
