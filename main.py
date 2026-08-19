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
from datetime import date, datetime
from pathlib import Path

from src.services import VentasService, ResumenMensualService, ResumenMensualConfig
from src.services.ventas import ReporteVentasConfig
from src.services.subdistribuidores import SubdistribuidoresConfig, SubdistribuidoresService

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

# Registry: tipo → handler function name.
# Resolved via globals() at call-time so `patch.object(main, "_run_X_report", fake)`
# in tests still intercepts dispatch.
REPORT_HANDLERS: dict[str, str] = {
    "ventas": "_run_ventas_report",
    "resumen-mensual": "_run_resumen_report",
    "champions-league": "_run_mision_report",
    "historico-fratelli": "_run_historico_fratelli_report",
    "stock-diario": "_run_stock_diario_report",
    "cartesiano": "_run_cartesiano_report",
    "avances": "_run_avances_report",
    "graficos-cobertura": "_run_graficos_cobertura_report",
    "ventas-articulo": "_run_ventas_articulo_report",
    "historico-cliente": "_run_historico_cliente_report",
    "reporte-general-badie": "_run_reporte_general_badie_report",
    "reporte-rebotes": "_run_rebotes_report",
    "reporte-incentivo-cobertura": "_run_incentivo_cobertura_report",
    "reporte-descuentos": "_run_descuentos_report",
    "subdistribuidores": "_run_subdistribuidores_report",
    "stock-suria": "_run_stock_suria_report",
    "stock-suria-control": "_run_stock_suria_control_report",
    "ventas-marca": "_run_ventas_marca_report",
    "ventas-cober-preventista-marca": "_run_ventas_cober_preventista_marca_report",
    "incentivo-salta": "_run_incentivo_salta_report",
    "stock-badie": "_run_stock_badie_report",
    "stock-valorizado": "_run_stock_valorizado_report",
    "cupo-desagregado": "_run_cupo_desagregado_report",
    "comparativo-salta": "_run_comparativo_salta_report",
    "cobertura": "_run_cobertura_report",
    "cobertura-cupos": "_run_cobertura_cupos_report",
    "cobertura-aguas": "_run_cobertura_aguas_report",
    "cobertura-levite": "_run_cobertura_levite_report",
    "quesos": "_run_quesos_report",
    "volumen-cobertura": "_run_volumen_cobertura_report",
}


def _run_report_config(
    config_path: Path,
    contactos_path: Path | None = None,
    test_mode: bool = False,
    no_delivery: bool = False,
) -> int:
    """Execute a single report config file (new format)."""
    from pydantic import ValidationError

    from src.config.resolver import load_contacts, load_report_config

    try:
        report_config = load_report_config(config_path)
    except (FileNotFoundError, ValidationError) as exc:
        print(f"Error: config invalida en {config_path}:\n{exc}")
        return 1

    # Ventana relativa: la resolvemos ANTES de ejecutar, con el mismo codigo que
    # usa el daily. Sin esto, una corrida manual toma las fechas guardadas en el
    # JSON, que envejecen y sacan el informe con el mes equivocado.
    if report_config.filtros.fecha_modo:
        from datetime import date as _date

        from src.core.periodos import meses_abarcados, resolver_ventana

        # El ancho se mide sobre las fechas ESCRITAS, antes de pisarlas.
        ancho = meses_abarcados(
            report_config.filtros.fecha_desde, report_config.filtros.fecha_hasta
        )
        try:
            desde, hasta = resolver_ventana(
                report_config.filtros.fecha_modo, _date.today(), ancho
            )
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
        report_config.filtros.fecha_desde = desde
        report_config.filtros.fecha_hasta = hasta
        print(f"Ventana ({report_config.filtros.fecha_modo}): {desde} a {hasta}")

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

    return _run_reportes(report_config, contactos, test_mode=test_mode, no_delivery=no_delivery)


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


# Uppercase Spanish month names, 1-indexed (index 0 unused) — used to resolve
# {MES} period tokens in report names.
_MESES_ES = [
    "", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
]


def _resolver_nombre_periodo(nombre: str, fecha_desde: str) -> str:
    """Resolve ``{MES}``/``{AÑO}`` tokens in a report name from the period start.

    A report's ``nombre`` may carry a period placeholder
    (e.g. ``"AVANCE BRANCA - {MES} {AÑO}"``) so the output filename always
    tracks the resolved period. Because the output folder is also derived from
    ``fecha_desde``, name and folder can never desync across months. ``{ANIO}``
    is accepted as an ASCII-safe alias of ``{AÑO}``. Names without tokens (or an
    unparseable date) are returned unchanged.
    """
    if not nombre or "{" not in nombre:
        return nombre
    try:
        d = date.fromisoformat(fecha_desde)
    except (ValueError, TypeError):
        return nombre
    reemplazos = {
        "{MES}": _MESES_ES[d.month],
        "{AÑO}": str(d.year),
        "{ANIO}": str(d.year),
    }
    for token, valor in reemplazos.items():
        nombre = nombre.replace(token, valor)
    return nombre


