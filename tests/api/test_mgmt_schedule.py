"""
Tests for Unit 12 (RF-13, RF-14): mgmt_schedule.py — read-only view of the
systemd user timer that actually runs the daily.

TDD: written BEFORE implementation.

The security contract is the point of most of these: the unit name is a module
constant and never reaches subprocess from the client, and every argument is
passed as its own argv element with shell=False, so a caller cannot smuggle a
command through ?since=.
"""
import json
import subprocess
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SHOW_TIMER_OUTPUT = "\n".join([
    "ActiveState=active",
    "UnitFileState=enabled",
    "Unit=excel-reporter-daily.service",
    "TimersCalendar={ OnCalendar=Mon..Sat *-*-* 07:00:00 ; next_elapse=Tue 2026-08-25 07:00:00 -03 }",
    "NextElapseUSecRealtime=Tue 2026-08-25 07:00:00 -03",
    "LastTriggerUSec=Mon 2026-08-24 07:00:56 -03",
    "Persistent=yes",
])

SHOW_SERVICE_OUTPUT = "\n".join([
    "ActiveState=inactive",
    "UnitFileState=static",
    "Result=success",
    "ExecMainStatus=0",
    "InactiveEnterTimestamp=Mon 2026-08-24 07:12:03 -03",
])

CAT_OUTPUT = """# /home/nahuel/.config/systemd/user/excel-reporter-daily.service
[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c 'cd "/home/nahuel/projects/work/Informes Badie" && exec python scripts/run_daily.py'

# /home/nahuel/.config/systemd/user/excel-reporter-daily.service.d/pin-main.conf
[Service]
ExecStartPre=-/usr/bin/git -C "/home/nahuel/projects/work/Informes Badie" checkout main
"""

JOURNAL_JSON = "\n".join([
    json.dumps({
        "__REALTIME_TIMESTAMP": "1787565656865662",
        "PRIORITY": "6",
        "MESSAGE": "Starting Excel Reporter — daily flow...",
        "SYSLOG_IDENTIFIER": "systemd",
    }),
    json.dumps({
        "__REALTIME_TIMESTAMP": "1787565657072882",
        "PRIORITY": "3",
        "MESSAGE": "Already on 'main'",
        "SYSLOG_IDENTIFIER": "git",
    }),
])


