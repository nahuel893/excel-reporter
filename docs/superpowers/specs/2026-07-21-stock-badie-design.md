# Stock Badie — Design Spec

**Date:** 2026-07-21
**Author:** pairing session (Nahuel + Claude)
**Status:** DRAFT — awaiting user review
**Reference workbook:** `/home/nahuel/VM shared/Copia de Stock Badie.xlsm` (sheet `STOCK`, "Vista 1")

---

## 1. Goal & scope

Automate the manual "Stock Badie" reposición/alcance workbook. Today a human pastes
physical stock + monthly sales into an `.xlsm` and Excel formulas compute suggested
orders and days-of-coverage per article per sucursal. This service generates the same
report **sourced from the DB**, output as `.xlsx`.

**Phase 1 (this spec):** the `STOCK` sheet only (14 sucursales, wide layout).
**Phase 2 (deferred):** proveedor sheets (BODEGAS / FRATELLI / FECOVITA / ADO) and their
category pivots — they depend on category master tables that live only inside the xlsm today.

**Non-goals:** no VBA/macros (drop `.xlsm` → `.xlsx`), no slicers required, no dependency on
`gold.mv_stock_quiebre`.

---

## 2. Data source (DIRECT — no materialized view)

Decision (user): do **not** couple to `gold.mv_stock_quiebre`. Pull raw facts and do the
transforms in Python. The MV stays only as a *reference* that the math below is correct.

### 2.1 Stock (existencia) — `gold.fact_stock`
- Latest snapshot: `date_stock = (SELECT MAX(date_stock) FROM gold.fact_stock)`.
- Roll deposito → sucursal via `gold.dim_deposito.id_sucursal` (fact_stock has `id_deposito`, NOT `id_sucursal`).
- Measures: `SUM(cant_bultos)`, `SUM(cantidad_total_htls)` grouped by `(id_sucursal, id_articulo)`.
- Reuse/extend `DataLoader.get_stock_diario(fecha)` (already returns per-articulo-per-sucursal stock).

### 2.2 Venta del mes — `gold.fact_ventas`
- Current calendar month: `fecha_comprobante >= date_trunc('month', CURRENT_DATE)` and `< next month`.
- Measures: `SUM(cantidades_total)` (bultos), `SUM(cantidad_total_htls)` grouped by `(id_sucursal, id_articulo)`.
- New `DataLoader` method: `get_venta_mes(fecha_desde, fecha_hasta) -> DataFrame` returning
  `id_sucursal, sucursal (descripcion), id_articulo, venta_bultos, venta_htls`.

### 2.3 Working days (días hábiles) — computed in Python
- `DiasVenta` = business days from the 1st of the month through `CURRENT_DATE` inclusive,
  excluding **Sundays** and **FERIADOS** (`config/settings.py::FERIADOS`). Reuse
  `src/core/base_processor.py` helpers (`calcular_dias_habiles` / `calcular_info_dias`).
  Mirrors the xlsm `NETWORKDAYS.INTL(..., 11, FERIADOS)` (weekmask 11 = Sunday-only weekend;
  Saturdays count).

### 2.4 Universe (which rows appear)
Per `(sucursal, articulo)`: keep the pair if it has **stock today (stock ≠ 0) OR sales this
month**. Implement as LEFT JOIN of venta_mes onto stock_hoy, kept when `stock ≠ 0 OR sale exists`;
`venta` is `COALESCE`d to 0. (Same locked decision the MV encodes.)
- stock>0 & sales → colored by Stock-vs-Pedido (see §6)
- stock=0 & sales → hard quiebre (row exists because fact_stock emits zero rows)
- stock>0 & no sales → dormant stock, shown, pedido 0
- stock=0 & no sales → excluded (the ~91% zero noise)

### 2.5 Wide pivot
Pivot the long `(sucursal, articulo)` set into **one row per articulo**, sucursales as column
blocks. Missing `(articulo, sucursal)` cells → Stock 0 / Venta 0.

---

## 3. Exact column map (faithful to xlsm `STOCK`)

Sucursal **column order** is preserved exactly from the xlsm. Headers use the **raw DB
`descripcion`** (no `"id - "` prefix — user decision).

### 3.1 Identity columns
| Target col | Header | Source | Note |
|---|---|---|---|
| A | `idArticulo` | `id_articulo` | General |
| B | `dsArticulo` | `des_articulo` | width ~50 |
| C | `GENERICO` | `generico` | |
| D | `MARCA` | `marca` | **MOVED** — xlsm has MARCA at col BE (mid-last-block, a builder artifact). Grouped next to GENERICO here. *Flagged for confirmation.* |

