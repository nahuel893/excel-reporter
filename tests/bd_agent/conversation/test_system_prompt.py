"""tests/bd_agent/conversation/test_system_prompt.py

Tests for build_system_prompt (T-051).

Scenarios:
- contact name is included in prompt
- permissions are included
- schema_doc is included
- tool_specs are included
- identity string is present ("Asistente de Análisis de Datos de Badie")
- constraints section present (gold schema, parameterized first, SELECT-only, PII refusal)
- Rioplatense Spanish instruction present
- custom schema_doc_loader is used (not default file read)
- empty tool_specs renders gracefully
- default_schema_loader reads CONTEXT_DATABASE.md from project root
"""
from __future__ import annotations

import pytest

from bd_agent.contracts import Contact
from bd_agent.conversation.system_prompt import build_system_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contact(
    name: str = "Juan Pérez",
    jid: str = "5493874123456@s.whatsapp.net",
    daily_message_limit: int = 20,
    permissions: tuple = ("ventas", "clientes"),
) -> Contact:
    return Contact(
        name=name,
        jid=jid,
        daily_message_limit=daily_message_limit,
        permissions=permissions,
    )


_FAKE_SCHEMA = "## gold.fact_ventas\nColumnas: id_venta, fecha, monto\n"
_FAKE_TOOLS = "- get_ventas_cliente: devuelve ventas para un cliente"


def _fake_loader() -> str:
    return _FAKE_SCHEMA


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_identity_present():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
    )
    assert "Asistente de Análisis de Datos de Badie" in prompt


# ---------------------------------------------------------------------------
# Contact info
# ---------------------------------------------------------------------------


def test_contact_name_present():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(name="María García"),
    )
    assert "María García" in prompt


def test_permissions_present():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(permissions=("ventas", "cobertura")),
    )
    assert "ventas" in prompt
    assert "cobertura" in prompt


def test_empty_permissions_renders_gracefully():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(permissions=()),
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 0


# ---------------------------------------------------------------------------
# Schema doc
# ---------------------------------------------------------------------------


def test_schema_doc_included():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
    )
    assert "gold.fact_ventas" in prompt


def test_schema_doc_full_content_present():
    schema = "CUSTOM_SCHEMA_MARKER_XYZ123"
    prompt = build_system_prompt(
        schema_doc=schema,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
    )
    assert schema in prompt


# ---------------------------------------------------------------------------
# Tool specs
# ---------------------------------------------------------------------------


def test_tool_specs_included():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
    )
    assert "get_ventas_cliente" in prompt


def test_empty_tool_specs_renders_gracefully():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs="",
        contact=_contact(),
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 0


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


def test_gold_schema_only_constraint():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
    )
    assert "gold" in prompt


def test_select_only_constraint():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
    )
    assert "SELECT" in prompt


def test_parameterized_tools_first_constraint():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
    )
    # Should mention using parameterized tools before run_sql_select fallback
    assert "run_sql_select" in prompt


def test_rioplatense_spanish_instruction():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
    )
    # "español rioplatense" should appear in the prompt
    assert "rioplatense" in prompt.lower()


def test_pii_refusal_or_out_of_scope_instruction():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
    )
    # The prompt must mention that out-of-scope questions should be refused
    # Accept variations: "alcance", "fuera de", "scope", "no aplica"
    lower = prompt.lower()
    assert any(kw in lower for kw in ("alcance", "fuera de", "scope", "no aplica"))


# ---------------------------------------------------------------------------
# Schema doc loader (injectable)
# ---------------------------------------------------------------------------


def test_schema_doc_loader_called_when_schema_doc_is_none():
    """If schema_doc=None, build_system_prompt calls schema_doc_loader()."""
    prompt = build_system_prompt(
        schema_doc=None,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
        schema_doc_loader=_fake_loader,
    )
    assert "gold.fact_ventas" in prompt


def test_schema_doc_takes_priority_over_loader():
    """Explicit schema_doc overrides the loader."""
    explicit_schema = "EXPLICIT_SCHEMA_CONTENT"
    prompt = build_system_prompt(
        schema_doc=explicit_schema,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
        schema_doc_loader=_fake_loader,
    )
    assert explicit_schema in prompt
    assert "gold.fact_ventas" not in prompt


def test_missing_schema_doc_and_no_loader_raises():
    """When schema_doc=None and no loader, must raise ValueError."""
    with pytest.raises((ValueError, TypeError)):
        build_system_prompt(
            schema_doc=None,
            tool_specs=_FAKE_TOOLS,
            contact=_contact(),
            schema_doc_loader=None,
        )


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


def test_returns_non_empty_string():
    prompt = build_system_prompt(
        schema_doc=_FAKE_SCHEMA,
        tool_specs=_FAKE_TOOLS,
        contact=_contact(),
    )
    assert isinstance(prompt, str)
    assert len(prompt.strip()) > 0


# ---------------------------------------------------------------------------
# T-204 — System prompt update: execute_python_report rule (RF-181..RF-183)
# ---------------------------------------------------------------------------

class TestSandboxSystemPromptUpdate:
    """T-204: System prompt must reflect execute_python_report as legitimate
    execution path and the anti-eval/exec rule must remain. RF-181..RF-183."""

    def _build(self, schema: str = "schema", tools: str = "tools") -> str:
        return build_system_prompt(
            schema_doc=schema,
            tool_specs=tools,
            contact=_contact(),
        )

    def test_blanket_python_ban_not_present(self):
        """RF-181: The unconditional 'NUNCA ejecutes codigo Python/Bash' rule
        must be replaced with the more nuanced rule that names execute_python_report."""
        prompt = self._build()
        # The old blanket rule mentioned 'filesystem, eval, exec, ni código Python/Bash'
        # It must not exist as the old verbatim phrase:
        assert "ni código Python/Bash" not in prompt

    def test_execute_python_report_named_as_legitimate_path(self):
        """RF-181: execute_python_report must appear in the security rule as the
        sole legitimate path for Python code execution."""
        prompt = self._build()
        assert "execute_python_report" in prompt

    def test_anti_eval_exec_rule_still_present(self):
        """RF-181: The anti-eval/exec prohibition must still be present."""
        prompt = self._build()
        assert "eval" in prompt
        assert "exec" in prompt

    def test_sandbox_isolation_described(self):
        """RF-182: Prompt must mention that code runs in an isolated sandbox."""
        prompt = self._build()
        assert "sandbox" in prompt.lower() or "aislado" in prompt.lower()

    def test_report_use_case_mentioned(self):
        """RF-182: Prompt must guide LLM to use the tool for report generation."""
        prompt = self._build()
        # Must mention Excel, grafico/gráfico, PDF or similar output types
        mentions_report = any(
            kw in prompt.lower()
            for kw in ["excel", "pdf", "reporte", "gráfico", "grafico"]
        )
        assert mentions_report

    def test_length_within_20_percent_budget(self):
        """RF-183: Updated prompt must not exceed pre-change length * 1.20."""
        # Pre-change template length measured with fixed schema/tools inputs
        _PRE_CHANGE_LENGTH = 2796  # measured before T-204 changes
        prompt = self._build(schema="schema", tools="tools")
        assert len(prompt) <= _PRE_CHANGE_LENGTH * 1.20, (
            f"Prompt length {len(prompt)} exceeds budget "
            f"{int(_PRE_CHANGE_LENGTH * 1.20)} (pre-change: {_PRE_CHANGE_LENGTH})"
        )
