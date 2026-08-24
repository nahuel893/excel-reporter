"""
Management API routes: read-only view of the systemd user timer that runs the
daily flow.

Endpoints:
    GET /mgmt/schedule          — timer state, unit definition, last outcome
    GET /mgmt/schedule/journal  — journal entries for the daily service

Non-negotiable constraints (see spec RF-13, RF-14):
    - Which unit is inspected is decided here, never by the caller: TIMER_UNIT
      and SERVICE_UNIT are module constants and no query parameter can steer
      them.
    - Every command runs as an explicit argv list with shell=False and a
      timeout. A caller can put anything in ?since= and it arrives at
      journalctl as one literal argument.
    - Nothing here starts, stops, enables or edits a unit. Read only.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mgmt")

# The units this panel reports on. Constants on purpose — see RF-14.
TIMER_UNIT = "excel-reporter-daily.timer"
SERVICE_UNIT = "excel-reporter-daily.service"

# systemctl/journalctl are local and fast; a hung call must not pin a request
# thread for longer than someone is willing to stare at a spinner.
_COMMAND_TIMEOUT_SECONDS = 10

_TIMER_PROPERTIES = [
    "ActiveState",
    "UnitFileState",
    "Unit",
    "TimersCalendar",
    "NextElapseUSecRealtime",
    "LastTriggerUSec",
    "Persistent",
]

_SERVICE_PROPERTIES = [
    "ActiveState",
    "UnitFileState",
    "Result",
    "ExecMainStatus",
    "InactiveEnterTimestamp",
]

# TimersCalendar comes back as "{ OnCalendar=<expr> ; next_elapse=<when> }".
_ON_CALENDAR_RE = re.compile(r"OnCalendar=(?P<expr>.*?)\s*;")

# systemd prints "n/a" (and epoch-zero timestamps) for "never happened".
# Only for timestamps: "0" is a real value elsewhere — an exit status of 0 is
# success, not a missing reading.
_EMPTY_VALUES = {"", "n/a", "0", "infinity"}


class _CommandError(Exception):
    """A systemd command could not be run, or refused."""


def _run(argv: list[str]) -> str:
    """Run a read-only systemd command and return stdout.

    Always an argv list, never a shell string: values that came from the
    caller (only --since/--until) are separate elements, so shell metacharacters
    in them are data, not syntax.
    """
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise _CommandError(f"{argv[0]} is not available on this host") from exc
    except subprocess.TimeoutExpired as exc:
        raise _CommandError(f"{argv[0]} timed out after {_COMMAND_TIMEOUT_SECONDS}s") from exc
    except OSError as exc:
        raise _CommandError(f"could not run {argv[0]}: {exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise _CommandError(detail or f"{argv[0]} exited with {proc.returncode}")

    return proc.stdout


def _parse_show(output: str) -> dict[str, str]:
    """Parse `systemctl show` KEY=VALUE lines."""
    parsed: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            parsed[key.strip()] = value.strip()
    return parsed


def _clean(value: Optional[str]) -> Optional[str]:
    """Normalize systemd's several spellings of "nothing here" to None."""
    if value is None or value.strip().lower() in _EMPTY_VALUES:
        return None
    return value.strip()


def _on_calendar(timers_calendar: Optional[str]) -> Optional[str]:
    """Join every OnCalendar expression the timer declares.

    A unit may carry several. Returning only the first would show half a
    schedule with nothing saying the other half exists.
    """
    if not timers_calendar:
        return None
    exprs = [m.group("expr").strip() for m in _ON_CALENDAR_RE.finditer(timers_calendar)]
    exprs = [e for e in exprs if e]
    if not exprs:
        return None
    return " | ".join(exprs)


def _as_int(value: object) -> Optional[int]:
    """Best-effort int, for fields journald does not guarantee are scalars.

    A multi-valued or inaccessible journal field arrives as a list or dict, so
    catching only ValueError let int([54]) raise TypeError straight out of the
    endpoint — a 500 from the module that promises never to raise.
    """
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _journal_message(raw: object) -> Optional[str]:
    """Decode a journal MESSAGE, which is a string or an array of bytes.

    Decoded as UTF-8, not per-character: chr() on each byte maps them to
    Latin-1 codepoints, which mangles every non-ASCII character. The daily's
    own log lines contain them ("Excel Reporter — daily flow").
    """
    if raw is None or isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        try:
            return bytes(b for b in raw if isinstance(b, int)).decode("utf-8", "replace")
        except ValueError:
            # A value outside 0..255 is not a byte array; fall through.
            pass
    return str(raw)


def _unavailable(error: str) -> dict:
    """The honest empty answer.

    Every schedule field is None rather than absent or defaulted: a screen that
    renders a next-run time it never actually read is worse than one that says
    it could not look.
    """
    return {
        "unit": TIMER_UNIT,
        "service": SERVICE_UNIT,
        "available": False,
        "error": error,
        "active_state": None,
        "unit_file_state": None,
        "persistent": None,
        "on_calendar": None,
        "next_elapse": None,
        "last_trigger": None,
        "last_result": None,
        "last_exit_code": None,
        "last_finished_at": None,
        "unit_definition": None,
        "apscheduler_is_placeholder": True,
    }


