"""Tests para AvancesService."""
import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import MagicMock, patch
from openpyxl import Workbook
from openpyxl.worksheet.table import Table
from openpyxl.utils import get_column_letter

from src.core.data_loader import DataLoader
from src.services.avances.service import AvancesService, AvancesConfig, SHEET_CONFIGS


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_template(tmp_path: Path) -> Path:
    """Create a minimal template Excel with the 3 gold sheets."""
    wb = Workbook()

    # gold fact_ventas — header at row 1
    ws_fv = wb.active
    ws_fv.title = "gold fact_ventas"
    fact_ventas_cols = [
        "id_cliente", "id_articulo", "id_vendedor", "id_sucursal",
        "fecha_comprobante", "id_documento", "letra", "serie", "nro_doc",
        "anulado", "cantidades_total", "bonificacion",
    ]
    for col_idx, h in enumerate(fact_ventas_cols, 1):
        ws_fv.cell(row=1, column=col_idx, value=h)
    # Some old data rows
    ws_fv.cell(row=2, column=1, value=999)
    ws_fv.cell(row=2, column=2, value=888)
    # Formula column after data columns
    ws_fv.cell(row=1, column=len(fact_ventas_cols) + 1, value="Formula")
    ws_fv.cell(row=2, column=len(fact_ventas_cols) + 1, value="=A2*2")

    # gold dim_articulo — header at row 1
    ws_art = wb.create_sheet("gold dim_articulo")
    dim_articulo_cols = [
        "id_articulo", "des_articulo", "marca", "generico", "calibre",
        "proveedor", "unidad_negocio", "factor_hectolitros",
    ]
    for col_idx, h in enumerate(dim_articulo_cols, 1):
        ws_art.cell(row=1, column=col_idx, value=h)
    ws_art.cell(row=2, column=1, value=1001)

    # gold dim_cliente — header at row 2 (row 1 is a title row)
    ws_cli = wb.create_sheet("gold dim_cliente")
    ws_cli.cell(row=1, column=1, value="TITULO")
    dim_cliente_cols = [
        "id_cliente", "fantasia", "razon_social", "des_sucursal", "id_sucursal",
        "id_ruta_fv1", "des_personal_fv1", "id_ruta_fv4", "des_personal_fv4",
    ]
    for col_idx, h in enumerate(dim_cliente_cols, 1):
        ws_cli.cell(row=2, column=col_idx, value=h)
    ws_cli.cell(row=3, column=1, value=5000)

    path = tmp_path / "plantilla.xlsx"
    wb.save(str(path))
    return path


def _make_fact_ventas_df():
    return pd.DataFrame({
        "id_cliente": [1, 2],
        "id_articulo": [101, 102],
        "id_vendedor": [10, 11],
        "id_sucursal": [1, 2],
        "fecha_comprobante": pd.to_datetime(["2026-04-01", "2026-04-02"]),
        "id_documento": [1001, 1002],
        "letra": ["A", "B"],
        "serie": ["0001", "0002"],
        "nro_doc": [500001, 500002],
        "anulado": [0, 0],
        "cantidades_total": [10.0, 20.0],
        "bonificacion": [0.0, 5.0],
    })


def _make_dim_articulo_df():
    return pd.DataFrame({
        "id_articulo": [101, 102],
        "des_articulo": ["BRAHMA LATA 473", "QUILMES 1L"],
        "marca": ["BRAHMA", "QUILMES"],
        "generico": ["CERVEZAS", "CERVEZAS"],
        "calibre": ["473ML", "1L"],
        "proveedor": ["AB INBEV", "AB INBEV"],
        "unidad_negocio": ["CERVEZAS", "CERVEZAS"],
        "factor_hectolitros": [0.00473, 0.01],
    })


def _make_dim_cliente_df():
    return pd.DataFrame({
        "id_cliente": [1, 2],
        "fantasia": ["ALMACEN SAN JUAN", "SUPER NORTE"],
        "razon_social": ["ALMACEN SAN JUAN SRL", "SUPER NORTE SA"],
        "des_sucursal": ["CASA CENTRAL", "CAFAYATE"],
        "id_sucursal": [1, 2],
        "id_ruta_fv1": [81, 10],
        "des_personal_fv1": ["Juan", "Ana"],
        "id_ruta_fv4": [81, 10],
        "des_personal_fv4": ["Juan", "Ana"],
    })


def _make_cob_prev_generico_df():
    return pd.DataFrame({
        "id": [1, 2],
        "periodo": pd.to_datetime(["2026-04-01", "2026-04-01"]),
        "id_fuerza_ventas": [1, 1],
        "id_vendedor": [10, 11],
        "id_ruta": [81, 10],
        "id_sucursal": [1, 1],
        "ds_sucursal": ["CASA CENTRAL", "CASA CENTRAL"],
        "generico": ["CERVEZAS", "AGUAS DANONE"],
        "clientes_compradores": [50, 30],
        "volumen_total": [100.5, 50.3],
    })


def _make_cob_prev_marca_df():
    return pd.DataFrame({
        "id": [1, 2],
        "periodo": pd.to_datetime(["2026-04-01", "2026-04-01"]),
        "id_fuerza_ventas": [1, 1],
        "id_vendedor": [10, 11],
        "id_ruta": [81, 10],
        "id_sucursal": [1, 1],
        "ds_sucursal": ["CASA CENTRAL", "CASA CENTRAL"],
        "marca": ["QUILMES", "BRAHMA"],
        "clientes_compradores": [40, 25],
        "volumen_total": [80.0, 45.0],
    })