def _run_reportes(report_config, contactos, test_mode: bool = False, no_delivery: bool = False) -> int:
    """Iterate over reportes[], generate each file, run delivery pipeline."""
    from src.config.resolver import merge_filters, resolve_delivery

    for report in report_config.reportes:
        merged = merge_filters(report_config.filtros, report.filtros, no_delivery=no_delivery)
        # Expose the run context so per-report handlers (e.g. the holidays
        # notification) can honor the test-mode redirect and no-delivery switch.
        merged["test_mode"] = test_mode
        merged["no_delivery"] = no_delivery

        # Resolve {MES}/{AÑO} period tokens so the output filename tracks the
        # run's period (covers both the daily and manual runs — both dispatch
        # through here). Names without tokens pass through untouched.
        report.nombre = _resolver_nombre_periodo(report.nombre, merged.get("fecha_desde", ""))
        # Same for the email subject: SendEmailStep uses `config.email.asunto`
        # verbatim, so an unresolved "{MES} {AÑO}" ships literally in the
        # subject line (affects avance-guemes, cupo-desagregado, stock-badie).
        if report.asunto_email:
            report.asunto_email = _resolver_nombre_periodo(
                report.asunto_email, merged.get("fecha_desde", "")
            )

        print(f"\nGenerando: {report.nombre}")

        handler_name = REPORT_HANDLERS.get(report_config.tipo)
        if handler_name is None:
            print(f"Error: tipo de reporte desconocido: {report_config.tipo}")
            return 1
        artifacts = globals()[handler_name](report, merged)

        if not artifacts:
            continue  # error already printed

        # Run delivery pipeline for EACH generated file
        delivery_config = resolve_delivery(
            report,
            contactos,
            enviar_email=merged["enviar_email"],
            enviar_whatsapp=merged["enviar_whatsapp"],
            test_mode=test_mode,
            whatsapp_enviar_como=merged.get("whatsapp_enviar_como", "imagen"),
            whatsapp_caption_imagenes=merged.get("whatsapp_caption_imagenes", True),
            email_adjuntos=merged.get("email_adjuntos", ["excel"]),
        )
        if delivery_config:
            for ruta_archivo, metadata in artifacts:
                meta = dict(metadata or {})
                meta["_tipo"] = report_config.tipo
                _ejecutar_pipeline(
                    ruta_excel=ruta_archivo,
                    delivery_config=delivery_config,
                    metadata=meta,
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
        con_montos=merged.get("con_montos", True),
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
        detalle_movimientos_path=merged.get("detalle_movimientos_path"),
        detalle_movimientos_ma_path=merged.get("detalle_movimientos_ma_path"),
        detalle_movimientos_mmaa_path=merged.get("detalle_movimientos_mmaa_path"),
        categorias_deposito_path=merged.get("categorias_deposito_path"),
        genericos_sin_prvta=merged.get("genericos_sin_prvta"),
        marca_splits=merged.get("marca_splits"),
        cupos_manuales=merged.get("cupos_manuales"),
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
    from src.services.champions_league import (
        ChampionsLeagueConfig,
        ChampionsLeagueService,
    )

    config = ChampionsLeagueConfig(
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        genericos=merged["genericos"],
        categorias=merged.get("categorias"),
        nombre_archivo=report.nombre,
    )
    result = ChampionsLeagueService().generar_reporte(config)
    print("Champions League generado exitosamente:")
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


def _run_stock_badie_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate stock-badie report (RF-01..RF-11). Returns list of (path, metadata).

    Mirrors the per-report handler contract used by sibling services:
    build the StockBadieConfig from the merged filters, dispatch through
    StockBadieService.generar_reporte, and return a list of (path, metadata)
    tuples so _run_reportes can hand each artifact to the delivery pipeline.
    """
    from src.services.stock_badie.config import StockBadieConfig
    from src.services.stock_badie.service import StockBadieService

    # Resolve {MES}/{AÑO} placeholders so the output filename tracks the
    # output folder's month (e.g. "Stock Badie - JULIO 2026.xlsx" lands in
    # data/output/stock-badie/2026-07/).
    nombre_periodo = _resolver_nombre_periodo(report.nombre, merged["fecha_desde"])

    config = StockBadieConfig(
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        dias_stock=merged.get("dias_stock", 15),
        genericos=merged.get("genericos"),
        genericos_excluidos=merged.get("genericos_excluidos"),
        nombre_archivo=nombre_periodo or None,
    )

    result = StockBadieService().generar_reporte(config)

    print("Stock Badie generado exitosamente:")
    print(f"  - Archivo: {result.archivo_generado.name}")
    print(f"  - Fecha stock: {result.fecha_stock.isoformat()}")
    print(f"  - Articulos: {result.n_articulos}")
    print(f"  - DiasVenta: {result.dias_venta}")

    return [
        (
            Path(result.archivo_generado),
            {"nombre": nombre_periodo, "fecha": result.fecha_stock.isoformat()},
        )
    ]


def _run_stock_valorizado_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate stock-valorizado report. Returns list of (path, metadata) tuples.

    Snapshot date comes from `fecha_stock` when present, otherwise the latest
    date in gold.fact_stock — deliberately NOT from fecha_desde/fecha_hasta,
    which the daily patches to the running month and do not describe a snapshot.
    """
    from src.services.stock_valorizado import (
        StockValorizadoConfig,
        StockValorizadoService,
    )

    lista_precios_path = merged.get("lista_precios_path")
    if not lista_precios_path:
        print(
            "Error: stock-valorizado requiere 'lista_precios_path' en los filtros "
            "(xlsx exportado del ERP con las columnas 'Articulo' y 'Precio Base')."
        )
        raise ValueError("stock-valorizado: falta lista_precios_path")

    kwargs = {}
    if merged.get("lista_precios_max_dias") is not None:
        kwargs["lista_precios_max_dias"] = merged["lista_precios_max_dias"]

    config = StockValorizadoConfig(
        lista_precios_path=lista_precios_path,
        fecha_stock=merged.get("fecha_stock"),
        genericos=merged.get("genericos"),
        genericos_excluidos=merged.get("genericos_excluidos"),
        nombre_archivo=report.nombre,
        **kwargs,
    )

    result = StockValorizadoService().generar_reporte(config)

    print("Stock Valorizado generado exitosamente:")
    print(f"  - Archivo: {result.archivo_generado.name}")
    print(f"  - Fecha stock: {result.fecha_stock.isoformat()}")
    print(f"  - Articulos: {result.n_articulos} en {result.n_sucursales} sucursales")
    print(f"  - Total bultos: {result.total_bultos:,.0f}")
    print(f"  - Total valorizado (base):  $ {result.total_valorizado:,.2f}")
    print(f"  - Total valorizado (final): $ {result.total_valorizado_final:,.2f}")
    print(
        f"  - Lista de precios: {result.lista_precios_path.name} "
        f"(actualizada {result.lista_precios_mtime.strftime('%d-%m-%Y %H:%M')}, "
        f"hace {result.lista_precios_dias} dias)"
    )

    # The price list is maintained by hand; nothing upstream notices when that
    # stops happening. Make the CLI impossible to skim past when it goes stale.
    if result.lista_precios_vencida:
        print("")
        print("=" * 72)
        print("  ATENCION: LA LISTA DE PRECIOS ESTA DESACTUALIZADA")
        print(f"  {result.lista_precios_path} tiene {result.lista_precios_dias} dias.")
        print("  Los precios se cargan A MANO: exportalos del ERP, reemplaza el")
        print("  archivo y volve a generar el informe antes de usar estos importes.")
        print("=" * 72)
        print("")

    return [
        (
            Path(result.archivo_generado),
            {"nombre": report.nombre, "fecha": result.fecha_stock.isoformat()},
        )
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
        icon = {"success": "\u2713", "skipped": "-", "error": "\u2717"}.get(step.status, "?")
        print(f"  [{icon}] {step.step_name}: {step.message}")

    if not result.success:
        print("  Advertencia: algunos pasos fallaron (ver logs).")

    from src.core.delivery_log import registrar_envio
    registrar_envio(
        tipo=metadata.get("_tipo", "desconocido") if metadata else "desconocido",
        nombre=metadata.get("nombre", "sin nombre") if metadata else "sin nombre",
        archivos=[str(ruta_excel)],
        status="enviado" if result.success else "error",
    )


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


def cmd_champions_league(args, test_mode: bool = False) -> int:
    """Ejecuta el comando de champions league."""
    if not args.config:
        print("Error: champions-league requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print(
            "Error: champions-league solo soporta el nuevo formato de configuracion JSON."
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


def _run_ventas_marca_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate ventas-marca report (quantity sold by marca for one generico)."""
    from src.services.ventas_marca import VentasMarcaConfig, VentasMarcaService

    genericos = merged.get("genericos") or []
    if not genericos:
        print("Error: ventas-marca requiere un generico en 'genericos' (filtros)")
        return []

    config = VentasMarcaConfig(
        generico=genericos[0],
        fecha=merged["fecha_desde"],
        fecha_hasta=merged.get("fecha_hasta"),
        id_sucursal=merged.get("id_sucursal") or 1,
        nombre_archivo=report.nombre,
        incluir_mes_anterior=bool(merged.get("incluir_mes_anterior")),
    )

    result = VentasMarcaService().generar_reporte(config)
    print(f"Venta por Marca '{report.nombre}' generada exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(
        f"  - Marcas: {result.marcas} | Total bultos: {result.total_bultos} "
        f"| Cobertura: {result.cobertura_total}"
    )
    if result.total_bultos_prev is not None:
        print(
            f"  - {result.etiqueta_prev} (mes anterior): "
            f"Bultos: {result.total_bultos_prev} | Cobertura: {result.cobertura_prev}"
        )
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")},
        )
    ]


def _run_quesos_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate quesos report (volumen y cobertura por mes de LA HUERTA)."""
    from src.services.quesos import QuesosConfig, QuesosService

    config = QuesosConfig(
        anios=merged.get("anios_mensual") or [2025, 2026],
        factores_path=merged.get("lista_precios_path") or "factor_conversion_quesos.xlsx",
        nombre_archivo=report.nombre,
    )
    result = QuesosService().generar_reporte(config)
    print(f"Quesos '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Anios: {result.anios} | Bultos: {result.bultos:,.0f} | Kg: {result.kg:,.2f}")
    if result.sin_factor:
        print(f"  - OJO articulos sin factor (bultos si, kilos no): {result.sin_factor}")
    return [(Path(result.ruta_archivo),
             {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")})]


def _run_volumen_cobertura_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate volumen-cobertura report (volumen y cobertura de un generico).

    El generico viene en `genericos` y tiene que ser UNO solo: el informe abre
    por marca y cruza sucursal x marca, y mezclar dos genericos en esa matriz
    da columnas que no se pueden comparar entre si.
    """
    from src.services.volumen_cobertura import (
        VolumenCoberturaConfig,
        VolumenCoberturaService,
    )

    genericos = merged.get("genericos") or []
    if len(genericos) != 1:
        print(
            f"Error: volumen-cobertura necesita exactamente UN generico en "
            f"'genericos'; llegaron {len(genericos)}: {genericos}"
        )
        return []

    config = VolumenCoberturaConfig(
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        generico=genericos[0],
        nombre_archivo=report.nombre,
        sucursales_excluidas=merged.get("sucursales_excluidas") or [],
        supervisores_sucursales=merged.get("supervisores_sucursales") or {},
        incluir_directa=bool(merged.get("incluir_directa")),
        split_por_sucursal=bool(merged.get("split_por_sucursal")),
    )

    servicio = VolumenCoberturaService()
    result = servicio.generar_reporte(config)
    print(f"Volumen y Cobertura '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Generico: {config.generico} | Meses: {', '.join(result.meses)}")
    print(f"  - Sucursales con movimiento: {result.sucursales}")
    print(
        f"  - Acumulado: {result.bultos:,.2f} bultos | {result.hectolitros:,.2f} HL "
        f"| {result.cobertura:,} clientes"
    )
    if result.articulos_sin_factor:
        print(
            f"  - ATENCION: {len(result.articulos_sin_factor)} articulos sin factor "
            f"de hectolitros; la columna HL sale corta"
        )

    artefactos = [(result.ruta_archivo, {"_tipo": "volumen-cobertura"})]

    if config.split_por_sucursal:
        # El split va DESPUES del consolidado y con el mismo servicio: comparte
        # la conexion y el criterio, y si el consolidado fallo no tiene sentido
        # generar doce archivos con el mismo problema.
        partes = servicio.generar_split(config)
        print(f"  - Split por sucursal: {len(partes)} archivos")
        for parte in partes:
            print(
                f"      {parte.ruta_archivo.name}  "
                f"({parte.bultos:,.2f} bultos | {parte.cobertura:,} clientes)"
            )
            artefactos.append((parte.ruta_archivo, {"_tipo": "volumen-cobertura"}))

    return artefactos


def _run_cobertura_aguas_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate cobertura-aguas report (cobertura de aguas por sucursal y marca).

    La cantidad de meses NO es un campo aparte: se DERIVA del rango
    fecha_desde..fecha_hasta que ya trae el config. Un campo suelto habria que
    mantenerlo sincronizado con las fechas a mano, y se desincroniza solo.
    """
    from src.core.periodos import meses_abarcados
    from src.services.cobertura_aguas import (
        CoberturaAguasConfig,
        CoberturaAguasService,
    )

    fecha_hasta = merged.get("fecha_hasta") or merged["fecha_desde"]
    config = CoberturaAguasConfig(
        fecha=fecha_hasta,
        meses=meses_abarcados(merged["fecha_desde"], fecha_hasta),
        nombre_archivo=report.nombre,
    )

    result = CoberturaAguasService().generar_reporte(config)
    print(f"Cobertura Aguas '{report.nombre}' generada exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Meses: {', '.join(result.meses)} | Sucursales: {result.sucursales}")
    print(
        f"  - Cobertura acumulada: {result.cobertura_acumulada:,} "
        f"de un padron de {result.padron:,} "
        f"({result.cobertura_acumulada / result.padron:.1%})"
    )
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")},
        )
    ]


def _run_cobertura_levite_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate cobertura-levite report (cobertura de Levite abierta por calibre)."""
    from src.services.cobertura_levite import (
        CoberturaLeviteConfig,
        CoberturaLeviteService,
    )

    fecha_hasta = merged.get("fecha_hasta") or merged.get("fecha_desde")
    fecha_desde = merged.get("fecha_desde") or (fecha_hasta[:7] + "-01")
    
    config = CoberturaLeviteConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        umbral=float(merged.get("umbral", 0.0)),
        nombre_archivo=report.nombre,
        sucursales=merged.get("sucursales_ids"),
    )

    result = CoberturaLeviteService().generar_reporte(config)
    print(f"Cobertura Levite por Calibre '{report.nombre}' generada exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Clientes compradores: {result.clientes_compradores:,} | Volumen total: {result.volumen_total:,.2f} bultos")
    print(
        f"  - Cobertura sobre padron: {result.clientes_compradores:,} "
        f"de {result.padron_total:,} "
        f"({result.clientes_compradores / result.padron_total:.1%})"
    )
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": fecha_hasta},
        )
    ]


def _run_ventas_cober_preventista_marca_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate ventas-cober-preventista-marca report (ventas + cobertura por preventista)."""
    from src.services.ventas_cober_preventista_marca import (
        VentasCoberPreventistaMarcaConfig,
        VentasCoberPreventistaMarcaService,
    )

    marcas = merged.get("marcas") or []
    if not marcas:
        print("Error: ventas-cober-preventista-marca requiere una marca en 'marcas' (filtros)")
        return []

    config = VentasCoberPreventistaMarcaConfig(
        marca=marcas[0],
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged.get("fecha_hasta") or merged["fecha_desde"],
        id_sucursal=merged.get("id_sucursal") or 1,
        nombre_archivo=report.nombre,
        incluir_mes_anterior=bool(merged.get("incluir_mes_anterior")),
        objetivo_cobertura=merged.get("objetivo_cobertura"),
        clausula_gatillo=merged.get("clausula_gatillo"),
    )

    result = VentasCoberPreventistaMarcaService().generar_reporte(config)
    print(f"Ventas+Cobertura por Preventista '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Preventistas: {result.preventistas} | Bultos: {result.total_bultos} | Cobertura: {result.cobertura_total}")
    if result.total_bultos_prev is not None:
        print(
            f"  - {result.etiqueta_prev} (mes anterior): "
            f"Bultos: {result.total_bultos_prev} | Cobertura: {result.cobertura_prev}"
        )
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")},
        )
    ]


def _run_incentivo_salta_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate the incentivo preventa SALTA report.

    Los bloques y los cupos salen del xlsx de objetivos, no del config: ahi vive
    el acuerdo con el negocio y se edita sin tocar codigo.
    """
    from src.services.incentivo_salta import IncentivoSaltaConfig, IncentivoSaltaService

    objetivos = merged.get("objetivos_path")
    if not objetivos:
        print("Error: incentivo-salta requiere 'objetivos_path' en filtros")
        return []

    config = IncentivoSaltaConfig(
        fecha_hasta=merged.get("fecha_hasta") or merged["fecha_desde"],
        objetivos_path=objetivos,
        id_sucursal=merged.get("id_sucursal") or 1,
        excluir_vendedores=merged.get("excluir_vendedores") or [],
        nombre_archivo=report.nombre,
    )

    result = IncentivoSaltaService().generar_reporte(config)
    print(f"Incentivo SALTA '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Bloques: {result.bloques} ({len(result.bloques_activos)} con datos) "
          f"| Preventistas: {result.preventistas}")
    return [(Path(result.ruta_archivo), {"nombre": report.nombre,
                                         "fecha": result.fecha_hasta})]


def _run_historico_cliente_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate historico-cliente report. Returns list of (path, metadata) tuples."""
    from src.services.historico_cliente import (
        HistoricoClienteConfig,
        HistoricoClienteService,
    )

    # Extract per-report filters if present, fall back to merged/globals
    clientes = merged.get("clientes")
    articulos = merged.get("articulos")
    marcas = merged.get("marcas")

    if not clientes:
        print("Error: historico-cliente requires 'clientes' in filtros (report or global)")
        return []

    config = HistoricoClienteConfig(
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        clientes=clientes,
        articulos=articulos,
        marcas=marcas,
        agrupar_por_generico=merged.get("agrupar_por_generico", False),
        marcas_completas=merged.get("marcas_completas", False),
        genericos_universo=merged.get("genericos_universo"),
        solo_con_cargo=merged.get("solo_con_cargo", False),
        nombre_archivo=report.nombre,
    )

    service = HistoricoClienteService()
    try:
        result = service.generar_reporte(config)
    except ValueError as e:
        print(f"Error: {e}")
        return []

    print(f"Historico Cliente '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Hojas generadas: {len(result.sheets_generated)}")
    for sh in result.sheets_generated:
        print(f"    - {sh}")
    print(f"  - Registros procesados: {result.registros_procesados}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")},
        )
    ]


