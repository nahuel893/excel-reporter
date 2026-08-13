"""Constants for the cobertura-cupos report: CCU generics and the zone map.

A "zona" is not always a sucursal. CASA CENTRAL is split by `id_ruta` into
VALLE SALTA, SUB DISTRIBUIDORES and the remainder, so a zone is defined as a
sucursal plus an optional route include/exclude list.

That split is the reason this report reads the per-preventista tables
(`gold.cob_preventista_*`) instead of the already-aggregated per-sucursal ones:
`cob_sucursal_*` has no `id_ruta`, so VALLE SALTA cannot be derived from it.
Aggregating routes reproduces the official sucursal figure to within 0.15%
(verified on 2026-07 and 2025-07 for the five CCU generics), and using one
single source for every zone keeps the numbers comparable across zones.
"""
from dataclasses import dataclass, field

# Los 5 genericos CCU. Coincide con los valores de `Calibre` del wapi.
GENERICOS_CCU: tuple[str, ...] = (
    "CERVEZAS",
    "AGUAS DANONE",
    "VINOS CCU",
    "SIDRAS Y LICORES",
    "PERNOD RICARD",
)

ID_SUCURSAL_CASA_CENTRAL = 1
ID_SUCURSAL_GUEMES = 16

# Rutas de las zonas virtuales de CASA CENTRAL. Se leen de config.settings para
# no duplicar la definicion: ahi es donde el resto del proyecto las mantiene.


def _rutas_zona_virtual(nombre: str) -> tuple[int, ...]:
    """Rutas de una zona virtual de config.settings, o () si no esta definida."""
    import config.settings as _settings

    zona = getattr(_settings, "ZONAS_VIRTUALES", {}).get(nombre, {})
    return tuple(zona.get("rutas", ()))


@dataclass(frozen=True)
class Zona:
    """Una zona del informe: sucursal, opcionalmente acotada por rutas.

    Attributes:
        nombre: Etiqueta de la zona (da nombre a la hoja).
        id_sucursal: Sucursal real. Junto con la ruta forma la clave compuesta —
            `id_ruta` se reusa entre sucursales, filtrar solo por ruta produce
            fan-out con datos de otras sucursales.
        rutas_incluidas: Si esta, la zona son SOLO esas rutas. None = la
            sucursal entera.
        rutas_excluidas: Rutas que se sacan de la zona. Se usa para el resto de
            CASA CENTRAL una vez separadas sus zonas virtuales.
    """
    nombre: str
    id_sucursal: int
    rutas_incluidas: tuple[int, ...] | None = None
    rutas_excluidas: tuple[int, ...] = field(default_factory=tuple)


def zonas_por_defecto() -> list[Zona]:
    """Las tres zonas del informe: CASA CENTRAL, VALLE SALTA y GUEMES.

    CASA CENTRAL sale por resta: es la sucursal 1 sin las rutas de sus zonas
    virtuales, igual que hace `_aplicar_zonas_virtuales` en el informe de
    ventas. Las tres zonas son DISJUNTAS — ningun cliente se cuenta dos veces
    entre ellas.
    """
    valle = _rutas_zona_virtual("VALLE SALTA")
    subdis = _rutas_zona_virtual("SUB DISTRIBUIDORES")
    return [
        Zona("CASA CENTRAL", ID_SUCURSAL_CASA_CENTRAL, rutas_excluidas=valle + subdis),
        Zona("VALLE SALTA", ID_SUCURSAL_CASA_CENTRAL, rutas_incluidas=valle),
        Zona("SUCURSAL GUEMES", ID_SUCURSAL_GUEMES),
    ]
