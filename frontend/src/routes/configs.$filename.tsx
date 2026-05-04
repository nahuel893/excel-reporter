/**
 * Config editor route — loads schema + content, renders rjsf form, handles save.
 */

import { useState } from "react";
import { createRoute, Link } from "@tanstack/react-router";
import { rootRoute } from "./__root";
import { useConfig } from "@/lib/queries";
import { useSaveConfig } from "@/lib/mutations";
import { ConfigForm } from "@/components/ConfigForm";
import type { ApiError } from "@/lib/api";

export const configEditorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/configs/$filename",
  component: ConfigEditorPage,
});

interface FieldError {
  loc: string[];
  msg: string;
  type: string;
}

function ConfigEditorPage() {
  const { filename } = configEditorRoute.useParams();
  const { data, isLoading, error } = useConfig(filename);
  const saveConfig = useSaveConfig(filename);

  const [serverErrors, setServerErrors] = useState<FieldError[]>([]);
  const [saveSuccess, setSaveSuccess] = useState(false);

  if (isLoading) {
    return (
      <div className="p-6 text-sm text-muted-foreground" aria-busy="true">
        Cargando configuración...
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-6 text-sm text-destructive" role="alert">
        Error al cargar: {String(error)}
      </div>
    );
  }

  const handleSave = (formData: Record<string, unknown>) => {
    setServerErrors([]);
    setSaveSuccess(false);
    saveConfig.mutate(formData, {
      onSuccess: () => {
        setSaveSuccess(true);
        setTimeout(() => setSaveSuccess(false), 3000);
      },
      onError: (err) => {
        const apiErr = err as ApiError;
        if (apiErr.status === 422) {
          const detail = apiErr.detail as { detail?: FieldError[] } | FieldError[];
          const errs = Array.isArray(detail)
            ? detail
            : (detail as { detail?: FieldError[] }).detail ?? [];
          setServerErrors(errs);
        }
      },
    });
  };

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center gap-2 text-sm text-muted-foreground">
        <Link to="/configs" className="hover:underline">
          Configuraciones
        </Link>
        <span>/</span>
        <span className="font-medium text-foreground">{filename}</span>
      </div>

      <h1 className="mb-1 text-xl font-bold">{filename}</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Tipo: <span className="font-medium">{String(data.content.tipo ?? "—")}</span>
      </p>

      {saveSuccess && (
        <div
          className="mb-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800"
          role="status"
          data-testid="save-success"
        >
          Guardado correctamente.
        </div>
      )}

      <ConfigForm
        schema={data.schema}
        formData={data.content}
        onSubmit={handleSave}
        serverErrors={serverErrors}
        isSaving={saveConfig.isPending}
      />
    </div>
  );
}
