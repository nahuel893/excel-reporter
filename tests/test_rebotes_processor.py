"""Tests for rebotes service: processor functions."""

import pytest
import pandas as pd

from src.services.rebotes.processor import (
    agregar_totales_supervisor,
    calcular_rebotes_vendedor,
)
from src.services.rebotes.constants import SUPERVISOR_VENDOR_MAP


class TestCalcularRebotesVendedor:
    """Tests para calcular_rebotes_vendedor()."""

    def test_pct_rechazo_cero_cuando_rechazados_zero(self):
        """bultos_rechazados=0 -> % rechazo=0."""
        df = pd.DataFrame({
            "vendedor": ["JUAN PEREZ"],
            "bultos_vendidos": [100],
            "bultos_rechazados": [0],
            "id_fuerza_ventas": [1],
        })
        result = calcular_rebotes_vendedor(df)
        assert result["% Rechazo"].iloc[0] == 0.0

    def test_pct_rechazo_normal(self):
        """25 rechazados de 100 = 0.25."""
        df = pd.DataFrame({
            "vendedor": ["JUAN PEREZ"],
            "bultos_vendidos": [100],
            "bultos_rechazados": [25],
            "id_fuerza_ventas": [1],
        })
        result = calcular_rebotes_vendedor(df)
        assert result["% Rechazo"].iloc[0] == 0.25

    def test_division_por_cero_bultos_vendidos_cero(self):
        """bultos_vendidos=0 -> % rechazo=0 (no crash)."""
        df = pd.DataFrame({
            "vendedor": ["JUAN PEREZ"],
            "bultos_vendidos": [0],
            "bultos_rechazados": [0],
            "id_fuerza_ventas": [1],
        })
        result = calcular_rebotes_vendedor(df)
        assert result["% Rechazo"].iloc[0] == 0.0

    def test_empty_dataframe(self):
        """Empty DF returns DF with % Rechazo column (no crash)."""
        df = pd.DataFrame(columns=["vendedor", "bultos_vendidos", "bultos_rechazados", "id_fuerza_ventas"])
        result = calcular_rebotes_vendedor(df)
        assert "% Rechazo" in result.columns
        assert result.empty


