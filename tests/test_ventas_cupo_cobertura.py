"""Tests for the cobertura quota columns of the ventas report.

The report already carried the actual cobertura (client count) and the VOLUME
quota; these cover the cobertura QUOTA and its achievement percentage
(% = cobertura real / cupo cobertura, no projection).
"""
from unittest.mock import patch

import pandas as pd

from config.settings import COLUMN_NAMES
from src.services.ventas.processor import procesar_ventas_diarias


def _df_ventas():
    """Two marcas of one generico in one sucursal, one sale day each."""
    return pd.DataFrame({
        "sucursal": ["SUC1", "SUC1"],
        "generico": ["CERVEZAS", "CERVEZAS"],
        "marca": ["SALTA", "HEINEKEN"],
        "fecha": pd.to_datetime(["2026-01-05", "2026-01-05"]),
        "cantidad": [100.0, 50.0],
        "cantidad_htls": [10.0, 5.0],
        "monto": [5000.0, 2500.0],
    })


def _df_cob_generico():
    return pd.DataFrame({
        "sucursal": ["SUC1"],
        "generico": ["CERVEZAS"],
        "clientes_compradores": [32],
    })


def _df_cob_marca():
    return pd.DataFrame({
        "sucursal": ["SUC1", "SUC1"],
        "marca": ["SALTA", "HEINEKEN"],
        "clientes_compradores": [20, 8],
    })


def _df_cupos_cob():
    """Quota keyed by generico AND by marca, same as the real loader returns."""
    return pd.DataFrame({
        "sucursal": ["SUC1", "SUC1", "SUC1"],
        "cupo_cob_generico": ["CERVEZAS", "SALTA", "HEINEKEN"],
        "cupo": [64.0, 40.0, 16.0],
    })


def _procesar(**kwargs):
    with patch("src.core.base_processor.FERIADOS", []):
        return procesar_ventas_diarias(
            _df_ventas(), "2026-01-01", "2026-01-31",
            df_cob_generico=_df_cob_generico(),
            df_cob_marca=_df_cob_marca(),
            **kwargs,
        )


def test_columnas_de_cupo_cobertura_existen():
    """The four new columns are present in the output frame."""
    r = _procesar(df_cupos_cob=_df_cupos_cob())
    for key in ("cupo_cob_generico", "cob_vs_cupo_generico",
                "cupo_cob_marca", "cob_vs_cupo_marca"):
        assert COLUMN_NAMES[key] in r.columns


def test_cupo_cobertura_generico_solo_en_primera_fila():
    """Generico-level values repeat the report's convention: first row only."""
    r = _procesar(df_cupos_cob=_df_cupos_cob())
    assert r.iloc[0][COLUMN_NAMES["cupo_cob_generico"]] == 64.0
    assert pd.isna(r.iloc[1][COLUMN_NAMES["cupo_cob_generico"]])


def test_porcentaje_generico_es_cobertura_sobre_cupo():
    """% = cobertura real / cupo (32/64 = 50%), NOT projected."""
    r = _procesar(df_cupos_cob=_df_cupos_cob())
    assert r.iloc[0][COLUMN_NAMES["cob_vs_cupo_generico"]] == 0.5


def test_porcentaje_marca_es_cobertura_sobre_cupo():
    """Per-marca: SALTA 20/40 = 50%, HEINEKEN 8/16 = 50%."""
    r = _procesar(df_cupos_cob=_df_cupos_cob())
    por_marca = r.set_index(COLUMN_NAMES["marca"])[COLUMN_NAMES["cob_vs_cupo_marca"]]
    assert por_marca["SALTA"] == 0.5
    assert por_marca["HEINEKEN"] == 0.5


def test_cupo_cobertura_marca_se_asigna_por_marca():
    """Each marca gets its own quota, not the generico's."""
    r = _procesar(df_cupos_cob=_df_cupos_cob())
    por_marca = r.set_index(COLUMN_NAMES["marca"])[COLUMN_NAMES["cupo_cob_marca"]]
    assert por_marca["SALTA"] == 40.0
    assert por_marca["HEINEKEN"] == 16.0


def test_sin_cupos_cobertura_las_columnas_quedan_vacias():
    """No quota loaded -> columns exist but stay empty (never crash)."""
    r = _procesar(df_cupos_cob=None)
    assert COLUMN_NAMES["cupo_cob_generico"] in r.columns
    assert r[COLUMN_NAMES["cupo_cob_generico"]].isna().all()
    assert r[COLUMN_NAMES["cob_vs_cupo_generico"]].isna().all()
    assert r[COLUMN_NAMES["cob_vs_cupo_marca"]].isna().all()


def test_cupo_cero_no_divide_por_cero():
    """A zero/absent quota must not produce inf or a ZeroDivisionError."""
    df_cupos = pd.DataFrame({
        "sucursal": ["SUC1"],
        "cupo_cob_generico": ["CERVEZAS"],
        "cupo": [0.0],
    })
    r = _procesar(df_cupos_cob=df_cupos)
    assert pd.isna(r.iloc[0][COLUMN_NAMES["cob_vs_cupo_generico"]])


def test_cupo_cobertura_no_se_convierte_a_htls():
    """Cobertura quota is a CLIENT COUNT: identical in the Bultos and HTLs sheets."""
    bultos = _procesar(df_cupos_cob=_df_cupos_cob(), col_cantidad="cantidad")
    htls = _procesar(df_cupos_cob=_df_cupos_cob(), col_cantidad="cantidad_htls")
    assert bultos.iloc[0][COLUMN_NAMES["cupo_cob_generico"]] == 64.0
    assert htls.iloc[0][COLUMN_NAMES["cupo_cob_generico"]] == 64.0
    assert (
        bultos.iloc[0][COLUMN_NAMES["cob_vs_cupo_generico"]]
        == htls.iloc[0][COLUMN_NAMES["cob_vs_cupo_generico"]]
    )
