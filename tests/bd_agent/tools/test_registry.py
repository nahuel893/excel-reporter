"""T-030: Tests for bd_agent/tools/registry.py — ToolRegistry.

TDD cycle: RED first (registry.py does not exist) -> GREEN -> REFACTOR.

Covers:
- Tool dataclass construction
- Registration and retrieval
- Gemini function declaration emission format
- Invocation with ToolCall -> ToolResult
- Error handling (tool raises exception -> ToolResult with is_error=True)
- Unknown tool -> ToolResult with is_error=True
"""
from __future__ import annotations

import json

import pytest

from bd_agent.contracts import ToolCall, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_echo_handler(prefix: str = "echo"):
    """Simple handler that echoes its args back as JSON."""

    def handler(gateway, **kwargs):
        return {"prefix": prefix, **kwargs}

    return handler


def _minimal_spec() -> dict:
    return {
        "name": "echo_tool",
        "description": "A simple echo tool for testing.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to echo"},
            },
            "required": ["message"],
        },
    }


# ---------------------------------------------------------------------------
# Import guard — RED phase: module does not exist yet
# ---------------------------------------------------------------------------


def test_registry_module_importable():
    """Registry module must be importable from bd_agent.tools.registry."""
    from bd_agent.tools.registry import ToolRegistry, Tool  # noqa: F401


def test_tool_dataclass_fields():
    """Tool dataclass must have name, description, params_schema, handler fields."""
    from bd_agent.tools.registry import Tool

    spec = _minimal_spec()
    handler = _make_echo_handler()
    tool = Tool(
        name=spec["name"],
        description=spec["description"],
        params_schema=spec["parameters"],
        handler=handler,
    )
    assert tool.name == "echo_tool"
    assert tool.description == "A simple echo tool for testing."
    assert tool.params_schema == spec["parameters"]
    assert tool.handler is handler


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_and_list(self):
        from bd_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        spec = _minimal_spec()
        registry.register(
            name=spec["name"],
            description=spec["description"],
            params_schema=spec["parameters"],
            handler=_make_echo_handler(),
        )
        assert "echo_tool" in registry.list_names()

    def test_register_multiple_tools(self):
        from bd_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        for i in range(3):
            spec = _minimal_spec()
            spec["name"] = f"tool_{i}"
            registry.register(
                name=spec["name"],
                description=spec["description"],
                params_schema=spec["parameters"],
                handler=_make_echo_handler(f"prefix_{i}"),
            )
        names = registry.list_names()
        assert len(names) == 3
        assert "tool_0" in names
        assert "tool_2" in names

    def test_register_duplicate_name_raises(self):
        """Registering the same name twice should raise ValueError."""
        from bd_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        spec = _minimal_spec()
        registry.register(
            name=spec["name"],
            description=spec["description"],
            params_schema=spec["parameters"],
            handler=_make_echo_handler(),
        )
        with pytest.raises(ValueError, match="already registered"):
            registry.register(
                name=spec["name"],
                description=spec["description"],
                params_schema=spec["parameters"],
                handler=_make_echo_handler(),
            )


# ---------------------------------------------------------------------------
# Gemini function declaration emission
# ---------------------------------------------------------------------------


class TestGeminiFunctionDeclarations:
    def test_single_tool_declaration_shape(self):
        from bd_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        spec = _minimal_spec()
        registry.register(
            name=spec["name"],
            description=spec["description"],
            params_schema=spec["parameters"],
            handler=_make_echo_handler(),
        )
        declarations = registry.gemini_function_declarations()
        assert len(declarations) == 1
        decl = declarations[0]
        # Must match Gemini API format
        assert decl["name"] == "echo_tool"
        assert decl["description"] == "A simple echo tool for testing."
        assert "parameters" in decl
        params = decl["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "message" in params["properties"]
        assert "required" in params

    def test_multiple_tools_declarations_ordered(self):
        from bd_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        for i in ["alpha", "beta", "gamma"]:
            spec = _minimal_spec()
            spec["name"] = i
            registry.register(
                name=spec["name"],
                description=spec["description"],
                params_schema=spec["parameters"],
                handler=_make_echo_handler(i),
            )
        declarations = registry.gemini_function_declarations()
        assert len(declarations) == 3
        names = [d["name"] for d in declarations]
        assert set(names) == {"alpha", "beta", "gamma"}

    def test_to_gemini_function_declarations_standalone(self):
        """The free function to_gemini_function_declarations must also work."""
        from bd_agent.tools.registry import to_gemini_function_declarations, Tool

        tools = [
            Tool(
                name="my_tool",
                description="Does something.",
                params_schema={
                    "type": "object",
                    "properties": {"x": {"type": "integer"}},
                    "required": ["x"],
                },
                handler=lambda gw, **kw: {},
            )
        ]
        decls = to_gemini_function_declarations(tools)
        assert len(decls) == 1
        assert decls[0]["name"] == "my_tool"
        assert decls[0]["parameters"]["properties"]["x"]["type"] == "integer"


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


class TestInvocation:
    def _registry_with_echo(self):
        from bd_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        spec = _minimal_spec()
        registry.register(
            name=spec["name"],
            description=spec["description"],
            params_schema=spec["parameters"],
            handler=_make_echo_handler("echo"),
        )
        return registry

    def test_invoke_known_tool_returns_tool_result(self):
        registry = self._registry_with_echo()
        call = ToolCall(id="call-1", name="echo_tool", arguments={"message": "hello"})
        result = registry.invoke(call, gateway=None)
        assert isinstance(result, ToolResult)
        assert result.call_id == "call-1"
        assert result.name == "echo_tool"
        assert result.is_error is False
        payload = json.loads(result.content)
        assert payload["message"] == "hello"
        assert payload["prefix"] == "echo"

    def test_invoke_unknown_tool_returns_error_result(self):
        registry = self._registry_with_echo()
        call = ToolCall(id="call-2", name="nonexistent_tool", arguments={})
        result = registry.invoke(call, gateway=None)
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert result.call_id == "call-2"
        assert "nonexistent_tool" in result.content

    def test_invoke_tool_exception_returns_error_result(self):
        from bd_agent.tools.registry import ToolRegistry

        def failing_handler(gateway, **kwargs):
            raise RuntimeError("DB exploded")

        registry = ToolRegistry()
        spec = _minimal_spec()
        registry.register(
            name=spec["name"],
            description=spec["description"],
            params_schema=spec["parameters"],
            handler=failing_handler,
        )
        call = ToolCall(id="call-3", name="echo_tool", arguments={"message": "boom"})
        result = registry.invoke(call, gateway=None)
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "tool_execution_error" in result.content

    def test_invoke_passes_gateway_to_handler(self):
        """Handler must receive the gateway object as first positional argument."""
        from bd_agent.tools.registry import ToolRegistry

        received_gateway = []

        def capturing_handler(gateway, **kwargs):
            received_gateway.append(gateway)
            return {"ok": True}

        registry = ToolRegistry()
        spec = _minimal_spec()
        registry.register(
            name=spec["name"],
            description=spec["description"],
            params_schema=spec["parameters"],
            handler=capturing_handler,
        )
        sentinel_gateway = object()
        call = ToolCall(id="call-4", name="echo_tool", arguments={"message": "x"})
        registry.invoke(call, gateway=sentinel_gateway)
        assert received_gateway == [sentinel_gateway]
