"""
Ventas API Routes - Endpoints para generacion de reportes de ventas.
"""
import io
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.services.ventas import VentasService, ReporteVentasConfig

router = APIRouter(prefix="/ventas", tags=["Ventas"])


# ── Modelos de request ──────────────────────────────────────────────────────

class ReporteVentasRequest(BaseModel):
    """
    Parametros para generar un reporte de ventas.

    Si se incluye 'supervisores', se genera un archivo por supervisor
    filtrado a sus sucursales. En ese caso el endpoint /download
    retorna un ZIP con todos los archivos.
    """
    fecha_desde: str = Field(..., description="Fecha inicio (YYYY-MM-DD)", examples=["2026-01-01"])
    fecha_hasta: str = Field(..., description="Fecha fin (YYYY-MM-DD)", examples=["2026-01-31"])
    genericos: Optional[list[str]] = Field(None, description="Genericos a filtrar. None = todos.")
    nombre_archivo: Optional[str] = Field(None, description="Nombre base del archivo (sin extension). Se ignora cuando hay supervisores.")
    con_slicers: bool = Field(True, description="Agregar slicers (solo Windows con Excel instalado)")
    con_cobertura: bool = Field(True, description="Cruzar con tablas de cobertura")
    supervisores: Optional[dict[str, list[str]]] = Field(
        None,
        description="Mapeo supervisor -> lista de sucursales. Si se provee, genera un archivo por supervisor.",
        examples=[{"Juan Perez": ["Sucursal Norte", "Sucursal Sur"], "Maria Garcia": ["Sucursal Este"]}]
    )


# ── Modelos de response ─────────────────────────────────────────────────────

class ReporteInfo(BaseModel):
    """Informacion de un reporte generado."""
    ruta_archivo: str
    registros_ventas: int
    registros_procesados: int
    sucursales: int
    genericos_incluidos: list[str]
    hojas: list[str]
    slicers_agregados: bool
    supervisor: Optional[str] = None


class ReporteVentasResponse(BaseModel):
    """Response para reporte de sucursales completo (sin supervisores)."""
    reporte: ReporteInfo


class ReportesSupervisoresResponse(BaseModel):
    """Response para multiples reportes por supervisor."""
    reportes: list[ReporteInfo]
    total_supervisores: int


# ── Helpers ─────────────────────────────────────────────────────────────────

def _build_config(request: ReporteVentasRequest) -> ReporteVentasConfig:
    return ReporteVentasConfig(
        fecha_desde=request.fecha_desde,
        fecha_hasta=request.fecha_hasta,
        genericos=request.genericos,
        nombre_archivo=request.nombre_archivo,
        con_slicers=request.con_slicers,
        con_cobertura=request.con_cobertura,
    )


def _result_to_info(result) -> ReporteInfo:
    return ReporteInfo(
        ruta_archivo=str(result.ruta_archivo),
        registros_ventas=result.registros_ventas,
        registros_procesados=result.registros_procesados,
        sucursales=result.sucursales,
        genericos_incluidos=result.genericos_incluidos,
        hojas=result.hojas,
        slicers_agregados=result.slicers_agregados,
        supervisor=result.supervisor,
    )


def _zip_archivos(results: list) -> io.BytesIO:
    """Empaqueta multiples archivos Excel en un ZIP en memoria."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for result in results:
            ruta = Path(result.ruta_archivo)
            zf.write(ruta, ruta.name)
    buf.seek(0)
    return buf


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post(
    "/reporte",
    summary="Genera reporte de ventas",
    description=(
        "Genera uno o varios reportes Excel y retorna metadata. "
        "Si se incluye 'supervisores', retorna un reporte por supervisor."
    ),
)
def generar_reporte(request: ReporteVentasRequest):
    try:
        service = VentasService()
        config = _build_config(request)

        if request.supervisores:
            results = service.generar_reporte_supervisores(config, request.supervisores)
            return ReportesSupervisoresResponse(
                reportes=[_result_to_info(r) for r in results],
                total_supervisores=len(results),
            )

        result = service.generar_reporte(config)
        return ReporteVentasResponse(reporte=_result_to_info(result))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/reporte/download",
    summary="Genera y descarga reporte de ventas",
    description=(
        "Genera el reporte y lo retorna como descarga directa. "
        "Con supervisores retorna un archivo ZIP con todos los reportes."
    ),
)
def descargar_reporte(request: ReporteVentasRequest):
    try:
        service = VentasService()
        config = _build_config(request)

        if request.supervisores:
            results = service.generar_reporte_supervisores(config, request.supervisores)
            buf = _zip_archivos(results)
            filename = f"reportes_supervisores_{request.fecha_desde}_{request.fecha_hasta}.zip"
            return StreamingResponse(
                buf,
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
            )

        result = service.generar_reporte(config)
        filename = result.ruta_archivo.name
        return FileResponse(
            path=result.ruta_archivo,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/genericos", summary="Lista genericos disponibles")
def listar_genericos():
    """Retorna todos los genericos disponibles en la base de datos."""
    try:
        service = VentasService()
        genericos = service.listar_genericos_disponibles()
        return {"genericos": genericos, "total": len(genericos)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sucursales", summary="Lista sucursales disponibles")
def listar_sucursales():
    """Retorna todas las sucursales disponibles en la base de datos."""
    try:
        service = VentasService()
        sucursales = service.listar_sucursales()
        return {"sucursales": sucursales, "total": len(sucursales)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
