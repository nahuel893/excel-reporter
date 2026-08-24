# Informes Badie — Frontend (Mgmt UI)

Single-user mgmt dashboard for the Informes Badie report system. Accessed via VPN, served by the FastAPI backend at `/app`. **This file scopes a frontend-only session — do NOT modify backend code (`../src/`, `../api.py`, `../main.py`, `../tests/`) from here.**

## Scope

- **You may touch**: anything inside `frontend/` (this directory)
- **You must NOT touch**: `../src/`, `../api.py`, `../main.py`, `../tests/`, `../configs/`, `../config/`, anything outside `frontend/`
- If a task requires backend changes, **stop and tell the user** — they'll handle it in a separate session

## Stack

- Vite 5.4 + React 18 + TypeScript 5.6 (strict)
- Tailwind 3.4 + shadcn-style CSS vars (`src/index.css`)
- TanStack Router 1.x (code-based routing, basepath `/app`)
- TanStack Query 5.x (queries + mutations in `src/lib/`)
- react-jsonschema-form 5.x (form rendering, custom widgets in `src/widgets/`)
- Monaco Editor (lazy-loaded for `categorias` field of champions-league)
- lucide-react (icons)
- sonner (toasts)
- shadcn/ui components (hand-written, in `src/components/ui/`)
- Vitest + React Testing Library

## Design direction (locked — do NOT debate)

- **Theme**: Dark-first. `<html class="dark" lang="es">`. NO theme toggle.
- **Palette**: Zinc base + Violet accent (Linear/Vercel-inspired). Use the CSS vars in `src/index.css`; do not hard-code colors in components.
- **Typography**: Inter (UI) + JetBrains Mono (code/IDs/numeric). Loaded via Google Fonts in `index.html`.
- **Icons**: lucide-react only. NO emoji icons.
- **Aesthetic**: serious dev-tool look (Linear, Vercel, Plane, GitHub). NO "purple gradient + glass morph" clichés. ~80% greys, ~15% violet accent, ~5% destructive/success.
- **Spacing**: Cards 24-32px padding, sections 32px gaps. Whitespace as a feature.
- **Motion**: 150ms transitions on hover/focus. NO flashy animations.
- **Type hierarchy**: page title 24-28px, section 16-18px, body 14px, captions 12px.

## Architecture

```
src/
├── components/           # Shared components (ConfigForm, ui/Button, ui/Card, etc.)
├── lib/
│   ├── api.ts            # Fetch wrapper + ApiError class
│   ├── queries.ts        # TanStack Query hooks (read)
│   ├── mutations.ts      # TanStack Query hooks (write)
│   ├── schema.ts         # rjsf schema → uiSchema dispatch (x-widget resolver)
│   └── utils.ts          # cn() helper
├── routes/               # TanStack Router code-based routes
│   ├── __root.tsx        # Sidebar layout
│   ├── index.tsx         # Dashboard (stub — Phase 3)
│   ├── configs.tsx       # Configs list
│   ├── configs.$filename.tsx  # Config edit form
│   ├── contactos.tsx     # contactos.json editor
│   ├── runs.tsx          # Runs list (stub — Phase 3)
│   ├── schedule.tsx      # Timer de systemd + journal (solo lectura)
│   └── artifacts.tsx     # Artifacts browser (3-level: service → period → files)
├── widgets/              # rjsf custom widgets (DateWidget, FilePathWidget, etc.)
└── test/setup.ts         # Vitest setup
```

## Backend API contract (consumed via `/api/*` proxied to `:8010`, override with `VITE_API_TARGET`)

### Implemented (use freely)

- `GET /mgmt/configs` → `[{filename, tipo, mtime}, ...]`
- `GET /mgmt/configs/{filename}` → `{content, schema}` (schema is JSON Schema with `x-widget` extensions)
- `PUT /mgmt/configs/{filename}` → 200 or 422 (Pydantic field errors)
- `GET /mgmt/configs/path-exists?p=...` → `{exists: bool}`
- `GET /mgmt/refs/sucursales` / `genericos` / `supervisores` → list of strings
- `GET /mgmt/contactos` / `PUT /mgmt/contactos` → contactos.json round-trip
- `POST /mgmt/runs` → `{run_id}` (409 if config locked)
- `GET /mgmt/runs` → paginated history
- `GET /mgmt/runs/{id}` → run detail
- `GET /mgmt/runs/{id}/log` → log file (FileResponse)
- `GET /mgmt/runs/{id}/stream` → SSE (replay-then-tail)
- `GET /mgmt/runs?status=running` → active runs (used by sidebar badge)

- `GET /mgmt/artifacts/tree?slug=&periodo=` → `{services: [{slug, unreadable, periods: [...]}], unclassified: [...]}`
- `GET /mgmt/artifacts/file?path=...` → the file (400 if the path escapes the artifacts root)

