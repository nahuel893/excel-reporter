/**
 * Tests for the schedule section of the api client.
 *
 * The interesting property here is what the client CANNOT send: the backend
 * fixes which systemd unit it reports on, so no call from the panel may carry
 * a unit name.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "../api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("api.schedule.get", () => {
  it("requests the schedule with no parameters at all", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ unit: "x" }));

    await api.schedule.get();

    expect(fetchMock.mock.calls[0][0]).toBe("/mgmt/schedule");
  });

  it("takes no argument that could name a unit", () => {
    // Guards the RF-14 contract at the call site: the signature itself gives
    // the caller nowhere to put a unit name.
    expect(api.schedule.get.length).toBe(0);
  });
});

describe("api.schedule.journal", () => {
  it("omits the query string when unfiltered", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ entries: [] }));

    await api.schedule.journal();

    expect(fetchMock.mock.calls[0][0]).toBe("/mgmt/schedule/journal");
  });

  it("sends since, until and limit as query parameters", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ entries: [] }));

    await api.schedule.journal({ since: "yesterday", until: "now", limit: 50 });

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/mgmt/schedule/journal?since=yesterday&until=now&limit=50",
    );
  });

  it("encodes a shell-injection attempt instead of emitting it raw", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ entries: [] }));

    await api.schedule.journal({ since: "yesterday; rm -rf /" });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/mgmt/schedule/journal?since=yesterday%3B+rm+-rf+%2F");
    expect(url).not.toContain("; rm");
  });

  it("keeps limit=0 in the query rather than dropping it as falsy", async () => {
    // The backend rejects it with 422; silently swallowing it here would turn
    // a validation error into a silent default.
    fetchMock.mockResolvedValue(jsonResponse({ entries: [] }));

    await api.schedule.journal({ limit: 0 });

    expect(fetchMock.mock.calls[0][0]).toBe("/mgmt/schedule/journal?limit=0");
  });

  it("throws ApiError carrying the status when the backend refuses", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "bad limit" }, 422));

    const err = await api.schedule.journal({ limit: 99999 }).catch((e: unknown) => e);

    expect((err as { status: number }).status).toBe(422);
  });
});
