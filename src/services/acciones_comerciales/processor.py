"""Derived wapi columns — the enriched internal table (RF-04..RF-08).

Turns the raw 21-column wapi frame (RF-02) into the enriched table by
appending the derived V:AD columns the informe and the 4 pivots consume:

    SUCURSAL, CONCAT, PRECIO FINAL , mvb, ZONA, Total2, Descuento,
    Tipo Descuento

Design intent (spec RF-04..RF-08, Decision 1 + Decision 14):

  * SUCURSAL (RF-04) — FRESH lookup by ``Cod. Cliente`` against the current
    dim_cliente snapshot (passed in as ``sucursal_por_cliente`` so this stays
    pure/testable; S3 wires the live query). Unresolvable client -> blank +
    surfaced in ``unresolved_sucursal`` (never defaulted to a wrong sucursal).

  * PRECIO FINAL  (RF-05) — exact-match terna ``(fecha, cliente, articulo)``
    lookup on the aexcel-equivalent picked-line price (Decision 14: an ACTUAL
    line value, NEVER a blend/average). No match -> blank + surfaced in
    ``unresolved_precio``; the row's Total2/Descuento INHERIT the blank state
    (never computed off a fabricated price — replaces the engine's #N/A -> 0).

  * mvb (RF-06) — case-sensitive 3-tier FIND: MVB / (ESC.) / EXTRA TASA /
    OTRAS.

  * ZONA (RF-07) — SUPERVISOR name keyed by SUCURSAL against the business
    sucursal->supervisor map. The field is named ``ZONA`` for contract
    stability even though it holds a supervisor (intentional legacy quirk).

  * Total2 / Descuento / Tipo Descuento (RF-08) — Total2 = Cantidad * PRECIO
    FINAL; Descuento = IFERROR(Total2 * Desc%/100 + SinCargo * PRECIO FINAL,
    0) with the error-safe fallback preserved for genuine input errors
    (blank is reserved for the missing-price case above); Tipo Descuento =
    SIN CARGO when Desc% is blank else Descuentos.

No value is ever rounded / truncated / cast to int here (RF-23): display
precision is an Excel ``number_format`` concern only.

NOTE for S3 wiring: the terna key is built from the RAW ``Fecha`` /
``Cod. Cliente`` / ``Artículo Distribuidora`` values, matched against the
aexcel-equivalent's ``Descripción Período`` / ``Cod. Cliente`` / ``Código``.
The service MUST align the ``Fecha``/``Descripción Período`` dtypes (both a
date, or both the same string form) before calling, or every terna misses.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.services.acciones_comerciales.constants import (
    COL_CONCAT,
    COL_DESCUENTO,
    COL_MVB,
    COL_PRECIO_FINAL,
    COL_SUCURSAL,
    COL_TIPO_DESCUENTO,
    COL_TOTAL2,
    COL_ZONA,
    MVB_DEFAULT,
    MVB_TIERS,
    TIPO_DESCUENTO_DESCUENTOS,
    TIPO_DESCUENTO_SIN_CARGO,
    ZONA_CONFIG_KEY,
)


@dataclass
class EnrichedWapiResult:
    """Enriched wapi table plus the two reconciliation flag subsets.

    ``data`` — raw 21-column wapi block + the appended derived columns.
    ``unresolved_sucursal`` — rows whose ``Cod. Cliente`` had no fresh
        dim_cliente match (RF-04) — SUCURSAL left blank.
    ``unresolved_precio`` — rows whose terna had no aexcel-equivalent price
        match (RF-05) — PRECIO FINAL /Total2/Descuento left blank.
    Both subsets feed the RF-11 reconciliation sheet's unresolved section.
    """

    data: pd.DataFrame
    unresolved_sucursal: pd.DataFrame = field(default_factory=pd.DataFrame)
    unresolved_precio: pd.DataFrame = field(default_factory=pd.DataFrame)


# ─────────────────────────────────────────────────────────────────────────
# small Excel-semantics helpers
# ─────────────────────────────────────────────────────────────────────────


def _is_blank(value: Any) -> bool:
    """True for an Excel-blank cell: None / NaN / NA / NaT / empty string."""
    if isinstance(value, str):
        return value.strip() == ""
    return bool(pd.isna(value))


def _num_or_zero(value: Any) -> float:
    """Coerce one arithmetic operand the way Excel does: a blank cell counts
    as 0; a numeric (or numeric string) becomes a float; any other
    non-numeric text raises ValueError so the IFERROR guard can fall back to
    0 (Excel #VALUE!)."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return 0.0
        return float(stripped)  # raises ValueError on non-numeric text
    if pd.isna(value):
        return 0.0
    return float(value)


# ─────────────────────────────────────────────────────────────────────────
# RF-06 — mvb classifier
# ─────────────────────────────────────────────────────────────────────────


def classify_mvb(value: Any) -> str:
    """Case-sensitive 3-tier substring classification of ``Descripción
    Acción`` (RF-06). First matching tier wins; no match -> OTRAS."""
    if not isinstance(value, str):
        return MVB_DEFAULT
    for needle, label in MVB_TIERS:
        if needle in value:
            return label
    return MVB_DEFAULT


# ─────────────────────────────────────────────────────────────────────────
# RF-05 — terna -> precio exact-match lookup (from the aexcel-equivalent)
# ─────────────────────────────────────────────────────────────────────────


def build_precio_lookup(aexcel_data: pd.DataFrame) -> dict[tuple, Any]:
    """Build the exact-match ``(fecha, cliente, articulo) -> Precio`` lookup
    from the aexcel-equivalent terna-grain frame (RF-01/RF-05).

    The aexcel-equivalent is already collapsed to one row per terna
    (gold_source), so keys are unique. Precio is the deterministically-picked
    ACTUAL line value (Decision 14) — this lookup never blends."""
    lookup: dict[tuple, Any] = {}
    for fecha, cliente, articulo, precio in zip(
        aexcel_data["Descripción Período"],
        aexcel_data["Cod. Cliente"],
        aexcel_data["Código"],
        aexcel_data["Precio"],
    ):
        lookup[(fecha, cliente, articulo)] = precio
    return lookup


# ─────────────────────────────────────────────────────────────────────────
# RF-07 — sucursal -> supervisor mapping loader (config-owned)
# ─────────────────────────────────────────────────────────────────────────


def load_supervisor_por_sucursal(path: str | Path) -> dict[str, str]:
    """Load the business-owned sucursal->supervisor mapping for ZONA (RF-07).

    The JSON nests the mapping under ``sucursal_supervisor`` so metadata keys
    (e.g. ``_note``) can live alongside it without polluting the lookup."""
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    return dict(payload[ZONA_CONFIG_KEY])


# ─────────────────────────────────────────────────────────────────────────
# RF-04..RF-08 — the enrichment
# ─────────────────────────────────────────────────────────────────────────


def enrich_wapi(
    wapi: pd.DataFrame,
    *,
    sucursal_por_cliente: Mapping[Any, str],
    precio_por_terna: Mapping[tuple, Any],
    supervisor_por_sucursal: Mapping[str, str],
) -> EnrichedWapiResult:
    """Append the derived V:AD columns to the raw wapi frame (RF-04..RF-08).

    All three lookups are passed in as plain mappings so the transform is a
    pure, database-free pandas operation (S3 wires the live sources)."""
    enriched = wapi.copy()

    # RF-04 SUCURSAL — fresh lookup; unmatched client -> NaN.
    enriched[COL_SUCURSAL] = enriched["Cod. Cliente"].map(dict(sucursal_por_cliente))

    # CONCAT (informe wapi col W) = Fecha & Cod. Cliente & Artículo Distribuidora.
    enriched[COL_CONCAT] = [
        f"{fecha}{cliente}{articulo}"
        for fecha, cliente, articulo in zip(
            enriched["Fecha"], enriched["Cod. Cliente"], enriched["Artículo Distribuidora"]
        )
    ]

    # RF-05 PRECIO FINAL — exact terna match; no match -> NaN (blank/flagged).
    precio_lookup = dict(precio_por_terna)
    precio_vals = [
        precio_lookup.get((fecha, cliente, articulo), float("nan"))
        for fecha, cliente, articulo in zip(
            enriched["Fecha"], enriched["Cod. Cliente"], enriched["Artículo Distribuidora"]
        )
    ]
    enriched[COL_PRECIO_FINAL] = precio_vals

    # RF-06 mvb.
    enriched[COL_MVB] = [classify_mvb(v) for v in enriched["Descripción Acción"]]

    # RF-07 ZONA (supervisor keyed by SUCURSAL).
    enriched[COL_ZONA] = enriched[COL_SUCURSAL].map(dict(supervisor_por_sucursal))

    # RF-08 Total2 + Descuento (row-wise so IFERROR/blank semantics are exact).
    total2_vals: list[float] = []
    descuento_vals: list[float] = []
    for cantidad, precio_final, desc_pct, sin_cargo in zip(
        enriched["Cantidad"],
        enriched[COL_PRECIO_FINAL],
        enriched["Descuento %"],
        enriched["Cantidad Sin Cargo"],
    ):
        if pd.isna(precio_final):
            # RF-08 exception: inherit the blank/flagged state, never compute
            # against a fabricated price (overrides the engine's #N/A -> 0).
            total2_vals.append(float("nan"))
            descuento_vals.append(float("nan"))
            continue

        # Total2 = Cantidad * PRECIO FINAL (no rounding).
        try:
            total2 = _num_or_zero(cantidad) * precio_final
        except (ValueError, TypeError):
            total2 = float("nan")
        total2_vals.append(total2)

        # Descuento = IFERROR(Total2 * Desc%/100 + SinCargo * PRECIO FINAL, 0).
        try:
            if pd.isna(total2):
                raise ValueError("Total2 unavailable")
            descuento = (
                total2 * (_num_or_zero(desc_pct) / 100.0)
                + _num_or_zero(sin_cargo) * precio_final
            )
        except (ValueError, TypeError):
            descuento = 0.0
        descuento_vals.append(descuento)

    enriched[COL_TOTAL2] = total2_vals
    enriched[COL_DESCUENTO] = descuento_vals

    # RF-08 Tipo Descuento.
    enriched[COL_TIPO_DESCUENTO] = [
        TIPO_DESCUENTO_SIN_CARGO if _is_blank(v) else TIPO_DESCUENTO_DESCUENTOS
        for v in enriched["Descuento %"]
    ]

    unresolved_sucursal = enriched[enriched[COL_SUCURSAL].isna()].copy()
    unresolved_precio = enriched[enriched[COL_PRECIO_FINAL].isna()].copy()

    return EnrichedWapiResult(
        data=enriched,
        unresolved_sucursal=unresolved_sucursal,
        unresolved_precio=unresolved_precio,
    )
