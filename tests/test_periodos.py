"""Tests for src.core.periodos — previous-month range and month labels.

These helpers exist so no config ever hardcodes a month name. A hardcoded month
is the root cause of the long-standing schneider-710 capture failure: the daily
patches fechas but not names, so the config silently drifts out of the period
once the month rolls over.
"""
import pytest

from src.core.periodos import (
    etiqueta_mes,
    meses_abarcados,
    periodo_mes,
    rango_mes_anterior,
)


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


class TestMesesAbarcados:
    """Cuantos meses calendario toca un rango — ambos extremos inclusive."""

    def test_un_mes_incompleto_sigue_siendo_un_mes(self):
        assert meses_abarcados("2026-08-01", "2026-08-10") == 1

    def test_junio_a_agosto_son_tres(self):
        assert meses_abarcados("2026-06-01", "2026-08-10") == 3

    def test_cruza_el_anio(self):
        assert meses_abarcados("2025-11-15", "2026-02-03") == 4

    def test_mismo_dia_es_un_mes(self):
        assert meses_abarcados("2026-08-10", "2026-08-10") == 1

    def test_rango_invertido_es_un_error_de_config(self):
        with pytest.raises(ValueError, match="rango invertido"):
            meses_abarcados("2026-08-10", "2026-06-01")

    def test_fecha_no_iso(self):
        with pytest.raises(ValueError):
            meses_abarcados("10/08/2026", "2026-08-10")


# --- rango_mes --------------------------------------------------------------


def test_rango_mes_devuelve_el_mes_calendario_entero():
    from src.core.periodos import rango_mes

    assert rango_mes("2026-07-14") == ("2026-07-01", "2026-07-31")
    assert rango_mes("2026-08-01") == ("2026-08-01", "2026-08-31")


def test_rango_mes_saca_el_ultimo_dia_del_calendario_no_de_una_tabla():
    """Febrero bisiesto: 29, no 28."""
    from src.core.periodos import rango_mes

    assert rango_mes("2024-02-10") == ("2024-02-01", "2024-02-29")
    assert rango_mes("2026-02-10") == ("2026-02-01", "2026-02-28")


def test_rango_mes_compone_con_periodo_meses_atras():
    """Asi derivan los informes su mes anterior y su mismo mes del anio pasado."""
    from src.core.periodos import periodo_meses_atras, rango_mes

    hasta = "2026-08-21"
    assert rango_mes(periodo_meses_atras(hasta, 1)) == ("2026-07-01", "2026-07-31")
    assert rango_mes(periodo_meses_atras(hasta, 12)) == ("2025-08-01", "2025-08-31")


def test_rango_mes_rechaza_una_fecha_que_no_es_iso():
    import pytest

    from src.core.periodos import rango_mes

    with pytest.raises(ValueError):
        rango_mes("14/07/2026")