def _run_reporte_general_badie_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate reporte-general-badie report. Returns list of (path, metadata) tuples."""
    from src.services.reporte_general_badie import (
        ReporteGeneralBadieConfig,
        ReporteGeneralBadieService,
    )

    fecha_desde = merged.get("fecha_desde")
    fecha_hasta = merged.get("fecha_hasta")
    if not fecha_desde or not fecha_hasta:
        print("Error: reporte-general-badie requires fecha_desde y fecha_hasta")
        return []

    print(f"Generando: {report.nombre}")
    config = ReporteGeneralBadieConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        nombre_archivo=report.nombre,
    )
    service = ReporteGeneralBadieService()
    result = service.generar_reporte(config)
    print(f"{report.nombre} generado exitosamente:")
    print(f"  - Archivo normal: {result.ruta_archivo}")
    print(f"      Ventas: {result.registros_ventas} | Cobertura: {result.registros_cobertura} | Trimestres: {result.trimestres_en_dropdown}")
    print(f"  - Archivo extendido: {result.ruta_archivo_extendido}")
    print(f"      Ventas: {result.registros_ventas_extendido} | Cobertura: {result.registros_cobertura_extendido} | Trimestres: {result.trimestres_en_dropdown_extendido}")
    print(f"  - Sucursales: {result.sucursales}")
    return [(result.ruta_archivo, {}), (result.ruta_archivo_extendido, {})]


def _resolve_feriados_target(nombre_o_telefono: str) -> str | None:
    """Resolve a holidays-notification target to a WhatsApp destination.

    A raw phone number (only digits, optional leading '+', spaces or dashes) is
    used directly. Otherwise the value is treated as a contact name and looked
    up in the contactos catalog to get its ``telefono``.

    Returns None when the contact cannot be resolved.
    """
    candidato = nombre_o_telefono.strip()
    solo_digitos = candidato.lstrip("+").replace(" ", "").replace("-", "")
    if solo_digitos.isdigit():
        return candidato

    try:
        from src.config.resolver import load_contacts

        contactos = load_contacts(Path("configs/contactos.json"))
        contacto = contactos.get(nombre_o_telefono)
        if contacto and contacto.telefono:
            return contacto.telefono
    except Exception as exc:  # noqa: BLE001 — resolution is best-effort
        logger.warning("No se pudo resolver contacto '%s': %s", nombre_o_telefono, exc)
    return None


def _notificar_feriados_avances(report, merged: dict, result) -> None:
    """Send the applied-holidays WhatsApp notification for an avances run.

    Guarded end to end: a missing target, an unresolved contact, or a transport
    failure only logs a warning — it MUST NOT break report generation.

    Honors the run context: a --no-delivery run sends nothing, and a --test-mode
    run redirects the notification to the test contact (never a real supervisor).
    """
    # A --no-delivery run must not send anything.
    if merged.get("no_delivery"):
        return

    destino = merged.get("notificar_feriados_a")
    if not destino:
        return

    # In test mode, redirect to the safe test contact so a real supervisor is
    # never notified. This mirrors resolve_delivery's test-mode chokepoint.
    if merged.get("test_mode"):
        from src.config.resolver import TEST_CONTACT_NAME

        destino = TEST_CONTACT_NAME

    try:
        from config.settings import WHATSAPP_SERVICE_URL

        from src.core.feriados import formatear_notificacion_feriados
        from src.core.whatsapp_client import WhatsAppClient

        target = _resolve_feriados_target(destino)
        if not target:
            logger.warning(
                "notificar_feriados_a='%s' no se pudo resolver a un destino", destino
            )
            return

        feriados = getattr(result, "feriados_aplicados", None) or []
        texto = formatear_notificacion_feriados(feriados, report.nombre)
        WhatsAppClient(WHATSAPP_SERVICE_URL).send_text(target=target, text=texto)
        logger.info("Notificacion de feriados enviada a %s", target)
    except Exception as exc:  # noqa: BLE001 — notification must never break generation
        logger.warning("No se pudo enviar la notificacion de feriados: %s", exc)


def _run_avances_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate avances report. Returns list of (path, metadata) tuples."""
    import logging

    from src.services.avances import AvancesConfig, AvancesService

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s"
    )

    archivo_plantilla = merged.get("archivo_plantilla")
    if not report.nombre:
        print("Error: avances report requires 'nombre' (used as output filename)")
        return []

    config = AvancesConfig(
        archivo_plantilla=archivo_plantilla or None,
        fecha_desde=merged["fecha_desde"],
        fecha_hasta=merged["fecha_hasta"],
        tipo_plantilla=merged.get("tipo_plantilla", "branca"),
        id_sucursal=merged.get("id_sucursal") or 1,
        id_fuerza_ventas=merged.get("id_fuerza_ventas") or 1,
        nombre_archivo=report.nombre,
        skip_cupos=merged.get("skip_cupos", False),
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

    # Notify the applied month holidays (own operational channel — independent
    # of enviar_email / enviar_whatsapp / no_delivery). Never breaks generation.
    _notificar_feriados_avances(report, merged, result)

    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")},
        )
    ]


