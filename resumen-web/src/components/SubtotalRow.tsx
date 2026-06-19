import { formatNumber, formatPercent } from '../lib/format'
import type { SubtotalValues } from '../types'

interface SubtotalRowProps {
  label: 'SUBTOTAL CASA CENTRAL' | 'SUCURSALES SIN DIRECTA' | 'TOTAL SIN SMK'
  values: SubtotalValues
  col_n1: string
  col_n2: string
}

const BAND_COLORS: Record<string, string> = {
  'SUBTOTAL CASA CENTRAL': '#548235',
  'SUCURSALES SIN DIRECTA': '#7030A0',
  'TOTAL SIN SMK': '#FF0000',
}

/**
 * Subtotal band row — colored full-width band with white text.
 * Heatmap is NOT applied here (the band color IS the visual signal).
 * ADR-2: values are recomputed by the frontend via computeSubtotals.
 */
export function SubtotalRow({ label, values }: SubtotalRowProps) {
  const bg = BAND_COLORS[label] ?? '#888888'

  const cellStyle: React.CSSProperties = {
    color: '#FFFFFF',
    fontFamily: "'JetBrains Mono', monospace",
    fontVariantNumeric: 'tabular-nums',
    textAlign: 'right',
    fontSize: '0.75rem',
    fontWeight: 600,
    // No individual heatmap background on cells
    backgroundColor: undefined,
  }

  return (
    <tr
      className="subtotal-row"
      style={{ backgroundColor: bg }}
      data-subtotal-label={label}
    >
      <td style={{ ...cellStyle, textAlign: 'left', fontFamily: "'Fraunces', Georgia, serif" }}>
        {label}
      </td>
      <td style={cellStyle}>{formatNumber(values.col_n2)}</td>
      <td style={cellStyle}>{formatNumber(values.col_n1)}</td>
      <td style={cellStyle}>{formatNumber(values['Total Ventas'])}</td>
      <td style={cellStyle}>{formatNumber(values.Tendencia)}</td>
      <td style={cellStyle}>{formatNumber(values.MMAA)}</td>
      <td style={cellStyle}>{formatNumber(values.MA)}</td>
      <td style={cellStyle}>{formatNumber(values.Objetivo)}</td>
      {/* Tend vs Obj on subtotal row uses text only — NOT heatmap */}
      <td style={cellStyle}>{formatPercent(values['Tend vs Obj (%)'])}</td>
    </tr>
  )
}
