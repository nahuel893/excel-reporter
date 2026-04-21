"""
CLI para generacion de reportes CCU.

Modos de uso:
    # Un informe con config nueva (recomendado)
    python main.py ventas --config configs/ventas.json

    # Todos los informes de un directorio
    python main.py --config-dir configs/

    # Args individuales (legacy)
    python main.py ventas --desde 2026-01-01 --hasta 2026-01-31
    python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --genericos "CERVEZAS,AGUAS"

    # Config legacy (sin contactos/reportes)
    python main.py ventas --config config.json

Subcomandos disponibles:
    ventas           - Reporte de ventas por sucursal, generico y marca
    resumen-mensual  - Resumen mensual por generico (ultimos dias, tendencia, anio anterior)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from src.services import VentasService, ResumenMensualService, ResumenMensualConfig
from src.services.ventas import ReporteVentasConfig

logger = logging.getLogger(__name__)


def _resolve_test_mode(cli_flag: bool) -> bool:
    """Test mode activates if --test-mode CLI flag OR INFORMES_TEST_MODE=1 env var."""
    return bool(cli_flag) or os.getenv("INFORMES_TEST_MODE", "0") == "1"


def validar_fecha(fecha_str: str) -> bool:
    """Valida que la fecha tenga formato YYYY-MM-DD."""
    try:
        datetime.strptime(fecha_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def parsear_genericos(genericos_str: str | None) -> list[str] | None:
    """Parsea string de genericos separados por coma."""
    if not genericos_str:
        return None
    return [g.strip() for g in genericos_str.split(",")]


# ---------------------------------------------------------------------------
# New config format — per-report delivery pipeline
# ---------------------------------------------------------------------------

SERVICIOS = {
    "ventas": "ventas",
    "resumen-mensual": "resumen-mensual",
}


def _run_report_config(
    config_path: Path, contactos_path: Path | None = None, test_mode: bool = False
) -> int:
    """Execute a single report config file (new format)."""
    from pydantic import ValidationError

    from src.config.resolver import load_contacts, load_report_config

    try:
        report_config = load_report_config(config_path)
    except (FileNotFoundError, ValidationError) as exc:
        print(f"Error: config invalida en {config_path}:\n{exc}")
        return 1

    # Load contacts from same dir or explicit path
    if contactos_path is None:
        contactos_path = config_path.parent / "contactos.json"

    contactos = {}
    if contactos_path.exists():
        try:
            contactos = load_contacts(contactos_path)
        except (FileNotFoundError, ValidationError) as exc:
            print(f"Error: contactos invalidos en {contactos_path}:\n{exc}")
            return 1

    # Validate contact references
    try:
        report_config.validate_contacts(contactos)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    return _run_reportes(report_config, contactos, test_mode=test_mode)


def _run_config_dir(config_dir: Path, test_mode: bool = False) -> int:
    """Execute all report config files in a directory."""
    config_dir = Path(config_dir)
    if not config_dir.is_dir():
        print(f"Error: directorio no encontrado: {config_dir}")
        return 1

    contactos_path = config_dir / "contactos.json"
    config_files = sorted(
        f for f in config_dir.glob("*.json") if f.name != "contactos.json"
    )

    if not config_files:
        print(f"Error: no se encontraron archivos .json en {config_dir}")
        return 1

    print(f"Procesando {len(config_files)} config(s) desde {config_dir}/")
    exit_code = 0
    for config_file in config_files:
        print(f"\n{'=' * 60}")
        print(f"Config: {config_file.name}")
        print(f"{'=' * 60}")
        result = _run_report_config(config_file, contactos_path, test_mode=test_mode)
        if result != 0:
            exit_code = result

    return exit_code


def _run_reportes(report_config, contactos, test_mode: bool = False) -> int:
    """Iterate over reportes[], generate each file, run delivery pipeline."""
    from src.config.resolver import merge_filters, resolve_delivery

    for report in report_config.reportes:
        merged = merge_filters(report_config.filtros, report.filtros)

        print(f"\nGenerando: {report.nombre}")

        if report_config.tipo == "ventas":
            artifacts = _run_ventas_report(report, merged)
        elif report_config.tipo == "resumen-mensual":
            artifacts = _run_resumen_report(report, merged)
        elif report_config.tipo == "mision-imposible":
            artifacts = _run_mision_report(report, merged)
        elif report_config.tipo == "historico-fratelli":
            artifacts = _run_historico_fratelli_report(report, merged)
        elif report_config.tipo == "stock-diario":
            artifacts = _run_stock_diario_report(report, merged)
        elif report_config.tipo == "cartesiano":
            artifacts = _run_cartesiano_report(report, merged)
        elif report_config.tipo == "avances":
            artifacts = _run_avances_report(report, merged)
        elif report_config.tipo == "graficos-cobertura":
            artifacts = _run_graficos_cobertura_report(report, merged)
        elif report_config.tipo == "ventas-articulo":
            artifacts = _run_ventas_articulo_report(report, merged)
        else:
            print(f"Error: tipo de reporte desconocido: {report_config.tipo}")
            return 1

        if not artifacts:
            continue  # error already printed

        # Run delivery pipeline for EACH generated file
        delivery_config = resolve_delivery(
            report,
            contactos,
            enviar_email=merged["enviar_email"],
            enviar_whatsapp=merged["enviar_whatsapp"],
            test_mode=test_mode,
        )
        if delivery_config:
            for ruta_archivo, metadata in artifacts:
                _ejecutar_pipeline(
                    ruta_excel=ruta_archivo,
                    delivery_config=delivery_config,
                    metadata=metadata,
                )

    return 0


def _run_ventas_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate ventas report(s). Returns list of (path, metadata) tuples."""
    config = ReporteVentasConfig(
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        genericos=merged["genericos"],
        nombre_archivo=report.nombre,
        con_slicers=merged["con_slicers"],
        con_cobertura=merged["con_cobertura"],
    )

    service = VentasService()

    # Build supervisor dict from merged filters
    supervisores = None
    if merged["supervisores"]:
        sucursales = merged["sucursales"] or []
        supervisores = {s: sucursales for s in merged["supervisores"]}

    if supervisores:
        results = service.generar_reporte_supervisores(config, supervisores)
        artifacts = []
        for result in results:
            _imprimir_resultado(result, merged["con_slicers"])
            artifacts.append(
                (
                    Path(result.ruta_archivo),
                    {
                        "nombre": f"Ventas {result.supervisor}",
                        "fecha": merged["fecha_hasta"],
                    },
                )
            )
        return artifacts
    else:
        result = service.generar_reporte(config)
        _imprimir_resultado(result, merged["con_slicers"])
        return [
            (
                Path(result.ruta_archivo),
                {"nombre": report.nombre, "fecha": merged["fecha_hasta"]},
            )
        ]


