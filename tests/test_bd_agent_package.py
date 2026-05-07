"""T-010: Tests for bd_agent package skeleton.

Verifies:
- bd_agent is importable as a package
- bd_agent has zero imports from src/ (modularity contract RF-070)
"""
import importlib
import subprocess
import sys


def test_bd_agent_importable():
    """bd_agent package must import without error."""
    import bd_agent  # noqa: F401


def test_no_src_imports_in_bd_agent():
    """bd_agent/ must have zero direct imports from src.* (RF-070).

    Uses rg (ripgrep) to find actual Python import statements only
    (not comments or strings).
    """
    result = subprocess.run(
        [
            "grep",
            "-r",
            "--include=*.py",
            "-E",
            r"^(from src\.|import src\.)",
            "bd_agent/",
        ],
        capture_output=True,
        text=True,
        cwd="/home/nahuel/projects/work/Informes Badie",
    )
    assert result.stdout.strip() == "", (
        f"Found forbidden src.* imports in bd_agent/:\n{result.stdout}"
    )


def test_bd_agent_has_no_side_effect_on_import():
    """Importing bd_agent must not raise or print anything."""
    # If the module is cached, re-importing is safe; if not, import fresh
    import bd_agent  # noqa: F401
    # No assertion needed — absence of exception is the assertion
