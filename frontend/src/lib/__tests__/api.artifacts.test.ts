/**
 * Tests for the artifacts section of the api client — URL construction and
 * error translation. This is the seam the query hooks mock, so it is the one
 * place the transport contract is asserted.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError } from "../api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// Real Response objects, not hand-rolled fakes: a fake whose json() throws
// while its text() still resolves cannot reproduce a single-use body, which is
// exactly the failure mode these tests exist to catch.
function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const emptyTree = { services: [], unclassified: [] };

describe("api.artifacts.tree", () => {
  it("omits the query string entirely when unfiltered", async () => {
    fetchMock.mockResolvedValue(jsonResponse(emptyTree));

    await api.artifacts.tree();

    expect(fetchMock.mock.calls[0][0]).toBe("/mgmt/artifacts/tree");
  });

  it("sends slug and periodo as query parameters", async () => {
    fetchMock.mockResolvedValue(jsonResponse(emptyTree));

    await api.artifacts.tree("ventas", "2026-07");

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/mgmt/artifacts/tree?slug=ventas&periodo=2026-07",
    );
  });

  it("escapes a slug that needs encoding", async () => {
    fetchMock.mockResolvedValue(jsonResponse(emptyTree));

    await api.artifacts.tree("graficos cobertura&x");

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/mgmt/artifacts/tree?slug=graficos+cobertura%26x",
    );
  });

  it("throws ApiError carrying the status and the parsed detail", async () => {
    // A Response body can be read once, so this asserts on a single rejection
    // rather than calling the client twice.
    fetchMock.mockResolvedValue(jsonResponse({ detail: "nope" }, 400));

    const err = await api.artifacts.tree().catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(400);
    expect((err as ApiError).detail).toEqual({ detail: "nope" });
  });

  it("falls back to the response text when the error body is not JSON", async () => {
    fetchMock.mockResolvedValue(
      new Response("<html>upstream down</html>", {
        status: 502,
        headers: { "content-type": "text/html" },
      }),
    );

    await expect(api.artifacts.tree()).rejects.toMatchObject({
      status: 502,
      detail: "<html>upstream down</html>",
    });
  });
});

describe("api.artifacts.fileUrl", () => {
  it("encodes the path so spaces and slashes survive", () => {
    expect(api.artifacts.fileUrl("ventas/2026-07/Ventas Test.xlsx")).toBe(
      "/mgmt/artifacts/file?path=ventas%2F2026-07%2FVentas%20Test.xlsx",
    );
  });

  it("encodes a traversal attempt rather than emitting it raw", () => {
    expect(api.artifacts.fileUrl("../../etc/passwd")).toBe(
      "/mgmt/artifacts/file?path=..%2F..%2Fetc%2Fpasswd",
    );
  });
});