### 3.2 Per-sucursal blocks (14 blocks × 4 cols) — exact order
Order (as in xlsm): CASA CENTRAL, LIBERTADOR, MAIMARA, HUMAHUACA, ABRA PAMPA, LA QUIACA,
SAN PEDRO, GUEMES, CAFAYATE, JOAQUIN V GONZALEZ, METAN, ORAN, TARTAGAL, PERICO.

Each block = 4 columns:
| Sub-col | Header | Content |
|---|---|---|
| 1 | `<descripcion>` | **Stock** (value from DB) |
| 2 | `VENTA` | **Venta del mes** (value from DB) |
| 3 | `PEDIDO` | live formula (see §5) |
| 4 | `ALCANCE` | live formula (see §5) |

### 3.3 Total block (4 cols, after the 14 blocks)
| Header | Content |
|---|---|
| `Total` | Stock total = SUM of the 14 stock cells (formula) |
| `VENTA TOTAL` | SUM of the 14 venta cells (formula) |
| `PEDIDO TOTAL` | SUM of the 14 pedido cells (formula) |
| `ALCANCE TOTAL` | **corrected** = StockTotal / (VentaTotal/DiasVenta), see §5.4 |

Total sheet width: A..BL (4 identity + 56 sucursal + 4 total = 64 columns).
Dropped vs xlsm: `bod` (BM, VLOOKUP to cat_bodegas — proveedor/phase-2) and `Columna1` (BN, empty).

---

## 4. Sheet layout (top to bottom)

```
Row 1:  DiasStock: [15]  (editable, bold)      Fecha stock: dd/mm/yyyy   Fecha venta: dd/mm/yyyy
Row 2:  DiasVenta: [NN]  (computed value)
Row 3:  (blank)
Rows 4..(4+G): TOTALES POR GENERICO band — one row per generico, spanning the wide columns,
               SUMIFS/formulas over the article table (see §5.3). *Shape flagged for confirmation.*
Row H:  (blank)
Row H+1: TABLE HEADER (idArticulo | dsArticulo | GENERICO | MARCA | <blocks...> | Total block)
Rows ...: one row per articulo (Stock & Venta values; Pedido & Alcance formulas)
Last row: TOTAL GENERAL (styled, table totals row where possible — see §5.4)
```
- Excel Table `Stock` over the article rows, style **TableStyleMedium8**.
- Freeze panes so identity columns + header stay visible when scrolling.
- Gridlines off.

---

## 5. Formulas (HYBRID: DB values + live Excel formulas)

Param cells (absolute refs): `$DiasStock$` (editable, default 15), `$DiasVenta$` (computed value).

### 5.1 Per article, per sucursal
- `Stock` = value (DB). `Venta` = value (DB, monthly total).
- `PEDIDO` = `=MAX((Venta/$DiasVenta$)*$DiasStock$ - Stock, 0)`
  (xlsm parity: `IFERROR(IF((V/DV)*DS - S > 0, (V/DV)*DS - S, 0), "")`; we floor at 0 with MAX.)
- `ALCANCE` = `=IFERROR(Stock/(Venta/$DiasVenta$), 0)`

Changing `DiasStock` (15→20) live-recomputes every PEDIDO and every ALCANCE — the one interactive knob.

### 5.2 Total block (per article row)
- `Total` = `=SUM(<14 stock cells>)`  · `VENTA TOTAL` = `=SUM(<14 venta cells>)`  · `PEDIDO TOTAL` = `=SUM(<14 pedido cells>)`

### 5.3 Top per-generico band (formulas)
One row per generico. For each sucursal block and the total block:
- StockGen = `=SUMIFS(<stock col>, <GENERICO col>, <this generico>)`
- VentaGen = `=SUMIFS(<venta col>, <GENERICO col>, <this generico>)`
- PedidoGen = `=SUMIFS(<pedido col>, <GENERICO col>, <this generico>)`
- AlcanceGen = `=IFERROR(StockGen/(VentaGen/$DiasVenta$), 0)`  (computed from the summed cells, NOT a SUM of alcances)

### 5.4 Corrected ALCANCE totals (user-approved)
The old xlsm computes `ALCANCE TOTAL` as the **sum of per-sucursal alcances** — mathematically
wrong (sum of ratios ≠ ratio of sums). Everywhere a total/subtotal alcance appears (per-article
Total block, per-generico band, TOTAL GENERAL row) we compute:
`ALCANCE = StockSum / (VentaSum / DiasVenta)`. Totals will differ from the legacy xlsm — on purpose.