# ---------------------------------------------------------------------------
# GET /mgmt/schedule
# ---------------------------------------------------------------------------


@router.get("/schedule")
def get_schedule() -> dict:
    """Report the timer that actually triggers the daily flow.

    Accepts no parameters: the unit is fixed (RF-14). Never raises on a
    missing or broken systemd — it answers `available: false` and says why,
    because "I could not read the schedule" and "there is no schedule" must
    not look the same on screen.
    """
    try:
        timer = _parse_show(
            _run([
                "systemctl", "--user", "show", TIMER_UNIT,
                *[f"--property={p}" for p in _TIMER_PROPERTIES],
            ])
        )
    except _CommandError as exc:
        logger.warning("Could not read %s: %s", TIMER_UNIT, exc)
        return _unavailable(str(exc))

    if not timer.get("ActiveState") or _clean(timer.get("UnitFileState")) is None:
        # systemctl show answers 0 for an unknown unit, with empty properties.
        return _unavailable(f"Unit {TIMER_UNIT} not loaded.")

    # The timer answered, so a failure in either secondary read degrades that
    # one field instead of throwing the whole response away.
    service: dict[str, str] = {}
    try:
        service = _parse_show(
            _run([
                "systemctl", "--user", "show", SERVICE_UNIT,
                *[f"--property={p}" for p in _SERVICE_PROPERTIES],
            ])
        )
    except _CommandError as exc:
        logger.warning("Could not read properties of %s: %s", SERVICE_UNIT, exc)

    unit_definition: Optional[str] = None
    try:
        unit_definition = _run(["systemctl", "--user", "cat", SERVICE_UNIT])
    except _CommandError as exc:
        logger.warning("Could not read the unit definition of %s: %s", SERVICE_UNIT, exc)

    return {
        "unit": TIMER_UNIT,
        "service": _clean(timer.get("Unit")) or SERVICE_UNIT,
        "available": True,
        "error": None,
        "active_state": _clean(timer.get("ActiveState")),
        "unit_file_state": _clean(timer.get("UnitFileState")),
        "persistent": _clean(timer.get("Persistent")) == "yes",
        "on_calendar": _on_calendar(timer.get("TimersCalendar")),
        "next_elapse": _clean(timer.get("NextElapseUSecRealtime")),
        "last_trigger": _clean(timer.get("LastTriggerUSec")),
        "last_result": _clean(service.get("Result")),
        # Not via _clean(): exit status 0 is the success case, and _clean reads
        # "0" as an absent value.
        "last_exit_code": _as_int(service.get("ExecMainStatus")),
        "last_finished_at": _clean(service.get("InactiveEnterTimestamp")),
        "unit_definition": unit_definition,
        # Design decision D1: api.py registers an APScheduler job named
        # 'daily-master' bound to a placeholder that only logs. The timer above
        # is the only thing that runs the daily, and the screen says so rather
        # than letting someone conclude the scheduler is doing the work.
        "apscheduler_is_placeholder": True,
    }


# ---------------------------------------------------------------------------
# GET /mgmt/schedule/journal
# ---------------------------------------------------------------------------


def _journal_timestamp(raw: Optional[str]) -> Optional[str]:
    """Convert journald's microseconds-since-epoch to ISO 8601."""
    micros = _as_int(raw)
    if micros is None:
        return None
    return datetime.fromtimestamp(micros / 1_000_000, tz=timezone.utc).isoformat()


@router.get("/schedule/journal")
def get_schedule_journal(
    since: Optional[str] = Query(None, max_length=200),
    until: Optional[str] = Query(None, max_length=200),
    limit: int = Query(200, ge=1, le=5000),
) -> dict:
    """Return recent journal entries for the daily service.

    `since` and `until` are handed to journalctl verbatim as their own argv
    elements — journalctl parses them, and a shell never sees them.
    """
    argv = [
        "journalctl", "--user",
        "--unit", SERVICE_UNIT,
        "--output", "json",
        "--no-pager",
        "--lines", str(limit),
    ]
    if since:
        argv += ["--since", since]
    if until:
        argv += ["--until", until]

    try:
        output = _run(argv)
    except _CommandError as exc:
        logger.warning("Could not read the journal for %s: %s", SERVICE_UNIT, exc)
        return {"unit": SERVICE_UNIT, "available": False, "error": str(exc), "entries": []}

    entries = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            # journalctl can emit a truncated line; losing it beats losing the
            # whole log view.
            logger.debug("Skipping unparseable journal line")
            continue
        identifier = record.get("SYSLOG_IDENTIFIER")
        entries.append({
            "timestamp": _journal_timestamp(record.get("__REALTIME_TIMESTAMP")),
            "priority": _as_int(record.get("PRIORITY")),
            "identifier": identifier if isinstance(identifier, str) else None,
            "message": _journal_message(record.get("MESSAGE")),
        })

    return {"unit": SERVICE_UNIT, "available": True, "error": None, "entries": entries}
