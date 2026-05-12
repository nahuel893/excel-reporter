"""Tests for GraficosCoberturaConfig dataclass."""
import pytest

from src.services.graficos_cobertura.config import GraficosCoberturaConfig


class TestGraficosCoberturaConfigDefaults:
    """RF-001: dataclass fields and defaults."""

    def test_required_fields(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-04-30",
        )
        assert config.fecha_desde == "2026-01-01"
        assert config.fecha_hasta == "2026-04-30"

    def test_defaults(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-04-30",
        )
        assert config.id_fuerza_ventas == 1
        assert config.nombre_archivo is None
        assert config.con_aguas is True

    def test_override_defaults(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-04-30",
            id_fuerza_ventas=2,
            nombre_archivo="custom",
            con_aguas=False,
        )
        assert config.id_fuerza_ventas == 2
        assert config.nombre_archivo == "custom"
        assert config.con_aguas is False


class TestGraficosCoberturaConfigDerivedProps:
    """RF-001: derived properties anio_actual / anio_anterior / anios_lineas / anios_barras / mes_corte."""

    def test_anio_actual_from_fecha_hasta(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2025-01-01",
            fecha_hasta="2026-04-30",
        )
        assert config.anio_actual == 2026

    def test_anio_anterior_is_actual_minus_one(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2025-01-01",
            fecha_hasta="2026-04-30",
        )
        assert config.anio_anterior == 2025

    def test_anios_lineas_is_three_year_window(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2025-01-01",
            fecha_hasta="2026-04-30",
        )
        assert config.anios_lineas == [2024, 2025, 2026]

    def test_anios_barras_is_two_year_tuple(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2025-01-01",
            fecha_hasta="2026-04-30",
        )
        assert config.anios_barras == (2025, 2026)

    def test_mes_corte_from_fecha_hasta(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2025-01-01",
            fecha_hasta="2026-04-30",
        )
        assert config.mes_corte == 4

    def test_anios_rollover_different_year(self):
        """Triangulation: different year produces different derived values."""
        config = GraficosCoberturaConfig(
            fecha_desde="2023-01-01",
            fecha_hasta="2024-11-15",
        )
        assert config.anio_actual == 2024
        assert config.anio_anterior == 2023
        assert config.anios_lineas == [2022, 2023, 2024]
        assert config.anios_barras == (2023, 2024)
        assert config.mes_corte == 11


class TestGraficosCoberturaConfigValidation:
    """RF-001: __post_init__ validation."""

    def test_invalid_fecha_desde_raises(self):
        with pytest.raises(ValueError, match="fecha_desde"):
            GraficosCoberturaConfig(
                fecha_desde="not-a-date",
                fecha_hasta="2026-04-30",
            )

    def test_invalid_fecha_hasta_raises(self):
        with pytest.raises(ValueError, match="fecha_hasta"):
            GraficosCoberturaConfig(
                fecha_desde="2026-01-01",
                fecha_hasta="30-04-2026",
            )

    def test_fecha_desde_after_fecha_hasta_raises(self):
        with pytest.raises(ValueError, match="fecha_desde"):
            GraficosCoberturaConfig(
                fecha_desde="2026-06-01",
                fecha_hasta="2026-04-30",
            )

    def test_equal_fechas_allowed(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2026-04-30",
            fecha_hasta="2026-04-30",
        )
        assert config.fecha_desde == config.fecha_hasta

    def test_id_fuerza_ventas_zero_raises(self):
        with pytest.raises(ValueError, match="id_fuerza_ventas"):
            GraficosCoberturaConfig(
                fecha_desde="2026-01-01",
                fecha_hasta="2026-04-30",
                id_fuerza_ventas=0,
            )

    def test_id_fuerza_ventas_negative_raises(self):
        with pytest.raises(ValueError, match="id_fuerza_ventas"):
            GraficosCoberturaConfig(
                fecha_desde="2026-01-01",
                fecha_hasta="2026-04-30",
                id_fuerza_ventas=-1,
            )


class TestGraficosCoberturaConfigSucursalSlides:
    """T-003: con_sucursal_slides flag."""

    def test_default_is_false(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-04-30",
        )
        assert config.con_sucursal_slides is False

    def test_can_set_to_true(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-04-30",
            con_sucursal_slides=True,
        )
        assert config.con_sucursal_slides is True

    def test_can_set_to_false_explicitly(self):
        config = GraficosCoberturaConfig(
            fecha_desde="2026-01-01",
            fecha_hasta="2026-04-30",
            con_sucursal_slides=False,
        )
        assert config.con_sucursal_slides is False

    def test_con_sucursal_slides_true_emits_warning(self, caplog):
        """Triangulation: setting con_sucursal_slides=True should log a warning."""
        import logging
        with caplog.at_level(logging.WARNING):
            GraficosCoberturaConfig(
                fecha_desde="2026-01-01",
                fecha_hasta="2026-04-30",
                con_sucursal_slides=True,
            )
        assert any("con_sucursal_slides" in record.message for record in caplog.records)

    def test_con_sucursal_slides_false_no_warning(self, caplog):
        """Triangulation: con_sucursal_slides=False should NOT log a warning."""
        import logging
        with caplog.at_level(logging.WARNING):
            GraficosCoberturaConfig(
                fecha_desde="2026-01-01",
                fecha_hasta="2026-04-30",
                con_sucursal_slides=False,
            )
        assert not any("con_sucursal_slides" in record.message for record in caplog.records)
