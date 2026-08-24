"""The 4 report pivots (RF-09).

Each builder returns a flat pandas frame whose column ORDER and header
STRINGS are a byte-for-byte contract (see ``constants``), ending in a
distinctly-usable ``TOTAL GENERAL`` grand-total row:

  * FACT_NET (aexcel)     — rows A:E, `Suma de Facturacion Neta`,
    `Suma de Descuentos`, `Suma de Campo1`; shape A:H.
  * ART-ACCION (wapi)     — 6 row fields + `Suma de Descuento`; shape A:G.
  * CLIENTE-FECHA (wapi)  — 9 row fields + `Suma de Descuento`; shape A:J.
  * ACC-GEN (wapi)        — 4 row fields (A:D) + BLANK spacer (E) + 5
    genéricos (F:J) in fixed order; the genérico grand `Total` is OUTSIDE
    this A:J block (informe col K, left untouched); shape A:J.

`Suma de Campo1` (FACT_NET) is Excel calculated-field semantics: the ratio
of GROUP SUMS at each node — `SUM(Descuentos) / SUM(Facturacion Neta)` — NOT
a per-row ratio and NOT a sum of per-row ratios. A zero Facturacion-Neta
group sum yields a BLANK cell (never `#DIV/0!`, 0, or a fabricated value).

Floats are preserved verbatim (RF-23) — no value is rounded / truncated /
cast to int anywhere in this module; display precision is a `number_format`
concern handled by the BASE-control writer (S3).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.services.acciones_comerciales.constants import (
    ACC_GEN_COLUMN_FIELD,
    ACC_GEN_ROW_FIELDS,
    ACC_GEN_SPACER_COL,
    ACC_GEN_VALUE_SRC,
    ART_ACCION_ROW_FIELDS,
    CLIENTE_FECHA_ROW_FIELDS,
    COL_DESCUENTO,
    FACT_NET_DESCUENTOS_SRC,
    FACT_NET_FACT_NETA_SRC,
    FACT_NET_ROW_FIELDS,
    GENERICOS_ORDER,
    LABEL_SUMA_CAMPO1,
    LABEL_SUMA_DESCUENTO,
    LABEL_SUMA_DESCUENTOS,
    LABEL_SUMA_FACT_NETA,
)

TOTAL_GENERAL_LABEL = "TOTAL GENERAL"


# ─────────────────────────────────────────────────────────────────────────
# shared helpers
# ─────────────────────────────────────────────────────────────────────────


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Element-wise ``numerator / denominator`` with a divide-by-zero guard:
    where the denominator is 0 the result is NaN (blank), never inf/`#DIV/0!`.
    No rounding is applied."""
    num = numerator.to_numpy(dtype="float64")
    den = denominator.to_numpy(dtype="float64")
    out = np.divide(num, den, out=np.full(num.shape, np.nan), where=den != 0)
    return pd.Series(out, index=numerator.index)


def _append_total_general(
    frame: pd.DataFrame, row_fields: list[str], totals: dict[str, float]
) -> pd.DataFrame:
    """Append a distinctly-labelled TOTAL GENERAL row: the first row-field
    column holds the label, remaining row-field/spacer columns are blank, and
    each value column carries its precomputed grand total."""
    total_row = {col: "" for col in frame.columns}
    total_row[row_fields[0]] = TOTAL_GENERAL_LABEL
    for col, value in totals.items():
        total_row[col] = value
    total_df = pd.DataFrame([total_row], columns=frame.columns)
    return pd.concat([frame, total_df], ignore_index=True)


def _sum_descuento_pivot(wapi: pd.DataFrame, row_fields: list[str]) -> pd.DataFrame:
    """Generic ``Suma de Descuento`` pivot over ``row_fields`` (ART-ACCION,
    CLIENTE-FECHA). NaN Descuento (unresolved-price rows, RF-08) is skipped by
    the sum, keeping the pivot totals valid."""
    grouped = wapi.groupby(row_fields, as_index=False, sort=True).agg(
        **{LABEL_SUMA_DESCUENTO: (COL_DESCUENTO, "sum")}
    )
    grand = grouped[LABEL_SUMA_DESCUENTO].sum()
    return _append_total_general(grouped, row_fields, {LABEL_SUMA_DESCUENTO: grand})


