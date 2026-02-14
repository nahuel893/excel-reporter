"""
Services module - Business logic for reports.

Contains specialized services for each report type:
- ventas: Sales reports by branch, generic and brand
- cobertura: Coverage reports by seller/branch and generic/brand
"""
from src.services.ventas import VentasService, ReporteVentasConfig, ReporteVentasResult
from src.services.cobertura import CoberturaService, ReporteCoberturaConfig, ReporteCoberturaResult

__all__ = [
    "VentasService", "ReporteVentasConfig", "ReporteVentasResult",
    "CoberturaService", "ReporteCoberturaConfig", "ReporteCoberturaResult",
]
