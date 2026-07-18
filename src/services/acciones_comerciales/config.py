"""Configuration for the acciones-comerciales service (RF-22).

Phase 1 (BASE control, this slice) only needs fecha range + input_dir
(wapi.xlsx / compras.xls location). The Phase-2 fields (escribir_informe,
informe_path, esperar_wapi_fresco, wapi_cobertura_requerida) are already
modeled here — with safe, inert defaults — so the config schema does not
change shape again when S5/S7 wire the gated behaviors; they simply start
consuming fields that already exist and default to OFF.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class AccionesComercialesConfig:
    """Configuracion para el reporte de acciones comerciales.

    Phase-1 (BASE control) fields:
      fecha_desde / fecha_hasta: date range for the gold aexcel-equivalent
        extraction and the wapi/compras period scope.
      input_dir: directory holding ``wapi.xlsx`` and ``compras.xls``.
      nombre_archivo: BASE control output filename (without extension).
      output_dir: override for the conventional
        ``data/output/acciones-comerciales/{YYYY-MM}/`` path (mainly for
        tests).

    Phase-2 (flag-gated, RF-13) fields — default OFF/inert until the
    sign-off gate (Decision 7) and S5-S7 wire the behaviors that consume
    them:
      escribir_informe: master gate for ANY write to the external INFORME
        file. MUST default to False.
      informe_path: path to the external INFORME .xlsm/.xlsx (never
        touched while escribir_informe is False).
      esperar_wapi_fresco: opt-in for the run_daily wapi-freshness gate
        (RF-20).
      wapi_cobertura_requerida: freshness threshold config knob (e.g.
        "habil_anterior" — Decision 16 default).
    """

    fecha_desde: str
    fecha_hasta: str
    input_dir: str
    nombre_archivo: str | None = None
    output_dir: Path | None = None

    # Phase-2 (flag-gated) — inert defaults.
    escribir_informe: bool = False
    informe_path: str | None = None
    esperar_wapi_fresco: bool = False
    wapi_cobertura_requerida: str = "habil_anterior"

    @property
    def wapi_path(self) -> Path:
        """Path to wapi.xlsx inside input_dir."""
        return Path(self.input_dir) / "wapi.xlsx"

    @property
    def compras_path(self) -> Path:
        """Path to compras.xls inside input_dir."""
        return Path(self.input_dir) / "compras.xls"
