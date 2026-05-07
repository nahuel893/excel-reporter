"""tests/bd_agent/tools/test_reports.py -- TDD tests for execute_python_report_handler.

T-103: happy path returns {ok: true, file_size, filename, exec_duration_ms}.
T-104: error paths for each phase (validation, sql, staging, execution, timeout, output, send).

All sandbox components are faked -- no real Docker, no real DB.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping

import pytest


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeDatabaseGateway:
    """Returns canned rows from execute_select."""

    def __init__(self, rows: list[dict] | None = None, raise_exc: Exception | None = None):
        self._rows = rows or [{"col": "val"}]
        self._raise_exc = raise_exc
        self.called_with: list[tuple] = []

    def execute_select(self, query: str, params: dict, max_rows: int) -> list[dict]:
        self.called_with.append((query, params, max_rows))
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._rows

    def get_schema_doc(self) -> str:
        return "schema"


class FakeMessagingGateway:
    """Records send_file calls."""

    def __init__(self, raise_exc: Exception | None = None):
        self.sent_files: list[tuple] = []
        self._raise_exc = raise_exc

    def send_text(self, jid: str, text: str) -> None:
        pass

    def send_file(self, jid: str, file_path: Path, caption: str | None = None) -> None:
        self.sent_files.append((jid, file_path, caption))
        if self._raise_exc is not None:
            raise self._raise_exc


class FakeDockerRunner:
    """Simulates DockerRunner.run() without touching Docker."""

    def __init__(
        self,
        exit_code: int = 0,
        stderr: str = "",
        stdout: str = "",
        timed_out: bool = False,
        duration_ms: int = 42,
        write_output: bool = True,
        output_filename: str = "report.xlsx",
    ):
        self._exit_code = exit_code
        self._stderr = stderr
        self._stdout = stdout
        self._timed_out = timed_out
        self._duration_ms = duration_ms
        self._write_output = write_output
        self._output_filename = output_filename
        self.calls: list[dict] = []

    def run(
        self,
        *,
        code_path: Path,
        parquet_path: Path,
        output_dir: Path,
        timeout_s: int,
    ):
        from bd_agent.sandbox.runner import RunResult

        self.calls.append(
            {
                "code_path": code_path,
                "parquet_path": parquet_path,
                "output_dir": output_dir,
                "timeout_s": timeout_s,
            }
        )

        # Simulate writing output file if configured to do so
        if self._write_output and self._exit_code == 0:
            out_file = output_dir / self._output_filename
            out_file.write_bytes(b"PK\x03\x04" + b"\x00" * 100)  # fake xlsx header + padding

        return RunResult(
            exit_code=self._exit_code,
            stdout=self._stdout,
            stderr=self._stderr,
            duration_ms=self._duration_ms,
            timed_out=self._timed_out,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PYTHON_CODE = """\
