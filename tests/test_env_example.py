"""
Tests for .env.example — T-101

Validates that .env.example contains all required BD Agent environment
variable keys so new contributors know which variables to configure.
"""

from pathlib import Path

import pytest

ENV_EXAMPLE_FILE = Path(__file__).parent.parent / ".env.example"


@pytest.fixture(scope="module")
def env_content() -> str:
    assert ENV_EXAMPLE_FILE.exists(), f".env.example not found at {ENV_EXAMPLE_FILE}"
    return ENV_EXAMPLE_FILE.read_text(encoding="utf-8")


def test_env_example_exists():
    assert ENV_EXAMPLE_FILE.exists(), ".env.example must exist in project root"


def test_env_example_non_empty(env_content):
    assert len(env_content.strip()) > 0, ".env.example should not be empty"


# ---------------------------------------------------------------------------
# BD Agent section header
# ---------------------------------------------------------------------------

def test_has_bd_agent_section_header(env_content):
    assert "BD Agent" in env_content, (
        "Expected a '# === BD Agent ...' section header in .env.example"
    )


# ---------------------------------------------------------------------------
# Required keys — each must appear as a key (at line start or after optional #)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", [
    "AGENT_DB_URL",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "WHATSAPP_SERVICE_URL",
    "PYTHON_AGENT_URL",
])
def test_key_present(env_content, key):
    # Accept both uncommented (KEY=...) and commented (# KEY=... or # GROQ_API_KEY=)
    lines_with_key = [
        line for line in env_content.splitlines()
        if key in line
    ]
    assert lines_with_key, (
        f"Expected key '{key}' to be present in .env.example (commented or uncommented)"
    )


# ---------------------------------------------------------------------------
# AGENT_DB_URL — must have a meaningful example value
# ---------------------------------------------------------------------------

def test_agent_db_url_has_example_value(env_content):
    for line in env_content.splitlines():
        if line.startswith("AGENT_DB_URL="):
            value = line.split("=", 1)[1].strip()
            assert value, "AGENT_DB_URL must have an example value, not be empty"
            assert "postgresql://" in value, (
                "AGENT_DB_URL example should show a postgresql:// DSN"
            )
            return
    pytest.fail("AGENT_DB_URL= not found as an uncommented line in .env.example")


# ---------------------------------------------------------------------------
# WHATSAPP_SERVICE_URL — must document both port options
# ---------------------------------------------------------------------------

def test_whatsapp_service_url_documents_port(env_content):
    # Should mention port 3000 at minimum
    assert "3000" in env_content, (
        "WHATSAPP_SERVICE_URL should reference port 3000 (docker-compose default)"
    )


# ---------------------------------------------------------------------------
# PYTHON_AGENT_URL — must point to localhost:8000 by default
# ---------------------------------------------------------------------------

def test_python_agent_url_default(env_content):
    for line in env_content.splitlines():
        if line.startswith("PYTHON_AGENT_URL="):
            assert "8000" in line, (
                "PYTHON_AGENT_URL default should use port 8000 (FastAPI default)"
            )
            return
    pytest.fail("PYTHON_AGENT_URL= not found as an uncommented line in .env.example")


# ---------------------------------------------------------------------------
# Main DB vars still present (regression guard)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"])
def test_main_db_keys_still_present(env_content, key):
    lines_with_key = [line for line in env_content.splitlines() if key in line]
    assert lines_with_key, (
        f"Main DB key '{key}' should still be present in .env.example"
    )
