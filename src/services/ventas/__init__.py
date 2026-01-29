"""
Modulo de servicio de ventas.

Proporciona funcionalidad para generar reportes de ventas
por sucursal, generico y marca.
"""
from src.services.ventas.service import VentasService, ReporteVentasConfig, ReporteVentasResult

__all__ = ["VentasService", "ReporteVentasConfig", "ReporteVentasResult"]
