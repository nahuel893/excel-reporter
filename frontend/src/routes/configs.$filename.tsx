/**
 * Config editor route — Card-wrapped rjsf form with dirty indicator,
 * loading button state, sonner toasts, and 422 inline errors.
 */

import { useState, useCallback } from "react";
import { createRoute, Link } from "@tanstack/react-router";
import { ChevronRight, Save, Loader2, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { rootRoute } from "./__root";
import { useConfig } from "@/lib/queries";
import { useSaveConfig } from "@/lib/mutations";
import { ConfigForm } from "@/components/ConfigForm";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
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

type TipoBadgeVariant =
  | "ventas"
  | "avances"
  | "champions-league"
  | "resumen-mensual"
  | "stock-diario"
  | "historico-fratelli"
  | "cartesiano"
  | "graficos-cobertura"
  | "ventas-articulo"
  | "historico-cliente"
  | "reporte-general-badie"
  | "reporte-rebotes"
  | "zinc";

function tipoToVariant(tipo: string): TipoBadgeVariant {
  const map: Record<string, TipoBadgeVariant> = {
    ventas: "ventas",
    avances: "avances",
    "champions-league": "champions-league",
    "resumen-mensual": "resumen-mensual",
    "stock-diario": "stock-diario",
    "historico-fratelli": "historico-fratelli",
    cartesiano: "cartesiano",
    "graficos-cobertura": "graficos-cobertura",
    "ventas-articulo": "ventas-articulo",
    "historico-cliente": "historico-cliente",
    "reporte-general-badie": "reporte-general-badie",
    "reporte-rebotes": "reporte-rebotes",
  };
  return map[tipo] ?? "zinc";
}

function LoadingSkeleton() {
  return (
    <div className="p-8" aria-busy="true">
      <div className="mb-6 flex items-center gap-2">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-4 w-4" />
        <Skeleton className="h-4 w-24" />
      </div>
      <Skeleton className="mb-6 h-8 w-64" />
      <div className="space-y-4">
        <Skeleton className="h-24 w-full rounded-lg" />
        <Skeleton className="h-24 w-full rounded-lg" />
        <Skeleton className="h-12 w-32 rounded-lg" />
      </div>
    </div>
  );
}

function ConfigEditorPage() {
  const { filename } = configEditorRoute.useParams();
  const { data, isLoading, error } = useConfig(filename);
  const saveConfig = useSaveConfig(filename);

  const [serverErrors, setServerErrors] = useState<FieldError[]>([]);
  const [isDirty, setIsDirty] = useState(false);

  const handleChange = useCallback(() => {
    setIsDirty(true);
  }, []);

  const handleSave = useCallback(
    (formData: Record<string, unknown>) => {
      setServerErrors([]);
      saveConfig.mutate(formData, {
        onSuccess: () => {
          setIsDirty(false);
          toast.success("Guardado correctamente", {
            description: `${filename} actualizado`,
            icon: <Save size={14} />,
          });
        },
        onError: (err) => {
          const apiErr = err as ApiError;
          if (apiErr.status === 422) {
            const detail = apiErr.detail as { detail?: FieldError[] } | FieldError[];
            const errs = Array.isArray(detail)
              ? detail
              : (detail as { detail?: FieldError[] }).detail ?? [];
            setServerErrors(errs);
            toast.error("Error de validación", {
              description: "Revisá los campos marcados en rojo.",
              icon: <AlertTriangle size={14} />,
            });
          } else {
            toast.error("Error al guardar", {
              description: String(apiErr.detail ?? err),
              icon: <AlertTriangle size={14} />,
            });
          }
        },
      });
    },
    [saveConfig, filename],
  );

  if (isLoading) return <LoadingSkeleton />;

  if (error || !data) {
    return (
      <div className="p-8">
        <div
          className="flex items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          role="alert"
        >
          <AlertTriangle size={16} aria-hidden="true" />
          Error al cargar: {String(error)}
        </div>
      </div>
    );
  }

  const tipo = String(data.content.tipo ?? "");

  return (
    <div className="p-8">
      {/* Breadcrumb */}
      <nav
        className="mb-6 flex items-center gap-1.5 text-xs text-muted-foreground"
        aria-label="Breadcrumb"
      >
        <Link
          to="/configs"
          className="hover:text-foreground transition-colors"
        >
          Configuraciones
        </Link>
        <ChevronRight size={12} aria-hidden="true" />
        <span className="font-medium text-foreground">{filename}</span>
      </nav>

      {/* Page title row */}
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight">{filename}</h1>
        {tipo && (
          <Badge variant={tipoToVariant(tipo)}>{tipo}</Badge>
        )}
        {isDirty && (
          <span
            className="dirty-dot h-2 w-2 rounded-full bg-amber-400"
            title="Cambios sin guardar"
            aria-label="Cambios sin guardar"
          />
        )}
      </div>

      <Separator className="mb-6" />

      {/* 422 error alert */}
      {serverErrors.length > 0 && (
        <div
          className="mb-6 flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          role="alert"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-medium">Error de validación del servidor</p>
            <ul className="mt-1 list-disc pl-4 text-xs space-y-0.5">
              {serverErrors.map((e, i) => (
                <li key={i}>
                  <span className="font-mono">{e.loc.join(" › ")}</span>:{" "}
                  {e.msg}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Form card */}
      <Card>
        <CardHeader>
          <CardTitle>Editar configuración</CardTitle>
          <CardDescription>
            Modificá los campos y guardá para aplicar los cambios.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ConfigForm
            schema={data.schema}
            formData={data.content}
            onChange={handleChange}
            onSubmit={handleSave}
            serverErrors={serverErrors}
            isSaving={saveConfig.isPending}
            submitLabel={
              saveConfig.isPending ? (
                <span className="flex items-center gap-2">
                  <Loader2 size={14} className="animate-spin" />
                  Guardando...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <Save size={14} />
                  Guardar
                </span>
              )
            }
          />
        </CardContent>
      </Card>
    </div>
  );
}
