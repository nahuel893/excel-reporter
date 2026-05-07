"""Tests for bd_agent/observability/logger.py — JSON structured logger (RF-090).

TDD — RED phase: all tests fail until logger.py is implemented.
"""
from __future__ import annotations

import hashlib
import json
import logging

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_8(jid: str) -> str:
    return hashlib.sha256(jid.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------

def _import():
    from bd_agent.observability.logger import (
        BDAgentLogger,
        JsonFormatter,
        get_bd_agent_logger,
    )
    return BDAgentLogger, JsonFormatter, get_bd_agent_logger


# ---------------------------------------------------------------------------
# JsonFormatter tests
# ---------------------------------------------------------------------------

class TestJsonFormatter:
    """JsonFormatter produces valid JSON with expected keys."""

    def test_import(self):
        _import()  # must not raise

    def test_json_formatter_formats_record_to_json(self):
        _, JsonFormatter, _ = _import()
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="bd_agent.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "hello"
        assert parsed["level"] == "INFO"
        assert "timestamp" in parsed

    def test_json_formatter_includes_extra_fields(self):
        _, JsonFormatter, _ = _import()
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="bd_agent",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="tool_call",
            args=(),
            exc_info=None,
        )
        record.jid_hash = "abc12345"
        record.tool_name = "get_ventas_cliente"
        record.duration_ms = 42
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["jid_hash"] == "abc12345"
        assert parsed["tool_name"] == "get_ventas_cliente"
        assert parsed["duration_ms"] == 42

    def test_json_formatter_never_contains_raw_jid(self):
        """No raw JID string should appear in the formatted output."""
        _, JsonFormatter, _ = _import()
        formatter = JsonFormatter()
        raw_jid = "5493871111111@s.whatsapp.net"
        record = logging.LogRecord(
            name="bd_agent",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="inbound_message",
            args=(),
            exc_info=None,
        )
        # accidentally set jid (not jid_hash) — formatter must mask it
        record.jid = raw_jid
        output = formatter.format(record)
        assert raw_jid not in output

    def test_json_formatter_output_is_single_line(self):
        _, JsonFormatter, _ = _import()
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="bd_agent",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "\n" not in output


# ---------------------------------------------------------------------------
# BDAgentLogger tests
# ---------------------------------------------------------------------------

class TestBDAgentLogger:
    """BDAgentLogger emits structured entries for each event type."""

    def _make_logger(self):
        BDAgentLogger, _, _ = _import()
        records: list[dict] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord):
                records.append(json.loads(self.format(record)))

        from bd_agent.observability.logger import JsonFormatter
        handler = CapturingHandler()
        handler.setFormatter(JsonFormatter())

        inner_logger = logging.getLogger(f"bd_agent.test.{id(records)}")
        inner_logger.handlers = [handler]
        inner_logger.propagate = False
        inner_logger.setLevel(logging.DEBUG)

        agent_logger = BDAgentLogger(logger=inner_logger)
        return agent_logger, records

    def test_log_inbound_emits_event_type(self):
        logger, records = self._make_logger()
        jid = "5493871111111@s.whatsapp.net"
        logger.log_inbound(jid=jid, text_len=20)
        assert len(records) == 1
        assert records[0]["event_type"] == "inbound_message"

    def test_log_inbound_hashes_jid(self):
        logger, records = self._make_logger()
        raw_jid = "5493871111111@s.whatsapp.net"
        logger.log_inbound(jid=raw_jid, text_len=20)
        entry = records[0]
        assert raw_jid not in json.dumps(entry)
        assert entry["jid_hash"] == _sha256_8(raw_jid)

    def test_log_tool_call_emits_tool_name_and_duration(self):
        logger, records = self._make_logger()
        jid = "5493871111111@s.whatsapp.net"
        logger.log_tool_call(jid=jid, tool_name="get_ventas_cliente", duration_ms=55, is_error=False)
        assert len(records) == 1
        entry = records[0]
        assert entry["event_type"] == "tool_call"
        assert entry["tool_name"] == "get_ventas_cliente"
        assert entry["duration_ms"] == 55
        assert entry["is_error"] is False

    def test_log_tool_call_error_flag(self):
        logger, records = self._make_logger()
        jid = "5493871111111@s.whatsapp.net"
        logger.log_tool_call(jid=jid, tool_name="run_sql_select", duration_ms=10, is_error=True)
        assert records[0]["is_error"] is True

    def test_log_outbound_emits_tokens(self):
        logger, records = self._make_logger()
        jid = "5493871111111@s.whatsapp.net"
        logger.log_outbound(jid=jid, tokens_in=500, tokens_out=150, duration_ms=3000)
        entry = records[0]
        assert entry["event_type"] == "outbound_message"
        assert entry["tokens_in"] == 500
        assert entry["tokens_out"] == 150
        assert entry["duration_ms"] == 3000

    def test_get_bd_agent_logger_returns_instance(self):
        _, _, get_bd_agent_logger = _import()
        result = get_bd_agent_logger()
        BDAgentLogger, _, _ = _import()
        assert isinstance(result, BDAgentLogger)

    def test_log_inbound_no_raw_jid_in_output(self):
        logger, records = self._make_logger()
        raw_jid = "5493879999999@s.whatsapp.net"
        logger.log_inbound(jid=raw_jid, text_len=5)
        dump = json.dumps(records)
        assert raw_jid not in dump

    def test_no_src_imports(self):
        """bd_agent.observability.logger must have zero 'from src.' imports (RF-070)."""
        import ast
        import pathlib
        src = pathlib.Path(__file__).parent.parent.parent.parent / "bd_agent" / "observability" / "logger.py"
        if not src.exists():
            pytest.skip("logger.py not yet created")
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src."):
                    pytest.fail(f"Found forbidden import: from {node.module} in logger.py")


