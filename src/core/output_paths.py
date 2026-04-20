"""Service-scoped output directory computation."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

Granularity = Literal["month", "day"]


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
