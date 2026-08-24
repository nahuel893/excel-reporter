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

// ─── Artifacts queries ────────────────────────────────────────────────────────

// Re-exported so consumers keep importing artifact types from one place; the
// definitions live in api.ts next to the client that returns them.
export type {
  ArtifactFileEntry,
  ArtifactPeriodNode,
  ArtifactServiceNode,
  ArtifactTree,
} from "./api";

export function useArtifactTree(slug?: string, periodo?: string) {
  return useQuery({
    queryKey: ["artifacts", "tree", slug ?? null, periodo ?? null],
    queryFn: () => api.artifacts.tree(slug, periodo),
    staleTime: 10_000,
  });
}

// ─── Schedule queries ─────────────────────────────────────────────────────────

export type { ScheduleStatus, ScheduleJournal, JournalEntry } from "./api";

export function useSchedule() {
  return useQuery({
    queryKey: ["schedule"],
    queryFn: () => api.schedule.get(),
    // The next-run time moves on its own, so a stale reading is misleading in
    // a way a stale config list is not.
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useScheduleJournal(limit = 200) {
  return useQuery({
    queryKey: ["schedule", "journal", limit],
    queryFn: () => api.schedule.journal({ limit }),
    staleTime: 30_000,
    // Same cadence as useSchedule: a live next-run time beside a frozen log
    // invites reading the log as current when it is not.
    refetchInterval: 60_000,
  });
}
