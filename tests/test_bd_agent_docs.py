"""tests/test_bd_agent_docs.py — T-112: Final documentation validation.

Ensures the documentation artifacts required by Slice 12 exist and contain
the expected content markers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# docs/bd_agent/README.md
# ---------------------------------------------------------------------------

class TestBdAgentReadme:

    def test_readme_exists(self):
        assert (PROJECT_ROOT / "docs" / "bd_agent" / "README.md").exists()

    def test_readme_has_module_layout_section(self):
        content = (PROJECT_ROOT / "docs" / "bd_agent" / "README.md").read_text()
        assert "Module layout" in content or "module layout" in content.lower()

    def test_readme_mentions_observability(self):
        content = (PROJECT_ROOT / "docs" / "bd_agent" / "README.md").read_text()
        assert "observability" in content.lower() or "Observability" in content

    def test_readme_mentions_smoke_test(self):
        content = (PROJECT_ROOT / "docs" / "bd_agent" / "README.md").read_text()
        assert "smoke_test" in content or "smoke test" in content.lower()

    def test_readme_mentions_protocol_contracts(self):
        content = (PROJECT_ROOT / "docs" / "bd_agent" / "README.md").read_text()
        assert "Protocol" in content or "protocol" in content.lower()

    def test_readme_mentions_extraction_recipe(self):
        content = (PROJECT_ROOT / "docs" / "bd_agent" / "README.md").read_text()
        assert "extract" in content.lower() or "standalone" in content.lower()

    def test_readme_mentions_security_layers(self):
        content = (PROJECT_ROOT / "docs" / "bd_agent" / "README.md").read_text()
        assert "sqlglot" in content.lower()
        assert "agent_user" in content or "Postgres" in content

    def test_readme_mentions_metrics_endpoint(self):
        content = (PROJECT_ROOT / "docs" / "bd_agent" / "README.md").read_text()
        assert "/agent/metrics" in content

    def test_readme_mentions_gemini_cost(self):
        content = (PROJECT_ROOT / "docs" / "bd_agent" / "README.md").read_text()
        assert "Flash Lite" in content or "flash-lite" in content.lower()
        assert "0.075" in content or "$0.075" in content


# ---------------------------------------------------------------------------
# AGENTS.md updated section
# ---------------------------------------------------------------------------

class TestAgentsMdObservability:

    def _content(self):
        return (PROJECT_ROOT / "AGENTS.md").read_text()

    def test_agents_md_has_metrics_curl(self):
        content = self._content()
        assert "/agent/metrics" in content

    def test_agents_md_has_smoke_test_command(self):
        content = self._content()
        assert "smoke_test" in content

    def test_agents_md_has_docs_pointer(self):
        content = self._content()
        assert "docs/bd_agent/README.md" in content

    def test_agents_md_mentions_jid_hash(self):
        content = self._content()
        assert "jid_hash" in content

    def test_agents_md_mentions_observabilidad(self):
        content = self._content()
        assert "Observabilidad" in content or "observabilidad" in content


# ---------------------------------------------------------------------------
# Smoke script exists and is runnable as __main__
# ---------------------------------------------------------------------------

class TestSmokeScriptMain:

    def test_smoke_script_exists(self):
        assert (PROJECT_ROOT / "bd_agent" / "scripts" / "smoke_test.py").exists()

    def test_smoke_script_has_main_guard(self):
        content = (PROJECT_ROOT / "bd_agent" / "scripts" / "smoke_test.py").read_text()
        assert '__name__ == "__main__"' in content or "__name__ == '__main__'" in content

    def test_smoke_script_has_run_all_checks(self):
        content = (PROJECT_ROOT / "bd_agent" / "scripts" / "smoke_test.py").read_text()
        assert "run_all_checks" in content

    def test_smoke_script_has_checklist_output(self):
        content = (PROJECT_ROOT / "bd_agent" / "scripts" / "smoke_test.py").read_text()
        # Must print checkmarks
        assert "✓" in content or "checkmark" in content.lower() or "_print_results" in content