def _run_resumen_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate resumen mensual report. Returns list of (path, metadata) tuples."""
    config = ResumenMensualConfig(
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        genericos=merged["genericos"],
        nombre_archivo=report.nombre,
    )

    result = ResumenMensualService().generar_reporte(config)

    print("Resumen mensual generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Hojas: {', '.join(result.hojas)}")
    print(f"  - Registros procesados: {result.registros_procesados}")
    print(f"  - Sucursales: {result.sucursales}")
    print(f"  - Genericos: {len(result.genericos_incluidos)}")

    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged["fecha_hasta"]},
        )
    ]


def _run_mision_report(report, merged: dict) -> list[tuple[Path, dict]]:
    from src.services.mision_imposible import (
        MisionImposibleConfig,
        MisionImposibleService,
    )

    config = MisionImposibleConfig(
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        genericos=merged["genericos"],
        categorias=merged.get("categorias"),
        nombre_archivo=report.nombre,
    )
    result = MisionImposibleService().generar_reporte(config)
    print("Mision Imposible generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Hojas: {', '.join(result.hojas)}")
    print(f"  - Registros procesados: {result.registros_procesados}")
    print(f"  - Sucursales: {result.sucursales}")
    print(f"  - Genericos: {len(result.genericos_incluidos)}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged["fecha_hasta"]},
        )
    ]


def _run_stock_diario_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate stock-diario report(s). Returns list of (path, metadata) tuples."""
    from src.services.stock_diario import StockDiarioConfig, StockDiarioService

    supervisores = merged.get("supervisores")
    supervisor_name = supervisores[0] if supervisores else None

    config = StockDiarioConfig(
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        genericos=merged.get("genericos"),
        nombre_archivo=report.nombre,
        sucursales=merged.get("sucursales"),
        supervisor=supervisor_name,
    )
    result = StockDiarioService().generar_reporte(config)

    print("Stock Diario generado exitosamente:")
    print(f"  - Archivos generados: {len(result.archivos_generados)}")
    if result.fechas_sin_datos:
        print(f"  - Fechas sin datos: {', '.join(result.fechas_sin_datos)}")

    return [
        (
            Path(ruta),
            {"nombre": report.nombre, "fecha": ruta.stem},
        )
        for ruta in result.archivos_generados
    ]


