/**
 * TanStack Query mutation hooks.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, TriggerRunRequest } from "./api";

export function useSaveConfig(filename: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (content: Record<string, unknown>) =>
      api.configs.update(filename, content),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["configs"] });
      void qc.invalidateQueries({ queryKey: ["config", filename] });
    },
  });
}

export function useTriggerRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: TriggerRunRequest) => api.runs.trigger(req),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

export function useSaveContactos() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (content: Record<string, unknown>) =>
      api.contactos.update(content),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["contactos"] });
    },
  });
}
