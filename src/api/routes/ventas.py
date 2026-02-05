"""
Ventas API Routes - Endpoints para generacion de reportes de ventas.
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional
from pathlib import Path

from src.services.ventas import VentasService, ReporteVentasConfig

router = APIRouter(prefix="/ventas", tags=["Ventas"])


class ReporteVentasRequest(BaseModel):
    """Request body para generar reporte de ventas."""
    fecha_desde: str = Field(..., description="Fecha inicio (YYYY-MM-DD)", examples=["2026-01-01"])
    fecha_hasta: str = Field(..., description="Fecha fin (YYYY-MM-DD)", examples=["2026-01-31"])
    genericos: Optional[list[str]] = Field(None, description="Lista de genericos a filtrar")
    nombre_archivo: Optional[str] = Field(None, description="Nombre del archivo (sin extension)")
    con_slicers: bool = Field(True, description="Agregar slicers (solo Windows)")


class ReporteVentasResponse(BaseModel):
    """Response con informacion del reporte generado."""
    ruta_archivo: str
    registros_ventas: int
    registros_procesados: int
    sucursales: int
    genericos_incluidos: list[str]
    slicers_agregados: bool


@router.post("/reporte", response_model=ReporteVentasResponse)
def generar_reporte(request: ReporteVentasRequest):
    """
    Genera un reporte de ventas en Excel.

    Retorna la ruta del archivo generado y estadisticas del reporte.
    """
    try:
        service = VentasService()
        config = ReporteVentasConfig(
            fecha_desde=request.fecha_desde,
            fecha_hasta=request.fecha_hasta,
            genericos=request.genericos,
            nombre_archivo=request.nombre_archivo,
            con_slicers=request.con_slicers
        )
        result = service.generar_reporte(config)

        return ReporteVentasResponse(
            ruta_archivo=str(result.ruta_archivo),
            registros_ventas=result.registros_ventas,
            registros_procesados=result.registros_procesados,
            sucursales=result.sucursales,
            genericos_incluidos=result.genericos_incluidos,
            slicers_agregados=result.slicers_agregados
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reporte/download")
def generar_y_descargar_reporte(request: ReporteVentasRequest):
    """
    Genera un reporte de ventas y lo retorna como descarga.
    """
    try:
        service = VentasService()
        config = ReporteVentasConfig(
            fecha_desde=request.fecha_desde,
            fecha_hasta=request.fecha_hasta,
            genericos=request.genericos,
            nombre_archivo=request.nombre_archivo,
            con_slicers=request.con_slicers
        )
        result = service.generar_reporte(config)

        return FileResponse(
            path=result.ruta_archivo,
            filename=result.ruta_archivo.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/genericos")
def listar_genericos():
    """
    Lista los genericos disponibles en la base de datos.
    """
    try:
        service = VentasService()
        genericos = service.listar_genericos_disponibles()
        return {"genericos": genericos, "total": len(genericos)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sucursales")
def listar_sucursales():
    """
    Lista las sucursales disponibles.
    """
    try:
        service = VentasService()
        sucursales = service.listar_sucursales()
        return {"sucursales": sucursales, "total": len(sucursales)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
