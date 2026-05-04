/**
 * Artifacts browser route (stub for Phase 5).
 */

import { createRoute } from "@tanstack/react-router";
import { rootRoute } from "./__root";

export const artifactsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/artifacts",
  component: ArtifactsPage,
});

function ArtifactsPage() {
  return (
    <div className="p-6">
      <h1 className="mb-4 text-2xl font-bold">Archivos</h1>
      <p className="text-muted-foreground">
        Explorador de archivos generados — implementado en Fase 5.
      </p>
    </div>
  );
}
