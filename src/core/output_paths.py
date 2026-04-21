"""Service-scoped output directory computation."""
from __future__ import annotations

import logging
import shutil
from datetime import date
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Granularity = Literal["month", "day"]


def prepare_accumulative_file(target_path: Path) -> bool:
    """Migration + backup helper for services that accumulate sheets over time.

    For services that load an existing xlsx and ADD new sheets each run
    (e.g. mision-imposible), this function:

    1. Checks if the file already exists at ``target_path`` (new per-period path).
    2. If NOT found, looks for a legacy flat copy at ``DATA_OUTPUT / filename``
       and migrates it to ``target_path`` automatically.
    3. If found (either originally or after migration), creates a backup at
       ``{stem}_backup.xlsx`` next to the file so the prior state is preserved.

    Call this BEFORE opening the workbook. Returns True if a file is ready to
    load (i.e. the caller should ``load_workbook``), False if the caller must
    create a fresh workbook.
    """
    import config.settings as _settings

    if not target_path.exists():
        # Try legacy flat path: DATA_OUTPUT / filename
        legacy = _settings.DATA_OUTPUT / target_path.name
        if legacy.exists():
            logger.info(
                "Migrando archivo a carpeta de periodo: %s -> %s", legacy, target_path
            )
            shutil.copy2(str(legacy), str(target_path))
        else:
            return False  # no file found anywhere — caller must create fresh

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