def _run_rebotes_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate reporte-rebotes report. Returns list of (path, metadata) tuples."""
    from src.services.rebotes import RebotesConfig, RebotesService

    fecha_desde = merged.get("fecha_desde")
    fecha_hasta = merged.get("fecha_hasta")
    if not fecha_desde or not fecha_hasta:
        print("Error: reporte-rebotes requires fecha_desde y fecha_hasta")
        return []

    print(f"Generando: {report.nombre}")
    config = RebotesConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        genericos=merged.get("genericos"),
        nombre_archivo=report.nombre,
    )
    service = RebotesService()
    result = service.generar_reporte(config)
    print(f"Rebotes '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Vendedores: {result.vendedores}")
    print(f"  - Supervisores: {result.supervisores}")
    print(f"  - Registros procesados: {result.registros_procesados}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": fecha_hasta},
        )
    ]


def _run_incentivo_cobertura_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate reporte-incentivo-cobertura. Returns list of (path, metadata) tuples.

    El incentivo ON PREMISE es puntual y específico (targets hardcoded en
    constants.py). El alcance de difusión también es fijo: solo el equipo de
    VCHAPUR, excluyendo a los preventistas que no participan. Por eso el
    supervisor y las exclusiones van hardcoded acá y no como filtros del config.
    """
    from src.services.incentivo_cobertura import (
        IncentivoCoberturaConfig,
        IncentivoCoberturaService,
    )

    fecha_desde = merged.get("fecha_desde")
    fecha_hasta = merged.get("fecha_hasta")
    if not fecha_desde or not fecha_hasta:
        print("Error: reporte-incentivo-cobertura requires fecha_desde y fecha_hasta")
        return []

    print(f"Generando: {report.nombre}")
    config = IncentivoCoberturaConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        nombre_archivo=report.nombre,
        solo_supervisor="VCHAPUR",
        vendedores_excluidos=["MARCELA ASTORGA", "JUAN JOSE BARRIOS", "CRUZ IGNACIO"],
    )
    service = IncentivoCoberturaService()
    result = service.generar_reporte(config)
    print(f"Incentivo cobertura '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Vendedores: {result.vendedores}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": fecha_hasta},
        )
    ]


