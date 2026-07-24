#!/usr/bin/env python3
"""Daily flow runner — executes registered services with today's date.

Patches each config's fecha_desde/fecha_hasta to today (or the configured
mode) and runs it through the normal pipeline. Delivery (email/whatsapp)
is handled by each config's own `enviar_a` entries — the script does NOT
override them, EXCEPT when `configs/daily_overrides.json` says otherwise.

Usage:
    python scripts/run_daily.py                       # all registered services
    python scripts/run_daily.py --date 2026-04-18     # override today (for testing)
    python scripts/run_daily.py --dry-run             # show patched fechas, don't execute
    python scripts/run_daily.py --only stock-diario   # run a subset
    python scripts/run_daily.py --only stock-diario champions-league

Add a new service:
    Append a `Servicio(...)` entry to SERVICIOS below. Three date modes:
        - "hoy"         : fecha_desde = fecha_hasta = today (single-day snapshots)
        - "mes_a_hoy"   : fecha_desde = first day of month, fecha_hasta = today
        - "solo_hasta"  : keep fecha_desde as-is, only patch fecha_hasta = today

Daily overrides (configs/daily_overrides.json):
    Optional file. Per-service flags to skip execution and/or delivery.
    Missing file → all services execute and deliver as configured. Schema:

        {
            "<servicio>": {
                "ejecutar": true | false,   // default: true
                "enviar":   true | false,   // default: true
                "razon":    "string"        // optional log note
            }
        }

    `ejecutar=false` → skip the service entirely.
    `ejecutar=true, enviar=false` → generate the file but suppress delivery
    (clears `enviar_a` in the patched config).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from main import _run_reportes, _resolve_test_mode  # noqa: E402
from config.settings import FERIADOS  # noqa: E402
from src.config.resolver import load_contacts, load_report_config  # noqa: E402


def _refresh_mv_resumen_mensual() -> None:
    """Refresh gold.mv_resumen_mensual so the Superset dashboard has current data.

    Called once at the start of every daily run, after the medallion ETL has
    loaded fact_ventas (ETL finishes before 07:00; this script runs at 07:00).
    CONCURRENTLY means the dashboard is never locked during the refresh.

    Errors are logged and silenced — a stale MV is acceptable; crashing the
    entire daily run for a dashboard refresh is not.
    """
    try:
        import os
        from sqlalchemy import create_engine, text
        from dotenv import load_dotenv

        env_path = ROOT / ".env"
        if env_path.exists():
            load_dotenv(str(env_path), override=False)

        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        db = os.getenv("DB_NAME")
        user = os.getenv("DB_USER")
        password = os.getenv("DB_PASSWORD")

        if not all([db, user, password]):
            print("  ⚠️  MV refresh skipped — DB credentials not set in environment")
            return

        url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
        engine = create_engine(url, connect_args={"connect_timeout": 30})
        with engine.connect() as conn:
            conn.execute(text(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_resumen_mensual"
            ))
            conn.commit()
        print("  ✅  gold.mv_resumen_mensual refreshed")
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  gold.mv_resumen_mensual refresh failed (non-fatal): {exc!r}")


CONFIGS_DIR = ROOT / "configs"
CONTACTOS_PATH = CONFIGS_DIR / "contactos.json"
OVERRIDES_PATH = CONFIGS_DIR / "daily_overrides.json"

FechaModo = Literal["hoy", "mes_a_hoy", "solo_hasta"]

# RAM guard for image-rendering reports (e.g. avance-badie's LibreOffice capture).
# The render needs ~2.5 GB RAM; below this floor we skip images rather than risk
# an OOM-killed render silently dropping the WhatsApp send.
RAM_MIN_MB_IMAGENES = 3000
_MEMINFO_PATH = Path("/proc/meminfo")


def _is_business_day(value: date) -> bool:
    """Return True when the date is not Sunday nor configured holiday."""
    feriados = {datetime.strptime(raw, "%Y-%m-%d").date() for raw in FERIADOS}
    return value.weekday() != 6 and value not in feriados


def _is_first_business_day_of_month(value: date) -> bool:
    """Return True if the given date is the first business day of its month."""
    if not _is_business_day(value):
        return False

    cursor = value.replace(day=1)
    while cursor < value:
        if _is_business_day(cursor):
            return False
        cursor += timedelta(days=1)
    return True


def _resolve_mes_a_hoy_range(hoy: date) -> tuple[str, str]:
    """Resolve the date range for monthly daily reports.

    Rule: on the first business day of a month, send the previous month closed.
    Otherwise, keep the current month-to-date behavior.
    """
    if _is_first_business_day_of_month(hoy):
        ultimo_dia_mes_anterior = hoy.replace(day=1) - timedelta(days=1)
        primer_dia_mes_anterior = ultimo_dia_mes_anterior.replace(day=1)
        return primer_dia_mes_anterior.isoformat(), ultimo_dia_mes_anterior.isoformat()

    return hoy.replace(day=1).isoformat(), hoy.isoformat()


@dataclass(frozen=True)
class Servicio:
    """Registered daily service."""
    nombre: str
    config_path: Path
    fecha_modo: FechaModo

    def patch(self, raw: dict, hoy: date) -> dict:
        """Return a new config dict with fechas patched according to fecha_modo."""
        patched = json.loads(json.dumps(raw))  # deep copy
        filtros = patched.setdefault("filtros", {})
        hoy_iso = hoy.isoformat()

        if self.fecha_modo == "hoy":
            filtros["fecha_desde"] = hoy_iso
            filtros["fecha_hasta"] = hoy_iso
        elif self.fecha_modo == "mes_a_hoy":
            fecha_desde, fecha_hasta = _resolve_mes_a_hoy_range(hoy)
            filtros["fecha_desde"] = fecha_desde
            filtros["fecha_hasta"] = fecha_hasta
        elif self.fecha_modo == "solo_hasta":
            filtros["fecha_hasta"] = hoy_iso
        return patched


# ── Add / remove services here ──
SERVICIOS: list[Servicio] = [
    Servicio(
        nombre="stock-diario",
        config_path=CONFIGS_DIR / "stock_diario.json",
        fecha_modo="hoy",
    ),
    Servicio(
        nombre="champions-league",
        config_path=CONFIGS_DIR / "champions_league.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="graficos-cobertura",
        config_path=CONFIGS_DIR / "graficos_cobertura.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="schneider-710",
        config_path=CONFIGS_DIR / "schneider710.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="avance-branca",
        config_path=CONFIGS_DIR / "avances_branca.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="avance-badie",
        config_path=CONFIGS_DIR / "avances_badie.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="avance-guemes",
        config_path=CONFIGS_DIR / "avances_guemes.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="ventas",
        config_path=CONFIGS_DIR / "ventas.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="ventas-marca-pernod",
        config_path=CONFIGS_DIR / "ventas_marca_pernod_ricard.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="ventas-cober-preventista-marca",
        config_path=CONFIGS_DIR / "ventas_cober_preventista_marca.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="resumen-mensual",
        config_path=CONFIGS_DIR / "resumen_mensual.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="reporte-rebotes",
        config_path=CONFIGS_DIR / "rebotes.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="descuentos",
        config_path=CONFIGS_DIR / "descuentos.json",
        fecha_modo="mes_a_hoy",
    ),
    # Incentivo ON PREMISE — vigente HASTA 2026-06-13. Después de esa fecha
    # quitar de esta lista (o poner ejecutar=false en daily_overrides.json):
    # los datos quedarían obsoletos porque el incentivo termina.
    Servicio(
        nombre="incentivo-cobertura",
        config_path=CONFIGS_DIR / "incentivo_cobertura.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="stock-suria",
        config_path=CONFIGS_DIR / "stock_suria.json",
        fecha_modo="hoy",
    ),
    Servicio(
        nombre="stock-suria-control",
        config_path=CONFIGS_DIR / "stock_suria_control.json",
        fecha_modo="hoy",
    ),
    Servicio(
        nombre="stock-suria-completo",
        config_path=CONFIGS_DIR / "stock_suria_completo.json",
        fecha_modo="hoy",
    ),
]


def _load_overrides() -> dict[str, dict]:
    """Load daily_overrides.json. Missing file → empty dict (default behavior)."""
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"⚠️  daily_overrides.json invalido ({exc}) — se ignora")
        return {}


def _strip_delivery(patched: dict) -> dict:
    """Clear all `enviar_a` entries in the patched config so delivery is suppressed."""
    for reporte in patched.get("reportes", []):
        reporte["enviar_a"] = {}
    return patched


def _keep_only_channel(patched: dict, channel: str) -> dict:
    """Filter each enviar_a entry's `via` list to keep only the given channel.

    Drops entries that end up with empty `via`. Useful for forcing single-channel
    delivery (e.g., only whatsapp).
    """
    for reporte in patched.get("reportes", []):
        enviar_a = reporte.get("enviar_a") or {}
        kept: dict = {}
        for contacto, target in enviar_a.items():
            via = target.get("via", []) if isinstance(target, dict) else []
            filtered = [v for v in via if v == channel]
            if filtered:
                new_target = dict(target)
                new_target["via"] = filtered
                kept[contacto] = new_target
        reporte["enviar_a"] = kept
    return patched


def _objetivo_cargado(periodo: str, id_sucursal: int) -> bool:
    """True if gold.fact_cupos has CCU cupo rows for this periodo + sucursal.

    Fail-closed: if the objetivo cannot be confirmed (DB/connection error), this
    returns False (treated as 'not loaded') so delivery is held — better to hold
    the send than to email a report with missing/stale cupos.
    """
    import os

    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text

    try:
        env_path = ROOT / ".env"
        if env_path.exists():
            load_dotenv(str(env_path), override=False)
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        db = os.getenv("DB_NAME")
        user = os.getenv("DB_USER")
        password = os.getenv("DB_PASSWORD")
        url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
        engine = create_engine(url, connect_args={"connect_timeout": 15})
        with engine.connect() as conn:
            n = conn.execute(
                text(
                    "SELECT count(*) FROM gold.fact_cupos "
                    "WHERE periodo = :p AND id_sucursal = :s AND proveedor = 'CCU'"
                ),
                {"p": periodo, "s": id_sucursal},
            ).scalar()
        return bool(n and int(n) > 0)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  objetivo gate: no se pudo verificar cupos ({exc!r}) — se asume NO cargado")
        return False


def _objetivo_gate_bloquea(patched: dict) -> bool:
    """True when a report opts into the objetivo gate (``filtros.esperar_objetivo``)
    AND the month's cupos are not loaded in gold yet — i.e. delivery must be held.

    The period comes from the report's own patched ``fecha_desde``, so the day-1
    cierre (previous month, whose cupos are already loaded) is never blocked.
    """
    filtros = patched.get("filtros", {})
    if not filtros.get("esperar_objetivo"):
        return False
    id_sucursal = filtros.get("id_sucursal")
    fecha_desde = filtros.get("fecha_desde")
    # Fail-closed: the gate is opted in, but we can't identify what to check —
    # hold the send rather than deliver ungated.
    if id_sucursal is None or not fecha_desde:
        print("  ⚠️  objetivo gate activo pero falta id_sucursal/fecha_desde — se retiene el envío")
        return True
    try:
        suc = int(id_sucursal)
    except (TypeError, ValueError):
        print(f"  ⚠️  objetivo gate: id_sucursal no numérico ({id_sucursal!r}) — se retiene el envío")
        return True
    return not _objetivo_cargado(str(fecha_desde)[:7], suc)


def _mem_available_mb() -> int | None:
    """Read `MemAvailable` from /proc/meminfo and return it in MB.

    Returns None (never raises) if the file can't be read or the field is
    missing — a fail-soft signal, not an error. Reads directly from /proc,
    no new dependencies.
    """
    try:
        contenido = _MEMINFO_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    for linea in contenido.splitlines():
        if linea.startswith("MemAvailable:"):
            partes = linea.split()
            try:
                kb = int(partes[1])
            except (IndexError, ValueError):
                return None
            return kb // 1024
    return None


def _report_renderiza_imagenes(patched: dict) -> bool:
    """True iff the patched config would trigger a LibreOffice image render.

    All of: enviar_whatsapp on, whatsapp_enviar_como includes images, and at
    least one reporte has a non-empty capture_images (or legacy capture_image).
    """
    filtros = patched.get("filtros", {})
    if not filtros.get("enviar_whatsapp"):
        return False
    if filtros.get("whatsapp_enviar_como") not in ("imagen", "ambos"):
        return False
    for reporte in patched.get("reportes", []):
        if reporte.get("capture_images") or reporte.get("capture_image"):
            return True
    return False


def _ram_guard_omite_imagenes(patched: dict, avail_mb: int | None) -> bool:
    """True when the RAM guard must suppress image delivery for this report.

    Fail-open: avail_mb is None means the measurement glitched (/proc/meminfo
    is always present on this Linux host), so it must NOT be treated as "low
    RAM" — doing so would suppress images on every run, not just genuinely
    low-RAM ones.
    """
    if avail_mb is None:
        return False
    if not _report_renderiza_imagenes(patched):
        return False
    return avail_mb < RAM_MIN_MB_IMAGENES


def _alertar_ram_baja(nombre: str, avail_mb: int | None) -> None:
    """Notify Nahuel by WhatsApp that images were skipped due to low RAM.

    Best-effort: an alert failure must NEVER crash the daily run — it's a
    secondary notification, not part of the report pipeline.
    """
    try:
        from config.settings import WHATSAPP_SERVICE_URL
        from src.core.whatsapp_client import WhatsAppClient

        contactos = load_contacts(CONTACTOS_PATH)
        nahuel = contactos.get("Nahuel Aguirre")
        telefono = nahuel.telefono if nahuel else None
        if not telefono:
            print("  ⚠️  alerta RAM baja: 'Nahuel Aguirre' sin telefono en contactos — no se envía")
            return
        msg = (
            f"⚠️ {nombre}: RAM baja ({avail_mb} MB) a las 07:00 — se envió el xlsx por "
            f"email pero se OMITIERON las imágenes del grupo. Cerrá el VM y regenerá si "
            f"querés las imágenes."
        )
        WhatsAppClient(WHATSAPP_SERVICE_URL).send_text(target=telefono, text=msg)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  no se pudo enviar la alerta de RAM baja: {exc!r}")


def _ejecutar_servicio(
    svc: Servicio,
    hoy: date,
    test_mode: bool = False,
    enviar: bool = True,
    solo_canal: str | None = None,
) -> int:
    """Load the config, patch fechas, and run through the normal pipeline."""
    raw = json.loads(svc.config_path.read_text(encoding="utf-8"))
    patched = svc.patch(raw, hoy)

    # Objetivo gate: opt-in reports (filtros.esperar_objetivo) only deliver once
    # the month's cupos are loaded in gold. Otherwise generate but hold the send.
    if enviar and _objetivo_gate_bloquea(patched):
        f = patched.get("filtros", {})
        print(
            f"  🚧 {svc.nombre}: objetivo del mes no cargado "
            f"(sucursal {f.get('id_sucursal')}, periodo {str(f.get('fecha_desde', ''))[:7]}) "
            f"— se genera pero NO se envía"
        )
        enviar = False

    # RAM guard: image-rendering reports (LibreOffice capture, ~2.5 GB) can get
    # OOM-killed if a VM is eating RAM at 07:00, silently dropping the WhatsApp
    # send. If RAM is short, disable enviar_whatsapp — resolve_delivery then
    # builds no WhatsApp config, so CaptureImageStep's `_images_consumed` gate
    # returns False (email adjuntos default to ["excel"], not image) → no
    # render, no OOM, but the email xlsx still goes out. Nahuel gets alerted.
    if enviar and _report_renderiza_imagenes(patched):
        avail = _mem_available_mb()
        if _ram_guard_omite_imagenes(patched, avail):
            print(
                f"  🧠 {svc.nombre}: RAM insuficiente ({avail} MB < {RAM_MIN_MB_IMAGENES} MB) — "
                f"se envía xlsx por email, se OMITEN las imágenes"
            )
            patched.setdefault("filtros", {})["enviar_whatsapp"] = False
            _alertar_ram_baja(svc.nombre, avail)

    if not enviar:
        patched = _strip_delivery(patched)
    elif solo_canal:
        patched = _keep_only_channel(patched, solo_canal)

    # Write patched config to a temp file so the existing loader can consume it
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir=str(CONFIGS_DIR), encoding="utf-8"
    ) as tmp:
        json.dump(patched, tmp, indent=2, ensure_ascii=False)
        tmp_path = Path(tmp.name)

    try:
        report_config = load_report_config(tmp_path)
        contactos = load_contacts(CONTACTOS_PATH) if CONTACTOS_PATH.exists() else {}
        report_config.validate_contacts(contactos)
        return _run_reportes(report_config, contactos, test_mode=test_mode)
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Override today's date (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Print patched fechas without executing")
    parser.add_argument("--only", nargs="+", metavar="SERVICIO", help="Run only these services by name")
    parser.add_argument("--test-mode", action="store_true", default=False, help="Redirige toda la entrega a Nahuel Aguirre (tambien activable con INFORMES_TEST_MODE=1)")
    parser.add_argument("--solo-canal", choices=["whatsapp", "email"], help="Filtra entrega a un solo canal (descarta los demas via)")
    args = parser.parse_args()

    hoy = date.fromisoformat(args.date) if args.date else date.today()
    test_mode = _resolve_test_mode(args.test_mode)
    if test_mode:
        print("[TEST MODE ACTIVO] delivery redirigido a Nahuel Aguirre")

    servicios = SERVICIOS
    if args.only:
        unknown = set(args.only) - {s.nombre for s in SERVICIOS}
        if unknown:
            print(f"Error: servicios desconocidos: {sorted(unknown)}")
            print(f"Disponibles: {[s.nombre for s in SERVICIOS]}")
            return 1
        servicios = [s for s in SERVICIOS if s.nombre in args.only]

    overrides = _load_overrides()

    print(f"Fecha: {hoy.isoformat()}")
    print(f"Servicios a ejecutar: {[s.nombre for s in servicios]}")
    if overrides:
        print(f"Overrides activos: {list(overrides.keys())}")

    if not args.dry_run:
        # Refresh Superset MV before any report runs so the dashboard is current.
        # The medallion ETL has already loaded fact_ventas by the time this runs
        # (ETL finishes before 07:00; daily timer fires at 07:00).
        print("\n--- Refreshing gold.mv_resumen_mensual ---")
        _refresh_mv_resumen_mensual()

    if args.dry_run:
        print("\n=== DRY RUN (no se ejecuta nada) ===")
        for svc in servicios:
            ov = overrides.get(svc.nombre, {})
            ejecutar = ov.get("ejecutar", True)
            enviar = ov.get("enviar", True)
            razon = ov.get("razon", "")
            raw = json.loads(svc.config_path.read_text(encoding="utf-8"))
            patched = svc.patch(raw, hoy)
            f = patched["filtros"]
            print(f"\n[{svc.nombre}] modo={svc.fecha_modo} ejecutar={ejecutar} enviar={enviar}{f' — {razon}' if razon else ''}")
            print(f"  fecha_desde: {f.get('fecha_desde')}")
            print(f"  fecha_hasta: {f.get('fecha_hasta')}")
        return 0

    errores: list[str] = []
    for svc in servicios:
        ov = overrides.get(svc.nombre, {})
        ejecutar = ov.get("ejecutar", True)
        enviar = ov.get("enviar", True)
        razon = ov.get("razon", "")

        print(f"\n{'=' * 60}")
        if not ejecutar:
            print(f"  ⏭️  SKIP: {svc.nombre}{f' — {razon}' if razon else ''}")
            print(f"{'=' * 60}")
            continue
        if not enviar:
            print(f"  Ejecutando: {svc.nombre}  (📵 sin envío{f' — {razon}' if razon else ''})")
        else:
            print(f"  Ejecutando: {svc.nombre}")
        print(f"{'=' * 60}")
        try:
            code = _ejecutar_servicio(svc, hoy, test_mode=test_mode, enviar=enviar, solo_canal=args.solo_canal)
            if code != 0:
                errores.append(f"{svc.nombre} (exit {code})")
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR en {svc.nombre}: {exc!r}")
            errores.append(f"{svc.nombre} (exception: {exc})")

    print(f"\n{'=' * 60}")
    if errores:
        print(f"Completado con errores: {errores}")
        return 1
    print(f"Todos los servicios OK ({len(servicios)}/{len(servicios)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
