"""
Argentina/Salta public holidays for a given month.

Thin wrapper over the ``holidays`` library used to auto-populate the avance
report's ``dias`` sheet and to build a human-readable WhatsApp notification.

``subdiv="A"`` selects the Salta province (ISO 3166-2:AR code AR-A), so the
provincial holidays (e.g. Güemes, Virgen del Milagro) are included on top of
the national ones.
"""
from datetime import date

import holidays


def feriados_del_mes(anio: int, mes: int, subdiv: str = "A") -> list[tuple[date, str]]:
    """Return the holidays that fall in ``anio``/``mes``, sorted by date.

    Args:
        anio: Four-digit year.
        mes: Month number (1-12).
        subdiv: ISO subdivision code. Defaults to "A" (Salta province).

    Returns:
        A list of ``(date, motivo)`` tuples sorted ascending by date, where
        ``motivo`` is the holiday name as reported by the ``holidays`` library.
    """
    calendario = holidays.Argentina(subdiv=subdiv, years=anio)
    del_mes = [
        (fecha, motivo)
        for fecha, motivo in calendario.items()
        if fecha.year == anio and fecha.month == mes
    ]
    return sorted(del_mes, key=lambda item: item[0])


def formatear_notificacion_feriados(
    feriados: list[tuple[date, str]], periodo_label: str
) -> str:
    """Build the WhatsApp notification text for the applied holidays.

    Args:
        feriados: List of ``(date, motivo)`` tuples (as returned by
            :func:`feriados_del_mes`).
        periodo_label: Human-readable label identifying the report/period.

    Returns:
        A multi-line message listing each holiday, or a "sin feriados"
        message when the list is empty.
    """
    if not feriados:
        return f"Feriados aplicados en {periodo_label}: sin feriados este mes."

    lineas = [f"Feriados aplicados en {periodo_label}:"]
    for fecha, motivo in feriados:
        lineas.append(f"- {fecha:%d/%m}: {motivo}")
    return "\n".join(lineas)