# ---------------------------------------------------------------------------
# RF-091 RotatingFileHandler tests
# ---------------------------------------------------------------------------

class TestSetupErrorLogHandler:
    """setup_error_log_handler must produce a properly configured RotatingFileHandler.

    RF-091: Errors are written to bd_agent/errors.log; rotates at 10MB; 3 backups.
    """

    def test_function_importable(self):
        """setup_error_log_handler must be importable from bd_agent.observability.logger."""
        from bd_agent.observability.logger import setup_error_log_handler  # noqa: F401

    def test_returns_rotating_file_handler(self, tmp_path):
        """setup_error_log_handler returns a RotatingFileHandler instance."""
        from logging.handlers import RotatingFileHandler
        from bd_agent.observability.logger import setup_error_log_handler

        log_path = tmp_path / "errors.log"
        handler = setup_error_log_handler(log_path=log_path)
        assert isinstance(handler, RotatingFileHandler)

    def test_handler_level_is_error(self, tmp_path):
        """Handler must only emit ERROR and above (RF-091)."""
        from bd_agent.observability.logger import setup_error_log_handler

        log_path = tmp_path / "errors.log"
        handler = setup_error_log_handler(log_path=log_path)
        assert handler.level == logging.ERROR

    def test_handler_max_bytes_default(self, tmp_path):
        """Default max_bytes is 10MB (10 * 1024 * 1024)."""
        from bd_agent.observability.logger import setup_error_log_handler

        log_path = tmp_path / "errors.log"
        handler = setup_error_log_handler(log_path=log_path)
        assert handler.maxBytes == 10 * 1024 * 1024

    def test_handler_backup_count_default(self, tmp_path):
        """Default backup_count is 3 (RF-091: retain at most 3 backups)."""
        from bd_agent.observability.logger import setup_error_log_handler

        log_path = tmp_path / "errors.log"
        handler = setup_error_log_handler(log_path=log_path)
        assert handler.backupCount == 3

    def test_handler_custom_max_bytes(self, tmp_path):
        """max_bytes parameter is forwarded to the handler."""
        from bd_agent.observability.logger import setup_error_log_handler

        log_path = tmp_path / "errors.log"
        handler = setup_error_log_handler(log_path=log_path, max_bytes=1024)
        assert handler.maxBytes == 1024

    def test_handler_custom_backup_count(self, tmp_path):
        """backup_count parameter is forwarded to the handler."""
        from bd_agent.observability.logger import setup_error_log_handler

        log_path = tmp_path / "errors.log"
        handler = setup_error_log_handler(log_path=log_path, backup_count=5)
        assert handler.backupCount == 5

    def test_handler_writes_to_configured_path(self, tmp_path):
        """Handler writes to the path passed in log_path."""
        from bd_agent.observability.logger import setup_error_log_handler

        log_path = tmp_path / "test_errors.log"
        handler = setup_error_log_handler(log_path=log_path)
        # The baseFilename is the resolved absolute path string
        import os
        assert os.path.abspath(str(log_path)) == handler.baseFilename

    def test_handler_filters_debug_info(self, tmp_path):
        """DEBUG and INFO records must NOT be written (only ERROR+)."""
        from bd_agent.observability.logger import setup_error_log_handler

        log_path = tmp_path / "errors.log"
        handler = setup_error_log_handler(log_path=log_path)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

        inner = logging.getLogger(f"bd_agent.test.rf091.{id(log_path)}")
        inner.handlers = [handler]
        inner.propagate = False
        inner.setLevel(logging.DEBUG)

        inner.debug("should not appear")
        inner.info("should not appear")
        inner.warning("should not appear either")
        inner.error("this should appear")

        handler.flush()
        handler.close()

        content = log_path.read_text()
        assert "this should appear" in content
        assert "should not appear" not in content

    def test_handler_writes_error_record(self, tmp_path):
        """ERROR-level records are written to the log file."""
        from bd_agent.observability.logger import setup_error_log_handler

        log_path = tmp_path / "errors.log"
        handler = setup_error_log_handler(log_path=log_path)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

        inner = logging.getLogger(f"bd_agent.test.rf091.write.{id(log_path)}")
        inner.handlers = [handler]
        inner.propagate = False
        inner.setLevel(logging.DEBUG)

        inner.error("tool_execution_error: DB timeout")
        handler.flush()
        handler.close()

        content = log_path.read_text()
        assert "tool_execution_error" in content


