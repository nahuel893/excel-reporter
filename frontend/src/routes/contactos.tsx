/**
 * Contactos editor route — Card-wrapped JSON textarea with mono font,
 * sonner toasts, and tab key support.
 */

import { useState } from "react";
import { createRoute, Link } from "@tanstack/react-router";
import { ChevronRight, Save, Loader2, AlertTriangle, Users } from "lucide-react";
import { toast } from "sonner";
import { rootRoute } from "./__root";
import { useContactos } from "@/lib/queries";
import { useSaveContactos } from "@/lib/mutations";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { ApiError } from "@/lib/api";

export const contactosRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/contactos",
  component: ContactosPage,
});

function ContactosPage() {
  const { data, isLoading, error } = useContactos();
  const save = useSaveContactos();

  const [text, setText] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [isDirty, setIsDirty] = useState(false);

  const currentText =
    text !== null
      ? text
      : data
        ? JSON.stringify(data, null, 2)
        : "";

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    setIsDirty(true);
    try {
      JSON.parse(e.target.value);
      setParseError(null);
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "JSON inválido");
    }
  };

  // Allow Tab key inside textarea for indentation
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const target = e.currentTarget;
      const start = target.selectionStart;
      const end = target.selectionEnd;
      const newText =
        currentText.substring(0, start) + "  " + currentText.substring(end);
      setText(newText);
      // Restore cursor position after React re-render
      requestAnimationFrame(() => {
        target.selectionStart = start + 2;
        target.selectionEnd = start + 2;
      });
    }
  };

  const handleSave = () => {
    if (parseError) return;
    try {
      const parsed = JSON.parse(currentText) as Record<string, unknown>;
      save.mutate(parsed, {
        onSuccess: () => {
          setIsDirty(false);
          setText(null);
          toast.success("Guardado correctamente", {
            description: "contactos.json actualizado",
            icon: <Save size={14} />,
          });
        },
        onError: (err) => {
          const apiErr = err as ApiError;
          toast.error("Error al guardar", {
            description: `Error ${apiErr.status}: ${JSON.stringify(apiErr.detail)}`,
            icon: <AlertTriangle size={14} />,
          });
        },
      });
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "JSON inválido");
    }
  };

  if (isLoading) {
    return (
      <div className="p-8" aria-busy="true">
        <Skeleton className="mb-6 h-8 w-40" />
        <Skeleton className="h-96 w-full rounded-lg" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <div
          className="flex items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          role="alert"
        >
          <AlertTriangle size={16} aria-hidden="true" />
          Error: {String(error)}
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      {/* Breadcrumb */}
      <nav
        className="mb-6 flex items-center gap-1.5 text-xs text-muted-foreground"
        aria-label="Breadcrumb"
      >
        <Link to="/configs" className="hover:text-foreground transition-colors">
          Configuraciones
        </Link>
        <ChevronRight size={12} aria-hidden="true" />
        <span className="font-medium text-foreground">contactos.json</span>
      </nav>

      {/* Page title */}
      <div className="mb-6 flex items-center gap-3">
        <Users size={20} className="text-muted-foreground" aria-hidden="true" />
        <h1 className="text-2xl font-bold tracking-tight">Contactos</h1>
        {isDirty && (
          <span
            className="dirty-dot h-2 w-2 rounded-full bg-amber-400"
            title="Cambios sin guardar"
            aria-label="Cambios sin guardar"
          />
        )}
      </div>

      <Separator className="mb-6" />

      <Card>
        <CardHeader>
          <CardTitle>Editor JSON</CardTitle>
          <CardDescription>
            Editá el archivo de contactos en formato JSON. Tab inserta dos espacios.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <textarea
              value={currentText}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              className={cn(
                "h-96 w-full resize-none rounded-md border bg-background p-3 font-mono text-xs leading-relaxed transition-colors focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                parseError ? "border-destructive" : "border-input",
              )}
              spellCheck={false}
              data-testid="contactos-editor"
              aria-label="Editor de contactos JSON"
            />
            {parseError && (
              <p className="flex items-center gap-1.5 text-xs text-destructive" role="alert">
                <AlertTriangle size={12} aria-hidden="true" />
                {parseError}
              </p>
            )}
          </div>
        </CardContent>
        <CardFooter className="border-t border-border pt-4">
          <Button
            type="button"
            onClick={handleSave}
            disabled={save.isPending || Boolean(parseError)}
            data-testid="contactos-save"
          >
            {save.isPending ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Guardando...
              </>
            ) : (
              <>
                <Save size={14} />
                Guardar
              </>
            )}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
