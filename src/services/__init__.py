"""
Services module - Business logic for reports.

Contains specialized services for each report type:
- ventas: Sales reports by branch, generic and brand
"""
from src.services.ventas import VentasService, ReporteVentasConfig, ReporteVentasResult

__all__ = ["VentasService", "ReporteVentasConfig", "ReporteVentasResult"]
