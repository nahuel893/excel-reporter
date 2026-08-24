/**
 * Tests for the daily-runs client.
 *
 * fetch is stubbed with real Response objects, never a hand-rolled fake. A
 * fake whose json() throws while text() still resolves cannot exist — a real
 * body reads once — and an earlier version of these tests passed happily
 * against production code that was broken exactly there.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError } from "../api";

const originalFetch = globalThis.fetch;

function stubFetch(response: Response) {
  const spy = vi.fn().mockResolvedValue(response);
  globalThis.fetch = spy as unknown as typeof fetch;
  return spy;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("api.daily.list", () => {
  it("asks for the history with no query string when given no filters", async () => {
    const spy = stubFetch(jsonResponse({ total: 0, items: [] }));

    const page = await api.daily.list();

    expect(page).toEqual({ total: 0, items: [] });
    expect(spy.mock.calls[0][0]).toBe("/mgmt/daily-runs");
  });

  it("passes every filter through as a query parameter", async () => {
    const spy = stubFetch(jsonResponse({ total: 0, items: [] }));

    await api.daily.list({
      limit: 25,
      offset: 50,
      status: "error",
      desde: "2026-08-01",
      hasta: "2026-08-24",
    });

    const url = new URL(spy.mock.calls[0][0] as string, "http://x");
    expect(url.pathname).toBe("/mgmt/daily-runs");
    expect(url.searchParams.get("limit")).toBe("25");
    expect(url.searchParams.get("offset")).toBe("50");
    expect(url.searchParams.get("status")).toBe("error");
    expect(url.searchParams.get("desde")).toBe("2026-08-01");
    expect(url.searchParams.get("hasta")).toBe("2026-08-24");
  });

  it("sends offset=0 rather than dropping it", async () => {
    // A falsy-check here would silently paginate from the wrong place.
    const spy = stubFetch(jsonResponse({ total: 0, items: [] }));

    await api.daily.list({ offset: 0 });

    const url = new URL(spy.mock.calls[0][0] as string, "http://x");
    expect(url.searchParams.get("offset")).toBe("0");
  });
});

describe("api.daily.get", () => {
  it("escapes the run id into the path", async () => {
    const spy = stubFetch(jsonResponse({ id: "a/b" }));

    await api.daily.get("a/b");

    expect(spy.mock.calls[0][0]).toBe("/mgmt/daily-runs/a%2Fb");
  });

  it("raises an ApiError carrying the backend's detail", async () => {
    stubFetch(jsonResponse({ detail: "Daily run 'nope' not found" }, 404));

    await expect(api.daily.get("nope")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("api.daily.serviceLogUrl", () => {
  it("builds a URL the browser can open directly", () => {
    expect(api.daily.serviceLogUrl("20260824-070000-daily", 3)).toBe(
      "/mgmt/daily-runs/20260824-070000-daily/services/3/log",
    );
  });

  it("escapes a run id that would otherwise break the path", () => {
    expect(api.daily.serviceLogUrl("a/b", 1)).toBe(
      "/mgmt/daily-runs/a%2Fb/services/1/log",
    );
  });
});
