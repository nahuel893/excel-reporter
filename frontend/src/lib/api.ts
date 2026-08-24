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
  const init: RequestInit = { method };
  if (body !== undefined) {
    // Only on requests that actually carry a body: a GET with a Content-Type
    // is a non-simple request for CORS and buys nothing.
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  const res = await fetch(path, init);
  if (!res.ok) {
    // Read the body exactly once. res.json() consumes it, so a json()-then-
    // text() fallback throws "Body is unusable" on every non-JSON error —
    // which is precisely the case the fallback existed for (a proxy's HTML
    // 502, a plain-text 500). The raw TypeError then reached the UI in place
    // of the real status.
    const raw = await res.text().catch(() => "");
    let detail: unknown = raw;
    try {
      detail = JSON.parse(raw);
    } catch {
      // Not JSON — keep the text as-is.
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

export interface ArtifactFileEntry {
  name: string;
  path: string;
  kind: string;
  size_bytes: number;
  mtime: string;
  /** Only present on PNG captures whose source workbook sits beside them. */
  sheet?: string;
  /** Only present on PNG captures, e.g. "A1:D10". */
  range?: string;
}

export interface ArtifactPeriodNode {
  periodo: string;
  /** Folder name outside the YYYY-MM / YYYY-MM-DD convention. */
  anomalous: boolean;
  /** The directory could not be listed — distinct from having no files. */
  unreadable: boolean;
  principal: ArtifactFileEntry[];
  imagenes: ArtifactFileEntry[];
  backups: ArtifactFileEntry[];
}

export interface ArtifactServiceNode {
  slug: string;
  periods: ArtifactPeriodNode[];
  /** The service directory could not be listed — its periods are unknown. */
  unreadable: boolean;
}

export interface ArtifactTree {
  services: ArtifactServiceNode[];
  unclassified: ArtifactFileEntry[];
}

/**
 * State of the systemd user timer that runs the daily flow.
 *
 * Every schedule field is nullable on purpose: when `available` is false the
 * backend could not read systemd, and reporting a next run it never actually
 * read would be worse than saying nothing.
 */
export interface ScheduleStatus {
  unit: string;
  service: string;
  available: boolean;
  error: string | null;
  active_state: string | null;
  unit_file_state: string | null;
  persistent: boolean | null;
  on_calendar: string | null;
  next_elapse: string | null;
  last_trigger: string | null;
  last_result: string | null;
  last_exit_code: number | null;
  last_finished_at: string | null;
  unit_definition: string | null;
  /** The in-process APScheduler job is inert; systemd is the real trigger. */
  apscheduler_is_placeholder: boolean;
}

export interface JournalEntry {
  timestamp: string | null;
  /** syslog severity: 0 emerg … 7 debug. 3 and below are errors. */
  priority: number | null;
  identifier: string | null;
  message: string | null;
}

export interface ScheduleJournal {
  unit: string;
  available: boolean;
  error: string | null;
  entries: JournalEntry[];
}

// ─── Daily runs ──────────────────────────────────────────────────────────────

/**
 * One run of the daily flow.
 *
 * git_dirty is `boolean | null` and the null matters: the recorder stores NULL
 * when it could not read git at all, which is not the same as a clean tree.
 */
export interface DailyRunSummary {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  exit_code: number | null;
  triggered_by: string;
  test_mode: boolean;
  hoy: string;
  solo_canal: string | null;
  git_branch: string | null;
  git_sha: string | null;
  git_dirty: boolean | null;
}

/**
 * One service inside a run.
 *
 * `status` and `delivery_status` are two independent axes: a report can be
 * generated correctly (`success`) and never leave the building (`suppressed`),
 * and `delivery_gate` says which gate stopped it.
 *
 * A row with `is_synthetic: true` was rebuilt at read time from the service
 * registry — it never ran, so it has no `id`, no `orden` and no log.
 */
export interface DailyRunServiceRow {
  id: number | null;
  orden: number | null;
  servicio: string;
  fecha_modo: string | null;
  fecha_desde: string | null;
  fecha_hasta: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  status: string;
  exit_code: number | null;
  skip_reason: string | null;
  delivery_status: string | null;
  delivery_gate: string | null;
  delivery_gate_detail: string | null;
  error_repr: string | null;
  error_traceback: string | null;
  has_log: boolean;
  is_synthetic: boolean;
}

export interface DailyRunArtifact {
  id: number;
  service_row_id: number;
  path: string;
  kind: string | null;
  size_bytes: number | null;
  mtime: string | null;
  sent: boolean;
}

export interface DailyRunDetail extends DailyRunSummary {
  overrides_snapshot: Record<string, unknown> | null;
  host_mem_available_mb: number | null;
  /** False when the backend could not read the service registry: the list of
   *  services is then only what ran, not everything that was configured. */
  skips_reconstructed: boolean;
  services: DailyRunServiceRow[];
  artifacts: DailyRunArtifact[];
}

export interface DailyRunsPage {
  total: number;
  items: DailyRunSummary[];
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

  artifacts: {
    tree: (slug?: string, periodo?: string) => {
      const qs = new URLSearchParams();
      if (slug) qs.set("slug", slug);
      if (periodo) qs.set("periodo", periodo);
      const query = qs.toString();
      return request<ArtifactTree>(
        "GET",
        `/mgmt/artifacts/tree${query ? `?${query}` : ""}`,
      );
    },

    /**
     * URL of a single artifact. Not a request(): the browser fetches this
     * directly as an <img> source or a download target.
     */
    fileUrl: (path: string) =>
      `/mgmt/artifacts/file?path=${encodeURIComponent(path)}`,
  },

  schedule: {
    // No unit parameter by design: the backend decides which unit it reports
    // on, so nothing the panel sends can point it at another service.
    get: () => request<ScheduleStatus>("GET", "/mgmt/schedule"),

    journal: (params?: { since?: string; until?: string; limit?: number }) => {
      const qs = new URLSearchParams();
      if (params?.since) qs.set("since", params.since);
      if (params?.until) qs.set("until", params.until);
      if (params?.limit !== undefined) qs.set("limit", String(params.limit));
      const query = qs.toString();
      return request<ScheduleJournal>(
        "GET",
        `/mgmt/schedule/journal${query ? `?${query}` : ""}`,
      );
    },
  },

  daily: {
    list: (params?: {
      limit?: number;
      offset?: number;
      status?: string;
      desde?: string;
      hasta?: string;
    }) => {
      const qs = new URLSearchParams();
      // Compared against undefined, not truthiness: offset=0 is the first page
      // and dropping it would paginate from somewhere else.
      if (params?.limit !== undefined) qs.set("limit", String(params.limit));
      if (params?.offset !== undefined) qs.set("offset", String(params.offset));
      if (params?.status) qs.set("status", params.status);
      if (params?.desde) qs.set("desde", params.desde);
      if (params?.hasta) qs.set("hasta", params.hasta);
      const query = qs.toString();
      return request<DailyRunsPage>(
        "GET",
        `/mgmt/daily-runs${query ? `?${query}` : ""}`,
      );
    },

    get: (runId: string) =>
      request<DailyRunDetail>(
        "GET",
        `/mgmt/daily-runs/${encodeURIComponent(runId)}`,
      ),

    /**
     * URL of one service's log. Not a request(): the browser opens it directly,
     * and the backend serves it as text/plain.
     */
    serviceLogUrl: (runId: string, orden: number) =>
      `/mgmt/daily-runs/${encodeURIComponent(runId)}/services/${orden}/log`,
  },
};
