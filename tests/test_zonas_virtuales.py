"""
Tests for ZONAS_VIRTUALES config changes (RF-005).
T-002: RED tests — ruta 93 -> SUB DISTRIBUIDORES; ruta 93 NOT in VALLE SALTA.
"""
import pytest
from config.settings import ZONAS_VIRTUALES


class TestZonasVirtualesSplit:
    """Verifies ZONAS_VIRTUALES config: VALLE SALTA vs SUB DISTRIBUIDORES split."""

    def test_sub_distribuidores_entry_exists(self):
        """T-002: SUB DISTRIBUIDORES must be a key in ZONAS_VIRTUALES."""
        assert "SUB DISTRIBUIDORES" in ZONAS_VIRTUALES

    def test_sub_distribuidores_sucursal_real_is_casa_central(self):
        """T-002: SUB DISTRIBUIDORES.sucursal_real must be 'CASA CENTRAL'."""
        assert ZONAS_VIRTUALES["SUB DISTRIBUIDORES"]["sucursal_real"] == "CASA CENTRAL"

    def test_sub_distribuidores_contains_ruta_93(self):
        """T-002: SUB DISTRIBUIDORES.rutas must contain 93."""
        assert 93 in ZONAS_VIRTUALES["SUB DISTRIBUIDORES"]["rutas"]

    def test_valle_salta_does_not_contain_ruta_93(self):
        """T-002: VALLE SALTA.rutas must NOT contain 93."""
        assert "VALLE SALTA" in ZONAS_VIRTUALES
        assert 93 not in ZONAS_VIRTUALES["VALLE SALTA"]["rutas"]

    def test_valle_salta_still_contains_other_rutas(self):
        """T-002: VALLE SALTA must still contain its other routes (e.g. 81, 82)."""
        rutas = ZONAS_VIRTUALES["VALLE SALTA"]["rutas"]
        assert 81 in rutas
        assert 82 in rutas
        assert 122 in rutas

    def test_rutas_are_disjoint_between_zones(self):
        """T-002: VALLE SALTA and SUB DISTRIBUIDORES rutas must be disjoint sets."""
        valle_rutas = set(ZONAS_VIRTUALES["VALLE SALTA"]["rutas"])
        sub_rutas = set(ZONAS_VIRTUALES["SUB DISTRIBUIDORES"]["rutas"])
        assert valle_rutas.isdisjoint(sub_rutas), (
            f"Rutas in both zones: {valle_rutas & sub_rutas}"
        )
