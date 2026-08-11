/**
 * TanStack Query hooks for the Excel Reporter mgmt API.
 */

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

// ─── Config queries ───────────────────────────────────────────────────────────

export function useConfigs() {
  return useQuery({
    queryKey: ["configs"],
    queryFn: () => api.configs.list(),
    staleTime: 30_000,
  });
}

export function useConfig(filename: string) {
  return useQuery({
    queryKey: ["config", filename],
    queryFn: () => api.configs.get(filename),
    enabled: Boolean(filename),
    staleTime: 10_000,
  });
}

// ─── Reference data queries ───────────────────────────────────────────────────

export function useSucursales() {
  return useQuery({
    queryKey: ["refs", "sucursales"],
    queryFn: () => api.refs.sucursales(),
    staleTime: 5 * 60_000,
  });
}

export function useGenericos() {
  return useQuery({
    queryKey: ["refs", "genericos"],
    queryFn: () => api.refs.genericos(),
    staleTime: 5 * 60_000,
  });
}

export function useSupervisores() {
  return useQuery({
    queryKey: ["refs", "supervisores"],
    queryFn: () => api.refs.supervisores(),
    staleTime: 5 * 60_000,
  });
}

// ─── Contactos ────────────────────────────────────────────────────────────────

export function useContactos() {
  return useQuery({
    queryKey: ["contactos"],
    queryFn: () => api.contactos.get(),
    staleTime: 10_000,
  });
}

// ─── Runs queries ─────────────────────────────────────────────────────────────

export function useRuns(params?: {
  limit?: number;
  offset?: number;
  status?: string;
  config?: string;
}) {
  return useQuery({
    queryKey: ["runs", params],
    queryFn: () => api.runs.list(params),
    staleTime: 5_000,
    refetchInterval: 10_000,
  });
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.runs.get(runId),
    enabled: Boolean(runId),
    staleTime: 2_000,
  });
}

export function useActiveRuns() {
  return useQuery({
    queryKey: ["runs", "active"],
    queryFn: () => api.runs.list({ status: "running", limit: 10 }),
    refetchInterval: 3_000,
  });
}
