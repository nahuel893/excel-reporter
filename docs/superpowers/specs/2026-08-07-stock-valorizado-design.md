# Stock Valorizado — Design Spec

**Date:** 2026-08-07
**Author:** pairing session (Nahuel + Claude)
**Status:** APPROVED — universe policy confirmed by user
**Reference price list:** `~/Downloads/export.xlsx` (ERP export, 2307 articles)

---

## 1. Goal & scope

Produce a per-article, per-sucursal stock report where every sucursal contributes **two**
columns — bultos and their monetary valuation — plus a grand total of both. Valuation is
`cant_bultos * Precio Base`, where `Precio Base` comes from an external ERP price-list
export (there is no price column anywhere in `gold`).

The report answers one question the existing stock reports do not: **how much capital is
immobilized, and where**.

**Non-goals:** no days-of-coverage / reposición math (that is `stock-badie`), no slicers,
no dependency on `gold.mv_stock_quiebre`.

---

## 2. Data sources

| Source | What it gives | Notes |
|---|---|---|
| `DataLoader.get_ultima_fecha_stock()` | Latest `date_stock` in `gold.fact_stock` | Default snapshot date |
| `DataLoader.get_stock_diario(fecha)` | `id_articulo, generico, marca, des_articulo, sucursal, cant_bultos, cant_htls` | Already grouped by article + sucursal |
| `data/input/lista_precios.xlsx` | `Artículo` (= `id_articulo`), `Precio Base`, `Precio Final` | ERP export, replaced by hand when prices change |

Verified on the 2026-08-07 snapshot: **2307 articles in stock, 2307 in the price list,
100% match, zero orphans on either side.** The export is the full article master.

### `Precio Base` is per bulto

Confirmed arithmetically across the file: `Precio Final / Presentación = Unit. Final`, so
`Precio Base` (like `Precio Final`) is quoted per bulto, net of internal taxes and
bonificación. It multiplies directly against `cant_bultos` with no unit conversion.

### Price-list lifecycle

The file lives at `data/input/lista_precios.xlsx`, next to the other hand-supplied inputs
this project already depends on (`descuentos_clientes.xlsx`, the SURIA copy, the Branca
relevamiento). Like all of them it is **not versioned** — `data/` is blanket-ignored, and
adding an exception just for this one would break a convention the repo applies uniformly.
Untracked files survive branch checkouts, so the daily's `git checkout main` does not
disturb it; a `git clean -x` would. The config points at it via `lista_precios_path`, so a
different path can be supplied without touching code.

The service logs the file's mtime and writes it into the workbook header, so a stale price
list is visible on the sheet rather than silently producing stale money. Loading is strict:
a missing file, a missing `Artículo`/`Precio Base`/`Precio Final` column, or a duplicated `Artículo` raises
rather than degrading to a half-priced report.

A `gold` price table would remove the manual step entirely; that is deferred to the ETL
session and is not a blocker for this service.

---

## 3. Universe policy

Confirmed with the user, case by case. This is the part that determines whether the totals
mean anything.

| Case | Volume on 2026-08-07 | Decision |
|---|---|---|
| Non-sellable genéricos (`ENVASES CCU`, `ENVASES GASEOSAS`, `ENVASES PALAU`, `EQUIPOS DE FRIO`, `MARKETING`, `MARKETING BRANCA`, `DISPENSER`) | 875.587 bultos | **Excluded.** Configurable via `genericos_excluidos`; default matches `stock-badie` |
| `generico IS NULL` (esqueletos, troqueles, vasos promo, bolsas) | 164 articles, 139.610 bultos | **Kept.** Shown as `SIN CLASIFICAR` |
| `Precio Base = 0` with real stock | 42 articles | **Kept** with real bultos and $0 valuation; flagged in `Control` |
| Negative stock | 9 rows, −$978.621,47 | **Kept**, valuation stays negative |
| Zero-stock rows | 27.072 rows | **Kept.** The sheet is a full catalog view |

Net effect: **2121 articles × 14 sucursales = 29.694 rows, 575.708 bultos,
$10.978.314.853,29.** Only the excluded-genérico list removes anything, and the `Control`
sheet states what was removed.

`SIN CLASIFICAR` articles carry 139.610 bultos at $0, which drags the report's
bultos-to-money ratio down. That is the user's explicit call — the bultos are physically
real — and `Control` makes the distortion measurable rather than invisible.

---

## 4. Module layout

Mirrors `src/services/stock_badie/`, the closest existing sibling (same wide
pivot-by-sucursal shape, same raw-openpyxl workbook construction).

```
src/services/stock_valorizado/
├── __init__.py     # re-exports Config / Service
├── config.py       # StockValorizadoConfig
├── precios.py      # cargar_lista_precios(path) -> DataFrame[id_articulo, precio_base, precio_final]
├── processor.py    # build_universe, pivot_wide, analytics frames
├── workbook.py     # build_workbook(...) -> openpyxl Workbook
└── service.py      # StockValorizadoService(BaseService)
```

Supporting changes:

- `configs/stock_valorizado.json` — report definition and delivery targets
- `main.py` — `_run_stock_valorizado_report` handler + dispatch registration
- `src/config/models.py` / `src/config/resolver.py` — `lista_precios_path` + `fecha_stock` filters

### Service contract

```python
@dataclass
class StockValorizadoConfig:
    lista_precios_path: str
    fecha_stock: str | None = None          # default: get_ultima_fecha_stock()
    genericos_excluidos: list[str] | None = None   # default: NO_VENDIBLES
    nombre_archivo: str | None = None
    db_name: str | None = None
```

