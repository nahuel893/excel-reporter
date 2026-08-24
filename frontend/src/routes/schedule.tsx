/**
 * Schedule route — read-only view of the systemd user timer that actually runs
 * the daily flow (RF-13, RF-14).
 *
 * Nothing here edits a unit. The screen answers one question: is the daily
 * going to run, and did the last one work. So every way of not knowing the
 * answer is kept distinct from "no" — a timer that is disabled, a systemd that
 * could not be read, and a backend that did not answer each say what they mean
 * instead of all rendering as a blank schedule.
 */

import { createRoute } from "@tanstack/react-router";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Clock,
  FileCode2,
  Info,
  PowerOff,
  XCircle,
} from "lucide-react";
import { rootRoute } from "./__root";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useSchedule,
  useScheduleJournal,
  type JournalEntry,
  type ScheduleStatus,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

export const scheduleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/schedule",
  component: SchedulePage,
});

/**
 * Render a journal timestamp in the viewer's local clock.
 *
 * The backend emits these in UTC while every systemd field on this page is a
 * local string. Slicing the ISO text put the same instant three hours from
 * itself, so a traceback and the run that produced it read as unrelated.
 */
function formatJournalTime(iso: string | null): string {
  if (!iso) return "--:--:--";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "--:--:--";
  return parsed.toLocaleTimeString("es-AR", { hour12: false });
}

/** syslog severity: 0 emerg … 7 debug. 3 (err) and below are failures. */
const ERROR_PRIORITY_MAX = 3;
const WARNING_PRIORITY = 4;

function priorityClass(priority: number | null): "error" | "warning" | "info" {
  if (priority === null) return "info";
  if (priority <= ERROR_PRIORITY_MAX) return "error";
  if (priority === WARNING_PRIORITY) return "warning";
  return "info";
}

function isTimerArmed(schedule: ScheduleStatus): boolean {
  return schedule.active_state === "active" && schedule.unit_file_state === "enabled";
}

// ─── Pieces ─────────────────────────────────────────────────────────────────

function Field({
  label,
  value,
  testId,
  mono = true,
}: {
  label: string;
  value: React.ReactNode;
  testId?: string;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn("mt-0.5 text-sm text-foreground", mono && "font-mono")}
        data-testid={testId}
      >
        {value ?? "—"}
      </p>
    </div>
  );
}

function Panel({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-lg border border-border p-6", className)}>{children}</div>
  );
}

