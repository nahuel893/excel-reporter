"""
Rebotes service - Bounce/rejection report by vendor and supervisor.
"""
from dataclasses import dataclass

from src.services.rebotes.processor import agregar_totales_supervisor, calcular_rebotes_vendedor
from src.services.rebotes.service import RebotesConfig, RebotesResult, RebotesService
from src.services.rebotes.constants import SUPERVISOR_VENDOR_MAP

__all__ = [
    "RebotesConfig",
    "RebotesResult",
    "RebotesService",
    "SUPERVISOR_VENDOR_MAP",
    "calcular_rebotes_vendedor",
    "agregar_totales_supervisor",
]