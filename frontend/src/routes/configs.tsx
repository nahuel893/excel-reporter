/**
 * Configs list route — polished table with tipo badges, skeleton loading,
 * empty state (FolderX), and sonner error toast.
 */

import { useEffect } from "react";
import { createRoute, Link } from "@tanstack/react-router";
import { FolderX, AlertTriangle, Settings2, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { rootRoute } from "./__root";
import { useConfigs } from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export const configsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/configs",
  component: ConfigsPage,
});

type TipoBadgeVariant =
  | "ventas"
  | "avances"
  | "champions-league"
  | "resumen-mensual"
  | "stock-diario"
  | "zinc";

function tipoToVariant(tipo: string): TipoBadgeVariant {
  const map: Record<string, TipoBadgeVariant> = {
    ventas: "ventas",
    avances: "avances",
    "champions-league": "champions-league",
    "resumen-mensual": "resumen-mensual",
    "stock-diario": "stock-diario",
  };
  return map[tipo] ?? "zinc";
}

function SkeletonRow() {
  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-4 py-3">
        <Skeleton className="h-4 w-48" />
      </td>
      <td className="px-4 py-3">
        <Skeleton className="h-5 w-24 rounded-full" />
      </td>
      <td className="px-4 py-3">
        <Skeleton className="h-4 w-36" />
      </td>
      <td className="px-4 py-3">
        <Skeleton className="h-4 w-12" />
      </td>
    </tr>
  );
}

function EmptyState() {
  return (
    <tr>
      <td colSpan={4} className="px-4 py-16 text-center">
        <div className="flex flex-col items-center gap-3">
          <FolderX
            size={36}
            className="text-muted-foreground/40"
            aria-hidden="true"
          />
          <p className="text-sm font-medium text-muted-foreground">
            No hay configs
          </p>
          <p className="text-xs text-muted-foreground/60">
            Agregá archivos JSON al directorio{" "}
            <code className="font-mono">configs/</code> para que aparezcan acá.
          </p>
        </div>
      </td>
    </tr>
  );
}

function ConfigsPage() {
  const { data: configs, isLoading, error } = useConfigs();

  useEffect(() => {
    if (error) {
      toast.error("Error al cargar configuraciones", {
        description: String(error),
        icon: <AlertTriangle size={16} />,
      });
    }
  }, [error]);

  return (
    <div className="p-8">
      {/* Page header */}
      <div className="mb-6 flex items-center gap-3">
        <Settings2 size={20} className="text-muted-foreground" aria-hidden="true" />
        <h1 className="text-2xl font-bold tracking-tight">Configuraciones</h1>
      </div>

      <Separator className="mb-6" />

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm" data-testid="configs-table">
          <thead>
            <tr className="border-b border-border bg-muted/40">
              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Archivo
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Tipo
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Última modificación
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Acción
              </th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)
            ) : !configs || configs.length === 0 ? (
              <EmptyState />
            ) : (
              configs.map((cfg) => (
                <tr
                  key={cfg.filename}
                  className={cn(
                    "border-b border-border last:border-0",
                    "transition-colors duration-100 hover:bg-accent/40",
                  )}
                  data-testid={`config-row-${cfg.filename}`}
                >
                  <td className="px-4 py-3">
                    <span className="font-mono text-xs text-foreground">
                      {cfg.filename}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={tipoToVariant(cfg.tipo)}>
                      {cfg.tipo}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    {new Date(cfg.mtime).toLocaleString("es-AR")}
                  </td>
                  <td className="px-4 py-3">
                    <Link
                      to="/configs/$filename"
                      params={{ filename: cfg.filename }}
                      className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80 transition-colors"
                      data-testid={`edit-link-${cfg.filename}`}
                    >
                      Editar
                      <ChevronRight size={12} aria-hidden="true" />
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
