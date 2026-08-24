/**
 * Ejecuciones route — the history of the daily flow (RF-10, RF-11, RF-12).
 *
 * The screen answers one question every morning: what did the daily do, and is
 * there anything to fix. Three distinctions carry that, and each is easy to
 * flatten by accident:
 *
 *   - a service that was SKIPPED never ran. It must not sit in the list looking
 *     like one that succeeded. Those rows arrive rebuilt from the registry with
 *     is_synthetic set, because a skipped service writes no row at all.
 *   - GENERATION and DELIVERY are separate. A report built correctly and then
 *     held back by the RAM guard is a success that was suppressed, and the gate
 *     that stopped it is the thing worth reading.
 *   - "we could not read it" is never "it did not happen". A failed request, a
 *     history that is genuinely empty, and a service list the backend already
 *     told us is incomplete each say so in their own words.
 */

import { useState } from "react";
import { createRoute } from "@tanstack/react-router";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  FlaskConical,
  GitBranch,
  HelpCircle,
  MinusCircle,
  Play,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { rootRoute } from "./__root";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useDailyRun,
  useDailyRuns,
  type DailyRunDetail,
  type DailyRunServiceRow,
  type DailyRunSummary,
} from "@/lib/queries";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export const runsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs",
  component: RunsPage,
});

const PAGE_SIZE = 25;

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/** The backend stores UTC; the reader lives in Salta. */
function localTime(iso: string | null): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("es-AR", { hour12: false });
}

function duration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  if (seconds < 90) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

function fileSize(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------
// Status vocabulary
// ---------------------------------------------------------------------------

type Tone = "ok" | "warn" | "bad" | "muted";

const TONE_CLASS: Record<Tone, string> = {
  ok: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
  warn: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  bad: "border-red-500/30 bg-red-500/10 text-red-400",
  muted: "border-border bg-muted/30 text-muted-foreground",
};

function runTone(status: string): Tone {
  if (status === "success") return "ok";
  if (status === "partial" || status === "interrupted") return "warn";
  if (status === "error") return "bad";
  return "muted"; // running, or a value this build does not know
}

function serviceTone(status: string): Tone {
  if (status === "success") return "ok";
  if (status === "error" || status === "exception") return "bad";
  if (status === "skipped") return "muted";
  return "warn"; // 'running' at read time means it never reported back
}

/**
 * How a delivery outcome should read.
 *
 * `sent` is the boring case and gets no colour. Everything else is a report
 * that did not reach someone, which is the reason to be on this screen.
 */
const DELIVERY_LABEL: Record<string, { text: string; tone: Tone }> = {
  sent: { text: "enviado", tone: "ok" },
  partial: { text: "un solo canal", tone: "warn" },
  suppressed: { text: "frenado", tone: "warn" },
  none_configured: { text: "sin canal configurado", tone: "muted" },
  test_redirect: { text: "modo test", tone: "muted" },
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function RunsPage() {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | undefined>(undefined);

  const runs = useDailyRuns({ limit: PAGE_SIZE, offset });
  // Opening this screen means asking about the last run, so it is already open.
  // An explicit click still wins, and survives a refetch that reorders nothing.
  const activeId = selected ?? runs.data?.items[0]?.id;
  const detail = useDailyRun(activeId);

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center gap-3">
        <Play size={20} className="text-muted-foreground" aria-hidden="true" />
        <h1 className="text-2xl font-bold tracking-tight">Ejecuciones</h1>
      </div>

      <Separator className="mb-6" />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <HistoryPanel
          runs={runs}
          offset={offset}
          selected={activeId}
          onSelect={setSelected}
          onOffset={setOffset}
        />
        <DetailPanel selected={activeId} detail={detail} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

interface HistoryPanelProps {
  runs: ReturnType<typeof useDailyRuns>;
  offset: number;
  selected: string | undefined;
  onSelect: (id: string) => void;
  onOffset: (offset: number) => void;
}

function HistoryPanel({ runs, offset, selected, onSelect, onOffset }: HistoryPanelProps) {
  if (runs.isLoading) {
    return (
      <section data-testid="runs-loading" className="space-y-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-16 w-full rounded-lg" />
        ))}
      </section>
    );
  }

  if (runs.isError || !runs.data) {
    return (
      <EmptyCard
        testId="runs-error"
        icon={<ShieldAlert size={20} className="text-red-400" aria-hidden="true" />}
        title="No se pudo leer el historial"
        detail="El panel no llegó al backend. Esto no dice nada sobre si el daily corrió."
      />
    );
  }

  if (runs.data.items.length === 0) {
    return (
      <EmptyCard
        testId="runs-empty"
        icon={<Play size={20} className="text-muted-foreground/50" aria-hidden="true" />}
        title="Todavía no hay corridas registradas"
        detail="La instrumentación empieza a escribir en la próxima corrida del daily."
      />
    );
  }

  const { total, items } = runs.data;
  const shown = offset + items.length;

  return (
    <section className="space-y-2">
      {items.map((run) => (
        <RunRow
          key={run.id}
          run={run}
          isSelected={run.id === selected}
          onSelect={() => onSelect(run.id)}
        />
      ))}

      <div className="flex items-center justify-between pt-2 text-xs text-muted-foreground">
        <span>
          {offset + 1}–{shown} de {total}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded border border-border px-2 py-1 disabled:opacity-40"
            disabled={offset === 0}
            onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Anteriores
          </button>
          <button
            type="button"
            className="rounded border border-border px-2 py-1 disabled:opacity-40"
            disabled={shown >= total}
            onClick={() => onOffset(offset + PAGE_SIZE)}
          >
            Siguientes
          </button>
        </div>
      </div>
    </section>
  );
}

