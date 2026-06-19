import { describe, it, expect } from 'vitest'
import { computeSubtotals } from '../lib/subtotals'
import type { Row } from '../types'

// Helper to build a data row
const row = (sucursal: string, overrides: Partial<Row> = {}): Row => ({
  Sucursal: sucursal,
  col_n2: 10,
  col_n1: 20,
  'Total Ventas': 100,
  Tendencia: 120,
  MMAA: 90,
  MA: 85,
  Objetivo: 100,
  'Tend vs Obj (%)': 1.2,
  is_subtotal: false,
  ...overrides,
})

const subtotalRow = (sucursal: string): Row =>
  row(sucursal, { is_subtotal: true, col_n2: null, col_n1: null, 'Total Ventas': null, Tendencia: null, MMAA: null, MA: null, Objetivo: null, 'Tend vs Obj (%)': null })

describe('computeSubtotals', () => {
  it('sums CC family correctly', () => {
    const rows: Row[] = [
      row('CASA CENTRAL', { 'Total Ventas': 1000, Tendencia: 1200, Objetivo: 1000 }),
      row('VALLE SALTA', { 'Total Ventas': 500, Tendencia: 600, Objetivo: 500 }),
      row('SUB DISTRIBUIDORES', { 'Total Ventas': 200, Tendencia: 240, Objetivo: null }),
      row('SUCURSAL 1', { 'Total Ventas': 300, Tendencia: 360, Objetivo: 300 }),
      subtotalRow('SUBTOTAL CASA CENTRAL'),
      subtotalRow('SUCURSALES SIN DIRECTA'),
      subtotalRow('TOTAL SIN SMK'),
    ]

    const result = computeSubtotals(rows)

    // CC family = CASA CENTRAL + VALLE SALTA + SUB DISTRIBUIDORES
    expect(result['SUBTOTAL CASA CENTRAL']['Total Ventas']).toBe(1700)
    expect(result['SUBTOTAL CASA CENTRAL'].Tendencia).toBe(2040)
    // Objetivo: sum of non-null (1000 + 500), null ignored
    expect(result['SUBTOTAL CASA CENTRAL'].Objetivo).toBe(1500)
  })

  it('sums numbered sucursales (by exclusion)', () => {
    const rows: Row[] = [
      row('CASA CENTRAL', { 'Total Ventas': 1000 }),
      row('VALLE SALTA', { 'Total Ventas': 500 }),
      row('SUB DISTRIBUIDORES', { 'Total Ventas': 200 }),
      row('DIRECTA SUCURSALES', { 'Total Ventas': 150 }),
      row('SUCURSAL CAFAYATE', { 'Total Ventas': 300 }),
      row('SUCURSAL JUJUY', { 'Total Ventas': 250 }),
      subtotalRow('SUBTOTAL CASA CENTRAL'),
      subtotalRow('SUCURSALES SIN DIRECTA'),
      subtotalRow('TOTAL SIN SMK'),
    ]

    const result = computeSubtotals(rows)

    // Numbered = not CC family, not DIRECTA SUCURSALES, not subtotal labels
    expect(result['SUCURSALES SIN DIRECTA']['Total Ventas']).toBe(550)
  })

  it('computes TOTAL SIN SMK = CC + numbered + DIRECTA SUCURSALES', () => {
    const rows: Row[] = [
      row('CASA CENTRAL', { 'Total Ventas': 1000, Tendencia: 1200, Objetivo: 900 }),
      row('DIRECTA SUCURSALES', { 'Total Ventas': 150, Tendencia: 180, Objetivo: 150 }),
      row('SUCURSAL CAFAYATE', { 'Total Ventas': 300, Tendencia: 360, Objetivo: 300 }),
      subtotalRow('SUBTOTAL CASA CENTRAL'),
      subtotalRow('SUCURSALES SIN DIRECTA'),
      subtotalRow('TOTAL SIN SMK'),
    ]

    const result = computeSubtotals(rows)

    // TOTAL = CC(1000) + numbered(300) + DIRECTA(150) = 1450
    expect(result['TOTAL SIN SMK']['Total Ventas']).toBe(1450)
  })

  it('preserves null Objetivo when ALL rows have null Objetivo', () => {
    const rows: Row[] = [
      row('CASA CENTRAL', { Objetivo: null, 'Tend vs Obj (%)': null }),
      row('VALLE SALTA', { Objetivo: null, 'Tend vs Obj (%)': null }),
      row('SUB DISTRIBUIDORES', { Objetivo: null, 'Tend vs Obj (%)': null }),
      subtotalRow('SUBTOTAL CASA CENTRAL'),
      subtotalRow('SUCURSALES SIN DIRECTA'),
      subtotalRow('TOTAL SIN SMK'),
    ]

    const result = computeSubtotals(rows)

    // All null → null (NOT 0)
    expect(result['SUBTOTAL CASA CENTRAL'].Objetivo).toBeNull()
    expect(result['SUBTOTAL CASA CENTRAL']['Tend vs Obj (%)']).toBeNull()
  })

  it('ignores existing is_subtotal rows in computation', () => {
    const rows: Row[] = [
      row('CASA CENTRAL', { 'Total Ventas': 1000 }),
      subtotalRow('SUBTOTAL CASA CENTRAL'),
      subtotalRow('SUCURSALES SIN DIRECTA'),
      subtotalRow('TOTAL SIN SMK'),
    ]

    const result = computeSubtotals(rows)

    // Subtotal rows themselves must NOT be summed
    expect(result['SUBTOTAL CASA CENTRAL']['Total Ventas']).toBe(1000)
  })

  it('computes Tend vs Obj (%) subtotal = Tendencia / Objetivo when truthy', () => {
    const rows: Row[] = [
      row('CASA CENTRAL', { Tendencia: 1200, Objetivo: 1000, 'Tend vs Obj (%)': 1.2 }),
      row('VALLE SALTA', { Tendencia: 600, Objetivo: 500, 'Tend vs Obj (%)': 1.2 }),
    ]

    const result = computeSubtotals(rows)

    const obj = result['SUBTOTAL CASA CENTRAL'].Objetivo!
    const tend = result['SUBTOTAL CASA CENTRAL'].Tendencia!
    const ratio = result['SUBTOTAL CASA CENTRAL']['Tend vs Obj (%)']

    expect(obj).toBe(1500)
    expect(tend).toBe(1800)
    expect(ratio).toBeCloseTo(tend / obj, 5)
  })

  it('Tend vs Obj (%) is null when Objetivo subtotal is null', () => {
    const rows: Row[] = [
      row('CASA CENTRAL', { Objetivo: null, Tendencia: 1000, 'Tend vs Obj (%)': null }),
    ]

    const result = computeSubtotals(rows)
    expect(result['SUBTOTAL CASA CENTRAL']['Tend vs Obj (%)']).toBeNull()
  })

  it('handles empty rows array', () => {
    const result = computeSubtotals([])
    expect(result['SUBTOTAL CASA CENTRAL']['Total Ventas']).toBeNull()
    expect(result['SUCURSALES SIN DIRECTA']['Total Ventas']).toBeNull()
    expect(result['TOTAL SIN SMK']['Total Ventas']).toBeNull()
  })
})
