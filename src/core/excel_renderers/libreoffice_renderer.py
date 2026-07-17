"""LibreOffice-backed renderer — thin wrapper around ExcelManager.capture_range."""
from __future__ import annotations

from pathlib import Path

from src.core.excel_manager import ExcelManager


class LibreOfficeRenderer:
    """Delegates rendering to `ExcelManager.capture_range` (LibreOffice + pdftoppm)."""

    name = "libreoffice"

    def render(
        self,
        xlsx_path: Path,
        sheet: str,
        range_addr: str,
        output_dir: Path,
        dpi: int = 300,
        crop: bool = False,
    ) -> Path:
        return ExcelManager(xlsx_path).capture_range(
            sheet_name=sheet,
            range_addr=range_addr,
            output_dir=output_dir,
            dpi=dpi,
            crop=crop,
        )

    def render_many(
        self,
        xlsx_path: Path,
        specs: list[tuple[str, str, bool]],
        output_dir: Path,
        dpi: int = 300,
    ) -> list[Path | Exception]:
        """Batch variant of render(): delegates to
        ExcelManager.capture_ranges, which recalculates the workbook ONCE
        and reuses it across every spec — proven pixel-identical to N
        individual capture_range() calls, at a fraction of the wall time
        (see scratchpad/pr5_bench in the PR that introduced this method).
        """
        return ExcelManager(xlsx_path).capture_ranges(
            specs=specs,
            output_dir=output_dir,
            dpi=dpi,
        )
