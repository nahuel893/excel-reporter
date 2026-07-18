"""RED tests — S1.7: Phase-1 CLI/service skeleton (RF-22).

Covers:
  - AccionesComercialesConfig defaults (escribir_informe=False — RF-13).
  - AccionesComercialesService writes ONLY under
    data/output/acciones-comerciales/{YYYY-MM}/ (service_output_dir
    convention) and never touches any external file (informe_path) when
    escribir_informe is False (default).
  - main.py wiring: REPORT_HANDLERS["acciones-comerciales"], ReportConfig
    accepts the new "tipo", merge_filters carries the new custom filtros
    through, and the full `python main.py --config <file>` path (global
    --config, RF-22's literal scenario) dispatches end-to-end with zero
    external-file writes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import load_workbook

from src.services.acciones_comerciales.config import AccionesComercialesConfig
from src.services.acciones_comerciales.service import (
    AccionesComercialesResult,
    AccionesComercialesService,
)


# ─────────────────────────────────────────────────────────────────────────
# config.py — AccionesComercialesConfig
# ─────────────────────────────────────────────────────────────────────────


class TestAccionesComercialesConfig:
    def test_escribir_informe_defaults_false(self, tmp_path):
        config = AccionesComercialesConfig(
            fecha_desde="2026-07-01",
            fecha_hasta="2026-07-31",
            input_dir=str(tmp_path),
        )

        assert config.escribir_informe is False

    def test_wapi_and_compras_path_properties(self, tmp_path):
        config = AccionesComercialesConfig(
            fecha_desde="2026-07-01",
            fecha_hasta="2026-07-31",
            input_dir=str(tmp_path),
        )

        assert config.wapi_path == tmp_path / "wapi.xlsx"
        assert config.compras_path == tmp_path / "compras.xls"


# ─────────────────────────────────────────────────────────────────────────
# service.py — AccionesComercialesService skeleton
# ─────────────────────────────────────────────────────────────────────────


class TestAccionesComercialesServiceSkeleton:
    def test_service_slug_and_granularity(self):
        assert AccionesComercialesService.SERVICE_SLUG == "acciones-comerciales"
        assert AccionesComercialesService.GRANULARITY == "month"

    def test_writes_base_control_under_conventional_output_dir(self, tmp_path):
        with patch("config.settings.DATA_OUTPUT", tmp_path / "out"):
            service = AccionesComercialesService()
            config = AccionesComercialesConfig(
                fecha_desde="2026-07-01",
                fecha_hasta="2026-07-31",
                input_dir=str(tmp_path / "input"),
                nombre_archivo="BASE control TEST",
            )
            result = service.generar_reporte(config)

        expected_dir = tmp_path / "out" / "acciones-comerciales" / "2026-07"
        assert result.ruta_archivo.parent == expected_dir
        assert result.ruta_archivo.exists()
        assert isinstance(result, AccionesComercialesResult)

    def test_zero_external_file_writes_when_escribir_informe_false(self, tmp_path):
        """RF-13/RF-22: default run (flag OFF) touches nothing outside
        data/output — the informe_path is never created/modified."""
        informe_path = tmp_path / "INFO - ACCIONES BADIE JULIO 2026.xlsm"

        with patch("config.settings.DATA_OUTPUT", tmp_path / "out"):
            service = AccionesComercialesService()
            config = AccionesComercialesConfig(
                fecha_desde="2026-07-01",
                fecha_hasta="2026-07-31",
                input_dir=str(tmp_path / "input"),
                nombre_archivo="BASE control TEST",
                escribir_informe=False,
                informe_path=str(informe_path),
            )
            service.generar_reporte(config)

        assert not informe_path.exists()

    def test_output_sheet_has_total_general_row(self, tmp_path):
        """Project rule: every generated sheet ends with a TOTAL GENERAL row."""
        with patch("config.settings.DATA_OUTPUT", tmp_path / "out"):
            service = AccionesComercialesService()
            config = AccionesComercialesConfig(
                fecha_desde="2026-07-01",
                fecha_hasta="2026-07-31",
                input_dir=str(tmp_path / "input"),
                nombre_archivo="BASE control TEST",
            )
            result = service.generar_reporte(config)

        wb = load_workbook(str(result.ruta_archivo))
        ws = wb.active
        values_col_a = [ws.cell(r, 1).value for r in range(1, ws.max_row + 1)]
        assert "TOTAL GENERAL" in values_col_a


# ─────────────────────────────────────────────────────────────────────────
# main.py wiring — REPORT_HANDLERS, config models, merge_filters, full CLI
# ─────────────────────────────────────────────────────────────────────────


class TestMainWiring:
    def test_report_handlers_registers_acciones_comerciales(self):
        import main as main_module

        assert (
            main_module.REPORT_HANDLERS.get("acciones-comerciales")
            == "_run_acciones_comerciales_report"
        )

    def test_report_config_accepts_acciones_comerciales_tipo(self):
        from src.config.models import ReportConfig

        raw = {
            "tipo": "acciones-comerciales",
            "filtros": {
                "fecha_desde": "2026-07-01",
                "fecha_hasta": "2026-07-31",
                "input_dir": "/tmp/does-not-matter",
            },
            "reportes": [{"nombre": "BASE control TEST"}],
        }
        cfg = ReportConfig.model_validate(raw)

        assert cfg.tipo == "acciones-comerciales"
        assert cfg.filtros.input_dir == "/tmp/does-not-matter"
        assert cfg.filtros.escribir_informe is False

    def test_merge_filters_carries_new_fields(self):
        from src.config.models import GlobalFilters
        from src.config.resolver import merge_filters

        global_f = GlobalFilters(
            fecha_desde="2026-07-01",
            fecha_hasta="2026-07-31",
            input_dir="/tmp/acciones-input",
            escribir_informe=True,
            informe_path="/tmp/informe.xlsm",
            esperar_wapi_fresco=True,
            wapi_cobertura_requerida="habil_anterior",
        )

        merged = merge_filters(global_f, None)

        assert merged["input_dir"] == "/tmp/acciones-input"
        assert merged["escribir_informe"] is True
        assert merged["informe_path"] == "/tmp/informe.xlsm"
        assert merged["esperar_wapi_fresco"] is True
        assert merged["wapi_cobertura_requerida"] == "habil_anterior"

    def test_run_acciones_comerciales_report_returns_path_and_meta(self, tmp_path):
        import main as main_module

        report = type("Report", (), {"nombre": "BASE control TEST"})()
        merged = {
            "fecha_desde": "2026-07-01",
            "fecha_hasta": "2026-07-31",
            "input_dir": str(tmp_path / "input"),
            "escribir_informe": False,
            "informe_path": None,
            "esperar_wapi_fresco": False,
            "wapi_cobertura_requerida": None,
        }

        with patch("config.settings.DATA_OUTPUT", tmp_path / "out"):
            artifacts = main_module._run_acciones_comerciales_report(report, merged)

        assert len(artifacts) == 1
        path, meta = artifacts[0]
        assert isinstance(path, Path)
        assert path.exists()
        assert meta["nombre"] == "BASE control TEST"

    def test_full_cli_global_config_flag_dispatches_end_to_end(self, tmp_path, monkeypatch):
        """RF-22 literal scenario: `python main.py --config <file>` with
        Phase-2 flag OFF writes BASE control under data/output and touches
        nothing else."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        informe_path = tmp_path / "INFO - ACCIONES BADIE JULIO 2026.xlsm"

        config_path = tmp_path / "acciones_comerciales.json"
        config_path.write_text(
            json.dumps(
                {
                    "tipo": "acciones-comerciales",
                    "filtros": {
                        "fecha_desde": "2026-07-01",
                        "fecha_hasta": "2026-07-31",
                        "input_dir": str(input_dir),
                        "escribir_informe": False,
                        "informe_path": str(informe_path),
                        "enviar_email": False,
                        "enviar_whatsapp": False,
                    },
                    "reportes": [{"nombre": "BASE control TEST"}],
                }
            ),
            encoding="utf-8",
        )

        with patch("config.settings.DATA_OUTPUT", tmp_path / "out"):
            monkeypatch.setattr(sys, "argv", ["main.py", "--config", str(config_path)])
            import main

            result = main.main()

        assert result == 0
        expected_dir = tmp_path / "out" / "acciones-comerciales" / "2026-07"
        assert expected_dir.is_dir()
        assert any(expected_dir.glob("*.xlsx"))
        assert not informe_path.exists()
