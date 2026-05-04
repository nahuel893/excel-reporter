/**
 * Runs history route (stub for Phase 3).
 */

import { createRoute } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const runsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs",
  component: RunsPage,
});

function RunsPage() {
  return (
    <div className="p-6">
      <h1 className="mb-4 text-2xl font-bold">Ejecuciones</h1>
      <p className="text-muted-foreground">
        Historial de ejecuciones — implementado en Fase 3.
      </p>
    </div>
  );
}
