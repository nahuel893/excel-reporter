import { useRef } from 'react'
import type { Sheet } from '../types'

interface GenericoTabsProps {
  sheets: Sheet[]
  selectedIndex: number
  onSelect: (index: number) => void
}

/**
 * ARIA tabs pattern — keyboard-navigable genérico selector.
 *
 * Implements the WAI-ARIA Authoring Practices tablist pattern:
 * - role="tablist" on the container
 * - role="tab" on each button
 * - aria-selected / roving tabindex
 * - Arrow key navigation (Left/Right)
 * - Sticky positioning below the page header
 */
export function GenericoTabs({ sheets, selectedIndex, onSelect }: GenericoTabsProps) {
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])

  function handleKeyDown(e: React.KeyboardEvent, index: number) {
    let next = index
    if (e.key === 'ArrowRight') {
      next = (index + 1) % sheets.length
    } else if (e.key === 'ArrowLeft') {
      next = (index - 1 + sheets.length) % sheets.length
    } else if (e.key === 'Home') {
      next = 0
    } else if (e.key === 'End') {
      next = sheets.length - 1
    } else {
      return
    }
    e.preventDefault()
    onSelect(next)
    tabRefs.current[next]?.focus()
  }

  return (
    <nav
      aria-label="Genéricos"
      className="sticky top-0 z-20 border-b"
      style={{
        backgroundColor: 'var(--paper)',
        borderColor: 'var(--paper-rule)',
        height: 'var(--tab-height)',
      }}
    >
      <div
        role="tablist"
        aria-label="Seleccionar genérico"
        className="flex items-end h-full px-4 gap-1 overflow-x-auto"
      >
        {sheets.map((sheet, i) => {
          const selected = i === selectedIndex
          return (
            <button
              key={sheet.generico}
              role="tab"
              ref={(el) => { tabRefs.current[i] = el }}
              id={`tab-${i}`}
              aria-selected={selected}
              aria-controls={`tabpanel-${i}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onSelect(i)}
              onKeyDown={(e) => handleKeyDown(e, i)}
              className="px-4 py-2 text-sm font-display whitespace-nowrap transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1"
              style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontWeight: selected ? 600 : 400,
                color: selected ? 'var(--ink)' : 'var(--ink-soft)',
                borderBottom: selected
                  ? '3px solid var(--header-navy)'
                  : '3px solid transparent',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                minHeight: '44px',
                minWidth: '44px',
              }}
            >
              {sheet.generico}
              {sheet.sin_prvta && (
                <span
                  aria-label="excluye preventista"
                  style={{ marginLeft: 4, fontSize: '0.65rem', color: '#D97706' }}
                >
                  ⚠
                </span>
              )}
            </button>
          )
        })}
      </div>
    </nav>
  )
}
