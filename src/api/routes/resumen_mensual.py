"""
Resumen Mensual API Routes - Endpoints para generacion de reportes de resumen mensual.
"""
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.services.resumen_mensual import ResumenMensualService, ResumenMensualConfig

router = APIRouter(prefix="/resumen-mensual", tags=["Resumen Mensual"])


# ── Modelos de request ──────────────────────────────────────────────────────

class ResumenMensualRequest(BaseModel):
    """
    Parametros para generar un reporte de resumen mensual.

    Genera un archivo Excel con una hoja por generico, con columnas de
    ventas de los ultimos dos dias habiles, total, tendencia al cierre,
    ventas del mes anterior y del mismo mes del ano anterior.
    """
    fecha_desde: str = Field(..., description="Fecha inicio (YYYY-MM-DD)", examples=["2026-02-01"])
    fecha_hasta: str = Field(..., description="Fecha fin (YYYY-MM-DD)", examples=["2026-02-28"])
    genericos: Optional[list[str]] = Field(None, description="Genericos a filtrar. None = todos.")
    nombre_archivo: Optional[str] = Field(None, description="Nombre base del archivo (sin extension).")
    con_objetivo: bool = Field(False, description="Incluir columnas de objetivo (requiere tabla en BD)")


# ── Modelos de response ─────────────────────────────────────────────────────

class ResumenMensualResponse(BaseModel):
    """Response para reporte de resumen mensual."""
    ruta_archivo: str
    registros_procesados: int
    sucursales: int
    genericos_incluidos: list[str]
    hojas: list[str]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _build_config(request: ResumenMensualRequest) -> ResumenMensualConfig:
    return ResumenMensualConfig(
        fecha_desde=request.fecha_desde,
        fecha_hasta=request.fecha_hasta,
        genericos=request.genericos,
        nombre_archivo=request.nombre_archivo,
        con_objetivo=request.con_objetivo,
    )


def _result_to_response(result) -> ResumenMensualResponse:
    return ResumenMensualResponse(
        ruta_archivo=str(result.ruta_archivo),
        registros_procesados=result.registros_procesados,
        sucursales=result.sucursales,
        genericos_incluidos=result.genericos_incluidos,
        hojas=result.hojas,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post(
    "/reporte",
    summary="Genera reporte de resumen mensual",
    description=(
        "Genera un reporte Excel con una hoja por generico y retorna metadata. "
        "Cada hoja incluye ventas de los ultimos dos dias habiles, total acumulado, "
        "tendencia al cierre, ventas del mes anterior y del mismo mes del ano anterior."
    ),
)
def generar_reporte(request: ResumenMensualRequest):
    try:
        service = ResumenMensualService()
        config = _build_config(request)
        result = service.generar_reporte(config)
        return _result_to_response(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/reporte/download",
    summary="Genera y descarga reporte de resumen mensual",
    description=(
        "Genera el reporte y lo retorna como descarga directa (.xlsx)."
    ),
)
def descargar_reporte(request: ResumenMensualRequest):
    try:
        service = ResumenMensualService()
        config = _build_config(request)
        result = service.generar_reporte(config)
        filename = Path(result.ruta_archivo).name
        return FileResponse(
            path=result.ruta_archivo,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
