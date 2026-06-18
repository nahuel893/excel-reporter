/**
 * Dashboard — real data, quick trigger, recent runs table, live log panel.
 */

import { useState } from "react";
import { createRoute } from "@tanstack/react-router";
import {
  Activity,
  CalendarClock,
  Settings2,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  ChevronRight,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { rootRoute } from "./__root";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { LiveLogStream } from "@/components/LiveLogStream";
import { useActiveRuns, useConfigs, useRuns } from "@/lib/queries";
import { useTriggerRun } from "@/lib/mutations";
import { cn } from "@/lib/utils";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: DashboardPage,
});

// ─── Stat cards ───────────────────────────────────────────────────────────

interface StatCardProps {
  title: string;
  value: string;
  hint?: string;
  icon: React.ReactNode;
  accent?: boolean;
}

function StatCard({ title, value, hint, icon, accent }: StatCardProps) {
  return (
    <Card
      className={cn(
        "relative overflow-hidden transition-all duration-200 hover:shadow-depth",
        accent ? "border-primary/40 bg-primary/5" : "",
      )}
    >
      {accent && (
        <div
          className="pointer-events-none absolute inset-0 opacity-20"
          style={{
            background:
              "linear-gradient(135deg, hsl(263 70% 68% / 0.15) 0%, transparent 60%)",
          }}
          aria-hidden="true"
        />
      )}
      <CardHeader className="relative pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {title}
          </CardTitle>
          <span
            className={cn(
              "transition-colors duration-150",
              accent ? "text-primary" : "text-muted-foreground/40",
            )}
            aria-hidden="true"
          >
            {icon}
          </span>
        </div>
      </CardHeader>
      <CardContent className="relative">
        <p
          className={cn(
            "font-mono text-2xl font-bold tracking-tight",
            accent ? "text-primary" : "text-muted-foreground/70",
          )}
        >
          {value}
        </p>
        {hint && <p className="mt-1 text-[11px] text-muted-foreground/50">{hint}</p>}
      </CardContent>
    </Card>
  );
}

// ─── Status badge ─────────────────────────────────────────────────────────

