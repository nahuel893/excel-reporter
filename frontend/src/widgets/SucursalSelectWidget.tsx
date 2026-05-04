/**
 * SucursalSelectWidget — multi-select widget for sucursales arrays.
 *
 * Fetches options from GET /mgmt/refs/sucursales and renders a
 * multi-select list. Used for fields with x-widget: "sucursal-select-array".
 */

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
      className="space-y-1"
      aria-required={required}
    >
      <div className="mb-1 flex gap-2">
        <button
          type="button"
          onClick={toggleAll}
          disabled={disabled || readonly}
          className="text-xs text-primary underline disabled:opacity-50"
        >
          {selected.length === options.length ? "Deseleccionar todo" : "Seleccionar todo"}
        </button>
        <span className="text-xs text-muted-foreground">
          ({selected.length} / {options.length} seleccionados)
        </span>
      </div>
      <div className="max-h-48 overflow-y-auto rounded-md border border-input bg-background p-2">
        {options.map((opt) => (
          <label
            key={opt}
            className={cn(
              "flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-accent",
              (disabled || readonly) && "cursor-not-allowed opacity-50",
            )}
          >
            <input
              type="checkbox"
              checked={selected.includes(opt)}
              disabled={disabled || readonly}
              onChange={() => toggle(opt)}
              className="accent-primary"
              data-testid={`sucursal-checkbox-${opt}`}
            />
            {opt}
          </label>
        ))}
      </div>
    </div>
  );
}
