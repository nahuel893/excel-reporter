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


class ResumenMensualDatosRequest(BaseModel):
    """
    Parametros para el endpoint /datos (JSON, sin generacion de Excel).

    Superset de ResumenMensualRequest: agrega marca_splits, cupos_manuales y
    genericos_sin_prvta para control fino del reporte web.
    """
    fecha_desde: str = Field(..., description="Fecha inicio (YYYY-MM-DD)", examples=["2026-06-01"])
    fecha_hasta: str = Field(..., description="Fecha fin (YYYY-MM-DD)", examples=["2026-06-30"])
    genericos: Optional[list[str]] = Field(None, description="Genericos a filtrar. None = todos.")
    con_objetivo: bool = Field(True, description="Incluir columnas de objetivo (cupos).")
    marca_splits: Optional[dict[str, list[str]]] = Field(
        None,
        description=(
            "Splits de marca por generico. "
            "Ej: {'VINOS FINOS': ['QUARA']} genera secciones separadas."
        ),
    )
    cupos_manuales: Optional[dict[str, dict[str, float]]] = Field(
        None,
        description=(
            "Cupos hardcodeados {sucursal: {generico: cupo}} — "
            "agregados antes del merge con fact_cupos."
        ),
    )
    genericos_sin_prvta: Optional[list[str]] = Field(
        None,
        description=(
            "Genericos que excluyen documentos PRVTA. "
            "None → usa el default del servicio (['FRATELLI B'])."
        ),
    )


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


def _build_datos_config(request: ResumenMensualDatosRequest) -> ResumenMensualConfig:
    return ResumenMensualConfig(
        fecha_desde=request.fecha_desde,
        fecha_hasta=request.fecha_hasta,
        genericos=request.genericos,
        con_objetivo=request.con_objetivo,
        marca_splits=request.marca_splits,
        cupos_manuales=request.cupos_manuales,
        genericos_sin_prvta=request.genericos_sin_prvta,
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


@router.post(
    "/datos",
    summary="Datos del reporte de resumen mensual en JSON",
    description=(
        "Retorna los datos del reporte en formato JSON estructurado (sin generar Excel). "
        "Consumido por la vista web standalone en /resumen. "
        "Incluye meta (info_dias, nombres de columnas dinamicas) y "
        "sheets (una por generico, con secciones y filas con null-vs-zero preservado)."
    ),
)
def obtener_datos(request: ResumenMensualDatosRequest):
    try:
        service = ResumenMensualService()
        config = _build_datos_config(request)
        return service.generar_datos(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
