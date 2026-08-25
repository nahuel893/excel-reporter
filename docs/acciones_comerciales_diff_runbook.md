# Acciones Comerciales — Parallel Diff Runbook (Phase 1, RF-12)

This runbook covers the **parallel-run sign-off window** (Decision 7): during
one full monthly cycle, the new Python pipeline runs alongside the legacy
manual `BASE INFOME ACCIONES WAPI.xlsm` flow, and every value difference must
be **explained or investigated** before Phase 2 (the live INFORME writer) is
enabled.

The diff harness lives in `src/services/acciones_comerciales/diff.py` and runs
as an **optional step of the Phase-1 CLI** — it never touches live files and
never fails the BASE run.

---

## 1. What the diff compares

| Side | Source |
|---|---|
| BASE (new) | The 4 pivot frames the Python pipeline just built (FACT_NET, ART-ACCION, CLIENTE-FECHA, ACC-GEN). |
| Backup (legacy) | The manual backup workbook, `backup.xlsx`, shaped like the BASE control (one sheet per pivot, header in row 1), placed under `backup_dir`. |
| aexcel (truth) | The real `aexcel.xlsx` export (still loaded by the manual flow) — used to validate the RF-01 terna→precio pick empirically (Decision 14). |

The comparison is **key-based** (each pivot's row-field tuple) and **exact to
$0.01**: a difference of a cent or less is treated as a match; anything greater
is surfaced. Underlying float values are **never rounded** (RF-23) — the
tolerance is a comparison mechanism only.

**Like-for-like period scope (RF-12).** The legacy engine table accumulates
rows across a wider window than a single BASE run. The harness filters the
backup (and base) to the configured `[fecha_desde, fecha_hasta]` window by each
row's `Fecha`, so out-of-scope accumulated rows are neither compared nor
reported as missing/extra.

---

## 2. How to run it

Add two keys to the acciones-comerciales config `filtros` block:

```jsonc
{
  "tipo": "acciones-comerciales",
  "filtros": {
    "fecha_desde": "2026-07-01",
    "fecha_hasta": "2026-07-16",
    "input_dir": "/home/nahuel/VM shared/archivos_diarios/acciones/",
    "backup_dir": "data/backups/acciones-comerciales-2026-07-16",   // enables the diff step
    "aexcel_path": "/home/nahuel/VM shared/archivos_diarios/acciones/aexcel.xlsx"
  },
  "reportes": [{ "nombre": "BASE control Acciones Comerciales - {MES} {AÑO}" }]
}
```

```bash
python main.py acciones-comerciales --config configs/acciones_comerciales.json
```

The report is written **next to the BASE output**
(`data/output/acciones-comerciales/{YYYY-MM}/`) as three files:

| File | Purpose |
|---|---|
| `diff_acciones_comerciales.json` | Machine-readable — every surfaced delta + classification + terna mismatches. |
| `diff_acciones_comerciales.xlsx` | Reviewable — `Resumen`, `Diferencias`, `Validacion Ternas` sheets (each ends in a TOTAL GENERAL row). |
| `diff_acciones_comerciales.txt` | Human summary for sign-off review. |

If `backup_dir` is unset (or holds no `*.xlsx`), the diff step is a **no-op** —
BASE is produced normally and no report is written.

---

## 3. Reading `baseline-defect` vs `real-divergence`

Every surfaced delta is classified as **exactly one** of:

- **`baseline-defect`** — the delta is explained by a **known bug in the legacy
  manual flow**. The Python side is CORRECT; the backup is wrong. These are
  EXPECTED and require no code change — they are the whole reason we are
  replacing the manual engine. The reason string names the specific bug:

  | Reason mentions | Known legacy bug |
  |---|---|
  | `BG:BH` | Stale SUCURSAL snapshot — the manual `BG:BH` map froze at row 72,759, so clients added after the freeze got a wrong/blank sucursal. The Python side does a fresh `dim_cliente` lookup (RF-04). |
  | `BD:BE` | Stale PRECIO snapshot — the manual `BD:BE` price map went `#N/A` for ternas priced after the freeze. The Python side does a fresh terna→precio lookup (RF-05). |
  | `es CCU` | The 6-row "es CCU?" map failed to classify some genérico/marca combos. |
  | `AZ/AX` | `tabla_control` column drift — the legacy reconciliation summed the unit-price (`AZ`) / es-CCU? text-flag (`AX`) columns instead of Facturacion Neta / Descuentos. |

- **`real-divergence`** — **no known bug explains the delta.** These MUST be
  investigated before sign-off. A real divergence means either the Python
  pipeline has a bug, or the legacy flow had a NEW bug we have not catalogued.
  Real divergences are **never** hidden by a tolerance margin (Decision 8) —
  they always appear in both reports.

**The goal of the sign-off month is: every delta is a `baseline-defect`, and
the `real-divergence` count reaches zero (or every remaining one is understood
and accepted).**

### Growing the evidence set

Classification is **evidence-driven** — it does not guess. Attribution comes
from a `known_defects.json` file placed next to the backup
(`<backup_dir>/known_defects.json`):

```json
{
  "stale_sucursal_clients": [730114, 730115],
  "stale_precio_clients": [],
  "stale_precio_ternas": [],
  "es_ccu_defect_generics": ["PERNOD RICARD"],
  "az_ax_drift_columns": ["Suma de Descuento"]
}
```

As you confirm during the parallel run that a given client / terna / genérico /
column sits in a known-defect zone, add it here and re-run. Anything you have
not yet added stays `real-divergence` — which is the honest default: an
un-attributed delta is treated as needing investigation, not silently excused.

---

## 4. Terna → precio empirical validation (Decision 14)

The `Validacion Ternas` sheet (and `terna_mismatches` in the JSON) lists every
generated terna→precio / →Bonific pick that **disagrees** with the real
`aexcel.xlsx`:

- `kind = "precio"` — the picked price differs from the aexcel line by > $0.01.
- `kind = "bonific"` — the picked Bonific differs by > $0.01.
- `kind = "missing-in-aexcel"` — the generated terna has no matching aexcel row.

The RF-01 pick rule (greatest `cantidades_total`, deterministic tie-break) is
**not assumed correct a priori** — it is validated here against the real export
and **adjusted from evidence** if mismatches appear. An empty `Validacion
Ternas` list (only the TOTAL GENERAL row) means the pick rule reproduced the
real aexcel exactly for the period.

> Open item (design §Open Questions): the real `aexcel.xlsx` header row / column
> labels are confirmed during the parallel run. `read_aexcel_export` currently
> expects the aexcel-equivalent column names (`Descripción Período`, `Cod.
> Cliente`, `Código`, `Precio`, `Bonific`); adjust the mapping there once the
> real export layout is pinned.

---

## 5. Sign-off checklist (per monthly cycle)

1. Run the CLI with `backup_dir` + `aexcel_path` set.
2. Open `diff_acciones_comerciales.txt`.
3. Confirm `real-divergence = 0` (or every remaining one is investigated and
   accepted, with a note).
4. Confirm the `terna->precio picks disagreeing with the real aexcel` count is
   0 (or the pick rule was adjusted and re-validated).
5. Record the outcome. After **one clean/explained full monthly cycle**, Phase 2
   (S5–S7) is unblocked (Decision 7).