def _run_historico_fratelli_report(report, merged: dict) -> list[tuple[Path, dict]]:
    from src.services.historico_fratelli import (
        HistoricoFratelliConfig,
        HistoricoFratelliService,
    )

    config = HistoricoFratelliConfig(nombre_archivo=report.nombre)
    result = HistoricoFratelliService().generar_reporte(config)
    print("Historico FRATELLI B generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Hojas: {', '.join(result.hojas)}")
    print(f"  - Registros procesados: {result.registros_procesados}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")},
        )
    ]


# ---------------------------------------------------------------------------
# Delivery pipeline execution
# ---------------------------------------------------------------------------


def _ejecutar_pipeline(
    ruta_excel: Path,
    delivery_config=None,
    cfg: dict | None = None,
    metadata: dict | None = None,
) -> None:
    """Execute the delivery pipeline.

    Supports two calling conventions:
    - New format: delivery_config is a DeliveryConfig object (from resolver)
    - Legacy format: cfg is a raw dict with cfg["delivery"] (parsed here)
    """
    from pydantic import ValidationError

    from src.delivery.pipeline import DeliveryConfig, DeliveryPipeline, ReportArtifact
    from src.delivery.steps import CaptureImageStep, SendEmailStep, SendWhatsAppStep

    if delivery_config is None:
        # Legacy path: parse from raw dict
        if cfg is None or "delivery" not in cfg:
            return
        try:
            delivery_config = DeliveryConfig.model_validate(cfg["delivery"])
        except ValidationError as exc:
            print(f"Error: configuracion de delivery invalida:\n{exc}")
            return

    artifact = ReportArtifact(
        ruta_excel=ruta_excel,
        metadata=metadata or {},
    )

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s"
    )
    pipeline = DeliveryPipeline(
        [CaptureImageStep(), SendEmailStep(), SendWhatsAppStep()]
    )
    result = pipeline.run(artifact, delivery_config)

    print("\nPipeline de entrega:")
    for step in result.steps:
        icon = {"success": "✓", "skipped": "-", "error": "✗"}.get(step.status, "?")
        print(f"  [{icon}] {step.step_name}: {step.message}")

    if not result.success:
        print("  Advertencia: algunos pasos fallaron (ver logs).")


# ---------------------------------------------------------------------------
# Legacy config support
# ---------------------------------------------------------------------------


def _cargar_config_json(ruta: str) -> dict:
    """Lee y parsea el archivo JSON de configuracion."""
    path = Path(ruta)
    if not path.exists():
        print(f"Error: archivo de configuracion no encontrado: {path}")
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def _is_new_format(cfg: dict) -> bool:
    """Detect if a config dict uses the new format (has 'reportes' key)."""
    return "reportes" in cfg


def cmd_ventas(args, test_mode: bool = False) -> int:
    """Ejecuta el comando de reporte de ventas."""

    # Cargar configuracion desde JSON si se provee --config
    if args.config:
        config_path = Path(args.config)
        # Try new format first
        cfg = _cargar_config_json(args.config)
        if _is_new_format(cfg):
            return _run_report_config(config_path, test_mode=test_mode)

        # Legacy format
        return _cmd_ventas_legacy(args, cfg, test_mode=test_mode)

    # No config file — use CLI args (legacy)
    return _cmd_ventas_legacy(args, {}, test_mode=test_mode)


