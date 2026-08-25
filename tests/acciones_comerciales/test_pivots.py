"""RED tests — S2.3: the 4 report pivots (RF-09) + S2.6 no-rounding audit.

Covers ``pivots`` (4 builders) + ``constants`` (exact label/shape specs):

  - FACT_NET (aexcel): rows Sucursal,Código,Descripción_2,Descripción_3,
    Descripción_12; value labels `Suma de Facturacion Neta`,
    `Suma de Descuentos`, `Suma de Campo1`. Campo1 = ratio of GROUP SUMS
    (SUM(Descuentos)/SUM(Facturacion Neta)) at each node — NOT per-row, NOT
    a sum of per-row ratios; divide-by-zero group sum -> blank. Shape A:H.
  - ART-ACCION (wapi): 6 row fields + `Suma de Descuento`. Shape A:G.
  - CLIENTE-FECHA (wapi): 9 row fields + `Suma de Descuento`. Shape A:J.
  - ACC-GEN (wapi): 4 row fields (A:D) + BLANK spacer at E + 5 genéricos
    (CERVEZAS,AGUAS DANONE,VINOS CCU,PERNOD RICARD,SIDRAS Y LICORES) at F:J
    in that positional order; genérico Total is OUTSIDE the A:J block (col K,
    left to the informe). Shape A:J.

Every pivot frame ends with a distinctly-usable TOTAL GENERAL row. Floats
preserved (no rounding). Written before ``pivots.py``/``constants.py`` exist.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from src.services.acciones_comerciales import constants as K
from src.services.acciones_comerciales.pivots import (
    TOTAL_GENERAL_LABEL,
    build_acc_gen,
    build_art_accion,
    build_cliente_fecha,
    build_fact_net,
)

# ─────────────────────────────────────────────────────────────────────────
# builders
# ─────────────────────────────────────────────────────────────────────────


def _aexcel_row(
    sucursal="1 - CASA CENTRAL",
    codigo=900,
    des_2="ART UNO",
    des_3="MARCA UNO",
    des_12="CERVEZAS",
    facturacion=100.0,
    descuentos=10.0,
) -> dict:
    return {
        "Sucursal": sucursal,
        "Código": codigo,
        "Descripción_2": des_2,
        "Descripción_3": des_3,
        "Descripción_12": des_12,
        "Facturacion Neta": facturacion,
        "Descuentos": descuentos,
    }


def _wapi_enriched_row(
    fecha="2026-07-01",
    sucursal="CASA CENTRAL",
    cod_cliente=100,
    razon="CLIENTE UNO",
    articulo=900,
    descripcion="ART UNO",
    calibre="CERVEZAS",
    accion="ACC1",
    descripcion_accion="MVB PROMO",
    mvb="MVB",
    descuento=25.0,
) -> dict:
    return {
        "Fecha": fecha,
        "SUCURSAL": sucursal,
        "Cod. Cliente": cod_cliente,
        "Razón Social": razon,
        "Artículo Distribuidora": articulo,
        "Descripción": descripcion,
        "Calibre": calibre,
        "Acción": accion,
        "Descripción Acción": descripcion_accion,
        "mvb": mvb,
        "Descuento": descuento,
    }


# ─────────────────────────────────────────────────────────────────────────
# FACT_NET (RF-09)
# ─────────────────────────────────────────────────────────────────────────


class TestFactNet:
    def test_exact_labels_and_column_order(self):
        df = build_fact_net(pd.DataFrame([_aexcel_row()]))
        assert list(df.columns) == [
            "Sucursal",
            "Código",
            "Descripción_2",
            "Descripción_3",
            "Descripción_12",
            "Suma de Facturacion Neta",
            "Suma de Descuentos",
            "Suma de Campo1",
        ]

    def test_shape_is_A_to_H(self):
        df = build_fact_net(pd.DataFrame([_aexcel_row()]))
        assert df.shape[1] == 8  # A:H

    def test_campo1_is_ratio_of_group_sums_not_sum_of_row_ratios(self):
        # One leaf group, two source rows:
        #   row1 FN=100 Desc=10 (row ratio 0.10)
        #   row2 FN=300 Desc=90 (row ratio 0.30)
        # group ratio = SUM(Desc)/SUM(FN) = 100/400 = 0.25
        # sum-of-row-ratios (WRONG) = 0.40
        df = build_fact_net(
            pd.DataFrame(
                [
                    _aexcel_row(facturacion=100.0, descuentos=10.0),
                    _aexcel_row(facturacion=300.0, descuentos=90.0),
                ]
            )
        )
        leaf = df.iloc[0]
        assert leaf["Suma de Facturacion Neta"] == 400.0
        assert leaf["Suma de Descuentos"] == 100.0
        assert leaf["Suma de Campo1"] == pytest.approx(0.25)
        assert leaf["Suma de Campo1"] != pytest.approx(0.40)

    def test_campo1_divide_by_zero_is_blank(self):
        df = build_fact_net(
            pd.DataFrame([_aexcel_row(facturacion=0.0, descuentos=5.0)])
        )
        assert pd.isna(df.iloc[0]["Suma de Campo1"])

    def test_total_general_row_present_and_last(self):
        df = build_fact_net(
            pd.DataFrame(
                [
                    _aexcel_row(codigo=900, facturacion=100.0, descuentos=10.0),
                    _aexcel_row(codigo=901, facturacion=300.0, descuentos=90.0),
                ]
            )
        )
        total = df.iloc[-1]
        assert total["Sucursal"] == TOTAL_GENERAL_LABEL
        assert total["Suma de Facturacion Neta"] == 400.0
        assert total["Suma de Descuentos"] == 100.0
        # grand-total Campo1 = ratio of grand sums
        assert total["Suma de Campo1"] == pytest.approx(0.25)


# ─────────────────────────────────────────────────────────────────────────
# ART-ACCION (RF-09)
# ─────────────────────────────────────────────────────────────────────────


class TestArtAccion:
    def test_exact_labels_and_shape_A_to_G(self):
        df = build_art_accion(pd.DataFrame([_wapi_enriched_row()]))
        assert list(df.columns) == [
            "SUCURSAL",
            "Artículo Distribuidora",
            "Descripción",
            "Acción",
            "Descripción Acción",
            "mvb",
            "Suma de Descuento",
        ]
        assert df.shape[1] == 7  # A:G

    def test_sums_descuento_per_group(self):
        df = build_art_accion(
            pd.DataFrame(
                [
                    _wapi_enriched_row(descuento=25.0),
                    _wapi_enriched_row(descuento=15.0),
                ]
            )
        )
        # both rows share the same group -> summed
        assert df.iloc[0]["Suma de Descuento"] == 40.0

    def test_total_general_row(self):
        df = build_art_accion(
            pd.DataFrame(
                [
                    _wapi_enriched_row(articulo=900, descuento=25.0),
                    _wapi_enriched_row(articulo=901, descuento=15.0),
                ]
            )
        )
        total = df.iloc[-1]
        assert total["SUCURSAL"] == TOTAL_GENERAL_LABEL
        assert total["Suma de Descuento"] == 40.0


# ─────────────────────────────────────────────────────────────────────────
# CLIENTE-FECHA (RF-09)
# ─────────────────────────────────────────────────────────────────────────


class TestClienteFecha:
    def test_exact_labels_and_shape_A_to_J(self):
        df = build_cliente_fecha(pd.DataFrame([_wapi_enriched_row()]))
        assert list(df.columns) == [
            "Fecha",
            "SUCURSAL",
            "Cod. Cliente",
            "Razón Social",
            "Artículo Distribuidora",
            "Descripción",
            "Calibre",
            "Acción",
            "Descripción Acción",
            "Suma de Descuento",
        ]
        assert df.shape[1] == 10  # A:J

    def test_total_general_row(self):
        df = build_cliente_fecha(
            pd.DataFrame(
                [
                    _wapi_enriched_row(cod_cliente=100, descuento=25.0),
                    _wapi_enriched_row(cod_cliente=101, descuento=15.0),
                ]
            )
        )
        total = df.iloc[-1]
        assert total["Fecha"] == TOTAL_GENERAL_LABEL
        assert total["Suma de Descuento"] == 40.0


# ─────────────────────────────────────────────────────────────────────────
# ACC-GEN (RF-09) — blank spacer at E, genéricos F:J
# ─────────────────────────────────────────────────────────────────────────


class TestAccGen:
    def test_column_layout_blank_spacer_and_genericos_F_to_J(self):
        df = build_acc_gen(pd.DataFrame([_wapi_enriched_row()]))
        cols = list(df.columns)
        # A:D row fields
        assert cols[:4] == ["SUCURSAL", "Acción", "Descripción Acción", "mvb"]
        # E blank spacer
        assert cols[4] == K.ACC_GEN_SPACER_COL
        # F:J genéricos in exact positional order
        assert cols[5:10] == [
            "CERVEZAS",
            "AGUAS DANONE",
            "VINOS CCU",
            "PERNOD RICARD",
            "SIDRAS Y LICORES",
        ]

    def test_shape_is_A_to_J_total_outside_paste(self):
        df = build_acc_gen(pd.DataFrame([_wapi_enriched_row()]))
        # exactly 10 columns (A:J); the genérico Total (col K) is OUTSIDE
        assert df.shape[1] == 10
        assert "Total" not in df.columns

    def test_spacer_column_is_blank(self):
        df = build_acc_gen(pd.DataFrame([_wapi_enriched_row()]))
        for value in df[K.ACC_GEN_SPACER_COL]:
            assert value == "" or pd.isna(value)

    def test_descuento_lands_under_correct_generico(self):
        df = build_acc_gen(
            pd.DataFrame(
                [
                    _wapi_enriched_row(calibre="CERVEZAS", descuento=25.0),
                    _wapi_enriched_row(calibre="VINOS CCU", descuento=40.0),
                ]
            )
        )
        # both rows share the same A:D group -> one data row + total
        leaf = df.iloc[0]
        assert leaf["CERVEZAS"] == 25.0
        assert leaf["VINOS CCU"] == 40.0
        assert leaf["AGUAS DANONE"] == 0.0

    def test_total_general_row(self):
        df = build_acc_gen(
            pd.DataFrame(
                [
                    _wapi_enriched_row(accion="ACC1", calibre="CERVEZAS", descuento=25.0),
                    _wapi_enriched_row(accion="ACC2", calibre="CERVEZAS", descuento=15.0),
                ]
            )
        )
        total = df.iloc[-1]
        assert total["SUCURSAL"] == TOTAL_GENERAL_LABEL
        assert total["CERVEZAS"] == 40.0


# ─────────────────────────────────────────────────────────────────────────
# floats preserved (RF-23) + S2.6 source audit
# ─────────────────────────────────────────────────────────────────────────


class TestNoRounding:
    def test_pivot_values_not_rounded(self):
        df = build_fact_net(
            pd.DataFrame([_aexcel_row(facturacion=100.123456, descuentos=10.987654)])
        )
        assert df.iloc[0]["Suma de Facturacion Neta"] == pytest.approx(100.123456, abs=1e-9)

    def test_no_rounding_or_int_cast_in_source(self):
        """S2.6 / RF-23: processor.py and pivots.py must contain no
        round()/int()/astype(int)/floor/ceil/trunc/// on report values."""
        here = Path(__file__).resolve()
        src_dir = here.parents[2] / "src" / "services" / "acciones_comerciales"
        forbidden_substrings = [
            "round(",
            "astype(int",
            "astype('int",
            'astype("int',
            "astype(np.int",
            "np.floor",
            "np.ceil",
            "np.trunc",
            "//",
        ]
        bare_int_call = re.compile(r"(?<![A-Za-z_.])int\s*\(")
        for name in ("processor.py", "pivots.py"):
            src = (src_dir / name).read_text(encoding="utf-8")
            for token in forbidden_substrings:
                assert token not in src, f"{name} contains forbidden token {token!r}"
            assert bare_int_call.search(src) is None, f"{name} contains a bare int() call"
