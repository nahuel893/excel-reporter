"""bd_agent/tools/curated.py — 5 parameterized curated tools (RF-020).

Each tool:
1. Validates its parameters before touching the DB.
2. Calls DatabaseGateway.execute_select (never builds raw SQL — delegates to gateway).
3. Returns at most 500 rows (RF-063).
4. Returns a structured ToolResult:
   - Success: {rows: [...], row_count: int, truncated: bool}
   - Failure: {error: "invalid_parameter", field: "...", message: "..."} (is_error=True)

Tools:
- get_ventas_cliente(id_cliente, periodo)            — periodo YYYY-MM
- get_clientes_sucursal(id_sucursal)
- get_articulos_generico(generico)
- get_cobertura_periodo(periodo, sucursales=None)    — periodo YYYY-MM
- get_ventas_articulo(id_articulo, fecha_desde, fecha_hasta) — dates YYYY-MM-DD

Handlers follow the registry calling convention:
    handler(gateway: DatabaseGateway, **kwargs) -> dict

Use register_all_into(registry) to register all 5 tools.

Zero imports from src.* (RF-070). Deps: stdlib + bd_agent.contracts.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bd_agent.contracts import DatabaseGateway, ToolResult

_MAX_ROWS = 500

# Regex patterns for parameter validation
_PERIODO_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")  # YYYY-MM
_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")  # YYYY-MM-DD


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ok(rows: list[dict]) -> ToolResult:
    """Build a successful ToolResult from a list of rows."""
    payload = json.dumps(
        {
            "rows": rows,
            "row_count": len(rows),
            "truncated": len(rows) >= _MAX_ROWS,
        }
    )
    return ToolResult(call_id="", name="", content=payload, is_error=False)


def _param_error(field: str, message: str) -> ToolResult:
    """Build an invalid_parameter error ToolResult."""
    payload = json.dumps(
        {
            "error": "invalid_parameter",
            "field": field,
            "message": message,
        }
    )
    return ToolResult(call_id="", name="", content=payload, is_error=True)


def _exec_error(tool_name: str, exc: Exception) -> ToolResult:
    """Build a tool_execution_error ToolResult from a caught exception."""
    payload = json.dumps(
        {
            "error": "tool_execution_error",
            "tool": tool_name,
            "message": str(exc),
        }
    )
    return ToolResult(call_id="", name=tool_name, content=payload, is_error=True)


def _validate_periodo(periodo: str, field: str = "periodo") -> ToolResult | None:
    """Return None if valid, or a param error ToolResult if invalid."""
    if not isinstance(periodo, str) or not _PERIODO_RE.match(periodo):
        return _param_error(
            field,
            f"'{periodo}' is not a valid period. Expected format: YYYY-MM (e.g. '2026-03').",
        )
    return None


def _validate_date(value: str, field: str) -> ToolResult | None:
    """Return None if valid YYYY-MM-DD date, or a param error ToolResult."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return _param_error(
            field,
            f"'{value}' is not a valid date. Expected format: YYYY-MM-DD (e.g. '2026-03-01').",
        )
    # Additional sanity check via date parsing
    try:
        date.fromisoformat(value)
    except ValueError:
        return _param_error(field, f"'{value}' is not a real calendar date.")
    return None


# ---------------------------------------------------------------------------
# Tool: get_ventas_cliente
# ---------------------------------------------------------------------------


def get_ventas_cliente(
    gateway: DatabaseGateway,
    id_cliente: int,
    periodo: str,
) -> ToolResult:
    """Fetch sales for a specific client in a period.

    Args:
        gateway: DatabaseGateway instance.
        id_cliente: Client ID (positive integer).
        periodo: Period in YYYY-MM format.

    Returns:
        ToolResult with rows or error payload.
    """
    err = _validate_periodo(periodo)
    if err:
        return err

    try:
        rows = gateway.execute_select(
            query="get_ventas_cliente",
            params={"id_cliente": id_cliente, "periodo": periodo},
            max_rows=_MAX_ROWS,
        )
    except Exception as exc:  # noqa: BLE001
        return _exec_error("get_ventas_cliente", exc)

    return _ok(rows)


def _handler_ventas_cliente(gateway: DatabaseGateway, **kwargs: Any) -> dict[str, Any]:
    id_cliente = kwargs["id_cliente"]
    periodo = kwargs["periodo"]
    result = get_ventas_cliente(gateway, id_cliente=id_cliente, periodo=periodo)
    payload = json.loads(result.content)
    if result.is_error:
        raise ValueError(json.dumps(payload))
    return payload


