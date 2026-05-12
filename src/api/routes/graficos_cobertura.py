"""Graficos Cobertura API Routes — charts + xlsx + pptx generation + per-sucursal dashboard."""
import io
import logging
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.core.data_loader import DataLoader
from src.services.graficos_cobertura.config import GraficosCoberturaConfig
from src.services.graficos_cobertura.constants import (
    COLORES_MARCA,
    COLORES_LINEAS,
    FALLBACK_COLORS,
    GENERICOS_INCLUIDOS,
    MARCAS_POR_GENERICO,
    MESES,
    SUBDIVISION_AGUAS,
    ZONA_SLUGS,
    ZONA_SUCS_AGUAS,
    ZONAS,
)
from src.services.graficos_cobertura.processor import build_gen_marcas_mapping
from src.services.graficos_cobertura.processor_sucursal import (
    build_sucursal_matrices,
    get_sucursal_data,
)
from src.services.graficos_cobertura.service import GraficosCoberturaService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graficos-cobertura", tags=["Graficos Cobertura"])


# ── Dependency injection ────────────────────────────────────────────────────

def get_data_loader() -> DataLoader:
    """Provide a DataLoader instance (can be overridden in tests)."""
    return DataLoader()


def get_config(
    fecha_desde: str = Query(..., description="Fecha inicio (YYYY-MM-DD)"),
    fecha_hasta: str = Query(..., description="Fecha fin (YYYY-MM-DD)"),
) -> GraficosCoberturaConfig:
    """Build a GraficosCoberturaConfig from query params."""
    try:
        return GraficosCoberturaConfig(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── Pydantic response models ────────────────────────────────────────────────

class SucursalOut(BaseModel):
    """Sucursal with ID and nombre."""
    id: int
    nombre: str


class ZonaOut(BaseModel):
    """Zona with its name, slug and member sucursales."""
    nombre: str
    slug: str
    sucursales: list[SucursalOut]


class ZonasResponse(BaseModel):
    """Response for GET /zonas — list of zones with their sucursales."""
    zonas: list[ZonaOut]


class CoberturaSucursalResponse(BaseModel):
    """Response for GET /cobertura-sucursal — Chart.js data for a single sucursal."""
    sucursal: SucursalOut
    generico: str
    chart_cobertura: dict  # Chart.js config (bar+line combo)
    chart_comparacion: dict  # Chart.js config (side-by-side bar)


# ── Existing report endpoints ────────────────────────────────────────────────

class GraficosCoberturaRequest(BaseModel):
    """Parametros para generar graficos-cobertura."""
    fecha_desde: str = Field(..., description="Fecha inicio (YYYY-MM-DD)", examples=["2026-01-01"])
    fecha_hasta: str = Field(..., description="Fecha fin (YYYY-MM-DD)", examples=["2026-04-30"])
    id_fuerza_ventas: int = Field(1, description="ID de fuerza de ventas")
    nombre_archivo: Optional[str] = Field(None, description="Nombre base (informativo)")
    con_aguas: bool = Field(True, description="Incluir subdivisiones de AGUAS DANONE")


class GraficosCoberturaInfo(BaseModel):
    """Metadata de los artefactos generados."""
    ruta_directorio: str
    archivo_xlsx: str
    archivo_generico_pptx: str
    graficos_generados: int
    zonas_incluidas: list[str]
    genericos_incluidos: list[str]


@router.post("/reporte", response_model=GraficosCoberturaInfo, summary="Genera graficos cobertura")
def generar_reporte(request: GraficosCoberturaRequest) -> GraficosCoberturaInfo:
    try:
        config = GraficosCoberturaConfig(
            fecha_desde=request.fecha_desde,
            fecha_hasta=request.fecha_hasta,
            id_fuerza_ventas=request.id_fuerza_ventas,
            nombre_archivo=request.nombre_archivo,
            con_aguas=request.con_aguas,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        result = GraficosCoberturaService().generar_reporte(config)
    except Exception as exc:  # pragma: no cover — wraps DB/matplotlib errors
        raise HTTPException(status_code=500, detail=f"Error generando reporte: {exc}")

    return GraficosCoberturaInfo(
        ruta_directorio=str(result.ruta_directorio),
        archivo_xlsx=str(result.archivo_xlsx),
        archivo_generico_pptx=str(result.archivo_generico_pptx),
        graficos_generados=result.graficos_generados,
        zonas_incluidas=result.zonas_incluidas,
        genericos_incluidos=result.genericos_incluidos,
    )


@router.post("/reporte/download", summary="Genera y descarga graficos cobertura como ZIP")
def descargar_reporte(request: GraficosCoberturaRequest):
    try:
        config = GraficosCoberturaConfig(
            fecha_desde=request.fecha_desde,
            fecha_hasta=request.fecha_hasta,
            id_fuerza_ventas=request.id_fuerza_ventas,
            nombre_archivo=request.nombre_archivo,
            con_aguas=request.con_aguas,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        result = GraficosCoberturaService().generar_reporte(config)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Error generando reporte: {exc}")

    # Build in-memory ZIP preserving png/ subdir structure
    buf = io.BytesIO()
    run_dir: Path = result.ruta_directorio
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in run_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(run_dir)
                zf.write(file_path, arcname=str(arcname))
    buf.seek(0)

    filename = f"graficos-cobertura-{run_dir.name}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{quote(filename)}"'},
    )


# ── Per-sucursal dashboard endpoints ─────────────────────────────────────────


def _validate_zona(zona: str) -> str:
    """Validate zona exists, raising 404 if not found."""
    if zona not in ZONAS:
        raise HTTPException(
            status_code=404,
            detail=f"Zona '{zona}' not found. Valid zones: {ZONAS}",
        )
    return zona


def _validate_sucursal_in_zona(zona: str, id_sucursal: int, nombres: dict[int, str]) -> str:
    """Validate sucursal belongs to zona, returning its nombre.

    For NOA NORTE (None in ZONA_SUCS_AGUAS), any sucursal in DB is valid.
    Raises 404 if sucursal does not belong to the zone.
    """
    suc_ids = ZONA_SUCS_AGUAS.get(zona)
    if suc_ids is None:
        # NOA NORTE — all sucursales valid; just check it exists in DB
        if id_sucursal not in nombres:
            raise HTTPException(
                status_code=404,
                detail=f"Sucursal {id_sucursal} not found in database.",
            )
    elif id_sucursal not in suc_ids:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Sucursal {id_sucursal} does not belong to zona '{zona}'. "
                f"Valid sucursales: {suc_ids}"
            ),
        )
    return nombres[id_sucursal]


