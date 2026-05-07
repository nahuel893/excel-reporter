"""
Tests for the "Asistente WhatsApp" documentation section — T-102

Validates that AGENTS.md (which CLAUDE.md symlinks to) contains the
BD Agent setup section with the required sub-topics.
"""

from pathlib import Path

import pytest

# CLAUDE.md is a symlink to AGENTS.md — test the real file
AGENTS_MD = Path(__file__).parent.parent / "AGENTS.md"
CLAUDE_MD_SYMLINK = Path(__file__).parent.parent / "CLAUDE.md"


@pytest.fixture(scope="module")
def doc_content() -> str:
    assert AGENTS_MD.exists(), f"AGENTS.md not found at {AGENTS_MD}"
    return AGENTS_MD.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# File and symlink checks
# ---------------------------------------------------------------------------

def test_agents_md_exists():
    assert AGENTS_MD.exists(), "AGENTS.md must exist"


def test_claude_md_is_symlink_to_agents_md():
    assert CLAUDE_MD_SYMLINK.is_symlink(), "CLAUDE.md should be a symlink"
    resolved = CLAUDE_MD_SYMLINK.resolve()
    assert resolved == AGENTS_MD.resolve(), (
        f"CLAUDE.md symlink should resolve to AGENTS.md, got {resolved}"
    )


# ---------------------------------------------------------------------------
# Section header
# ---------------------------------------------------------------------------

def test_has_whatsapp_agent_section(doc_content):
    assert "Asistente WhatsApp" in doc_content, (
        "Expected '## Asistente WhatsApp' section header in AGENTS.md"
    )


# ---------------------------------------------------------------------------
# Setup checklist items
# ---------------------------------------------------------------------------

def test_mentions_agent_user_sql(doc_content):
    assert "agent_user.sql" in doc_content, (
        "Setup section should reference scripts/sql/agent_user.sql"
    )


def test_mentions_gemini_api_key(doc_content):
    assert "GEMINI_API_KEY" in doc_content, (
        "Setup section should mention GEMINI_API_KEY"
    )


def test_mentions_contactos_agente(doc_content):
    assert "contactos_agente" in doc_content, (
        "Setup section should reference configs/contactos_agente.json"
    )


def test_mentions_test_roundtrip(doc_content):
    assert "test-roundtrip" in doc_content, (
        "Setup section should reference whatsapp-service/test-roundtrip.md"
    )


# ---------------------------------------------------------------------------
# Architecture links
# ---------------------------------------------------------------------------

def test_mentions_bd_agent_package(doc_content):
    assert "bd_agent/" in doc_content, (
        "Architecture section should reference bd_agent/ package"
    )


def test_mentions_whatsapp_service(doc_content):
    assert "whatsapp-service/index.js" in doc_content, (
        "Architecture section should reference whatsapp-service/index.js"
    )


# ---------------------------------------------------------------------------
# Operational notes
# ---------------------------------------------------------------------------

def test_mentions_disable_via_empty_key(doc_content):
    assert "GEMINI_API_KEY" in doc_content and (
        "deshabilitar" in doc_content.lower() or "disable" in doc_content.lower()
    ), "Docs should explain how to disable the agent via empty GEMINI_API_KEY"


def test_mentions_reload_contacts_endpoint(doc_content):
    assert "reload-contacts" in doc_content, (
        "Operational notes should mention POST /agent/reload-contacts"
    )


# ---------------------------------------------------------------------------
# Cost estimate
# ---------------------------------------------------------------------------

def test_mentions_cost_estimate(doc_content):
    assert "gemini-2.0-flash-lite" in doc_content.lower() or "flash-lite" in doc_content.lower(), (
        "Docs should include cost estimate referencing gemini-2.0-flash-lite"
    )
