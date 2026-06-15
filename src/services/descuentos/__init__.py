"""Descuentos CCU — reporte de descuentos (bonificaciones) por sucursal/genérico/marca."""
from src.services.descuentos.service import (
    DescuentosConfig,
    DescuentosResult,
    DescuentosService,
)

__all__ = ["DescuentosConfig", "DescuentosResult", "DescuentosService"]