function LastRun({ schedule }: { schedule: ScheduleStatus }) {
  // Three states, not two. The backend degrades field by field: when it
  // cannot read the service it still answers available:true with last_result
  // null. Folding null into "not a failure" reported an unreadable service as
  // a successful run — the exact confusion this screen exists to prevent.
  const outcome: "success" | "failed" | "unknown" =
    schedule.last_result === null
      ? "unknown"
      : schedule.last_result === "success"
        ? "success"
        : "failed";
  const testId =
    outcome === "failed"
      ? "last-run-failed"
      : outcome === "unknown"
        ? "last-run-unknown"
        : "last-run";
  return (
    <Panel className={cn(outcome === "failed" && "border-destructive/40")}>
      <div className="flex items-start gap-3" data-testid={testId}>
        {outcome === "failed" ? (
          <XCircle size={18} className="mt-0.5 shrink-0 text-destructive" aria-hidden="true" />
        ) : outcome === "unknown" ? (
          <AlertTriangle
            size={18}
            className="mt-0.5 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
        ) : (
          <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-primary" aria-hidden="true" />
        )}
        <div className="flex-1">
          {outcome === "unknown" ? (
            <p className="mb-3 text-sm text-foreground">
              No se pudo leer el estado de la última corrida.
              <span className="mt-1 block text-xs text-muted-foreground">
                El timer respondió, el servicio no. Esto no dice que el daily
                haya fallado — dice que no se pudo averiguar.
              </span>
            </p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Última corrida" value={schedule.last_trigger} />
            <Field label="Terminó" value={schedule.last_finished_at} />
            <Field label="Resultado" value={schedule.last_result} />
            <Field
              label="Código de salida"
              value={schedule.last_exit_code === null ? "—" : String(schedule.last_exit_code)}
            />
          </div>
        </div>
      </div>
    </Panel>
  );
}

function JournalLine({ entry, index }: { entry: JournalEntry; index: number }) {
  const level = priorityClass(entry.priority);
  return (
    <div
      className="flex gap-3 px-3 py-1"
      data-testid={`journal-line-${index}`}
      data-priority={level}
    >
      <span className="shrink-0 font-mono text-[11px] text-muted-foreground/60">
        {formatJournalTime(entry.timestamp)}
      </span>
      <span className="shrink-0 font-mono text-[11px] text-muted-foreground/60">
        {entry.identifier ?? "—"}
      </span>
      <span
        className={cn(
          "min-w-0 whitespace-pre-wrap break-words font-mono text-xs",
          level === "error" && "text-destructive",
          level === "warning" && "text-foreground",
          level === "info" && "text-muted-foreground",
        )}
      >
        {entry.message}
      </span>
    </div>
  );
}

function Notice({
  icon,
  title,
  detail,
  testId,
  tone = "info",
}: {
  icon: React.ReactNode;
  title: string;
  detail?: React.ReactNode;
  testId: string;
  // Only two renderings exist. A third name that painted identically to
  // "info" was a branch nothing could tell apart.
  tone?: "error" | "info";
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-lg border p-4",
        tone === "error"
          ? "border-destructive/40 bg-destructive/5"
          : "border-border bg-muted/20",
      )}
      data-testid={testId}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div className="min-w-0">
        <p
          className={cn(
            "text-sm font-medium",
            tone === "error" ? "text-destructive" : "text-foreground",
          )}
        >
          {title}
        </p>
        {detail ? (
          <p className="mt-1 break-words text-xs text-muted-foreground">{detail}</p>
        ) : null}
      </div>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export function SchedulePage() {
  const { data: schedule, isLoading, isError, error } = useSchedule();
  const {
    data: journal,
    isLoading: journalLoading,
    isError: journalIsError,
    error: journalError,
  } = useScheduleJournal(200);

  let content: React.ReactNode;

  if (isLoading) {
    content = (
      <div className="flex flex-col gap-4" data-testid="schedule-loading">
        <Skeleton className="h-32 w-full rounded-lg" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </div>
    );
  } else if (isError) {
    content = (
      <Notice
        tone="error"
        testId="schedule-error"
        icon={<AlertTriangle size={18} className="text-destructive" aria-hidden="true" />}
        title="No se pudo consultar la programación"
        detail={error instanceof Error ? error.message : String(error ?? "")}
      />
    );
  } else if (!schedule) {
    content = (
      <Notice
        tone="error"
        testId="schedule-error"
        icon={<AlertTriangle size={18} className="text-destructive" aria-hidden="true" />}
        title="No se pudo consultar la programación"
      />
    );
  } else if (!schedule.available) {
    // Distinct from a disabled timer: this is "no pude leer systemd", which
    // says nothing about whether the daily is going to run.
    content = (
      <Notice
        tone="error"
        testId="schedule-unavailable"
        icon={<AlertTriangle size={18} className="text-destructive" aria-hidden="true" />}
        title="No se pudo leer systemd"
        detail={
          <>
            {schedule.error}
            <br />
            Esto no dice que el daily no esté programado — dice que no se pudo
            averiguar.
          </>
        }
      />
    );
  } else {
    const armed = isTimerArmed(schedule);
    content = (
      <div className="flex flex-col gap-6">
        {!armed ? (
          <Notice
            tone="error"
            testId="timer-inactive"
            icon={<PowerOff size={18} className="text-destructive" aria-hidden="true" />}
            title="El timer no está armado"
            detail={`El daily no va a correr solo. Estado: ${
              schedule.active_state ?? "?"
            } / ${schedule.unit_file_state ?? "?"}.`}
          />
        ) : null}

        <Panel>
          <div className="mb-4 flex items-center gap-2">
            <Clock size={16} className="text-muted-foreground" aria-hidden="true" />
            <h2 className="text-sm font-semibold text-foreground">Próxima corrida</h2>
            <Badge variant={armed ? "default" : "destructive"} className="ml-auto">
              {schedule.active_state ?? "desconocido"} · {schedule.unit_file_state ?? "?"}
            </Badge>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Próxima" value={schedule.next_elapse} testId="next-elapse" />
            <Field label="OnCalendar" value={schedule.on_calendar} testId="on-calendar" />
            <Field
              label="Persistent"
              value={schedule.persistent ? "Sí" : "No"}
              testId="persistent"
              mono={false}
            />
            <Field label="Unit" value={schedule.unit} />
          </div>
          {schedule.persistent ? (
            <p className="mt-4 text-xs text-muted-foreground">
              Con <code className="font-mono">Persistent=true</code>, si la máquina
              estuvo apagada a la hora programada, la corrida se dispara apenas
              arranca.
            </p>
          ) : null}
        </Panel>

        <LastRun schedule={schedule} />

        <Notice
          tone="info"
          testId="apscheduler-warning"
          icon={<Info size={18} className="text-muted-foreground" aria-hidden="true" />}
          title="El scheduler interno de la API no dispara nada"
          detail={
            <>
              El job <code className="font-mono">daily-master</code> de APScheduler
              está ligado a un placeholder que solo escribe en el log. El único
              disparador real del daily es el timer de systemd que se ve arriba.
            </>
          }
        />

        <Panel>
          <div className="mb-3 flex items-center gap-2">
            <FileCode2 size={16} className="text-muted-foreground" aria-hidden="true" />
            <h2 className="text-sm font-semibold text-foreground">
              Definición de la unit
            </h2>
          </div>
          {schedule.unit_definition ? (
            <pre
              className="overflow-x-auto rounded-md bg-muted/30 p-3 font-mono text-xs text-muted-foreground"
              data-testid="unit-definition"
            >
              {schedule.unit_definition}
            </pre>
          ) : (
            // Hiding the panel would leave no trace that the definition was
            // supposed to be here — including the pin-main drop-in, which is
            // what decides which branch runs at 07:00.
            <p className="text-xs text-muted-foreground" data-testid="unit-definition-missing">
              No se pudo leer la definición de la unit.
            </p>
          )}
        </Panel>

        <Panel>
          <div className="mb-3 flex items-center gap-2">
            <CalendarClock size={16} className="text-muted-foreground" aria-hidden="true" />
            <h2 className="text-sm font-semibold text-foreground">Journal</h2>
          </div>
          {journalLoading ? (
            <Skeleton className="h-24 w-full rounded-md" data-testid="journal-loading" />
          ) : journalIsError ? (
            // A thrown request is not an empty log. Without this branch both
            // fell through to the same bordered empty box.
            <Notice
              tone="error"
              testId="journal-error"
              icon={
                <AlertTriangle size={18} className="text-destructive" aria-hidden="true" />
              }
              title="No se pudo consultar el journal"
              detail={
                journalError instanceof Error
                  ? journalError.message
                  : String(journalError ?? "")
              }
            />
          ) : journal && !journal.available ? (
            <Notice
              tone="error"
              testId="journal-unavailable"
              icon={
                <AlertTriangle size={18} className="text-destructive" aria-hidden="true" />
              }
              title="No se pudo leer el journal"
              detail={journal.error}
            />
          ) : !journal ? (
            // Neither loading nor a thrown error, yet nothing arrived — a
            // paused or offline fetch. Saying "sin entradas" here would state
            // as fact something that was never read.
            <Notice
              tone="error"
              testId="journal-error"
              icon={
                <AlertTriangle size={18} className="text-destructive" aria-hidden="true" />
              }
              title="No se pudo consultar el journal"
            />
          ) : journal.entries.length > 0 ? (
            <div className="max-h-96 overflow-y-auto rounded-md bg-muted/20 py-2">
              {journal.entries.map((entry, i) => (
                <JournalLine key={i} entry={entry} index={i} />
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Sin entradas en el journal para esta unit.
            </p>
          )}
        </Panel>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center gap-3">
        <CalendarClock size={20} className="text-muted-foreground" aria-hidden="true" />
        <h1 className="text-2xl font-bold tracking-tight">Programación</h1>
      </div>

      <Separator className="mb-6" />

      {content}
    </div>
  );
}
