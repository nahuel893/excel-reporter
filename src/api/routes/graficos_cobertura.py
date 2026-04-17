"""Graficos Cobertura API Routes — charts + xlsx + pptx generation."""
import io
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.services.graficos_cobertura.config import GraficosCoberturaConfig
from src.services.graficos_cobertura.service import GraficosCoberturaService


router = APIRouter(prefix="/graficos-cobertura", tags=["Graficos Cobertura"])


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
    archivo_marca_pptx: str
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
        archivo_marca_pptx=str(result.archivo_marca_pptx),
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
