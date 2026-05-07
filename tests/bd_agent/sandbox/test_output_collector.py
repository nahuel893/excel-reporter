"""T-013: Failing tests for bd_agent/sandbox/output_collector.py.

TDD cycle: RED first (output_collector.py does not exist) -> GREEN -> REFACTOR.

Covers (RF-131, RF-132, RF-133, RF-134):
- Happy path: xlsx/png/pdf present, size ok, MIME accepted
- Size 0 rejected
- Size > 16 MB rejected
- File missing -> OutputError
- Traversal ../ rejected
- Unsupported MIME text/x-shellscript rejected
- Extra files in output_dir don't break collection
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def _write_file(path: Path, size_bytes: int = 1024, content: bytes | None = None) -> Path:
    """Write a file of the given size to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if content is not None:
        path.write_bytes(content)
    else:
        path.write_bytes(b"x" * size_bytes)
    return path


# ---------------------------------------------------------------------------
# Tests -- RED phase
# ---------------------------------------------------------------------------


class TestImports:
    """Module and key symbols must be importable."""

    def test_module_importable(self):
        from bd_agent.sandbox.output_collector import collect_output  # noqa: F401

    def test_collected_file_importable(self):
        from bd_agent.sandbox.output_collector import CollectedFile  # noqa: F401

    def test_output_error_importable(self):
        from bd_agent.sandbox.output_collector import OutputError  # noqa: F401

    def test_max_output_bytes_constant(self):
        from bd_agent.sandbox.output_collector import MAX_OUTPUT_BYTES

        assert MAX_OUTPUT_BYTES == 16 * 1024 * 1024


class TestCollectedFileContract:
    """CollectedFile dataclass contract."""

    def test_fields_present(self):
        from bd_agent.sandbox.output_collector import CollectedFile

        cf = CollectedFile(path=Path("/tmp/x.xlsx"), size_bytes=1024, mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        assert cf.path == Path("/tmp/x.xlsx")
        assert cf.size_bytes == 1024
        assert "openxmlformats" in cf.mime_type

    def test_frozen(self):
        from bd_agent.sandbox.output_collector import CollectedFile

        cf = CollectedFile(path=Path("/tmp/x.xlsx"), size_bytes=100, mime_type="application/vnd.ms-excel")
        with pytest.raises((AttributeError, TypeError)):
            cf.size_bytes = 999  # type: ignore[misc]


class TestHappyPath:
    """RF-131: File present and valid -> CollectedFile returned."""

    def test_xlsx_file_accepted(self):
        from bd_agent.sandbox.output_collector import collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            xlsx = _write_file(output_dir / "report.xlsx")
            result = collect_output(output_dir=output_dir, expected_filename="report.xlsx")
            assert result.path == xlsx
            assert result.size_bytes == 1024

    def test_png_file_accepted(self):
        from bd_agent.sandbox.output_collector import collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            _write_file(output_dir / "chart.png", size_bytes=512)
            result = collect_output(output_dir=output_dir, expected_filename="chart.png")
            assert result.size_bytes == 512

    def test_pdf_file_accepted(self):
        from bd_agent.sandbox.output_collector import collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            _write_file(output_dir / "report.pdf", size_bytes=2048)
            result = collect_output(output_dir=output_dir, expected_filename="report.pdf")
            assert result.size_bytes == 2048

    def test_csv_file_accepted(self):
        from bd_agent.sandbox.output_collector import collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            _write_file(output_dir / "data.csv", size_bytes=256)
            result = collect_output(output_dir=output_dir, expected_filename="data.csv")
            assert result.size_bytes == 256

    def test_extra_files_in_dir_dont_break_collection(self):
        """Other files in output_dir must not interfere with expected file collection."""
        from bd_agent.sandbox.output_collector import collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            _write_file(output_dir / "report.xlsx")
            _write_file(output_dir / "other_garbage.tmp")
            _write_file(output_dir / "another_file.log")
            result = collect_output(output_dir=output_dir, expected_filename="report.xlsx")
            assert result.path.name == "report.xlsx"

    def test_mime_type_detected(self):
        """MIME type must be non-empty for accepted files."""
        from bd_agent.sandbox.output_collector import collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            _write_file(output_dir / "report.xlsx")
            result = collect_output(output_dir=output_dir, expected_filename="report.xlsx")
            assert result.mime_type is not None
            assert len(result.mime_type) > 0


class TestFileMissing:
    """RF-131: File absent after container exit -> OutputError."""

    def test_missing_file_raises_output_error(self):
        from bd_agent.sandbox.output_collector import OutputError, collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with pytest.raises(OutputError) as exc_info:
                collect_output(output_dir=output_dir, expected_filename="report.xlsx")
            assert exc_info.value.phase == "output"

    def test_missing_file_error_message(self):
        from bd_agent.sandbox.output_collector import OutputError, collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(OutputError) as exc_info:
                collect_output(output_dir=Path(tmpdir), expected_filename="missing.xlsx")
            assert "not found" in str(exc_info.value).lower() or exc_info.value.reason


class TestSizeLimits:
    """RF-132: Size checks."""

    def test_zero_size_file_rejected(self):
        from bd_agent.sandbox.output_collector import OutputError, collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            empty = output_dir / "empty.xlsx"
            empty.write_bytes(b"")
            with pytest.raises(OutputError) as exc_info:
                collect_output(output_dir=output_dir, expected_filename="empty.xlsx")
            assert exc_info.value.phase == "output"

    def test_oversized_file_rejected(self):
        """Files over 16 MB must be rejected (RF-132)."""
        from bd_agent.sandbox.output_collector import MAX_OUTPUT_BYTES, OutputError, collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            big = output_dir / "big.xlsx"
            big.write_bytes(b"x" * (MAX_OUTPUT_BYTES + 1))
            with pytest.raises(OutputError) as exc_info:
                collect_output(output_dir=output_dir, expected_filename="big.xlsx")
            assert exc_info.value.phase == "output"

    def test_exactly_max_size_accepted(self):
        """A file of exactly MAX_OUTPUT_BYTES must be accepted."""
        from bd_agent.sandbox.output_collector import MAX_OUTPUT_BYTES, collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            exact = output_dir / "exact.xlsx"
            exact.write_bytes(b"x" * MAX_OUTPUT_BYTES)
            result = collect_output(output_dir=output_dir, expected_filename="exact.xlsx")
            assert result.size_bytes == MAX_OUTPUT_BYTES


class TestMimeValidation:
    """RF-133: MIME type validation."""

    def test_shell_script_rejected(self):
        """text/x-shellscript is not an allowed MIME type."""
        from bd_agent.sandbox.output_collector import OutputError, collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            shell = output_dir / "payload.sh"
            shell.write_bytes(b"#!/bin/bash\nrm -rf /\n")
            with pytest.raises(OutputError) as exc_info:
                collect_output(output_dir=output_dir, expected_filename="payload.sh")
            assert exc_info.value.phase == "output"


class TestPathTraversal:
    """RF-131 path safety: traversal attempts must be rejected."""

    def test_traversal_in_filename_rejected(self):
        """Filename with ../ must be rejected."""
        from bd_agent.sandbox.output_collector import OutputError, collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with pytest.raises((OutputError, ValueError)):
                collect_output(
                    output_dir=output_dir,
                    expected_filename="../etc/passwd",
                )

    def test_traversal_absolute_path_rejected(self):
        """Absolute path as expected_filename must be rejected."""
        from bd_agent.sandbox.output_collector import OutputError, collect_output

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises((OutputError, ValueError)):
                collect_output(
                    output_dir=Path(tmpdir),
                    expected_filename="/etc/passwd",
                )
