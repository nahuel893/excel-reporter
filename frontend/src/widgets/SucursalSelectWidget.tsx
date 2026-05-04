/**
 * SucursalSelectWidget — multi-select widget for sucursales arrays.
 *
 * Fetches options from GET /mgmt/refs/sucursales and renders them as
 * chip-style toggleable items with X to deselect.
 * Used for fields with x-widget: "sucursal-select-array".
 */

import { X } from "lucide-react";
import type { WidgetProps } from "@rjsf/utils";
import { useSucursales } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function SucursalSelectWidget({
  id,
  value,
  required,
  disabled,
  readonly,
  onChange,
}: WidgetProps) {
  const { data: options = [], isLoading } = useSucursales();

  const selected: string[] = Array.isArray(value) ? (value as string[]) : [];

  const toggle = (option: string) => {
    const next = selected.includes(option)
      ? selected.filter((v) => v !== option)
      : [...selected, option];
    onChange(next);
  };

  const toggleAll = () => {
    if (selected.length === options.length) {
      onChange([]);
    } else {
      onChange([...options]);
    }
  };

  if (isLoading) {
    return (
      <div className="text-sm text-muted-foreground" aria-busy="true">
        Cargando sucursales...
      </div>
    );
  }

  return (
    <div
      id={id}
      data-testid={`sucursal-select-${id}`}
      className="space-y-2"
      aria-required={required}
    >
      {/* Controls row */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={toggleAll}
          disabled={disabled || readonly}
          className="text-xs font-medium text-primary hover:text-primary/80 transition-colors disabled:opacity-50"
        >
          {selected.length === options.length ? "Deseleccionar todo" : "Seleccionar todo"}
        </button>
        <span className="text-xs text-muted-foreground">
          {selected.length} / {options.length}
        </span>
      </div>

      {/* Chip grid */}
      <div className="flex flex-wrap gap-1.5 rounded-md border border-input bg-background/50 p-2">
        {options.map((opt) => {
          const isSelected = selected.includes(opt);
          return (
            <label
              key={opt}
              className={cn(
                "inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors select-none",
                isSelected
                  ? "border-primary/30 bg-primary/15 text-primary hover:bg-primary/20"
                  : "border-border bg-muted/30 text-muted-foreground hover:border-border/80 hover:bg-muted/50 hover:text-foreground",
                (disabled || readonly) && "cursor-not-allowed opacity-50",
              )}
            >
              {/* Hidden checkbox for test compatibility */}
              <input
                type="checkbox"
                checked={isSelected}
                disabled={disabled || readonly}
                onChange={() => toggle(opt)}
                className="sr-only"
                data-testid={`sucursal-checkbox-${opt}`}
              />
              {opt}
              {isSelected && !disabled && !readonly && (
                <X size={10} className="shrink-0 opacity-60" aria-hidden="true" />
              )}
            </label>
          );
        })}
      </div>
    </div>
  );
}
