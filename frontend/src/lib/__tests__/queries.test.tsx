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
const { treeMock } = vi.hoisted(() => ({ treeMock: vi.fn() }));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: { ...actual.api, artifacts: { ...actual.api.artifacts, tree: treeMock } },
  };
});

import { useArtifactTree } from "../queries";
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
