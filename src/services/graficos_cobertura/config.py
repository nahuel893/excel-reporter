"""Configuration dataclass for graficos-cobertura service."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


def _parse_fecha(nombre: str, valor: str) -> datetime:
    try:
        return datetime.strptime(valor, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{nombre} debe tener formato YYYY-MM-DD (recibido: {valor!r})"
        ) from exc


@dataclass
class GraficosCoberturaConfig:
    """Config for graficos-cobertura (charts + xlsx + pptx).

    Years are derived from fecha_hasta.year so this config stays symmetric with
    the rest of the services (ventas, stock_diario, etc.) that take a date range.
    """

    fecha_desde: str
    fecha_hasta: str
    id_fuerza_ventas: int = 1
    nombre_archivo: str | None = None
    con_aguas: bool = True
    con_sucursal_slides: bool = False

    def __post_init__(self) -> None:
        desde = _parse_fecha("fecha_desde", self.fecha_desde)
        hasta = _parse_fecha("fecha_hasta", self.fecha_hasta)
        if desde > hasta:
            raise ValueError(
                f"fecha_desde ({self.fecha_desde}) no puede ser posterior a "
                f"fecha_hasta ({self.fecha_hasta})"
            )
        if self.id_fuerza_ventas < 1:
            raise ValueError(
                f"id_fuerza_ventas debe ser >= 1 (recibido: {self.id_fuerza_ventas})"
            )
        if self.con_sucursal_slides:
            logger.warning(
                "con_sucursal_slides=True but no sucursal mapping is provided — "
                "sucursal slides will use default zone-to-sucursal mapping"
            )

    @property
    def anio_actual(self) -> int:
        return datetime.strptime(self.fecha_hasta, "%Y-%m-%d").year

    @property
    def anio_anterior(self) -> int:
        return self.anio_actual - 1

    @property
    def anios_lineas(self) -> list[int]:
        """Three-year window for trend lines: [actual-2, actual-1, actual]."""
        actual = self.anio_actual
        return [actual - 2, actual - 1, actual]

    @property
    def anios_barras(self) -> tuple[int, int]:
        """Two-year tuple for YoY bar comparisons: (anterior, actual)."""
        return (self.anio_anterior, self.anio_actual)

    @property
    def mes_corte(self) -> int:
        """Cutoff month for bar series (month of fecha_hasta)."""
        return datetime.strptime(self.fecha_hasta, "%Y-%m-%d").month
