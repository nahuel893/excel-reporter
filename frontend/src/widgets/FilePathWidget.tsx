/**
 * FilePathWidget — rjsf custom widget for filesystem path fields.
 *
 * Renders a text input with a File icon + live existence indicator
 * (green dot = exists, red dot = not found). Calls GET /mgmt/configs/path-exists?path=...
 * Used for archivo_plantilla / detalle_movimientos_path (x-widget: "filepath").
 */

import { useState } from "react";
import { File } from "lucide-react";
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
    <div className="relative flex items-center gap-2">
      <div className="relative flex-1">
        <File
          size={14}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
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
          className={cn(
            "block w-full rounded-md border border-input bg-background py-2 pl-9 pr-3 font-mono text-xs shadow-sm transition-colors focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
            status === "exists" && "border-emerald-500/40",
            status === "missing" && "border-destructive/50",
          )}
          data-testid={`filepath-widget-${id}`}
        />
      </div>
      <span
        className={cn("h-3 w-3 flex-shrink-0 rounded-full transition-colors", dotColor)}
        aria-label={`Path status: ${status}`}
        data-testid={`filepath-status-${id}`}
      />
    </div>
  );
}
