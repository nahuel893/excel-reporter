"""bd_agent/sandbox -- Hardened Docker execution sandbox for LLM-generated Python reports.

Provides:
- validate_python_code: AST-based whitelist validator (RF-111..RF-115)
- stage_query_to_parquet: SQL -> Parquet staging for container input (RF-121..RF-124)
- DockerRunner: isolated docker run wrapper with all hardening flags (RF-101..RF-103)
- collect_output: output file validator and collector (RF-131..RF-134)
"""
from __future__ import annotations

from bd_agent.sandbox.output_collector import collect_output
from bd_agent.sandbox.runner import DockerRunner
from bd_agent.sandbox.stage import stage_query_to_parquet
from bd_agent.sandbox.validator import validate_python_code

__all__ = [
    "DockerRunner",
    "collect_output",
    "stage_query_to_parquet",
    "validate_python_code",
]
