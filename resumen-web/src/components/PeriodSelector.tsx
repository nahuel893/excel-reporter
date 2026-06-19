import { useState } from 'react'

interface PeriodSelectorProps {
  initialDesde?: string
  initialHasta?: string
  onSubmit: (desde: string, hasta: string) => void
  isPending?: boolean
}

/**
 * Month range selector — labeled inputs meeting WCAG 3.3.2 (form labels).
 * 44px touch targets. Submits on form submit or "Actualizar" button click.
 */
export function PeriodSelector({
  initialDesde = '',
  initialHasta = '',
  onSubmit,
  isPending = false,
}: PeriodSelectorProps) {
  const [desde, setDesde] = useState(initialDesde)
  const [hasta, setHasta] = useState(initialHasta)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (desde && hasta) {
      onSubmit(desde, hasta)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-wrap items-end gap-3 px-4 py-3"
      aria-label="Seleccionar período"
    >
      <div className="flex flex-col gap-1">
        <label
          htmlFor="fecha-desde"
          style={{ fontSize: '0.72rem', color: 'var(--ink-soft)', fontWeight: 500 }}
        >
          Desde
        </label>
        <input
          id="fecha-desde"
          type="date"
          value={desde}
          onChange={(e) => setDesde(e.target.value)}
          required
          aria-label="Fecha desde"
          style={{
            minHeight: '44px',
            padding: '0 12px',
            border: '1px solid var(--paper-rule)',
            borderRadius: 4,
            background: 'white',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '0.85rem',
            color: 'var(--ink)',
          }}
        />
      </div>

      <div className="flex flex-col gap-1">
        <label
          htmlFor="fecha-hasta"
          style={{ fontSize: '0.72rem', color: 'var(--ink-soft)', fontWeight: 500 }}
        >
          Hasta
        </label>
        <input
          id="fecha-hasta"
          type="date"
          value={hasta}
          onChange={(e) => setHasta(e.target.value)}
          required
          aria-label="Fecha hasta"
          style={{
            minHeight: '44px',
            padding: '0 12px',
            border: '1px solid var(--paper-rule)',
            borderRadius: 4,
            background: 'white',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '0.85rem',
            color: 'var(--ink)',
          }}
        />
      </div>

      <button
        type="submit"
        disabled={isPending || !desde || !hasta}
        style={{
          minHeight: '44px',
          minWidth: '44px',
          padding: '0 20px',
          background: 'var(--header-navy)',
          color: 'white',
          border: 'none',
          borderRadius: 4,
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: '0.9rem',
          cursor: isPending ? 'wait' : 'pointer',
          opacity: isPending ? 0.7 : 1,
          transition: 'opacity 0.15s',
        }}
      >
        {isPending ? 'Cargando…' : 'Actualizar'}
      </button>
    </form>
  )
}
