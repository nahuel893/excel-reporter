/**
 * Typed fetch wrapper for the Excel Reporter mgmt API.
 *
 * API base is /mgmt (proxied to the FastAPI backend in dev via Vite,
 * served from same origin in prod).
 *
 * Throws ApiError (with status + detail) on non-2xx responses.
 */

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: unknown,
  ) {
    super(`API error ${status}: ${JSON.stringify(detail)}`);
    this.name = "ApiError";
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
    },
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }

  const res = await fetch(path, init);
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text();
    }
    throw new ApiError(res.status, detail);
  }

  // 204 No Content
  if (res.status === 204) {
    return undefined as T;
  }

  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return res.json() as Promise<T>;
  }
  return res.text() as unknown as Promise<T>;
}

// ─── Types ──────────────────────────────────────────────────────────────────

export interface ConfigListItem {
  filename: string;
  tipo: string;
  mtime: string;
}

export interface ConfigDetail {
  content: Record<string, unknown>;
  schema: Record<string, unknown>;
}

export interface PathExistsResponse {
  exists: boolean;
  is_file: boolean;
}

export interface ContactosContent {
  [key: string]: unknown;
}

export interface RunSummary {
  id: string;
  config_file: string;
  slug: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "success" | "error" | "interrupted";
  exit_code: number | null;
  triggered_by: "manual" | "schedule";
  test_mode: boolean;
}

export interface RunsPage {
  total: number;
  items: RunSummary[];
}

export interface TriggerRunRequest {
  config_filename: string;
  test_mode?: boolean;
}

export interface TriggerRunResponse {
  run_id: string;
  status: string;
}

// ─── Config endpoints ────────────────────────────────────────────────────────

export const api = {
  configs: {
    list: () => request<ConfigListItem[]>("GET", "/mgmt/configs"),

    get: (filename: string) =>
      request<ConfigDetail>("GET", `/mgmt/configs/${encodeURIComponent(filename)}`),

    update: (filename: string, content: Record<string, unknown>) =>
      request<{ filename: string; mtime: number }>(
        "PUT",
        `/mgmt/configs/${encodeURIComponent(filename)}`,
        content,
      ),

    schema: (tipo: string) =>
      request<Record<string, unknown>>(
        "GET",
        `/mgmt/configs/schema/${encodeURIComponent(tipo)}`,
      ),

    pathExists: (p: string) =>
      request<PathExistsResponse>(
        "GET",
        `/mgmt/configs/path-exists?path=${encodeURIComponent(p)}`,
      ),
  },

  refs: {
    sucursales: () => request<string[]>("GET", "/mgmt/refs/sucursales"),
    genericos: () => request<string[]>("GET", "/mgmt/refs/genericos"),
    supervisores: () => request<string[]>("GET", "/mgmt/refs/supervisores"),
  },

  contactos: {
    get: () => request<ContactosContent>("GET", "/mgmt/contactos"),
    update: (content: ContactosContent) =>
      request<ContactosContent>("PUT", "/mgmt/contactos", content),
  },

  runs: {
    list: (params?: {
      limit?: number;
      offset?: number;
      status?: string;
      config?: string;
    }) => {
      const qs = new URLSearchParams();
      if (params?.limit !== undefined) qs.set("limit", String(params.limit));
      if (params?.offset !== undefined) qs.set("offset", String(params.offset));
      if (params?.status) qs.set("status", params.status);
      if (params?.config) qs.set("config", params.config);
      const query = qs.toString();
      return request<RunsPage>("GET", `/mgmt/runs${query ? `?${query}` : ""}`);
    },

    get: (runId: string) =>
      request<RunSummary>("GET", `/mgmt/runs/${encodeURIComponent(runId)}`),

    trigger: (req: TriggerRunRequest) =>
      request<TriggerRunResponse>("POST", "/mgmt/runs", req),

    log: (runId: string) =>
      request<string>("GET", `/mgmt/runs/${encodeURIComponent(runId)}/log`),
  },
};
