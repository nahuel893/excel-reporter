import { describe, it, expect } from 'vitest'
import { getHeatmapColor } from '../lib/heatmap'

describe('getHeatmapColor', () => {
  it('returns null for null input', () => {
    expect(getHeatmapColor(null)).toBeNull()
  })

  it('returns null for undefined input', () => {
    expect(getHeatmapColor(undefined as unknown as null)).toBeNull()
  })

  it('returns null for NaN input', () => {
    expect(getHeatmapColor(NaN)).toBeNull()
  })

  it('returns #FF0000 for value = 0 (clamp red)', () => {
    expect(getHeatmapColor(0)).toBe('#FF0000')
  })

  it('returns #FF0000 for value < 0 (clamp red)', () => {
    expect(getHeatmapColor(-0.3)).toBe('#FF0000')
    expect(getHeatmapColor(-100)).toBe('#FF0000')
  })

  it('interpolates red→yellow at 0.5', () => {
    const color = getHeatmapColor(0.5)
    expect(color).not.toBeNull()
    // At 0.5: R=255, G=128 (half of 255), B=0
    expect(color).toBe('#FF8000')
  })

  it('returns #FFFF00 for value = 1.0 (yellow midpoint)', () => {
    expect(getHeatmapColor(1.0)).toBe('#FFFF00')
  })

  it('interpolates yellow→green at 1.1 (halfway in [1.0, 1.2])', () => {
    const color = getHeatmapColor(1.1)
    expect(color).not.toBeNull()
    // At 1.1: t=0.5 in yellow→green
    // R: lerp(255,0,0.5)=127 or 128 depending on rounding; G: lerp(255,176,0.5)=215; B: lerp(0,80,0.5)=40=0x28
    // Verify it is between yellow and green (not a boundary)
    const hex = color!
    const r = parseInt(hex.slice(1, 3), 16)
    const g = parseInt(hex.slice(3, 5), 16)
    const b = parseInt(hex.slice(5, 7), 16)
    // R decreasing from 255 toward 0
    expect(r).toBeGreaterThan(0)
    expect(r).toBeLessThan(255)
    // G decreasing from 255 toward 176
    expect(g).toBeGreaterThan(176)
    expect(g).toBeLessThanOrEqual(255)
    // B increasing from 0 toward 80
    expect(b).toBeGreaterThan(0)
    expect(b).toBeLessThan(80)
  })

  it('returns #00B050 for value = 1.2 (clamp green)', () => {
    expect(getHeatmapColor(1.2)).toBe('#00B050')
  })

  it('returns #00B050 for value > 1.2 (clamp green)', () => {
    expect(getHeatmapColor(2.0)).toBe('#00B050')
    expect(getHeatmapColor(100)).toBe('#00B050')
  })

  it('returns a valid hex string for any in-range value', () => {
    const hex = /^#[0-9A-F]{6}$/i
    expect(getHeatmapColor(0.25)).toMatch(hex)
    expect(getHeatmapColor(0.75)).toMatch(hex)
    expect(getHeatmapColor(1.15)).toMatch(hex)
  })
})
