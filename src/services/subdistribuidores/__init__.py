"""
Subdistribuidores service - Reporte de ventas para subdistribuidores (ruta 93).
"""
from src.services.subdistribuidores.service import (
    SubdistribuidoresConfig,
    SubdistribuidoresResult,
    SubdistribuidoresService,
)
from src.services.subdistribuidores.processor import procesar_subdistribuidores

__all__ = [
    "SubdistribuidoresConfig",
    "SubdistribuidoresResult",
    "SubdistribuidoresService",
    "procesar_subdistribuidores",
]