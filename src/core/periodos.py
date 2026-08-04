"""Period helpers: previous-month range and human month labels.

Reports that show two periods side by side (current month vs. the closed
previous month) must DERIVE the second window, never read it from the config.
The daily patches ``fecha_desde``/``fecha_hasta`` on every run but leaves the
rest of the config untouched, so a hardcoded month silently drifts out of the
period once the month rolls over — the exact failure mode behind the
schneider-710 capture, whose sheet name still points at a month that no longer
exists in the workbook.

Deriving from ``fecha_desde`` keeps name, folder and window in lockstep forever.
"""
from datetime import date, timedelta

# Uppercase Spanish month names, 1-indexed (index 0 unused).
MESES_ES: tuple[str, ...] = (
    "", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
)


def rango_mes_anterior(fecha: str) -> tuple[str, str]:
    """Return the full previous calendar month as ``(desde, hasta)`` ISO dates.

    ``hasta`` is INCLUSIVE (the real last day of that month), matching the
    convention used by ``_resolve_mes_a_hoy_range`` in the daily runner.
    Month length — including February in leap years — comes from the calendar,
    never from a lookup table.

    Raises:
        ValueError: if ``fecha`` is not an ISO date.
    """
    d = date.fromisoformat(fecha)
    ultimo = d.replace(day=1) - timedelta(days=1)
    return ultimo.replace(day=1).isoformat(), ultimo.isoformat()


def periodo_mes(fecha: str) -> str:
    """Return the first day of ``fecha``'s month — the key of the monthly tables.

    Las tablas `gold.cob_*` estan keyeadas por `periodo`, que es siempre el dia 1
    del mes. Un rango de dias se traduce a su mes para poder consultarlas.

    Raises:
        ValueError: if ``fecha`` is not an ISO date.
    """
    return date.fromisoformat(fecha).replace(day=1).isoformat()


def periodo_meses_atras(fecha: str, meses: int) -> str:
    """Return the first day of the month ``meses`` months before ``fecha``'s month.

    The generalization of :func:`periodo_mes` used by reports that compare more
    than two windows. ``meses=1`` is the previous month, ``meses=12`` the same
    month a year earlier, ``meses=13`` the month before that one. Arithmetic runs
    over a month ordinal, so year rollovers need no special case.

    Raises:
        ValueError: if ``fecha`` is not an ISO date or ``meses`` is negative.
    """
    if meses < 0:
        raise ValueError(f"meses debe ser >= 0, recibido {meses}")
    d = date.fromisoformat(fecha)
    ordinal = d.year * 12 + (d.month - 1) - meses
    if ordinal < 0:
        raise ValueError(f"meses={meses} cae antes del año 0 desde {fecha}")
    return date(ordinal // 12, ordinal % 12 + 1, 1).isoformat()


def etiqueta_mes(fecha: str) -> str:
    """Return the uppercase Spanish month label, e.g. ``"JULIO 2026"``.

    Raises:
        ValueError: if ``fecha`` is not an ISO date.
    """
    d = date.fromisoformat(fecha)
    return f"{MESES_ES[d.month]} {d.year}"
