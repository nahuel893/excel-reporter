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


CONFIGS_DIR = ROOT / "configs"
CONTACTOS_PATH = CONFIGS_DIR / "contactos.json"
OVERRIDES_PATH = CONFIGS_DIR / "daily_overrides.json"

FechaModo = Literal["hoy", "mes_a_hoy", "solo_hasta"]


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
        nombre="ventas",
        config_path=CONFIGS_DIR / "ventas.json",
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