def _completed(stdout: str, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _fake_run(argv, **kwargs):
    """Stand-in for subprocess.run that answers by inspecting argv."""
    if "journalctl" in argv[0]:
        return _completed(JOURNAL_JSON)
    if "cat" in argv:
        return _completed(CAT_OUTPUT)
    if "show" in argv and any(a.endswith(".timer") for a in argv):
        return _completed(SHOW_TIMER_OUTPUT)
    if "show" in argv:
        return _completed(SHOW_SERVICE_OUTPUT)
    return _completed("")


@pytest.fixture
def app():
    from src.api.routes.mgmt_schedule import router

    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def run_mock():
    with patch("src.api.routes.mgmt_schedule.subprocess.run", side_effect=_fake_run) as m:
        yield m


# ---------------------------------------------------------------------------
# GET /mgmt/schedule
# ---------------------------------------------------------------------------


def test_schedule_reports_the_timer_state(client, run_mock):
    body = client.get("/mgmt/schedule").json()

    assert body["unit"] == "excel-reporter-daily.timer"
    assert body["service"] == "excel-reporter-daily.service"
    assert body["active_state"] == "active"
    assert body["unit_file_state"] == "enabled"
    assert body["persistent"] is True
    assert body["on_calendar"] == "Mon..Sat *-*-* 07:00:00"
    assert body["next_elapse"] == "Tue 2026-08-25 07:00:00 -03"
    assert body["last_trigger"] == "Mon 2026-08-24 07:00:56 -03"


def test_schedule_includes_the_unit_definition_with_its_drop_ins(client, run_mock):
    """The pin-main drop-in is what makes production always run main — it has
    to be visible, not just the base unit."""
    body = client.get("/mgmt/schedule").json()
    assert "pin-main.conf" in body["unit_definition"]
    assert "checkout main" in body["unit_definition"]


def test_schedule_reports_the_last_run_outcome(client, run_mock):
    body = client.get("/mgmt/schedule").json()
    assert body["last_result"] == "success"
    assert body["last_exit_code"] == 0


def test_schedule_joins_every_on_calendar_expression(client):
    """A timer may declare several schedules; showing the first only would
    hide half of when the daily actually runs."""
    two_schedules = SHOW_TIMER_OUTPUT.replace(
        "TimersCalendar={ OnCalendar=Mon..Sat *-*-* 07:00:00 ; next_elapse=Tue 2026-08-25 07:00:00 -03 }",
        "TimersCalendar={ OnCalendar=Mon..Fri *-*-* 07:00:00 ; next_elapse=x } "
        "{ OnCalendar=Sat *-*-* 12:00:00 ; next_elapse=y }",
    )

    def multi(argv, **kwargs):
        if "show" in argv and any(a.endswith(".timer") for a in argv):
            return _completed(two_schedules)
        return _fake_run(argv, **kwargs)

    with patch("src.api.routes.mgmt_schedule.subprocess.run", side_effect=multi):
        body = client.get("/mgmt/schedule").json()

    assert "Mon..Fri *-*-* 07:00:00" in body["on_calendar"]
    assert "Sat *-*-* 12:00:00" in body["on_calendar"]


def test_schedule_degrades_field_by_field_when_a_secondary_read_fails(client):
    """The timer answered, so a failing `systemctl cat` costs the unit
    definition and nothing else."""
    def cat_fails(argv, **kwargs):
        if "cat" in argv:
            return _completed("", returncode=1, stderr="No files found")
        return _fake_run(argv, **kwargs)

    with patch("src.api.routes.mgmt_schedule.subprocess.run", side_effect=cat_fails):
        body = client.get("/mgmt/schedule").json()

    assert body["available"] is True
    assert body["unit_definition"] is None
    # Everything else survived.
    assert body["next_elapse"] == "Tue 2026-08-25 07:00:00 -03"
    assert body["last_result"] == "success"


def test_schedule_warns_that_the_apscheduler_job_is_inert(client, run_mock):
    """Design decision D1: the in-process 'daily-master' APScheduler job is a
    placeholder that only logs. systemd is the sole real trigger, and the
    screen must say so or it invites the wrong conclusion."""
    body = client.get("/mgmt/schedule").json()
    assert body["apscheduler_is_placeholder"] is True


# ---------------------------------------------------------------------------
# GET /mgmt/schedule/journal
# ---------------------------------------------------------------------------


def test_journal_returns_parsed_entries(client, run_mock):
    body = client.get("/mgmt/schedule/journal").json()

    assert len(body["entries"]) == 2
    first = body["entries"][0]
    assert first["message"] == "Starting Excel Reporter — daily flow..."
    assert first["priority"] == 6
    assert first["identifier"] == "systemd"
    assert first["timestamp"].startswith("2026-")


def test_journal_decodes_a_byte_array_message_as_utf8(client):
    """journald returns MESSAGE as an array of bytes when it is not plain text.

    Decoding byte-by-byte with chr() maps each UTF-8 byte to a Latin-1
    codepoint, so "—" comes out as "â\\x80\\x94" — and the daily's own log
    lines are full of accented text and em-dashes.
    """
    text = "Servicio terminó — 22/22 OK"
    record = json.dumps({
        "__REALTIME_TIMESTAMP": "1787565656865662",
        "PRIORITY": "6",
        "MESSAGE": list(text.encode("utf-8")),
        "SYSLOG_IDENTIFIER": "bash",
    })

    def with_bytes(argv, **kwargs):
        if "journalctl" in argv[0]:
            return _completed(record)
        return _fake_run(argv, **kwargs)

    with patch("src.api.routes.mgmt_schedule.subprocess.run", side_effect=with_bytes):
        body = client.get("/mgmt/schedule/journal").json()

    assert body["entries"][0]["message"] == text


def test_journal_survives_non_scalar_fields(client):
    """A multi-valued or inaccessible journal field arrives as a list or dict.

    int() on those raises TypeError, which used to escape as a 500 from the
    module whose whole contract is that it degrades instead of raising.
    """
    record = json.dumps({
        "__REALTIME_TIMESTAMP": ["1787565656865662"],
        "PRIORITY": [54],
        "MESSAGE": "raro pero real",
        "SYSLOG_IDENTIFIER": {"unreadable": True},
    })

    def weird(argv, **kwargs):
        if "journalctl" in argv[0]:
            return _completed(record)
        return _fake_run(argv, **kwargs)

    with patch("src.api.routes.mgmt_schedule.subprocess.run", side_effect=weird):
        r = client.get("/mgmt/schedule/journal")

    assert r.status_code == 200
    entry = r.json()["entries"][0]
    assert entry["message"] == "raro pero real"
    assert entry["priority"] is None
    assert entry["timestamp"] is None
    assert entry["identifier"] is None


def test_journal_skips_malformed_lines_instead_of_failing(client):
    """journalctl can emit a truncated line; one bad entry must not blank the
    whole log view."""
    def partial(argv, **kwargs):
        if "journalctl" in argv[0]:
            return _completed(JOURNAL_JSON + "\n{not json\n")
        return _fake_run(argv, **kwargs)

    with patch("src.api.routes.mgmt_schedule.subprocess.run", side_effect=partial):
        body = client.get("/mgmt/schedule/journal").json()
    assert len(body["entries"]) == 2


# ---------------------------------------------------------------------------
# Security — RF-14
# ---------------------------------------------------------------------------


def test_never_uses_a_shell(client, run_mock):
    client.get("/mgmt/schedule")
    client.get("/mgmt/schedule/journal")

    assert run_mock.call_count > 0
    for call in run_mock.call_args_list:
        # `is not True` would also pass when the key is absent, which asserts
        # nothing: it must be passed, and passed as False.
        assert call.kwargs.get("shell") is False
        # argv form, not a command string.
        assert isinstance(call.args[0], list)


def test_injection_in_since_arrives_as_one_literal_argv_element(client, run_mock):
    payload = "yesterday; rm -rf /"
    client.get("/mgmt/schedule/journal", params={"since": payload})

    journal_calls = [
        c for c in run_mock.call_args_list if "journalctl" in c.args[0][0]
    ]
    assert journal_calls, "journalctl was never invoked"
    argv = journal_calls[-1].args[0]
    # Present verbatim as its own element — never concatenated into another arg.
    assert payload in argv
    assert not any(a != payload and payload in a for a in argv)


def test_unit_name_is_a_constant_and_ignores_client_input(client, run_mock):
    """No query parameter may steer which unit is inspected."""
    client.get("/mgmt/schedule", params={"unit": "sshd.service"})
    client.get("/mgmt/schedule/journal", params={"unit": "sshd.service"})

    for call in run_mock.call_args_list:
        argv = call.args[0]
        assert "sshd.service" not in argv
        assert all("sshd" not in a for a in argv)


def test_every_subprocess_call_has_a_timeout(client, run_mock):
    """A hung systemctl must not hang the request thread forever."""
    client.get("/mgmt/schedule")
    client.get("/mgmt/schedule/journal")

    for call in run_mock.call_args_list:
        assert call.kwargs.get("timeout") is not None


def test_journal_rejects_an_out_of_range_limit(client, run_mock):
    assert client.get("/mgmt/schedule/journal", params={"limit": 0}).status_code == 422
    assert client.get("/mgmt/schedule/journal", params={"limit": 100_000}).status_code == 422


# ---------------------------------------------------------------------------
# Degradation — systemd may be absent or refuse
# ---------------------------------------------------------------------------


def test_schedule_reports_honestly_when_systemctl_is_missing(client):
    with patch(
        "src.api.routes.mgmt_schedule.subprocess.run",
        side_effect=FileNotFoundError("systemctl"),
    ):
        r = client.get("/mgmt/schedule")

    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["error"]
    # Never invent a schedule when it could not be read.
    assert body["next_elapse"] is None


def test_schedule_reports_honestly_when_the_timer_does_not_exist(client):
    def missing(argv, **kwargs):
        return _completed("", returncode=1, stderr="Unit excel-reporter-daily.timer not loaded.")

    with patch("src.api.routes.mgmt_schedule.subprocess.run", side_effect=missing):
        body = client.get("/mgmt/schedule").json()

    assert body["available"] is False
    assert "not loaded" in body["error"]


def test_journal_reports_honestly_when_systemctl_times_out(client):
    with patch(
        "src.api.routes.mgmt_schedule.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="journalctl", timeout=5),
    ):
        r = client.get("/mgmt/schedule/journal")

    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["entries"] == []


# ---------------------------------------------------------------------------
# RF-17 parity — this router is read-only too
# ---------------------------------------------------------------------------


def test_router_exposes_no_write_methods(app):
    schema = app.openapi()
    for path, methods in schema["paths"].items():
        if path.startswith("/mgmt/schedule"):
            assert set(methods) <= {"get"}, f"unexpected method on {path}: {set(methods)}"
