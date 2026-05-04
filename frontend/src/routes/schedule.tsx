/**
 * Schedule route (stub for Phase 4).
 */

import { createRoute } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const scheduleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/schedule",
  component: SchedulePage,
});

function SchedulePage() {
  return (
    <div className="p-6">
      <h1 className="mb-4 text-2xl font-bold">Programación</h1>
      <p className="text-muted-foreground">
        Configuración de horarios — implementado en Fase 4.
      </p>
    </div>
  );
}