def _cmd_ventas_legacy(args, cfg: dict, test_mode: bool = False) -> int:
    """Legacy ventas flow with flat config."""
    if test_mode:
        logger.warning(
            "test-mode no tiene efecto en el flujo legacy. "
            "Usa --config <config.json> con formato nuevo para activarlo."
        )
    # Resolver parametros: JSON tiene precedencia sobre args individuales
    fecha_desde = cfg.get("fecha_desde") or args.desde
    fecha_hasta = cfg.get("fecha_hasta") or args.hasta
    genericos = cfg.get("genericos") or parsear_genericos(args.genericos)
    nombre_archivo = cfg.get("output") or args.output
    con_slicers = cfg.get("con_slicers", args.slicers)
    con_cobertura = cfg.get("con_cobertura", True)
    supervisores = cfg.get("supervisores")  # Solo disponible via JSON

    # Validar campos requeridos
    if not fecha_desde or not fecha_hasta:
        print("Error: fecha_desde y fecha_hasta son requeridos.")
        print("       Usa --desde/--hasta o definelos en --config config.json")
        return 1

    if not validar_fecha(fecha_desde) or not validar_fecha(fecha_hasta):
        print("Error: Las fechas deben tener formato YYYY-MM-DD")
        return 1

    # Crear configuracion del servicio
    config = ReporteVentasConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        genericos=genericos,
        nombre_archivo=nombre_archivo,
        con_slicers=con_slicers,
        con_cobertura=con_cobertura,
    )

    if genericos:
        print(f"Filtrando por genericos: {genericos}")

    service = VentasService()

    # Modo supervisores: genera un archivo por supervisor
    if supervisores:
        print(f"Generando reportes por supervisor: {list(supervisores.keys())}")
        results = service.generar_reporte_supervisores(config, supervisores)
        for result in results:
            print(f"\nSupervisor: {result.supervisor}")
            _imprimir_resultado(result, con_slicers)
        return 0

    # Modo normal: un archivo con todas las sucursales
    print(f"Generando reporte de ventas desde {fecha_desde} hasta {fecha_hasta}...")
    result = service.generar_reporte(config)
    _imprimir_resultado(result, con_slicers)
    _ejecutar_pipeline(
        ruta_excel=Path(result.ruta_archivo),
        cfg=cfg,
        metadata={"nombre": "Ventas", "fecha": fecha_hasta},
    )
    return 0


def _imprimir_resultado(result, con_slicers: bool):
    """Imprime el resultado de un reporte generado."""
    print("Reporte generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Hojas: {', '.join(result.hojas)}")
    print(f"  - Registros de ventas: {result.registros_ventas}")
    print(f"  - Registros procesados: {result.registros_procesados}")
    print(f"  - Sucursales: {result.sucursales}")
    print(f"  - Genericos: {len(result.genericos_incluidos)}")
    if result.slicers_agregados:
        print("  - Slicers: Agregados (Sucursal, Generico, Marca)")
    elif con_slicers:
        print("  - Slicers: No disponibles (requiere Windows + Excel)")


def cmd_resumen_mensual(args, test_mode: bool = False) -> int:
    """Ejecuta el comando de resumen mensual."""

    # Try new format first
    if args.config:
        config_path = Path(args.config)
        cfg = _cargar_config_json(args.config)
        if _is_new_format(cfg):
            return _run_report_config(config_path, test_mode=test_mode)

        # Legacy format
        return _cmd_resumen_legacy(args, cfg, test_mode=test_mode)

    # No config file — use CLI args (legacy)
    return _cmd_resumen_legacy(args, {}, test_mode=test_mode)


def cmd_mision_imposible(args, test_mode: bool = False) -> int:
    """Ejecuta el comando de mision imposible."""
    if not args.config:
        print("Error: mision-imposible requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print(
            "Error: mision-imposible solo soporta el nuevo formato de configuracion JSON."
        )
        return 1


def cmd_historico_fratelli(args, test_mode: bool = False) -> int:
    """Ejecuta el comando de historico fratelli."""
    if not args.config:
        print("Error: historico-fratelli requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print(
            "Error: historico-fratelli solo soporta el nuevo formato de configuracion JSON."
        )
        return 1


