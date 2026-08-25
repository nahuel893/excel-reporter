"""Regression: `incluir_mes_anterior` must survive merge_filters.

A new filter needs FOUR edits: the model field, the merge_filters defaults dict,
its `if ... is not None` branch, and the main.py handler. Forgetting the branch
drops the flag SILENTLY — the report generates fine, just without the feature.
That is exactly how `solo_con_cargo` shipped broken (a client total came out
1101.96 instead of 1032.63 and nothing errored), so this flag gets its own test.
"""
from src.config.models import GlobalFilters, ReportFilters
from src.config.resolver import merge_filters


def _global():
    return GlobalFilters(fecha_desde="2026-08-01", fecha_hasta="2026-08-03")


def test_default_is_false_when_no_report_filters():
    assert merge_filters(_global(), None)["incluir_mes_anterior"] is False


def test_default_is_false_when_report_filters_omit_it():
    merged = merge_filters(_global(), ReportFilters(marcas=["FULL SPORT"]))
    assert merged["incluir_mes_anterior"] is False


def test_report_filter_true_reaches_merged():
    merged = merge_filters(_global(), ReportFilters(incluir_mes_anterior=True))
    assert merged["incluir_mes_anterior"] is True


def test_report_filter_false_is_not_swallowed_as_none():
    """False is a real value, not 'inherit' — `is not None` must let it through."""
    merged = merge_filters(_global(), ReportFilters(incluir_mes_anterior=False))
    assert merged["incluir_mes_anterior"] is False


# ── objetivo_cobertura / clausula_gatillo ────────────────────────────────────
# Misma regla de 4 lugares: modelo, defaults, rama del merge y handler.

def test_objetivo_y_gatillo_default_a_none():
    merged = merge_filters(_global(), ReportFilters(marcas=["FULL SPORT"]))
    assert merged["objetivo_cobertura"] is None
    assert merged["clausula_gatillo"] is None


def test_objetivo_cobertura_llega_al_merged():
    obj = {"marca": "SALTA", "pct_anterior": 0.20, "pct_actual": 0.25,
           "base_actual": "anterior"}
    merged = merge_filters(_global(), ReportFilters(objetivo_cobertura=obj))
    assert merged["objetivo_cobertura"] == obj


def test_clausula_gatillo_llega_al_merged():
    merged = merge_filters(_global(), ReportFilters(clausula_gatillo=1800))
    assert merged["clausula_gatillo"] == 1800
