"""
Routes - Rutas de la API organizadas por servicio.
"""
from .ventas import router as ventas_router
from .resumen_mensual import router as resumen_mensual_router
from .mision_posible import router as mision_posible_router

__all__ = ["ventas_router", "resumen_mensual_router", "mision_posible_router"]