# ---------------------------------------------------------------------------
# Tool: get_clientes_sucursal
# ---------------------------------------------------------------------------


def get_clientes_sucursal(
    gateway: DatabaseGateway,
    id_sucursal: int,
) -> ToolResult:
    """Fetch the list of clients for a given branch.

    Args:
        gateway: DatabaseGateway instance.
        id_sucursal: Branch ID (positive integer, >= 1).

    Returns:
        ToolResult with rows or error payload.
    """
    if not isinstance(id_sucursal, int) or id_sucursal < 1:
        return _param_error(
            "id_sucursal",
            f"'{id_sucursal}' is not a valid branch ID. Must be a positive integer.",
        )

    try:
        rows = gateway.execute_select(
            query="get_clientes_sucursal",
            params={"id_sucursal": id_sucursal},
            max_rows=_MAX_ROWS,
        )
    except Exception as exc:  # noqa: BLE001
        return _exec_error("get_clientes_sucursal", exc)

    return _ok(rows)


def _handler_clientes_sucursal(gateway: DatabaseGateway, **kwargs: Any) -> dict[str, Any]:
    id_sucursal = kwargs["id_sucursal"]
    result = get_clientes_sucursal(gateway, id_sucursal=id_sucursal)
    payload = json.loads(result.content)
    if result.is_error:
        raise ValueError(json.dumps(payload))
    return payload


# ---------------------------------------------------------------------------
# Tool: get_articulos_generico
# ---------------------------------------------------------------------------


def get_articulos_generico(
    gateway: DatabaseGateway,
    generico: str,
) -> ToolResult:
    """Fetch articles belonging to a product generic.

    Args:
        gateway: DatabaseGateway instance.
        generico: Generic name (non-empty string, e.g. 'CERVEZAS').

    Returns:
        ToolResult with rows or error payload.
    """
    if not isinstance(generico, str) or not generico.strip():
        return _param_error(
            "generico",
            "Generic name must be a non-empty string (e.g. 'CERVEZAS').",
        )

    try:
        rows = gateway.execute_select(
            query="get_articulos_generico",
            params={"generico": generico.strip()},
            max_rows=_MAX_ROWS,
        )
    except Exception as exc:  # noqa: BLE001
        return _exec_error("get_articulos_generico", exc)

    return _ok(rows)


def _handler_articulos_generico(gateway: DatabaseGateway, **kwargs: Any) -> dict[str, Any]:
    generico = kwargs["generico"]
    result = get_articulos_generico(gateway, generico=generico)
    payload = json.loads(result.content)
    if result.is_error:
        raise ValueError(json.dumps(payload))
    return payload


# ---------------------------------------------------------------------------
# Tool: get_cobertura_periodo
# ---------------------------------------------------------------------------


def get_cobertura_periodo(
    gateway: DatabaseGateway,
    periodo: str,
    sucursales: list[str] | None = None,
) -> ToolResult:
    """Fetch coverage for a period, optionally filtered by branch list.

    Args:
        gateway: DatabaseGateway instance.
        periodo: Period in YYYY-MM format.
        sucursales: Optional list of branch names to filter results.

    Returns:
        ToolResult with rows or error payload.
    """
    err = _validate_periodo(periodo)
    if err:
        return err

    params: dict[str, Any] = {"periodo": periodo}
    if sucursales is not None:
        params["sucursales"] = sucursales

    try:
        rows = gateway.execute_select(
            query="get_cobertura_periodo",
            params=params,
            max_rows=_MAX_ROWS,
        )
    except Exception as exc:  # noqa: BLE001
        return _exec_error("get_cobertura_periodo", exc)

    return _ok(rows)


def _handler_cobertura_periodo(gateway: DatabaseGateway, **kwargs: Any) -> dict[str, Any]:
    periodo = kwargs["periodo"]
    sucursales = kwargs.get("sucursales")
    result = get_cobertura_periodo(gateway, periodo=periodo, sucursales=sucursales)
    payload = json.loads(result.content)
    if result.is_error:
        raise ValueError(json.dumps(payload))
    return payload


# ---------------------------------------------------------------------------
# Tool: get_ventas_articulo
# ---------------------------------------------------------------------------


