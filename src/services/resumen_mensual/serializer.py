"""
JSON serializer for the resumen-mensual report.

Pure function — no DB access, no I/O. Converts _SheetStruct list into
the JSON contract dict consumed by the /resumen-mensual/datos endpoint
and the React frontend.

Contract (ADR-2): subtotal numeric values are emitted as null; the frontend
recomputes them via computeSubtotals(). Row numeric values are float (never
rounded/truncated — project-wide no-rounding rule).
"""
import pandas as pd

from src.services.resumen_mensual.service import (
    _SheetSection,
    _SheetStruct,
    _SUBTOTAL_CC,
    _SUC_SIN_DIRECTA,
    _TOTAL_SIN_SMK,
)

# The 3 special Sucursal labels that mark injected subtotal rows
_SUBTOTAL_LABELS: frozenset[str] = frozenset({_SUBTOTAL_CC, _SUC_SIN_DIRECTA, _TOTAL_SIN_SMK})


def _serialize_value(v) -> float | None:
    """Serialize a single numeric value.

    Rules (project no-rounding rule):
      - NaN / None → None (JSON null)
      - otherwise → float(v) — preserves all precision; formatting is frontend-only
    """
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return float(v)


def _serialize_row(
    row: pd.Series,
    col_n1: str,
    col_n2: str,
) -> dict:
    """Serialize one DataFrame row to the JSON row contract.

    Column mapping:
      - Sucursal → "Sucursal" (string)
      - Generico → dropped (section carries the label)
      - <col_n2> (dynamic) → canonical key "col_n2"
      - <col_n1> (dynamic) → canonical key "col_n1"
      - Total Ventas, Tendencia, MMAA, MA → float | null
      - Objetivo → float | null  (null ≠ 0 — critical contract surface)
      - Tend vs Obj (%) → float | null
      - is_subtotal → bool derived from Sucursal label

    Args:
        row: One row of the 10-column DataFrame.
        col_n1: Human name of the N-1 day column (e.g. "09-06 Martes").
        col_n2: Human name of the N-2 day column (e.g. "08-06 Lunes").

    Returns:
        Dict with canonical keys.
    """
    sucursal = row.get("Sucursal") or row["Sucursal"]
    is_subtotal = sucursal in _SUBTOTAL_LABELS

    return {
        "Sucursal": sucursal,
        "col_n2": _serialize_value(row.get(col_n2)),
        "col_n1": _serialize_value(row.get(col_n1)),
        "Total Ventas": _serialize_value(row.get("Total Ventas")),
        "Tendencia": _serialize_value(row.get("Tendencia")),
        "MMAA": _serialize_value(row.get("MMAA")),
        "MA": _serialize_value(row.get("MA")),
        "Objetivo": _serialize_value(row.get("Objetivo")),
        "Tend vs Obj (%)": _serialize_value(row.get("Tend vs Obj (%)")),
        "is_subtotal": is_subtotal,
    }


def _serialize_section(section: _SheetSection, col_n1: str, col_n2: str) -> dict:
    """Serialize one _SheetSection to the JSON section contract."""
    rows = [
        _serialize_row(row, col_n1, col_n2)
        for _, row in section.df.iterrows()
    ]
    return {
        "label": section.label,
        "rows": rows,
    }


def to_datos_json(
    structs: list[_SheetStruct],
    info_dias: dict,
    col_n1: str,
    col_n2: str,
    con_objetivo: bool = True,
) -> dict:
    """Convert the ordered sheet structure into the JSON response contract.

    This is the single serialization boundary between the service layer and
    the JSON endpoint. It is a pure function with no DB access or I/O.

    Args:
        structs: Ordered list of _SheetStruct from _build_sheet_structs().
        info_dias: Dict with Dias Habiles / Transcurridos / Faltantes.
        col_n1: Dynamic human name of the N-1 day column (e.g. "09-06 Martes").
        col_n2: Dynamic human name of the N-2 day column (e.g. "08-06 Lunes").
        con_objetivo: Whether cupos/Objetivo column is included in the data.

    Returns:
        Dict matching the JSON contract:
        {
            "meta": {
                "col_n1": str, "col_n2": str,
                "info_dias": {...}, "con_objetivo": bool
            },
            "sheets": [
                {
                    "generico": str, "note": str|null, "sin_prvta": bool (when true),
                    "sections": [{"label": str, "rows": [...]}]
                }
            ]
        }
    """
    meta = {
        "col_n1": col_n1,
        "col_n2": col_n2,
        "info_dias": dict(info_dias),
        "con_objetivo": con_objetivo,
    }

    sheets = []
    for struct in structs:
        sections = [
            _serialize_section(sec, col_n1, col_n2)
            for sec in struct.sections
        ]
        sheet: dict = {
            "generico": struct.logical_generico,
            "note": struct.note,
            "sections": sections,
        }
        # sin_prvta signal: present and true only when the note is set
        # (note is set by _build_sheet_structs when logical_generico is in sin_prvta list)
        if struct.note is not None:
            sheet["sin_prvta"] = True

        sheets.append(sheet)

    return {
        "meta": meta,
        "sheets": sheets,
    }
