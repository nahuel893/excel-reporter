#!/usr/bin/env python3
"""Daily flow runner — executes registered services with today's date.

Patches each config's fecha_desde/fecha_hasta to today (or the configured
mode) and runs it through the normal pipeline. Delivery (email/whatsapp)
is handled by each config's own `enviar_email` / `enviar_whatsapp` flags
and `enviar_a` entries — the script does NOT override them.

Usage:
    python scripts/run_daily.py                       # all registered services
    python scripts/run_daily.py --date 2026-04-18     # override today (for testing)
    python scripts/run_daily.py --dry-run             # show patched fechas, don't execute
    python scripts/run_daily.py --only stock-diario   # run a subset
    python scripts/run_daily.py --only stock-diario mision-imposible

Add a new service:
    Append a `Servicio(...)` entry to SERVICIOS below. Three date modes:
        - "hoy"         : fecha_desde = fecha_hasta = today (single-day snapshots)
        - "mes_a_hoy"   : fecha_desde = first day of month, fecha_hasta = today
        - "solo_hasta"  : keep fecha_desde as-is, only patch fecha_hasta = today
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from main import _run_reportes  # noqa: E402
from src.config.resolver import load_contacts, load_report_config  # noqa: E402


CONFIGS_DIR = ROOT / "configs"
CONTACTOS_PATH = CONFIGS_DIR / "contactos.json"

FechaModo = Literal["hoy", "mes_a_hoy", "solo_hasta"]


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
            filtros["fecha_desde"] = hoy.replace(day=1).isoformat()
            filtros["fecha_hasta"] = hoy_iso
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
        nombre="mision-imposible",
        config_path=CONFIGS_DIR / "mision_imposible.json",
        fecha_modo="mes_a_hoy",
    ),
    Servicio(
        nombre="graficos-cobertura",
        config_path=CONFIGS_DIR / "graficos_cobertura.json",
        fecha_modo="mes_a_hoy",
    ),
]


def _ejecutar_servicio(svc: Servicio, hoy: date) -> int:
    """Load the config, patch fechas, and run through the normal pipeline."""
    raw = json.loads(svc.config_path.read_text(encoding="utf-8"))
    patched = svc.patch(raw, hoy)

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
        return _run_reportes(report_config, contactos)
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Override today's date (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Print patched fechas without executing")
    parser.add_argument("--only", nargs="+", metavar="SERVICIO", help="Run only these services by name")
    args = parser.parse_args()

    hoy = date.fromisoformat(args.date) if args.date else date.today()

    servicios = SERVICIOS
    if args.only:
        unknown = set(args.only) - {s.nombre for s in SERVICIOS}
        if unknown:
            print(f"Error: servicios desconocidos: {sorted(unknown)}")
            print(f"Disponibles: {[s.nombre for s in SERVICIOS]}")
            return 1
        servicios = [s for s in SERVICIOS if s.nombre in args.only]

    print(f"Fecha: {hoy.isoformat()}")
    print(f"Servicios a ejecutar: {[s.nombre for s in servicios]}")

    if args.dry_run:
        print("\n=== DRY RUN (no se ejecuta nada) ===")
        for svc in servicios:
            raw = json.loads(svc.config_path.read_text(encoding="utf-8"))
            patched = svc.patch(raw, hoy)
            f = patched["filtros"]
            print(f"\n[{svc.nombre}] modo={svc.fecha_modo}")
            print(f"  fecha_desde: {f.get('fecha_desde')}")
            print(f"  fecha_hasta: {f.get('fecha_hasta')}")
        return 0

    errores: list[str] = []
    for svc in servicios:
        print(f"\n{'=' * 60}")
        print(f"  Ejecutando: {svc.nombre}")
        print(f"{'=' * 60}")
        try:
            code = _ejecutar_servicio(svc, hoy)
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
