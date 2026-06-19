import type { DatosRequest, DatosResponse } from '../types'

/**
 * POST /resumen-mensual/datos
 *
 * In dev: proxied to http://localhost:8000 via Vite proxy.
 * In prod: same-origin request under /resumen/ SPA mount.
 */
export async function fetchDatos(params: DatosRequest): Promise<DatosResponse> {
  const res = await fetch('/resumen-mensual/datos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })

  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(
      typeof detail === 'object' && 'detail' in detail
        ? String(detail.detail)
        : `HTTP ${res.status}`,
    )
  }

  return res.json() as Promise<DatosResponse>
}
