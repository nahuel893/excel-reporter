"""T-032: Tests for bd_agent/tools/curated.py — 5 parameterized curated tools.

TDD cycle: RED first (curated.py does not exist) -> GREEN -> REFACTOR.

Tools:
- get_ventas_cliente(id_cliente, periodo)         — periodo YYYY-MM
- get_clientes_sucursal(id_sucursal)
- get_articulos_generico(generico)
- get_cobertura_periodo(periodo, sucursales=None) — periodo YYYY-MM
- get_ventas_articulo(id_articulo, fecha_desde, fecha_hasta) — dates YYYY-MM-DD

Each test verifies:
1. Tool calls DatabaseGateway with valid args and returns rows via ToolResult
2. Tool validates params and returns error ToolResult (is_error=True) on bad args
3. All 5 tools are registered via register_all_into(registry)
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from bd_agent.contracts import ToolCall, ToolResult


# ---------------------------------------------------------------------------
# Fake DatabaseGateway
# ---------------------------------------------------------------------------


class FakeGateway:
    def __init__(self, rows: list[dict] | None = None, raises: Exception | None = None):
        self._rows = rows or []
        self._raises = raises
        self.calls: list[dict] = []

    def execute_select(self, query: str, params: dict[str, Any], max_rows: int) -> list[dict]:
        self.calls.append({"query": query, "params": params, "max_rows": max_rows})
        if self._raises:
            raise self._raises
        return self._rows

    def get_schema_doc(self) -> str:
        return "fake schema"


# ---------------------------------------------------------------------------
# Import guard — RED phase
# ---------------------------------------------------------------------------


def test_curated_module_importable():
    from bd_agent.tools.curated import (  # noqa: F401
        get_ventas_cliente,
        get_clientes_sucursal,
        get_articulos_generico,
        get_cobertura_periodo,
        get_ventas_articulo,
        register_all_into,
    )


# ---------------------------------------------------------------------------
# Helper: build ToolCall + invoke via registry
# ---------------------------------------------------------------------------


def _make_registry_with_all():
    from bd_agent.tools.registry import ToolRegistry
    from bd_agent.tools.curated import register_all_into

    registry = ToolRegistry()
    register_all_into(registry)
    return registry


# ---------------------------------------------------------------------------
# get_ventas_cliente
# ---------------------------------------------------------------------------


class TestGetVentasCliente:
    def test_valid_args_returns_rows(self):
        from bd_agent.tools.curated import get_ventas_cliente

        rows = [{"id_cliente": 1, "total": 5000}]
        gateway = FakeGateway(rows=rows)
        result = get_ventas_cliente(gateway, id_cliente=1, periodo="2026-03")
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        payload = json.loads(result.content)
        assert payload["rows"] == rows

    def test_invalid_periodo_format_returns_error(self):
        from bd_agent.tools.curated import get_ventas_cliente

        gateway = FakeGateway(rows=[])
        result = get_ventas_cliente(gateway, id_cliente=1, periodo="march")
        assert result.is_error is True
        payload = json.loads(result.content)
        assert payload["error"] == "invalid_parameter"
        assert payload["field"] == "periodo"

    def test_gateway_not_called_on_invalid_params(self):
        from bd_agent.tools.curated import get_ventas_cliente

        gateway = FakeGateway(rows=[])
        get_ventas_cliente(gateway, id_cliente=1, periodo="bad")
        assert len(gateway.calls) == 0

    def test_max_rows_respected(self):
        from bd_agent.tools.curated import get_ventas_cliente

        gateway = FakeGateway(rows=[{"x": i} for i in range(500)])
        result = get_ventas_cliente(gateway, id_cliente=1, periodo="2026-03")
        assert gateway.calls[0]["max_rows"] == 500
        payload = json.loads(result.content)
        assert payload["truncated"] is True

    def test_via_registry(self):
        registry = _make_registry_with_all()
        gateway = FakeGateway(rows=[{"total": 1234}])
        call = ToolCall(
            id="c1",
            name="get_ventas_cliente",
            arguments={"id_cliente": 7, "periodo": "2026-01"},
        )
        result = registry.invoke(call, gateway=gateway)
        assert result.is_error is False


# ---------------------------------------------------------------------------
# get_clientes_sucursal
# ---------------------------------------------------------------------------


class TestGetClientesSucursal:
    def test_valid_args_returns_rows(self):
        from bd_agent.tools.curated import get_clientes_sucursal

        rows = [{"id_cliente": 5, "fantasia": "Bar El Sol"}]
        gateway = FakeGateway(rows=rows)
        result = get_clientes_sucursal(gateway, id_sucursal=3)
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        payload = json.loads(result.content)
        assert payload["rows"] == rows

    def test_missing_id_sucursal_returns_error(self):
        from bd_agent.tools.curated import get_clientes_sucursal

        gateway = FakeGateway(rows=[])
        # id_sucursal must be a positive integer
        result = get_clientes_sucursal(gateway, id_sucursal=0)
        assert result.is_error is True
        payload = json.loads(result.content)
        assert payload["error"] == "invalid_parameter"
        assert payload["field"] == "id_sucursal"

    def test_via_registry(self):
        registry = _make_registry_with_all()
        gateway = FakeGateway(rows=[{"id_cliente": 1}])
        call = ToolCall(
            id="c2",
            name="get_clientes_sucursal",
            arguments={"id_sucursal": 2},
        )
        result = registry.invoke(call, gateway=gateway)
        assert result.is_error is False


# ---------------------------------------------------------------------------
# get_articulos_generico
# ---------------------------------------------------------------------------


class TestGetArticulosGenerico:
    def test_valid_args_returns_rows(self):
        from bd_agent.tools.curated import get_articulos_generico

        rows = [{"id_articulo": 10, "descripcion": "Corona 710ml"}]
        gateway = FakeGateway(rows=rows)
        result = get_articulos_generico(gateway, generico="CERVEZAS")
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        payload = json.loads(result.content)
        assert payload["rows"] == rows

    def test_empty_generico_returns_error(self):
        from bd_agent.tools.curated import get_articulos_generico

        gateway = FakeGateway(rows=[])
        result = get_articulos_generico(gateway, generico="")
        assert result.is_error is True
        payload = json.loads(result.content)
        assert payload["error"] == "invalid_parameter"
        assert payload["field"] == "generico"

    def test_via_registry(self):
        registry = _make_registry_with_all()
        gateway = FakeGateway(rows=[{"id_articulo": 1}])
        call = ToolCall(
            id="c3",
            name="get_articulos_generico",
            arguments={"generico": "AGUAS"},
        )
        result = registry.invoke(call, gateway=gateway)
        assert result.is_error is False


# ---------------------------------------------------------------------------
# get_cobertura_periodo
# ---------------------------------------------------------------------------


class TestGetCoberturaPeriodo:
    def test_valid_args_no_sucursales_returns_rows(self):
        from bd_agent.tools.curated import get_cobertura_periodo

        rows = [{"sucursal": "CASA CENTRAL", "cobertura": 0.87}]
        gateway = FakeGateway(rows=rows)
        result = get_cobertura_periodo(gateway, periodo="2026-03")
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        payload = json.loads(result.content)
        assert payload["rows"] == rows

    def test_valid_args_with_sucursales_filter(self):
        from bd_agent.tools.curated import get_cobertura_periodo

        rows = [{"sucursal": "CASA CENTRAL", "cobertura": 0.90}]
        gateway = FakeGateway(rows=rows)
        result = get_cobertura_periodo(
            gateway, periodo="2026-03", sucursales=["CASA CENTRAL", "CAFAYATE"]
        )
        assert result.is_error is False

    def test_invalid_periodo_format_returns_error(self):
        from bd_agent.tools.curated import get_cobertura_periodo

        gateway = FakeGateway(rows=[])
        result = get_cobertura_periodo(gateway, periodo="march-2026")
        assert result.is_error is True
        payload = json.loads(result.content)
        assert payload["error"] == "invalid_parameter"
        assert payload["field"] == "periodo"

    def test_via_registry(self):
        registry = _make_registry_with_all()
        gateway = FakeGateway(rows=[{"cobertura": 0.75}])
        call = ToolCall(
            id="c4",
            name="get_cobertura_periodo",
            arguments={"periodo": "2026-03"},
        )
        result = registry.invoke(call, gateway=gateway)
        assert result.is_error is False

    def test_via_registry_with_sucursales(self):
        registry = _make_registry_with_all()
        gateway = FakeGateway(rows=[{"cobertura": 0.80}])
        call = ToolCall(
            id="c4b",
            name="get_cobertura_periodo",
            arguments={"periodo": "2026-03", "sucursales": ["CASA CENTRAL"]},
        )
        result = registry.invoke(call, gateway=gateway)
        assert result.is_error is False


# ---------------------------------------------------------------------------
# get_ventas_articulo
# ---------------------------------------------------------------------------


class TestGetVentasArticulo:
    def test_valid_args_returns_rows(self):
        from bd_agent.tools.curated import get_ventas_articulo

        rows = [{"fecha": "2026-03-01", "cantidad": 50}]
        gateway = FakeGateway(rows=rows)
        result = get_ventas_articulo(
            gateway,
            id_articulo=42,
            fecha_desde="2026-03-01",
            fecha_hasta="2026-03-31",
        )
        assert isinstance(result, ToolResult)
        assert result.is_error is False
        payload = json.loads(result.content)
        assert payload["rows"] == rows

    def test_invalid_fecha_desde_format_returns_error(self):
        from bd_agent.tools.curated import get_ventas_articulo

        gateway = FakeGateway(rows=[])
        result = get_ventas_articulo(
            gateway, id_articulo=1, fecha_desde="01-03-2026", fecha_hasta="2026-03-31"
        )
        assert result.is_error is True
        payload = json.loads(result.content)
        assert payload["error"] == "invalid_parameter"
        assert payload["field"] == "fecha_desde"

    def test_invalid_fecha_hasta_format_returns_error(self):
        from bd_agent.tools.curated import get_ventas_articulo

        gateway = FakeGateway(rows=[])
        result = get_ventas_articulo(
            gateway, id_articulo=1, fecha_desde="2026-03-01", fecha_hasta="not-a-date"
        )
        assert result.is_error is True
        payload = json.loads(result.content)
        assert payload["error"] == "invalid_parameter"
        assert payload["field"] == "fecha_hasta"

    def test_fecha_desde_after_fecha_hasta_returns_error(self):
        from bd_agent.tools.curated import get_ventas_articulo

        gateway = FakeGateway(rows=[])
        result = get_ventas_articulo(
            gateway, id_articulo=1, fecha_desde="2026-04-01", fecha_hasta="2026-03-01"
        )
        assert result.is_error is True
        payload = json.loads(result.content)
        assert payload["error"] == "invalid_parameter"

    def test_via_registry(self):
        registry = _make_registry_with_all()
        gateway = FakeGateway(rows=[{"total": 100}])
        call = ToolCall(
            id="c5",
            name="get_ventas_articulo",
            arguments={
                "id_articulo": 10,
                "fecha_desde": "2026-03-01",
                "fecha_hasta": "2026-03-31",
            },
        )
        result = registry.invoke(call, gateway=gateway)
        assert result.is_error is False


# ---------------------------------------------------------------------------
# All 5 tools registered
# ---------------------------------------------------------------------------


class TestAllToolsRegistered:
    def test_register_all_into_registers_5_tools(self):
        from bd_agent.tools.registry import ToolRegistry
        from bd_agent.tools.curated import register_all_into

        registry = ToolRegistry()
        register_all_into(registry)
        names = registry.list_names()
        assert "get_ventas_cliente" in names
        assert "get_clientes_sucursal" in names
        assert "get_articulos_generico" in names
        assert "get_cobertura_periodo" in names
        assert "get_ventas_articulo" in names
        assert len(names) == 5

    def test_gemini_declarations_include_all_5(self):
        from bd_agent.tools.registry import ToolRegistry
        from bd_agent.tools.curated import register_all_into

        registry = ToolRegistry()
        register_all_into(registry)
        decls = registry.gemini_function_declarations()
        assert len(decls) == 5
        decl_names = {d["name"] for d in decls}
        assert decl_names == {
            "get_ventas_cliente",
            "get_clientes_sucursal",
            "get_articulos_generico",
            "get_cobertura_periodo",
            "get_ventas_articulo",
        }

    def test_each_declaration_has_required_gemini_fields(self):
        from bd_agent.tools.registry import ToolRegistry
        from bd_agent.tools.curated import register_all_into

        registry = ToolRegistry()
        register_all_into(registry)
        for decl in registry.gemini_function_declarations():
            assert "name" in decl, f"Missing 'name' in {decl}"
            assert "description" in decl, f"Missing 'description' in {decl}"
            assert "parameters" in decl, f"Missing 'parameters' in {decl}"
            params = decl["parameters"]
            assert params.get("type") == "object", f"parameters.type must be 'object' in {decl}"
            assert "properties" in params, f"Missing 'properties' in {decl}"
