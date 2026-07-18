"""Gold datasource for acciones-comerciales: aexcel-equivalent extraction +
deterministic terna grain-collapse (RF-01, Decision 14).

``DataLoader.get_aexcel_equivalent()`` issues a single read-only, composite
-key SQL query returning ONE ROW PER fact_ventas LINE (not pre-aggregated),
joined with dim_cliente/dim_articulo/dim_sucursal and labeled with the
aexcel-equivalent column names.

The (fecha, cliente, articulo) terna grain-collapse the real aexcel export
carries — additive SUMs + a deterministic ACTUAL-value pick for the
non-additive Precio/Bonific columns — is performed HERE in pandas
(``collapse_to_terna_grain``), not in SQL. This keeps the deterministic
pick/tie-break rule fully unit-testable without a live database, and gives
S2's PRECIO FINAL lookup (RF-05) and S3's reconciliation sheet (RF-11) a
single, auditable place to consume.

Decision 14 (user-corrected, overrides an earlier weighted-average
remediation): Precio and Bonific at the terna grain are NEVER a computed
blend/average. They are the ACTUAL value of the single source line picked
deterministically within the terna:
    1. greatest ``Cantidades Totales`` (line-level, pre-sum)
    2. tie-break: greatest ``Precio``
    3. tie-break: lowest ``_id_linea`` (a "ctid-equivalent" — fact_ventas.id
       is a monotonically-assigned PK, used as a stable physical/logical
       row-order proxy since gold.fact_ventas may be a view without a
       literally exposed ctid)
Every terna where the pick had to disambiguate more than one distinct
Precio (or Bonific) among its source lines is returned via
``AexcelEquivalentResult.multi_price_ternas`` for the RF-11 reconciliation
sheet audit section.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.core.data_loader import DataLoader

# Grain key columns (fecha, cliente, articulo) — matches the real aexcel
# export's pre-aggregated shape.
TERNA_COLS: list[str] = ["Descripción Período", "Cod. Cliente", "Código"]

# Additive columns: SUMmed across every line sharing the terna.
_ADDITIVE_SUM_COLS: list[str] = ["Cantidades Totales", "Facturacion Neta", "Descuentos"]

# Non-additive + passthrough descriptive columns carried through from the
# deterministically-PICKED line. Precio/Bonific are the picked line's ACTUAL
# value (Decision 14) — the passthrough descriptive columns (client/article
# labels) are expected to be constant within a terna, so sourcing them from
# the picked line is safe.
_PICKED_LINE_COLS: list[str] = [
    "Descripción",
    "Sucursal",
    "Descripción_2",
    "Descripción_3",
    "Descripción_12",
    "Precio",
    "Bonific",
]

# Internal tie-break column — sort-only, never surfaces in the collapsed output.
_TIE_BREAK_COL = "_id_linea"


@dataclass
class MultiPriceTerna:
    """One flagged terna where the grain-collapse pick had to disambiguate
    more than one distinct Precio (or Bonific) among its source lines.

    Feeds the RF-11 reconciliation sheet's multi-price audit section, which
    the RF-12 diff harness uses to validate the pick/tie-break rule
    empirically against the real aexcel.xlsx file during the parallel run.
    """

    fecha: Any
    id_cliente: Any
    id_articulo: Any
    candidate_precios: list[float]
    candidate_bonific: list[float]
    picked_precio: float
    picked_bonific: float
    pick_reason: str


@dataclass
class AexcelEquivalentResult:
    """Terna-grain (fecha, cliente, articulo) aexcel-equivalent dataset plus
    the audit trail of multi-price ternas the deterministic pick had to
    disambiguate (RF-01, RF-11)."""

    data: pd.DataFrame
    multi_price_ternas: list[MultiPriceTerna] = field(default_factory=list)


_PICK_REASON = (
    "greatest Cantidades Totales; tie-break greatest Precio; "
    "tie-break lowest _id_linea (ctid-equivalent)"
)


def collapse_to_terna_grain(df_lineas: pd.DataFrame) -> AexcelEquivalentResult:
    """Collapse line-level gold rows to the (fecha, cliente, articulo) terna
    grain the aexcel export expects (RF-01, Decision 14).

    ADDITIVE columns (Cantidades Totales, Facturacion Neta, Descuentos) are
    SUMmed across every line sharing the terna.

    NON-ADDITIVE columns (Precio, Bonific) resolve to the ACTUAL value of the
    single line PICKED deterministically within the terna — NEVER a computed
    blend/average. See module docstring for the exact tie-break chain.

    Zero-cantidad lines participate in the same deterministic ranking (no
    special-cased branch is needed — the tie-break chain is total).
    """
    if df_lineas.empty:
        return AexcelEquivalentResult(data=df_lineas.iloc[0:0].copy(), multi_price_ternas=[])

    working = df_lineas.copy()

    # 1. Deterministic pick: sort so the winning line is first per terna,
    #    then take the first ROW of each group (stable sort — full tie-break
    #    chain already disambiguates every row via the unique _id_linea).
    #    NOTE: deliberately NOT groupby(...).first() — that pandas method
    #    returns the first NON-NULL value PER COLUMN independently, not the
    #    first row, so it would silently splice in a value from a DIFFERENT
    #    source line whenever the winning line has a NaN in any picked
    #    column (e.g. a NULL bonificacion, or a descriptive column left
    #    NULL by a LEFT JOIN miss) — exactly the "computed
    #    blend/fabricated value" Decision 14 forbids. groupby(...).head(1)
    #    keeps the whole winning row intact, NaNs included.
    sort_cols = TERNA_COLS + ["Cantidades Totales", "Precio", _TIE_BREAK_COL]
    ascending = [True] * len(TERNA_COLS) + [False, False, True]
    ordered = working.sort_values(by=sort_cols, ascending=ascending, kind="mergesort")
    picked = ordered.groupby(TERNA_COLS, sort=False).head(1)
    picked = picked[TERNA_COLS + _PICKED_LINE_COLS].reset_index(drop=True)

    # 2. Additive sums.
    sums = working.groupby(TERNA_COLS, as_index=False, sort=False)[_ADDITIVE_SUM_COLS].sum()

    collapsed = picked.merge(sums, on=TERNA_COLS, how="left")

    # 3. Flag multi-price/multi-Bonific ternas (audit trail for RF-11).
    picked_indexed = picked.set_index(TERNA_COLS)
    multi_price_ternas: list[MultiPriceTerna] = []
    for terna_key, group in working.groupby(TERNA_COLS, sort=False):
        distinct_precios = sorted(group["Precio"].dropna().unique().tolist())
        distinct_bonific = sorted(group["Bonific"].dropna().unique().tolist())
        if len(distinct_precios) > 1 or len(distinct_bonific) > 1:
            picked_row = picked_indexed.loc[terna_key]
            multi_price_ternas.append(
                MultiPriceTerna(
                    fecha=terna_key[0],
                    id_cliente=terna_key[1],
                    id_articulo=terna_key[2],
                    candidate_precios=distinct_precios,
                    candidate_bonific=distinct_bonific,
                    picked_precio=picked_row["Precio"],
                    picked_bonific=picked_row["Bonific"],
                    pick_reason=_PICK_REASON,
                )
            )

    return AexcelEquivalentResult(data=collapsed, multi_price_ternas=multi_price_ternas)


def load_aexcel_equivalent(
    data_loader: DataLoader, fecha_desde: str, fecha_hasta: str
) -> AexcelEquivalentResult:
    """Fetch line-level gold data and collapse it to the aexcel-equivalent
    terna grain (RF-01). Read-only — issues no DDL against gold (RF-25)."""
    df_lineas = data_loader.get_aexcel_equivalent(fecha_desde, fecha_hasta)
    return collapse_to_terna_grain(df_lineas)


def load_sucursal_por_cliente(data_loader: DataLoader) -> dict[Any, str]:
    """Fresh ``Cod. Cliente -> Sucursal`` map for the RF-04 wapi SUCURSAL
    lookup (S3 wiring). Thin wrapper around
    ``DataLoader.get_clientes_sucursal()`` — read-only, zero DDL (RF-25)."""
    df = data_loader.get_clientes_sucursal()
    return dict(zip(df["Cod. Cliente"], df["Sucursal"]))
