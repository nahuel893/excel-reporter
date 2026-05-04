/**
 * Dashboard route — 4 stat cards layout (Phase 3 content stubs).
 */

import { createRoute } from "@tanstack/react-router";
import { Activity, CalendarClock, Settings2, Package } from "lucide-react";
import { rootRoute } from "./__root";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: DashboardPage,
});

interface StatCardProps {
  title: string;
  value: string;
  hint: string;
  icon: React.ReactNode;
}

function StatCard({ title, value, hint, icon }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {title}
          </CardTitle>
          <span className="text-muted-foreground/40" aria-hidden="true">
            {icon}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <p className="font-mono text-2xl font-bold tracking-tight text-muted-foreground/40">
          {value}
        </p>
        <p className="mt-1 text-xs text-muted-foreground/50">{hint}</p>
      </CardContent>
    </Card>
  );
}

function DashboardPage() {
  return (
    <div className="p-8">
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
      </div>

      <Separator className="mb-6" />

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard
          title="Última ejecución"
          value="—"
          hint="Disponible en Fase 3"
          icon={<Activity size={16} />}
        />
        <StatCard
          title="Próximo schedule"
          value="—"
          hint="Disponible en Fase 4"
          icon={<CalendarClock size={16} />}
        />
        <StatCard
          title="Configs activos"
          value="—"
          hint="Disponible en Fase 3"
          icon={<Settings2 size={16} />}
        />
        <StatCard
          title="Artefactos recientes"
          value="—"
          hint="Disponible en Fase 5"
          icon={<Package size={16} />}
        />
      </div>
    </div>
  );
}