def cmd_stock_diario(args, test_mode: bool = False) -> int:
    """Ejecuta el comando de stock diario."""
    if not args.config:
        print("Error: stock-diario requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print(
            "Error: stock-diario solo soporta el nuevo formato de configuracion JSON."
        )
        return 1


def cmd_graficos_cobertura(args, test_mode: bool = False) -> int:
    """Ejecuta el comando de graficos-cobertura."""
    if not args.config:
        print("Error: graficos-cobertura requiere un archivo --config")
        return 1
    return _run_report_config(Path(args.config), test_mode=test_mode)


def cmd_ventas_articulo(args, test_mode: bool = False) -> int:
    """Ejecuta el comando de ventas-articulo-diario."""
    if not args.config:
        print("Error: ventas-articulo requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    return _run_report_config(config_path, test_mode=test_mode)


def _run_ventas_articulo_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate ventas-articulo-diario report. Returns list of (path, metadata) tuples."""
    from src.services.ventas_articulo import VentasArticuloConfig, VentasArticuloService

    config = VentasArticuloConfig(
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        id_articulo=merged.get("id_articulo"),
        id_sucursal=merged.get("id_sucursal"),
        nombre_archivo=report.nombre if report.nombre else None,
    )

    try:
        result = VentasArticuloService().generar_reporte(config)
    except ValueError as exc:
        print(f"Error: {exc}")
        return []

    print("Ventas Articulo Diario generado exitosamente:")
    print(f"  - Articulo: {result.articulo_nombre}")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Dias con venta: {result.dias_con_venta} / {result.registros_procesados}")
    print(f"  - Total bultos: {result.total_bultos}")

    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")},
        )
    ]


def _run_graficos_cobertura_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate graficos-cobertura report. Returns list of (path, metadata) tuples."""
    from src.services.graficos_cobertura.config import GraficosCoberturaConfig
    from src.services.graficos_cobertura.service import GraficosCoberturaService

    config = GraficosCoberturaConfig(
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        id_fuerza_ventas=merged.get("id_fuerza_ventas", 1),
        nombre_archivo=report.nombre,
        con_aguas=merged.get("con_aguas", True),
    )
    result = GraficosCoberturaService().generar_reporte(config)

    print("Graficos Cobertura generado exitosamente:")
    print(f"  - Directorio: {result.ruta_directorio}")
    print(f"  - XLSX: {result.archivo_xlsx.name}")
    print(f"  - PPTX: {result.archivo_generico_pptx.name}")
    print(f"  - Graficos generados: {result.graficos_generados}")

    meta = {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")}
    return [
        (Path(result.archivo_xlsx), meta),
        (Path(result.archivo_generico_pptx), meta),
    ]


def _run_cartesiano_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate cartesiano report. Returns list of (path, metadata) tuples."""
    from src.services.cartesiano import CartesianoConfig, CartesianoService

    config = CartesianoConfig(
        id_sucursal=merged.get("id_sucursal", 1),
        genericos=merged.get("genericos"),
        nombre_archivo=report.nombre,
    )
    result = CartesianoService().generar_reporte(config)
    print("Cartesiano generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Rutas: {result.rutas}")
    print(f"  - Genericos: {result.genericos}")
    print(f"  - Combinaciones: {result.registros_procesados}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")},
        )
    ]


def _run_avances_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate avances report. Returns list of (path, metadata) tuples."""
    import logging

    from src.services.avances import AvancesConfig, AvancesService

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s"
    )

    archivo_plantilla = merged.get("archivo_plantilla")
    if not archivo_plantilla:
        print("Error: avances report requires 'archivo_plantilla' in filtros")
        return []

    config = AvancesConfig(
        archivo_plantilla=archivo_plantilla,
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        id_sucursal=merged.get("id_sucursal") or 1,
        id_fuerza_ventas=merged.get("id_fuerza_ventas") or 1,
        nombre_archivo=report.nombre if report.nombre else None,
    )

    service = AvancesService()
    try:
        result = service.generar_reporte(config)
    except FileNotFoundError as e:
        print(f"Error: Template not found: {e}")
        return []

    print(f"Avances '{report.nombre}' generado exitosamente:")
    for hoja, registros in result.registros_por_hoja.items():
        print(f"  - {hoja}: {registros} registros")
    print(f"  - Archivo: {result.ruta_archivo}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")},
        )
    ]


