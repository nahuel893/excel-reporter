/**
 * FilePathWidget — rjsf custom widget for filesystem path fields.
 *
 * Renders a text input with a live existence indicator (green dot = exists,
 * red dot = not found). Calls GET /mgmt/configs/path-exists?path=... on blur.
 * Used for archivo_plantilla / detalle_movimientos_path (x-widget: "filepath").
 */

import { useState } from "react";
import type { WidgetProps } from "@rjsf/utils";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type PathStatus = "unknown" | "checking" | "exists" | "missing";

export function FilePathWidget({
  id,
  value,
  required,
  disabled,
  readonly,
  onChange,
  onBlur,
  onFocus,
}: WidgetProps) {
  const [status, setStatus] = useState<PathStatus>("unknown");

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setStatus("unknown");
    onChange(e.target.value || undefined);
  };

  const handleBlur = async (e: React.FocusEvent<HTMLInputElement>) => {
    const val = e.target.value.trim();
    onBlur(id, val);
    if (!val) {
      setStatus("unknown");
      return;
    }
    setStatus("checking");
    try {
      const res = await api.configs.pathExists(val);
      setStatus(res.exists && res.is_file ? "exists" : "missing");
    } catch {
      setStatus("missing");
    }
  };

  const dotColor = {
    unknown: "bg-gray-300",
    checking: "bg-yellow-400 animate-pulse",
    exists: "bg-green-500",
    missing: "bg-red-500",
  }[status];

  return (
    <div className="flex items-center gap-2">
      <input
        type="text"
        id={id}
        name={id}
        value={typeof value === "string" ? value : ""}
        required={required}
        disabled={disabled || readonly}
        onChange={handleChange}
        onBlur={(e) => void handleBlur(e)}
        onFocus={(e) => onFocus(id, e.target.value)}
        placeholder="/ruta/absoluta/al/archivo.xlsx"
        className="block flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        data-testid={`filepath-widget-${id}`}
      />
      <span
        className={cn("h-3 w-3 flex-shrink-0 rounded-full", dotColor)}
        aria-label={`Path status: ${status}`}
        data-testid={`filepath-status-${id}`}
      />
    </div>
  );
}