`SERVICE_SLUG = "stock-valorizado"`, `GRANULARITY = "day"` → output lands in
`data/output/stock-valorizado/{YYYY-MM-DD}/`.

Raises `ValueError` when `gold.fact_stock` has no snapshot at all, matching
`StockBadieService`'s behaviour — never emit a bogus empty report.

---

## 5. Sheets

### 5.1 `Stock Valorizado` (primary)

```
Artículo | Descripción | Genérico | Marca | ⟨Sucursal: Bultos | $⟩ × 14 | Total Bultos | Total Valorizado
```

- Sucursales in a stable alphabetical order, `CASA CENTRAL` first.
- Each sucursal is a collapsible two-column group.
- Sorted by `Total Valorizado` descending — the capital leads.

**Totals follow the filter.** The `TOTAL GENERAL` row at the bottom uses
`SUBTOTAL(9, <col>6:<col><last>)`, not `SUM`: on a 2000-row grid the point of the
autofilter is to answer "how much is *this* slice worth", and `SUM` would keep
reporting the whole sheet. Function 9 rather than 109 tracks the autofilter only —
a row hidden by hand keeps counting, so nobody silently moves a total by dragging
a row border.

Row 3, inside the frozen pane, mirrors that row as `TOTAL VISIBLE`: each cell is a
plain reference (`=E2127`) to its SUBTOTAL counterpart, so the filtered figures stay
on screen without scrolling to the bottom, and there is exactly one formula to get
right. Ranges are derived from the real row count, so they track the table length.

The autofilter range deliberately stops one row short of `TOTAL GENERAL`. Inside the
range, SUBTOTAL would count itself and the filter would treat the total as another
article row.

### 5.2 `Stock Valorizado Final`

Identical grid, valued at `Precio Final` instead of `Precio Base`. Verified on all
2307 rows of the 2026-08 export: `Precio Final = Precio Base * 1.21 + Imp. Internos`
(VAT plus internal taxes; `Bonificación (%)` is zero throughout the file, so it never
participates).

The two sheets share bultos exactly and differ only in money — total $10.978.314.853
at base against $14.571.460.616 at final, a 1,3273 ratio (above 1,21 because internal
taxes are not proportional). Note that 15 articles carry a zero base and a non-zero
final, so they are invisible on the base sheet and valued on this one.

The analytics sheets stay on `Precio Base`: they answer "where is the capital", and
mixing two price bases into one ABC ranking would make it unreadable.

### 5.3 `Resumen Sucursal`

Bultos, valorizado, % of total capital, article count with stock, and average value per
bulto. `TOTAL GENERAL` row.

### 5.4 `ABC Pareto`

Articles ranked by `Total Valorizado`, with running cumulative % and an A/B/C class
(A ≤ 80%, B ≤ 95%, C = rest). Answers which fraction of the catalog holds the capital.

### 5.5 `Generico x Sucursal`

Valuation matrix, genérico × sucursal, with data bars. Row and column totals.

### 5.6 `Control`

Diagnostics, so nothing is invisible:

- Articles with `Precio Base = 0` and non-zero stock (bultos at risk of under-valuation)
- Rows with negative stock
- `SIN CLASIFICAR` totals
- Summary of what `genericos_excluidos` removed (bultos left out, per genérico)
- Price-list file path and mtime

---

## 6. Numeric handling

No `round()`, no `int()`, no `astype(int)` anywhere in the pipeline. Values reach the sheet
at full float precision; presentation is entirely `number_format` (`#,##0` for bultos,
`$ #,##0` for money — no decimals by request, a formatting choice that never touches
the stored value). Money columns are a fixed 14,5 wide so the two valuation sheets
line up. This is a standing project rule.

Merges are `how="left"` from stock onto prices, keyed on `id_articulo` alone — the price
list is a global article master with no sucursal dimension, so the composite-key rule
`(id, id_sucursal)` does not apply here. `cant_bultos` and `sucursal` already come
pre-grouped from `get_stock_diario`, so no fan-out is possible.

---

## 7. Testing

TDD, `tests/test_stock_valorizado.py`, `DataLoader` mocked. Coverage:

- **`cargar_lista_precios`**: happy path; missing file; missing required column; duplicated
  `Artículo`; non-numeric price.
- **Universe policy**: one test per row of the §3 table — excluded genéricos vanish, NULL
  genérico survives as `SIN CLASIFICAR`, zero-price rows survive at $0, negative stock keeps
  its negative valuation, zero rows survive.
- **Valuation**: `valor == cant_bultos * precio_base` at float precision, negatives included.
- **Pivot**: every sucursal yields exactly two columns; an article missing from a sucursal
  reads 0, not NaN.
- **Totals**: `TOTAL GENERAL` equals the column sums, and per-row `Total Valorizado` equals
  the sum of that row's sucursal money columns.
- **Filter-aware totals**: the bottom row emits `SUBTOTAL(9,...)` and never `SUM`; row 3
  mirrors it by reference; both ranges follow the actual table length; the autofilter
  range excludes the total row.
- **Service**: raises `ValueError` when no stock snapshot exists.
- **Precio Final**: a price list missing the column fails hard; `valorizado_final`
  equals bultos x final price; a zero-base/non-zero-final article is valued only on
  the final sheet; both pivots report identical bultos.
- **Workbook**: six sheets in order; money cells carry `$ #,##0` at width 14,5; the
  per-sucursal blocks keep `outline_level == 1` without losing their widths.

---

## 8. Deferred

- `gold` price table (removes the manual export step) — hand the spec to the ETL session.
- Daily scheduling via `scripts/run_daily.py` — the service ships runnable on demand first.
