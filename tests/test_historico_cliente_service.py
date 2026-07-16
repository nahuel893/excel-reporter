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


def _make_grouped_df():
    """One client, two genericos (CERVEZAS: SALTA, HEINEKEN; VINOS: TORO), two months.

    Row grain matches loader output in ``agrupar_por_generico`` mode:
    columns include ``generico`` and ``row_key`` (= marca).
    """
    return pd.DataFrame({
        "id_cliente": [1] * 6,
        "id_sucursal": [1] * 6,
        "nombre_cliente": ["Cli A"] * 6,
        "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS", "CERVEZAS", "VINOS", "VINOS"],
        "row_key": ["SALTA", "SALTA", "HEINEKEN", "HEINEKEN", "TORO", "TORO"],
        "mes": ["2026-01", "2026-02", "2026-01", "2026-02", "2026-01", "2026-02"],
        "bultos": [100.0, 120.0, 30.0, 40.0, 10.0, 5.0],
    })


def _read_marca_column(ruta):
    """Return the values of the 'Marca' column (data rows only) of the active sheet."""
    from openpyxl import load_workbook
    wb = load_workbook(ruta)
    ws = wb.active
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    marca_col = headers.index("Marca") + 1
    total_col = headers.index("Total") + 1
    rows = []
    for r in range(2, ws.max_row + 1):
        rows.append((ws.cell(row=r, column=marca_col).value, ws.cell(row=r, column=total_col).value))
    return rows


def test_grouped_by_generico_adds_subtotals(tmp_path):
    """agrupar_por_generico=True → per-generico subtotal rows + grand total row."""
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_historico_cliente.return_value = _make_grouped_df()

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config(
        clientes=[{"id_cliente": 1, "id_sucursal": 1}],
        marcas=None,
        articulos=None,
        agrupar_por_generico=True,
    )

    with patch("src.services.historico_cliente.service.service_output_dir", return_value=tmp_path):
        result = service.generar_reporte(config)

    assert result.ruta_archivo.exists()

    # Loader must be told to group by generico
    _, kwargs = loader.get_ventas_historico_cliente.call_args
    assert kwargs.get("agrupar_por_generico") is True

    rows = _read_marca_column(result.ruta_archivo)
    labels = {label for label, _ in rows}
    assert "TOTAL CERVEZAS" in labels
    assert "TOTAL VINOS" in labels
    assert "TOTAL GENERAL" in labels

    # Subtotal + grand-total values are correct
    totals = dict(rows)
    assert totals["TOTAL CERVEZAS"] == 290
    assert totals["TOTAL VINOS"] == 15
    assert totals["TOTAL GENERAL"] == 305


def test_grouped_mode_no_filter_required(tmp_path):
    """In grouped mode, neither marcas nor articulos is required (shows all marcas)."""
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_historico_cliente.return_value = _make_grouped_df()

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config(
        clientes=[{"id_cliente": 1, "id_sucursal": 1}],
        marcas=None,
        articulos=None,
        agrupar_por_generico=True,
    )

    with patch("src.services.historico_cliente.service.service_output_dir", return_value=tmp_path):
        result = service.generar_reporte(config)  # must NOT raise

    assert len(result.sheets_generated) == 1


def test_grouped_mode_generico_ordered_by_total(tmp_path):
    """Genericos are ordered by descending total; CERVEZAS (290) before VINOS (15)."""
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_historico_cliente.return_value = _make_grouped_df()

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config(
        clientes=[{"id_cliente": 1, "id_sucursal": 1}],
        marcas=None,
        articulos=None,
        agrupar_por_generico=True,
    )

    with patch("src.services.historico_cliente.service.service_output_dir", return_value=tmp_path):
        result = service.generar_reporte(config)

    labels = [label for label, _ in _read_marca_column(result.ruta_archivo)]
    assert labels.index("TOTAL CERVEZAS") < labels.index("TOTAL VINOS")
    # Grand total is the last row
    assert labels[-1] == "TOTAL GENERAL"


def test_marcas_completas_fills_universe(tmp_path):
    """marcas_completas=True → marcas del universo no compradas aparecen con Total 0."""
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_historico_cliente.return_value = _make_grouped_df()
    # Universe adds QUILMES (CERVEZAS) + ANDES (VINOS) the client never bought.
    loader.get_marca_universe.return_value = pd.DataFrame({
        "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS", "VINOS", "VINOS"],
        "marca": ["SALTA", "HEINEKEN", "QUILMES", "TORO", "ANDES"],
    })

    service = HistoricoClienteService(data_loader=loader)
    config = _base_config(
        clientes=[{"id_cliente": 1, "id_sucursal": 1}],
        marcas=None,
        articulos=None,
        agrupar_por_generico=True,
        marcas_completas=True,
        genericos_universo=["CERVEZAS", "VINOS"],
    )

    with patch("src.services.historico_cliente.service.service_output_dir", return_value=tmp_path):
        result = service.generar_reporte(config)

    loader.get_marca_universe.assert_called_once_with(["CERVEZAS", "VINOS"])

    rows = _read_marca_column(result.ruta_archivo)
    labels = {label for label, _ in rows}
    totals = dict(rows)
    # Never-bought marcas are present with 0
    assert "QUILMES" in labels and totals["QUILMES"] == 0
    assert "ANDES" in labels and totals["ANDES"] == 0
    # Bought marcas + subtotals unchanged by the zero-fill
    assert totals["TOTAL CERVEZAS"] == 290
    assert totals["TOTAL VINOS"] == 15
    assert totals["TOTAL GENERAL"] == 305


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