def _build_chartjs_cobertura(
    bars_data: dict[int, pd.DataFrame],
    gen_data: dict[int, pd.DataFrame],
    sucursal_id: int,
    generico: str,
    gen_marcas: dict[str, set[str]],
    config: GraficosCoberturaConfig,
) -> dict:
    """Build a Chart.js bar+line config for per-sucursal coverage."""
    df_bars = bars_data.get(sucursal_id, pd.DataFrame())
    df_gen = gen_data.get(sucursal_id, pd.DataFrame())

    # Determine which marcas to include
    marcas_del_generico = gen_marcas.get(generico, set())
    if generico in MARCAS_POR_GENERICO:
        marcas_plot = [m for m in MARCAS_POR_GENERICO[generico] if m in marcas_del_generico]
    else:
        # Top marcas by total clients
        if not df_bars.empty:
            top = (
                df_bars.groupby("marca")["clientes"]
                .sum()
                .sort_values(ascending=False)
                .head(10)
                .index.tolist()
            )
            marcas_plot = [m for m in top if m in marcas_del_generico]
        else:
            marcas_plot = sorted(marcas_del_generico)

    labels = MESES

    # Bar datasets (one per marca)
    datasets = []
    for i, marca in enumerate(marcas_plot):
        if df_bars.empty:
            data = [0] * 12
        else:
            marca_data = df_bars[df_bars["marca"] == marca]
            vals = []
            for mes in range(1, 13):
                row = marca_data[marca_data["mes"] == mes]
                vals.append(int(row["clientes"].sum()) if not row.empty else 0)
            data = vals

        color = COLORES_MARCA.get(marca, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])
        datasets.append({
            "type": "bar",
            "label": marca,
            "data": data,
            "backgroundColor": color,
            "borderColor": color,
        })

    # Line datasets (one per anio)
    anios_lineas = config.anios_lineas
    if not df_gen.empty:
        for yr in anios_lineas:
            year_data = df_gen[df_gen["anio"] == yr]
            vals = []
            for mes in range(1, 13):
                row = year_data[year_data["mes"] == mes]
                vals.append(int(row["clientes"].sum()) if not row.empty else None)

            line_color = COLORES_LINEAS.get(yr, "#888888")
            datasets.append({
                "type": "line",
                "label": str(yr),
                "data": vals,
                "borderColor": line_color,
                "backgroundColor": line_color,
                "fill": False,
                "tension": 0.1,
            })

    return {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": datasets,
        },
        "options": {
            "responsive": True,
            "scales": {
                "y": {"beginAtZero": True},
            },
        },
    }


