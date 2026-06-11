import { computeSubtotals } from '../lib/subtotals'
import { DataRow } from './DataRow'
import { SubtotalRow } from './SubtotalRow'
import type { Section } from '../types'

interface ReportSectionProps {
  section: Section
  col_n1: string
  col_n2: string
}

/**
 * One marca_split group: data rows followed by 3 computed subtotal rows.
 *
 * The backend emits is_subtotal rows with null numerics — they act as
 * position markers. We filter them out and re-render computed subtotals
 * with values from computeSubtotals() (ADR-2).
 */
export function ReportSection({ section, col_n1, col_n2 }: ReportSectionProps) {
  const allRows = section.rows
  const dataRows = allRows.filter((r) => !r.is_subtotal)
  const subtotals = computeSubtotals(allRows)

  return (
    <>
      {dataRows.map((row, i) => (
        <DataRow key={`${row.Sucursal}-${i}`} row={row} />
      ))}
      <SubtotalRow
        label="SUBTOTAL CASA CENTRAL"
        values={subtotals['SUBTOTAL CASA CENTRAL']}
        col_n1={col_n1}
        col_n2={col_n2}
      />
      <SubtotalRow
        label="SUCURSALES SIN DIRECTA"
        values={subtotals['SUCURSALES SIN DIRECTA']}
        col_n1={col_n1}
        col_n2={col_n2}
      />
      <SubtotalRow
        label="TOTAL SIN SMK"
        values={subtotals['TOTAL SIN SMK']}
        col_n1={col_n1}
        col_n2={col_n2}
      />
    </>
  )
}
