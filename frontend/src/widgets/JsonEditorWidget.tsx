/**
 * JsonEditorWidget — Monaco-based JSON editor widget for rjsf.
 *
 * Used for fields with x-widget: "json-editor" (e.g., champions-league
 * categorias). Monaco is lazy-loaded to avoid bundle size impact.
 *
 * The value stored in rjsf is a JSON object. Monaco edits raw JSON text,
 * and we parse/stringify on change.
 */

import { lazy, Suspense, useState, useCallback } from "react";
import type { WidgetProps } from "@rjsf/utils";
import { cn } from "@/lib/utils";

// Lazy-load Monaco to avoid pulling ~3MB into the main chunk
const MonacoEditor = lazy(() =>
  import("@monaco-editor/react").then((m) => ({ default: m.default })),
);

export function JsonEditorWidget({
  id,
  value,
  disabled,
  readonly,
  onChange,
  rawErrors,
}: WidgetProps) {
  // Convert the object value to a JSON string for Monaco
  const toText = (v: unknown): string => {
    if (typeof v === "string") return v;
    try {
      return JSON.stringify(v, null, 2);
    } catch {
      return "{}";
    }
  };

  const [text, setText] = useState(() => toText(value));
  const [parseError, setParseError] = useState<string | null>(null);

  const handleChange = useCallback(
    (newValue: string | undefined) => {
      const raw = newValue ?? "";
      setText(raw);
      try {
        const parsed = JSON.parse(raw) as unknown;
        setParseError(null);
        onChange(parsed);
      } catch (e) {
        setParseError(e instanceof Error ? e.message : "JSON inválido");
        // Don't call onChange with invalid JSON — let the user fix it
      }
    },
    [onChange],
  );

  const hasError = parseError !== null || (rawErrors && rawErrors.length > 0);

  return (
    <div
      id={id}
      data-testid={`json-editor-widget-${id}`}
      className="space-y-1"
    >
      <div
        className={cn(
          "overflow-hidden rounded-md border",
          hasError ? "border-destructive" : "border-input",
        )}
      >
        <Suspense
          fallback={
            <div className="flex h-48 items-center justify-center bg-muted text-sm text-muted-foreground">
              Cargando editor...
            </div>
          }
        >
          <MonacoEditor
            height="240px"
            language="json"
            value={text}
            onChange={handleChange}
            options={{
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              readOnly: disabled || readonly,
              fontSize: 13,
              lineNumbers: "on",
              wordWrap: "on",
              tabSize: 2,
              automaticLayout: true,
            }}
            theme="vs-light"
            data-testid={`monaco-${id}`}
          />
        </Suspense>
      </div>
      {parseError && (
        <p className="text-xs text-destructive" role="alert">
          {parseError}
        </p>
      )}
      {rawErrors?.map((err, i) => (
        <p key={i} className="text-xs text-destructive" role="alert">
          {err}
        </p>
      ))}
    </div>
  );
}
