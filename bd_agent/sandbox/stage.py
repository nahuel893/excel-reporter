"""bd_agent/sandbox/stage.py -- SQL query result staging to Parquet.

Executes a SELECT query via DatabaseGateway, validates it with the sqlglot
safety validator first, then writes the result as a Parquet file to a temp
directory so the sandbox container can read it as /data/input.parquet.

RF-121: successful staging writes a valid Parquet file.
RF-122: row cap enforcement (default 100_000 rows).
RF-123: sqlglot pre-validation before any DB call.
RF-124: parquet file lifecycle is managed by the caller (tempdir).

Deps: pandas, pyarrow (snappy compression), bd_agent.safety.sqlglot_validator,
bd_agent.contracts.DatabaseGateway.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StagedDataset:
    """Result of a successful staging operation.

    Attributes:
        parquet_path: Absolute path to the written parquet file.
        row_count: Number of rows written.
        bytes_written: Size of the parquet file in bytes.
    """

    parquet_path: Path
    row_count: int
    bytes_written: int


class StagingError(Exception):
    """Raised when staging fails (row cap exceeded, SQL unsafe, DB error, etc.)."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DEFAULT_MAX_ROWS = 100_000
_OUTPUT_FILENAME = "input.parquet"


def stage_query_to_parquet(
    *,
    gateway: Any,  # DatabaseGateway Protocol -- typed Any to avoid circular import
    sql: str,
    params: Mapping[str, Any],
    target_dir: Path,
    max_rows: int = _DEFAULT_MAX_ROWS,
) -> StagedDataset:
    """Execute SQL and write result as Parquet to target_dir/input.parquet.

    Steps:
    1. sqlglot pre-validation -- raises StagingError if SQL is unsafe.
    2. DB execution via gateway.execute_select.
    3. Row cap check -- raises StagingError if result exceeds max_rows.
    4. Write to target_dir/input.parquet (pyarrow snappy compression).

    Args:
        gateway: DatabaseGateway instance.
        sql: SELECT query string (will be validated by sqlglot first).
        params: Query parameters dict.
        target_dir: Directory where input.parquet will be written.
        max_rows: Maximum allowed rows (default 100_000).

    Returns:
        StagedDataset with parquet_path, row_count, bytes_written.

    Raises:
        StagingError: if SQL is unsafe, row cap exceeded, or I/O fails.
    """
    import pandas as pd

    from bd_agent.safety.sqlglot_validator import UnsafeQuery, validate

    # RF-123: validate SQL before any DB access
    try:
        validate(sql)
    except UnsafeQuery as exc:
        raise StagingError(f"SQL rejected by safety validator: {exc}") from exc

    # Execute query
    rows = gateway.execute_select(sql, dict(params), max_rows)

    # RF-122: row cap check
    if len(rows) > max_rows:
        raise StagingError(
            f"Query returned {len(rows)} rows which exceeds the "
            f"{max_rows} row cap. Reduce the query scope."
        )

    # Build DataFrame and write Parquet
    df = pd.DataFrame(rows)
    parquet_path = target_dir / _OUTPUT_FILENAME

    try:
        df.to_parquet(parquet_path, engine="pyarrow", compression="snappy", index=False)
    except Exception as exc:
        raise StagingError(f"Failed to write parquet: {exc}") from exc

    bytes_written = parquet_path.stat().st_size
    return StagedDataset(
        parquet_path=parquet_path,
        row_count=len(df),
        bytes_written=bytes_written,
    )
