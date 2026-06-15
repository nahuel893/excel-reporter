/**
 * LiveLogStream — consumes SSE at /mgmt/runs/{run_id}/stream and renders
 * a scrollable, auto-scroll terminal-style log view.
 *
 * - While status === "running": EventSource streams live lines.
 * - While status === "finished"|"error"|"interrupted": fetches full log via GET /mgmt/runs/{run_id}/log.
 * - Auto-scrolls to bottom on new lines; respects user scroll (pauses auto-scroll if
 *   user scrolled up, resumes on bottom button click).
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { ChevronDown, AlertCircle, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface LiveLogStreamProps {
  runId: string;
  status: "running" | "success" | "error" | "interrupted";
  className?: string;
}

type LogLine = { ts: string; text: string };

function StatusBadge({ status }: { status: LiveLogStreamProps["status"] }) {
  if (status === "running") {
    return (
      <span className="flex items-center gap-1.5 text-xs font-medium text-blue-400">
        <Loader2 size={12} className="animate-spin" />
        En ejecución
      </span>
    );
  }
  if (status === "success") {
    return (
      <span className="flex items-center gap-1.5 text-xs font-medium text-emerald-400">
        <CheckCircle2 size={12} />
        Finalizado
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 text-xs font-medium text-destructive">
      <XCircle size={12} />
      Error
    </span>
  );
}

export function LiveLogStream({ runId, status, className }: LiveLogStreamProps) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isPaused, setIsPaused] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  // Auto-scroll to bottom unless user scrolled up
  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    if (!isPaused && lines.length > 0) {
      requestAnimationFrame(scrollToBottom);
    }
  }, [lines, isPaused, scrollToBottom]);

  // Detect manual scroll
  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setIsPaused(!atBottom);
  }, []);

  // SSE / GET based on status
  useEffect(() => {
    if (!runId) return;

    // Reset state on new runId or status change
    setLines([]);
    setError(null);

    if (status !== "running") {
      // Fetch full static log for finished runs
      setIsLoading(true);
      fetch(`/mgmt/runs/${encodeURIComponent(runId)}/log`)
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.text();
        })
        .then((text) => {
          const parsed = text
            .split("\n")
            .filter((l) => l.trim())
            .map((line) => {
              // Try to extract timestamp from line start: [YYYY-MM-DD HH:MM:SS]
              // or fallback to just use the line
              const m = line.match(/^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\]?\s*/);
              return {
                ts: m ? m[1] : "",
                text: line.replace(/^\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\]?\s*/, ""),
              };
            });
          setLines(parsed);
          setIsLoading(false);
        })
        .catch((err) => {
          setError(String(err));
          setIsLoading(false);
        });
      return;
    }

    // Running — open SSE
    const url = `/mgmt/runs/${encodeURIComponent(runId)}/stream`;
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener("log", (e: MessageEvent) => {
      const raw = e.data;
      const m = raw.match(/^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\]?\s*/);
      setLines((prev) => [
        ...prev,
        {
          ts: m ? m[1] : "",
          text: raw.replace(/^\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\]?\s*/, ""),
        },
      ]);
    });

    es.addEventListener("done", () => {
      es.close();
    });

    es.onerror = () => {
      // Don't clobber — just note disconnect (may reconnect)
    };

    return () => {
      es.close();
    };
  }, [runId, status]);

  return (
    <div className={cn("flex flex-col rounded-lg border border-border bg-[#0d0d0f]", className)}>
      {/* Terminal header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-muted-foreground">
            logs / {runId}
          </span>
          <StatusBadge status={status} />
        </div>
        <button
          onClick={() => {
            setIsPaused(false);
            scrollToBottom();
          }}
          className={cn(
            "flex items-center gap-1 rounded px-2 py-1 text-[11px] transition-colors",
            isPaused
              ? "bg-primary/20 text-primary hover:bg-primary/30"
              : "text-muted-foreground hover:text-foreground",
          )}
          title={isPaused ? "Continuar scroll automático" : "Pausar scroll automático"}
        >
          {isPaused ? <ChevronDown size={12} /> : null}
          {isPaused ? "Reanudar" : "Auto-scroll"}
        </button>
      </div>

      {/* Log body */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto font-mono text-xs leading-relaxed"
        style={{ maxHeight: "400px" }}
      >
        {isLoading && (
          <div className="flex items-center gap-2 px-4 py-6 text-muted-foreground">
            <Loader2 size={14} className="animate-spin" />
            <span>Cargando logs…</span>
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 px-4 py-6 text-destructive">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!isLoading && !error && lines.length === 0 && (
          <div className="px-4 py-6 text-muted-foreground">
            <span>Esperando output…</span>
          </div>
        )}

        {lines.map((line, i) => (
          <div
            key={i}
            className={cn(
              "flex gap-3 px-4 py-0.5",
              i % 2 === 0 ? "bg-[#0d0d0f]" : "bg-[#111113]",
            )}
          >
            {line.ts && (
              <span className="shrink-0 text-[10px] text-muted-foreground/40">{line.ts}</span>
            )}
            <span
              className={cn(
                "break-all",
                line.text.startsWith("ERROR") || line.text.startsWith("Traceback")
                  ? "text-destructive"
                  : line.text.startsWith("WARNING") || line.text.startsWith("warn")
                  ? "text-amber-400"
                  : "text-[#e2e8f0]",
              )}
            >
              {line.text}
            </span>
          </div>
        ))}

        {/* Scroll anchor */}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}