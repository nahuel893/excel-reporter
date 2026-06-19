import type { InfoDias } from '../types'

interface InfoDiasBannerProps {
  infoDias: InfoDias
  prvtaNote?: string | null
}

/**
 * Stats banner: 3 stat tiles (Dias Habiles / Transcurridos / Faltantes).
 * When prvtaNote is present, shows an amber warning note (role="note").
 */
export function InfoDiasBanner({ infoDias, prvtaNote }: InfoDiasBannerProps) {
  const stats = [
    { label: 'Días Hábiles', value: infoDias['Dias Habiles'] },
    { label: 'Transcurridos', value: infoDias['Dias Transcurridos'] },
    { label: 'Faltantes', value: infoDias['Dias Faltantes'] },
  ]

  return (
    <div className="flex flex-wrap items-center gap-4 py-3 px-4">
      {stats.map(({ label, value }) => (
        <div
          key={label}
          className="flex flex-col items-center px-4 py-2 rounded"
          style={{
            border: '1px solid var(--paper-rule)',
            background: 'white',
            minWidth: 80,
          }}
        >
          <span
            className="numeric"
            style={{ fontSize: '1.4rem', fontWeight: 600, color: 'var(--header-navy)' }}
          >
            {value}
          </span>
          <span
            style={{ fontSize: '0.7rem', color: 'var(--ink-soft)', whiteSpace: 'nowrap' }}
          >
            {label}
          </span>
        </div>
      ))}

      {prvtaNote && (
        <div
          role="note"
          aria-label="Advertencia: exclusión de preventista"
          className="flex items-center gap-2 px-3 py-2 rounded text-sm"
          style={{
            background: '#FEF3C7',
            border: '1px solid #FDE68A',
            color: '#92400E',
            fontFamily: "'Fraunces', Georgia, serif",
          }}
        >
          <span aria-hidden="true">⚠</span>
          <span>{prvtaNote}</span>
        </div>
      )}
    </div>
  )
}