### 5.5 TOTAL GENERAL row (bottom)
- Stock/Venta/Pedido per column = SUM over all article rows (Excel Table totals row where feasible).
- Alcance cells = corrected ratio per §5.4.
- Styled distinctly (bold + fill) — satisfies the project "totals row in every report" rule.

No `ROUND`/`int()`/`astype(int)` anywhere. Precision kept in values/formulas; only `number_format` controls display.

---

## 6. Formatting (extracted from xlsm)

- **Numeric format** (Stock/Venta/Pedido/Alcance + all totals): `_-* #,##0_-;\-* #,##0_-;_-* "-"??_-;_-@_-`
  (accounting, 0 decimals, dash on zero).
- Identity A/C/D + MARCA: `General`. `dsArticulo` width ~50; `GENERICO` width ~18; stock cols ~16–21; venta cols ~11.
- Header row: fill + bold on VENTA/PEDIDO/ALCANCE headers (approximated via table style).
- **Conditional formatting (the real "semáforo"):** ⚠️ the xlsm does NOT do a 3-band alcance
  semaphore. Each **Stock cell** is colored vs its **Pedido**:
  `Stock < Pedido` → RED (understocked / quiebre risk), `Stock > Pedido` → GREEN.
  Faithful replication = Stock-vs-Pedido rule. *Flagged: confirm this vs a 3-band alcance
  semaphore (ROJO<15 / AMARILLO 15–30 / VERDE>30).*

---

## 7. Delivery (daily email)

Wire into the existing daily pipeline (`docs/flujo-envio-informes.md`):
- Register a handler in `main.py::REPORT_HANDLERS` and add the service to `scripts/run_daily.py::SERVICIOS`.
- `configs/stock_badie.json`: `enviar_a` / `cc` = `mbravo`, `fgallardo`, `sdellamea`, `gfarah`
  (names resolved to addresses by `src/config/resolver.py::resolve_delivery` via `configs/contactos.json`).
- Pipeline: `CaptureImageStep` (xlsx→PNG) + `SendEmailStep` (To+Cc, xlsx attached) + optional WhatsApp.
- ⚠️ *Flagged:* confirm `mbravo/fgallardo/sdellamea/gfarah` exist in `configs/contactos.json`
  (add them if missing — need real addresses; won't fabricate).

---

## 8. Code structure

```
src/services/stock_badie/
  config.py     # StockBadieConfig (dias_stock=15, genericos?, nombre_archivo?, db_name?)
  processor.py  # build DataFrame(s): stock+venta pivot, universe, dias habiles; build_excel(...)
  service.py    # StockBadieService(BaseService), SERVICE_SLUG="stock-badie", GRANULARITY="day"
src/core/data_loader.py   # + get_venta_mes(...); reuse get_stock_diario(...)
main.py                    # subcommand `stock-badie` + REPORT_HANDLERS entry
configs/stock_badie.json   # prod config + delivery
data/output/stock-badie/{YYYY-MM}/   # output (+ sibling PNG)
```
Patterns: Service Layer + BaseService (Template Method), DataLoader injectable (Repository), no rounding.

---

## 9. Testing (STRICT TDD — active)

Tests first, mock the DataLoader (unit tests never hit the DB; mock `ExcelWriter`, not `generar_excel`):
- `get_venta_mes` SQL shape + composite-safe joins (roll deposito→sucursal; month window).
- Universe rule (stock≠0 OR sales; dormant vs quiebre vs excluded).
- Wide pivot correctness (missing cells → 0; sucursal order preserved).
- Días hábiles = Sundays + FERIADOS excluded.
- Formula strings emitted for PEDIDO/ALCANCE reference `$DiasStock$`/`$DiasVenta$`; corrected alcance totals.
- Number format + conditional formatting rule present.
- No rounding anywhere.

---

## 10. Open items to confirm (review gate)

1. **MARCA position** — grouped at col D (vs faithful BE)? (§3.1)
2. **Semáforo** — faithful Stock-vs-Pedido coloring, or the 3-band alcance version? (§6)
3. **Top per-generico band shape** — per-generico rows spanning the wide sucursal columns (proposed), or a compact `Generico | Stock | Venta | Pedido | Alcance` summary table? (§5.3)
4. **Delivery contacts** — confirm `mbravo/fgallardo/sdellamea/gfarah` map to real addresses in `configs/contactos.json`. (§7)
5. **Bottom totals as native table totals row** acceptable, with Alcance overridden by the corrected ratio? (§5.5)
```
