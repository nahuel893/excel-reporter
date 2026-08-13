"""Cobertura de aguas por sucursal y marca — mensual, acumulado y pesos."""
from .constants import CONCEPTOS, MARCAS_AGUAS, TOTAL_AGUAS
from .service import (
    CoberturaAguasConfig,
    CoberturaAguasResult,
    CoberturaAguasService,
)

__all__ = [
    "CONCEPTOS",
    "MARCAS_AGUAS",
    "TOTAL_AGUAS",
    "CoberturaAguasConfig",
    "CoberturaAguasResult",
    "CoberturaAguasService",
]
