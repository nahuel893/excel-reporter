/**
 * SupervisorMatrixWidget — custom rjsf widget for the supervisores dict field.
 *
 * Renders a matrix: one row per supervisor (from GET /mgmt/refs/supervisores),
 * each row has a multi-select of sucursales (from GET /mgmt/refs/sucursales).
 *
 * The rjsf value is a dict: { [supervisor: string]: string[] }
 * Used for fields with x-widget: "supervisor-matrix".
 */

import { useState } from "react";
import type { WidgetProps } from "@rjsf/utils";
import { useSucursales, useSupervisores } from "@/lib/queries";
import { cn } from "@/lib/utils";

type SupervisorMap = Record<string, string[]>;

export function SupervisorMatrixWidget({
  id,
  value,
  disabled,
  readonly,
  onChange,
}: WidgetProps) {
  const { data: allSucursales = [], isLoading: loadingSuc } = useSucursales();
  const { data: allSupervisores = [], isLoading: loadingSup } = useSupervisores();

  // Current value as dict
  const current: SupervisorMap =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as SupervisorMap)
      : {};

  // Track which supervisors have been "activated" (have a row)
  const activeSupervisores = Object.keys(current);

  // Local state for which supervisor rows are expanded
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const toggleExpand = (sup: string) => {
    setExpanded((prev) => ({ ...prev, [sup]: !prev[sup] }));
  };

  const addSupervisor = (sup: string) => {
    if (activeSupervisores.includes(sup)) return;
    onChange({ ...current, [sup]: [] });
    setExpanded((prev) => ({ ...prev, [sup]: true }));
  };

  const removeSupervisor = (sup: string) => {
    const next = { ...current };
    delete next[sup];
    onChange(next);
  };

  const toggleSucursal = (sup: string, suc: string) => {
    const existing = current[sup] ?? [];
    const next = existing.includes(suc)
      ? existing.filter((s) => s !== suc)
      : [...existing, suc];
    onChange({ ...current, [sup]: next });
  };

  if (loadingSuc || loadingSup) {
    return (
      <div className="text-sm text-muted-foreground" aria-busy="true">
        Cargando datos...
      </div>
    );
  }

  const unusedSupervisores = allSupervisores.filter(
    (s) => !activeSupervisores.includes(s),
  );

  return (
    <div
      id={id}
      data-testid={`supervisor-matrix-${id}`}
      className="space-y-2"
    >
      {/* Active supervisor rows */}
      {activeSupervisores.map((sup) => (
        <div key={sup} className="rounded-md border border-input bg-background">
          <div className="flex items-center justify-between px-3 py-2">
            <button
              type="button"
              onClick={() => toggleExpand(sup)}
              className="flex flex-1 items-center gap-2 text-left text-sm font-medium"
              disabled={disabled || readonly}
            >
              <span className="font-semibold">{sup}</span>
              <span className="text-xs text-muted-foreground">
                ({(current[sup] ?? []).length} sucursales)
              </span>
              <span className="ml-auto text-xs text-muted-foreground">
                {expanded[sup] ? "▲" : "▼"}
              </span>
            </button>
            {!disabled && !readonly && (
              <button
                type="button"
                onClick={() => removeSupervisor(sup)}
                className="ml-2 text-xs text-destructive hover:underline"
                data-testid={`supervisor-remove-${sup}`}
                aria-label={`Eliminar supervisor ${sup}`}
              >
                ✕
              </button>
            )}
          </div>

          {expanded[sup] && (
            <div className="border-t border-input px-3 py-2">
              <div className="grid grid-cols-2 gap-1 sm:grid-cols-3">
                {allSucursales.map((suc) => (
                  <label
                    key={suc}
                    className={cn(
                      "flex cursor-pointer items-center gap-1 rounded px-1 py-0.5 text-xs hover:bg-accent",
                      (disabled || readonly) && "cursor-not-allowed opacity-50",
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={(current[sup] ?? []).includes(suc)}
                      disabled={disabled || readonly}
                      onChange={() => toggleSucursal(sup, suc)}
                      className="accent-primary"
                      data-testid={`supervisor-suc-${sup}-${suc}`}
                    />
                    <span className="truncate">{suc}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}

      {/* Add supervisor dropdown */}
      {!disabled && !readonly && unusedSupervisores.length > 0 && (
        <div className="flex items-center gap-2">
          <select
            className="rounded-md border border-input bg-background px-2 py-1 text-sm"
            defaultValue=""
            onChange={(e) => {
              if (e.target.value) {
                addSupervisor(e.target.value);
                e.target.value = "";
              }
            }}
            data-testid={`supervisor-add-select-${id}`}
          >
            <option value="" disabled>
              + Agregar supervisor...
            </option>
            {unusedSupervisores.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
