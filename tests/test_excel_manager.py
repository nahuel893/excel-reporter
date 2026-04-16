"""Tests para ExcelManager."""
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

    def test_pillow_not_installed_raises_import_error(self, tmp_path):
        xlsx = self._make_xlsx(tmp_path)
        mgr = ExcelManager(xlsx)
        # soffice debe estar disponible (o mockeado) para llegar al import de Pillow
        with patch.object(ExcelManager, "_find_soffice", return_value="/usr/bin/soffice"):
            with patch.object(ExcelManager, "_recalc_with_libreoffice", return_value=xlsx):
                with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None, "PIL.ImageDraw": None, "PIL.ImageFont": None}):
                    with pytest.raises((ImportError, ModuleNotFoundError)):
                        mgr.capture_range("Hoja1", "A1:B2")

    def test_soffice_not_found_raises_runtime_error(self, tmp_path):
        """Sin LibreOffice en el PATH -> RuntimeError antes de intentar renderizar."""
        xlsx = self._make_xlsx(tmp_path)
        mgr = ExcelManager(xlsx)
        with patch.object(ExcelManager, "_find_soffice", return_value=None):
            with pytest.raises(RuntimeError, match="LibreOffice no encontrado"):
                mgr.capture_range("Hoja1", "A1:B2")

    def test_capture_range_generates_png(self, tmp_path):
        """Verifica que genera un archivo PNG real."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        xlsx = self._make_xlsx(tmp_path)
        mgr = ExcelManager(xlsx)
        with patch.object(ExcelManager, "_find_soffice", return_value="/usr/bin/soffice"):
            with patch.object(ExcelManager, "_recalc_with_libreoffice", return_value=xlsx):
                out_path = mgr.capture_range("Hoja1", "A1:B2", output_dir=tmp_path)

        assert out_path.exists()
        assert out_path.suffix == ".png"
        img = Image.open(out_path)
        assert img.width > 0
        assert img.height > 0

    def test_capture_range_auto_detect(self, tmp_path):
        """Verifica auto-deteccion de bordes gruesos."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        from openpyxl.styles import Border, Side

        xlsx = tmp_path / "bordered.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Hoja1"

        thick = Side(style="thick")
        # Poner bordes gruesos en A1:B3
        for r in range(1, 4):
            for c in range(1, 3):
                cell = ws.cell(row=r, column=c, value=f"R{r}C{c}")
                cell.border = Border(
                    top=thick if r == 1 else None,
                    bottom=thick if r == 3 else None,
                    left=thick if c == 1 else None,
                    right=thick if c == 2 else None,
                )
        wb.save(xlsx)

        mgr = ExcelManager(xlsx)
        with patch.object(ExcelManager, "_find_soffice", return_value="/usr/bin/soffice"):
            with patch.object(ExcelManager, "_recalc_with_libreoffice", return_value=xlsx):
                out_path = mgr.capture_range("Hoja1", "auto", output_dir=tmp_path)
        assert out_path.exists()

    def test_auto_detect_no_borders_raises(self, tmp_path):
        """Sin bordes gruesos y rango 'auto' -> ValueError."""
        xlsx = self._make_xlsx(tmp_path)
        mgr = ExcelManager(xlsx)
        with pytest.raises(ValueError, match="No se detectaron bordes gruesos"):
            mgr.capture_range("Hoja1", "auto")


class TestExcelManagerDetectBorderedRange:
    def test_detects_thick_borders(self, tmp_path):
        from openpyxl.styles import Border, Side

        xlsx = tmp_path / "borders.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Test"

        thick = Side(style="medium")
        ws.cell(row=2, column=2).border = Border(top=thick)
        ws.cell(row=5, column=4).border = Border(bottom=thick)
        wb.save(xlsx)

        mgr = ExcelManager(xlsx)
        result = mgr.detect_bordered_range("Test")
        assert result == "B2:D5"

    def test_no_borders_returns_none(self, tmp_path):
        xlsx = tmp_path / "no_borders.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "Test"
        wb.save(xlsx)

        mgr = ExcelManager(xlsx)
        assert mgr.detect_bordered_range("Test") is None

    def test_missing_sheet_returns_none(self, tmp_path):
        xlsx = tmp_path / "test.xlsx"
        wb = openpyxl.Workbook()
        wb.save(xlsx)

        mgr = ExcelManager(xlsx)
        assert mgr.detect_bordered_range("NoExiste") is None


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
        df = mgr.get_dataframe("Vacio", "A5:B4")
        assert df.empty
