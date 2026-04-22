"""Service-scoped output directory computation."""
from __future__ import annotations

import logging
import shutil
from datetime import date
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Granularity = Literal["month", "day"]


def prepare_accumulative_file(
    target_path: Path,
    legacy_slugs: list[str] | None = None,
) -> bool:
    """Migration + backup helper for services that accumulate sheets over time.

    For services that load an existing xlsx and ADD new sheets each run, this:

    1. Checks if the file exists at ``target_path`` (new per-period path).
    2. If NOT found, searches in order:
       a. Legacy flat path: ``DATA_OUTPUT / filename``
       b. Legacy slug folders (for renamed services): any .xlsx in
          ``DATA_OUTPUT / legacy_slug / period /`` — useful when both the
          service slug AND the file name changed after a rename.
    3. If found anywhere, migrates to ``target_path`` and creates a backup.

    Returns True if a file is ready to load, False if caller must create fresh.
    """
    import config.settings as _settings

    if not target_path.exists():
        found_legacy: Path | None = None

        # a. Legacy flat path (old pre-output-per-service layout)
        flat = _settings.DATA_OUTPUT / target_path.name
        if flat.exists():
            found_legacy = flat
        else:
            # b. Legacy slug folders (service was renamed — slug + filename both changed)
            period = target_path.parent.name  # e.g. "2026-04"
            for slug in (legacy_slugs or []):
                slug_dir = _settings.DATA_OUTPUT / slug / period
                if slug_dir.is_dir():
                    candidates = sorted(slug_dir.glob("*.xlsx"))
                    # Exclude backup files
                    candidates = [p for p in candidates if "_backup" not in p.stem]
                    if candidates:
                        found_legacy = candidates[0]
                        break

        if found_legacy is None:
            return False

        logger.info("Migrando archivo a nueva carpeta: %s -> %s", found_legacy, target_path)
        shutil.copy2(str(found_legacy), str(target_path))

    # File exists at target_path. Backup before modifying.
    backup = target_path.with_stem(target_path.stem + "_backup")
    shutil.copy2(str(target_path), str(backup))
    logger.info("Backup creado: %s", backup.name)
    return True


def service_output_dir(
    service_slug: str,
    fecha_desde: str | None,
    granularity: Granularity = "month",
) -> Path:
    """Compute data/output/{slug}/{period}/ — does NOT create dir.

    Args:
        service_slug: Slug identifying the service (e.g. 'ventas', 'stock-diario').
        fecha_desde: Date string in YYYY-MM-DD or ISO format. If None, uses today.
        granularity: 'month' -> period = YYYY-MM; 'day' -> period = YYYY-MM-DD.

    Returns:
        Path under DATA_OUTPUT/{service_slug}/{period}. Directory is NOT created.

    Raises:
        ValueError: If granularity is not 'month' or 'day'.
    """
    import config.settings as _settings  # call-time bind for test patching

    if granularity not in ("month", "day"):
        raise ValueError(f"granularity must be 'month' or 'day', got {granularity!r}")

    if fecha_desde:
        date_str = fecha_desde[:10]
        period = date_str[:7] if granularity == "month" else date_str
    else:
        today = date.today()
        period = today.strftime("%Y-%m" if granularity == "month" else "%Y-%m-%d")

    return _settings.DATA_OUTPUT / service_slug / period