def _run_descuentos_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate reporte-descuentos (Descuentos CCU). Returns [(path, metadata)]."""
    from src.services.descuentos import DescuentosConfig, DescuentosService

    fecha_desde = merged.get("fecha_desde")
    fecha_hasta = merged.get("fecha_hasta")
    if not fecha_desde or not fecha_hasta:
        print("Error: reporte-descuentos requires fecha_desde y fecha_hasta")
        return []

    print(f"Generando: {report.nombre}")
    config = DescuentosConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        nombre_archivo=report.nombre,
        con_lista_precio=merged.get("con_lista_precio", True),
    )
    result = DescuentosService().generar_reporte(config)
    print(f"Descuentos '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Registros: {result.registros_procesados}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": fecha_hasta},
        )
    ]


def cmd_subdistribuidores(args, test_mode: bool = False) -> int:
    """Ejecuta el comando de subdistribuidores."""
    if not args.config:
        print("Error: subdistribuidores requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print(
            "Error: subdistribuidores solo soporta el nuevo formato de configuracion JSON."
        )
        return 1


def _run_subdistribuidores_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate subdistribuidores report. Returns list of (path, metadata) tuples."""
    fecha_desde = merged.get("fecha_desde")
    fecha_hasta = merged.get("fecha_hasta")
    if not fecha_desde or not fecha_hasta:
        print("Error: subdistribuidores requires fecha_desde y fecha_hasta")
        return []

    print(f"Generando: {report.nombre}")
    config = SubdistribuidoresConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        nombre_archivo=report.nombre,
    )
    service = SubdistribuidoresService()
    result = service.generar_reporte(config)
    print(f"Subdistribuidores '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Clientes unicos: {result.clientes}")
    print(f"  - Filas en Bultos: {result.filas_bultos}")
    print(f"  - Hojas: {', '.join(result.hojas)}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": fecha_hasta},
        )
    ]


