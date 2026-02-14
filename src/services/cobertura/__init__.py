"""
Modulo de servicio de cobertura.

Proporciona funcionalidad para generar reportes de cobertura
por preventista/sucursal y generico/marca.
"""
from src.services.cobertura.service import (
    CoberturaService,
    ReporteCoberturaConfig,
    ReporteCoberturaResult,
    TIPO_PREVENTISTA_GENERICO,
    TIPO_PREVENTISTA_MARCA,
    TIPO_SUCURSAL_MARCA,
)

__all__ = [
    "CoberturaService",
    "ReporteCoberturaConfig",
    "ReporteCoberturaResult",
    "TIPO_PREVENTISTA_GENERICO",
    "TIPO_PREVENTISTA_MARCA",
    "TIPO_SUCURSAL_MARCA",
]
