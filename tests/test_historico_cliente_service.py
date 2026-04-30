"""
Tests for HistoricoClienteService.
"""
import logging
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.data_loader import DataLoader
from src.services.historico_cliente import (
    HistoricoClienteConfig,
    HistoricoClienteService,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_two_client_df():
    """Two clients, two months, marcas as row_key."""
    return pd.DataFrame({
        "id_cliente": [1, 1, 2, 2],
        "id_sucursal": [1, 1, 1, 1],
        "nombre_cliente": ["Cliente A", "Cliente A", "Cliente B", "Cliente B"],
        "row_key": ["BRANCA", "BRANCA", "BRANCA", "BRAHMA"],
        "mes": ["2026-01", "2026-02", "2026-01", "2026-02"],
        "bultos": [10.0, 20.0, 5.0, 15.0],
    })


def _base_config(**kwargs):
    defaults = dict(
        fecha_desde="2026-01-01",
        fecha_hasta="2026-02-28",
        clientes=[
            {"id_cliente": 1, "id_sucursal": 1},
            {"id_cliente": 2, "id_sucursal": 1},
        ],
        marcas=["BRANCA", "BRAHMA"],
        nombre_archivo="Test",
    )
    defaults.update(kwargs)
    return HistoricoClienteConfig(**defaults)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_happy_path_marcas(tmp_path):
    """Two clients with marcas filter → 2 sheets generated, file exists."""
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_historico_cliente.return_value = _make_two_client_df()

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config()

    with patch("src.services.historico_cliente.service.service_output_dir", return_value=tmp_path):
        result = service.generar_reporte(config)

    assert result.ruta_archivo.exists()
    assert len(result.sheets_generated) == 2


def test_happy_path_articulos(tmp_path):
    """Articulos filter → row labels use 'Articulo' column name."""
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_historico_cliente.return_value = pd.DataFrame({
        "id_cliente": [1, 1],
        "id_sucursal": [1, 1],
        "nombre_cliente": ["Cliente A", "Cliente A"],
        "row_key": ["12345 CERVEZA", "67890 AGUA"],
        "mes": ["2026-01", "2026-02"],
        "bultos": [10.0, 20.0],
    })

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config(
        clientes=[{"id_cliente": 1, "id_sucursal": 1}],
        articulos=[12345, 67890],
        marcas=None,
    )

    with patch("src.services.historico_cliente.service.service_output_dir", return_value=tmp_path):
        result = service.generar_reporte(config)

    # Verify the sheet was generated
    assert result.ruta_archivo.exists()
    assert len(result.sheets_generated) == 1

    # Verify the column label is "Articulo" (not "Marca")
    from openpyxl import load_workbook
    wb = load_workbook(result.ruta_archivo)
    ws = wb.active
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    assert "Articulo" in headers
    assert "Marca" not in headers


def test_both_filters_raises(tmp_path):
    """Config with both articulos and marcas → ValueError before any DB call."""
    loader = MagicMock(spec=DataLoader)

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config(articulos=[1, 2], marcas=["BRANCA"])

    with pytest.raises(ValueError, match="articulos"):
        service.generar_reporte(config)

    loader.get_ventas_historico_cliente.assert_not_called()


def test_neither_filter_raises(tmp_path):
    """Config with neither articulos nor marcas → ValueError."""
    loader = MagicMock(spec=DataLoader)

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config(articulos=None, marcas=None)

    with pytest.raises(ValueError):
        service.generar_reporte(config)


def test_client_empty_skipped(tmp_path, caplog):
    """Client with no data in mock → 1 sheet generated, 1 warning logged."""
    loader = MagicMock(spec=DataLoader)
    # Only client 1 has data; client 2 is absent from the DataFrame
    loader.get_ventas_historico_cliente.return_value = pd.DataFrame({
        "id_cliente": [1],
        "id_sucursal": [1],
        "nombre_cliente": ["Cliente A"],
        "row_key": ["BRANCA"],
        "mes": ["2026-01"],
        "bultos": [10.0],
    })

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config()  # still requests 2 clients

    with patch("src.services.historico_cliente.service.service_output_dir", return_value=tmp_path):
        with caplog.at_level(logging.WARNING, logger="src.services.historico_cliente.service"):
            result = service.generar_reporte(config)

    assert len(result.sheets_generated) == 1
    assert any("sin datos" in record.message for record in caplog.records)


def test_all_months_covered(tmp_path):
    """Mock returns data for 2 of 4 months → pivot has all 4 columns, missing filled with 0."""
    loader = MagicMock(spec=DataLoader)
    # Data only for Jan and Mar; Feb and Apr are missing
    loader.get_ventas_historico_cliente.return_value = pd.DataFrame({
        "id_cliente": [1, 1],
        "id_sucursal": [1, 1],
        "nombre_cliente": ["Cliente A", "Cliente A"],
        "row_key": ["BRANCA", "BRANCA"],
        "mes": ["2026-01", "2026-03"],
        "bultos": [10.0, 30.0],
    })

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config(
        fecha_desde="2026-01-01",
        fecha_hasta="2026-04-30",
        clientes=[{"id_cliente": 1, "id_sucursal": 1}],
    )

    with patch("src.services.historico_cliente.service.service_output_dir", return_value=tmp_path):
        result = service.generar_reporte(config)

    assert result.ruta_archivo.exists()

    from openpyxl import load_workbook
    wb = load_workbook(result.ruta_archivo)
    ws = wb.active
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]

    for month in ("2026-01", "2026-02", "2026-03", "2026-04"):
        assert month in headers, f"Missing month column: {month}"

    # Find Feb column and verify its value is 0
    feb_col = headers.index("2026-02") + 1  # 1-based
    data_row = 2  # first data row
    assert ws.cell(row=data_row, column=feb_col).value == 0


def test_long_client_name_truncated(tmp_path):
    """Client with 40-char nombre_cliente → sheet name is exactly 31 chars."""
    long_name = "A" * 40
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_historico_cliente.return_value = pd.DataFrame({
        "id_cliente": [1],
        "id_sucursal": [1],
        "nombre_cliente": [long_name],
        "row_key": ["BRANCA"],
        "mes": ["2026-01"],
        "bultos": [10.0],
    })

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config(clientes=[{"id_cliente": 1, "id_sucursal": 1}])

    with patch("src.services.historico_cliente.service.service_output_dir", return_value=tmp_path):
        result = service.generar_reporte(config)

    assert len(result.sheets_generated) == 1
    assert len(result.sheets_generated[0]) == 31
