"""
Mision Posible API Routes - Endpoints para reportes de cobertura.
"""
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.services.mision_posible import MisionPosibleService, MisionPosibleConfig, GrupoArticulos

router = APIRouter(prefix="/mision-posible", tags=["Mision Posible"])


# ── Modelos de request ──────────────────────────────────────────────────────

class GrupoArticulosSchema(BaseModel):
    """Define un grupo de articulos."""
    nombre: str = Field(..., description="Nombre de display del grupo")
    marca: str = Field(..., description="Marca en dim_articulo")
    filtro_descripcion: Optional[str] = Field(None, description="Substring para filtrar des_articulo con ILIKE")


class MisionPosibleRequest(BaseModel):
    """Parametros para generar un reporte Mision Posible."""
    periodo: str = Field(..., description="Periodo (YYYY-MM-DD, primer dia del mes)", examples=["2026-03-01"])
    grupos: list[GrupoArticulosSchema] = Field(..., description="Grupos de articulos a incluir")
    objetivos: dict[str, int] = Field(default_factory=dict, description="Objetivo total empresa por grupo")
    porcentajes_sucursal: dict[str, float] = Field(default_factory=dict, description="Porcentaje de cada sucursal")
    nombre_archivo: Optional[str] = Field(None, description="Nombre base del archivo (sin extension)")
    supervisores: Optional[dict[str, list[str]]] = Field(None, description="Supervisores y sus sucursales")


# ── Modelos de response ─────────────────────────────────────────────────────

class MisionPosibleResponse(BaseModel):
    """Response para reporte Mision Posible."""
    ruta_archivos: list[str]
    marcas_incluidas: list[str]
    hojas: list[str]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _build_config(request: MisionPosibleRequest) -> MisionPosibleConfig:
    grupos = [
        GrupoArticulos(
            nombre=g.nombre,
            marca=g.marca,
            filtro_descripcion=g.filtro_descripcion,
        )
        for g in request.grupos
    ]
    return MisionPosibleConfig(
        periodo=request.periodo,
        grupos=grupos,
        objetivos=request.objetivos,
        porcentajes_sucursal=request.porcentajes_sucursal,
        nombre_archivo=request.nombre_archivo,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post(
    "/reporte",
    summary="Genera reporte Mision Posible",
    description="Genera un reporte Excel de cobertura por marca y retorna metadata.",
)
def generar_reporte(request: MisionPosibleRequest):
    try:
        service = MisionPosibleService()
        config = _build_config(request)

        if request.supervisores:
            results = service.generar_reporte_supervisores(config, request.supervisores)
            all_paths = []
            for r in results:
                all_paths.extend(str(p) for p in r.ruta_archivos)
            return MisionPosibleResponse(
                ruta_archivos=all_paths,
                marcas_incluidas=results[0].marcas_incluidas if results else [],
                hojas=results[0].hojas if results else [],
            )

        result = service.generar_reporte(config)
        return MisionPosibleResponse(
            ruta_archivos=[str(p) for p in result.ruta_archivos],
            marcas_incluidas=result.marcas_incluidas,
            hojas=result.hojas,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/reporte/download",
    summary="Genera y descarga reporte Mision Posible",
    description="Genera el reporte y lo retorna como descarga directa (.xlsx o .zip).",
)
def descargar_reporte(request: MisionPosibleRequest):
    try:
        service = MisionPosibleService()
        config = _build_config(request)

        if request.supervisores:
            results = service.generar_reporte_supervisores(config, request.supervisores)
            buf = BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for r in results:
                    for p in r.ruta_archivos:
                        zf.write(p, Path(p).name)
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="application/zip",
                headers={"Content-Disposition": "attachment; filename=\"Mision Posible.zip\""},
            )

        result = service.generar_reporte(config)
        filepath = result.ruta_archivos[0]
        filename = Path(filepath).name
        return FileResponse(
            path=filepath,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