# ─────────────────────────────────────────────────────────────────────────
# FACT_NET (RF-09)
# ─────────────────────────────────────────────────────────────────────────


def build_fact_net(aexcel: pd.DataFrame) -> pd.DataFrame:
    """FACT_NET pivot from the aexcel-equivalent terna frame — rows A:E,
    `Suma de Facturacion Neta`/`Suma de Descuentos`/`Suma de Campo1` (F:H)."""
    grouped = aexcel.groupby(FACT_NET_ROW_FIELDS, as_index=False, sort=True).agg(
        **{
            LABEL_SUMA_FACT_NETA: (FACT_NET_FACT_NETA_SRC, "sum"),
            LABEL_SUMA_DESCUENTOS: (FACT_NET_DESCUENTOS_SRC, "sum"),
        }
    )
    # Campo1 = ratio of GROUP SUMS per leaf node; zero FN sum -> blank.
    grouped[LABEL_SUMA_CAMPO1] = _safe_ratio(
        grouped[LABEL_SUMA_DESCUENTOS], grouped[LABEL_SUMA_FACT_NETA]
    )

    fn_total = grouped[LABEL_SUMA_FACT_NETA].sum()
    desc_total = grouped[LABEL_SUMA_DESCUENTOS].sum()
    # Grand-total Campo1 = ratio of grand sums; zero FN sum -> blank.
    campo1_total = desc_total / fn_total if fn_total != 0 else float("nan")

    return _append_total_general(
        grouped,
        FACT_NET_ROW_FIELDS,
        {
            LABEL_SUMA_FACT_NETA: fn_total,
            LABEL_SUMA_DESCUENTOS: desc_total,
            LABEL_SUMA_CAMPO1: campo1_total,
        },
    )


# ─────────────────────────────────────────────────────────────────────────
# ART-ACCION / CLIENTE-FECHA (RF-09)
# ─────────────────────────────────────────────────────────────────────────


def build_art_accion(wapi: pd.DataFrame) -> pd.DataFrame:
    """ART-ACCION pivot from enriched wapi — 6 row fields + `Suma de
    Descuento` (A:G)."""
    return _sum_descuento_pivot(wapi, ART_ACCION_ROW_FIELDS)


def build_cliente_fecha(wapi: pd.DataFrame) -> pd.DataFrame:
    """CLIENTE-FECHA pivot from enriched wapi — 9 row fields + `Suma de
    Descuento` (A:J)."""
    return _sum_descuento_pivot(wapi, CLIENTE_FECHA_ROW_FIELDS)


# ─────────────────────────────────────────────────────────────────────────
# ACC-GEN (RF-09) — blank spacer at E, genéricos F:J
# ─────────────────────────────────────────────────────────────────────────


def build_acc_gen(wapi: pd.DataFrame) -> pd.DataFrame:
    """ACC-GEN pivot from enriched wapi — 4 row fields (A:D), a BLANK spacer
    column (E), and `Suma de Descuento` per genérico at F:J in the fixed
    CERVEZAS / AGUAS DANONE / VINOS CCU / PERNOD RICARD / SIDRAS Y LICORES
    order. The genérico grand `Total` (informe col K) is OUTSIDE this A:J
    block and is intentionally NOT emitted here (Decision 11)."""
    pivot = wapi.pivot_table(
        index=ACC_GEN_ROW_FIELDS,
        columns=ACC_GEN_COLUMN_FIELD,
        values=ACC_GEN_VALUE_SRC,
        aggfunc="sum",
        fill_value=0.0,
        sort=True,
    )
    # Force all 5 genéricos to exist in the exact positional order (missing
    # genéricos land as an all-zero column).
    pivot = pivot.reindex(columns=GENERICOS_ORDER, fill_value=0.0)
    pivot = pivot.reset_index()

    # Insert the BLANK spacer at position E (after the 4 row fields) so the
    # positional A:J paste aligns each genérico under its correct header.
    pivot.insert(len(ACC_GEN_ROW_FIELDS), ACC_GEN_SPACER_COL, "")

    totals = {generico: pivot[generico].sum() for generico in GENERICOS_ORDER}
    return _append_total_general(pivot, ACC_GEN_ROW_FIELDS, totals)
