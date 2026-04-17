"""GraficosCoberturaService — orchestrates chart + xlsx + pptx generation."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.settings import DATA_OUTPUT
from src.services.base_service import BaseService
from src.services.graficos_cobertura import chart_generator, excel_builder, pptx_builder
from src.services.graficos_cobertura.config import GraficosCoberturaConfig
from src.services.graficos_cobertura.constants import (
    GENERICOS_INCLUIDOS,
    MESES,
    PPTX_GENERICO_FILENAME,
    PPTX_MARCA_FILENAME,
    PNG_SUBDIR,
    XLSX_FILENAME,
    ZONAS,
    ZONA_SLUGS,
    ZONA_SUCS_AGUAS,
    SUCS_INTERIOR,
    SUCS_SALTA_NORTE,
    SUCS_JUJUY,
)
from src.services.graficos_cobertura.processor import (
    build_gen_marcas_mapping,
    filtrar_barras_mixtas,
    get_zona_data,
    reassign_rutas_suc1,
    select_marcas_para_grafico,
)


logger = logging.getLogger(__name__)


@dataclass
class GraficosCoberturaResult:
    """Artifacts produced by a graficos-cobertura run."""
    ruta_directorio: Path
    archivo_xlsx: Path
    archivo_marca_pptx: Path
    archivo_generico_pptx: Path
    graficos_generados: int
    zonas_incluidas: list[str] = field(default_factory=list)
    genericos_incluidos: list[str] = field(default_factory=list)


class GraficosCoberturaService(BaseService):
    """Generates the complete coverage visual package.

    Per run: ~50 PNGs + 1 XLSX + 2 PPTX decks in a timestamped subdir of
    data/output/graficos-cobertura/.
    """

    def generar_reporte(
        self, config: GraficosCoberturaConfig
    ) -> GraficosCoberturaResult:
        run_dir, png_dir = self._resolve_output_dir()
        data = self._fetch_data(config)
        data = self._apply_zonas(data)

        gen_marcas = build_gen_marcas_mapping(data["articulos"])

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

        graficos = self._build_charts(data, gen_marcas, config, png_dir)

        xlsx_path = excel_builder.build_resumen_xlsx(
            output_path=run_dir / XLSX_FILENAME,
            sheets_por_generico={},  # populated by later iterations if needed
            sheets_mensuales={},
            sheet_comparativo=None,
        )

        pptx_paths = pptx_builder.build_decks(
            png_dir=png_dir,
            output_dir=run_dir,
            con_aguas=config.con_aguas,
        )

        return GraficosCoberturaResult(
            ruta_directorio=run_dir,
            archivo_xlsx=xlsx_path,
            archivo_marca_pptx=pptx_paths["marca"],
            archivo_generico_pptx=pptx_paths["generico"],
            graficos_generados=graficos,
            zonas_incluidas=list(ZONAS),
            genericos_incluidos=[g for g in GENERICOS_INCLUIDOS if g in gen_marcas],
        )

    # ── Private helpers ──

    def _resolve_output_dir(self) -> tuple[Path, Path]:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        run_dir = DATA_OUTPUT / "graficos-cobertura" / ts
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
