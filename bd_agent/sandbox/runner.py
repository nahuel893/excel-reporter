"""bd_agent/sandbox/runner.py -- Hardened Docker runner for sandbox scripts.

Builds and executes `docker run` with all security hardening flags required
by RF-101 and RF-102. Subprocess-based; no Docker SDK dependency.

Container isolation flags (RF-101):
  --rm                        remove container on exit
  --network=none              no network access
  --read-only                 read-only rootfs
  --user 1000:1000            non-root user
  --cap-drop=ALL              drop all Linux capabilities
  --security-opt=no-new-privileges
  --pids-limit=64             fork bomb protection
  --memory=256m               OOM kill at 256 MB
  --cpus=1.0                  CPU throttle
  --ulimit nofile=64:64       file descriptor limit
  --tmpfs /tmp:size=50m       scratch space

Volume mounts:
  <parquet_path>:/data/input.parquet:ro   read-only SQL result
  <code_path>:/code/script.py:ro          read-only LLM script
  <output_dir>:/output:rw                 write-only output

Timeout (RF-102): if subprocess.TimeoutExpired fires, run `docker kill <name>`
and return RunResult(timed_out=True, exit_code=-1).

Zero imports from src.* or bd_agent.* (pure stdlib).
"""
from __future__ import annotations

import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    """Result of a docker run invocation.

    Attributes:
        exit_code: Container exit code, or -1 on timeout.
        stdout: Captured stdout (decoded, may be empty).
        stderr: Captured stderr (decoded, last 500 chars recommended for LLM).
        duration_ms: Wall-clock duration in milliseconds.
        timed_out: True if the container was killed due to timeout.
    """

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool


# ---------------------------------------------------------------------------
# DockerRunner
# ---------------------------------------------------------------------------


class DockerRunner:
    """Executes a Python script in an isolated Docker container.

    Usage::

        runner = DockerRunner(image="bd-agent-sandbox:latest")
        result = runner.run(
            code_path=Path("/tmp/sb-abc/code/script.py"),
            parquet_path=Path("/tmp/sb-abc/data/input.parquet"),
            output_dir=Path("/tmp/sb-abc/output"),
            timeout_s=30,
        )
    """

    def __init__(self, *, image: str, docker_bin: str = "docker") -> None:
        self.image = image
        self.docker_bin = docker_bin

    def run(
        self,
        *,
        code_path: Path,
        parquet_path: Path,
        output_dir: Path,
        timeout_s: int,
    ) -> RunResult:
        """Run the script in a hardened container.

        Args:
            code_path: Host path to the validated Python script.
            parquet_path: Host path to the input parquet file.
            output_dir: Host path to the output directory (container writes here).
            timeout_s: Hard timeout in seconds; container is killed if exceeded.

        Returns:
            RunResult with exit_code, stderr, duration_ms, timed_out.
        """
        container_name = f"sb-{uuid.uuid4().hex[:12]}"

        cmd = [
            self.docker_bin,
            "run",
            "--rm",
            "--name", container_name,
            "--network=none",
            "--read-only",
            "--user", "1000:1000",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory=256m",
            "--cpus=1.0",
            "--ulimit", "nofile=64:64",
            "--tmpfs", "/tmp:size=50m",
            # Volume mounts
            "-v", f"{parquet_path}:/data/input.parquet:ro",
            "-v", f"{code_path}:/code/script.py:ro",
            "-v", f"{output_dir}:/output:rw",
            # Image and entrypoint
            self.image,
            "/code/script.py",
        ]

        start_ms = time.monotonic()

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout_s + 5,  # grace period beyond user timeout
            )
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            return RunResult(
                exit_code=completed.returncode,
                stdout=_decode(completed.stdout),
                stderr=_decode(completed.stderr),
                duration_ms=duration_ms,
                timed_out=False,
            )

        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            # Kill the named container
            subprocess.run(
                [self.docker_bin, "kill", container_name],
                capture_output=True,
                timeout=10,
            )
            return RunResult(
                exit_code=-1,
                stdout="",
                stderr=f"Container killed after timeout ({timeout_s}s)",
                duration_ms=duration_ms,
                timed_out=True,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode(raw: bytes, max_chars: int = 500) -> str:
    """Decode bytes to str, keeping last max_chars characters."""
    text = raw.decode("utf-8", errors="replace")
    return text[-max_chars:] if len(text) > max_chars else text
