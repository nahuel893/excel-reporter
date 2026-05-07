"""T-007: Failing tests for bd_agent/sandbox/stage.py -- Parquet staging.

TDD cycle: RED first (stage.py does not exist) -> GREEN -> REFACTOR.

Covers (RF-121, RF-122, RF-123, RF-124):
- Successful staging: parquet written, row_count matches, bytes > 0
- Row cap: >100_000 rows raises StagingError before writing
- SQL safety: sqlglot validator blocks DROP TABLE before DB call
- Cleanup: parquet file deleted on success and on failure
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fake DatabaseGateway for unit testing
# ---------------------------------------------------------------------------


class FakeDatabaseGateway:
    """Minimal DatabaseGateway that returns canned rows as a list of dicts."""

    def __init__(self, rows: list[dict[str, Any]], *, raise_on_call: Exception | None = None) -> None:
        self._rows = rows
        self._raise_on_call = raise_on_call
        self.calls: list[tuple[str, dict, int]] = []

    def execute_select(self, query: str, params: dict[str, Any], max_rows: int) -> list[dict]:
        self.calls.append((query, params, max_rows))
        if self._raise_on_call is not None:
            raise self._raise_on_call
        return self._rows

    def get_schema_doc(self) -> str:
        return "fake schema"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rows(n: int) -> list[dict[str, Any]]:
    return [{"id": i, "value": f"row_{i}"} for i in range(n)]


# ---------------------------------------------------------------------------
# Tests -- RED: stage.py does not exist yet
# ---------------------------------------------------------------------------


class TestStagingImports:
    """Module and key symbols must be importable."""

    def test_module_importable(self):
        from bd_agent.sandbox.stage import stage_query_to_parquet  # noqa: F401

    def test_staged_dataset_importable(self):
        from bd_agent.sandbox.stage import StagedDataset  # noqa: F401

    def test_staging_error_importable(self):
        from bd_agent.sandbox.stage import StagingError  # noqa: F401


class TestStagedDatasetContract:
    """StagedDataset is a frozen dataclass with parquet_path, row_count, bytes_written."""

    def test_fields_present(self):
        from bd_agent.sandbox.stage import StagedDataset

        p = Path("/tmp/fake.parquet")
        ds = StagedDataset(parquet_path=p, row_count=10, bytes_written=1024)
        assert ds.parquet_path == p
        assert ds.row_count == 10
        assert ds.bytes_written == 1024

    def test_frozen(self):
        from bd_agent.sandbox.stage import StagedDataset

        ds = StagedDataset(parquet_path=Path("/tmp/f.parquet"), row_count=1, bytes_written=100)
        with pytest.raises((AttributeError, TypeError)):
            ds.row_count = 99  # type: ignore[misc]


class TestHappyPath:
    """RF-121: successful staging writes a valid parquet file."""

    def test_parquet_file_written(self):
        from bd_agent.sandbox.stage import stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=_make_rows(5))
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            result = stage_query_to_parquet(
                gateway=gateway,
                sql="SELECT * FROM gold.ventas",
                params={},
                target_dir=target,
            )
            assert (target / "input.parquet").exists(), "Parquet file must be written"

    def test_row_count_matches(self):
        from bd_agent.sandbox.stage import stage_query_to_parquet

        rows = _make_rows(7)
        gateway = FakeDatabaseGateway(rows=rows)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = stage_query_to_parquet(
                gateway=gateway,
                sql="SELECT * FROM gold.ventas",
                params={},
                target_dir=Path(tmpdir),
            )
            assert result.row_count == 7

    def test_bytes_written_positive(self):
        from bd_agent.sandbox.stage import stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=_make_rows(3))
        with tempfile.TemporaryDirectory() as tmpdir:
            result = stage_query_to_parquet(
                gateway=gateway,
                sql="SELECT * FROM gold.ventas",
                params={},
                target_dir=Path(tmpdir),
            )
            assert result.bytes_written > 0

    def test_returned_path_is_correct(self):
        from bd_agent.sandbox.stage import stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=_make_rows(2))
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            result = stage_query_to_parquet(
                gateway=gateway,
                sql="SELECT * FROM gold.ventas",
                params={},
                target_dir=target,
            )
            assert result.parquet_path == target / "input.parquet"

    def test_params_passed_to_gateway(self):
        from bd_agent.sandbox.stage import stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=_make_rows(1))
        params = {"fecha": "2026-01-01"}
        with tempfile.TemporaryDirectory() as tmpdir:
            stage_query_to_parquet(
                gateway=gateway,
                sql="SELECT * FROM gold.ventas WHERE fecha = :fecha",
                params=params,
                target_dir=Path(tmpdir),
            )
        assert len(gateway.calls) == 1
        _, called_params, _ = gateway.calls[0]
        assert called_params == params


class TestRowCap:
    """RF-122: queries exceeding max_rows must raise StagingError before writing."""

    def test_over_default_limit_raises(self):
        from bd_agent.sandbox.stage import StagingError, stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=_make_rows(100_001))
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(StagingError, match="100"):
                stage_query_to_parquet(
                    gateway=gateway,
                    sql="SELECT * FROM gold.ventas",
                    params={},
                    target_dir=Path(tmpdir),
                )

    def test_custom_max_rows_enforced(self):
        from bd_agent.sandbox.stage import StagingError, stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=_make_rows(11))
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(StagingError):
                stage_query_to_parquet(
                    gateway=gateway,
                    sql="SELECT * FROM gold.ventas",
                    params={},
                    target_dir=Path(tmpdir),
                    max_rows=10,
                )

    def test_exactly_at_limit_succeeds(self):
        from bd_agent.sandbox.stage import stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=_make_rows(10))
        with tempfile.TemporaryDirectory() as tmpdir:
            result = stage_query_to_parquet(
                gateway=gateway,
                sql="SELECT * FROM gold.ventas",
                params={},
                target_dir=Path(tmpdir),
                max_rows=10,
            )
            assert result.row_count == 10


class TestSqlValidation:
    """RF-123: sqlglot validator blocks unsafe SQL before DB call."""

    def test_drop_table_rejected_before_db_call(self):
        from bd_agent.sandbox.stage import StagingError, stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=[])
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises((StagingError, Exception)):
                stage_query_to_parquet(
                    gateway=gateway,
                    sql="DROP TABLE gold.ventas",
                    params={},
                    target_dir=Path(tmpdir),
                )
        # DB must NOT have been called
        assert len(gateway.calls) == 0, "DB must not be called for unsafe SQL"

    def test_delete_rejected_before_db_call(self):
        from bd_agent.sandbox.stage import StagingError, stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=[])
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(Exception):
                stage_query_to_parquet(
                    gateway=gateway,
                    sql="DELETE FROM gold.ventas",
                    params={},
                    target_dir=Path(tmpdir),
                )
        assert len(gateway.calls) == 0


class TestCleanup:
    """RF-124: parquet file must be deleted after use (cleanup helper)."""

    def test_parquet_written_during_staging(self):
        """The file exists during the operation (cleanup happens in caller context)."""
        from bd_agent.sandbox.stage import stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=_make_rows(3))
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            result = stage_query_to_parquet(
                gateway=gateway,
                sql="SELECT * FROM gold.ventas",
                params={},
                target_dir=target,
            )
            # File must exist immediately after staging (before cleanup)
            assert result.parquet_path.exists()

    def test_parquet_not_written_on_row_cap_error(self):
        """When StagingError is raised (row cap), no parquet file is written."""
        from bd_agent.sandbox.stage import StagingError, stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=_make_rows(5))
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            with pytest.raises(StagingError):
                stage_query_to_parquet(
                    gateway=gateway,
                    sql="SELECT * FROM gold.ventas",
                    params={},
                    target_dir=target,
                    max_rows=4,
                )
            # No parquet file should have been written before the error
            assert not (target / "input.parquet").exists(), (
                "Parquet file must not be written when row cap is exceeded"
            )


class TestCleanupOnException:
    """RF-124: parquet file must be deleted after container exits (managed by tempdir)."""

    def test_tempdir_cleanup_removes_parquet(self):
        """Using tempfile.TemporaryDirectory ensures cleanup on context exit."""
        from bd_agent.sandbox.stage import stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=_make_rows(4))
        parquet_path_ref: list[Path] = []

        # Use TemporaryDirectory -- parquet must not exist after context exits
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            result = stage_query_to_parquet(
                gateway=gateway,
                sql="SELECT * FROM gold.ventas",
                params={},
                target_dir=target,
            )
            parquet_path_ref.append(result.parquet_path)
            assert result.parquet_path.exists(), "File must exist while in tempdir scope"

        # After context exit the tempdir (and parquet) are gone
        assert not parquet_path_ref[0].exists(), (
            "Parquet file must be deleted when tempdir is cleaned up"
        )

    def test_no_parquet_written_on_sql_rejection(self):
        """RF-124: no file is written if sqlglot rejects the SQL."""
        from bd_agent.sandbox.stage import stage_query_to_parquet

        gateway = FakeDatabaseGateway(rows=[])
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            with pytest.raises(Exception):
                stage_query_to_parquet(
                    gateway=gateway,
                    sql="DELETE FROM gold.ventas",
                    params={},
                    target_dir=target,
                )
            assert not (target / "input.parquet").exists()
