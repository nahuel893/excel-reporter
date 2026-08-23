/**
 * Artifacts browser route — three-level navigation (service -> period -> files)
 * over data/output/, with inline preview limited to PNGs already on disk and
 * download links for xlsx/xlsm/pptx (RF-15..18).
 */

import { useState } from "react";
import { createRoute } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowLeft,
  Download,
  FileArchive,
  FileSpreadsheet,
  Folder,
  Image as ImageIcon,
} from "lucide-react";
import { rootRoute } from "./__root";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useArtifactTree,
  type ArtifactFileEntry,
} from "@/lib/queries";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export const artifactsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/artifacts",
  component: ArtifactsPage,
});

const UNCLASSIFIED_KEY = "__unclassified__";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("es-AR");
}

// ─── Level 3: file rows ─────────────────────────────────────────────────────

function DownloadRow({ file, icon }: { file: ArtifactFileEntry; icon: React.ReactNode }) {
  return (
    <div
      className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 transition-colors duration-150 hover:bg-accent/40"
      data-testid={`file-row-${file.path}`}
    >
      <div className="flex min-w-0 items-center gap-2">
        {icon}
        <div className="min-w-0">
          <p className="truncate text-sm text-foreground">{file.name}</p>
          <p className="text-xs text-muted-foreground">
            {formatBytes(file.size_bytes)} · {formatDate(file.mtime)}
          </p>
        </div>
      </div>
      <a
        href={api.artifacts.fileUrl(file.path)}
        download={file.name}
        className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-primary transition-colors duration-150 hover:text-primary/80"
        data-testid={`download-link-${file.path}`}
      >
        <Download size={14} aria-hidden="true" />
        Descargar
      </a>
    </div>
  );
}

function ImagePreviewCard({ file }: { file: ArtifactFileEntry }) {
  const label =
    file.sheet && file.range ? `Hoja ${file.sheet} · Rango ${file.range}` : file.name;
  return (
    <div
      className="overflow-hidden rounded-md border border-border"
      data-testid={`image-card-${file.path}`}
    >
      <img
        src={api.artifacts.fileUrl(file.path)}
        alt={label}
        loading="lazy"
        className="h-32 w-full object-cover"
        data-testid={`image-preview-${file.path}`}
      />
      <div className="px-2 py-1.5">
        <p className="truncate text-xs text-foreground">{label}</p>
        <p className="text-[11px] text-muted-foreground">{formatBytes(file.size_bytes)}</p>
      </div>
    </div>
  );
}