def get_ventas_articulo(
    gateway: DatabaseGateway,
    id_articulo: int,
    fecha_desde: str,
    fecha_hasta: str,
) -> ToolResult:
    """Fetch article-level sales between two dates.

    Args:
        gateway: DatabaseGateway instance.
        id_articulo: Article ID (integer).
        fecha_desde: Start date in YYYY-MM-DD format (inclusive).
        fecha_hasta: End date in YYYY-MM-DD format (inclusive).

    Returns:
        ToolResult with rows or error payload.
    """
    err = _validate_date(fecha_desde, "fecha_desde")
    if err:
        return err

    err = _validate_date(fecha_hasta, "fecha_hasta")
    if err:
        return err

    # fecha_desde must not be after fecha_hasta
    if fecha_desde > fecha_hasta:
        return _param_error(
            "fecha_desde",
            f"fecha_desde '{fecha_desde}' must not be after fecha_hasta '{fecha_hasta}'.",
        )

    try:
        rows = gateway.execute_select(
            query="get_ventas_articulo",
            params={
                "id_articulo": id_articulo,
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
            },
            max_rows=_MAX_ROWS,
        )
    except Exception as exc:  # noqa: BLE001
        return _exec_error("get_ventas_articulo", exc)

    return _ok(rows)


def _handler_ventas_articulo(gateway: DatabaseGateway, **kwargs: Any) -> dict[str, Any]:
    id_articulo = kwargs["id_articulo"]
    fecha_desde = kwargs["fecha_desde"]
    fecha_hasta = kwargs["fecha_hasta"]
    result = get_ventas_articulo(
        gateway,
        id_articulo=id_articulo,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    payload = json.loads(result.content)
    if result.is_error:
        raise ValueError(json.dumps(payload))
    return payload


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_all_into(registry) -> None:  # type: ignore[type-arg]
    """Register all 5 curated tools into a ToolRegistry.

    Args:
        registry: ToolRegistry instance.
    """
    registry.register(
        name="get_ventas_cliente",
        description=(
            "Trae las ventas de un cliente para un periodo. "
            "Retorna hasta 500 filas con totales por periodo."
        ),
        params_schema={
            "type": "object",
            "properties": {
                "id_cliente": {
                    "type": "integer",
                    "description": "ID numérico del cliente.",
                },
                "periodo": {
                    "type": "string",
                    "description": "Periodo en formato YYYY-MM (ej. '2026-03').",
                },
            },
            "required": ["id_cliente", "periodo"],
        },
        handler=_handler_ventas_cliente,
    )

    registry.register(
        name="get_clientes_sucursal",
        description=(
            "Lista los clientes activos de una sucursal. "
            "Retorna hasta 500 filas con ID, razón social y datos del cliente."
        ),
        params_schema={
            "type": "object",
            "properties": {
                "id_sucursal": {
                    "type": "integer",
                    "description": "ID numérico de la sucursal (entero positivo).",
                },
            },
            "required": ["id_sucursal"],
        },
        handler=_handler_clientes_sucursal,
    )

    registry.register(
        name="get_articulos_generico",
        description=(
            "Lista los artículos que pertenecen a un genérico. "
            "Retorna hasta 500 filas con ID, descripción y unidad de medida."
        ),
        params_schema={
            "type": "object",
            "properties": {
                "generico": {
                    "type": "string",
                    "description": "Nombre del genérico en mayúsculas (ej. 'CERVEZAS').",
                },
            },
            "required": ["generico"],
        },
        handler=_handler_articulos_generico,
    )

    registry.register(
        name="get_cobertura_periodo",
        description=(
            "Trae la cobertura de ventas para un periodo, opcionalmente filtrada por sucursales. "
            "Retorna hasta 500 filas con cobertura por sucursal y genérico."
        ),
        params_schema={
            "type": "object",
            "properties": {
                "periodo": {
                    "type": "string",
                    "description": "Periodo en formato YYYY-MM (ej. '2026-03').",
                },
                "sucursales": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Lista opcional de nombres de sucursales para filtrar. "
                        "Si se omite, retorna todas las sucursales."
                    ),
                },
            },
            "required": ["periodo"],
        },
        handler=_handler_cobertura_periodo,
    )

    registry.register(
        name="get_ventas_articulo",
        description=(
            "Trae las ventas de un artículo entre dos fechas. "
            "Retorna hasta 500 filas con cantidad y monto por día."
        ),
        params_schema={
            "type": "object",
            "properties": {
                "id_articulo": {
                    "type": "integer",
                    "description": "ID numérico del artículo.",
                },
                "fecha_desde": {
                    "type": "string",
                    "description": "Fecha de inicio en formato YYYY-MM-DD (ej. '2026-03-01').",
                },
                "fecha_hasta": {
                    "type": "string",
                    "description": "Fecha de fin en formato YYYY-MM-DD (ej. '2026-03-31').",
                },
            },
            "required": ["id_articulo", "fecha_desde", "fecha_hasta"],
        },
        handler=_handler_ventas_articulo,
    )