The artifacts routes live in `panel:app` (port 8010), not `api:app` — see the
"Admin Panel" section of the root AGENTS.md. A period carries both `anomalous`
(folder name outside the `YYYY-MM` / `YYYY-MM-DD` convention) and `unreadable`
(the directory could not be listed). Never render `unreadable` as an empty
period: "no files" and "could not read" mean different things to whoever is
checking whether a report actually ran.

- `GET /mgmt/schedule` → timer state, unit definition, last-run outcome
- `GET /mgmt/schedule/journal?since=&until=&limit=` → `{unit, available, error, entries: [...]}`

Both schedule endpoints are read-only and take no unit parameter — the backend
fixes which systemd unit it reports on. `available: false` means systemd could
not be read; it says nothing about whether the daily is scheduled, so never
render it as "no timer configured". Journal `priority` is syslog severity:
3 and below are failures.

### NOT yet implemented (do NOT consume — coordinate with user before assuming)

- `GET /mgmt/daily-runs/*` — daily-run instrumentation, not wired yet

### `x-widget` contract (server emits these in the schema)

| `x-widget` value          | Widget                          | Reads from                    |
|---------------------------|---------------------------------|-------------------------------|
| `date`                    | DateWidget                      | (native date input)           |
| `filepath`                | FilePathWidget                  | `/mgmt/configs/path-exists`   |
| `sucursal-select-array`   | SucursalSelectWidget            | `/mgmt/refs/sucursales`       |
| `generico-select-array`   | GenericoSelectWidget            | `/mgmt/refs/genericos`        |
| `supervisor-matrix`       | SupervisorMatrixWidget          | `/mgmt/refs/supervisores`     |
| `json-editor`             | JsonEditorWidget (Monaco)       | (raw JSON)                    |

## Pending phases

- **Phase 3** (next) — Trigger + observability UI:
  - Dashboard page (4 stat cards: latest run, next schedule, configs activos, artefactos recientes)
  - RunButton component (with `test_mode` checkbox + confirm dialog when delivery is on)
  - LogStream component (consumes SSE)
  - Run detail page (full log, status, exit code)
  - Run history list with status filter
  - Error UX (toasts on failure)
- **Phase 4** — Schedule page. **Done** (read-only view; no cron editor — the timer is edited in systemd, not here).
- **Phase 5** — Artifacts browser. **Done** — `artifacts.tsx` + `GET /mgmt/artifacts/*`.

## Engram bootstrap

Search engram at the start of any session:

```
mem_search(query: "sdd/frontend-mgmt-ui", project: "excel-reporter")
mem_search(query: "frontend/visual-polish", project: "excel-reporter")
```

Key topic keys:
- `sdd/frontend-mgmt-ui/explore` — original architecture exploration
- `sdd/frontend-mgmt-ui/proposal` — locked decisions (#672)
- `sdd/frontend-mgmt-ui/spec` — RF requirements (#673)
- `sdd/frontend-mgmt-ui/design` — technical design (#674)
- `sdd/frontend-mgmt-ui/tasks` — task breakdown with check marks (#675)
- `sdd/frontend-mgmt-ui/apply-progress` — what's done so far (#677)
- `frontend/visual-polish/index-html` — dark theme + fonts decision (#683)

Always retrieve full content via `mem_get_observation(id)` — search results are truncated.

## Commands

```bash
# Dev (with HMR)
npm run dev               # → http://localhost:5173 (Vite proxies /mgmt to :8010)

# Build for production
npm run build             # → dist/  (mounted at /app by FastAPI)

# Tests
npm test -- --run         # Vitest (must stay green)
npm run lint              # 0 errors, warnings OK

# Type check
npx tsc --noEmit
```

## Conventions

- TypeScript strict — no `any` introduced (rjsf forces some, isolate with `// eslint-disable-next-line` + reason comment)
- Imports: alias `@/` for `src/` (not relative imports past one level)
- Tests: colocate in `__tests__/` next to the component, name `Foo.test.tsx`
- Route paths use TanStack Router code-based (no file-based routing); register routes in `src/router.tsx`
- Forms: rjsf with `buildUiSchema()` from `lib/schema.ts` to dispatch x-widget extensions
- API errors: throw `ApiError` from `lib/api.ts`; Sonner toast on UI

## Out of scope

- Backend changes (FastAPI, Pydantic, services)
- New API endpoints (request user to do them in a backend session)
- Auth (VPN-only, none planned)
- Mobile-first UI (desktop-first)
- Theme switcher (dark-only)
- Plugin system / custom dashboards (not happening)

## Pre-commit checks

Before committing, run:
```bash
npm test -- --run && npm run lint && npm run build
```

If any fail, fix before commit. The `frontend/dist/` directory is gitignored — don't commit build output.
