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


def rango_mes(fecha: str) -> tuple[str, str]:
    """Return the whole calendar month containing ``fecha`` as ``(desde, hasta)``.

    ``hasta`` is INCLUSIVE (the real last day), same convention as
    :func:`rango_mes_anterior`. Month length — February in leap years included
    — comes from the calendar, never from a lookup table.

    Composes with :func:`periodo_meses_atras` so a report can derive any
    historical window from the one date its config already carries:
    ``rango_mes(periodo_meses_atras(fecha_hasta, 12))`` is the same month a
    year earlier.

    Raises:
        ValueError: if ``fecha`` is not an ISO date.
    """
    d = date.fromisoformat(fecha)
    primero = d.replace(day=1)
    siguiente = (primero + timedelta(days=32)).replace(day=1)
    return primero.isoformat(), (siguiente - timedelta(days=1)).isoformat()


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


def meses_abarcados(fecha_desde: str, fecha_hasta: str) -> int:
    """Cantidad de meses calendario que toca el rango, ambos extremos inclusive.

    ``2026-06-01`` a ``2026-08-10`` son 3 meses (junio, julio y agosto), aunque
    agosto este incompleto. Sirve para que un informe abierto por mes derive
    cuantas columnas necesita del rango que ya trae el config, sin agregar un
    campo aparte que despues haya que mantener sincronizado.

    Raises:
        ValueError: si alguna fecha no es ISO, o si ``hasta`` es anterior a
            ``desde`` (un rango invertido es un error de config, no un rango
            vacio que convenga tapar).
    """
    d = date.fromisoformat(fecha_desde)
    h = date.fromisoformat(fecha_hasta)
    if h < d:
        raise ValueError(f"rango invertido: {fecha_desde} .. {fecha_hasta}")
    return (h.year * 12 + h.month) - (d.year * 12 + d.month) + 1


def etiqueta_mes(fecha: str) -> str:
    """Return the uppercase Spanish month label, e.g. ``"JULIO 2026"``.

    Raises:
        ValueError: if ``fecha`` is not an ISO date.
    """
    d = date.fromisoformat(fecha)
    return f"{MESES_ES[d.month]} {d.year}"


# --- Ventanas relativas ----------------------------------------------------
#
# Vivian en scripts/run_daily.py, donde solo las veia el daily. Un config que
# se corre a mano usaba las fechas guardadas, que envejecen: asi salio el
# informe de FULL SPORT con junio-julio cuando tenia que ser julio-agosto.
# Estando aca las comparten el daily y `main.py --config`.


Feriados = list[str] | set[str] | None


def _dias_feriados(feriados: Feriados) -> set[date]:
    """Normaliza la fuente de feriados. `None` -> los de config.settings.

    Es un parametro y no una lectura fija porque el daily los parchea en sus
    tests sobre su propio modulo; sin el parametro, ese parche dejaba de tener
    efecto y el helper contestaba con los feriados reales.
    """
    if feriados is None:
        from config.settings import FERIADOS

        feriados = FERIADOS
    return {date.fromisoformat(r) if isinstance(r, str) else r for r in feriados}


def es_dia_habil(value: date, feriados: Feriados = None) -> bool:
    """True cuando la fecha no es domingo ni feriado configurado.

    OJO: el sabado ES habil en este proyecto; solo se excluyen domingos y
    FERIADOS.
    """
    return value.weekday() != 6 and value not in _dias_feriados(feriados)


def es_primer_dia_habil_del_mes(value: date, feriados: Feriados = None) -> bool:
    """True si la fecha es el primer dia habil de su mes."""
    dias = _dias_feriados(feriados)
    if not es_dia_habil(value, dias):
        return False
    cursor = value.replace(day=1)
    while cursor < value:
        if es_dia_habil(cursor, dias):
            return False
        cursor += timedelta(days=1)
    return True


def rango_mes_a_hoy(hoy: date, feriados: Feriados = None) -> tuple[str, str]:
    """Ventana de los informes mensuales, con `fecha_hasta` INCLUSIVA.

    El primer dia habil del mes se manda el mes anterior cerrado; el resto de
    los dias, el mes en curso hasta hoy.
    """
    if es_primer_dia_habil_del_mes(hoy, feriados):
        ultimo = hoy.replace(day=1) - timedelta(days=1)
        return ultimo.replace(day=1).isoformat(), ultimo.isoformat()
    return hoy.replace(day=1).isoformat(), hoy.isoformat()


def rango_mes_completo(hoy: date, feriados: Feriados = None) -> tuple[str, str]:
    """Igual que :func:`rango_mes_a_hoy` pero con el limite superior EXCLUSIVO.

    Para los informes cuyo SQL usa `fecha_comprobante < :fecha_hasta`.
    """
    if es_primer_dia_habil_del_mes(hoy, feriados):
        primero_anterior = (hoy.replace(day=1) - timedelta(days=1)).replace(day=1)
        return primero_anterior.isoformat(), hoy.replace(day=1).isoformat()
    return hoy.replace(day=1).isoformat(), (hoy + timedelta(days=1)).isoformat()


def rango_ventana_movil(hoy: date, meses: int) -> tuple[str, str]:
    """Ventana de `meses` meses calendario que TERMINA hoy.

    Con meses=3 y hoy=2026-08-18 devuelve ('2026-06-01', '2026-08-18'): junio
    entero, julio entero y agosto hasta hoy. Al cambiar de mes la ventana rueda
    sola y sigue midiendo tres meses; no crece.

    Es distinto de `mes_a_hoy`, que siempre da UN mes. Los informes abiertos por
    mes derivan la cantidad de columnas del rango, asi que necesitan que el
    ancho se conserve.
    """
    if meses < 1:
        raise ValueError(f"la ventana tiene que ser de al menos 1 mes, no {meses}")
    total = (hoy.year * 12 + hoy.month - 1) - (meses - 1)
    desde = date(total // 12, total % 12 + 1, 1)
    return desde.isoformat(), hoy.isoformat()


def resolver_ventana(
    modo: str, hoy: date, meses_ventana: int | None = None
) -> tuple[str, str]:
    """Traduce un `fecha_modo` de config a un rango concreto.

    Raises:
        ValueError: si el modo no existe. Un modo mal escrito tiene que romper
            fuerte y no caer en silencio a las fechas guardadas, que es
            justamente el bug que esto viene a cerrar.
    """
    if modo == "mes_a_hoy":
        return rango_mes_a_hoy(hoy)
    if modo == "mes_completo":
        return rango_mes_completo(hoy)
    if modo == "hoy":
        return hoy.isoformat(), hoy.isoformat()
    if modo == "ventana_movil":
        # El ancho NO se escribe aparte: sale de las fechas que ya trae el
        # config, que quedan documentando cuantos meses mide el informe.
        if not meses_ventana:
            raise ValueError(
                "fecha_modo 'ventana_movil' necesita el ancho en meses, que se "
                "deriva de fecha_desde..fecha_hasta del config"
            )
        return rango_ventana_movil(hoy, meses_ventana)
    raise ValueError(
        f"fecha_modo desconocido: {modo!r}. "
        "Validos: mes_a_hoy, mes_completo, hoy, ventana_movil"
    )
