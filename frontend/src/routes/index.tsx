/**
 * Dashboard route (stub for Phase 2, content in Phase 3).
 */

import { createRoute } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: DashboardPage,
});

function DashboardPage() {
  return (
    <div className="p-6">
      <h1 className="mb-4 text-2xl font-bold">Dashboard</h1>
      <p className="text-muted-foreground">
        Panel de control — implementado en Fase 3.
      </p>
    </div>
  );
}