def _build_chartjs_comparacion(
    df_marca_raw: pd.DataFrame,
    sucursal_id: int,
    generico: str,
    gen_marcas: dict[str, set[str]],
    config: GraficosCoberturaConfig,
) -> dict:
    """Build a Chart.js side-by-side bar config comparing anio_anterior vs anio_actual.

    Uses raw marca data (with anio column) filtered to the single sucursal.
    """
    # Filter to this sucursal and generico's marcas
    marcas_del_generico = gen_marcas.get(generico, set())
    if generico in MARCAS_POR_GENERICO:
        marcas_plot = [m for m in MARCAS_POR_GENERICO[generico] if m in marcas_del_generico]
    else:
        marcas_plot = sorted(marcas_del_generico)

    anio_anterior = config.anio_anterior
    anio_actual = config.anio_actual
    mes_corte = config.mes_corte

    # Filter to this sucursal
    if not df_marca_raw.empty and "id_sucursal" in df_marca_raw.columns:
        df_suc = df_marca_raw[df_marca_raw["id_sucursal"] == sucursal_id].copy()
    else:
        df_suc = df_marca_raw.copy()

    # Filter to this generico's marcas
    df_suc = df_suc[df_suc["marca"].isin(marcas_del_generico)].copy() if not df_suc.empty else df_suc

    if marcas_plot and not df_suc.empty:
        # Re-derive top marcas if not in MARCAS_POR_GENERICO
        if generico not in MARCAS_POR_GENERICO:
            top = (
                df_suc[df_suc["anio"] == anio_actual]
                .groupby("marca")["clientes"]
                .sum()
                .sort_values(ascending=False)
                .head(10)
                .index.tolist()
            )
            marcas_plot = [m for m in top if m in marcas_del_generico]

    labels = marcas_plot
    prev_vals = []
    actual_vals = []

    for marca in labels:
        if df_suc.empty:
            prev_vals.append(0)
            actual_vals.append(0)
        else:
            prev_row = df_suc[
                (df_suc["marca"] == marca) &
                (df_suc["anio"] == anio_anterior) &
                (df_suc["mes"] == mes_corte)
            ]
            actual_row = df_suc[
                (df_suc["marca"] == marca) &
                (df_suc["anio"] == anio_actual) &
                (df_suc["mes"] == mes_corte)
            ]
            prev_vals.append(int(prev_row["clientes"].sum()) if not prev_row.empty else 0)
            actual_vals.append(int(actual_row["clientes"].sum()) if not actual_row.empty else 0)

    color_anterior = COLORES_LINEAS.get(anio_anterior, "#E65100")
    color_actual = COLORES_LINEAS.get(anio_actual, "#2E7D32")
    mes_nombre = MESES[mes_corte - 1] if 1 <= mes_corte <= 12 else ""

    datasets = [
        {
            "label": str(anio_anterior),
            "data": prev_vals,
            "backgroundColor": color_anterior,
        },
        {
            "label": str(anio_actual),
            "data": actual_vals,
            "backgroundColor": color_actual,
        },
    ]

    return {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": datasets,
        },
        "options": {
            "responsive": True,
            "scales": {
                "y": {"beginAtZero": True},
            },
            "plugins": {
                "title": {
                    "display": True,
                    "text": f"Comparativo {mes_nombre} {anio_anterior} vs {anio_actual}",
                },
            },
        },
    }


