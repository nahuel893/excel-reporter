"""bd_agent/observability — structured logging + in-memory metrics (T-110).

Public exports:
    JsonFormatter      — stdlib logging Formatter producing single-line JSON
    BDAgentLogger      — high-level logger with log_inbound/log_tool_call/log_outbound
    get_bd_agent_logger — module-level singleton factory
    MetricsCollector   — thread-safe in-memory counter store
    get_metrics        — process-level singleton factory
"""
from bd_agent.observability.logger import BDAgentLogger, JsonFormatter, get_bd_agent_logger
from bd_agent.observability.metrics import MetricsCollector, get_metrics

__all__ = [
    "BDAgentLogger",
    "JsonFormatter",
    "get_bd_agent_logger",
    "MetricsCollector",
    "get_metrics",
]
