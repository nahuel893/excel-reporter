"""
Routes - Rutas de la API organizadas por servicio.
"""
from .ventas import router as ventas_router

__all__ = ["ventas_router"]
