import { useMutation } from '@tanstack/react-query'
import { fetchDatos } from './fetchDatos'
import type { DatosRequest, DatosResponse } from '../types'

/**
 * react-query mutation hook for fetching report data.
 *
 * Uses useMutation because fetching is triggered by user action (form submit /
 * period change), not automatically on mount.
 *
 * Usage:
 *   const { mutate, data, isPending, isError, error } = useDatos()
 *   mutate({ fecha_desde, fecha_hasta, ... })
 */
export function useDatos() {
  return useMutation<DatosResponse, Error, DatosRequest>({
    mutationFn: fetchDatos,
  })
}
