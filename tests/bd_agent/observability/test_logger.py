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
