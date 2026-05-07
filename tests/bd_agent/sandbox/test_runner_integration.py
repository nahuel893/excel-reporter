"""T-012: Integration tests for DockerRunner with real Docker.

Marked @pytest.mark.integration -- skipped unless:
  - SANDBOX_ENABLED=true
  - Docker daemon is available
  - bd-agent-sandbox:latest image exists

These tests do NOT run in CI without explicit opt-in.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    """Return True if Docker daemon is reachable."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _sandbox_image_exists() -> bool:
    """Return True if bd-agent-sandbox:latest is present locally."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "bd-agent-sandbox:latest"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _sandbox_enabled() -> bool:
    return os.environ.get("SANDBOX_ENABLED", "").lower() == "true"


_SKIP_REASON = (
    "Integration test skipped: requires SANDBOX_ENABLED=true, "
    "Docker daemon, and bd-agent-sandbox:latest image"
)

_skip_unless_ready = pytest.mark.skipif(
    not (_sandbox_enabled() and _docker_available() and _sandbox_image_exists()),
    reason=_SKIP_REASON,
)


@_skip_unless_ready
def test_trivial_script_exits_zero():
    """A trivial pd.read_parquet -> to_excel script runs successfully."""
    import pandas as pd

    from bd_agent.sandbox.runner import DockerRunner

    runner = DockerRunner(image="bd-agent-sandbox:latest")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        data_dir = tmp / "data"
        code_dir = tmp / "code"
        output_dir = tmp / "output"
        data_dir.mkdir()
        code_dir.mkdir()
        output_dir.mkdir(mode=0o777)

        # Write a minimal parquet fixture
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        parquet_path = data_dir / "input.parquet"
        df.to_parquet(parquet_path, engine="pyarrow")

        # Write a minimal script
        script = (
            "import pandas as pd\n"
            "df = pd.read_parquet('/data/input.parquet')\n"
            "df.to_excel('/output/report.xlsx', index=False)\n"
        )
        script_path = code_dir / "script.py"
        script_path.write_text(script)

        result = runner.run(
            code_path=script_path,
            parquet_path=parquet_path,
            output_dir=output_dir,
            timeout_s=60,
        )

    assert result.exit_code == 0, f"Expected exit_code=0, got {result.exit_code}. stderr: {result.stderr}"
    assert result.timed_out is False


@_skip_unless_ready
def test_output_file_created():
    """After a successful run, the output file exists in output_dir."""
    import pandas as pd

    from bd_agent.sandbox.runner import DockerRunner

    runner = DockerRunner(image="bd-agent-sandbox:latest")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        data_dir = tmp / "data"
        code_dir = tmp / "code"
        output_dir = tmp / "output"
        data_dir.mkdir()
        code_dir.mkdir()
        output_dir.mkdir(mode=0o777)

        df = pd.DataFrame({"x": range(5)})
        parquet_path = data_dir / "input.parquet"
        df.to_parquet(parquet_path, engine="pyarrow")

        script_path = code_dir / "script.py"
        script_path.write_text(
            "import pandas as pd\n"
            "df = pd.read_parquet('/data/input.parquet')\n"
            "df.to_excel('/output/result.xlsx', index=False)\n"
        )

        runner.run(
            code_path=script_path,
            parquet_path=parquet_path,
            output_dir=output_dir,
            timeout_s=60,
        )

        assert (output_dir / "result.xlsx").exists(), "Output file must be created"
