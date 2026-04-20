"""Tests for BaseService._output_dir() hook."""
from pathlib import Path
from unittest.mock import patch

import pytest

import config.settings as settings
from src.services.base_service import BaseService
from src.core.data_loader import DataLoader


class _ConcreteService(BaseService):
    """Minimal concrete subclass with SLUG set."""
    SERVICE_SLUG = "test-service"

    def generar_reporte(self, config):
        pass


class _NoSlugService(BaseService):
    """Concrete subclass that forgets to set SERVICE_SLUG."""
    def generar_reporte(self, config):
        pass


class TestBaseServiceOutputDir:
    def test_output_dir_raises_without_slug(self, tmp_path):
        """_output_dir raises NotImplementedError when SERVICE_SLUG is empty."""
        svc = _NoSlugService()
        with pytest.raises(NotImplementedError, match="SERVICE_SLUG"):
            svc._output_dir("2026-04-01")

    def test_output_dir_returns_correct_path_when_slug_set(self, tmp_path):
        """_output_dir returns DATA_OUTPUT/slug/YYYY-MM given fecha_desde."""
        svc = _ConcreteService()
        with patch.object(settings, "DATA_OUTPUT", tmp_path):
            result = svc._output_dir("2026-04-01")
        assert result == tmp_path / "test-service" / "2026-04"
