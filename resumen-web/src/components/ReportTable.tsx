import { ReportSection } from './ReportSection'
import type { Sheet, Meta } from '../types'

interface ReportTableProps {
  sheet: Sheet
  meta: Meta
}

/**
 * Renders one genérico's table: caption, sticky header, sections with subtotals.
 *
 * Accessibility:
 * - <caption> identifies the table by genérico name
 * - <th scope="col"> on all header cells
 * - Sticky thead clears the GenericoTabs bar (--tab-height CSS var)
 * - Numeric cells use JetBrains Mono (tabular-nums) for digit alignment
 */
export function ReportTable({ sheet, meta }: ReportTableProps) {
  const { col_n1, col_n2 } = meta

  return (
    <div className="overflow-x-auto">
      <table className="report-table" aria-label={`Reporte de ${sheet.generico}`}>
        <caption className="sr-only">{sheet.generico}</caption>
        <thead>
          <tr>
            <th scope="col" style={{ textAlign: 'left', minWidth: 160 }}>
              Sucursal
            </th>
            <th scope="col" style={{ minWidth: 90 }}>
              {col_n2}
            </th>
            <th scope="col" style={{ minWidth: 90 }}>
              {col_n1}
            </th>
            <th scope="col" style={{ minWidth: 90 }}>
              Total Ventas
            </th>
            <th scope="col" style={{ minWidth: 90 }}>
              Tendencia
            </th>
            <th scope="col" style={{ minWidth: 90, color: '#FFC7C7' }}>
              MMAA
            </th>
            <th scope="col" style={{ minWidth: 90, color: '#E8E8A0' }}>
              MA
            </th>
            <th scope="col" style={{ minWidth: 90, color: '#A8C4E8' }}>
              Objetivo
            </th>
            <th scope="col" style={{ minWidth: 90 }}>
              Tend vs Obj (%)
            </th>
          </tr>
        </thead>
        <tbody>
          {sheet.sections.map((section, i) => (
            <ReportSection
              key={`${section.label}-${i}`}
              section={section}
              col_n1={col_n1}
              col_n2={col_n2}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}
