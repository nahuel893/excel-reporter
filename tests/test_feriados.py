"""Tests for src.core.feriados — month holidays lookup + WhatsApp notification text.

Pure unit tests, no I/O. Uses explicit years/months (no date.today()) so the
suite stays deterministic.
"""
from datetime import date

from src.core.feriados import feriados_del_mes, formatear_notificacion_feriados


class TestFeriadosDelMes:
    def test_julio_2026_incluye_independencia_y_turistico(self):
        """July 2026 has Independence Day (09) and the tourism holiday (10)."""
        feriados = feriados_del_mes(2026, 7)
        fechas = [f for f, _ in feriados]

        assert date(2026, 7, 9) in fechas
        assert date(2026, 7, 10) in fechas

        # motivo for Independence Day carries the library's holiday name
        motivo_9 = next(m for f, m in feriados if f == date(2026, 7, 9))
        assert "Independencia" in motivo_9

    def test_julio_2026_no_incluye_otros_meses(self):
        """Result for July must not leak June or August dates."""
        feriados = feriados_del_mes(2026, 7)
        for fecha, _ in feriados:
            assert fecha.year == 2026
            assert fecha.month == 7

    def test_junio_2026_incluye_guemes_provincial(self):
        """June 2026 (Salta) has Güemes (15), the provincial Salta day (17), Belgrano (20)."""
        feriados = feriados_del_mes(2026, 6)
        fechas = [f for f, _ in feriados]

        assert date(2026, 6, 15) in fechas
        assert date(2026, 6, 17) in fechas
        assert date(2026, 6, 20) in fechas

    def test_septiembre_2026_incluye_virgen_del_milagro(self):
        """September 2026 (Salta subdiv) has the 3 Virgen del Milagro days."""
        feriados = feriados_del_mes(2026, 9)
        fechas = [f for f, _ in feriados]

        assert date(2026, 9, 13) in fechas
        assert date(2026, 9, 14) in fechas
        assert date(2026, 9, 15) in fechas

    def test_result_sorted_by_date(self):
        """Holidays must be returned sorted by date ascending."""
        feriados = feriados_del_mes(2026, 9)
        fechas = [f for f, _ in feriados]
        assert fechas == sorted(fechas)


class TestFormatearNotificacionFeriados:
    def test_non_empty_formats_each_line(self):
        feriados = [
            (date(2026, 7, 9), "Día de la Independencia"),
            (date(2026, 7, 10), "Feriado con fines turísticos"),
        ]
        texto = formatear_notificacion_feriados(feriados, "AVANCE BADIE - JULIO 2026")

        assert "AVANCE BADIE - JULIO 2026" in texto
        assert "- 09/07: Día de la Independencia" in texto
        assert "- 10/07: Feriado con fines turísticos" in texto

    def test_empty_returns_sin_feriados_message(self):
        texto = formatear_notificacion_feriados([], "AVANCE BADIE - ABRIL 2026")

        assert "sin feriados" in texto.lower()
        assert "AVANCE BADIE - ABRIL 2026" in texto
