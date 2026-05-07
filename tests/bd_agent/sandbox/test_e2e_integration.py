"""tests/bd_agent/sandbox/test_e2e_integration.py — End-to-end integration tests (T-207).

These tests require:
  - A running Docker daemon
  - The bd-agent-sandbox:latest image built (bash scripts/build_sandbox_image.sh)
  - SANDBOX_ENABLED=true in the environment (or skip)

All tests are marked @pytest.mark.integration and are SKIPPED by default in CI.
Run explicitly with: pytest -m integration -v tests/bd_agent/sandbox/test_e2e_integration.py

Scenarios covered (RF-101, RF-141, RF-143):
  Case 1: Full pipeline — validator -> stage -> runner -> collector -> messaging stub
  Case 2: Malicious payload rejected by validator (no container spawn)
  Case 3: Timeout enforcement — script that sleeps 60s + timeout_s=2
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pytest


# ---------------------------------------------------------------------------
# Skip guard: all tests require SANDBOX_ENABLED=true AND Docker + image
# ---------------------------------------------------------------------------

def _sandbox_available() -> bool:
    """Return True if Docker is available AND the sandbox image exists."""
    if os.environ.get("SANDBOX_ENABLED", "").lower() != "true":
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "bd-agent-sandbox:latest"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


_sandbox_skip = pytest.mark.skipif(
    not _sandbox_available(),
    reason=(
        "Sandbox integration tests require SANDBOX_ENABLED=true, "
        "Docker daemon running, and bd-agent-sandbox:latest image built."
    ),
)

pytestmark = [pytest.mark.integration, _sandbox_skip]


# ---------------------------------------------------------------------------
# Fakes and helpers
# ---------------------------------------------------------------------------

class FakeDatabaseGateway:
    """Fake gateway that returns a small canned DataFrame."""

    def execute_select(
        self, query: str, params: Mapping[str, Any], *, max_rows: int = 100_000
    ):
        import pandas as pd
        return pd.DataFrame([
            {"sucursal": "CASA CENTRAL", "monto": 150_000},
            {"sucursal": "SUCURSAL CAFAYATE", "monto": 72_500},
        ])

    def get_schema_doc(self) -> str:
        return "# Test schema"


class RecordingMessagingGateway:
    """Captures send_file() calls instead of POSTing to Baileys."""

    def __init__(self):
        self.sent_files: list[tuple] = []

    def send_text(self, jid: str, text: str) -> None:
        pass

    def send_file(self, jid: str, file_path: Path, caption: str | None = None) -> None:
        # Copy the file contents before the caller deletes it
        import shutil
        dest = Path(tempfile.mktemp(suffix=file_path.suffix))
        shutil.copy2(file_path, dest)
        self.sent_files.append((jid, dest, caption))


_TEST_JID = "5493874000000@s.whatsapp.net"


# ---------------------------------------------------------------------------
# Case 1 — Full pipeline: generates Excel correctly
# ---------------------------------------------------------------------------

def test_full_pipeline_generates_excel():
    """RF-141: Full pipeline from SQL -> parquet -> Docker -> xlsx -> messaging stub."""
    from bd_agent.sandbox.runner import DockerRunner
    from bd_agent.tools.reports import execute_python_report_handler

    runner = DockerRunner(image="bd-agent-sandbox:latest")
    gateway = FakeDatabaseGateway()
    messaging = RecordingMessagingGateway()

    python_code = (
        "import pandas as pd\n"
        "df = pd.read_parquet('/data/input.parquet')\n"
        "df.to_excel('/output/report.xlsx', index=False)\n"
    )

    result = execute_python_report_handler(
        sql_query="SELECT sucursal, monto FROM gold.fact_ventas LIMIT 10",
        sql_params={},
        python_code=python_code,
        output_filename="report.xlsx",
        description="Test report",
        _jid=_TEST_JID,
        gateway=gateway,
        messaging=messaging,
        runner=runner,
        timeout_s=60,
    )

    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    assert result["filename"] == "report.xlsx"
    assert result["file_size"] > 0
    assert result["exec_duration_ms"] >= 0

    # Messaging stub received the file
    assert len(messaging.sent_files) == 1
    jid_sent, file_path, caption = messaging.sent_files[0]
    assert jid_sent == _TEST_JID
    assert file_path.exists()
    assert file_path.suffix == ".xlsx"
    assert caption == "Test report"


# ---------------------------------------------------------------------------
# Case 2 — Malicious payload rejected by validator (no container spawn)
# ---------------------------------------------------------------------------

def test_malicious_payload_rejected_by_validator():
    """RF-151: AST validator blocks dangerous code before any container is started."""
    from bd_agent.sandbox.runner import DockerRunner
    from bd_agent.tools.reports import execute_python_report_handler
    from unittest.mock import patch

    runner = DockerRunner(image="bd-agent-sandbox:latest")
    gateway = FakeDatabaseGateway()
    messaging = RecordingMessagingGateway()

    # Attempt to import subprocess (blocked by validator)
    malicious_code = "import subprocess\nsubprocess.run(['id'])\n"

    with patch.object(runner, "run") as mock_run:
        result = execute_python_report_handler(
            sql_query="SELECT 1",
            sql_params={},
            python_code=malicious_code,
            output_filename="evil.xlsx",
            description="Evil",
            _jid=_TEST_JID,
            gateway=gateway,
            messaging=messaging,
            runner=runner,
            timeout_s=5,
        )

    assert result["ok"] is False
    assert result["phase"] == "validation"
    # Container must NOT have been spawned
    mock_run.assert_not_called()
    # Messaging must NOT have been called
    assert len(messaging.sent_files) == 0


# ---------------------------------------------------------------------------
# Case 3 — Timeout enforcement
# ---------------------------------------------------------------------------

def test_timeout_enforcement():
    """RF-102: Script that sleeps 60s is killed after timeout_s=2."""
    from bd_agent.sandbox.runner import DockerRunner
    from bd_agent.tools.reports import execute_python_report_handler

    runner = DockerRunner(image="bd-agent-sandbox:latest")
    gateway = FakeDatabaseGateway()
    messaging = RecordingMessagingGateway()

    # Script that blocks indefinitely
    infinite_code = "import time\ntime.sleep(60)\n"

    result = execute_python_report_handler(
        sql_query="SELECT 1",
        sql_params={},
        python_code=infinite_code,
        output_filename="never.xlsx",
        description="Timeout test",
        _jid=_TEST_JID,
        gateway=gateway,
        messaging=messaging,
        runner=runner,
        timeout_s=2,
    )

    assert result["ok"] is False
    # Phase should be "execution" or "timeout"
    assert result["phase"] in ("execution", "timeout")
    # No file was sent
    assert len(messaging.sent_files) == 0
