"""RED tests — S2.1: derived wapi columns (RF-04..RF-08).

Covers the ``processor`` module that turns the raw 21-column wapi table
(RF-02) into the enriched internal table with the derived V:AD columns:

  - SUCURSAL: FRESH lookup by ``Cod. Cliente`` (RF-04); unresolved -> blank
    + flagged (never silently defaulted to a wrong sucursal).
  - PRECIO FINAL : exact-match terna (fecha, cliente, articulo) lookup on the
    aexcel-equivalent picked-line price (RF-05, Decision 14 — an ACTUAL line
    value, never a blend). #N/A -> blank/flagged, with Total2/Descuento
    inheriting the blank state (never computed off a fabricated price).
  - mvb: 3-tier case-sensitive FIND priority MVB / (ESC.) / EXTRA TASA / OTRAS
    (RF-06).
  - ZONA: supervisor lookup keyed by SUCURSAL (RF-07); field name preserved.
  - Total2 = Cantidad * PRECIO FINAL; Descuento =
    IFERROR(Total2 * Desc%/100 + SinCargo * PRECIO FINAL, 0); Tipo Descuento
    = SIN CARGO when Desc% blank else Descuentos (RF-08).

Strict-TDD: written before ``processor.py`` exists (import fails RED).
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from src.services.acciones_comerciales.constants import (
    COL_CONCAT,
    COL_DESCUENTO,
    COL_MVB,
    COL_PRECIO_FINAL,
    COL_SUCURSAL,
    COL_TIPO_DESCUENTO,
    COL_TOTAL2,
    COL_ZONA,
)
from src.services.acciones_comerciales.processor import (
    EnrichedWapiResult,
    build_precio_lookup,
    classify_mvb,
    enrich_wapi,
    load_supervisor_por_sucursal,
)

# ─────────────────────────────────────────────────────────────────────────
# fixtures / builders
# ─────────────────────────────────────────────────────────────────────────

_WAPI_RAW_COLUMNS = [
    "Fecha",
    "Comprobante",
    "Agrupaciones",
    "Cod. Cliente",
    "Razón Social",
    "Dirección",
    "Artículo CMQ",
    "Descripción",
    "Marca",
    "Calibre",
    "Cantidad",
    "Precio Neto SF",
    "Total",
    "Cantidad Sin Cargo",
    "Descuento %",
    "Descuento $ sobre PN SF",
    "Participación CMQ",
    "Monto A Acreditar",
    "Acción",
    "Descripción Acción",
    "Artículo Distribuidora",
]


def _wapi_row(
    fecha="2026-07-01",
    cod_cliente=100,
    razon="CLIENTE UNO",
    descripcion="ART UNO",
    calibre="CERVEZAS",
    cantidad=20.0,
    cantidad_sin_cargo=0.0,
    descuento_pct=10.0,
    accion="ACC1",
    descripcion_accion="MVB PROMO",
    articulo_distribuidora=900,
) -> dict:
    return {
        "Fecha": fecha,
        "Comprobante": "FC-1",
        "Agrupaciones": "",
        "Cod. Cliente": cod_cliente,
        "Razón Social": razon,
        "Dirección": "",
        "Artículo CMQ": "CMQ1",
        "Descripción": descripcion,
        "Marca": "MARCA UNO",
        "Calibre": calibre,
        "Cantidad": cantidad,
        "Precio Neto SF": 45.0,
        "Total": 900.0,
        "Cantidad Sin Cargo": cantidad_sin_cargo,
        "Descuento %": descuento_pct,
        "Descuento $ sobre PN SF": 0.0,
        "Participación CMQ": 0.0,
        "Monto A Acreditar": 0.0,
        "Acción": accion,
        "Descripción Acción": descripcion_accion,
        "Artículo Distribuidora": articulo_distribuidora,
    }


def _wapi_df(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_WAPI_RAW_COLUMNS)


def _enrich(
    rows,
    *,
    sucursal_por_cliente=None,
    precio_por_terna=None,
    supervisor_por_sucursal=None,
) -> EnrichedWapiResult:
    if sucursal_por_cliente is None:
        sucursal_por_cliente = {100: "CASA CENTRAL"}
    if precio_por_terna is None:
        precio_por_terna = {("2026-07-01", 100, 900): 50.0}
    if supervisor_por_sucursal is None:
        supervisor_por_sucursal = {"CASA CENTRAL": "Antonio Cabrerizo"}
    return enrich_wapi(
        _wapi_df(rows),
        sucursal_por_cliente=sucursal_por_cliente,
        precio_por_terna=precio_por_terna,
        supervisor_por_sucursal=supervisor_por_sucursal,
    )


# ─────────────────────────────────────────────────────────────────────────
# RF-04 — SUCURSAL fresh lookup
# ─────────────────────────────────────────────────────────────────────────


class TestSucursalDerivation:
    def test_sucursal_resolved_from_fresh_lookup(self):
        result = _enrich([_wapi_row(cod_cliente=100)])
        assert result.data.iloc[0][COL_SUCURSAL] == "CASA CENTRAL"

    def test_sucursal_unresolved_is_blank_and_flagged(self):
        # cliente 999 has no entry in the sucursal lookup
        result = _enrich(
            [_wapi_row(cod_cliente=999)],
            sucursal_por_cliente={100: "CASA CENTRAL"},
        )
        assert pd.isna(result.data.iloc[0][COL_SUCURSAL])
        # flagged for the reconciliation sheet, never defaulted to a wrong sucursal
        assert len(result.unresolved_sucursal) == 1
        assert result.unresolved_sucursal.iloc[0]["Cod. Cliente"] == 999


# ─────────────────────────────────────────────────────────────────────────
# RF-05 — PRECIO FINAL exact-match terna lookup + #N/A fallback
# ─────────────────────────────────────────────────────────────────────────


class TestPrecioFinalDerivation:
    def test_precio_final_column_header_has_trailing_space(self):
        # byte-for-byte engine contract: the header ends with a space.
        assert COL_PRECIO_FINAL == "PRECIO FINAL "

    def test_precio_final_exact_terna_match(self):
        result = _enrich(
            [_wapi_row(fecha="2026-07-01", cod_cliente=100, articulo_distribuidora=900)],
            precio_por_terna={("2026-07-01", 100, 900): 50.0},
        )
        assert result.data.iloc[0][COL_PRECIO_FINAL] == 50.0

    def test_precio_final_is_actual_value_never_blended(self):
        # The lookup returns the picked-line value verbatim (Decision 14).
        result = _enrich(
            [_wapi_row(articulo_distribuidora=900)],
            precio_por_terna={("2026-07-01", 100, 900): 73.33},
        )
        assert result.data.iloc[0][COL_PRECIO_FINAL] == 73.33

    def test_precio_final_no_match_blank_and_flagged(self):
        result = _enrich(
            [_wapi_row(articulo_distribuidora=901)],  # no terna entry for 901
            precio_por_terna={("2026-07-01", 100, 900): 50.0},
        )
        row = result.data.iloc[0]
        assert pd.isna(row[COL_PRECIO_FINAL])
        assert len(result.unresolved_precio) == 1

    def test_total2_and_descuento_inherit_blank_when_precio_missing(self):
        # RF-08 exception: never computed against a fabricated price.
        result = _enrich(
            [_wapi_row(articulo_distribuidora=901, cantidad=20.0, descuento_pct=10.0)],
            precio_por_terna={("2026-07-01", 100, 900): 50.0},
        )
        row = result.data.iloc[0]
        assert pd.isna(row[COL_TOTAL2])
        assert pd.isna(row[COL_DESCUENTO])

    def test_build_precio_lookup_from_aexcel_terna_grain(self):
        aexcel = pd.DataFrame(
            [
                {"Descripción Período": "2026-07-01", "Cod. Cliente": 100, "Código": 900, "Precio": 50.0},
                {"Descripción Período": "2026-07-01", "Cod. Cliente": 101, "Código": 900, "Precio": 60.0},
            ]
        )
        lookup = build_precio_lookup(aexcel)
        assert lookup[("2026-07-01", 100, 900)] == 50.0
        assert lookup[("2026-07-01", 101, 900)] == 60.0


# ─────────────────────────────────────────────────────────────────────────
# RF-06 — mvb 3-tier classifier
# ─────────────────────────────────────────────────────────────────────────


class TestMvbClassifier:
    def test_mvb_wins_over_extra_tasa(self):
        assert classify_mvb("MVB Y EXTRA TASA JUNTOS") == "MVB"

    def test_esc_tier(self):
        assert classify_mvb("PROMO (ESC.) VIGENTE") == "ESC"

    def test_extra_tasa_tier(self):
        assert classify_mvb("SOLO EXTRA TASA") == "EXTRA TASA"

    def test_otras_default(self):
        assert classify_mvb("PROMO GENERICA") == "OTRAS"

    def test_case_sensitive_find_semantics(self):
        # lowercase "mvb" must NOT match the uppercase-only tier.
        assert classify_mvb("promo mvb minuscula") == "OTRAS"

    def test_esc_before_extra_tasa_priority(self):
        assert classify_mvb("(ESC.) CON EXTRA TASA") == "ESC"

    def test_mvb_column_populated_in_enriched_frame(self):
        result = _enrich([_wapi_row(descripcion_accion="MVB PROMO")])
        assert result.data.iloc[0][COL_MVB] == "MVB"


# ─────────────────────────────────────────────────────────────────────────
# RF-07 — ZONA (supervisor) derivation
# ─────────────────────────────────────────────────────────────────────────


class TestZonaDerivation:
    def test_zona_is_supervisor_keyed_by_sucursal(self):
        result = _enrich(
            [_wapi_row(cod_cliente=100)],
            sucursal_por_cliente={100: "CASA CENTRAL"},
            supervisor_por_sucursal={"CASA CENTRAL": "Antonio Cabrerizo"},
        )
        assert result.data.iloc[0][COL_ZONA] == "Antonio Cabrerizo"

    def test_zona_blank_when_sucursal_unresolved(self):
        result = _enrich(
            [_wapi_row(cod_cliente=999)],
            sucursal_por_cliente={100: "CASA CENTRAL"},
            supervisor_por_sucursal={"CASA CENTRAL": "Antonio Cabrerizo"},
        )
        assert pd.isna(result.data.iloc[0][COL_ZONA])


# ─────────────────────────────────────────────────────────────────────────
# RF-08 — Total2, Descuento, Tipo Descuento
# ─────────────────────────────────────────────────────────────────────────


class TestTotal2AndDescuento:
    def test_total2_is_cantidad_times_precio_final(self):
        result = _enrich(
            [_wapi_row(cantidad=20.0)],
            precio_por_terna={("2026-07-01", 100, 900): 50.0},
        )
        assert result.data.iloc[0][COL_TOTAL2] == 1000.0

    def test_descuento_normal_formula(self):
        # Total2=1000 (20*50), Desc%=10, SinCargo=2, PrecioFinal=50
        # -> 1000*10/100 + 2*50 = 100 + 100 = 200
        result = _enrich(
            [_wapi_row(cantidad=20.0, descuento_pct=10.0, cantidad_sin_cargo=2.0)],
            precio_por_terna={("2026-07-01", 100, 900): 50.0},
        )
        assert result.data.iloc[0][COL_DESCUENTO] == 200.0

    def test_descuento_error_safe_fallback_zero(self):
        # Price present but Desc% is non-numeric text -> IFERROR -> 0
        # (NOT blank — blank is reserved for the missing-price case).
        result = _enrich(
            [_wapi_row(cantidad=20.0, descuento_pct="N/A")],
            precio_por_terna={("2026-07-01", 100, 900): 50.0},
        )
        assert result.data.iloc[0][COL_DESCUENTO] == 0.0

    def test_sin_cargo_blank_pct_uses_free_goods_value(self):
        # Blank Desc% behaves like Excel blank (0 in arithmetic), so the
        # discount is the free-goods value: 0 + SinCargo*PrecioFinal.
        result = _enrich(
            [_wapi_row(cantidad=0.0, descuento_pct=None, cantidad_sin_cargo=3.0)],
            precio_por_terna={("2026-07-01", 100, 900): 50.0},
        )
        assert result.data.iloc[0][COL_DESCUENTO] == 150.0

    def test_tipo_descuento_sin_cargo_when_pct_blank(self):
        result = _enrich([_wapi_row(descuento_pct=None)])
        assert result.data.iloc[0][COL_TIPO_DESCUENTO] == "SIN CARGO"

    def test_tipo_descuento_descuentos_when_pct_present(self):
        result = _enrich([_wapi_row(descuento_pct=10.0)])
        assert result.data.iloc[0][COL_TIPO_DESCUENTO] == "Descuentos"


# ─────────────────────────────────────────────────────────────────────────
# CONCAT (informe wapi W column) + no-rounding guard
# ─────────────────────────────────────────────────────────────────────────


class TestConcatAndNoRounding:
    def test_concat_is_fecha_cliente_articulo(self):
        result = _enrich(
            [_wapi_row(fecha="2026-07-01", cod_cliente=100, articulo_distribuidora=900)]
        )
        concat = result.data.iloc[0][COL_CONCAT]
        assert "2026-07-01" in concat
        assert "100" in concat
        assert "900" in concat

    def test_values_are_not_rounded(self):
        result = _enrich(
            [_wapi_row(cantidad=20.0, descuento_pct=10.0, cantidad_sin_cargo=0.0)],
            precio_por_terna={("2026-07-01", 100, 900): 45.678901},
        )
        row = result.data.iloc[0]
        # Total2 = 20 * 45.678901 = 913.57802 exactly, unrounded
        assert row[COL_TOTAL2] == pytest.approx(913.57802, abs=1e-9)

    def test_raw_wapi_columns_preserved_in_enriched_frame(self):
        result = _enrich([_wapi_row()])
        for col in _WAPI_RAW_COLUMNS:
            assert col in result.data.columns


# ─────────────────────────────────────────────────────────────────────────
# S2.5 — sucursal->supervisor mapping (config JSON) loader
# ─────────────────────────────────────────────────────────────────────────


class TestSupervisorMappingLoader:
    def test_load_from_config_json(self, tmp_path):
        cfg = tmp_path / "zonas.json"
        cfg.write_text(
            json.dumps(
                {
                    "sucursal_supervisor": {"CASA CENTRAL": "Antonio Cabrerizo"},
                    "_note": "ignored metadata key",
                }
            ),
            encoding="utf-8",
        )
        mapping = load_supervisor_por_sucursal(cfg)
        assert mapping == {"CASA CENTRAL": "Antonio Cabrerizo"}

    def test_repo_config_file_loads_and_maps_casa_central(self):
        # the shipped config must exist and cover CASA CENTRAL (RF-07 scenario)
        mapping = load_supervisor_por_sucursal(
            "configs/acciones_comerciales_zonas.json"
        )
        assert isinstance(mapping, dict)
        assert mapping  # non-empty
        assert "CASA CENTRAL" in mapping
        assert isinstance(mapping["CASA CENTRAL"], str)
        assert mapping["CASA CENTRAL"]  # non-empty supervisor name
