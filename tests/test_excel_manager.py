"""Tests para ExcelManager."""
import io
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from src.core.excel_manager import ExcelManager, _col_letter_to_index, _parse_range


class TestColLetterToIndex:
    def test_single_letters(self):
        assert _col_letter_to_index("A") == 1
        assert _col_letter_to_index("Z") == 26

    def test_double_letters(self):
        assert _col_letter_to_index("AA") == 27
        assert _col_letter_to_index("AZ") == 52

    def test_case_insensitive(self):
        assert _col_letter_to_index("a") == _col_letter_to_index("A")


class TestParseRange:
    def test_simple_range(self):
        col1, row1, col2, row2 = _parse_range("A1:H20")
        assert col1 == 1
        assert row1 == 1
        assert col2 == 8
        assert row2 == 20

    def test_double_letter_column(self):
        col1, row1, col2, row2 = _parse_range("AA1:AB5")
        assert col1 == 27
        assert col2 == 28

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError, match="Rango invalido"):
            _parse_range("A1")


class TestExcelManagerInit:
    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ExcelManager(tmp_path / "no_existe.xlsx")

    def test_accepts_existing_file(self, tmp_path):
        xlsx = tmp_path / "test.xlsx"
        wb = openpyxl.Workbook()
        wb.save(xlsx)
        mgr = ExcelManager(xlsx)
        assert mgr.ruta_excel == xlsx


class TestExcelManagerCaptureRange:
    def _make_xlsx(self, tmp_path: Path, sheet_name: str = "Hoja1") -> Path:
        xlsx = tmp_path / "reporte.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
        # Datos simples para la hoja
        ws["A1"] = "Header"
        ws["B1"] = "Value"
        ws["A2"] = 100
        ws["B2"] = 200
        wb.save(xlsx)
        return xlsx

    def test_missing_sheet_raises_value_error(self, tmp_path):
        xlsx = self._make_xlsx(tmp_path)
        mgr = ExcelManager(xlsx)
        with pytest.raises(ValueError, match="Hoja 'NoExiste' no encontrada"):
            mgr.capture_range("NoExiste", "A1:B2")

    def test_soffice_not_found_raises_runtime_error(self, tmp_path):
        xlsx = self._make_xlsx(tmp_path)
        mgr = ExcelManager(xlsx)

        mock_pil_image = MagicMock()
        mock_pil = MagicMock()
        mock_pil.Image = mock_pil_image

        with (
            patch.dict("sys.modules", {"PIL": mock_pil, "PIL.Image": mock_pil_image}),
            patch("shutil.which", return_value=None),
        ):
            with pytest.raises(RuntimeError, match="LibreOffice no encontrado"):
                mgr.capture_range("Hoja1", "A1:B2")

    def test_pillow_not_installed_raises_import_error(self, tmp_path):
        xlsx = self._make_xlsx(tmp_path)
        mgr = ExcelManager(xlsx)
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            with pytest.raises(ImportError, match="Pillow"):
                mgr.capture_range("Hoja1", "A1:B2")

    def test_capture_range_calls_soffice_and_crops(self, tmp_path):
        """Verifica que se llama a soffice y se recorta la imagen con Pillow."""
        xlsx = self._make_xlsx(tmp_path)
        mgr = ExcelManager(xlsx)

        fake_png = tmp_path / "fake_full.png"
        fake_png.write_bytes(b"fake-png-data")

        # Mock de PIL.Image
        mock_image_instance = MagicMock()
        mock_cropped = MagicMock()
        mock_image_instance.crop.return_value = mock_cropped

        mock_pil_image = MagicMock()
        mock_pil_image.open.return_value = mock_image_instance
        mock_pil = MagicMock()
        mock_pil.Image = mock_pil_image

        mock_result = MagicMock()
        mock_result.returncode = 0

        with (
            patch.dict("sys.modules", {"PIL": mock_pil, "PIL.Image": mock_pil_image}),
            patch("shutil.which", return_value="/usr/bin/soffice"),
            patch("subprocess.run", return_value=mock_result),
            patch("pathlib.Path.glob", return_value=[fake_png]),
        ):
            out_path = mgr.capture_range("Hoja1", "A1:B2", output_dir=tmp_path)

        mock_cropped.save.assert_called_once()
        assert out_path.suffix == ".png"

    def test_calculate_crop_box_pixel_math(self, tmp_path):
        """Verifica la conversion chars→px y pts→px segun la formula del diseno."""
        xlsx = self._make_xlsx(tmp_path)
        mgr = ExcelManager(xlsx)

        wb = openpyxl.load_workbook(xlsx)
        ws = wb.active

        # Con dimensiones por defecto (8.43 chars, 15.0 pts):
        # col_px = int(8.43 * 7.0 + 5) = int(64.01) = 64
        # row_px = int(15.0 * 96.0 / 72.0) = int(20.0) = 20
        col_px_default = int(ExcelManager.DEFAULT_COL_WIDTH_CHARS * 7.0 + 5)
        row_px_default = int(ExcelManager.DEFAULT_ROW_HEIGHT_PTS * 96.0 / 72.0)

        # Rango A1:B2 → x1=0, y1=0, x2=col_px*2, y2=row_px*2
        box = mgr._calculate_crop_box(ws, col1=1, row1=1, col2=2, row2=2)
        assert box == (0, 0, col_px_default * 2, row_px_default * 2)

    def test_calculate_crop_box_with_custom_dimensions(self, tmp_path):
        """Verifica el calculo cuando hay dimensiones de columnas/filas personalizadas."""
        xlsx = tmp_path / "custom.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Hoja1"
        ws.column_dimensions["A"].width = 20.0  # 20 chars
        ws.row_dimensions[1].height = 30.0      # 30 pts
        wb.save(xlsx)

        mgr = ExcelManager(xlsx)
        wb2 = openpyxl.load_workbook(xlsx)
        ws2 = wb2.active

        # col A (width=20): px = int(20 * 7.0 + 5) = 145
        # row 1 (height=30): px = int(30 * 96.0 / 72.0) = 40
        box = mgr._calculate_crop_box(ws2, col1=1, row1=1, col2=1, row2=1)
        assert box == (0, 0, int(20.0 * 7.0 + 5), int(30.0 * 96.0 / 72.0))


