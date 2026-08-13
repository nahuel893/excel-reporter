"""Wiring tests for cupo-desagregado: config -> merge_filters -> handler -> service."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config.models import GlobalFilters, ReportEntry
from src.config.resolver import merge_filters
from src.services.cupo_desagregado import CupoDesagregadoConfig, CupoDesagregadoResult

CONFIG_REAL = Path("configs/cupo_desagregado.json")


class TestConfigJson:
    def test_el_config_de_ejemplo_es_valido(self):
        from src.config.resolver import load_report_config

        config = load_report_config(CONFIG_REAL)
        assert config.tipo == "cupo-desagregado"
        assert config.filtros.cupos_source_path

    def test_el_config_declara_el_token_de_periodo(self):
        cfg = json.loads(CONFIG_REAL.read_text(encoding="utf-8"))
        assert "{MES}" in cfg["reportes"][0]["nombre"]


class TestMergeFilters:
    def test_los_filtros_del_cupo_llegan_al_handler(self):
        # Un filtro nuevo que no se agrega a merge_filters se pierde en silencio.
        globales = GlobalFilters(
            fecha_desde="2026-07-01",
            fecha_hasta="2026-07-31",
            cupos_source_path="/tmp/Objetivo.xlsx",
            cupos_hoja="JULIO",
            historia_desde="2026-06-01",
            historia_hasta="2026-07-01",
        )
        merged = merge_filters(globales, None)

        assert merged["cupos_source_path"] == "/tmp/Objetivo.xlsx"
        assert merged["cupos_hoja"] == "JULIO"
        assert merged["historia_desde"] == "2026-06-01"
        assert merged["historia_hasta"] == "2026-07-01"

    def test_los_opcionales_por_defecto_son_none(self):
        merged = merge_filters(
            GlobalFilters(fecha_desde="2026-07-01", fecha_hasta="2026-07-31"), None)

        assert merged["cupos_source_path"] is None
        assert merged["cupos_hoja"] is None
        assert merged["historia_desde"] is None


def _merged(**overrides):
    base = {
        "fecha_desde": "2026-07-01",
        "fecha_hasta": "2026-07-31",
        "cupos_source_path": "/tmp/Objetivo.xlsx",
        "cupos_hoja": None,
        "historia_desde": None,
        "historia_hasta": None,
    }
    base.update(overrides)
    return base


def _resultado(errores=None):
    return CupoDesagregadoResult(
        ruta_archivo=Path("/tmp/salida.xlsx"),
        registros_procesados=3,
        vendedores=2,
        filas_ruta=3,
        errores_validacion=errores or {},
    )


class TestHandler:
    def test_construye_la_config_y_devuelve_el_artefacto(self):
        import main as main_module

        servicio = MagicMock()
        servicio.generar_reporte.return_value = _resultado()

        with patch.object(main_module, "_run_cupo_desagregado_report",
                          main_module._run_cupo_desagregado_report), \
             patch("src.services.cupo_desagregado.CupoDesagregadoService",
                   return_value=servicio):
            artefactos = main_module._run_cupo_desagregado_report(
                ReportEntry(nombre="CUPO DESAGREGADO POR RUTA - JULIO 2026"),
                _merged(),
            )

        config = servicio.generar_reporte.call_args[0][0]
        assert isinstance(config, CupoDesagregadoConfig)
        assert config.cupos_source_path == "/tmp/Objetivo.xlsx"
        assert config.nombre_archivo == "CUPO DESAGREGADO POR RUTA - JULIO 2026"
        assert artefactos == [
            (Path("/tmp/salida.xlsx"),
             {"nombre": "CUPO DESAGREGADO POR RUTA - JULIO 2026", "fecha": "2026-07-31"})
        ]

    def test_sin_archivo_fuente_no_llama_al_servicio(self, capsys):
        import main as main_module

        with patch("src.services.cupo_desagregado.CupoDesagregadoService") as servicio:
            artefactos = main_module._run_cupo_desagregado_report(
                ReportEntry(nombre="X"), _merged(cupos_source_path=None))

        assert artefactos == []
        servicio.assert_not_called()
        assert "cupos_source_path" in capsys.readouterr().out

    def test_un_reparto_que_no_cierra_no_se_entrega(self, capsys):
        # Preferimos no entregar nada antes que mandar un cupo mal abierto.
        import main as main_module

        servicio = MagicMock()
        servicio.generar_reporte.return_value = _resultado(
            errores={"PEREZ JUAN/SALTA": 10.0})

        with patch("src.services.cupo_desagregado.CupoDesagregadoService",
                   return_value=servicio):
            artefactos = main_module._run_cupo_desagregado_report(
                ReportEntry(nombre="X"), _merged())

        assert artefactos == []
        salida = capsys.readouterr().out
        assert "PEREZ JUAN/SALTA" in salida

    def test_archivo_fuente_inexistente_no_rompe_el_run(self, capsys):
        import main as main_module

        servicio = MagicMock()
        servicio.generar_reporte.side_effect = FileNotFoundError("no existe")

        with patch("src.services.cupo_desagregado.CupoDesagregadoService",
                   return_value=servicio):
            artefactos = main_module._run_cupo_desagregado_report(
                ReportEntry(nombre="X"), _merged())

        assert artefactos == []
        assert "no existe" in capsys.readouterr().out


class TestConfigDelServicio:
    def test_deriva_hoja_y_ventana_de_historia_del_mes(self):
        config = CupoDesagregadoConfig(
            fecha_desde="2026-08-01", fecha_hasta="2026-08-31",
            cupos_source_path="/tmp/Objetivo.xlsx",
        )
        from datetime import date

        assert config.resolver_hoja() == "AGOSTO"
        assert config.resolver_historia() == (date(2026, 7, 1), date(2026, 8, 1))

    def test_la_ventana_explicita_gana(self):
        from datetime import date

        config = CupoDesagregadoConfig(
            fecha_desde="2026-08-01", fecha_hasta="2026-08-31",
            cupos_source_path="/tmp/Objetivo.xlsx",
            historia_desde="2026-05-01", historia_hasta="2026-08-01",
        )
        assert config.resolver_historia() == (date(2026, 5, 1), date(2026, 8, 1))

    def test_sin_archivo_fuente_la_config_falla_temprano(self):
        with pytest.raises(ValueError, match="cupos_source_path"):
            CupoDesagregadoConfig(fecha_desde="2026-08-01", fecha_hasta="2026-08-31")
