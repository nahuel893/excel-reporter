"""bd_agent/tools/registry.py — ToolRegistry and Gemini function declaration emitter.

Provides:
- Tool dataclass: name, description, params_schema, handler
- ToolRegistry: register, invoke, list_names, gemini_function_declarations
- to_gemini_function_declarations(tools): free function for external callers

Tool handlers have the signature:
    handler(gateway: DatabaseGateway | None, **kwargs) -> dict

ToolRegistry.invoke wraps exceptions in a structured ToolResult(is_error=True).

Zero imports from src.* (RF-070). Deps: stdlib + bd_agent.contracts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from bd_agent.contracts import DatabaseGateway, ToolCall, ToolResult


@dataclass
class Tool:
    """Registered tool descriptor.

    Attributes:
        name: Unique tool name; must match Gemini function declaration name.
        description: Human-readable description; used in Gemini function decl.
        params_schema: JSON-Schema-like dict for the ``parameters`` field in
            the Gemini function declaration.  Must have ``type == "object"``.
        handler: callable(gateway, **kwargs) -> dict.  The registry passes the
            DatabaseGateway as the first positional argument and expands tool
            arguments as keyword arguments.
    """

    name: str
    description: str
    params_schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]


def to_gemini_function_declarations(tools: list[Tool]) -> list[dict]:
    """Convert a list of Tool objects to Gemini API function declarations.

    Each declaration follows the format expected by the Gemini ``tools``
    parameter::

        {
          "name": "...",
          "description": "...",
          "parameters": {
            "type": "object",
            "properties": {...},
            "required": [...]
          }
        }

    Args:
        tools: List of registered Tool objects.

    Returns:
        List of dicts, one per tool, in Gemini function-declaration format.
    """
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.params_schema,
        }
        for tool in tools
    ]


class ToolRegistry:
    """Registry for tools callable by the LLM.

    Usage::

        registry = ToolRegistry()
        registry.register(name="my_tool", description="...",
                          params_schema={...}, handler=my_fn)
        result = registry.invoke(tool_call, gateway=db_gateway)
        declarations = registry.gemini_function_declarations()
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        description: str,
        params_schema: dict[str, Any],
        handler: Callable[..., dict[str, Any]],
    ) -> None:
        """Register a new tool.

        Args:
            name: Unique tool name.
            description: Human-readable description.
            params_schema: JSON-Schema dict for the tool's parameters.
            handler: callable(gateway, **kwargs) -> dict.

        Raises:
            ValueError: if a tool with the same name is already registered.
        """
        if name in self._tools:
            raise ValueError(
                f"Tool '{name}' is already registered. "
                "Use a different name or create a new ToolRegistry."
            )
        self._tools[name] = Tool(
            name=name,
            description=description,
            params_schema=params_schema,
            handler=handler,
        )

    def list_names(self) -> list[str]:
        """Return a list of all registered tool names."""
        return list(self._tools.keys())

    # ------------------------------------------------------------------
    # Gemini function declarations
    # ------------------------------------------------------------------

    def gemini_function_declarations(self) -> list[dict]:
        """Emit Gemini-compatible function declarations for all registered tools."""
        return to_gemini_function_declarations(list(self._tools.values()))

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def invoke(
        self,
        call: ToolCall,
        gateway: DatabaseGateway | None,
    ) -> ToolResult:
        """Execute a tool call and return the result.

        If the tool is not registered, returns a ToolResult with is_error=True.
        If the handler raises any exception, catches it and returns a
        ToolResult with is_error=True (RF-022).

        Args:
            call: ToolCall emitted by the LLM.
            gateway: DatabaseGateway instance (or None for tools that don't
                need DB access).

        Returns:
            ToolResult with JSON-serialized content or error payload.
        """
        tool = self._tools.get(call.name)
        if tool is None:
            error_payload = json.dumps(
                {
                    "error": "tool_not_found",
                    "tool": call.name,
                    "message": f"No tool named '{call.name}' is registered.",
                }
            )
            return ToolResult(
                call_id=call.id,
                name=call.name,
                content=error_payload,
                is_error=True,
            )

        try:
            result = tool.handler(gateway, **call.arguments)
            return ToolResult(
                call_id=call.id,
                name=call.name,
                content=json.dumps(result),
                is_error=False,
            )
        except Exception as exc:  # noqa: BLE001
            error_payload = json.dumps(
                {
                    "error": "tool_execution_error",
                    "tool": call.name,
                    "message": str(exc),
                }
            )
            return ToolResult(
                call_id=call.id,
                name=call.name,
                content=error_payload,
                is_error=True,
            )
