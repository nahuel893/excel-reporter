"""T-010, T-011: Failing tests for bd_agent/sandbox/runner.py -- DockerRunner.

TDD cycle: RED first (runner.py does not exist) -> GREEN -> REFACTOR.

Covers (RF-101, RF-102):
- All hardening flags are present in the docker run command
- Timeout path: subprocess.TimeoutExpired -> docker kill -> RunResult(timed_out=True)
- exit_code propagated correctly
- Container named with sb-{uuid} prefix
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_PARQUET = Path("/tmp/test_parquet/input.parquet")
_FAKE_CODE = Path("/tmp/test_code/script.py")
_FAKE_OUTPUT = Path("/tmp/test_output")
_IMAGE = "bd-agent-sandbox:latest"


def _make_runner():
    from bd_agent.sandbox.runner import DockerRunner

    return DockerRunner(image=_IMAGE)


def _extract_cmd(mock_run: MagicMock) -> list[str]:
    """Extract the command list from the first subprocess.run call."""
    args, kwargs = mock_run.call_args
    if args:
        return list(args[0])
    return list(kwargs.get("cmd", []))


# ---------------------------------------------------------------------------
# Tests -- RED phase
# ---------------------------------------------------------------------------


class TestRunResultContract:
    """RunResult dataclass contract."""

    def test_importable(self):
        from bd_agent.sandbox.runner import RunResult  # noqa: F401

    def test_fields_present(self):
        from bd_agent.sandbox.runner import RunResult

        r = RunResult(
            exit_code=0,
            stdout="hello",
            stderr="",
            duration_ms=150,
            timed_out=False,
        )
        assert r.exit_code == 0
        assert r.stdout == "hello"
        assert r.stderr == ""
        assert r.duration_ms == 150
        assert r.timed_out is False

    def test_frozen(self):
        from bd_agent.sandbox.runner import RunResult

        r = RunResult(exit_code=0, stdout="", stderr="", duration_ms=0, timed_out=False)
        with pytest.raises((AttributeError, TypeError)):
            r.exit_code = 1  # type: ignore[misc]


class TestDockerRunnerInit:
    """DockerRunner basic construction."""

    def test_importable(self):
        from bd_agent.sandbox.runner import DockerRunner  # noqa: F401

    def test_default_docker_bin(self):
        from bd_agent.sandbox.runner import DockerRunner

        runner = DockerRunner(image=_IMAGE)
        assert runner.image == _IMAGE

    def test_custom_docker_bin(self):
        from bd_agent.sandbox.runner import DockerRunner

        runner = DockerRunner(image=_IMAGE, docker_bin="/usr/local/bin/docker")
        assert runner.docker_bin == "/usr/local/bin/docker"


class TestHardeningFlags:
    """T-010: All hardening flags must appear in the docker run command (RF-101)."""

    def _run_and_capture_cmd(self) -> list[str]:
        """Run DockerRunner with mocked subprocess and return the command list."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b""
        mock_result.stderr = b""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            runner = _make_runner()
            runner.run(
                code_path=_FAKE_CODE,
                parquet_path=_FAKE_PARQUET,
                output_dir=_FAKE_OUTPUT,
                timeout_s=30,
            )
            args, kwargs = mock_run.call_args
            return list(args[0])

    def test_rm_flag_present(self):
        cmd = self._run_and_capture_cmd()
        assert "--rm" in cmd

    def test_network_none_flag_present(self):
        cmd = self._run_and_capture_cmd()
        assert "--network=none" in cmd

    def test_read_only_flag_present(self):
        cmd = self._run_and_capture_cmd()
        assert "--read-only" in cmd

    def test_user_flag_present(self):
        cmd = self._run_and_capture_cmd()
        assert "--user" in cmd
        user_idx = cmd.index("--user")
        assert cmd[user_idx + 1] == "1000:1000"

    def test_cap_drop_all_present(self):
        cmd = self._run_and_capture_cmd()
        assert "--cap-drop=ALL" in cmd

    def test_security_opt_no_new_privileges(self):
        cmd = self._run_and_capture_cmd()
        assert "--security-opt=no-new-privileges" in cmd

    def test_pids_limit_present(self):
        cmd = self._run_and_capture_cmd()
        assert "--pids-limit=64" in cmd

    def test_memory_limit_present(self):
        cmd = self._run_and_capture_cmd()
        assert "--memory=256m" in cmd

    def test_cpus_limit_present(self):
        cmd = self._run_and_capture_cmd()
        assert "--cpus=1.0" in cmd

    def test_tmpfs_tmp_present(self):
        cmd = self._run_and_capture_cmd()
        assert "--tmpfs" in cmd
        tmpfs_idx = cmd.index("--tmpfs")
        assert "/tmp:size=50m" in cmd[tmpfs_idx + 1]

    def test_parquet_volume_mount_present(self):
        """Parquet must be mounted as /data/input.parquet:ro."""
        cmd = self._run_and_capture_cmd()
        # Find -v flag for parquet
        v_flags = [cmd[i + 1] for i, c in enumerate(cmd) if c == "-v"]
        parquet_mounts = [v for v in v_flags if "input.parquet" in v and ":ro" in v]
        assert parquet_mounts, f"No parquet:ro volume mount found in: {v_flags}"
        assert "/data/input.parquet:ro" in parquet_mounts[0]

    def test_script_volume_mount_present(self):
        """Script must be mounted as /code/script.py:ro."""
        cmd = self._run_and_capture_cmd()
        v_flags = [cmd[i + 1] for i, c in enumerate(cmd) if c == "-v"]
        script_mounts = [v for v in v_flags if "script.py" in v and ":ro" in v]
        assert script_mounts, f"No script:ro volume mount found in: {v_flags}"
        assert "/code/script.py:ro" in script_mounts[0]

    def test_output_volume_mount_present(self):
        """Output dir must be mounted as /output:rw."""
        cmd = self._run_and_capture_cmd()
        v_flags = [cmd[i + 1] for i, c in enumerate(cmd) if c == "-v"]
        output_mounts = [v for v in v_flags if "/output" in v]
        assert output_mounts, f"No /output volume mount found in: {v_flags}"

    def test_image_present_in_command(self):
        cmd = self._run_and_capture_cmd()
        assert _IMAGE in cmd

    def test_entrypoint_script_present(self):
        """Container must be told to run /code/script.py."""
        cmd = self._run_and_capture_cmd()
        assert "/code/script.py" in cmd

    def test_container_named_with_sb_prefix(self):
        """Container must use --name sb-{uuid} for docker kill on timeout."""
        cmd = self._run_and_capture_cmd()
        assert "--name" in cmd
        name_idx = cmd.index("--name")
        assert cmd[name_idx + 1].startswith("sb-"), (
            f"Container name must start with 'sb-', got: {cmd[name_idx + 1]}"
        )


