"""bd_agent/tools/reports.py -- execute_python_report tool handler.

T-105: Registers the execute_python_report tool with the ToolRegistry via
register_into(), implementing the full data flow from spec §4/design §4:

  1. Validate _jid from context (fast-fail, no container)
  2. AST-validate python_code (fast-fail, no container)
  3. Validate SQL via sqlglot (fast-fail, no DB)
  4. Stage SQL result to Parquet tempfile
  5. Write python_code to tempfile
  6. Run DockerRunner.run()
  7. Collect output file via output_collector
  8. Deliver via messaging.send_file(_jid, path, caption=description)
  9. Cleanup tempdir (always, in finally)
  10. Return {ok: true, filename, file_size, exec_duration_ms}

Error paths return {ok: false, phase: str, error: str} so the LLM can retry.

Zero imports from src.*. Deps: bd_agent.contracts, bd_agent.sandbox.*,
bd_agent.safety.sqlglot_validator, bd_agent.tools.registry. (RF-070)
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from bd_agent.contracts import DatabaseGateway, MessagingGateway
from bd_agent.sandbox import (
    DockerRunner,
    collect_output,
    stage_query_to_parquet,
    validate_python_code,
)
from bd_agent.sandbox.output_collector import OutputError
from bd_agent.sandbox.stage import StagingError
from bd_agent.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Tool definition (Gemini schema)
# ---------------------------------------------------------------------------

_TOOL_NAME = "execute_python_report"

_TOOL_DESCRIPTION = (
    "Execute a Python script inside an isolated sandbox container that reads SQL results "
    "from /data/input.parquet and writes exactly one output file to /output/<output_filename>. "
    "The file is delivered to the user as a WhatsApp document. "
    "Use this ONLY for generating file reports (Excel, PNG, PDF, CSV). "
    "For simple data queries, use the curated tools or sql_fallback instead."
)

_TOOL_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sql_query": {
            "type": "string",
            "description": (
                "Read-only SELECT query. Will be validated and executed against gold schema. "
                "Results are available as a Parquet file at /data/input.parquet inside the container."
            ),
        },
        "sql_params": {
            "type": "object",
            "description": "Named parameters for the SQL query (can be empty object).",
        },
        "python_code": {
            "type": "string",
            "description": (
                "Python script to run inside the sandbox. Must read /data/input.parquet "
                "and write exactly one file to /output/<output_filename>. "
                "Allowed imports: pandas, numpy, matplotlib, openpyxl, pyarrow, PIL, "
                "datetime, math, json, csv, decimal, statistics, collections, itertools, "
                "functools, typing, re."
            ),
        },
        "output_filename": {
            "type": "string",
            "description": (
                "Basename of the output file (no slashes). "
                "Allowed extensions: .xlsx, .png, .pdf, .csv, .pptx."
            ),
        },
        "description": {
            "type": "string",
            "description": "Short description used as the file caption when sent to the user.",
        },
    },
    "required": ["sql_query", "sql_params", "python_code", "output_filename", "description"],
}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def execute_python_report_handler(
    gateway: DatabaseGateway | None,
    *,
    sql_query: str,
    sql_params: Mapping[str, Any],
    python_code: str,
    output_filename: str,
    description: str,
    context: Mapping[str, Any] | None = None,
    # Closures from register_into:
    _messaging: MessagingGateway,
    _runner: DockerRunner,
    _timeout_s: int,
) -> dict[str, Any]:
    """Execute python_code in a sandbox, send the output file to the user.

    This is the closure-bound handler.  register_into() wraps it with the
    wiring deps (messaging, runner, timeout_s); the ToolRegistry passes
    sql_query/sql_params/python_code/output_filename/description from the LLM
    call arguments, and injects context (which carries _jid).

    Returns:
        {ok: true, filename, file_size, exec_duration_ms} on success.
        {ok: false, phase, error[, exit_code]} on any failure.
    """
    # ------------------------------------------------------------------
    # Step 0: Extract _jid from context (fast-fail, no side effects)
    # ------------------------------------------------------------------
    _jid: str | None = (context or {}).get("_jid")
    if not _jid:
        return {
            "ok": False,
            "phase": "validation",
            "error": "_jid not found in context; cannot deliver the file",
        }

    # ------------------------------------------------------------------
    # Step 1: AST validation of python_code
    # ------------------------------------------------------------------
    validation = validate_python_code(python_code)
    if not validation.ok:
        return {
            "ok": False,
            "phase": "validation",
            "error": validation.reason or "AST validation failed",
        }

    # ------------------------------------------------------------------
    # Steps 2-9 all happen inside a tempdir; always cleaned up in finally
    # ------------------------------------------------------------------
    tempdir = Path(tempfile.mkdtemp(prefix="sb-"))
    try:
        data_dir = tempdir / "data"
        code_dir = tempdir / "code"
        output_dir = tempdir / "output"
        data_dir.mkdir()
        code_dir.mkdir()
        output_dir.mkdir(mode=0o777)

        # Step 2: Stage SQL → Parquet
        try:
            staged = stage_query_to_parquet(
                gateway=gateway,
                sql=sql_query,
                params=sql_params,
                target_dir=data_dir,
            )
        except StagingError as exc:
            # Distinguish SQL rejection (phase "sql") from other staging failures
            msg = str(exc)
            if "SQL rejected" in msg or "safety validator" in msg:
                return {"ok": False, "phase": "sql", "error": msg}
            return {"ok": False, "phase": "staging", "error": msg}

        # Step 3: Write script to temp file
        script_path = code_dir / "script.py"
        script_path.write_text(python_code, encoding="utf-8")

        # Step 4: Run container
        run_result = _runner.run(
            code_path=script_path,
            parquet_path=staged.parquet_path,
            output_dir=output_dir,
            timeout_s=_timeout_s,
        )

        if run_result.timed_out:
            return {
                "ok": False,
                "phase": "timeout",
                "error": f"timeout after {_timeout_s}s",
            }

        if run_result.exit_code != 0:
            return {
                "ok": False,
                "phase": "execution",
                "exit_code": run_result.exit_code,
                "error": run_result.stderr[-500:] if run_result.stderr else "container exited non-zero",
            }

        # Step 5: Collect output
        try:
            collected = collect_output(output_dir=output_dir, expected_filename=output_filename)
        except (OutputError, ValueError) as exc:
            return {"ok": False, "phase": "output", "error": str(exc)}

        # Step 6: Send file to user
        try:
            _messaging.send_file(_jid, collected.path, caption=description)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "phase": "send", "error": str(exc)}

        return {
            "ok": True,
            "filename": output_filename,
            "file_size": collected.size_bytes,
            "exec_duration_ms": run_result.duration_ms,
        }

    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_into(
    registry: ToolRegistry,
    *,
    gateway: DatabaseGateway,
    messaging: MessagingGateway,
    runner: DockerRunner,
    timeout_s: int = 30,
) -> None:
    """Register execute_python_report in registry with closure-bound deps.

    Args:
        registry: ToolRegistry to register into.
        gateway: DatabaseGateway for SQL execution.
        messaging: MessagingGateway for file delivery.
        runner: DockerRunner for container execution.
        timeout_s: Container timeout in seconds.
    """

    def _handler(
        _registry_gateway: DatabaseGateway | None,
        *,
        sql_query: str,
        sql_params: Mapping[str, Any],
        python_code: str,
        output_filename: str,
        description: str,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Use the wiring-time gateway (not the one the registry passes, which
        # is the agent-level DB gateway).  The sandbox handler uses its own
        # gateway closure for SQL staging.
        return execute_python_report_handler(
            gateway,
            sql_query=sql_query,
            sql_params=sql_params,
            python_code=python_code,
            output_filename=output_filename,
            description=description,
            context=context,
            _messaging=messaging,
            _runner=runner,
            _timeout_s=timeout_s,
        )

    registry.register(
        name=_TOOL_NAME,
        description=_TOOL_DESCRIPTION,
        params_schema=_TOOL_PARAMS_SCHEMA,
        handler=_handler,
    )