class TestExcelManagerGetDataframe:
    def _make_xlsx_with_data(self, tmp_path: Path) -> Path:
        xlsx = tmp_path / "data.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Datos"
        ws["A1"] = "Nombre"
        ws["B1"] = "Valor"
        ws["A2"] = "Alpha"
        ws["B2"] = 10
        ws["A3"] = "Beta"
        ws["B3"] = 20
        wb.save(xlsx)
        return xlsx

    def test_returns_dataframe_with_headers(self, tmp_path):
        xlsx = self._make_xlsx_with_data(tmp_path)
        mgr = ExcelManager(xlsx)
        df = mgr.get_dataframe("Datos", "A1:B3")
        assert list(df.columns) == ["Nombre", "Valor"]
        assert len(df) == 2
        assert df.iloc[0]["Nombre"] == "Alpha"
        assert df.iloc[1]["Valor"] == 20

    def test_missing_sheet_raises_value_error(self, tmp_path):
        xlsx = self._make_xlsx_with_data(tmp_path)
        mgr = ExcelManager(xlsx)
        with pytest.raises(ValueError, match="NoExiste"):
            mgr.get_dataframe("NoExiste", "A1:B3")

    def test_empty_range_returns_empty_dataframe(self, tmp_path):
        xlsx = tmp_path / "empty.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Vacio"
        wb.save(xlsx)
        mgr = ExcelManager(xlsx)
        # Rango con fila inicio > fila fin → sin filas
        df = mgr.get_dataframe("Vacio", "A5:B4")
        assert df.empty


