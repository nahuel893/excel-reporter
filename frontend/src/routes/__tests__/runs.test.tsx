/**
 * Tests for the Ejecuciones screen.
 *
 * The screen answers one question: what did the daily do this morning, and is
 * there anything to fix. So the assertions are about the answers that are easy
 * to get subtly wrong — a service that was skipped must not look like one that
 * ran, a report that was generated and then held back must not look like a
 * failure, and a list the backend told us is incomplete must not be presented
 * as the whole story.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { DailyRunDetail, DailyRunSummary } from "@/lib/queries";

const { runsMock, runMock } = vi.hoisted(() => ({
  runsMock: vi.fn(),
  runMock: vi.fn(),
}));

vi.mock("@/lib/queries", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/queries")>();
  return { ...actual, useDailyRuns: runsMock, useDailyRun: runMock };
});

import { RunsPage } from "../runs";

const SUMMARY: DailyRunSummary = {
  id: "20260824-070000-daily",
  started_at: "2026-08-24T10:00:00+00:00",
  finished_at: "2026-08-24T10:12:00+00:00",
  status: "success",
  exit_code: 0,
  triggered_by: "schedule",
  test_mode: false,
  hoy: "2026-08-24",
  solo_canal: null,
  git_branch: "main",
  git_sha: "abc1234",
  git_dirty: false,
};

function service(over: Partial<DailyRunDetail["services"][number]> = {}) {
  return {
    id: 1,
    orden: 1,
    servicio: "ventas",
    fecha_modo: "mes_a_hoy",
    fecha_desde: "2026-08-01",
    fecha_hasta: "2026-08-24",
    started_at: "2026-08-24T10:00:00+00:00",
    finished_at: "2026-08-24T10:01:00+00:00",
    duration_ms: 60_000,
    status: "success",
    exit_code: 0,
    skip_reason: null,
    delivery_status: "sent",
    delivery_gate: null,
    delivery_gate_detail: null,
    error_repr: null,
    error_traceback: null,
    has_log: false,
    is_synthetic: false,
    ...over,
  };
}

function detail(over: Partial<DailyRunDetail> = {}): DailyRunDetail {
  return {
    ...SUMMARY,
    overrides_snapshot: null,
    host_mem_available_mb: 4096,
    skips_reconstructed: true,
    services: [service()],
    artifacts: [],
    ...over,
  };
}

function listState(over: Record<string, unknown> = {}) {
  return { data: { total: 1, items: [SUMMARY] }, isLoading: false, isError: false, ...over };
}

function detailState(over: Record<string, unknown> = {}) {
  return { data: detail(), isLoading: false, isError: false, ...over };
}

beforeEach(() => {
  runsMock.mockReset();
  runMock.mockReset();
  runsMock.mockReturnValue(listState());
  runMock.mockReturnValue({ data: undefined, isLoading: false, isError: false });
});

// ---------------------------------------------------------------------------
// The history table
// ---------------------------------------------------------------------------

describe("history", () => {
  it("lists the runs the backend returned", () => {
    render(<RunsPage />);
    expect(screen.getByText("20260824-070000-daily")).toBeInTheDocument();
  });

  it("shows a loading state instead of an empty table", () => {
    runsMock.mockReturnValue(listState({ data: undefined, isLoading: true }));
    render(<RunsPage />);
    expect(screen.getByTestId("runs-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("runs-empty")).not.toBeInTheDocument();
  });

  it("distinguishes a failed request from an empty history", () => {
    runsMock.mockReturnValue(listState({ data: undefined, isError: true }));
    render(<RunsPage />);
    expect(screen.getByTestId("runs-error")).toBeInTheDocument();
    expect(screen.queryByTestId("runs-empty")).not.toBeInTheDocument();
  });

  it("says the history is empty when it genuinely is", () => {
    runsMock.mockReturnValue(listState({ data: { total: 0, items: [] } }));
    render(<RunsPage />);
    expect(screen.getByTestId("runs-empty")).toBeInTheDocument();
  });

  it("flags a run that did not come from the schedule", () => {
    runsMock.mockReturnValue(
      listState({
        data: { total: 1, items: [{ ...SUMMARY, test_mode: true }] },
      }),
    );
    render(<RunsPage />);
    expect(screen.getByTestId("badge-test-mode")).toBeInTheDocument();
  });

  it("flags a run made from a dirty tree", () => {
    runsMock.mockReturnValue(
      listState({ data: { total: 1, items: [{ ...SUMMARY, git_dirty: true }] } }),
    );
    render(<RunsPage />);
    expect(screen.getByTestId("badge-git-dirty")).toBeInTheDocument();
  });

  it("does not claim a clean tree when git was never read", () => {
    runsMock.mockReturnValue(
      listState({ data: { total: 1, items: [{ ...SUMMARY, git_dirty: null }] } }),
    );
    render(<RunsPage />);
    expect(screen.queryByTestId("badge-git-dirty")).not.toBeInTheDocument();
    expect(screen.getByTestId("badge-git-unknown")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// The detail panel
// ---------------------------------------------------------------------------

describe("detail", () => {
  beforeEach(() => {
    runMock.mockReturnValue(detailState());
  });

  it("lists the services of the selected run", () => {
    render(<RunsPage />);
    expect(screen.getByText("ventas")).toBeInTheDocument();
  });

  it("marks a rebuilt skip as never having run", () => {
    runMock.mockReturnValue(
      detailState({
        data: detail({
          services: [
            service(),
            service({
              id: null,
              orden: null,
              servicio: "avance-badie",
              status: "skipped",
              is_synthetic: true,
              skip_reason: "objetivos sin cargar",
              delivery_status: null,
            }),
          ],
        }),
      }),
    );
    render(<RunsPage />);

    const row = screen.getByTestId("service-avance-badie");
    expect(within(row).getByTestId("badge-skipped")).toBeInTheDocument();
    expect(within(row).getByText(/objetivos sin cargar/)).toBeInTheDocument();
  });

  it("says a skip's reason was not recorded rather than leaving it blank", () => {
    runMock.mockReturnValue(
      detailState({
        data: detail({
          services: [
            service({
              id: null,
              orden: null,
              servicio: "rechazos",
              status: "skipped",
              is_synthetic: true,
              skip_reason: null,
            }),
          ],
        }),
      }),
    );
    render(<RunsPage />);

    const row = screen.getByTestId("service-rechazos");
    expect(within(row).getByText(/sin motivo registrado/i)).toBeInTheDocument();
  });

  it("warns when the backend could not rebuild the skips", () => {
    runMock.mockReturnValue(
      detailState({ data: detail({ skips_reconstructed: false }) }),
    );
    render(<RunsPage />);
    expect(screen.getByTestId("skips-incomplete")).toBeInTheDocument();
  });

  it("does not warn when the list is complete", () => {
    render(<RunsPage />);
    expect(screen.queryByTestId("skips-incomplete")).not.toBeInTheDocument();
  });

  it("shows a suppressed delivery as a success that did not go out", () => {
    runMock.mockReturnValue(
      detailState({
        data: detail({
          services: [
            service({
              status: "success",
              delivery_status: "suppressed",
              delivery_gate: "ram_guard_whatsapp",
              delivery_gate_detail: "MemAvailable=812MB, umbral 3000",
            }),
          ],
        }),
      }),
    );
    render(<RunsPage />);

    const row = screen.getByTestId("service-ventas");
    // Generated fine…
    expect(within(row).getByTestId("badge-status")).toHaveTextContent(/success/i);
    // …and separately, never delivered, with the gate that stopped it.
    expect(within(row).getByTestId("badge-delivery")).toBeInTheDocument();
    expect(within(row).getByText(/ram_guard_whatsapp/)).toBeInTheDocument();
  });

  it("shows the traceback of a service that raised", () => {
    runMock.mockReturnValue(
      detailState({
        data: detail({
          services: [
            service({
              status: "exception",
              error_repr: "ValueError('boom')",
              error_traceback: "Traceback...\nValueError: boom",
              delivery_status: null,
            }),
          ],
        }),
      }),
    );
    render(<RunsPage />);
    expect(screen.getByText(/ValueError: boom/)).toBeInTheDocument();
  });

  it("offers a log link only where a log exists", () => {
    runMock.mockReturnValue(
      detailState({
        data: detail({
          services: [
            service({ servicio: "con-log", has_log: true, orden: 1 }),
            service({ id: 2, servicio: "sin-log", has_log: false, orden: 2 }),
          ],
        }),
      }),
    );
    render(<RunsPage />);

    expect(
      within(screen.getByTestId("service-con-log")).getByTestId("service-log-link"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("service-sin-log")).queryByTestId("service-log-link"),
    ).not.toBeInTheDocument();
  });

  it("lists the files a run produced", () => {
    runMock.mockReturnValue(
      detailState({
        data: detail({
          artifacts: [
            {
              id: 1,
              service_row_id: 1,
              path: "ventas/2026-08/Ventas.xlsx",
              kind: "xlsx",
              size_bytes: 8192,
              mtime: null,
              sent: true,
            },
          ],
        }),
      }),
    );
    render(<RunsPage />);
    expect(screen.getByText("ventas/2026-08/Ventas.xlsx")).toBeInTheDocument();
  });

  it("distinguishes a detail that failed to load from one not yet chosen", () => {
    runMock.mockReturnValue(detailState({ data: undefined, isError: true }));
    render(<RunsPage />);
    expect(screen.getByTestId("detail-error")).toBeInTheDocument();
  });
});
