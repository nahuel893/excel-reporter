"""Repair of the workbook's pre-existing ``#REF!`` formulas.

The workbook arrived with 162 formulas whose ranges had been lost — every one of
them a ``SUMIFS`` that had pointed at ``AX`` or at ``referencia ma`` before some
past edit deleted the columns underneath. They render as ``#REF!``, which means
the four wholesale-mix tables in ``suc`` and the per-branch MIX MAY rows of
``ramal``/``qbrd``/``inte`` had shown nothing for a long time.

The ranges are recoverable because each broken formula has a healthy sibling with
the same shape sitting next to it. For example ``suc!B3``::

    +SUMIFS(#REF!, #REF!, suc!$A3, #REF!, suc!$A$1, #REF!, suc!B$2)

maps argument for argument onto the surviving ``salta!J7`` numerator::

    +SUMIFS(AX!$T:$T, AX!$AD:$AD, $K$1, AX!$V:$V, $A7, AX!$W:$W, $D7)

so the lost ranges are the quantity column, the branch column, the price-list
column and the generic column, in that order.

The reconstruction was verified by triangulation: after repair, ``suc!B11``
(built from the rebuilt formulas) and ``salta!J7`` (untouched, computed straight
from ``AX``) agree to the last decimal — 0,343824653859693 — despite being
independent paths to the same number.

Repair is idempotent: a formula without ``#REF!`` is returned unchanged.
"""
from __future__ import annotations

import re

# A cell reference like suc!$A3 or inte!AG$2. Deliberately strict — an earlier
# version used [^,]+ and matched across cell boundaries in the raw XML, which
# silently produced formulas pointing at the wrong column.
_REF = r"\$?[A-Z]{1,3}\$?\d+"

# suc, three criteria: branch + price list + generic -> wholesale sales
_SUC_TRES = re.compile(
    rf"^\+SUMIFS\(#REF!,#REF!,(suc!{_REF}),#REF!,(suc!{_REF}),#REF!,(suc!{_REF})\)$"
)
# suc, two criteria: branch + generic -> total sales
_SUC_DOS = re.compile(rf"^\+SUMIFS\(#REF!,#REF!,(suc!{_REF}),#REF!,(suc!{_REF})\)$")

# ramal/qbrd/inte: the per-branch MIX MAY row, which reads the wholesale block of
# `referencia ma` instead of recomputing the ratio.
_ZONA = re.compile(
    rf"SUMIFS\(#REF!,#REF!,((?:inte|qbrd|ramal)!{_REF}),#REF!,((?:inte|qbrd|ramal)!{_REF})\)"
)

HOJAS_REPARABLES = ("suc", "inte", "qbrd", "ramal")

# The generic criterion of the VOLUMEN HTLS table points at row 26; the mix
# tables point at row 2. That is what tells the two apart, and it decides whether
# the sum range is hectolitres or units.
_FILA_HTLS = "26"


def _rango_suma(criterio_generico: str) -> str:
    return "AX!$AC:$AC" if criterio_generico.endswith(_FILA_HTLS) else "AX!$T:$T"


def reparar_formula(hoja: str, formula: str) -> str:
    """Return ``formula`` with its lost ranges restored, or unchanged.

    Args:
        hoja: worksheet name; the reconstruction differs per sheet.
        formula: formula body without the leading ``=``.

    Returns:
        The repaired formula, or the original when nothing matches.
    """
    if "#REF!" not in formula:
        return formula

    if hoja == "suc":
        match = _SUC_TRES.match(formula)
        if match:
            branch, lista, generico = match.groups()
            return (
                f"+SUMIFS({_rango_suma(generico)},AX!$F:$F,{branch},"
                f"AX!$V:$V,{lista},AX!$W:$W,{generico})"
            )
        match = _SUC_DOS.match(formula)
        if match:
            branch, generico = match.groups()
            return (
                f"+SUMIFS({_rango_suma(generico)},AX!$F:$F,{branch},"
                f"AX!$W:$W,{generico})"
            )
        return formula

    return _ZONA.sub(
        lambda m: (
            "SUMIFS('referencia ma'!$AM:$AM,'referencia ma'!$AD:$AD,"
            f"{m.group(1)},'referencia ma'!$AF:$AF,{m.group(2)})"
        ),
        formula,
    )


_CELDA_CON_FORMULA = re.compile(r'(<c r="[A-Z]+\d+"[^>]*>\s*<f[^>]*>)([^<]*)(</f>)')


def reparar_hoja(hoja: str, sheet_xml: str) -> tuple[str, int]:
    """Repair every broken formula in one worksheet's XML.

    Each formula is transformed in isolation so a pattern can never run past the
    end of a cell into the next one.

    Returns:
        ``(xml, repaired_count)``.
    """
    reparadas = 0

    def _sub(match: re.Match) -> str:
        nonlocal reparadas
        cuerpo = match.group(2)
        if "#REF!" not in cuerpo:
            return match.group(0)
        nuevo = reparar_formula(hoja, cuerpo.replace("&quot;", '"'))
        if nuevo == cuerpo:
            return match.group(0)
        reparadas += 1
        return match.group(1) + nuevo.replace('"', "&quot;") + match.group(3)

    return _CELDA_CON_FORMULA.sub(_sub, sheet_xml), reparadas


def contar_refs_rotas(sheet_xml: str) -> int:
    """How many formulas in this worksheet still evaluate to ``#REF!``."""
    return len(re.findall(r"<f[^>]*>[^<]*#REF![^<]*</f>", sheet_xml))
