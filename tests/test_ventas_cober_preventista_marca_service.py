"""Tests for VentasCoberPreventistaMarcaService."""
import pandas as pd
from unittest.mock import MagicMock, patch

from openpyxl import load_workbook

from src.core.data_loader import DataLoader
from src.services.ventas_cober_preventista_marca import (
    VentasCoberPreventistaMarcaConfig,
    VentasCoberPreventistaMarcaService,
)


def _raw():
    """Client 1 bought from FGUANTAY (LORENA) AND VCHAPUR (NAHUEL) → distinct-count test."""
    return pd.DataFrame({
        "vendedor": ["LORENA TARITOLAY", "LORENA TARITOLAY", "NAHUEL RUEDA", "DIRECTA"],
        "id_cliente": [1, 2, 1, 3],
        "bultos": [10.0, 5.0, 8.0, 3.0],
    })


def _sheet_rows(ruta):
    ws = load_workbook(ruta).active
    return [[ws.cell(r, c).value for c in range(1, 5)] for r in range(1, ws.max_row + 1)]


def _make(tmp_path, raw):
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_cobertura_por_vendedor.return_value = raw
    service = VentasCoberPreventistaMarcaService(data_loader=loader)
    config = VentasCoberPreventistaMarcaConfig(
        marca="FULL SPORT", fecha_desde="2026-07-01", fecha_hasta="2026-07-31", id_sucursal=1,
    )
    with patch("src.services.ventas_cober_preventista_marca.service.service_output_dir",
               return_value=tmp_path):
        return service.generar_reporte(config), loader


def test_composite_key_query_args(tmp_path):
    result, loader = _make(tmp_path, _raw())
    _, kwargs = loader.get_ventas_cobertura_por_vendedor.call_args
    assert kwargs["marca"] == "FULL SPORT"
    assert kwargs["id_sucursal"] == 1
    assert result.ruta_archivo.exists()


def test_supervisor_mapping_and_totals(tmp_path):
    result, _ = _make(tmp_path, _raw())
    rows = _sheet_rows(result.ruta_archivo)
    # supervisor of each vendedor row
    vend = {r[0]: r[1] for r in rows if r[0] in ("LORENA TARITOLAY", "NAHUEL RUEDA", "DIRECTA")}
    assert vend["LORENA TARITOLAY"] == "FGUANTAY"
    assert vend["NAHUEL RUEDA"] == "VCHAPUR"
    assert vend["DIRECTA"] == "SIN SUPERVISOR"
    # per-preventista total bultos
    assert result.total_bultos == 26.0


def test_cobertura_is_not_additive(tmp_path):
    """Sum of supervisor coberturas (2+1+1=4) exceeds the true total (3 distinct clients)."""
    result, _ = _make(tmp_path, _raw())
    assert result.cobertura_total == 3  # clients {1,2,3}, client 1 shared across supervisors
    rows = _sheet_rows(result.ruta_archivo)
    # supervisor-section cobertura (col 4) for FGUANTAY should be 2 (clients 1,2)
    sup_cob = {r[0]: r[3] for r in rows if r[0] in ("FGUANTAY", "VCHAPUR", "SIN SUPERVISOR")}
    assert sup_cob["FGUANTAY"] == 2
    assert sup_cob["VCHAPUR"] == 1


def test_has_two_total_general_rows(tmp_path):
    result, _ = _make(tmp_path, _raw())
    rows = _sheet_rows(result.ruta_archivo)
    totals = [r for r in rows if r[0] == "TOTAL GENERAL"]
    assert len(totals) == 2  # one per section (convención: fila de totales)


def test_empty_raw_does_not_crash(tmp_path):
    result, _ = _make(tmp_path, pd.DataFrame(columns=["vendedor", "id_cliente", "bultos"]))
    assert result.ruta_archivo.exists()
    assert result.total_bultos == 0.0
    assert result.cobertura_total == 0