import pandas as pd
df = pd.read_parquet('/data/input.parquet')
df.to_excel('/output/report.xlsx', index=False)
"""

VALID_SQL = "SELECT col FROM gold.fact_ventas LIMIT 10"

# Malicious code that the AST validator blocks
BLOCKED_CODE_SUBPROCESS = "import subprocess\nresult = subprocess.run(['ls'])"


def _register(gateway=None, messaging=None, runner=None, timeout_s: int = 30):
    """Create a ToolRegistry with execute_python_report registered."""
    from bd_agent.tools.reports import register_into
    from bd_agent.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_into(
        registry,
        gateway=gateway or FakeDatabaseGateway(),
        messaging=messaging or FakeMessagingGateway(),
        runner=runner or FakeDockerRunner(),
        timeout_s=timeout_s,
    )
    return registry


def _invoke(registry, *, python_code=VALID_PYTHON_CODE, sql_query=VALID_SQL,
            sql_params=None, output_filename="report.xlsx", description="test",
            jid="jid@s.whatsapp.net", context_override=None):
    import json
    from bd_agent.contracts import ToolCall

    call = ToolCall(
        id="cx",
        name="execute_python_report",
        arguments={
            "sql_query": sql_query,
            "sql_params": sql_params or {},
            "python_code": python_code,
            "output_filename": output_filename,
            "description": description,
        },
    )
    ctx = context_override if context_override is not None else {"_jid": jid}
    result = registry.invoke(call, gateway=None, context=ctx)
    return json.loads(result.content)


# ---------------------------------------------------------------------------
# T-103: Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_returns_ok_true_with_expected_fields(self):
        """T-103: happy path returns {ok: true, file_size, filename, exec_duration_ms}."""
        registry = _register(runner=FakeDockerRunner(output_filename="report.xlsx"))
        payload = _invoke(registry)
        assert payload["ok"] is True
        assert payload["filename"] == "report.xlsx"
        assert payload["file_size"] > 0
        assert isinstance(payload["exec_duration_ms"], int)

    def test_send_file_called_once_with_correct_jid(self):
        """T-103/RF-142: send_file called exactly once with _jid from context."""
        messaging = FakeMessagingGateway()
        registry = _register(
            messaging=messaging,
            runner=FakeDockerRunner(output_filename="report.xlsx"),
        )
        jid = "5493870000001@s.whatsapp.net"
        _invoke(registry, jid=jid, description="caption text")

        assert len(messaging.sent_files) == 1
        sent_jid, _, sent_caption = messaging.sent_files[0]
        assert sent_jid == jid
        assert sent_caption == "caption text"

    def test_tempdir_cleaned_up_after_success(self):
        """T-103/RF-124,RF-134: temp files are deleted after successful execution."""
        created_tempdirs = []

        class SpyRunner(FakeDockerRunner):
            def run(self, *, code_path, parquet_path, output_dir, timeout_s):
                created_tempdirs.append(output_dir.parent)
                return super().run(
                    code_path=code_path,
                    parquet_path=parquet_path,
                    output_dir=output_dir,
                    timeout_s=timeout_s,
                )

        registry = _register(runner=SpyRunner(output_filename="report.xlsx"))
        _invoke(registry)

        assert len(created_tempdirs) == 1
        assert not created_tempdirs[0].exists(), "tempdir must be removed"


# ---------------------------------------------------------------------------
# T-104: Error phases
# ---------------------------------------------------------------------------


class TestErrorPhases:
    def test_ast_validation_failure(self):
        """T-104a: blocked import → {ok: false, phase: 'validation'}."""
        registry = _register()
        payload = _invoke(registry, python_code=BLOCKED_CODE_SUBPROCESS)
        assert payload["ok"] is False
        assert payload["phase"] == "validation"
        assert "error" in payload

    def test_sql_validation_failure(self):
        """T-104b: unsafe SQL → {ok: false, phase: 'sql'}."""
        registry = _register()
        payload = _invoke(registry, sql_query="DROP TABLE gold.fact_ventas")
        assert payload["ok"] is False
        assert payload["phase"] == "sql"

    def test_staging_row_cap_error(self):
        """T-104c: row cap exceeded → {ok: false, phase: 'staging'}."""
        big_rows = [{"c": i} for i in range(100_001)]
        registry = _register(gateway=FakeDatabaseGateway(rows=big_rows))
        payload = _invoke(registry)
        assert payload["ok"] is False
        assert payload["phase"] == "staging"

    def test_runner_exit_code_nonzero(self):
        """T-104d: container exit_code != 0 → {ok: false, phase: 'execution', exit_code, error}."""
        runner = FakeDockerRunner(
            exit_code=1,
            stderr="ZeroDivisionError: division by zero",
            write_output=False,
        )
        registry = _register(runner=runner)
        payload = _invoke(registry)
        assert payload["ok"] is False
        assert payload["phase"] == "execution"
        assert payload.get("exit_code") == 1
        assert "error" in payload

    def test_runner_timeout(self):
        """T-104e: container timed out → {ok: false, phase: 'timeout'}."""
        runner = FakeDockerRunner(
            exit_code=-1,
            timed_out=True,
            stderr="Container killed after timeout (30s)",
            write_output=False,
        )
        registry = _register(runner=runner, timeout_s=30)
        payload = _invoke(registry)
        assert payload["ok"] is False
        assert payload["phase"] == "timeout"
        assert "error" in payload

    def test_output_collection_failure_file_missing(self):
        """T-104f: output file not written → {ok: false, phase: 'output'}."""
        runner = FakeDockerRunner(exit_code=0, write_output=False)
        registry = _register(runner=runner)
        payload = _invoke(registry, output_filename="report.xlsx")
        assert payload["ok"] is False
        assert payload["phase"] == "output"

    def test_send_file_exception(self):
        """T-104g: send_file raises → {ok: false, phase: 'send'}."""
        messaging = FakeMessagingGateway(raise_exc=RuntimeError("network timeout"))
        registry = _register(messaging=messaging)
        payload = _invoke(registry)
        assert payload["ok"] is False
        assert payload["phase"] == "send"

    def test_missing_jid_in_context(self):
        """T-104h: context without _jid → {ok: false, phase: 'validation'}."""
        registry = _register()
        payload = _invoke(registry, context_override={})
        assert payload["ok"] is False
        assert payload["phase"] == "validation"

    def test_no_docker_started_on_validation_failure(self):
        """T-104: AST failure must not start any container."""
        runner = FakeDockerRunner()
        registry = _register(runner=runner)
        _invoke(registry, python_code=BLOCKED_CODE_SUBPROCESS)
        assert len(runner.calls) == 0