def cmd_stock_suria(args, test_mode: bool = False) -> int:
    """Ejecuta el comando de stock SURIA."""
    if not args.config:
        print("Error: stock-suria requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print("Error: stock-suria solo soporta el nuevo formato de configuracion JSON.")
        return 1


def _run_stock_suria_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate stock-suria report. Returns list of (path, metadata) tuples."""
    from src.services.stock_suria import StockSuriaConfig, StockSuriaService

    # stock-suria uses fecha_hasta as the target date for output dir naming
    fecha = merged.get("fecha_hasta") or merged.get("fecha_desde")
    if not fecha:
        print("Error: stock-suria requires fecha_desde or fecha_hasta")
        return []

    print(f"Generando: {report.nombre}")
    config = StockSuriaConfig(
        fecha=fecha,
        nombre_archivo=report.nombre,
        todos_los_articulos=merged.get("todos_los_articulos", False),
    )
    service = StockSuriaService()
    result = service.generar_reporte(config)
    print(f"Stock SURIA '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Fecha stock: {result.fecha_stock}")
    print(f"  - Articulos con stock: {result.articulos_con_stock}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": fecha},
        )
    ]


def _run_stock_suria_control_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Refresh stock columns of a user-maintained 'Control de stock' SURIA base.

    Reads `archivo_plantilla` from merged (the user-managed base xlsx), runs
    StockSuriaControlService which writes ONLY stock columns K..O in-place
    matched by 'Cod SURIA', and returns the OUTPUT (copied) file as the
    artifact. The base file at data/input is never touched.
    """
    import logging
    from src.services.stock_suria_control import (
        StockSuriaControlConfig,
        StockSuriaControlService,
    )

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s"
    )

    archivo_plantilla = merged.get("archivo_plantilla")
    if not archivo_plantilla:
        print("Error: stock-suria-control requires filtros.archivo_plantilla")
        return []

    fecha = merged.get("fecha_hasta") or merged.get("fecha_desde")
    config = StockSuriaControlConfig(
        archivo_plantilla=archivo_plantilla,
        nombre_archivo=report.nombre,
        fecha=fecha,
        in_place=False,
    )
    service = StockSuriaControlService()
    try:
        result = service.generar_reporte(config)
    except FileNotFoundError as e:
        print(f"Error: Archivo base no encontrado: {e}")
        return []

    print(f"Stock SURIA Control '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Fecha stock: {result.fecha_stock}")
    print(f"  - Filas actualizadas: {result.filas_actualizadas}")
    print(f"  - Articulos sin stock: {len(result.articulos_sin_stock)}")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": fecha or ""},
        )
    ]


