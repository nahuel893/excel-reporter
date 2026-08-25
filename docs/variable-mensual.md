# Variable Mensual (INCENTIVO HERNAN)

Reload of the base data behind the monthly 4% incentive workbook. The workbook is
**not** generated from scratch: `ramal`, `qbrd`, `inte`, `salta`, `ORIGINAL` and
`suc` are Nahuel's, full of hand-tuned objectives, weights and formulas. Python
only replaces what sits underneath them.

```bash
python main.py variable-mensual \
  --archivo 'data/output/variable_mensual/INCENTIVO HERNAN 2025.xlsm' \
  --desde 2026-07-01 --hasta 2026-07-31
```

~10 seconds. Writes in place, leaving `INCENTIVO HERNAN 2025.<fecha>.bak.xlsm`
next to it (`--sin-backup` to skip, `--salida` to write elsewhere).

## What the tab colours mean

The workbook encodes its own contract in the tab colours, and that is what the
service follows:

| Colour | Sheets | Meaning |
|---|---|---|
| **Blue** | `AX`, `cober_marca`, `cober_gen`, `villav y villa sur`, `cober_colon_dulce`, `referencia ma`, `art_colon_dulce` | Base data. Loaded, not authored. |
| Red / yellow / plain | `ramal`, `qbrd`, `inte`, `salta`, `ORIGINAL`, `marcas_x_pdv`, `suc` | Report and calculation sheets. Untouched. |

`marcas_x_pdv` is the exception: it is a red calculation sheet, but its input
block used to be a pivot table plus 26.000 COUNTIFS, and Python now computes it.

## What gets reloaded

| Sheet | Source | Rows (jul-2026) |
|---|---|---|
| `AX` | `fact_ventas` + `dim_articulo` + `dim_cliente` | 147.357 |
| `marcas_x_pdv` A:F, J:L, N:P | derived from `AX` | 61.614 / 11.715 |
| `cober_marca` | `cob_preventista_marca` | 5.118 |
| `cober_gen` | `cob_preventista_generico` | 800 |
| `villav y villa sur` | `fact_ventas` (union of two brands) | 243 |
| `referencia ma` | `cober_gen` + `cober_marca` + `AX` | 52 / 91 / 13 |

Not reloaded, on purpose:

- **`cober_colon_dulce`** is a pivot over `AX`. The service sets `refreshOnLoad`
  on its cache, so it re-reads the new `AX` when the workbook opens.
- **`art_colon_dulce`** is a hand-kept list of six article codes. Nothing in gold
  identifies them — the service reads them from there to build the COLON DULCE
  block of `referencia ma`.

## AX — 11 columns of 31

Only eleven columns are read by anything; the other twenty are written as empty
cells. The headers, the Excel table `aexcel` and every table-column reference
stay, so no formula breaks — the sheet just stops carrying dead payload.

| Column | Field | Who reads it |
|---|---|---|
| C | Descripcion Período | `salta!F1` = `MAX(AX!C:C)`, the last sale date |
| D | Codigo Cliente | `marcas_x_pdv`, `cober_colon_dulce` |
| F | Sucursal | SUMIFS criteria across the report sheets |
| M | Código_Articulo | feeds the COLON DULCE lookup in AE |
| P | Descripcion_Marca | `marcas_x_pdv` |
| T | Cantidades Totales | wholesale-share numerator and denominator |
| V | Descripcion lista de precios | wholesale-share criteria |
| W | GENERICO | the most referenced column in the workbook |
| AC | Cantidad htls | volume, in hectolitres |
| AD | zona | `=VLOOKUP(...,suc!Q:R,2,0)` — kept as a formula |
| AE | COLON DULCE | `=VLOOKUP(...,art_colon_dulce!A:C,3,0)` — kept as a formula |

Blanked: `A B E G H I J K L N O Q R S U X Y Z AA AB`.

