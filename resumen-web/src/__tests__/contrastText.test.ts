import { describe, it, expect } from 'vitest'
import { pickTextColor, getLuminance, getContrastRatio } from '../lib/contrastText'

describe('getLuminance', () => {
  it('returns 0 for pure black', () => {
    expect(getLuminance('#000000')).toBeCloseTo(0, 4)
  })

  it('returns 1 for pure white', () => {
    expect(getLuminance('#FFFFFF')).toBeCloseTo(1, 4)
  })

  it('returns correct luminance for yellow #FFFF00', () => {
    // Yellow has high luminance
    const l = getLuminance('#FFFF00')
    expect(l).toBeGreaterThan(0.9)
  })
})

describe('getContrastRatio', () => {
  it('returns 21 for black on white', () => {
    expect(getContrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 0)
  })

  it('returns 1 for same color', () => {
    expect(getContrastRatio('#FF0000', '#FF0000')).toBeCloseTo(1, 1)
  })
})

describe('pickTextColor', () => {
  it('returns dark ink on yellow (#FFFF00) — must satisfy AA', () => {
    const text = pickTextColor('#FFFF00')
    const ratio = getContrastRatio(text, '#FFFF00')
    expect(ratio).toBeGreaterThanOrEqual(4.5)
    // Yellow is bright — must use dark text
    expect(text.toLowerCase()).not.toBe('#ffffff')
  })

  it('returns the higher-contrast option on red (#FF0000)', () => {
    // Pure red is borderline: white contrast ~4.46 vs dark ~3.34
    // The function should return whichever is higher
    const text = pickTextColor('#FF0000')
    const darkRatio = getContrastRatio('#1A1714', '#FF0000')
    const whiteRatio = getContrastRatio('#FFFFFF', '#FF0000')
    const expectedText = darkRatio >= whiteRatio ? '#1A1714' : '#FFFFFF'
    expect(text).toBe(expectedText)
  })

  it('returns white on green (#00B050)', () => {
    const text = pickTextColor('#00B050')
    const ratio = getContrastRatio(text, '#00B050')
    expect(ratio).toBeGreaterThanOrEqual(4.5)
  })

  it('returns accessible text on mid-range heatmap color', () => {
    // Orange-ish at 0.5
    const text = pickTextColor('#FF8000')
    const ratio = getContrastRatio(text, '#FF8000')
    expect(ratio).toBeGreaterThanOrEqual(4.5)
  })

  it('always returns either dark ink or white', () => {
    const colors = ['#FF0000', '#FFFF00', '#00B050', '#FF8000', '#80D728']
    for (const bg of colors) {
      const text = pickTextColor(bg)
      const isInk = text === '#1A1714' || text === '#000000'
      const isWhite = text === '#FFFFFF' || text === '#ffffff'
      expect(isInk || isWhite).toBe(true)
    }
  })
})
