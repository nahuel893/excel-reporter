"""bd_agent/sandbox/output_collector.py -- Output file validator and collector.

After the sandbox container exits with code 0, this module validates and
collects the output file produced by the script.

Validations (RF-131, RF-132, RF-133):
- File exists at expected path (no extras collected)
- File size > 0 bytes
- File size <= 16 MB (WhatsApp document limit margin)
- MIME type is in the allowed set: xlsx, png, jpg, pdf, csv
- Path does not escape output_dir (no traversal)

RF-134: Cleanup of the output file is the caller's responsibility (tempdir).

Zero imports from src.* or bd_agent.* (pure stdlib).
"""
from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_OUTPUT_BYTES: int = 16 * 1024 * 1024  # 16 MB

# MIME types that map to allowed output formats (xlsx, png, jpg, pdf, csv).
# mimetypes.guess_type is used -- it returns the canonical MIME or None.
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        # Excel (xlsx)
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        # PNG
        "image/png",
        # JPEG
        "image/jpeg",
        # PDF
        "application/pdf",
        # CSV
        "text/csv",
        "text/plain",  # some systems report .csv as text/plain
        # PowerPoint (pptx) -- included as per RF-141 output_filename spec
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-powerpoint",
    }
)

# Extension-level fallback for MIME types mimetypes.guess_type may not know
_EXT_FALLBACK: dict[str, str] = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CollectedFile:
    """A validated output file ready for delivery.

    Attributes:
        path: Absolute host path to the file.
        size_bytes: File size in bytes.
        mime_type: Detected MIME type string.
    """

    path: Path
    size_bytes: int
    mime_type: str


class OutputError(Exception):
    """Raised when output collection fails.

    Attributes:
        reason: Human-readable reason string.
        phase: Always "output" -- for structured error propagation to LLM.
    """

    def __init__(self, reason: str, phase: str = "output") -> None:
        self.reason = reason
        self.phase = phase
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_output(
    *,
    output_dir: Path,
    expected_filename: str,
) -> CollectedFile:
    """Validate and collect the output file written by the sandbox container.

    Args:
        output_dir: Host directory that was mounted as /output inside container.
        expected_filename: Basename (no slashes) of the expected output file.

    Returns:
        CollectedFile with path, size_bytes, and mime_type.

    Raises:
        OutputError: if any validation fails (file missing, size, MIME, traversal).
        ValueError: if expected_filename contains path separators or is absolute.
    """
    # Reject traversal / absolute paths in filename
    _validate_filename_safety(expected_filename)

    target = output_dir / expected_filename

    # Resolve to catch any symlink escapes
    try:
        resolved = target.resolve()
        output_resolved = output_dir.resolve()
        if not str(resolved).startswith(str(output_resolved)):
            raise OutputError(
                f"Path traversal detected: '{expected_filename}' resolves outside output_dir"
            )
    except (OSError, ValueError):
        pass  # File doesn't exist yet -- handled below

    # RF-131: file must exist
    if not target.exists():
        raise OutputError(f"Output file not found: '{expected_filename}'")

    # Size checks (RF-132)
    size = os.stat(target).st_size
    if size == 0:
        raise OutputError(f"Output file is empty (0 bytes): '{expected_filename}'")
    if size > MAX_OUTPUT_BYTES:
        raise OutputError(
            f"Output file exceeds 16 MB limit ({size} bytes > {MAX_OUTPUT_BYTES}): "
            f"'{expected_filename}'"
        )

    # MIME type check (RF-133)
    mime = _detect_mime(target)
    if mime not in ALLOWED_MIME_TYPES:
        raise OutputError(
            f"Unsupported file type '{mime}' for '{expected_filename}'. "
            f"Allowed: xlsx, png, jpg, pdf, csv, pptx"
        )

    return CollectedFile(path=target, size_bytes=size, mime_type=mime)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_filename_safety(filename: str) -> None:
    """Raise ValueError if filename is an absolute path or contains traversal."""
    if filename.startswith("/"):
        raise ValueError(f"expected_filename must be a basename, got absolute path: '{filename}'")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise ValueError(
            f"expected_filename must be a plain filename without path separators or '..': "
            f"'{filename}'"
        )


def _detect_mime(path: Path) -> str:
    """Detect MIME type by extension, with fallback."""
    ext = path.suffix.lower()
    if ext in _EXT_FALLBACK:
        return _EXT_FALLBACK[ext]
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"