class TestExitCodePropagation:
    """exit_code from subprocess must be propagated in RunResult."""

    @pytest.mark.parametrize("code", [0, 1, 127, 255])
    def test_exit_code_propagated(self, code: int):
        mock_result = MagicMock()
        mock_result.returncode = code
        mock_result.stdout = b""
        mock_result.stderr = b""

        with patch("subprocess.run", return_value=mock_result):
            runner = _make_runner()
            result = runner.run(
                code_path=_FAKE_CODE,
                parquet_path=_FAKE_PARQUET,
                output_dir=_FAKE_OUTPUT,
                timeout_s=30,
            )
            assert result.exit_code == code

    def test_ok_exit_code_timed_out_false(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b""
        mock_result.stderr = b""

        with patch("subprocess.run", return_value=mock_result):
            runner = _make_runner()
            result = runner.run(
                code_path=_FAKE_CODE,
                parquet_path=_FAKE_PARQUET,
                output_dir=_FAKE_OUTPUT,
                timeout_s=30,
            )
            assert result.timed_out is False


class TestTimeout:
    """T-011: Timeout path -- subprocess.TimeoutExpired triggers docker kill (RF-102)."""

    def test_timeout_returns_timed_out_true(self):
        """On TimeoutExpired, RunResult.timed_out must be True."""
        mock_kill_result = MagicMock()
        mock_kill_result.returncode = 0
        mock_kill_result.stdout = b""
        mock_kill_result.stderr = b""

        with patch(
            "subprocess.run",
            side_effect=[
                subprocess.TimeoutExpired(cmd=["docker", "run"], timeout=30),
                mock_kill_result,  # docker kill response
            ],
        ):
            runner = _make_runner()
            result = runner.run(
                code_path=_FAKE_CODE,
                parquet_path=_FAKE_PARQUET,
                output_dir=_FAKE_OUTPUT,
                timeout_s=30,
            )
            assert result.timed_out is True

    def test_timeout_exit_code_minus_one(self):
        """On timeout, exit_code must be -1."""
        mock_kill_result = MagicMock()
        mock_kill_result.returncode = 0
        mock_kill_result.stdout = b""
        mock_kill_result.stderr = b""

        with patch(
            "subprocess.run",
            side_effect=[
                subprocess.TimeoutExpired(cmd=["docker", "run"], timeout=30),
                mock_kill_result,
            ],
        ):
            runner = _make_runner()
            result = runner.run(
                code_path=_FAKE_CODE,
                parquet_path=_FAKE_PARQUET,
                output_dir=_FAKE_OUTPUT,
                timeout_s=30,
            )
            assert result.exit_code == -1

    def test_timeout_calls_docker_kill(self):
        """On TimeoutExpired, docker kill must be called with the container name."""
        kill_calls: list[list[str]] = []

        def side_effect(cmd, *args, **kwargs):
            if "kill" in cmd:
                kill_calls.append(cmd)
                r = MagicMock()
                r.returncode = 0
                r.stdout = b""
                r.stderr = b""
                return r
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

        with patch("subprocess.run", side_effect=side_effect):
            runner = _make_runner()
            runner.run(
                code_path=_FAKE_CODE,
                parquet_path=_FAKE_PARQUET,
                output_dir=_FAKE_OUTPUT,
                timeout_s=30,
            )

        assert len(kill_calls) == 1, "docker kill must be called exactly once on timeout"
        kill_cmd = kill_calls[0]
        assert "kill" in kill_cmd, f"Expected 'kill' in command: {kill_cmd}"
        # Container name must appear in kill command
        container_name = [arg for arg in kill_cmd if arg.startswith("sb-")]
        assert container_name, f"No sb-* container name found in kill cmd: {kill_cmd}"

    def test_stderr_tail_in_result(self):
        """stderr output must be captured and available in RunResult."""
        stderr_content = b"Error: something failed\n" * 10
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = b""
        mock_result.stderr = stderr_content

        with patch("subprocess.run", return_value=mock_result):
            runner = _make_runner()
            result = runner.run(
                code_path=_FAKE_CODE,
                parquet_path=_FAKE_PARQUET,
                output_dir=_FAKE_OUTPUT,
                timeout_s=30,
            )
            assert len(result.stderr) > 0
            assert "Error" in result.stderr

    def test_duration_ms_positive_on_success(self):
        """duration_ms must be a non-negative integer."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b""
        mock_result.stderr = b""

        with patch("subprocess.run", return_value=mock_result):
            runner = _make_runner()
            result = runner.run(
                code_path=_FAKE_CODE,
                parquet_path=_FAKE_PARQUET,
                output_dir=_FAKE_OUTPUT,
                timeout_s=30,
            )
            assert result.duration_ms >= 0