The `aexcel` table `ref` and `autoFilter` are moved to the new last row on every
run. **That is what stretches AD and AE to the foot of the data** — Excel fills a
table's formula columns for every row inside `ref`, so a stale `ref` would leave
the tail without a zone.

### Row grain

One row per `(fecha, cliente, sucursal, articulo, lista de precios)`. The old
manual export split rows further by unit price, giving ~10% more rows for the
same totals. Nothing downstream reads price — every consumer is a SUMIFS or a
pivot — so the coarser grain is deliberate.

### The price list is pinned in code

`gold.dim_lista_precio` is empty and `dim_cliente.des_lista_precio` is blank for
all 28.392 clients, so gold cannot name a price list. `LISTAS_DE_PRECIO` in
`constants.py` maps the id to the name; the mapping was recovered by
cross-referencing the workbook's own AX export against
`dim_cliente.id_lista_precio`, and every id resolved to exactly one name. If a
new list appears, add it there — an unknown id is left blank rather than guessed,
because a wrong label silently moves the wholesale share.

## marcas_x_pdv — how the brand count works

The goal: **how many brands of CERVEZAS, AGUAS DANONE and VINOS CCU each point of
sale bought.**

| Range | Was | Is now |
|---|---|---|
| A3:F | `pivotTable1` over `aexcel` | values, grouped in pandas |
| J3:L | pivot column copied and deduplicated by hand | values |
| N3:P | `=COUNTIFS($A:$A,$J3,$B:$B,N$1,$F:$F,">0")` | values |
| R1:V50 | zone and branch averages | **untouched, still formulas** |

The rule the COUNTIFS encoded: group the sales by
`(cliente, generico, marca, sucursal, zona)`, sum the quantity, then count the
groups whose sum is **strictly positive**. Netting matters — a client who bought
a brand and returned all of it inside the window does not count for that brand.

`R:V` stays as live formulas because that is what `ramal`, `qbrd` and `inte`
actually read, via
`SUMIFS(marcas_x_pdv!$T:$T, $R:$R, <zona|sucursal>, $S:$S, <generico>)`.

`pivotTable1` is **removed from the package**, because a pivot and pasted values
cannot share a range: on the next refresh the pivot would overwrite the values.

### Gotcha in the R:V block

