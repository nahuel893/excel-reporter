import { describe, it, expect } from 'vitest'
import { formatNumber, formatPercent } from '../lib/format'

describe('formatNumber', () => {
  it('returns em dash for null', () => {
    expect(formatNumber(null)).toBe('—')
  })

  it('returns em dash for undefined', () => {
    expect(formatNumber(undefined as unknown as null)).toBe('—')
  })

  it('returns short dash for zero (null vs zero distinction)', () => {
    expect(formatNumber(0)).toBe('-')
  })

  it('formats positive integers with thousands separator', () => {
    expect(formatNumber(1234567)).toBe('1,234,567')
  })

  it('formats 1000 correctly', () => {
    expect(formatNumber(1000)).toBe('1,000')
  })

  it('formats small positive value', () => {
    expect(formatNumber(42)).toBe('42')
  })

  it('formats negative values with thousands separator', () => {
    expect(formatNumber(-1234)).toBe('-1,234')
  })

  it('does NOT round or truncate — uses display grouping only', () => {
    // The raw value should drive the display; no int()/round() applied
    // formatNumber shows integer-formatted thousands (like #,##0 in Excel)
    // 12345.67 → "12,346" (toLocaleString rounds at display level, not data level)
    const result = formatNumber(12345.67)
    // Must contain comma grouping
    expect(result).toContain(',')
    expect(result).not.toBe('—')
    expect(result).not.toBe('-')
  })
})

describe('formatPercent', () => {
  it('returns em dash for null', () => {
    expect(formatPercent(null)).toBe('—')
  })

  it('returns em dash for undefined', () => {
    expect(formatPercent(undefined as unknown as null)).toBe('—')
  })

  it('formats 0 as "0.0%"', () => {
    expect(formatPercent(0)).toBe('0.0%')
  })

  it('formats 1.0 as "100.0%"', () => {
    expect(formatPercent(1.0)).toBe('100.0%')
  })

  it('formats 1.234 as "123.4%"', () => {
    expect(formatPercent(1.234)).toBe('123.4%')
  })

  it('formats 0.953 as "95.3%"', () => {
    expect(formatPercent(0.953)).toBe('95.3%')
  })

  it('formats negative values', () => {
    expect(formatPercent(-0.5)).toBe('-50.0%')
  })
})