class TestAgregarTotalesSupervisor:
    """Tests para agregar_totales_supervisor()."""

    def test_gfarah_representa_total_general_y_preserva_supervisores_reales(self):
        """GFARAH debe ser el total global sin romper los agregados reales."""
        supervisor_map = {
            "FGUANTAY": ["AGUIRRE ETHEL", "GONZALEZ INES"],
            "VCHAPUR": ["CRUZ IGNACIO"],
            "GFARAH": ["VENDEDOR DIRECTA"],
        }
        df = pd.DataFrame({
            "vendedor": [
                "AGUIRRE ETHEL",
                "GONZALEZ INES",
                "CRUZ IGNACIO",
                "VENDEDOR DIRECTA",
            ],
            "bultos_vendidos": [100, 50, 200, 50],
            "bultos_rechazados": [10, 5, 20, 15],
            "id_fuerza_ventas": [1, 1, 1, 1],
        })

        _, supervisor_df = agregar_totales_supervisor(df, supervisor_map)

        assert supervisor_df["Supervisor"].tolist() == ["FGUANTAY", "VCHAPUR", "GFARAH"]

        fguantay_row = supervisor_df[supervisor_df["Supervisor"] == "FGUANTAY"].iloc[0]
        assert fguantay_row["Bultos Vendidos"] == 150
        assert fguantay_row["Bultos Rechazados"] == 15
        assert fguantay_row["% Rechazo"] == pytest.approx(0.1)

        vchapur_row = supervisor_df[supervisor_df["Supervisor"] == "VCHAPUR"].iloc[0]
        assert vchapur_row["Bultos Vendidos"] == 200
        assert vchapur_row["Bultos Rechazados"] == 20
        assert vchapur_row["% Rechazo"] == pytest.approx(0.1)

        gfarah_row = supervisor_df[supervisor_df["Supervisor"] == "GFARAH"].iloc[0]
        assert gfarah_row["Bultos Vendidos"] == 400
        assert gfarah_row["Bultos Rechazados"] == 50
        assert gfarah_row["% Rechazo"] == pytest.approx(0.125)

    def test_agregacion_correcta_dos_supervisores(self):
        """Vendedores asignados a supervisors correctos."""
        df = pd.DataFrame({
            "vendedor": ["AGUIRRE ETHEL", "GONZALEZ INES", "CRUZ IGNACIO"],
            "bultos_vendidos": [100, 50, 200],
            "bultos_rechazados": [5, 0, 10],
            "id_fuerza_ventas": [1, 1, 1],
        })
        vendor_df, supervisor_df = agregar_totales_supervisor(df, SUPERVISOR_VENDOR_MAP)

        # Vendedor section should have all 3 vendors
        assert len(vendor_df) == 3
        assert "Supervisor" in vendor_df.columns

        # Supervisor section should keep real supervisors and add GFARAH total
        assert len(supervisor_df) == 3

        fguantay_row = supervisor_df[supervisor_df["Supervisor"] == "FGUANTAY"].iloc[0]
        assert fguantay_row["Bultos Vendidos"] == 150
        assert fguantay_row["Bultos Rechazados"] == 5

        vchapur_row = supervisor_df[supervisor_df["Supervisor"] == "VCHAPUR"].iloc[0]
        assert vchapur_row["Bultos Vendidos"] == 200
        assert vchapur_row["Bultos Rechazados"] == 10

        gfarah_row = supervisor_df[supervisor_df["Supervisor"] == "GFARAH"].iloc[0]
        assert gfarah_row["Bultos Vendidos"] == 350
        assert gfarah_row["Bultos Rechazados"] == 15

    def test_vendor_no_en_mapa_asigna_sin_supervisor(self):
        """Vendor desconocido -> 'Sin Supervisor'."""
        df = pd.DataFrame({
            "vendedor": ["VENDEDOR DESCONOCIDO"],
            "bultos_vendidos": [99],
            "bultos_rechazados": [0],
            "id_fuerza_ventas": [1],
        })
        vendor_df, supervisor_df = agregar_totales_supervisor(df, SUPERVISOR_VENDOR_MAP)

        sin_sup = vendor_df[vendor_df["Supervisor"] == "Sin Supervisor"]
        assert len(sin_sup) == 1

        sin_row = supervisor_df[supervisor_df["Supervisor"] == "Sin Supervisor"].iloc[0]
        assert sin_row["Bultos Vendidos"] == 99

    def test_pct_rechazo_agregado_correctamente(self):
        """Supervisor aggregate recalcula % correctamente."""
        df = pd.DataFrame({
            "vendedor": ["AGUIRRE ETHEL", "GONZALEZ INES"],
            "bultos_vendidos": [100, 100],
            "bultos_rechazados": [10, 10],  # 20/200 = 10%
            "id_fuerza_ventas": [1, 1],
        })
        _, supervisor_df = agregar_totales_supervisor(df, SUPERVISOR_VENDOR_MAP)

        row = supervisor_df[supervisor_df["Supervisor"] == "FGUANTAY"].iloc[0]
        assert row["% Rechazo"] == pytest.approx(0.1)

    def test_empty_dataframe(self):
        """Empty DF returns empty vendor_df and supervisor_df with correct columns."""
        df = pd.DataFrame(columns=["vendedor", "bultos_vendidos", "bultos_rechazados", "id_fuerza_ventas"])
        vendor_df, supervisor_df = agregar_totales_supervisor(df, SUPERVISOR_VENDOR_MAP)
        assert vendor_df.empty
        assert supervisor_df.empty

    def test_supervisor_sin_vendedores(self):
        """Supervisor key with no vendors in df: not present in supervisor section."""
        df = pd.DataFrame({
            "vendedor": ["CRUZ IGNACIO"],  # Only VCHAPUR
            "bultos_vendidos": [100],
            "bultos_rechazados": [0],
            "id_fuerza_ventas": [1],
        })
        _, supervisor_df = agregar_totales_supervisor(df, SUPERVISOR_VENDOR_MAP)

        supervisors = supervisor_df["Supervisor"].tolist()
        assert "FGUANTAY" not in supervisors
        assert "GFLORES" not in supervisors
        assert "VCHAPUR" in supervisors