Rows 25-50 divide by `COUNTIFS($K:$K,$R12...)` — a reference into the CERVEZAS
block above, not into their own row. It is correct today only because the three
blocks list the branches in identical order. Reordering the branches in `R` breaks
the AGUAS and VINOS averages silently. Left as-is (it is Nahuel's sheet), but do
not reorder it.

## referencia ma — each branch's share of its zone

Five blocks side by side, all keyed by the same **thirteen branches in a fixed
order**. CASA CENTRAL and VALLE SALTA are absent: this sheet only feeds `ramal`,
`qbrd` and `inte`, the interior zone reports.

| Block | Rows | What it holds |
|---|---|---|
| `A:G` | 52 | coverage per branch and generic, and its share of the zone |
| `I:N` | 52 | volume **in units** per branch and generic, and its share |
| `P:V` | 91 | coverage of seven focus brands (SALTA, VILLAVICENCIO, LEVITE, O-61, Imperial, NORTE, BRIO) |
| `W:AB` | 13 | coverage of the COLON DULCE articles |
| `AD:AN` | 52 | the wholesale split of volume |

Only the percentage columns are read by anything — `ramal`, `qbrd` and `inte`
pull `G`, `N`, `U` and `AB` with SUMIFS. The rest is context.

Three ratios in `AD:AN`, and the middle one catches people out:

- `AK % mayo zona` = wholesale / total, for the zone
- `AL % participacion sucursal` = the branch's share of its zone's **wholesale**
  volume — not of its total volume
- `AM % mayo sucursal` = wholesale / total, for the branch

Wholesale means the price lists named `... MAYORISTA`. `SUB DISTRIBUIDORES` is
**not** wholesale here; the pasted values confirmed it.

Volume is in units (`cantidades_total`), not hectolitres. The pasted values
matched units to the fourth decimal and did not match hectolitres at all.

A branch with no sales keeps its row with a zero. Dropping it would shift every
row below and silently repoint the report sheets, which match by row position
inside the block.

### What the pasted values turned out to be

The sheet had never been reloaded since **May 2026** — three months stale in a
workbook being used for August. Worse, its blocks were frozen at *different*
moments: `I:N` and `AD:AN` reproduce May exactly, but column `D` (`M X PDV`)
matches no month under any criterion (March without the positive-net filter is
the closest, at 3,0870 against the pasted 3,1089).

Rebuilding May from gold and comparing against those values:

| Block | Cells | Match |
|---|---|---|
| `I:N` volume | 312 | **312** |
| `W:AB` COLON DULCE | 78 | **78** |
| `P:V` coverage by brand | 546 | 534 — the rest is `cob_*` recomputed since |
| `A:G` coverage | 351 | 301 — every miss is column `D` |
| `AD:AN` wholesale | 520 | 406 — see below |

`AD:AN` splits cleanly: `AG` and `AH` (total volume) matched 52 of 52, and every
mismatch is in a wholesale column. That is the SCD type 1 problem again — the
price list is today's, not the one in force in May. Volume that does not depend
on the price list reproduces perfectly; volume that does, does not.

Column `D` is filled with the same average `marcas_x_pdv` computes, so the two
sheets agree. Nothing reads it.

## Zones

`suc!Q:R` maps branch to zone; `ZONA_POR_SUCURSAL` mirrors it. Four zones:

- **SALTA Y VALLE** — `1 - CASA CENTRAL`, `VALLE SALTA`
- **SALTA INTERIOR** — CAFAYATE, JOAQUIN V GONZALEZ, METAN, GUEMES
- **QUEBRADA** — PERICO, LIBERTADOR, MAIMARA, HUMAHUACA, ABRA PAMPA, SAN PEDRO, LA QUIACA
- **RAMAL** — ORAN, TARTAGAL

CASA CENTRAL splits into `VALLE SALTA` by the client's preventa route
(`dim_cliente.id_ruta_fv1`). Note this is **not** `ZONAS_VIRTUALES` from
`config/settings.py`: that one also carves out route 93 as SUB DISTRIBUIDORES,
and this workbook keeps route 93 inside CASA CENTRAL. If a branch is missing from
the map the service logs a warning and leaves the zone empty — the AD lookup would
show `#N/A`, which is worth seeing early.

## Coverage sheets

`cober_marca` and `cober_gen` come straight from `cob_preventista_*` filtered to
`id_fuerza_ventas = 1` (preventa). Coverage is additive across routes, so
relabelling CASA CENTRAL rows as VALLE SALTA is safe here.

`cober_gen` is filtered to the four generics. `cober_marca` **is not filtered by
generic** — a brand can belong to several generics at once (FRATELLI BRANCA lives
in FRATELLI B, BOUTIQUE, MARKETING and MARKETING BRANCA), so filtering brands by
generic would drop rows the workbook keeps. It instead drops brands that are
exclusively PERNOD RICARD, plus `SIN MARCA`.

`villav y villa sur` is the coverage of VILLAVICENCIO **and** VILLA DEL SUR as one
concept. It cannot be summed out of `cob_preventista_marca`: coverage is not
additive across brands, and a client who buys both would be counted twice. It is
totalled from `fact_ventas` instead — cut first, total the net per
`(cliente, sucursal)` inside the cut, then filter `> 0`.

## Verification (julio 2026)

The workbook was reloaded and recalculated, then compared cell by cell against
the figures it carried before. Fifteen report cells across `salta` and `inte`
recalculated to exactly the value predicted from the new data. The residual
differences against the *old* numbers, all explained:

| What | Diff | Why |
|---|---|---|
| Volume in htls, CERVEZAS / VINOS / SIDRAS | < 0,01% | — |
| Volume in htls, AGUAS DANONE | +0,88% | the workbook multiplied its own factor column; gold uses `fact_ventas.cantidad_total_htls` |
| Coverage | -0,2% to -0,4% | `cob_preventista_*` was recomputed after the manual export |
| Wholesale share, AGUAS | +2,2% | `dim_cliente` is SCD type 1 — today's price list, not the one in force at invoice time. Small base magnifies it |
| Brands per PDV | 0,00% | exact |

The htls gap on AGUAS is the "99% parity" Nahuel mentions. **This service uses
gold's number.** If the workbook's own factor is the right one, that belongs in
`dim_articulo.factor_hectolitros`, not in a spreadsheet column.

## The #REF! repair

The workbook arrived with **162 formulas showing `#REF!`** — none of them caused
by this service (the count is identical before and after). Each is a `SUMIFS`
whose ranges a past edit had deleted:

| Sheet | Broken | What had stopped working |
|---|---|---|
| `suc` | 117 | the four wholesale-mix tables — every one blank |
| `qbrd` | 21 | MIX MAY per branch |
| `inte` | 18 | MIX MAY per branch, plus 6 lookups into a vanished table |
| `ramal` | 6 | MIX MAY per branch |

The ranges are recoverable because each broken formula has a healthy sibling of
the same shape beside it. `suc!B3` maps argument for argument onto the surviving
`salta!J7` numerator, which fixes the lost ranges as quantity, branch, price list
and generic:

```
roto:  +SUMIFS(#REF!,      #REF!,       suc!$A3, #REF!,      suc!$A$1, #REF!,      suc!B$2)
sano:  +SUMIFS(AX!$T:$T,   AX!$AD:$AD,  $K$1,    AX!$V:$V,   $A7,      AX!$W:$W,   $D7)
```

The per-branch MIX MAY rows carry only two criteria and no division, which is
why they read the ready-made ratio in the wholesale block of `referencia ma`
rather than recomputing it — and why that block has an `AM` column at all.

**Verified by triangulation.** After repair, `suc!B11` and `salta!J7` both give
0,343824653859693 — the same wholesale mix reached by independent paths, one
rebuilt and one untouched. `inte!K8` and the `suc` SALTA INTERIOR table agree the
same way, at 0,1779.

156 of the 162 are repaired. The remaining 6, all in `inte`, are
`VLOOKUP(CONCATENATE(...), #REF!, ...)` into a table that no longer exists in the
workbook — there is nothing left to point them at. Repair is idempotent and runs
on every reload.

## Known gaps

- **Six `#REF!` survive in `inte`** — lookups into a table that is gone.
- **Pivot refresh needs a real spreadsheet.** `cober_colon_dulce` and `suc!K7:L171`
  refresh when the workbook is opened in Excel or WPS. LibreOffice does not
  refresh OOXML pivots, so a headless conversion leaves them stale.
- **VBA is preserved but never exercised** by this service.

## Implementation

- `src/core/xlsx_blocks.py` — block-level worksheet surgery. Edits only the target
  sheets' XML inside the zip and copies every other part byte-for-byte, so pivot
  caches, VBA, styles and drawings survive. `openpyxl` cannot round-trip this
  workbook: it parses the 74 MB pivot cache and drops the pivot tables.
- `src/services/variable_mensual/constants.py` — the workbook's layout, derived
  from tab colours, the formulas pointed at each sheet, and the pivot definitions.
- `src/services/variable_mensual/processor.py` — the marcas_x_pdv logic.
- `src/services/variable_mensual/service.py` — orchestration and workbook writing.

The reload also shrinks the file from 39,7 MB to 15,9 MB: blank columns write no
cell at all, and repeated text goes through the shared-string table instead of
being spelled out inline 150.000 times.