def _make_mock_loader():
    loader = MagicMock(spec=DataLoader)
    loader.get_fact_ventas_raw.return_value = _make_fact_ventas_df()
    loader.get_dim_articulo_raw.return_value = _make_dim_articulo_df()
    loader.get_dim_cliente_raw.return_value = _make_dim_cliente_df()
    loader.get_cob_preventista_generico_raw.return_value = _make_cob_prev_generico_df()
    loader.get_cob_preventista_marca_raw.return_value = _make_cob_prev_marca_df()
    return loader


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestAvancesServiceHappyPath:
    def test_happy_path(self, tmp_path):
        """Template with 3 gold sheets + mocked DataLoader → output file exists,
        registros_por_hoja has correct counts, formula columns in fact_ventas untouched."""
        plantilla = _make_template(tmp_path)
        mock_loader = _make_mock_loader()

        service = AvancesService(data_loader=mock_loader)
        config = AvancesConfig(
            archivo_plantilla=str(plantilla),
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-15",
            nombre_archivo="avances_test",
        )

        with patch("src.services.avances.service.DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)

        # Output file exists
        assert result.ruta_archivo.exists()

        # registros_por_hoja has correct counts
        assert result.registros_por_hoja["gold fact_ventas"] == 2
        assert result.registros_por_hoja["gold dim_articulo"] == 2
        assert result.registros_por_hoja["gold dim_cliente"] == 2
        assert result.registros_por_hoja["cob_preventista_generico"] == 2
        assert result.registros_por_hoja["cob_preventista_marca"] == 2

        # Formula column in fact_ventas untouched
        import openpyxl
        wb = openpyxl.load_workbook(str(result.ruta_archivo))
        ws = wb["gold fact_ventas"]
        formula_col_idx = len([
            "id_cliente", "id_articulo", "id_vendedor", "id_sucursal",
            "fecha_comprobante", "id_documento", "letra", "serie", "nro_doc",
            "anulado", "cantidades_total", "bonificacion",
        ]) + 1
        assert ws.cell(row=2, column=formula_col_idx).value == "=A2*2"


class TestAvancesServiceErrors:
    def test_missing_template_raises(self, tmp_path):
        """Config points to nonexistent file → FileNotFoundError."""
        service = AvancesService(data_loader=MagicMock(spec=DataLoader))
        config = AvancesConfig(
            archivo_plantilla=str(tmp_path / "no_existe.xlsx"),
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-15",
        )

        with patch("src.services.avances.service.DATA_OUTPUT", tmp_path):
            with pytest.raises(FileNotFoundError):
                service.generar_reporte(config)

    def test_output_equals_template_raises(self, tmp_path):
        """output_path == plantilla → ValueError."""
        plantilla = _make_template(tmp_path)
        service = AvancesService(data_loader=MagicMock(spec=DataLoader))

        # nombre_archivo matches plantilla stem so output_path == plantilla
        config = AvancesConfig(
            archivo_plantilla=str(plantilla),
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-15",
            nombre_archivo=plantilla.stem,
        )

        # DATA_OUTPUT must be same dir as plantilla so paths resolve equal
        with patch("src.services.avances.service.DATA_OUTPUT", tmp_path):
            with pytest.raises(ValueError, match="differ"):
                service.generar_reporte(config)


class TestAvancesServiceMissingSheet:
    def test_missing_sheet_creates_it(self, tmp_path, caplog):
        """Template missing sheets → creates them, writes data, all 5 in result."""
        # Build template with only 2 of the 5 sheets
        wb = Workbook()
        ws_fv = wb.active
        ws_fv.title = "gold fact_ventas"
        for col_idx, h in enumerate([
            "id_cliente", "id_articulo", "id_vendedor", "id_sucursal",
            "fecha_comprobante", "id_documento", "letra", "serie", "nro_doc",
            "anulado", "cantidades_total", "bonificacion",
        ], 1):
            ws_fv.cell(row=1, column=col_idx, value=h)

        ws_art = wb.create_sheet("gold dim_articulo")
        for col_idx, h in enumerate([
            "id_articulo", "des_articulo", "marca", "generico", "calibre",
            "proveedor", "unidad_negocio", "factor_hectolitros",
        ], 1):
            ws_art.cell(row=1, column=col_idx, value=h)

        # gold dim_cliente, cob_preventista_generico, cob_preventista_marca omitted
        plantilla = tmp_path / "plantilla_incompleta.xlsx"
        wb.save(str(plantilla))

        mock_loader = _make_mock_loader()
        service = AvancesService(data_loader=mock_loader)
        config = AvancesConfig(
            archivo_plantilla=str(plantilla),
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-15",
            nombre_archivo="avances_incompleto",
        )

        import logging
        with caplog.at_level(logging.INFO), patch("src.services.avances.service.DATA_OUTPUT", tmp_path):
            result = service.generar_reporte(config)

        # All 5 sheets processed (3 created on the fly)
        assert len(result.registros_por_hoja) == 5
        assert "gold dim_cliente" in result.registros_por_hoja
        assert "cob_preventista_generico" in result.registros_por_hoja
        assert "cob_preventista_marca" in result.registros_por_hoja
        # Log says sheets were created
        assert any("not found, creating" in record.message for record in caplog.records)
