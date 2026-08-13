"""Shared contract between the analysis modules and the workbook builder.

Every analysis module exposes a single `build(ctx) -> AnalysisResult`. The
builder never needs to know how an analysis was computed — only what tables,
headline numbers, alerts and methodology notes came out of it. That keeps the
analytics testable without openpyxl and the workbook testable without a database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src.core.data_loader import DataLoader


@dataclass
class AnalysisContext:
    """Everything an analysis module needs to run.

    Attributes:
        data_loader: live DB access.
        fecha_hasta: analysis cut-off (inclusive), YYYY-MM-DD.
        meses_ventana: length of the primary rolling window, in months.
        meses_historia: length of the long window used for seasonality and gaps.
    """

    data_loader: DataLoader
    fecha_hasta: str
    meses_ventana: int = 12
    meses_historia: int = 24

    def sql(self, query: str, params: dict | None = None) -> pd.DataFrame:
        """Run a read-only query and return a DataFrame."""
        return pd.read_sql(query, self.data_loader.engine, params=params)

    @property
    def hasta(self) -> date:
        return date.fromisoformat(self.fecha_hasta)

    def desde(self, meses: int | None = None) -> str:
        """Start of a rolling window of `meses` months ending at fecha_hasta."""
        meses = self.meses_ventana if meses is None else meses
        end = self.hasta
        total = end.month - meses
        year = end.year + (total - 1) // 12
        month = (total - 1) % 12 + 1
        day = min(end.day, 28)
        return date(year, month, day).isoformat()


@dataclass
class Alert:
    """A finding that must not be buried inside a table.

    Attributes:
        severity: 'critica' | 'alta' | 'media' | 'info'.
        title: one line, no jargon.
        detail: the quantified statement, with the number in it.
        amount: peso or volume figure at stake, for ranking. None if not monetary.
    """

    severity: str
    title: str
    detail: str
    amount: float | None = None


@dataclass
class Headline:
    """One KPI destined for the cover.

    `value` is already in display units; `number_format` is an Excel format string.
    `delta` is a fraction (0.12 = +12%) versus the comparison period, or None.
    """

    label: str
    value: float | int | str
    number_format: str
    delta: float | None = None
    note: str = ""
    higher_is_better: bool = True
    tone: str | None = None


@dataclass
class AnalysisResult:
    """What every analysis module returns.

    Attributes:
        name: human-readable family name.
        tables: named DataFrames, ready to write. Order is preserved.
        headlines: KPIs for the cover.
        alerts: findings that need to surface above the tables.
        notes: methodology and caveat lines for the Metodologia sheet.
        failed: set when the analysis could not run; `notes` explains why.
    """

    name: str
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    headlines: list[Headline] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    failed: bool = False

    def table(self, key: str) -> pd.DataFrame:
        """Fetch a table, or an empty frame if the analysis skipped it."""
        return self.tables.get(key, pd.DataFrame())
