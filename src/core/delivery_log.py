"""
DeliveryLog - registro de envios del dia para saber que se entrego y que no.

Persiste un JSON por dia en data/output/_send_log/YYYY-MM-DD.json.
Cada entrada: { tipo, nombre, archivos, hora, status }
"""
import json
import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_SEND_LOG_DIR = Path("data/output/_send_log")


def _log_path(d: date | None = None) -> Path:
    d = d or date.today()
    _SEND_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _SEND_LOG_DIR / f"{d.isoformat()}.json"


def registrar_envio(
    tipo: str,
    nombre: str,
    archivos: list[str],
    status: str = "enviado",
) -> None:
    log = _leer_log()
    log.append({
        "tipo": tipo,
        "nombre": nombre,
        "archivos": archivos,
        "hora": datetime.now().isoformat(timespec="minutes"),
        "status": status,
    })
    _escribir_log(log)


def _leer_log(d: date | None = None) -> list:
    path = _log_path(d)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _escribir_log(entries: list, d: date | None = None) -> None:
    path = _log_path(d)
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def ya_enviado_hoy(tipo: str, nombre: str) -> bool:
    for entry in _leer_log():
        if entry["tipo"] == tipo and entry["nombre"] == nombre and entry.get("status") == "enviado":
            return True
    return False


def mostrar_resumen(d: date | None = None) -> str:
    entries = _leer_log(d)
    if not entries:
        return "No se registraron envios hoy."

    lines = [f"Envios del {d or date.today()}:", ""]
    for e in entries:
        archivos = ", ".join(e.get("archivos", []))
        lines.append(f"  [{e['hora']}] {e['tipo']} - {e['nombre']}")
        lines.append(f"           Status: {e['status']} | {archivos}")
    lines.append("")
    lines.append(f"Total: {len(entries)} envio(s)")
    return "\n".join(lines)