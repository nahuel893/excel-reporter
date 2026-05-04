/**
 * DateWidget — rjsf custom widget for date fields (yyyy-mm-dd).
 *
 * Renders a native <input type="date"> and emits a yyyy-mm-dd string.
 * Used for fecha_desde / fecha_hasta fields (x-widget: "date").
 */

import type { WidgetProps } from "@rjsf/utils";

export function DateWidget({
  id,
  value,
  required,
  disabled,
  readonly,
  onChange,
  onBlur,
  onFocus,
  schema,
}: WidgetProps) {
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value || undefined);
  };

  return (
    <input
      type="date"
      id={id}
      name={id}
      value={typeof value === "string" ? value : ""}
      required={required}
      disabled={disabled || readonly}
      min={typeof schema.minimum === "string" ? schema.minimum : undefined}
      max={typeof schema.maximum === "string" ? schema.maximum : undefined}
      onChange={handleChange}
      onBlur={(e) => onBlur(id, e.target.value)}
      onFocus={(e) => onFocus(id, e.target.value)}
      className="block w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
      data-testid={`date-widget-${id}`}
    />
  );
}