def cmd_stock_badie(args, test_mode: bool = False) -> int:
    """Ejecuta el comando stock-badie."""
    if not args.config:
        print("Error: stock-badie requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print("Error: stock-badie solo soporta el nuevo formato de configuracion JSON.")
        return 1


def cmd_stock_valorizado(args, test_mode: bool = False) -> int:
    """Ejecuta el comando stock-valorizado."""
    if not args.config:
        print("Error: stock-valorizado requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    print("Error: stock-valorizado solo soporta el nuevo formato de configuracion JSON.")
    return 1


def cmd_comparativo_salta(args, test_mode: bool = False) -> int:
    """Ejecuta el comando comparativo-salta."""
    if not args.config:
        print("Error: comparativo-salta requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    print("Error: comparativo-salta solo soporta el nuevo formato de configuracion JSON.")
    return 1


def cmd_cobertura(args, test_mode: bool = False) -> int:
    """Ejecuta el comando cobertura."""
    if not args.config:
        print("Error: cobertura requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    print("Error: cobertura solo soporta el nuevo formato de configuracion JSON.")
    return 1


def _run_cobertura_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate cobertura report (historico de cobertura por periodo)."""
    from src.services.cobertura import CoberturaService, ReporteCoberturaConfig

    kwargs = {}
    # Se omiten SOLO cuando vienen en None, para que el default del servicio
    # gane; pasarlos explicitamente en None romperia la derivacion de periodos.
    # El chequeo es contra None y no por verdad: un `"meses_atras": []` escrito
    # en el config tiene que llegar al servicio y explotar ahi, no caer al
    # default en silencio.
    if merged.get("apertura_cobertura") is not None:
        kwargs["tipo"] = merged["apertura_cobertura"]
    if merged.get("meses_atras") is not None:
        kwargs["meses_atras"] = merged["meses_atras"]

    try:
        config = ReporteCoberturaConfig(
            fecha_desde=merged["fecha_desde"],
            sucursales=merged.get("sucursales"),
            nombre_archivo=report.nombre,
            con_slicers=bool(merged.get("con_slicers")),
            **kwargs,
        )
    except ValueError as exc:
        print(f"Error: config invalida para cobertura: {exc}")
        return []

    result = CoberturaService().generar_reporte(config)
    print(f"Cobertura '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Apertura: {result.tipo} | Periodos: {', '.join(result.periodos)}")
    print(f"  - Registros: {result.registros_raw} crudos -> {result.registros_procesados} filas")
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": merged.get("fecha_hasta", "")},
        )
    ]


def cmd_cobertura_cupos(args, test_mode: bool = False) -> int:
    """Ejecuta el comando cobertura-cupos."""
    if not args.config:
        print("Error: cobertura-cupos requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    print("Error: cobertura-cupos solo soporta el nuevo formato de configuracion JSON.")
    return 1


def _run_cobertura_cupos_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate cobertura-cupos report (cobertura por generico y marca por zona)."""
    from src.services.cobertura_cupos import CoberturaCuposConfig, CoberturaCuposService

    config = CoberturaCuposConfig(
        fecha_desde=merged["fecha_desde"],
        # None -> los 5 genericos CCU (default del servicio).
        genericos=merged.get("genericos"),
        # None -> las tres zonas por defecto (CASA CENTRAL / VALLE SALTA /
        # GUEMES). Con nombres, una hoja entera por sucursal.
        sucursales=merged.get("sucursales"),
        nombre_archivo=report.nombre,
    )

    result = CoberturaCuposService().generar_reporte(config)
    print(f"Cobertura y Cupos '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Periodos: {' vs '.join(result.periodos)}")
    print(f"  - Zonas: {', '.join(result.zonas)} | Filas de marca: {result.filas_marca}")
    # La metadata `fecha` alimenta el caption de WhatsApp. Va el periodo del
    # DATO (el mes anterior cerrado), no el de la corrida: con `fecha_hasta` el
    # caption diria "Agosto 2026" sobre un informe de julio.
    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": result.periodo_principal},
        )
    ]


def cmd_inteligencia_comercial(args, test_mode: bool = False) -> int:
    """Ejecuta el comando inteligencia-comercial.

    No pasa por el pipeline de delivery: es un informe pesado (~6 minutos, 35
    hojas) que se corre a mano cuando se lo necesita, no todos los dias.
    """
    from src.services.inteligencia_comercial import (
        InteligenciaComercialConfig,
        InteligenciaComercialService,
    )

    modulos = None
    if args.modulos:
        modulos = [m.strip() for m in args.modulos.split(",") if m.strip()]

    try:
        config = InteligenciaComercialConfig(
            fecha_hasta=args.hasta,
            meses_ventana=args.meses,
            meses_historia=args.historia,
            nombre_archivo=args.nombre,
            modulos=modulos,
        )
    except ValueError as exc:
        print(f"Error de configuracion: {exc}")
        return 1

    print(f"Inteligencia Comercial — corte {config.fecha_hasta}, "
          f"ventana {config.meses_ventana}m, historia {config.meses_historia}m")
    print("Esto tarda varios minutos: son cinco familias de analisis sobre 8M de lineas.")

    try:
        resultado = InteligenciaComercialService().generar_reporte(config)
    except Exception as exc:  # noqa: BLE001
        print(f"Error generando el reporte: {exc}")
        return 1

    print(f"\nArchivo:   {resultado.ruta_archivo}")
    print(f"Hojas:     {resultado.hojas}")
    print(f"Alertas:   {resultado.alertas}")
    print(f"Duracion:  {resultado.duracion_segundos:.0f}s")
    if resultado.analisis_fallidos:
        # El archivo se entrega igual, pero el usuario tiene que saber que le falta.
        print(f"ATENCION — analisis que no corrieron: {', '.join(resultado.analisis_fallidos)}")
        print("El motivo esta en la hoja Metodologia del libro.")
    return 0


def _run_comparativo_salta_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate comparativo-salta report. Returns list of (path, metadata) tuples."""
    from src.services.comparativo_salta import (
        ComparativoSaltaConfig,
        ComparativoSaltaService,
    )

    fecha_desde = merged.get("fecha_desde")
    fecha_hasta = merged.get("fecha_hasta")
    if not fecha_desde or not fecha_hasta:
        print("Error: comparativo-salta requiere fecha_desde y fecha_hasta")
        return []

    config = ComparativoSaltaConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        con_detalle_clientes=merged.get("con_detalle_clientes", True),
        anios_mensual=merged.get("anios_mensual"),
        sucursal_comparativa=merged.get("sucursal_comparativa"),
        meses_vendedor=merged.get("meses_vendedor"),
        bloques_vendedor=merged.get("bloques_vendedor"),
        id_sucursal_vendedor=merged.get("id_sucursal_vendedor"),
        excluir_vendedores=merged.get("excluir_vendedores"),
        nombre_archivo=report.nombre,
    )

    service = ComparativoSaltaService()
    result = service.generar_reporte(config)

    print(f"Comparativo SALTA '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Periodo: {result.fecha_desde} al {result.fecha_hasta}")
    print(f"  - Cobertura marca: {result.cobertura_total} clientes")
    print(f"  - Calibres: {', '.join(result.calibres)}")
    return [(
        result.ruta_archivo,
        {
            "cobertura_total": result.cobertura_total,
            "calibres": result.calibres,
            "fecha_desde": result.fecha_desde,
            "fecha_hasta": result.fecha_hasta,
        },
    )]


def cmd_cupo_desagregado(args, test_mode: bool = False) -> int:
    """Ejecuta el comando cupo-desagregado."""
    if not args.config:
        print("Error: cupo-desagregado requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print("Error: cupo-desagregado solo soporta el nuevo formato de configuracion JSON.")
        return 1


def _run_cupo_desagregado_report(report, merged: dict) -> list[tuple[Path, dict]]:
    """Generate cupo-desagregado report. Returns list of (path, metadata) tuples."""
    from src.services.cupo_desagregado import (
        CupoDesagregadoConfig,
        CupoDesagregadoService,
    )

    fecha_desde = merged.get("fecha_desde")
    fecha_hasta = merged.get("fecha_hasta")
    if not fecha_desde or not fecha_hasta:
        print("Error: cupo-desagregado requiere fecha_desde y fecha_hasta (mes del cupo)")
        return []
    if not merged.get("cupos_source_path"):
        print("Error: cupo-desagregado requiere cupos_source_path en los filtros")
        return []

    config = CupoDesagregadoConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        nombre_archivo=report.nombre,
        cupos_source_path=merged["cupos_source_path"],
        cupos_hoja=merged.get("cupos_hoja"),
        historia_desde=merged.get("historia_desde"),
        historia_hasta=merged.get("historia_hasta"),
    )

    try:
        result = CupoDesagregadoService().generar_reporte(config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return []

    print(f"Cupo desagregado '{report.nombre}' generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Preventistas: {result.vendedores}")
    print(f"  - Filas por ruta: {result.filas_ruta}")
    if result.sin_ruta:
        print(f"  - Sin ruta asignada: {', '.join(result.sin_ruta)}")
    if result.sin_historia:
        print(f"  - Sin historia (reparto parejo): {', '.join(result.sin_historia)}")

    # El reparto que no cierra contra el cupo es un error de datos: no se
    # entrega un archivo mal abierto, se corta y se avisa.
    if result.errores_validacion:
        print("Error: la suma de las rutas no cierra con el cupo del preventista:")
        for clave, diferencia in result.errores_validacion.items():
            print(f"    {clave}: diferencia {diferencia}")
        return []

    return [
        (
            Path(result.ruta_archivo),
            {"nombre": report.nombre, "fecha": fecha_hasta},
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


def cmd_historico_cliente(args, test_mode: bool = False) -> int:
    """Ejecuta el comando historico-cliente."""
    if not args.config:
        print("Error: historico-cliente requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print("Error: historico-cliente solo soporta el nuevo formato de configuracion JSON.")
        return 1


def cmd_reporte_general_badie(args, test_mode: bool = False) -> int:
    """Ejecuta el comando reporte-general-badie."""
    if not args.config:
        print("Error: reporte-general-badie requiere un archivo --config")
        return 1

    config_path = Path(args.config)
    cfg = _cargar_config_json(args.config)

    if _is_new_format(cfg):
        return _run_report_config(config_path, test_mode=test_mode)
    else:
        print(
            "Error: reporte-general-badie solo soporta el nuevo formato de configuracion JSON."
        )
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

    # Global option: --no-delivery to suppress email + whatsapp dispatch
    parser.add_argument(
        "--no-delivery",
        action="store_true",
        default=False,
        dest="no_delivery",
        help="Suprime el envio de email y WhatsApp. Util para correr reportes sin notificar.",
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

    # Subcomando: champions-league
    mision_parser = subparsers.add_parser(
        "champions-league",
        help="Reporte Champions League con cobertura y categorias",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mision_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    mision_parser.set_defaults(func=cmd_champions_league)

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

    historico_cliente_parser = subparsers.add_parser(
        "historico-cliente",
        help="Historico de ventas por cliente",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    historico_cliente_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    historico_cliente_parser.set_defaults(func=cmd_historico_cliente)

    reporte_general_badie_parser = subparsers.add_parser(
        "reporte-general-badie",
        help="Reporte General Badie con selector de mes interactivo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    reporte_general_badie_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    reporte_general_badie_parser.set_defaults(func=cmd_reporte_general_badie)

    subdistribuidores_parser = subparsers.add_parser(
        "subdistribuidores",
        help="Reporte de ventas para subdistribuidores (ruta 93)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subdistribuidores_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    subdistribuidores_parser.set_defaults(func=cmd_subdistribuidores)

    stock_suria_parser = subparsers.add_parser(
        "stock-suria",
        help="Reporte de stock SURIA (articulos del proveedor pareados contra la base SURIA)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    stock_suria_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    stock_suria_parser.set_defaults(func=cmd_stock_suria)

    # Subcomando: stock-badie (alcance vs. ventas del mes en curso)
    stock_badie_parser = subparsers.add_parser(
        "stock-badie",
        help="Reporte de alcance de stock BADIE (stock actual vs. ventas del mes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    stock_badie_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    stock_badie_parser.set_defaults(func=cmd_stock_badie)

    # Subcomando: stock-valorizado (bultos + pesos por articulo y sucursal)
    stock_valorizado_parser = subparsers.add_parser(
        "stock-valorizado",
        help="Stock por articulo y sucursal en bultos y pesos (lista de precios del ERP)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    stock_valorizado_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    stock_valorizado_parser.set_defaults(func=cmd_stock_valorizado)

    # Subcomando: cupo-desagregado (abre el cupo del preventista por ruta)
    cupo_desagregado_parser = subparsers.add_parser(
        "cupo-desagregado",
        help="Abre el cupo mensual de cada preventista entre sus rutas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cupo_desagregado_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    cupo_desagregado_parser.set_defaults(func=cmd_cupo_desagregado)

    comparativo_salta_parser = subparsers.add_parser(
        "comparativo-salta",
        help="Cobertura de la marca SALTA abierta por calibre (1000, 1200, 473...)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    comparativo_salta_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    comparativo_salta_parser.set_defaults(func=cmd_comparativo_salta)

    # Subcomando: cobertura (historico de cobertura, N periodos lado a lado)
    cobertura_parser = subparsers.add_parser(
        "cobertura",
        help="Cobertura de N periodos lado a lado (mes cerrado vs mismo mes del año anterior)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cobertura_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    cobertura_parser.set_defaults(func=cmd_cobertura)

    # Subcomando: cobertura-cupos (cobertura por generico y marca, para cupos)
    cobertura_cupos_parser = subparsers.add_parser(
        "cobertura-cupos",
        help="Cobertura por generico y marca de los genericos CCU, por zona, con columna de cupo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cobertura_cupos_parser.add_argument(
        "--config",
        required=True,
        metavar="config.json",
        help="Archivo JSON con configuracion del reporte (formato nuevo requerido).",
    )
    cobertura_cupos_parser.set_defaults(func=cmd_cobertura_cupos)

    inteligencia_parser = subparsers.add_parser(
        "inteligencia-comercial",
        help="Informe analitico integral: RFM, fuga, portafolio, margen, pronostico y logistica.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Corre cinco familias de analisis sobre el esquema gold y las consolida en\n"
            "un unico libro Excel con portada, KPIs, alertas, graficos y metodologia.\n\n"
            "Ejemplos:\n"
            "  python main.py inteligencia-comercial --hasta 2026-07-30\n"
            "  python main.py inteligencia-comercial --hasta 2026-07-30 --modulos clientes,demanda\n"
        ),
    )
    inteligencia_parser.add_argument(
        "--hasta",
        default=date.today().isoformat(),
        metavar="YYYY-MM-DD",
        help="Fecha de corte del analisis (inclusive). Por defecto, hoy.",
    )
    inteligencia_parser.add_argument(
        "--meses", type=int, default=12, metavar="N",
        help="Largo de la ventana principal en meses (default: 12).",
    )
    inteligencia_parser.add_argument(
        "--historia", type=int, default=24, metavar="N",
        help="Largo de la ventana de historia para estacionalidad y ritmos (default: 24).",
    )
    inteligencia_parser.add_argument(
        "--modulos", default=None, metavar="a,b",
        help=("Subconjunto de analisis a correr, separados por coma: "
              "clientes, portafolio, rentabilidad, demanda, logistica. "
              "Por defecto corre todos."),
    )
    inteligencia_parser.add_argument(
        "--nombre", default=None, metavar="archivo",
        help="Nombre del xlsx sin extension. Se deriva de la fecha si se omite.",
    )
    inteligencia_parser.set_defaults(func=cmd_inteligencia_comercial)

    # check-delivery: mostrar estado de envios del dia
    check_parser = subparsers.add_parser(
        "check-delivery",
        help="Muestra el registro de envios del dia de hoy.",
    )
    check_parser.set_defaults(func=lambda args: None)

    # Parsear argumentos
    args = parser.parse_args()

    from src.core.delivery_log import mostrar_resumen

    # check-delivery: show today's send log
    if hasattr(args, "comando") and args.comando == "check-delivery":
        print(mostrar_resumen())
        return 0

    test_mode = _resolve_test_mode(args.test_mode)
    if test_mode:
        print("[TEST MODE ACTIVO] delivery redirigido a Nahuel Aguirre", flush=True)

    no_delivery = getattr(args, "no_delivery", False)
    if no_delivery:
        print("[NO DELIVERY] envio de email y WhatsApp desactivado", flush=True)

    # --config mode: process a single config file
    if args.config:
        return _run_report_config(Path(args.config), test_mode=test_mode, no_delivery=no_delivery)

    # --config-dir mode: process all configs in directory
    if args.config_dir:
        return _run_config_dir(Path(args.config_dir), test_mode=test_mode)

    if args.comando is None:
        parser.print_help()
        return 1

    return args.func(args, test_mode=test_mode)


if __name__ == "__main__":
    sys.exit(main())
