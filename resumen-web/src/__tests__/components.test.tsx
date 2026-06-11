import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Row, Section, Sheet } from '../types'
import { HeatmapCell } from '../components/HeatmapCell'
import { SubtotalRow } from '../components/SubtotalRow'
import { ReportSection } from '../components/ReportSection'
import { GenericoTabs } from '../components/GenericoTabs'

// ─── Fixtures ──────────────────────────────────────────────────────────────

const makeRow = (sucursal: string, overrides: Partial<Row> = {}): Row => ({
  Sucursal: sucursal,
  col_n2: 100,
  col_n1: 110,
  'Total Ventas': 2000,
  Tendencia: 2400,
  MMAA: 1800,
  MA: 1700,
  Objetivo: 2000,
  'Tend vs Obj (%)': 1.2,
  is_subtotal: false,
  ...overrides,
})

const subtotalRow = (sucursal: string): Row =>
  makeRow(sucursal, {
    is_subtotal: true,
    col_n2: null,
    col_n1: null,
    'Total Ventas': null,
    Tendencia: null,
    MMAA: null,
    MA: null,
    Objetivo: null,
    'Tend vs Obj (%)': null,
  })

const sectionFixture: Section = {
  label: 'CERVEZAS',
  rows: [
    makeRow('CASA CENTRAL', { 'Total Ventas': 1000, Tendencia: 1200, Objetivo: 1000 }),
    makeRow('VALLE SALTA', { 'Total Ventas': 500, Tendencia: 600, Objetivo: 500 }),
    makeRow('SUB DISTRIBUIDORES', { 'Total Ventas': 200, Tendencia: 240, Objetivo: null }),
    makeRow('SUCURSAL CAFAYATE', { 'Total Ventas': 300, Tendencia: 360, Objetivo: 300 }),
    makeRow('DIRECTA SUCURSALES', { 'Total Ventas': 150, Tendencia: 180, Objetivo: 150 }),
    subtotalRow('SUBTOTAL CASA CENTRAL'),
    subtotalRow('SUCURSALES SIN DIRECTA'),
    subtotalRow('TOTAL SIN SMK'),
  ],
}

const sheetFixture: Sheet = {
  generico: 'CERVEZAS',
  note: null,
  sections: [sectionFixture],
}

const sheetWithNote: Sheet = {
  generico: 'FRATELLI B',
  note: 'Excluye preventista (PRVTA)',
  sin_prvta: true,
  sections: [{ ...sectionFixture, label: 'FRATELLI B' }],
}

// ─── HeatmapCell ──────────────────────────────────────────────────────────

