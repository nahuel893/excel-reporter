/**
 * Tests for the artifacts query hook.
 *
 * The hook is tested against the api client seam, not against fetch: URL
 * construction belongs to api.ts and is covered there, so pinning the URL
 * string here would duplicate that contract in two places.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// vi.hoisted: vi.mock's factory is lifted above the imports, so a plain const
// here would not exist yet when the factory runs.
const { treeMock, scheduleMock, journalMock, dailyListMock, dailyGetMock } =
  vi.hoisted(() => ({
    treeMock: vi.fn(),
    scheduleMock: vi.fn(),
    journalMock: vi.fn(),
    dailyListMock: vi.fn(),
    dailyGetMock: vi.fn(),
  }));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      artifacts: { ...actual.api.artifacts, tree: treeMock },
      schedule: { ...actual.api.schedule, get: scheduleMock, journal: journalMock },
      daily: { ...actual.api.daily, list: dailyListMock, get: dailyGetMock },
    },
  };
});

import {
  useArtifactTree,
  useDailyRun,
  useDailyRuns,
  useSchedule,
  useScheduleJournal,
} from "../queries";
import { ApiError } from "../api";
import type { ArtifactTree } from "../api";

// Built once per test rather than inside the render body: a client rebuilt on
// every render would leave the tests relying on TanStack pinning the first
// instance into the observer instead of on a stable cache.
function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const emptyTree: ArtifactTree = { services: [], unclassified: [] };

describe("useArtifactTree", () => {
  beforeEach(() => {
    treeMock.mockReset();
  });

  it("returns the tree the client resolves", async () => {
    const tree: ArtifactTree = {
      services: [{ slug: "ventas", periods: [], unreadable: false }],
      unclassified: [],
    };
    treeMock.mockResolvedValue(tree);

    const { result } = renderHook(() => useArtifactTree(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(tree);
    expect(treeMock).toHaveBeenCalledWith(undefined, undefined);
  });

  it("passes slug and periodo straight through to the client", async () => {
    treeMock.mockResolvedValue(emptyTree);

    const { result } = renderHook(() => useArtifactTree("ventas", "2026-07"), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(treeMock).toHaveBeenCalledWith("ventas", "2026-07");
  });

  it("surfaces a failure as an error state rather than empty data", async () => {
    treeMock.mockRejectedValue(new ApiError(500, { detail: "boom" }));

    const { result } = renderHook(() => useArtifactTree(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
    expect((result.current.error as ApiError).status).toBe(500);
  });

  it("keys the cache by slug and periodo so drilling down refetches", async () => {
    treeMock.mockResolvedValue(emptyTree);

    const { result, rerender } = renderHook(
      ({ slug }: { slug?: string }) => useArtifactTree(slug),
      { wrapper: makeWrapper(), initialProps: { slug: undefined as string | undefined } },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    rerender({ slug: "ventas" });
    await waitFor(() => expect(treeMock).toHaveBeenCalledTimes(2));
    expect(treeMock).toHaveBeenLastCalledWith("ventas", undefined);
  });
});

describe("useSchedule", () => {
  beforeEach(() => {
    scheduleMock.mockReset();
  });

  it("calls the client with no arguments at all", async () => {
    scheduleMock.mockResolvedValue({ unit: "excel-reporter-daily.timer" });

    const { result } = renderHook(() => useSchedule(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(scheduleMock).toHaveBeenCalledWith();
  });

  it("surfaces a failure as an error state rather than empty data", async () => {
    scheduleMock.mockRejectedValue(new ApiError(500, "boom"));

    const { result } = renderHook(() => useSchedule(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});

describe("useScheduleJournal", () => {
  beforeEach(() => {
    journalMock.mockReset();
  });

  it("passes its limit through to the client", async () => {
    journalMock.mockResolvedValue({ entries: [] });

    const { result } = renderHook(() => useScheduleJournal(25), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(journalMock).toHaveBeenCalledWith({ limit: 25 });
  });

  it("defaults to 200 lines when no limit is given", async () => {
    journalMock.mockResolvedValue({ entries: [] });

    const { result } = renderHook(() => useScheduleJournal(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(journalMock).toHaveBeenCalledWith({ limit: 200 });
  });

  it("keys the cache by limit so changing it refetches", async () => {
    journalMock.mockResolvedValue({ entries: [] });

    const { result, rerender } = renderHook(
      ({ limit }: { limit: number }) => useScheduleJournal(limit),
      { wrapper: makeWrapper(), initialProps: { limit: 50 } },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    rerender({ limit: 500 });
    await waitFor(() => expect(journalMock).toHaveBeenCalledTimes(2));
    expect(journalMock).toHaveBeenLastCalledWith({ limit: 500 });
  });
});

describe("useDailyRuns", () => {
  beforeEach(() => {
    dailyListMock.mockReset();
  });

  it("asks for the first page when given no parameters", async () => {
    dailyListMock.mockResolvedValue({ total: 0, items: [] });

    const { result } = renderHook(() => useDailyRuns(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(dailyListMock).toHaveBeenCalledWith(undefined);
  });

  it("passes filters straight through to the client", async () => {
    dailyListMock.mockResolvedValue({ total: 0, items: [] });
    const params = { limit: 10, offset: 20, status: "error" };

    const { result } = renderHook(() => useDailyRuns(params), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(dailyListMock).toHaveBeenCalledWith(params);
  });

  it("keys the cache by the filters so changing a page refetches", async () => {
    dailyListMock.mockResolvedValue({ total: 0, items: [] });

    const { result, rerender } = renderHook(
      ({ offset }: { offset: number }) => useDailyRuns({ offset }),
      { wrapper: makeWrapper(), initialProps: { offset: 0 } },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    rerender({ offset: 50 });
    await waitFor(() => expect(dailyListMock).toHaveBeenCalledTimes(2));
    expect(dailyListMock).toHaveBeenLastCalledWith({ offset: 50 });
  });

  it("surfaces a failure as an error state rather than empty data", async () => {
    dailyListMock.mockRejectedValue(new ApiError(500, "boom"));

    const { result } = renderHook(() => useDailyRuns(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});

describe("useDailyRun", () => {
  beforeEach(() => {
    dailyGetMock.mockReset();
  });

  it("does not fetch until a run is actually selected", async () => {
    const { result } = renderHook(() => useDailyRun(undefined), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(dailyGetMock).not.toHaveBeenCalled();
  });

  it("fetches the run once one is selected", async () => {
    dailyGetMock.mockResolvedValue({ id: "20260824-070000-daily" });

    const { result } = renderHook(() => useDailyRun("20260824-070000-daily"), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(dailyGetMock).toHaveBeenCalledWith("20260824-070000-daily");
  });
});