def cmd_cartesiano(args, test_mode: bool = False) -> int:
    """Ejecuta el comando cartesiano."""
    if not args.config:
        print("Error: cartesiano requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print("Error: cartesiano solo soporta el nuevo formato de configuracion JSON.")
        return 1


def _cmd_resumen_legacy(args, cfg: dict, test_mode: bool = False) -> int:
    """Legacy resumen mensual flow."""
    if test_mode:
        logger.warning(
            "test-mode no tiene efecto en el flujo legacy. "
            "Usa --config <config.json> con formato nuevo para activarlo."
        )
    # Resolver parametros: JSON tiene precedencia sobre args individuales
    fecha_desde = cfg.get("fecha_desde") or args.desde
    fecha_hasta = cfg.get("fecha_hasta") or args.hasta
    genericos_raw = cfg.get("genericos") or parsear_genericos(args.genericos)
    nombre_archivo = cfg.get("output") or args.output
    con_objetivo = cfg.get("con_objetivo", False)

    # Tratar lista vacia como None (trae todos los genericos)
    genericos = genericos_raw if genericos_raw else None

    # Validar campos requeridos
    if not fecha_desde or not fecha_hasta:
        print("Error: fecha_desde y fecha_hasta son requeridos.")
        print("       Usa --desde/--hasta o definelos en --config config.json")
        return 1

    if not validar_fecha(fecha_desde) or not validar_fecha(fecha_hasta):
        print("Error: Las fechas deben tener formato YYYY-MM-DD")
        return 1

    # Crear configuracion del servicio
    config = ResumenMensualConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        genericos=genericos,
        nombre_archivo=nombre_archivo,
        con_objetivo=con_objetivo,
    )

    if genericos:
        print(f"Filtrando por genericos: {genericos}")

    print(f"Generando resumen mensual desde {fecha_desde} hasta {fecha_hasta}...")
    result = ResumenMensualService().generar_reporte(config)

    print("Resumen mensual generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Hojas: {', '.join(result.hojas)}")
    print(f"  - Registros procesados: {result.registros_procesados}")
    print(f"  - Sucursales: {result.sucursales}")
    print(f"  - Genericos: {len(result.genericos_incluidos)}")
    _ejecutar_pipeline(
        ruta_excel=Path(result.ruta_archivo),
        cfg=cfg,
        metadata={"nombre": "Resumen Mensual", "fecha": fecha_hasta},
    )
    return 0


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Generador de reportes CCU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Nuevo formato (recomendado)
  python main.py --config configs/avances_branca.json
  python main.py ventas --config configs/ventas.json
  python main.py --config-dir configs/

  # Legacy (args individuales)
  python main.py ventas --desde 2026-01-01 --hasta 2026-01-31
  python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --genericos "CERVEZAS,AGUAS"

  # Legacy (config flat)
  python main.py ventas --config config.json
