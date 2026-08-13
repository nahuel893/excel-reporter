"""Cobertura y cupos: cobertura por generico y marca de los genericos CCU,
abierta por zona, con una columna vacia para cargar el cupo a mano.
"""
from src.services.cobertura_cupos.constants import (
    GENERICOS_CCU,
    Zona,
    zonas_por_defecto,
)
from src.services.cobertura_cupos.service import (
    CoberturaCuposConfig,
    CoberturaCuposResult,
    CoberturaCuposService,
)

__all__ = [
    "CoberturaCuposService",
    "CoberturaCuposConfig",
    "CoberturaCuposResult",
    "GENERICOS_CCU",
    "Zona",
    "zonas_por_defecto",
]
