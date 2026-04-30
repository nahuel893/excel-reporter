"""
Tests for T-05 and T-06:
- GlobalFilters accepts detalle_movimientos_path (T-05)
- merge_filters propagates detalle_movimientos_path (T-06)
"""
import pytest

from src.config.models import GlobalFilters
from src.config.resolver import merge_filters


class TestGlobalFiltersDetalleMovimientos:
    """T-05: GlobalFilters.detalle_movimientos_path field."""

    def test_global_filters_accepts_detalle_movimientos_path(self):
        """T-05: GlobalFilters with detalle_movimientos_path set → field accessible."""
        gf = GlobalFilters(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
            detalle_movimientos_path="/some/path.xlsx",
        )
        assert gf.detalle_movimientos_path == "/some/path.xlsx"

    def test_global_filters_default_none(self):
        """T-05: GlobalFilters without detalle_movimientos_path → defaults to None."""
        gf = GlobalFilters(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
        )
        assert gf.detalle_movimientos_path is None


class TestMergeFiltersDetalleMovimientos:
    """T-06: merge_filters propagates detalle_movimientos_path."""

    def test_merge_filters_includes_detalle_movimientos_path(self):
        """T-06: merge_filters result contains detalle_movimientos_path from GlobalFilters."""
        gf = GlobalFilters(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
            detalle_movimientos_path="/x.xlsx",
        )
        result = merge_filters(gf, None)
        assert "detalle_movimientos_path" in result
        assert result["detalle_movimientos_path"] == "/x.xlsx"

    def test_merge_filters_detalle_movimientos_path_none_when_not_set(self):
        """T-06: merge_filters returns None for detalle_movimientos_path when not configured."""
        gf = GlobalFilters(
            fecha_desde="2026-04-01",
            fecha_hasta="2026-04-30",
        )
        result = merge_filters(gf, None)
        assert result.get("detalle_movimientos_path") is None
