import { useState } from 'react'
import { useDatos } from './api/useDatos'
import { PeriodSelector } from './components/PeriodSelector'
import { GenericoTabs } from './components/GenericoTabs'
import { ReportTable } from './components/ReportTable'
import { InfoDiasBanner } from './components/InfoDiasBanner'

// Default to the first day of the current month through today
function getDefaultDesde(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
}

function getDefaultHasta(): string {
  const now = new Date()
  return now.toISOString().slice(0, 10)
}

export function App() {
  const [selectedTab, setSelectedTab] = useState(0)
  const { mutate, data, isPending, isError, error } = useDatos()

  function handlePeriodSubmit(desde: string, hasta: string) {
    setSelectedTab(0)
    mutate({ fecha_desde: desde, fecha_hasta: hasta, con_objetivo: true })
  }

  const activeSheet = data?.sheets[selectedTab]
  const activeNote = activeSheet?.note ?? null

  return (
    <div className="min-h-screen" style={{ background: 'var(--paper)' }}>
      {/* Skip link target */}
      <main id="main-content">
        {/* ── Page header ────────────────────────────────────── */}
        <header
          className="px-4 pt-6 pb-2 border-b"
          style={{ borderColor: 'var(--paper-rule)' }}
        >
          <h1
            style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: '1.5rem',
              fontWeight: 700,
              color: 'var(--header-navy)',
              letterSpacing: '-0.01em',
              margin: 0,
            }}
          >
            Resumen Mensual
          </h1>
          <p style={{ fontSize: '0.78rem', color: 'var(--ink-soft)', marginTop: 2 }}>
            Vista en vivo — Distribuidora Badie
          </p>
        </header>

        {/* ── Period selector ────────────────────────────────── */}
        <section aria-label="Período de consulta">
          <PeriodSelector
            initialDesde={getDefaultDesde()}
            initialHasta={getDefaultHasta()}
            onSubmit={handlePeriodSubmit}
            isPending={isPending}
          />
        </section>

        {/* ── Info días banner + PRVTA note ──────────────────── */}
        {data && (
          <section aria-label="Días del período">
            <InfoDiasBanner
              infoDias={data.meta.info_dias}
              prvtaNote={activeNote}
            />
          </section>
        )}

        {/* ── Loading state ──────────────────────────────────── */}
        {isPending && (
          <div
            role="status"
            aria-live="polite"
            className="flex items-center justify-center py-16"
            style={{ color: 'var(--ink-soft)' }}
          >
            <span aria-hidden="true" className="mr-2" style={{ fontSize: '1.2rem' }}>
              ⟳
            </span>
            <span style={{ fontFamily: "'Fraunces', serif", fontSize: '0.9rem' }}>
              Cargando datos…
            </span>
          </div>
        )}

        {/* ── Error state ────────────────────────────────────── */}
        {isError && (
          <div
            role="alert"
            aria-live="assertive"
            className="mx-4 my-4 p-4 rounded border"
            style={{
              background: '#FEF2F2',
              borderColor: '#FECACA',
              color: '#991B1B',
              fontFamily: "'Fraunces', serif",
            }}
          >
            <strong>Error al cargar los datos.</strong>{' '}
            {error?.message ?? 'Por favor intentá de nuevo.'}
            <button
              onClick={() => mutate({ fecha_desde: getDefaultDesde(), fecha_hasta: getDefaultHasta() })}
              style={{
                marginLeft: 12,
                color: '#1F4E78',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                textDecoration: 'underline',
                fontFamily: 'inherit',
              }}
            >
              Reintentar
            </button>
          </div>
        )}

        {/* ── Empty state ────────────────────────────────────── */}
        {data && data.sheets.length === 0 && (
          <div
            className="flex items-center justify-center py-16"
            style={{ color: 'var(--ink-soft)', fontFamily: "'Fraunces', serif" }}
          >
            No hay datos para el período seleccionado.
          </div>
        )}

        {/* ── Genérico tabs + Report table ──────────────────── */}
        {data && data.sheets.length > 0 && (
          <>
            <GenericoTabs
              sheets={data.sheets}
              selectedIndex={selectedTab}
              onSelect={setSelectedTab}
            />

            {data.sheets.map((sheet, i) => (
              <div
                key={sheet.generico}
                id={`tabpanel-${i}`}
                role="tabpanel"
                aria-labelledby={`tab-${i}`}
                hidden={i !== selectedTab}
                className="animate-fade-up"
                style={{ animationDelay: `${i * 60}ms` }}
              >
                <ReportTable sheet={sheet} meta={data.meta} />
              </div>
            ))}
          </>
        )}

        {/* ── Initial prompt (no data fetched yet) ──────────── */}
        {!data && !isPending && !isError && (
          <div
            className="flex flex-col items-center justify-center py-20"
            style={{ color: 'var(--ink-soft)' }}
          >
            <span
              style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: '1.1rem',
                fontWeight: 300,
                fontStyle: 'italic',
                color: 'var(--ink-soft)',
              }}
            >
              Seleccioná el período y presioná Actualizar
            </span>
          </div>
        )}
      </main>
    </div>
  )
}
