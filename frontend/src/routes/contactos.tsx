/**
 * Contactos editor route — form for contactos.json.
 */

import { useState } from "react";
import { createRoute, Link } from "@tanstack/react-router";
import { rootRoute } from "./__root";
import { useContactos } from "@/lib/queries";
import { useSaveContactos } from "@/lib/mutations";
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
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const currentText =
    text !== null
      ? text
      : data
        ? JSON.stringify(data, null, 2)
        : "";

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    try {
      JSON.parse(e.target.value);
      setParseError(null);
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "JSON inválido");
    }
  };

  const handleSave = () => {
    if (parseError) return;
    try {
      const parsed = JSON.parse(currentText) as Record<string, unknown>;
      setServerError(null);
      setSaveSuccess(false);
      save.mutate(parsed, {
        onSuccess: () => {
          setSaveSuccess(true);
          setText(null);
          setTimeout(() => setSaveSuccess(false), 3000);
        },
        onError: (err) => {
          const apiErr = err as ApiError;
          setServerError(`Error ${apiErr.status}: ${JSON.stringify(apiErr.detail)}`);
        },
      });
    } catch (err) {
      setParseError(err instanceof Error ? err.message : "JSON inválido");
    }
  };

  if (isLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground" aria-busy="true">
        Cargando contactos...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-sm text-destructive" role="alert">
        Error: {String(error)}
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center gap-2 text-sm text-muted-foreground">
        <Link to="/configs" className="hover:underline">
          Configuraciones
        </Link>
        <span>/</span>
        <span className="font-medium text-foreground">contactos.json</span>
      </div>

      <h1 className="mb-4 text-xl font-bold">Contactos</h1>

      {saveSuccess && (
        <div
          className="mb-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800"
          role="status"
          data-testid="save-success"
        >
          Guardado correctamente.
        </div>
      )}

      {serverError && (
        <div
          className="mb-4 rounded-md border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          role="alert"
        >
          {serverError}
        </div>
      )}

      <div className="space-y-2">
        <textarea
          value={currentText}
          onChange={handleChange}
          className="h-96 w-full rounded-md border border-input bg-background p-3 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          spellCheck={false}
          data-testid="contactos-editor"
        />
        {parseError && (
          <p className="text-xs text-destructive" role="alert">
            {parseError}
          </p>
        )}
        <button
          type="button"
          onClick={handleSave}
          disabled={save.isPending || Boolean(parseError)}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="contactos-save"
        >
          {save.isPending ? "Guardando..." : "Guardar"}
        </button>
      </div>
    </div>
  );
}
