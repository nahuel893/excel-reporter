"""bd_agent/conversation/system_prompt.py — System prompt builder.

build_system_prompt() assembles the full system prompt from:
  - Identity declaration
  - Contact metadata (name + permissions)
  - Gold schema documentation
  - Available tool specs
  - Operating constraints

Design:
    - schema_doc is passed explicitly; no file I/O inside the function itself.
    - schema_doc_loader is an optional callable used when schema_doc is None
      (enables lazy loading and caching at call site).
    - Default loader (default_schema_doc_loader) reads CONTEXT_DATABASE.md
      from the project root; it is module-level so callers can replace it.
    - Zero imports from src.* (RF-070).
"""
from __future__ import annotations

import pathlib
from typing import Callable

from bd_agent.contracts import Contact

# ---------------------------------------------------------------------------
# Default schema loader — reads CONTEXT_DATABASE.md relative to project root.
# The root is located by walking up from this file's location.
# ---------------------------------------------------------------------------

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent


def default_schema_doc_loader() -> str:
    """Read CONTEXT_DATABASE.md from the project root.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    doc_path = _PROJECT_ROOT / "CONTEXT_DATABASE.md"
    return doc_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_TEMPLATE = """\
Sos el "Asistente de Análisis de Datos de Badie".
Tu rol: responder preguntas sobre la base de datos del data warehouse (schema gold) usando las herramientas disponibles.

Información del usuario actual:
- Nombre: {contact_name}
- Permisos: {permissions}

Esquema de datos disponible:
{schema_doc}

Herramientas disponibles:
{tool_specs}

Reglas:
- Usá las herramientas parametrizadas (get_ventas_cliente, etc.) cuando sea posible.
- Solo recurrí a run_sql_select si ninguna herramienta parametrizada cubre la pregunta.
- Toda consulta es SELECT-only sobre el schema gold.
- Si la pregunta está fuera de tu alcance (datos no en gold, info personal, etc.), aclaralo claramente y no intentes responderla.
- Respondé en español rioplatense, breve y directo.
- Si una herramienta falla, explicale al usuario qué pasó sin volcar errores técnicos.
"""


def build_system_prompt(
    schema_doc: str | None,
    tool_specs: str,
    contact: Contact,
    schema_doc_loader: Callable[[], str] | None = default_schema_doc_loader,
) -> str:
    """Build the system prompt for the BD Agent.

    Args:
        schema_doc: The gold schema documentation text.  If None, schema_doc_loader
            is called to fetch it.
        tool_specs: Human-readable description of available tools (one per line).
        contact: The Contact for whom this conversation is happening.
        schema_doc_loader: Callable that returns schema_doc when schema_doc is
            None.  Pass None explicitly to disable — a ValueError will be raised
            if schema_doc is also None.

    Returns:
        The fully assembled system prompt string.

    Raises:
        ValueError: If both schema_doc and schema_doc_loader are None.
    """
    if schema_doc is None:
        if schema_doc_loader is None:
            raise ValueError(
                "Either schema_doc or schema_doc_loader must be provided."
            )
        schema_doc = schema_doc_loader()

    permissions_str = ", ".join(contact.permissions) if contact.permissions else "(ninguno)"

    return _TEMPLATE.format(
        contact_name=contact.name,
        permissions=permissions_str,
        schema_doc=schema_doc,
        tool_specs=tool_specs,
    )
