/**
 * Artifacts browser route — polished stub with dashed-border card.
 */

import { createRoute } from "@tanstack/react-router";
import { Folder } from "lucide-react";
import { rootRoute } from "./__root";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export const artifactsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/artifacts",
  component: ArtifactsPage,
});

function ArtifactsPage() {
  return (
    <div className="p-8">
      <div className="mb-6 flex items-center gap-3">
        <Folder size={20} className="text-muted-foreground" aria-hidden="true" />
        <h1 className="text-2xl font-bold tracking-tight">Archivos</h1>
      </div>

      <Separator className="mb-6" />

      <div
        className={cn(
          "flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed border-border py-20",
        )}
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-border bg-muted/30">
          <Folder size={20} className="text-muted-foreground/50" aria-hidden="true" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-muted-foreground">
            Disponible en Fase 5
          </p>
          <p className="mt-1 text-xs text-muted-foreground/60">
            El explorador de archivos generados estará disponible próximamente.
          </p>
        </div>
      </div>
    </div>
  );
}
