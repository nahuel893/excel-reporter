"""Tests for bd_agent/observability/metrics.py — in-memory metrics counters.

TDD — RED phase: all tests fail until metrics.py is implemented.
"""
from __future__ import annotations

import threading
import time

import pytest


def _import():
    from bd_agent.observability.metrics import MetricsCollector, get_metrics
    return MetricsCollector, get_metrics


class TestMetricsCollector:
    """MetricsCollector tracks counters for all observed event types."""

    def _fresh(self):
        MetricsCollector, _ = _import()
        return MetricsCollector()

    def test_import(self):
        _import()

    def test_initial_counters_are_zero(self):
        m = self._fresh()
        snap = m.snapshot()
        assert snap["messages_received"] == 0
        assert snap["messages_sent"] == 0
        assert snap["errors_total"] == 0
        assert snap["tokens_in_total"] == 0
        assert snap["tokens_out_total"] == 0

    def test_record_inbound_increments_messages_received(self):
        m = self._fresh()
        m.record_inbound()
        m.record_inbound()
        snap = m.snapshot()
        assert snap["messages_received"] == 2

    def test_record_outbound_increments_messages_sent(self):
        m = self._fresh()
        m.record_outbound(tokens_in=100, tokens_out=50)
        snap = m.snapshot()
        assert snap["messages_sent"] == 1
        assert snap["tokens_in_total"] == 100
        assert snap["tokens_out_total"] == 50

    def test_record_outbound_accumulates_tokens(self):
        m = self._fresh()
        m.record_outbound(tokens_in=100, tokens_out=50)
        m.record_outbound(tokens_in=200, tokens_out=75)
        snap = m.snapshot()
        assert snap["tokens_in_total"] == 300
        assert snap["tokens_out_total"] == 125

    def test_record_tool_call_increments_by_name(self):
        m = self._fresh()
        m.record_tool_call("get_ventas_cliente")
        m.record_tool_call("get_ventas_cliente")
        m.record_tool_call("run_sql_select")
        snap = m.snapshot()
        assert snap["tool_calls_by_name"]["get_ventas_cliente"] == 2
        assert snap["tool_calls_by_name"]["run_sql_select"] == 1

    def test_record_error_increments_by_type(self):
        m = self._fresh()
        m.record_error("tool_execution_error")
        m.record_error("tool_execution_error")
        m.record_error("validation_error")
        snap = m.snapshot()
        assert snap["errors_by_type"]["tool_execution_error"] == 2
        assert snap["errors_by_type"]["validation_error"] == 1
        assert snap["errors_total"] == 3

    def test_snapshot_is_a_copy(self):
        """Mutating snapshot does not affect internal state."""
        m = self._fresh()
        m.record_inbound()
        snap1 = m.snapshot()
        snap1["messages_received"] = 9999
        snap2 = m.snapshot()
        assert snap2["messages_received"] == 1

    def test_uptime_seconds_increases(self):
        m = self._fresh()
        snap1 = m.snapshot()
        time.sleep(0.01)
        snap2 = m.snapshot()
        assert snap2["uptime_seconds"] >= snap1["uptime_seconds"]

    def test_thread_safety_concurrent_increments(self):
        """Concurrent increments from multiple threads produce correct totals."""
        m = self._fresh()
        n = 100

        def inc():
            for _ in range(n):
                m.record_inbound()

        threads = [threading.Thread(target=inc) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = m.snapshot()
        assert snap["messages_received"] == 10 * n

    def test_reset_clears_all_counters(self):
        m = self._fresh()
        m.record_inbound()
        m.record_outbound(tokens_in=100, tokens_out=50)
        m.record_tool_call("some_tool")
        m.record_error("some_error")
        m.reset()
        snap = m.snapshot()
        assert snap["messages_received"] == 0
        assert snap["messages_sent"] == 0
        assert snap["tokens_in_total"] == 0
        assert snap["tokens_out_total"] == 0
        assert snap["tool_calls_by_name"] == {}
        assert snap["errors_by_type"] == {}
        assert snap["errors_total"] == 0

    def test_get_metrics_returns_singleton(self):
        _, get_metrics = _import()
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2

    def test_no_src_imports(self):
        """bd_agent.observability.metrics must have zero 'from src.' imports (RF-070)."""
        import ast
        import pathlib
        src = pathlib.Path(__file__).parent.parent.parent.parent / "bd_agent" / "observability" / "metrics.py"
        if not src.exists():
            pytest.skip("metrics.py not yet created")
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src."):
                    pytest.fail(f"Found forbidden import: from {node.module} in metrics.py")


# ---------------------------------------------------------------------------
# T-203 — Sandbox metrics counters (RF-172)
# ---------------------------------------------------------------------------

class TestSandboxMetrics:
    """T-203: MetricsCollector exposes sandbox_executions_total,
    sandbox_failures_total, sandbox_duration_seconds, record_sandbox_execution."""

    def _fresh(self):
        MetricsCollector, _ = _import()
        return MetricsCollector()

    def test_sandbox_executions_total_in_snapshot(self):
        m = self._fresh()
        snap = m.snapshot()
        assert "sandbox_executions_total" in snap

    def test_sandbox_failures_total_in_snapshot(self):
        m = self._fresh()
        snap = m.snapshot()
        assert "sandbox_failures_total" in snap

    def test_sandbox_duration_seconds_in_snapshot(self):
        m = self._fresh()
        snap = m.snapshot()
        assert "sandbox_duration_seconds" in snap

    def test_record_sandbox_execution_method_exists(self):
        m = self._fresh()
        assert hasattr(m, "record_sandbox_execution")

    def test_success_increments_executions_total(self):
        m = self._fresh()
        m.record_sandbox_execution(reason=None, duration_seconds=1.5)
        snap = m.snapshot()
        assert snap["sandbox_executions_total"] == 1

    def test_failure_increments_both_total_and_failures(self):
        m = self._fresh()
        m.record_sandbox_execution(reason="validation", duration_seconds=0.1)
        snap = m.snapshot()
        assert snap["sandbox_executions_total"] == 1
        assert snap["sandbox_failures_total"] == 1

    def test_success_does_not_increment_failures(self):
        m = self._fresh()
        m.record_sandbox_execution(reason=None, duration_seconds=2.0)
        snap = m.snapshot()
        assert snap["sandbox_failures_total"] == 0

    def test_multiple_executions_accumulate(self):
        m = self._fresh()
        m.record_sandbox_execution(reason=None, duration_seconds=1.0)
        m.record_sandbox_execution(reason="timeout", duration_seconds=30.0)
        m.record_sandbox_execution(reason=None, duration_seconds=2.5)
        snap = m.snapshot()
        assert snap["sandbox_executions_total"] == 3
        assert snap["sandbox_failures_total"] == 1

    def test_duration_seconds_accumulates(self):
        m = self._fresh()
        m.record_sandbox_execution(reason=None, duration_seconds=1.0)
        m.record_sandbox_execution(reason=None, duration_seconds=2.0)
        snap = m.snapshot()
        # sandbox_duration_seconds is a list or sum — just verify it's non-empty/non-zero
        durations = snap["sandbox_duration_seconds"]
        if isinstance(durations, list):
            assert len(durations) == 2
        else:
            assert durations > 0

    def test_reset_clears_sandbox_counters(self):
        m = self._fresh()
        m.record_sandbox_execution(reason=None, duration_seconds=1.0)
        m.record_sandbox_execution(reason="sql", duration_seconds=0.5)
        m.reset()
        snap = m.snapshot()
        assert snap["sandbox_executions_total"] == 0
        assert snap["sandbox_failures_total"] == 0
        durations = snap["sandbox_duration_seconds"]
        if isinstance(durations, list):
            assert durations == []
        else:
            assert durations == 0