@router.get("/zonas", response_model=ZonasResponse, summary="Zonas y sucursales")
def zonas(loader: DataLoader = Depends(get_data_loader)) -> ZonasResponse:
    """Return all zones with their member sucursales."""
    nombres = loader.get_sucursal_nombres()
    zonas_out: list[ZonaOut] = []

    for zona_name in ZONAS:
        suc_ids = ZONA_SUCS_AGUAS.get(zona_name)
        if suc_ids is None:
            # NOA NORTE — all sucursales from DB
            suc_ids = sorted(nombres.keys())

        sucursales = [
            SucursalOut(id=sid, nombre=nombres.get(sid, f"Sucursal {sid}"))
            for sid in suc_ids
        ]
        zonas_out.append(ZonaOut(
            nombre=zona_name,
            slug=ZONA_SLUGS[zona_name],
            sucursales=sucursales,
        ))

    return ZonasResponse(zonas=zonas_out)


@router.get(
    "/cobertura-sucursal",
    response_model=CoberturaSucursalResponse,
    summary="Cobertura por sucursal (Chart.js)",
)
def cobertura_sucursal(
    zona: str = Query(..., description="Nombre de la zona"),
    generico: str = Query(..., description="Generico a consultar"),
    id_sucursal: int = Query(..., description="ID de sucursal"),
    fecha_desde: str = Query(..., description="Fecha inicio (YYYY-MM-DD)"),
    fecha_hasta: str = Query(..., description="Fecha fin (YYYY-MM-DD)"),
    loader: DataLoader = Depends(get_data_loader),
    config: GraficosCoberturaConfig = Depends(get_config),
) -> CoberturaSucursalResponse:
    """Return Chart.js-compatible coverage data for a single sucursal within a zone."""
    # Validate zona
    _validate_zona(zona)

    # Validate sucursal
    nombres = loader.get_sucursal_nombres()
    suc_nombre = _validate_sucursal_in_zona(zona, id_sucursal, nombres)

    # Build per-sucursal data
    sucursales_config = dict(ZONA_SUCS_AGUAS)
    fv = config.id_fuerza_ventas
    anios_barras = list(config.anios_barras)
    anios_lineas = config.anios_lineas

    # Fetch marca and generico data for the sucursal's zone
    # Determine which sucursales to query
    suc_ids_for_query: list[int] | None = ZONA_SUCS_AGUAS.get(zona)
    # NOA NORTE has None → needs all sucursales from DB
    if suc_ids_for_query is None:
        suc_ids_for_query = sorted(nombres.keys())

    df_marca_suc = loader.get_cobertura_sucursal_marca(fv, anios_barras, suc_ids_for_query)
    df_generico_suc = loader.get_cobertura_sucursal_generico(fv, anios_lineas, suc_ids_for_query)

    # Fetch marca-prev data (SALTA CAPITAL only with id_ruta)
    df_marca_prev = None
    df_generico_prev = None
    df_generico_suc1 = None
    df_aguas = None

    if zona == "SALTA CAPITAL":
        df_marca_prev = loader.get_cobertura_graficos_marca_ruta(fv, anios_barras, 1)
        df_generico_prev = loader.get_cobertura_graficos_generico_ruta(fv, anios_lineas, 1)
        df_generico_suc1 = loader.get_cobertura_graficos_generico_sucursal(fv, anios_lineas, [1])

    if generico in SUBDIVISION_AGUAS:
        df_aguas = loader.get_cobertura_graficos_aguas_sucursal(fv, anios_lineas)

    # Get articulos for gen-marcas mapping
    articulos_df = loader.get_articulos()
    gen_marcas = build_gen_marcas_mapping(articulos_df)

    # Build per-sucursal matrices
    bars_data, gen_data = build_sucursal_matrices(
        df_marca_suc=df_marca_suc,
        df_generico_suc=df_generico_suc,
        generico=generico,
        zona=zona,
        sucursales_config=sucursales_config,
    )

    # Build Chart.js configs
    chart_cobertura = _build_chartjs_cobertura(
        bars_data=bars_data,
        gen_data=gen_data,
        sucursal_id=id_sucursal,
        generico=generico,
        gen_marcas=gen_marcas,
        config=config,
    )

    chart_comparacion = _build_chartjs_comparacion(
        df_marca_raw=df_marca_suc,
        sucursal_id=id_sucursal,
        generico=generico,
        gen_marcas=gen_marcas,
        config=config,
    )

    return CoberturaSucursalResponse(
        sucursal=SucursalOut(id=id_sucursal, nombre=suc_nombre),
        generico=generico,
        chart_cobertura=chart_cobertura,
        chart_comparacion=chart_comparacion,
    )