function RunStatusBadge({ status }: { status: string }) {
  if (status === "running") {
    return (
      <span className="flex items-center gap-1 text-[11px] font-medium text-blue-400">
        <Loader2 size={10} className="animate-spin" />
        Running
      </span>
    );
  }
  if (status === "success") {
    return (
      <span className="flex items-center gap-1 text-[11px] font-medium text-emerald-400">
        <CheckCircle2 size={10} />
        Success
      </span>
    );
  }
  if (status === "interrupted") {
    return (
      <span className="flex items-center gap-1 text-[11px] font-medium text-amber-400">
        <Clock size={10} />
        Interrupted
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[11px] font-medium text-destructive">
      <XCircle size={10} />
      Error
    </span>
  );
}

// ─── Quick trigger row ─────────────────────────────────────────────────────

function QuickTriggerRow({ onSelect }: { onSelect: (filename: string) => void }) {
  const { data: configs, isLoading } = useConfigs();
  const trigger = useTriggerRun();
  const [selectedConfig, setSelectedConfig] = useState<string>("");
  const [isRunning, setIsRunning] = useState(false);

  const handleTrigger = async () => {
    if (!selectedConfig) return;
    setIsRunning(true);
    try {
      const result = await trigger.mutateAsync({ config_filename: selectedConfig });
      toast.success("Ejecución iniciada", {
        description: result.run_id,
        icon: <Zap size={14} />,
      });
      onSelect(result.run_id);
    } catch (err) {
      toast.error("Error al iniciar ejecución", {
        description: String(err),
        icon: <XCircle size={14} />,
      });
    } finally {
      setIsRunning(false);
    }
  };

  if (isLoading) {
    return <Skeleton className="h-10 w-full rounded-lg" />;
  }

  const realConfigs =
    configs?.filter(
      (c) =>
        !c.filename.startsWith("tmp") &&
        !c.filename.startsWith("daily_overrides") &&
        !c.filename.startsWith("contactos"),
    ) ?? [];

  return (
    <div className="flex items-center gap-3">
      <select
        className={cn(
          "h-9 flex-1 rounded-md border border-border bg-background px-3 text-sm",
          "focus:outline-none focus:ring-2 focus:ring-ring",
          "cursor-pointer transition-colors hover:border-primary/50",
        )}
        value={selectedConfig}
        onChange={(e) => setSelectedConfig(e.target.value)}
      >
        <option value="">Seleccionar config…</option>
        {realConfigs.map((c) => (
          <option key={c.filename} value={c.filename}>
            {c.filename}
          </option>
        ))}
      </select>
      <Button
        size="sm"
        onClick={handleTrigger}
        disabled={!selectedConfig || isRunning}
        className="shrink-0"
      >
        {isRunning ? (
          <>
            <Loader2 size={13} className="animate-spin" />
            Iniciando…
          </>
        ) : (
          <>
            <Play size={13} />
            Ejecutar
          </>
        )}
      </Button>
    </div>
  );
}

// ─── Recent runs table ─────────────────────────────────────────────────────

function RecentRunsTable({
  onSelectRun,
}: {
  onSelectRun: (runId: string) => void;
}) {
  const { data, isLoading } = useRuns({ limit: 10 });

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  const items = data?.items ?? [];

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border py-10">
        <Play size={20} className="text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground">Sin ejecuciones recientes</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/30">
            <th className="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Run ID
            </th>
            <th className="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Config
            </th>
            <th className="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Inicio
            </th>
            <th className="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Estado
            </th>
            <th className="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Ver
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((run) => (
            <tr
              key={run.id}
              className="border-b border-border last:border-0 transition-colors hover:bg-accent/40 cursor-pointer"
              onClick={() => onSelectRun(run.id)}
            >
              <td className="px-4 py-2.5">
                <span className="font-mono text-[11px] text-foreground">{run.id}</span>
              </td>
              <td className="px-4 py-2.5">
                <span className="font-mono text-[11px] text-muted-foreground">
                  {run.config_file}
                </span>
              </td>
              <td className="px-4 py-2.5">
                <span className="text-[11px] text-muted-foreground">
                  {new Date(run.started_at).toLocaleString("es-AR", {
                    day: "2-digit",
                    month: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </td>
              <td className="px-4 py-2.5">
                <RunStatusBadge status={run.status} />
              </td>
              <td className="px-4 py-2.5">
                <ChevronRight size={13} className="text-muted-foreground" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main Dashboard ────────────────────────────────────────────────────────

function DashboardPage() {
  const { data: activeRuns } = useActiveRuns();
  const { data: configs } = useConfigs();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRunStatus, setSelectedRunStatus] = useState<
    "running" | "success" | "error" | "interrupted"
  >("running");

  // When a run is triggered, select it automatically
  const handleRunSelect = (runId: string) => {
    setSelectedRunId(runId);
    setSelectedRunStatus("running");
  };

  // When clicking a run in the table, select it
  const handleTableSelect = (runId: string) => {
    // Find the run in recent runs to get its status
    const run = configs; // dummy reference
    void run;
    setSelectedRunId(runId);
    // We'll fetch the full run detail for status - for now just set to running
    // The LiveLogStream will handle fetching the right status
    setSelectedRunStatus("running");
  };

  return (
    <div className="flex flex-col gap-6 p-8">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        </div>
      </div>

      <Separator />

      {/* Quick trigger */}
      <div>
        <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Ejecución rápida
        </p>
        <QuickTriggerRow onSelect={handleRunSelect} />
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard
          title="Ejecuciones activas"
          value={String(activeRuns?.items?.length ?? 0)}
          hint="Runs en este momento"
          icon={<Activity size={15} />}
          accent={(activeRuns?.items?.length ?? 0) > 0}
        />
        <StatCard
          title="Configs disponibles"
          value={String(configs?.length ?? 0)}
          hint="Archivos en configs/"
          icon={<Settings2 size={15} />}
        />
        <StatCard
          title="Último run"
          value={
            (activeRuns?.items?.length ?? 0) > 0
              ? "Activo"
              : selectedRunId
                ? "Seleccionado"
                : "—"
          }
          hint={selectedRunId ?? "Sin selección"}
          icon={<Clock size={15} />}
          accent={selectedRunId != null}
        />
        <StatCard
          title="Próximo schedule"
          value="—"
          hint="Phase 4"
          icon={<CalendarClock size={15} />}
        />
      </div>

      {/* Recent runs table */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Ejecuciones recientes
          </p>
        </div>
        <RecentRunsTable onSelectRun={handleTableSelect} />
      </div>

      {/* Log stream panel */}
      {selectedRunId && (
        <div>
          <div className="mb-3 flex items-center justify-between">
            <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Logs — {selectedRunId}
            </p>
            <button
              onClick={() => setSelectedRunId(null)}
              className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            >
              Cerrar
            </button>
          </div>
          <LiveLogStream runId={selectedRunId} status={selectedRunStatus} />
        </div>
      )}
    </div>
  );
}