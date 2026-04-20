"""Tests for src/core/output_paths.py — service-scoped output directory helper."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest


class TestServiceOutputDir:
    """Unit tests for service_output_dir()."""

    def test_month_from_fecha(self, tmp_path):
        """fecha_desde='2026-04-19', granularity='month' -> ends with '2026-04'."""
        import config.settings as settings

        with patch.object(settings, "DATA_OUTPUT", tmp_path):
            from src.core.output_paths import service_output_dir

            result = service_output_dir("ventas", "2026-04-19", "month")

        assert result == tmp_path / "ventas" / "2026-04"

    def test_day_from_fecha(self, tmp_path):
        """fecha_desde='2026-04-19', granularity='day' -> ends with '2026-04-19'."""
        import config.settings as settings

        with patch.object(settings, "DATA_OUTPUT", tmp_path):
            from src.core.output_paths import service_output_dir

            result = service_output_dir("stock-diario", "2026-04-19", "day")

        assert result == tmp_path / "stock-diario" / "2026-04-19"

    def test_iso_timestamp_trimmed(self, tmp_path):
        """fecha_desde with ISO timestamp -> trimmed to date portion."""
        import config.settings as settings

        with patch.object(settings, "DATA_OUTPUT", tmp_path):
            from src.core.output_paths import service_output_dir

            result_month = service_output_dir("ventas", "2026-04-19T12:00:00", "month")
            result_day = service_output_dir("stock-diario", "2026-04-19T12:00:00", "day")

        assert result_month == tmp_path / "ventas" / "2026-04"
        assert result_day == tmp_path / "stock-diario" / "2026-04-19"

    def test_month_default_today(self, tmp_path):
        """fecha_desde=None with month granularity -> today's YYYY-MM."""
        import config.settings as settings

        fake_today = date(2026, 4, 19)
        with patch.object(settings, "DATA_OUTPUT", tmp_path):
            with patch("src.core.output_paths.date") as mock_date:
                mock_date.today.return_value = fake_today
                from src.core.output_paths import service_output_dir

                result = service_output_dir("ventas", None, "month")

        assert result == tmp_path / "ventas" / "2026-04"

    def test_day_default_today(self, tmp_path):
        """fecha_desde=None with day granularity -> today's YYYY-MM-DD."""
        import config.settings as settings

        fake_today = date(2026, 4, 19)
        with patch.object(settings, "DATA_OUTPUT", tmp_path):
            with patch("src.core.output_paths.date") as mock_date:
                mock_date.today.return_value = fake_today
                from src.core.output_paths import service_output_dir

                result = service_output_dir("stock-diario", None, "day")

        assert result == tmp_path / "stock-diario" / "2026-04-19"

    def test_invalid_granularity_raises(self, tmp_path):
        """granularity='year' -> ValueError."""
        import config.settings as settings

        with patch.object(settings, "DATA_OUTPUT", tmp_path):
            from src.core.output_paths import service_output_dir

            with pytest.raises(ValueError, match="granularity"):
                service_output_dir("ventas", "2026-04-19", "year")

    def test_respects_patched_data_output(self, tmp_path):
        """patch(config.settings.DATA_OUTPUT, tmp_path) must work correctly."""
        import config.settings as settings

        custom_root = tmp_path / "custom"
        custom_root.mkdir()

        with patch.object(settings, "DATA_OUTPUT", custom_root):
            from src.core.output_paths import service_output_dir

            result = service_output_dir("mision-imposible", "2026-04-01", "month")

        assert result == custom_root / "mision-imposible" / "2026-04"

    def test_does_not_create_directory(self, tmp_path):
        """Helper must NOT create the directory — caller owns mkdir."""
        import config.settings as settings

        with patch.object(settings, "DATA_OUTPUT", tmp_path):
            from src.core.output_paths import service_output_dir

            result = service_output_dir("ventas", "2026-04-19", "month")

        assert not result.exists()
