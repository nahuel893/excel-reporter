/**
 * Configs list route — lists all configs/*.json files with tipo + mtime + edit link.
 */

import { createRoute, Link } from "@tanstack/react-router";
import { rootRoute } from "./__root";
import { useConfigs } from "@/lib/queries";

export const configsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/configs",
  component: ConfigsPage,
});

function ConfigsPage() {
  const { data: configs, isLoading, error } = useConfigs();

  if (isLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground" aria-busy="true">
        Cargando configuraciones...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-sm text-destructive" role="alert">
        Error al cargar configuraciones: {String(error)}
      </div>
    );
  }

  return (
    <div className="p-6">
      <h1 className="mb-4 text-2xl font-bold">Configuraciones</h1>
      <div className="overflow-hidden rounded-md border border-border">
        <table className="w-full text-sm" data-testid="configs-table">
          <thead>
            <tr className="border-b border-border bg-muted">
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                Archivo
              </th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                Tipo
              </th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                Última modificación
              </th>
              <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                Acción
              </th>
            </tr>
          </thead>
          <tbody>
            {configs?.map((cfg, i) => (
              <tr
                key={cfg.filename}
                className={i % 2 === 0 ? "bg-background" : "bg-muted/30"}
                data-testid={`config-row-${cfg.filename}`}
              >
                <td className="px-4 py-3 font-mono text-xs">{cfg.filename}</td>
                <td className="px-4 py-3">
                  <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium">
                    {cfg.tipo}
                  </span>
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {new Date(cfg.mtime).toLocaleString("es-AR")}
                </td>
                <td className="px-4 py-3">
                  <Link
                    to="/configs/$filename"
                    params={{ filename: cfg.filename }}
                    className="text-primary hover:underline"
                    data-testid={`edit-link-${cfg.filename}`}
                  >
                    Editar
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
