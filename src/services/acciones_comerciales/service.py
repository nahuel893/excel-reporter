"""AccionesComercialesService — Phase-1 full orchestration (RF-22).

Generates the 6-sheet BASE control workbook for acciones-comerciales into
``data/output/acciones-comerciales/{YYYY-MM}/`` (service_output_dir
convention): gold aexcel-equivalent extraction (RF-01) -> wapi ingestion
(RF-02) -> derived-column enrichment (RF-04..RF-08) -> the 4 pivots (RF-09)
-> the BASE control + reconciliation writer (RF-10, RF-11).

Phase-1 scope note (spec-grounded): ``compras.xls`` (RF-03) is NOT read
here. Every RF that names a Phase-1 artifact — the 4 pivots (RF-09), the
BASE control workbook's 6 sheets (RF-10), and the reconciliation sheet
(RF-11) — sources exclusively from the aexcel-equivalent (gold) and wapi
data. compras only appears in RF-17 (the Phase-2 informe faithful paste,
flag-gated) and the future RF-12 diff harness. Wiring compras into Phase-1
here would be scope creep with no consuming sheet; ``readers/compras.py``
(S1, already implemented + tested standalone) stays ready for S5/S4.

Phase 2 (informe write, captures, delivery) stays behind
``config.escribir_informe`` (default False, RF-13) — this service never
touches ``config.informe_path``.

CRITICAL WIRING NOTE (Decision 14 / RF-05): ``processor.build_precio_lookup``
keys on the RAW aexcel ``(Descripción Período, Cod. Cliente, Código)`` and
``processor.enrich_wapi`` looks up the RAW wapi ``(Fecha, Cod. Cliente,
Artículo Distribuidora)``. Both date columns are normalized to the SAME
``YYYY-MM-DD`` string form (``_normalize_fecha_col``) before either lookup
is built/used — otherwise a Timestamp-vs-string dtype mismatch would make
every terna miss and PRECIO FINAL universally blank.

Decision 19 (parallel-run comparison, BASE-control ONLY): alongside the
authoritative terna-based PRECIO FINAL above, this service also loads a
comprobante-keyed diagnostic price (``DataLoader.get_comprobante_precio`` +
``processor.build_precio_comprobante_lookup``) and passes it into
``enrich_wapi`` as the optional ``precio_comprobante_por_clave`` — it never
replaces or influences the terna PRECIO FINAL/Total2/Descuento/pivots, it
only feeds an extra diagnostic column + a BASE-control reconciliation
comparison section. Both sides' ``Comprobante`` are normalized
(``astype(str).str.strip()``) before the exact-match lookup is built.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.services.acciones_comerciales.config import AccionesComercialesConfig
from src.services.acciones_comerciales.constants import (
    ZONA_CONFIG_PATH,
)
from src.services.acciones_comerciales.diff import run_diff_step
from src.services.acciones_comerciales.gold_source import (
    load_aexcel_equivalent,
    load_sucursal_por_cliente,
)
from src.services.acciones_comerciales.pivots import (
    build_acc_gen,
    build_art_accion,
    build_cliente_fecha,
    build_fact_net,
)
from src.services.acciones_comerciales.processor import (
    build_precio_comprobante_lookup,
    build_precio_lookup,
    enrich_wapi,
    load_supervisor_por_sucursal,
)
from src.services.acciones_comerciales.readers.wapi import read_wapi
from src.services.acciones_comerciales.writers.base_control import (
    ReconciliationInputs,
    build_base_control_workbook,
)
from src.services.base_service import BaseService

logger = logging.getLogger(__name__)

_AEXCEL_FECHA_COL = "Descripción Período"
_WAPI_FECHA_COL = "Fecha"


@dataclass
class AccionesComercialesResult:
    """Resultado de la generacion del reporte de acciones comerciales.

    ``diff_report_paths`` — cuando ``config.backup_dir`` esta seteado y hay un
    workbook de backup, contiene {"json"/"xlsx"/"summary": Path} del reporte
    de diff paralelo (RF-12, S4) escrito junto al BASE. None en caso contrario.
    """

    ruta_archivo: Path
    registros_procesados: int
    diff_report_paths: dict | None = None


def _normalize_fecha_col(series: pd.Series) -> pd.Series:
    """Normalize a date-ish column (date / Timestamp / string) to ISO
    ``YYYY-MM-DD`` strings so the aexcel/wapi terna keys match regardless
    of their original dtype (S3 wiring note, RF-05)."""
    return pd.to_datetime(series).dt.strftime("%Y-%m-%d")


class AccionesComercialesService(BaseService):
    """Genera el reporte de acciones comerciales (Phase 1: BASE control)."""

    SERVICE_SLUG = "acciones-comerciales"
    GRANULARITY = "month"

    def generar_reporte(self, config: AccionesComercialesConfig) -> AccionesComercialesResult:
        if not self.validar_fechas(config.fecha_desde, config.fecha_hasta):
            raise ValueError(
                "fecha_desde/fecha_hasta invalidas — formato esperado YYYY-MM-DD"
            )

        output_dir = (
            Path(config.output_dir) if config.output_dir else self._output_dir(config.fecha_desde)
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        nombre = config.nombre_archivo or "BASE control Acciones Comerciales"

        # 1. Gold aexcel-equivalent extraction + deterministic grain-collapse
        #    (RF-01, Decision 14).
        aexcel_result = load_aexcel_equivalent(
            self.data_loader, config.fecha_desde, config.fecha_hasta
        )
        aexcel_data = aexcel_result.data.copy()
        if not aexcel_data.empty:
            aexcel_data[_AEXCEL_FECHA_COL] = _normalize_fecha_col(aexcel_data[_AEXCEL_FECHA_COL])

        # 2. wapi ingestion (RF-02).
        wapi_raw = read_wapi(config.wapi_path).copy()
        if not wapi_raw.empty:
            wapi_raw[_WAPI_FECHA_COL] = _normalize_fecha_col(wapi_raw[_WAPI_FECHA_COL])
            wapi_raw["Comprobante"] = wapi_raw["Comprobante"].astype(str).str.strip()

        # 3. Fresh lookups (RF-04, RF-05, RF-07).
        sucursal_por_cliente = load_sucursal_por_cliente(self.data_loader)
        supervisor_por_sucursal = load_supervisor_por_sucursal(ZONA_CONFIG_PATH)
        precio_por_terna = build_precio_lookup(aexcel_data)

        # 3b. Decision 19 — comprobante-based diagnostic price (BASE-control
        #     ONLY parallel-run comparison; never feeds the authoritative
        #     terna-based PRECIO FINAL above).
        comprobante_data = self.data_loader.get_comprobante_precio(
            config.fecha_desde, config.fecha_hasta
        )
        if not comprobante_data.empty:
            comprobante_data = comprobante_data.copy()
            comprobante_data["Comprobante"] = comprobante_data["Comprobante"].astype(str).str.strip()
        precio_comprobante_por_clave = build_precio_comprobante_lookup(comprobante_data)

        # 4. Derived wapi columns (RF-04..RF-08 + Decision 19 diagnostic).
        enriched = enrich_wapi(
            wapi_raw,
            sucursal_por_cliente=sucursal_por_cliente,
            precio_por_terna=precio_por_terna,
            supervisor_por_sucursal=supervisor_por_sucursal,
            precio_comprobante_por_clave=precio_comprobante_por_clave,
        )

        # 5. The 4 pivots (RF-09).
        fact_net = build_fact_net(aexcel_data)
        art_accion = build_art_accion(enriched.data)
        cliente_fecha = build_cliente_fecha(enriched.data)
        acc_gen = build_acc_gen(enriched.data)

        # 6. BASE control workbook + reconciliation (RF-10, RF-11).
        reconciliation = ReconciliationInputs(
            aexcel_data=aexcel_data,
            wapi_enriched=enriched.data,
            multi_price_ternas=aexcel_result.multi_price_ternas,
            unresolved_sucursal=enriched.unresolved_sucursal,
            unresolved_precio=enriched.unresolved_precio,
            fecha_desde=config.fecha_desde,
            fecha_hasta=config.fecha_hasta,
        )
        ruta = build_base_control_workbook(
            nombre_archivo=nombre,
            output_dir=output_dir,
            fact_net=fact_net,
            art_accion=art_accion,
            cliente_fecha=cliente_fecha,
            acc_gen=acc_gen,
            wapi_enriched=enriched.data,
            reconciliation=reconciliation,
        )

        logger.info("Acciones Comerciales BASE control generado: %s", ruta)

        # 7. Optional Phase-1 parallel-diff step (RF-12, S4) — off unless
        #    config.backup_dir points at a manual-backup workbook. Writes the
        #    diff report NEXT TO the BASE output; never fails the BASE run.
        diff_report_paths = None
        if config.backup_dir:
            base_frames = {
                "FACT_NET": fact_net,
                "ART-ACCION": art_accion,
                "CLIENTE-FECHA": cliente_fecha,
                "ACC-GEN": acc_gen,
            }
            generated_ternas = self._generated_ternas(aexcel_data)
            diff_report_paths = run_diff_step(
                base_frames=base_frames,
                backup_dir=config.backup_dir,
                aexcel_path=config.aexcel_path,
                generated_ternas=generated_ternas,
                fecha_desde=config.fecha_desde,
                fecha_hasta=config.fecha_hasta,
                output_dir=output_dir,
            )

        return AccionesComercialesResult(
            ruta_archivo=ruta,
            registros_procesados=len(aexcel_data),
            diff_report_paths=diff_report_paths,
        )

    @staticmethod
    def _generated_ternas(aexcel_data: pd.DataFrame) -> pd.DataFrame | None:
        """The generated terna->precio/Bonific table (RF-01 picked-line
        values) the diff harness validates empirically against the real
        aexcel (Decision 14). None when the aexcel-equivalent is empty."""
        cols = ["Descripción Período", "Cod. Cliente", "Código", "Precio", "Bonific"]
        if aexcel_data.empty or not all(c in aexcel_data.columns for c in cols):
            return None
        return aexcel_data[cols].copy()
