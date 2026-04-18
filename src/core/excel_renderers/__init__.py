"""Image renderer protocol + backend factory.

Two backends available:
  - 'libreoffice'     : wraps ExcelManager.capture_range (LibreOffice + pdftoppm)
  - 'html_playwright' : xlsx2html + Playwright Chromium headless

Use via the factory:
    from src.core.excel_renderers import get_renderer
    renderer = get_renderer("html_playwright")
    png = renderer.render(xlsx, sheet, range_addr, output_dir, dpi=300)
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


_VALID_RENDERERS = ("libreoffice", "html_playwright")


@runtime_checkable
class ImageRenderer(Protocol):
    """Contract for any backend that renders an xlsx sheet region to a PNG."""

    name: str

    def render(
        self,
        xlsx_path: Path,
        sheet: str,
        range_addr: str,
        output_dir: Path,
        dpi: int = 300,
    ) -> Path:
        ...


def get_renderer(name: str) -> ImageRenderer:
    """Return a renderer instance by name.

    Raises:
        ValueError: if `name` is not one of the supported backend keys.
    """
    if name == "libreoffice":
        from src.core.excel_renderers.libreoffice_renderer import LibreOfficeRenderer
        return LibreOfficeRenderer()
    if name == "html_playwright":
        from src.core.excel_renderers.html_playwright_renderer import (
            HtmlPlaywrightRenderer,
        )
        return HtmlPlaywrightRenderer()
    raise ValueError(
        f"Unknown renderer {name!r}. Valid: {list(_VALID_RENDERERS)}"
    )


__all__ = ["ImageRenderer", "get_renderer"]