# ---------------------------------------------------------------------------
# T-202 — BDAgentLogger.log_sandbox_execution (RF-171, RF-173)
# ---------------------------------------------------------------------------

class TestLogSandboxExecution:
    """T-202: BDAgentLogger.log_sandbox_execution emits structured JSON, no PII."""

    def _make_logger(self):
        from bd_agent.observability.logger import BDAgentLogger, JsonFormatter
        records: list[dict] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord):
                records.append(json.loads(self.format(record)))

        handler = CapturingHandler()
        handler.setFormatter(JsonFormatter())

        inner_logger = logging.getLogger(f"bd_agent.test.sandbox.{id(records)}")
        inner_logger.handlers = [handler]
        inner_logger.propagate = False
        inner_logger.setLevel(logging.DEBUG)

        agent_logger = BDAgentLogger(logger=inner_logger)
        return agent_logger, records

    def test_method_importable(self):
        from bd_agent.observability.logger import BDAgentLogger
        assert hasattr(BDAgentLogger, "log_sandbox_execution")

    def test_emits_sandbox_execution_event_type(self):
        logger, records = self._make_logger()
        logger.log_sandbox_execution(
            jid="5493871111111@s.whatsapp.net",
            code_hash="abc12345",
            query_hash="def67890",
            exit_code=0,
            duration_ms=1200,
            file_size=4096,
            error_type=None,
        )
        assert len(records) == 1
        assert records[0]["event_type"] == "sandbox_execution"

    def test_includes_all_required_fields(self):
        logger, records = self._make_logger()
        logger.log_sandbox_execution(
            jid="5493871111111@s.whatsapp.net",
            code_hash="abc12345",
            query_hash="def67890",
            exit_code=0,
            duration_ms=1200,
            file_size=4096,
            error_type=None,
        )
        entry = records[0]
        assert "jid_hash" in entry
        assert "code_hash" in entry
        assert "query_hash" in entry
        assert "exit_code" in entry
        assert "duration_ms" in entry
        assert "file_size" in entry
        assert "error_type" in entry

    def test_no_raw_jid_in_log(self):
        """RF-173: Raw JID must not appear in the log output."""
        logger, records = self._make_logger()
        raw_jid = "5493879999999@s.whatsapp.net"
        logger.log_sandbox_execution(
            jid=raw_jid,
            code_hash="abc12345",
            query_hash="def67890",
            exit_code=0,
            duration_ms=500,
            file_size=1024,
            error_type=None,
        )
        dump = json.dumps(records)
        assert raw_jid not in dump

    def test_jid_hash_is_8_chars(self):
        logger, records = self._make_logger()
        jid = "5493871111111@s.whatsapp.net"
        logger.log_sandbox_execution(
            jid=jid, code_hash="x", query_hash="y",
            exit_code=0, duration_ms=100, file_size=0, error_type=None,
        )
        assert len(records[0]["jid_hash"]) == 8

    def test_error_type_present_on_failure(self):
        logger, records = self._make_logger()
        logger.log_sandbox_execution(
            jid="5493871111111@s.whatsapp.net",
            code_hash="abc",
            query_hash="def",
            exit_code=1,
            duration_ms=300,
            file_size=0,
            error_type="validation",
        )
        assert records[0]["error_type"] == "validation"

    def test_error_type_null_on_success(self):
        logger, records = self._make_logger()
        logger.log_sandbox_execution(
            jid="5493871111111@s.whatsapp.net",
            code_hash="abc",
            query_hash="def",
            exit_code=0,
            duration_ms=800,
            file_size=2048,
            error_type=None,
        )
        assert records[0]["error_type"] is None

    def test_exit_code_propagated(self):
        logger, records = self._make_logger()
        logger.log_sandbox_execution(
            jid="5493871111111@s.whatsapp.net",
            code_hash="h1",
            query_hash="h2",
            exit_code=137,
            duration_ms=100,
            file_size=0,
            error_type="execution",
        )
        assert records[0]["exit_code"] == 137
