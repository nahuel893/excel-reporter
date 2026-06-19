import { formatNumber } from '../lib/format'
import { HeatmapCell } from './HeatmapCell'
import type { Row } from '../types'

interface DataRowProps {
  row: Row
}

/**
 * A standard data row in the report table.
 * Column-specific ink colors match the Excel heatmap/conditional formatting:
 *   MMAA → #C00000, MA → #808000, Objetivo → #4472C4
 * Heatmap is applied ONLY to "Tend vs Obj (%)" via HeatmapCell.
 */
export function DataRow({ row }: DataRowProps) {
  return (
    <tr>
      <td style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: '0.78rem' }}>
        {row.Sucursal}
      </td>
      <td className="numeric">{formatNumber(row.col_n2)}</td>
      <td className="numeric">{formatNumber(row.col_n1)}</td>
      <td className="numeric">{formatNumber(row['Total Ventas'])}</td>
      <td className="numeric">{formatNumber(row.Tendencia)}</td>
      <td className="numeric" style={{ color: '#C00000' }}>
        {formatNumber(row.MMAA)}
      </td>
      <td className="numeric" style={{ color: '#808000' }}>
        {formatNumber(row.MA)}
      </td>
      <td className="numeric" style={{ color: '#4472C4' }}>
        {formatNumber(row.Objetivo)}
      </td>
      <HeatmapCell value={row['Tend vs Obj (%)']} />
    </tr>
  )
}
