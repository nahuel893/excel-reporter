"""
Modulo de servicio de cobertura.

Proporciona funcionalidad para generar reportes de cobertura
por preventista/ruta y generico/marca.
"""
from src.services.cobertura.service import (
    MESES_ATRAS_DEFAULT,
    TIPO_PREVENTISTA_GENERICO,
    TIPO_PREVENTISTA_MARCA,
    TIPO_SUCURSAL_MARCA,
    TIPOS_VALIDOS,
    CoberturaService,
    ReporteCoberturaConfig,
    ReporteCoberturaResult,
)

__all__ = [
    "CoberturaService",
    "ReporteCoberturaConfig",
    "ReporteCoberturaResult",
    "MESES_ATRAS_DEFAULT",
    "TIPOS_VALIDOS",
    "TIPO_PREVENTISTA_GENERICO",
    "TIPO_PREVENTISTA_MARCA",
    "TIPO_SUCURSAL_MARCA",
]
