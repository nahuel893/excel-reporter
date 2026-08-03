"""Tests for src.core.periodos — previous-month range and month labels.

These helpers exist so no config ever hardcodes a month name. A hardcoded month
is the root cause of the long-standing schneider-710 capture failure: the daily
patches fechas but not names, so the config silently drifts out of the period
once the month rolls over.
"""
import pytest

from src.core.periodos import etiqueta_mes, periodo_mes, rango_mes_anterior


class TestPeriodoMes:
    @pytest.mark.parametrize(
        "fecha,esperado",
        [
            ("2026-08-03", "2026-08-01"),
            ("2026-08-01", "2026-08-01"),
            ("2026-07-31", "2026-07-01"),
            ("2025-12-25", "2025-12-01"),
        ],
    )
    def test_first_day_of_month(self, fecha, esperado):
        assert periodo_mes(fecha) == esperado

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            periodo_mes("no-es-fecha")


class TestRangoMesAnterior:
    def test_mid_year(self):
        assert rango_mes_anterior("2026-08-03") == ("2026-07-01", "2026-07-31")

    def test_from_first_day_of_month(self):
        assert rango_mes_anterior("2026-08-01") == ("2026-07-01", "2026-07-31")

    def test_crosses_year_boundary(self):
        assert rango_mes_anterior("2026-01-15") == ("2025-12-01", "2025-12-31")

    def test_previous_month_is_february_leap_year(self):
        assert rango_mes_anterior("2028-03-10") == ("2028-02-01", "2028-02-29")

    def test_previous_month_is_february_common_year(self):
        assert rango_mes_anterior("2026-03-10") == ("2026-02-01", "2026-02-28")

    def test_previous_month_is_30_days(self):
        assert rango_mes_anterior("2026-05-31") == ("2026-04-01", "2026-04-30")

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            rango_mes_anterior("no-es-fecha")


class TestEtiquetaMes:
    @pytest.mark.parametrize(
        "fecha,esperado",
        [
            ("2026-01-01", "ENERO 2026"),
            ("2026-07-31", "JULIO 2026"),
            ("2026-08-03", "AGOSTO 2026"),
            ("2025-12-25", "DICIEMBRE 2025"),
        ],
    )
    def test_uppercase_spanish_month_and_year(self, fecha, esperado):
        assert etiqueta_mes(fecha) == esperado

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            etiqueta_mes("2026-13-01")