function RunRow({
  run,
  isSelected,
  onSelect,
}: {
  run: DailyRunSummary;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      data-testid={`run-${run.id}`}
      onClick={onSelect}
      className={cn(
        "w-full rounded-lg border p-3 text-left transition-colors",
        isSelected
          ? "border-primary/40 bg-primary/5"
          : "border-border hover:bg-muted/30",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-xs">{run.id}</span>
        <Badge
          data-testid="badge-status"
          variant="outline"
          className={cn("shrink-0 text-[11px]", TONE_CLASS[runTone(run.status)])}
        >
          {run.status}
        </Badge>
      </div>

      <div className="mt-1 text-xs text-muted-foreground">{localTime(run.started_at)}</div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {run.test_mode && (
          <Badge
            data-testid="badge-test-mode"
            variant="outline"
            className={cn("gap-1 text-[10px]", TONE_CLASS.muted)}
          >
            <FlaskConical size={10} aria-hidden="true" />
            modo test
          </Badge>
        )}
        {run.solo_canal && (
          <Badge variant="outline" className={cn("text-[10px]", TONE_CLASS.warn)}>
            solo {run.solo_canal}
          </Badge>
        )}
        {run.git_branch && (
          <Badge variant="outline" className={cn("gap-1 text-[10px]", TONE_CLASS.muted)}>
            <GitBranch size={10} aria-hidden="true" />
            {run.git_branch}
          </Badge>
        )}
        {/* Three states, not two: true, false, and never read. */}
        {run.git_dirty === true && (
          <Badge
            data-testid="badge-git-dirty"
            variant="outline"
            className={cn("text-[10px]", TONE_CLASS.warn)}
          >
            árbol sucio
          </Badge>
        )}
        {run.git_dirty === null && (
          <Badge
            data-testid="badge-git-unknown"
            variant="outline"
            className={cn("gap-1 text-[10px]", TONE_CLASS.muted)}
          >
            <HelpCircle size={10} aria-hidden="true" />
            git sin leer
          </Badge>
        )}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

function DetailPanel({
  selected,
  detail,
}: {
  selected: string | undefined;
  detail: ReturnType<typeof useDailyRun>;
}) {
  if (!selected) {
    return (
      <EmptyCard
        testId="detail-none"
        icon={<Play size={20} className="text-muted-foreground/50" aria-hidden="true" />}
        title="Elegí una corrida"
        detail="Cada corrida muestra sus servicios, su entrega y los archivos que dejó."
      />
    );
  }

  if (detail.isLoading) {
    return (
      <section data-testid="detail-loading" className="space-y-2">
        <Skeleton className="h-24 w-full rounded-lg" />
        <Skeleton className="h-64 w-full rounded-lg" />
      </section>
    );
  }

  if (detail.isError || !detail.data) {
    return (
      <EmptyCard
        testId="detail-error"
        icon={<ShieldAlert size={20} className="text-red-400" aria-hidden="true" />}
        title="No se pudo leer esta corrida"
        detail="El backend no respondió. La corrida puede haber estado perfecta."
      />
    );
  }

  return <RunDetail run={detail.data} />;
}

function RunDetail({ run }: { run: DailyRunDetail }) {
  const artifactsByService = new Map<number, DailyRunDetail["artifacts"]>();
  for (const artifact of run.artifacts) {
    const bucket = artifactsByService.get(artifact.service_row_id) ?? [];
    bucket.push(artifact);
    artifactsByService.set(artifact.service_row_id, bucket);
  }

  return (
    <section className="space-y-4">
      <div className="rounded-lg border border-border p-4">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
          <Field label="Estado" value={run.status} />
          <Field label="Exit code" value={run.exit_code === null ? "—" : String(run.exit_code)} />
          <Field label="Disparada por" value={run.triggered_by} />
          <Field label="Fecha del informe" value={run.hoy} />
          <Field label="Inicio" value={localTime(run.started_at)} />
          <Field label="Fin" value={localTime(run.finished_at)} />
          <Field
            label="Memoria disponible"
            value={
              run.host_mem_available_mb === null
                ? "sin leer"
                : `${run.host_mem_available_mb} MB`
            }
          />
          <Field label="Commit" value={run.git_sha ? run.git_sha.slice(0, 8) : "sin leer"} />
        </dl>
      </div>

      {!run.skips_reconstructed && (
        <div
          data-testid="skips-incomplete"
          className={cn(
            "flex items-start gap-2 rounded-lg border p-3 text-xs",
            TONE_CLASS.warn,
          )}
        >
          <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            Esta lista tiene solo los servicios que dejaron registro. El backend no
            pudo leer el registro de servicios, asi que los salteados no aparecen —
            no significa que no los haya.
          </span>
        </div>
      )}

      <div className="space-y-2">
        {run.services.map((service) => (
          <ServiceRow
            key={service.servicio}
            runId={run.id}
            service={service}
            artifacts={
              service.id === null ? [] : artifactsByService.get(service.id) ?? []
            }
          />
        ))}
      </div>
    </section>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-mono">{value}</dd>
    </div>
  );
}

function ServiceRow({
  runId,
  service,
  artifacts,
}: {
  runId: string;
  service: DailyRunServiceRow;
  artifacts: DailyRunDetail["artifacts"];
}) {
  const delivery = service.delivery_status
    ? DELIVERY_LABEL[service.delivery_status] ?? {
        text: service.delivery_status,
        tone: "muted" as Tone,
      }
    : null;

  return (
    <div
      data-testid={`service-${service.servicio}`}
      className={cn(
        "rounded-lg border p-3",
        service.is_synthetic ? "border-dashed border-border/60" : "border-border",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{service.servicio}</span>

        {service.status === "skipped" ? (
          <Badge
            data-testid="badge-skipped"
            variant="outline"
            className={cn("gap-1 text-[10px]", TONE_CLASS.muted)}
          >
            <MinusCircle size={10} aria-hidden="true" />
            no corrió
          </Badge>
        ) : (
          <Badge
            data-testid="badge-status"
            variant="outline"
            className={cn("gap-1 text-[10px]", TONE_CLASS[serviceTone(service.status)])}
          >
            {service.status === "success" ? (
              <CheckCircle2 size={10} aria-hidden="true" />
            ) : (
              <XCircle size={10} aria-hidden="true" />
            )}
            {service.status}
          </Badge>
        )}

        {/* Delivery is its own axis and gets its own badge, always. */}
        {delivery && (
          <Badge
            data-testid="badge-delivery"
            variant="outline"
            className={cn("text-[10px]", TONE_CLASS[delivery.tone])}
          >
            {delivery.text}
          </Badge>
        )}

        <span className="ml-auto font-mono text-[11px] text-muted-foreground">
          {duration(service.duration_ms)}
        </span>

        {service.has_log && service.orden !== null && (
          <a
            data-testid="service-log-link"
            href={api.daily.serviceLogUrl(runId, service.orden)}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
          >
            <FileText size={11} aria-hidden="true" />
            log
          </a>
        )}
      </div>

      {service.status === "skipped" && (
        <p className="mt-1.5 text-xs text-muted-foreground">
          {service.skip_reason ?? "Sin motivo registrado"}
        </p>
      )}

      {service.delivery_gate && (
        <p className="mt-1.5 text-xs text-muted-foreground">
          Frenado por <span className="font-mono">{service.delivery_gate}</span>
          {service.delivery_gate_detail && ` — ${service.delivery_gate_detail}`}
        </p>
      )}

      {service.error_traceback && (
        <pre className="mt-2 max-h-48 overflow-auto rounded border border-red-500/20 bg-red-500/5 p-2 font-mono text-[11px] text-red-300">
          {service.error_traceback}
        </pre>
      )}

      {artifacts.length > 0 && (
        <ul className="mt-2 space-y-1">
          {artifacts.map((artifact) => (
            <li
              key={artifact.id}
              className="flex items-center gap-2 text-[11px] text-muted-foreground"
            >
              <FileText size={11} aria-hidden="true" />
              <span className="truncate font-mono">{artifact.path}</span>
              <span className="ml-auto shrink-0">{fileSize(artifact.size_bytes)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared empty state
// ---------------------------------------------------------------------------

function EmptyCard({
  testId,
  icon,
  title,
  detail,
}: {
  testId: string;
  icon: React.ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <section
      data-testid={testId}
      className="flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-border px-6 py-16 text-center"
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full border border-border bg-muted/30">
        {icon}
      </div>
      <p className="text-sm font-medium text-muted-foreground">{title}</p>
      <p className="max-w-sm text-xs text-muted-foreground/60">{detail}</p>
    </section>
  );
}
