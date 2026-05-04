/**
 * SupervisorMatrixWidget — custom rjsf widget for the supervisores dict field.
 *
 * Renders one Card per supervisor with collapsible sucursal checkboxes.
 * Used for fields with x-widget: "supervisor-matrix".
 */

import { useState } from "react";
import { ChevronDown, ChevronUp, X, UserPlus } from "lucide-react";
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

  const activeSupervisores = Object.keys(current);
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
      {/* Active supervisor cards */}
      {activeSupervisores.map((sup) => {
        const isExpanded = Boolean(expanded[sup]);
        const sucCount = (current[sup] ?? []).length;
        return (
          <div
            key={sup}
            className="overflow-hidden rounded-lg border border-border bg-card"
          >
            {/* Header row */}
            <div className="flex items-center justify-between px-4 py-3">
              <button
                type="button"
                onClick={() => toggleExpand(sup)}
                className="flex flex-1 items-center gap-3 text-left"
                disabled={disabled || readonly}
                aria-expanded={isExpanded}
              >
                <span className="text-sm font-semibold text-foreground">
                  {sup}
                </span>
                <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                  {sucCount} sucursales
                </span>
                <span
                  className="ml-auto text-muted-foreground"
                  aria-hidden="true"
                >
                  {isExpanded ? (
                    <ChevronUp size={14} />
                  ) : (
                    <ChevronDown size={14} />
                  )}
                </span>
              </button>
              {!disabled && !readonly && (
                <button
                  type="button"
                  onClick={() => removeSupervisor(sup)}
                  className="ml-3 flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/15 hover:text-destructive"
                  data-testid={`supervisor-remove-${sup}`}
                  aria-label={`Eliminar supervisor ${sup}`}
                >
                  <X size={13} />
                </button>
              )}
            </div>

            {/* Expanded sucursales grid */}
            {isExpanded && (
              <div className="border-t border-border bg-muted/20 px-4 py-3">
                <div className="grid grid-cols-2 gap-1 sm:grid-cols-3">
                  {allSucursales.map((suc) => (
                    <label
                      key={suc}
                      className={cn(
                        "flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 text-xs transition-colors hover:bg-accent",
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
        );
      })}

      {/* Add supervisor row */}
      {!disabled && !readonly && unusedSupervisores.length > 0 && (
        <div className="flex items-center gap-2">
          <UserPlus
            size={14}
            className="text-muted-foreground"
            aria-hidden="true"
          />
          <select
            className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
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
              Agregar supervisor...
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
