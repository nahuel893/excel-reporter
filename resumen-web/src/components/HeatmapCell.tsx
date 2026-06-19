import { getHeatmapColor } from '../lib/heatmap'
import { pickTextColor } from '../lib/contrastText'
import { formatPercent } from '../lib/format'

interface HeatmapCellProps {
  value: number | null
}

/**
 * Table cell for the "Tend vs Obj (%)" column on DATA rows only.
 * Applies the semáforo heatmap background (red→yellow→green) with
 * WCAG AA accessible text color (never color-only — the % value is always shown).
 */
export function HeatmapCell({ value }: HeatmapCellProps) {
  const bg = getHeatmapColor(value)
  const textColor = bg ? pickTextColor(bg) : undefined

  const formatted = formatPercent(value)
  const ariaLabel =
    value !== null
      ? `Tendencia vs Objetivo: ${formatted}`
      : 'Tendencia vs Objetivo: sin datos'

  return (
    <td
      role="cell"
      className="numeric"
      aria-label={ariaLabel}
      style={{
        backgroundColor: bg ?? 'transparent',
        color: textColor,
        fontWeight: bg ? 600 : undefined,
      }}
    >
      {formatted}
    </td>
  )
}