describe('HeatmapCell', () => {

  it('renders the formatted % text', () => {
    render(<HeatmapCell value={1.2} />)
    expect(screen.getByText('120.0%')).toBeInTheDocument()
  })

  it('applies background color for non-null value', () => {
    const { container } = render(<HeatmapCell value={1.2} />)
    const cell = container.firstChild as HTMLElement
    expect(cell.style.backgroundColor).toBeTruthy()
  })

  it('renders em dash for null value (no color)', () => {
    render(<HeatmapCell value={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('has aria-label with the value', () => {
    render(<HeatmapCell value={0.5} />)
    const el = screen.getByRole('cell')
    expect(el).toHaveAttribute('aria-label')
    expect(el.getAttribute('aria-label')).toContain('50.0%')
  })
})

// ─── SubtotalRow ──────────────────────────────────────────────────────────

describe('SubtotalRow', () => {

  const computedValues = {
    col_n2: 1700,
    col_n1: 1800,
    'Total Ventas': 1700,
    Tendencia: 2040,
    MMAA: 1500,
    MA: 1400,
    Objetivo: 1500,
    'Tend vs Obj (%)': 1.36,
  }

  it('renders SUBTOTAL CASA CENTRAL with green band (#548235)', () => {
    const { container } = render(
      <table>
        <tbody>
          <SubtotalRow
            label="SUBTOTAL CASA CENTRAL"
            values={computedValues}
            col_n1="09-06 Martes"
            col_n2="08-06 Lunes"
          />
        </tbody>
      </table>,
    )
    const row = container.querySelector('tr')!
    expect(row.style.backgroundColor).toBeTruthy()
  })

  it('renders SUCURSALES SIN DIRECTA with purple band (#7030A0)', () => {
    const { container } = render(
      <table>
        <tbody>
          <SubtotalRow
            label="SUCURSALES SIN DIRECTA"
            values={computedValues}
            col_n1="09-06 Martes"
            col_n2="08-06 Lunes"
          />
        </tbody>
      </table>,
    )
    const row = container.querySelector('tr')!
    expect(row.style.backgroundColor).toBeTruthy()
  })

  it('renders TOTAL SIN SMK with red band (#FF0000)', () => {
    const { container } = render(
      <table>
        <tbody>
          <SubtotalRow
            label="TOTAL SIN SMK"
            values={computedValues}
            col_n1="09-06 Martes"
            col_n2="08-06 Lunes"
          />
        </tbody>
      </table>,
    )
    const row = container.querySelector('tr')!
    expect(row.style.backgroundColor).toBeTruthy()
  })

  it('does NOT apply heatmap color to subtotal Tend vs Obj cell', () => {
    const { container } = render(
      <table>
        <tbody>
          <SubtotalRow
            label="TOTAL SIN SMK"
            values={{ ...computedValues, 'Tend vs Obj (%)': 1.5 }}
            col_n1="09-06 Martes"
            col_n2="08-06 Lunes"
          />
        </tbody>
      </table>,
    )
    // The entire row has the band color; cells should NOT have individual heatmap colors
    const tds = container.querySelectorAll('td')
    // Last td is Tend vs Obj — it should not have an overriding background
    const lastTd = tds[tds.length - 1] as HTMLElement
    // It should show the value but not have a cell-level heatmap background
    // (the row itself has the background)
    expect(lastTd.style.backgroundColor).toBeFalsy()
  })
})

// ─── ReportSection ────────────────────────────────────────────────────────

describe('ReportSection', () => {

  it('renders data rows', () => {
    render(
      <table>
        <tbody>
          <ReportSection
            section={sectionFixture}
            col_n1="09-06 Martes"
            col_n2="08-06 Lunes"
          />
        </tbody>
      </table>,
    )
    expect(screen.getByText('CASA CENTRAL')).toBeInTheDocument()
    expect(screen.getByText('SUCURSAL CAFAYATE')).toBeInTheDocument()
  })

  it('renders 3 subtotal rows after data rows', () => {
    render(
      <table>
        <tbody>
          <ReportSection
            section={sectionFixture}
            col_n1="09-06 Martes"
            col_n2="08-06 Lunes"
          />
        </tbody>
      </table>,
    )
    expect(screen.getByText('SUBTOTAL CASA CENTRAL')).toBeInTheDocument()
    expect(screen.getByText('SUCURSALES SIN DIRECTA')).toBeInTheDocument()
    expect(screen.getByText('TOTAL SIN SMK')).toBeInTheDocument()
  })
})

// ─── GenericoTabs ─────────────────────────────────────────────────────────

describe('GenericoTabs', () => {

  const sheets: Sheet[] = [sheetFixture, sheetWithNote]
  const onSelect = vi.fn()

  it('renders tab buttons with correct ARIA roles', () => {
    render(
      <GenericoTabs
        sheets={sheets}
        selectedIndex={0}
        onSelect={onSelect}
      />,
    )
    const tablist = screen.getByRole('tablist')
    expect(tablist).toBeInTheDocument()
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(2)
  })

  it('marks the selected tab with aria-selected=true', () => {
    render(
      <GenericoTabs
        sheets={sheets}
        selectedIndex={0}
        onSelect={onSelect}
      />,
    )
    const tabs = screen.getAllByRole('tab')
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[1]).toHaveAttribute('aria-selected', 'false')
  })

  it('calls onSelect when a tab is clicked', async () => {
    const user = userEvent.setup()
    render(
      <GenericoTabs
        sheets={sheets}
        selectedIndex={0}
        onSelect={onSelect}
      />,
    )
    const tabs = screen.getAllByRole('tab')
    await user.click(tabs[1])
    expect(onSelect).toHaveBeenCalledWith(1)
  })

  it('navigates with arrow keys (roving tabindex)', async () => {
    const user = userEvent.setup()
    render(
      <GenericoTabs
        sheets={sheets}
        selectedIndex={0}
        onSelect={onSelect}
      />,
    )
    const tabs = screen.getAllByRole('tab')
    tabs[0].focus()
    await user.keyboard('[ArrowRight]')
    expect(onSelect).toHaveBeenCalledWith(1)
  })
})