""",
    )

    # Global option: --config for running a single config file
    parser.add_argument(
        "--config",
        default=None,
        metavar="FILE",
        help="Archivo JSON de configuracion. Ejecuta un solo informe.",
    )

    # Global option: --config-dir for running all configs
    parser.add_argument(
        "--config-dir",
        default=None,
        metavar="DIR",
        help="Directorio con configs JSON y contactos.json. Ejecuta todos los informes.",
    )

    # Global option: --test-mode to redirect all delivery to Nahuel Aguirre
    parser.add_argument(
        "--test-mode",
        action="store_true",
        default=False,
        help="Redirige TODA la entrega (email + whatsapp) a Nahuel Aguirre. Tambien activable con INFORMES_TEST_MODE=1.",
    )

    subparsers = parser.add_subparsers(
        title="comandos", description="Tipos de reportes disponibles", dest="comando"
    )

    # Subcomando: ventas
    ventas_parser = subparsers.add_parser(
        "ventas",
        help="Reporte de ventas por sucursal, generico y marca",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ventas_parser.add_argument(
        "--config",
        default=None,
        metavar="config.json",
        help=(
            "Archivo JSON con configuracion del reporte. "
            "Soporta formato nuevo (contactos + reportes) y legacy."
        ),
    )
    ventas_parser.add_argument(
        "--desde", default=None, help="Fecha inicio (YYYY-MM-DD)"
    )
    ventas_parser.add_argument("--hasta", default=None, help="Fecha fin (YYYY-MM-DD)")
    ventas_parser.add_argument(
        "--genericos",
        default=None,
        help="Genericos a incluir, separados por coma (ej: CERVEZAS,AGUAS,VINOS)",
    )
    ventas_parser.add_argument(
        "--output", default=None, help="Nombre del archivo de salida (sin extension)"
    )
    ventas_parser.add_argument(
        "--slicers",
        action="store_true",
        default=True,
        help="Agregar slicers/segmentadores (solo Windows con Excel)",
    )
    ventas_parser.add_argument(
        "--no-slicers", action="store_false", dest="slicers", help="No agregar slicers"
    )
    ventas_parser.set_defaults(func=cmd_ventas)

    # Subcomando: resumen-mensual
    resumen_parser = subparsers.add_parser(
        "resumen-mensual",
        help="Resumen mensual por generico (ultimos dias, tendencia, anio anterior)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    resumen_parser.add_argument(
        "--config",
        default=None,
        metavar="config.json",
        help=(
            "Archivo JSON con configuracion del reporte. "
            "Soporta formato nuevo (contactos + reportes) y legacy."
        ),
    )
    resumen_parser.add_argument(
        "--desde", default=None, help="Fecha inicio (YYYY-MM-DD)"
    )
    resumen_parser.add_argument("--hasta", default=None, help="Fecha fin (YYYY-MM-DD)")
    resumen_parser.add_argument(
        "--genericos",
        default=None,
        help="Genericos a incluir, separados por coma (ej: CERVEZAS,AGUAS,VINOS)",
    )
    resumen_parser.add_argument(
        "--output", default=None, help="Nombre del archivo de salida (sin extension)"
    )
    resumen_parser.set_defaults(func=cmd_resumen_mensual)

    # Subcomando: historico-fratelli
    historico_parser = subparsers.add_parser(
        "historico-fratelli",
        help="Historico de ventas FRATELLI B (2024-2026)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    historico_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    historico_parser.set_defaults(func=cmd_historico_fratelli)

    # Subcomando: stock-diario
    mision_parser = subparsers.add_parser(
        "mision-imposible",
        help="Reporte Mision Imposible con cobertura y categorias",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mision_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    mision_parser.set_defaults(func=cmd_mision_imposible)

    stock_parser = subparsers.add_parser(
        "stock-diario",
        help="Reporte de stock diario por articulo y sucursal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    stock_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    stock_parser.set_defaults(func=cmd_stock_diario)

    cartesiano_parser = subparsers.add_parser(
        "cartesiano",
        help="Producto cartesiano de rutas x genericos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cartesiano_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    cartesiano_parser.set_defaults(func=cmd_cartesiano)

    graficos_parser = subparsers.add_parser(
        "graficos-cobertura",
        help="Graficos de cobertura (XLSX + 2 PPTX + PNGs)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    graficos_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    graficos_parser.set_defaults(func=cmd_graficos_cobertura)

    ventas_articulo_parser = subparsers.add_parser(
        "ventas-articulo",
        help="Reporte diario de ventas para un articulo especifico",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ventas_articulo_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    ventas_articulo_parser.set_defaults(func=cmd_ventas_articulo)

    # Parsear argumentos
    args = parser.parse_args()

    test_mode = _resolve_test_mode(args.test_mode)
    if test_mode:
        print("[TEST MODE ACTIVO] delivery redirigido a Nahuel Aguirre", flush=True)

    # --config mode: process a single config file
    if args.config:
        return _run_report_config(Path(args.config), test_mode=test_mode)

    # --config-dir mode: process all configs in directory
    if args.config_dir:
        return _run_config_dir(Path(args.config_dir), test_mode=test_mode)

    if args.comando is None:
        parser.print_help()
        return 1

    return args.func(args, test_mode=test_mode)


if __name__ == "__main__":
    sys.exit(main())
