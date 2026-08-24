/**
 * Tests for routes/schedule.tsx — read-only view of the systemd timer that
 * runs the daily (Unit 13).
 *
 * TDD: written BEFORE implementation.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { ScheduleStatus, ScheduleJournal } from "@/lib/queries";

const useScheduleMock = vi.fn();
const useScheduleJournalMock = vi.fn();

vi.mock("@/lib/queries", () => ({
  useSchedule: () => useScheduleMock(),
  useScheduleJournal: (limit?: number) => useScheduleJournalMock(limit),
}));

// Import AFTER the mock is registered.
import { SchedulePage } from "../schedule";

function queryResult<T>(data: T | undefined, isLoading = false) {
  return { data, isLoading, isError: false, error: null };
}

function queryError(error: unknown) {
  return { data: undefined, isLoading: false, isError: true, error };
}

const healthySchedule: ScheduleStatus = {
  unit: "excel-reporter-daily.timer",
  service: "excel-reporter-daily.service",
  available: true,
  error: null,
  active_state: "active",
  unit_file_state: "enabled",
  persistent: true,
  on_calendar: "Mon..Sat *-*-* 07:00:00",
  next_elapse: "Tue 2026-08-25 07:00:00 -03",
  last_trigger: "Mon 2026-08-24 07:00:56 -03",
  last_result: "success",
  last_exit_code: 0,
  last_finished_at: "Mon 2026-08-24 07:21:52 -03",
  unit_definition:
    "[Service]\nExecStart=/usr/bin/bash -c 'python scripts/run_daily.py'\n\n# pin-main.conf\nExecStartPre=-/usr/bin/git checkout main\n",
  apscheduler_is_placeholder: true,
};

const emptyJournal: ScheduleJournal = {
  unit: "excel-reporter-daily.service",
  available: true,
  error: null,
  entries: [],
};

describe("SchedulePage", () => {
  beforeEach(() => {
    useScheduleMock.mockReturnValue(queryResult(healthySchedule));
    useScheduleJournalMock.mockReturnValue(queryResult(emptyJournal));
  });

  it("shows the next run, the calendar expression and Persistent", () => {
    render(<SchedulePage />);

    expect(screen.getByTestId("next-elapse")).toHaveTextContent(
      "Tue 2026-08-25 07:00:00 -03",
    );
    expect(screen.getByTestId("on-calendar")).toHaveTextContent(
      "Mon..Sat *-*-* 07:00:00",
    );
    expect(screen.getByTestId("persistent")).toHaveTextContent(/sí/i);
  });

  it("reports the outcome of the last run", () => {
    render(<SchedulePage />);

    const last = screen.getByTestId("last-run");
    expect(within(last).getByText(/success/i)).toBeInTheDocument();
    expect(last).toHaveTextContent("Mon 2026-08-24 07:00:56 -03");
  });

  it("flags a failed last run distinctly from a successful one", () => {
    useScheduleMock.mockReturnValue(
      queryResult({
        ...healthySchedule,
        last_result: "exit-code",
        last_exit_code: 1,
      }),
    );
    render(<SchedulePage />);

    expect(screen.getByTestId("last-run-failed")).toBeInTheDocument();
  });

  it("says the timer is disabled instead of just showing its calendar", () => {
    useScheduleMock.mockReturnValue(
      queryResult({
        ...healthySchedule,
        active_state: "inactive",
        unit_file_state: "disabled",
        next_elapse: null,
      }),
    );
    render(<SchedulePage />);

    expect(screen.getByTestId("timer-inactive")).toBeInTheDocument();
  });

  it("warns that the APScheduler job is inert so systemd is the real trigger", () => {
    render(<SchedulePage />);
    expect(screen.getByTestId("apscheduler-warning")).toBeInTheDocument();
  });

  it("shows the unit definition including the pin-main drop-in", () => {
    render(<SchedulePage />);

    const unit = screen.getByTestId("unit-definition");
    expect(unit).toHaveTextContent("pin-main.conf");
    expect(unit).toHaveTextContent("checkout main");
  });

  it("says systemd could not be read instead of showing an empty schedule", () => {
    useScheduleMock.mockReturnValue(
      queryResult({
        ...healthySchedule,
        available: false,
        error: "systemctl is not available on this host",
        active_state: null,
        next_elapse: null,
        on_calendar: null,
      }),
    );
    render(<SchedulePage />);

    const unavailable = screen.getByTestId("schedule-unavailable");
    expect(unavailable).toHaveTextContent("systemctl is not available on this host");
    expect(screen.queryByTestId("next-elapse")).not.toBeInTheDocument();
    // "could not read" must never be dressed up as "no timer configured".
    expect(screen.queryByTestId("timer-inactive")).not.toBeInTheDocument();
  });

  it("surfaces a request failure rather than rendering blanks", () => {
    useScheduleMock.mockReturnValue(queryError(new Error("Network down")));
    render(<SchedulePage />);

    expect(screen.getByTestId("schedule-error")).toBeInTheDocument();
    expect(screen.getByText(/network down/i)).toBeInTheDocument();
  });

  it("renders journal entries and marks the error-priority ones", () => {
    useScheduleJournalMock.mockReturnValue(
      queryResult<ScheduleJournal>({
        unit: "excel-reporter-daily.service",
        available: true,
        error: null,
        entries: [
          {
            timestamp: "2026-08-24T10:21:52.000+00:00",
            priority: 6,
            identifier: "bash",
            message: "Todos los servicios OK (22/22)",
          },
          {
            timestamp: "2026-08-24T10:22:00.000+00:00",
            priority: 3,
            identifier: "bash",
            message: "Traceback: boom",
          },
        ],
      }),
    );
    render(<SchedulePage />);

    expect(screen.getByText(/Todos los servicios OK/)).toBeInTheDocument();
    const errorLine = screen.getByTestId("journal-line-1");
    expect(errorLine).toHaveAttribute("data-priority", "error");
  });

  it("says the journal could not be read instead of showing it as empty", () => {
    useScheduleJournalMock.mockReturnValue(
      queryResult<ScheduleJournal>({
        unit: "excel-reporter-daily.service",
        available: false,
        error: "journalctl timed out after 10s",
        entries: [],
      }),
    );
    render(<SchedulePage />);

    expect(screen.getByTestId("journal-unavailable")).toHaveTextContent(
      "journalctl timed out after 10s",
    );
  });

  it("says the last run outcome is unknown instead of painting it green", () => {
    // The backend degrades field by field: if `systemctl show <service>`
    // fails it still answers available:true with these three fields null.
    // Treating null as "not a failure" reported an unreadable service as a
    // successful run.
    useScheduleMock.mockReturnValue(
      queryResult({
        ...healthySchedule,
        last_result: null,
        last_exit_code: null,
        last_finished_at: null,
      }),
    );
    render(<SchedulePage />);

    expect(screen.getByTestId("last-run-unknown")).toBeInTheDocument();
    expect(screen.queryByTestId("last-run")).not.toBeInTheDocument();
    expect(screen.queryByTestId("last-run-failed")).not.toBeInTheDocument();
  });

  it("says the unit definition could not be read instead of hiding the panel", () => {
    useScheduleMock.mockReturnValue(
      queryResult({ ...healthySchedule, unit_definition: null }),
    );
    render(<SchedulePage />);

    expect(screen.getByTestId("unit-definition-missing")).toBeInTheDocument();
  });

  it("surfaces a thrown journal request rather than an empty log box", () => {
    useScheduleJournalMock.mockReturnValue(queryError(new Error("journal 500")));
    render(<SchedulePage />);

    expect(screen.getByTestId("journal-error")).toBeInTheDocument();
    expect(screen.getByText(/journal 500/i)).toBeInTheDocument();
    // An empty log and a failed request must not look the same.
    expect(screen.queryByText(/sin entradas en el journal/i)).not.toBeInTheDocument();
  });

  it("shows the journal as loading rather than as empty while in flight", () => {
    useScheduleJournalMock.mockReturnValue(queryResult(undefined, true));
    render(<SchedulePage />);

    expect(screen.getByTestId("journal-loading")).toBeInTheDocument();
    expect(screen.queryByText(/sin entradas en el journal/i)).not.toBeInTheDocument();
  });

  it("does not claim the journal is empty when it never arrived", () => {
    // TanStack can hand back data:undefined with isLoading and isError both
    // false (a paused/offline fetch). Falling through to "sin entradas" would
    // state as fact something that was never read.
    useScheduleJournalMock.mockReturnValue(queryResult(undefined));
    render(<SchedulePage />);

    expect(screen.getByTestId("journal-error")).toBeInTheDocument();
    expect(screen.queryByText(/sin entradas en el journal/i)).not.toBeInTheDocument();
  });

  it("renders journal times in the same clock as the systemd fields", () => {
    // The backend builds journal timestamps in UTC while every systemd field
    // is a local string. Slicing the ISO string showed the same instant three
    // hours apart, so a traceback and its run read as different events.
    useScheduleJournalMock.mockReturnValue(
      queryResult<ScheduleJournal>({
        unit: "excel-reporter-daily.service",
        available: true,
        error: null,
        entries: [
          {
            timestamp: "2026-08-24T10:21:52.000+00:00",
            priority: 6,
            identifier: "bash",
            message: "fin",
          },
        ],
      }),
    );
    render(<SchedulePage />);

    const expected = new Date("2026-08-24T10:21:52.000+00:00").toLocaleTimeString(
      "es-AR",
      { hour12: false },
    );
    expect(screen.getByTestId("journal-line-0")).toHaveTextContent(expected);
  });

  it("shows a loading state while the schedule is in flight", () => {
    useScheduleMock.mockReturnValue(queryResult(undefined, true));
    render(<SchedulePage />);

    expect(screen.getByTestId("schedule-loading")).toBeInTheDocument();
  });
});
