#!/usr/bin/env python3
"""Reenvia por WhatsApp lo que quedo en `error` en el log de envios del dia.

Para cuando el daily genero todo bien pero la entrega se cayo — tipicamente
porque la sesion de Baileys se desvinculo y `/send-image` devolvio 503. Pasa lo
suficiente como para no volver a resolverlo a mano cada vez (2026-06-05,
2026-08-21, 2026-08-22).

**No regenera nada.** Toma los archivos que ya estan en disco: el principal sale
del propio log de envios y las imagenes se buscan por el prefijo que deja el
renderer. Un libro que Nahuel edito a mano se manda tal cual quedo.

**Solo WhatsApp.** El mail de la corrida ya salio — reenviarlo duplicaria.

Uso:
    python scripts/reenviar_fallidos.py                # dry-run, no manda nada
    python scripts/reenviar_fallidos.py --enviar
    python scripts/reenviar_fallidos.py --fecha 2026-08-22 --solo avances
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.config.resolver import (  # noqa: E402
    load_contacts, load_report_config, merge_filters, resolve_delivery,
)
from src.delivery.pipeline import DeliveryPipeline, ReportArtifact  # noqa: E402
from src.delivery.steps import SendWhatsAppStep  # noqa: E402

SEND_LOG_DIR = RAIZ / "data" / "output" / "_send_log"
CONFIGS_DIR = RAIZ / "configs"
CONTACTOS_PATH = CONFIGS_DIR / "contactos.json"

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
         "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


def _resolver_periodo(nombre: str, fecha_desde: str) -> str:
    """Misma sustitucion que `_resolver_nombre_periodo` de main.py.

    Sin esto un config con "{MES} {AÑO}" nunca casa contra el nombre ya
    resuelto que quedo escrito en el log.
    """
    if not nombre or "{" not in nombre or not fecha_desde:
        return nombre
    try:
        d = date.fromisoformat(fecha_desde[:10])
    except ValueError:
        return nombre
    for token, valor in (("{MES}", MESES[d.month - 1]),
                         ("{AÑO}", str(d.year)),
                         ("{ANIO}", str(d.year))):
        nombre = nombre.replace(token, valor)
    return nombre


def _nombres_posibles(report, merged: dict, fecha_log: str) -> set:
    """Todos los nombres bajo los que ese reporte pudo quedar en el log.

    Dos motivos para que no alcance con el nombre del config:

    - El daily parchea las fechas antes de correr, asi que "{MES} {AÑO}" se
      resolvio con el mes de la corrida y no con el que quedo escrito en el
      config. Por eso se prueba tambien contra la fecha del log.
    - Los informes por supervisor nombran cada archivo por el supervisor y
      descartan el `nombre` del config: el reporte que en `ventas.json` se llama
      "Ventas CCU - WV" quedo en el log como "Ventas Walter Vilte".
    """
    bases = {report.nombre}
    for fecha in (merged.get("fecha_desde", ""), fecha_log):
        bases.add(_resolver_periodo(report.nombre, fecha))
    return bases


def _buscar_reporte(tipo: str, nombre: str, fecha_log: str):
    """(config, report, merged) del reporte que produjo esa entrada del log.

    Busca por `tipo` + `nombre`. El nombre desambigua los configs que comparten
    tipo — los tres avances, por ejemplo.
    """
    for ruta in sorted(CONFIGS_DIR.glob("*.json")):
        try:
            crudo = json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        # configs/ tiene tambien listas y catalogos (contactos, feriados), no
        # solo configs de reporte.
        if not isinstance(crudo, dict) or crudo.get("tipo") != tipo:
            continue
        try:
            cfg = load_report_config(ruta)
        except Exception:
            continue
        for report in cfg.reportes:
            merged = merge_filters(cfg.filtros, report.filtros)
            if nombre in _nombres_posibles(report, merged, fecha_log):
                return cfg, report, merged
            # Por supervisor: el nombre del log termina con el supervisor del
            # reporte, sin importar como se llame el reporte en el config.
            supervisores = merged.get("supervisores") or {}
            if any(nombre.endswith(sup) for sup in supervisores):
                return cfg, report, merged
    return None, None, None


def _imagenes_de(report, principal: Path) -> tuple[list, list]:
    """(rutas, captions) de las capturas que ya estan renderizadas en disco.

    El renderer nombra cada PNG `{stem}_{hoja}_{rango}.png` con los `:` del
    rango cambiados por `_`. Con rangos `auto:` el rango final no se conoce acá,
    asi que se cae a buscar por el prefijo de la hoja.
    """
    rutas, captions = [], []
    for cap in (report.capture_images or []):
        hoja = cap.hoja
        exacta = principal.parent / f"{principal.stem}_{hoja}_{cap.rango.replace(':', '_')}.png"
        if exacta.is_file():
            elegida = exacta
        else:
            candidatas = [
                p for p in principal.parent.glob(f"{principal.stem}_{hoja}_*.png")
                if "backup-" not in p.name
            ]
            if not candidatas:
                continue
            elegida = max(candidatas, key=lambda p: p.stat().st_mtime)
        rutas.append(elegida)
        captions.append(cap.caption or hoja)
    return rutas, captions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fecha", default=date.today().isoformat(),
                        metavar="YYYY-MM-DD", help="Dia del log a reenviar.")
    parser.add_argument("--solo", nargs="+", metavar="TIPO",
                        help="Reenviar solo estos tipos.")
    parser.add_argument("--excluir", nargs="+", default=[], metavar="NOMBRE",
                        help="Saltear estos nombres. Para lo que ya se mando a "
                             "mano: el log lo sigue marcando en error porque el "
                             "envio de afuera no lo registra.")
    parser.add_argument("--enviar", action="store_true",
                        help="Mandar de verdad. Sin esto es dry-run.")
    args = parser.parse_args()

    log_path = SEND_LOG_DIR / f"{args.fecha}.json"
    if not log_path.is_file():
        print(f"ERROR: no hay log de envios para {args.fecha}", file=sys.stderr)
        return 1

    entradas = [e for e in json.loads(log_path.read_text(encoding="utf-8"))
                if e.get("status") == "error"]
    if args.solo:
        entradas = [e for e in entradas if e.get("tipo") in args.solo]
    if args.excluir:
        entradas = [e for e in entradas if e.get("nombre") not in args.excluir]
    if not entradas:
        print("No hay envios en error para reenviar.")
        return 0

    contactos = load_contacts(CONTACTOS_PATH)
    pendientes, sin_resolver = [], []

    for entrada in entradas:
        tipo, nombre = entrada["tipo"], entrada["nombre"]
        archivos = [Path(a) for a in entrada.get("archivos", [])]
        principal = next((a for a in archivos if a.is_file()), None)
        if principal is None:
            sin_resolver.append((tipo, nombre, "el archivo ya no esta en disco"))
            continue

        cfg, report, merged = _buscar_reporte(tipo, nombre, args.fecha)
        if report is None:
            sin_resolver.append((tipo, nombre, "no encontre su config"))
            continue

        delivery = resolve_delivery(
            report, contactos,
            enviar_email=False,
            enviar_whatsapp=True,
            whatsapp_enviar_como=merged.get("whatsapp_enviar_como", "imagen"),
            whatsapp_caption_imagenes=merged.get("whatsapp_caption_imagenes", True),
        )
        if delivery is None or delivery.whatsapp is None:
            sin_resolver.append((tipo, nombre, "no tiene destinos de WhatsApp"))
            continue

        imagenes, captions = _imagenes_de(report, principal)
        como = delivery.whatsapp.enviar_como
        if como == "imagen" and not imagenes:
            sin_resolver.append(
                (tipo, nombre, "manda imagenes y no hay PNG en disco: hay que renderizar"))
            continue

        pendientes.append((tipo, nombre, principal, imagenes, captions, delivery, como))

    print(f"Log {args.fecha}: {len(entradas)} en error, {len(pendientes)} reenviables\n")
    for tipo, nombre, principal, imagenes, _c, delivery, como in pendientes:
        destinos = ", ".join(delivery.whatsapp.grupos)
        detalle = f"{len(imagenes)} imagen(es)" if como != "archivo" else principal.name
        print(f"  {tipo:<30} {nombre[:38]:<38} como={como:<8} {detalle}")
        print(f"  {'':<30} -> {destinos}")

    if sin_resolver:
        print("\nNo se reenvian:")
        for tipo, nombre, motivo in sin_resolver:
            print(f"  {tipo:<30} {nombre[:38]:<38} {motivo}")

    if not args.enviar:
        print("\nDRY-RUN. Nada enviado. Correr con --enviar.")
        return 0

    print()
    fallados = 0
    for tipo, nombre, principal, imagenes, captions, delivery, _como in pendientes:
        artifact = ReportArtifact(
            ruta_excel=principal,
            rutas_imagenes=imagenes,
            nombres_hojas=captions,
            metadata={"_tipo": tipo},
        )
        resultado = DeliveryPipeline([SendWhatsAppStep()]).run(artifact, delivery)
        for paso in resultado.steps:
            marca = "ok " if paso.status == "success" else "FALLO"
            if paso.status != "success":
                fallados += 1
            print(f"  {marca} {nombre[:44]:<44} {paso.message[:70]}")

    return 1 if fallados else 0


if __name__ == "__main__":
    raise SystemExit(main())