function FileSection({
  title,
  files,
  empty,
  variant,
}: {
  title: string;
  files: ArtifactFileEntry[];
  empty: string;
  variant: "principal" | "imagenes" | "backups";
}) {
  return (
    <div className="mb-6">
      <h2 className="mb-2 text-sm font-semibold text-foreground">{title}</h2>
      {files.length === 0 ? (
        <p className="text-xs text-muted-foreground">{empty}</p>
      ) : variant === "imagenes" ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {files.map((f) => (
            <ImagePreviewCard key={f.path} file={f} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {files.map((f) => (
            <DownloadRow
              key={f.path}
              file={f}
              icon={
                variant === "backups" ? (
                  <FileArchive size={16} className="shrink-0 text-muted-foreground" aria-hidden="true" />
                ) : (
                  <FileSpreadsheet size={16} className="shrink-0 text-muted-foreground" aria-hidden="true" />
                )
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Level 1 / 2: navigation cards ──────────────────────────────────────────

function NavCard({
  icon,
  title,
  subtitle,
  warning,
  onClick,
  testId,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  warning?: string;
  onClick: () => void;
  testId: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      className={cn(
        "flex flex-col items-start gap-2 rounded-lg border border-border p-4 text-left",
        "transition-colors duration-150 hover:bg-accent/40 hover:border-primary/40",
      )}
    >
      <div className="flex w-full items-center justify-between">
        {icon}
        {warning ? (
          <Badge variant="destructive" className="gap-1">
            <AlertTriangle size={12} aria-hidden="true" />
            {warning}
          </Badge>
        ) : null}
      </div>
      <div>
        <p className="font-mono text-sm text-foreground">{title}</p>
        {subtitle ? <p className="text-xs text-muted-foreground">{subtitle}</p> : null}
      </div>
    </button>
  );
}

// ─── Empty / loading states ─────────────────────────────────────────────────

function LoadingGrid() {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4" data-testid="artifacts-loading">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-24 w-full rounded-lg" />
      ))}
    </div>
  );
}

function ErrorState({ error }: { error: unknown }) {
  const detail = error instanceof Error ? error.message : String(error ?? "");
  return (
    <div
      className="flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed border-destructive/40 py-20"
      data-testid="artifacts-error"
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full border border-destructive/40 bg-destructive/10">
        <AlertTriangle size={20} className="text-destructive" aria-hidden="true" />
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-destructive">
          No se pudo leer la lista de archivos
        </p>
        <p className="mt-1 text-xs text-muted-foreground/60">
          Esto no significa que no haya reportes generados: el backend no respondió.
        </p>
        {detail && (
          <p className="mt-2 font-mono text-xs text-muted-foreground/60">{detail}</p>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div
      className="flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed border-border py-20"
      data-testid="artifacts-empty"
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full border border-border bg-muted/30">
        <Folder size={20} className="text-muted-foreground/50" aria-hidden="true" />
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-muted-foreground">No hay archivos generados</p>
        <p className="mt-1 text-xs text-muted-foreground/60">
          Todavía no se generó ningún reporte en <code className="font-mono">data/output/</code>.
        </p>
      </div>
    </div>
  );
}

// ─── Breadcrumb ──────────────────────────────────────────────────────────────

function Breadcrumb({
  label,
  periodo,
  onReset,
  onBackToService,
}: {
  /** Display text for the current service level — not necessarily a slug:
   *  the unclassified bucket shows a Spanish label with no slug behind it. */
  label: string | null;
  periodo: string | null;
  onReset: () => void;
  onBackToService: () => void;
}) {
  if (!label) return null;
  return (
    <div className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
      <button
        type="button"
        onClick={onReset}
        className="inline-flex items-center gap-1 transition-colors duration-150 hover:text-foreground"
        data-testid="breadcrumb-root"
      >
        <ArrowLeft size={12} aria-hidden="true" />
        Archivos
      </button>
      <span>/</span>
      {periodo ? (
        <>
          <button
            type="button"
            onClick={onBackToService}
            className="font-mono transition-colors duration-150 hover:text-foreground"
            data-testid="breadcrumb-service"
          >
            {label}
          </button>
          <span>/</span>
          <span className="font-mono text-foreground">{periodo}</span>
        </>
      ) : (
        <span className="font-mono text-foreground">{label}</span>
      )}
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export function ArtifactsPage() {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [selectedPeriodo, setSelectedPeriodo] = useState<string | null>(null);

  // The unclassified bucket is not a service: it already rides along in the
  // unfiltered response, so this view asks for the same query key the root
  // view used and reads it straight out of the cache — no second walk.
  const isUnclassifiedView = selectedSlug === UNCLASSIFIED_KEY;
  const treeSlug = isUnclassifiedView ? undefined : selectedSlug ?? undefined;
  const treePeriodo = isUnclassifiedView ? undefined : selectedPeriodo ?? undefined;

  const { data, isLoading, isError, error } = useArtifactTree(treeSlug, treePeriodo);

  const resetToRoot = () => {
    setSelectedSlug(null);
    setSelectedPeriodo(null);
  };
  const backToService = () => setSelectedPeriodo(null);

  const service = data?.services.find((s) => s.slug === selectedSlug);
  const period = service?.periods.find((p) => p.periodo === selectedPeriodo);

  let content: React.ReactNode;

  if (isLoading) {
    content = <LoadingGrid />;
  } else if (isError) {
    // Never fall through to the empty state here: "no hay archivos" and "no
    // pude preguntar" look identical on screen and mean opposite things.
    content = <ErrorState error={error} />;
  } else if (isUnclassifiedView) {
    const files = data?.unclassified ?? [];
    content = (
      <FileSection
        title="Sin clasificar"
        files={files}
        empty="No hay archivos sueltos."
        variant="principal"
      />
    );
  } else if (selectedSlug && selectedPeriodo) {
    if (!period) {
      // The response came back without the period the breadcrumb points at.
      // Falling through would draw the root grid under a breadcrumb that says
      // otherwise, which reads as "the period is empty" instead of "I lost it".
      content = (
        <p className="text-sm text-destructive" data-testid="period-missing">
          El período {selectedPeriodo} no vino en la respuesta del servidor.
        </p>
      );
    } else if (period.unreadable) {
      content = (
        <p className="text-sm text-destructive">
          No se pudo leer esta carpeta. Sus archivos son desconocidos.
        </p>
      );
    } else {
      content = (
        <>
          <FileSection title="Principal" files={period.principal} empty="Sin archivos." variant="principal" />
          <FileSection title="Imágenes" files={period.imagenes} empty="Sin imágenes generadas." variant="imagenes" />
          <FileSection title="Backups" files={period.backups} empty="Sin backups." variant="backups" />
        </>
      );
    }
  } else if (selectedSlug) {
    if (!service) {
      // Same lie as period-missing, one level up: without this the root grid
      // renders under a breadcrumb pointing at a service, reading as "this
      // service generated nothing".
      content = (
        <p className="text-sm text-destructive" data-testid="service-missing">
          El servicio {selectedSlug} no vino en la respuesta del servidor.
        </p>
      );
    } else if (service.unreadable) {
      content = (
        <p className="text-sm text-destructive">
          No se pudo leer la carpeta de este servicio. Sus períodos son desconocidos.
        </p>
      );
    } else if (service.periods.length === 0) {
      content = <p className="text-sm text-muted-foreground">Sin períodos generados para este servicio.</p>;
    } else {
      content = (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
          {service.periods.map((p) => (
            <NavCard
              key={p.periodo}
              icon={<Folder size={18} className="text-muted-foreground" aria-hidden="true" />}
              title={p.periodo}
              warning={
                p.unreadable
                  ? "No se pudo leer"
                  : p.anomalous
                    ? "Carpeta anómala"
                    : undefined
              }
              onClick={() => setSelectedPeriodo(p.periodo)}
              testId={`period-card-${p.periodo}`}
            />
          ))}
        </div>
      );
    }
  } else {
    const services = data?.services ?? [];
    const unclassified = data?.unclassified ?? [];
    if (services.length === 0 && unclassified.length === 0) {
      content = <EmptyState />;
    } else {
      content = (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
          {services.map((s) => (
            <NavCard
              key={s.slug}
              icon={<Folder size={18} className="text-primary" aria-hidden="true" />}
              title={s.slug}
              onClick={() => setSelectedSlug(s.slug)}
              testId={`service-card-${s.slug}`}
            />
          ))}
          {unclassified.length > 0 ? (
            <NavCard
              icon={<ImageIcon size={18} className="text-muted-foreground" aria-hidden="true" />}
              title="Sin clasificar"
              subtitle={`${unclassified.length} archivo(s) suelto(s)`}
              warning="Revisar"
              onClick={() => setSelectedSlug(UNCLASSIFIED_KEY)}
              testId="unclassified-card"
            />
          ) : null}
        </div>
      );
    }
  }

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center gap-3">
        <Folder size={20} className="text-muted-foreground" aria-hidden="true" />
        <h1 className="text-2xl font-bold tracking-tight">Archivos</h1>
      </div>

      <Separator className="mb-6" />

      <Breadcrumb
        label={isUnclassifiedView ? "Sin clasificar" : selectedSlug}
        periodo={selectedPeriodo}
        onReset={resetToRoot}
        onBackToService={backToService}
      />

      {content}
    </div>
  );
}
