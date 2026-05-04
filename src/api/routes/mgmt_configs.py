"""
Management API routes: config CRUD + JSON Schema + reference data + contactos.

Endpoints:
    GET    /mgmt/configs                     — list all configs
    GET    /mgmt/configs/{filename}          — get config content + schema
    PUT    /mgmt/configs/{filename}          — validate + atomic write
    GET    /mgmt/configs/schema/{tipo}       — JSON Schema for a tipo
    GET    /mgmt/configs/path-exists         — check if a path exists
    GET    /mgmt/refs/sucursales             — list sucursales
    GET    /mgmt/refs/genericos              — list genericos
    GET    /mgmt/refs/supervisores           — list supervisores (from configs)
    GET    /mgmt/contactos                   — read contactos.json
    PUT    /mgmt/contactos                   — write contactos.json
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mgmt")

# Default configs dir — overridable via set_configs_dir() for tests
_CONFIGS_DIR: Path = Path("configs")


def set_configs_dir(path: Path) -> None:
    """Override the configs directory (used in tests)."""
    global _CONFIGS_DIR
    _CONFIGS_DIR = Path(path)


def _get_configs_dir() -> Path:
    return _CONFIGS_DIR


def _read_config(filename: str) -> dict:
    path = _get_configs_dir() / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Config '{filename}' not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_config_atomic(filename: str, content: dict) -> None:
    """Write config atomically using a temp file + os.replace."""
    path = _get_configs_dir() / filename
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, path)


def _mtime_iso(path: Path) -> str:
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def _get_schema_for_tipo(tipo: str) -> dict:
    """Return the JSON Schema for a given tipo, augmented with x-widget extensions."""
    from src.config.models import ReportConfig
    schema = ReportConfig.model_json_schema()
    return _augment_schema(schema, tipo)


def _augment_schema(schema: dict, tipo: str) -> dict:
    """Inject x-widget extensions into the schema for known field paths.

    Walks every $defs entry so widgets land on whatever model declares the
    field — sucursales/supervisores live on ReportFilters, fechas on GlobalFilters.
    """
    widget_map = {
        "fecha_desde": "date",
        "fecha_hasta": "date",
        "archivo_plantilla": "filepath",
        "detalle_movimientos_path": "filepath",
        "sucursales": "sucursal-select-array",
        "genericos": "generico-select-array",
        "supervisores": "supervisor-matrix",
    }

    defs = schema.get("$defs", {})
    for model_def in defs.values():
        props = model_def.get("properties", {}) if isinstance(model_def, dict) else {}
        for field_name, widget in widget_map.items():
            if field_name in props:
                props[field_name]["x-widget"] = widget
        if tipo == "champions-league" and "categorias" in props:
            props["categorias"]["x-widget"] = "json-editor"

    return schema


# ---------------------------------------------------------------------------
# GET /mgmt/configs — list all configs
# ---------------------------------------------------------------------------


@router.get("/configs")
def list_configs():
    """Return all .json files in the configs directory."""
    configs_dir = _get_configs_dir()
    results = []
    for path in sorted(configs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tipo = data.get("tipo", "unknown")
        except Exception:
            tipo = "unknown"
        results.append({
            "filename": path.name,
            "tipo": tipo,
            "mtime": _mtime_iso(path),
        })
    return results


# ---------------------------------------------------------------------------
# GET /mgmt/configs/schema/{tipo} — JSON Schema for a tipo
# NOTE: Must be defined BEFORE /mgmt/configs/{filename} to avoid route conflict
# ---------------------------------------------------------------------------


@router.get("/configs/schema/{tipo}")
def get_config_schema(tipo: str):
    """Return the augmented JSON Schema for a given tipo."""
    return _get_schema_for_tipo(tipo)


# ---------------------------------------------------------------------------
# GET /mgmt/configs/path-exists — check if a path exists
# ---------------------------------------------------------------------------


@router.get("/configs/path-exists")
def path_exists(path: str):
    """Check whether a filesystem path exists."""
    p = Path(path)
    exists = p.exists()
    return {
        "exists": exists,
        "is_file": p.is_file() if exists else False,
    }


# ---------------------------------------------------------------------------
# GET /mgmt/configs/{filename} — get config content + schema
# ---------------------------------------------------------------------------


@router.get("/configs/{filename}")
def get_config(filename: str):
    """Return the config JSON content and its resolved JSON Schema."""
    content = _read_config(filename)
    tipo = content.get("tipo", "ventas")
    schema = _get_schema_for_tipo(tipo)
    return {"content": content, "schema": schema}


# ---------------------------------------------------------------------------
# PUT /mgmt/configs/{filename} — validate + atomic write
# ---------------------------------------------------------------------------


@router.put("/configs/{filename}")
def put_config(filename: str, body: dict):
    """Validate and atomically write a config file."""
    from src.config.models import ReportConfig

    try:
        validated = ReportConfig.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[
                {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
                for err in exc.errors()
            ],
        )

    # Extra validation: archivo_plantilla must exist if provided
    archivo = getattr(validated.filtros, "archivo_plantilla", None)
    if archivo:
        p = Path(archivo)
        if not p.exists() or not p.is_file() or p.suffix.lower() != ".xlsx":
            raise HTTPException(
                status_code=422,
                detail=[{
                    "loc": ["filtros", "archivo_plantilla"],
                    "msg": "file must exist and be a .xlsx file",
                    "type": "value_error.path",
                }],
            )

    _write_config_atomic(filename, body)

    path = _get_configs_dir() / filename
    return {"filename": filename, "mtime": _mtime_iso(path)}


# ---------------------------------------------------------------------------
# Reference data endpoints
# ---------------------------------------------------------------------------


@router.get("/refs/sucursales")
def get_sucursales():
    """Return list of sucursal names from configs."""
    sucursales: set[str] = set()
    for path in _get_configs_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            filtros = data.get("filtros", {})
            for s in filtros.get("sucursales", []):
                sucursales.add(s)
            # Also from supervisores values
            supervisores = filtros.get("supervisores", {})
            if isinstance(supervisores, dict):
                for s_list in supervisores.values():
                    sucursales.update(s_list)
        except Exception:
            pass
    return sorted(sucursales) if sucursales else ["CASA CENTRAL", "SUCURSAL CAFAYATE"]


@router.get("/refs/genericos")
def get_genericos():
    """Return list of genericos from configs."""
    genericos: set[str] = set()
    for path in _get_configs_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            filtros = data.get("filtros", {})
            for g in filtros.get("genericos", []):
                genericos.add(g)
        except Exception:
            pass
    return sorted(genericos) if genericos else ["CERVEZAS", "AGUAS DANONE"]


@router.get("/refs/supervisores")
def get_supervisores():
    """Return list of supervisor names from configs."""
    supervisores: set[str] = set()
    for path in _get_configs_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            filtros = data.get("filtros", {})
            sup_dict = filtros.get("supervisores", {})
            if isinstance(sup_dict, dict):
                supervisores.update(sup_dict.keys())
            elif isinstance(sup_dict, list):
                supervisores.update(sup_dict)
        except Exception:
            pass
    return sorted(supervisores)


# ---------------------------------------------------------------------------
# Contactos endpoints
# ---------------------------------------------------------------------------


@router.get("/contactos")
def get_contactos():
    """Return contents of contactos.json."""
    path = _get_configs_dir() / "contactos.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@router.put("/contactos")
def put_contactos(body: dict):
    """Write contactos.json atomically."""
    path = _get_configs_dir() / "contactos.json"
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, path)
    return {"status": "ok", "mtime": _mtime_iso(path)}
