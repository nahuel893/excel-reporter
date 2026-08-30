# Superset Bundle — Cobertura Zonas

This directory contains the version-controlled export of the **Cobertura Zonas** Superset dashboard and all its dependent assets. The dashboard is backed by a **virtual dataset** whose `sql:` field encodes the 5-zona cobertura logic from the Python deck pipeline (`src/services/graficos_cobertura/`). No DDL is applied to `gold` — the dataset is virtual, materialized at query time.

## What is here

```
superset/bundle/graficos-cobertura/
├── metadata.yaml                                # Export metadata (version, type)
├── README.md                                    # This file
├── databases/
│   └── Medallion_Gold.yaml                      # DB connection (password masked, REUSE)
├── datasets/
│   └── Medallion_Gold/
│       └── cobertura_zonas.yaml                 # Virtual dataset — sql: populated
├── charts/
│   ├── C01_KPI_Total_Clientes.yaml              # big_number_total
│   ├── C02_KPI_NOA_NORTE.yaml                   # big_number_total (filtered zona=NOA NORTE)
│   ├── C03_Marca_x_Mes.yaml                     # dist_bar (marca × mes stacked)
│   ├── C04_Generico_x_Mes.yaml                  # line (genérico trend)
│   ├── C05_Pivot_Cobertura.yaml                 # pivot_table_v2 (zona × periodo)
│   ├── C06_YoY_Comparativo.yaml                 # dist_bar (anio_actual vs anio_anterior)
│   ├── C07_Generico_Mix.yaml                    # pie (genérico share)
│   └── C08_PerZona_KPIs.yaml                    # big_number_total grouped by zona
└── dashboards/
    └── Cobertura_Zonas.yaml                     # Dashboard layout + 4 native filters
```

## Dashboard overview

**Cobertura Zonas** (`slug: cobertura-zonas`) displays monthly cobertura KPIs across the 5 NOA zonas: NOA NORTE, SALTA CAPITAL, INTERIOR SALTA SUR, INTERIOR SALTA NORTE, JUJUY INTERIOR.

### Charts (8)

| # | Name | Type | What it shows |
|---|------|------|---|
| 1 | Clientes TOTAL | KPI / Big Number | SUM(clientes) for selected (periodo, generico) |
| 2 | NOA NORTE | KPI / Big Number | SUM(clientes) for NOA NORTE (rollup, NOT sum of others) |
| 3 | Marca × Mes | dist_bar | marca stacked bars across meses for (zona, generico) |
| 4 | Genérico × Mes | line | genérico trend across meses for (zona, anio range) |
| 5 | Pivot Cobertura | pivot_table_v2 | zona (rows) × periodo (cols), values = SUM(clientes) |
| 6 | YoY Comparativo | dist_bar | anio_actual vs anio_anterior marca-stacked |
| 7 | Genérico Mix (%) | pie | generico share of total clientes |
| 8 | Clientes por Zona | KPI / Big Number (grouped) | one KPI per zona |

### Native filters (4)

| Filter | Column | `chartsInScope` | `tabsInScope` | `enableEmptyFilter` |
|--------|--------|-----------------|---------------|---------------------|
| Período | `periodo` | [1,2,3,4,5,6,7,8] | [] | true |
| Zona | `zona` | [1,2,3,4,5,6,7,8] | [] | true |
| Genérico | `generico` | [1,2,3,4,5,6,7,8] | [] | true |
| Marca | `marca` | [1,2,3,4,5,6,7,8] | [] | true |

`chartsInScope` + `tabsInScope` are mandatory for native filters to bind correctly on PUT (lesson from the resumen-mensual provisioning gotcha).

### Database connection

- **Connection name**: Medallion (Gold)
- **Role**: `superset_ro` (read-only Postgres role)
- **Host**: `host.docker.internal:5432` (Superset runs in Docker; resolves to the host's Postgres)
- **Database**: `medallion_db`
- **Password**: masked (`XXXXXXXXXX`) in the exported YAML — supply it at import time (see below)
- **UUID**: `a842c321-6955-4eea-9c30-01824a8d0039` (REUSE from resumen-mensual)

## How to re-import

### Option A — Superset UI

1. Go to **Settings → Import dashboards** (or `Manage → Import`).
2. Upload `bundle/graficos-cobertura/` as a ZIP:
   ```bash
   cd superset
   zip -r /tmp/cobertura_zonas_bundle.zip bundle/graficos-cobertura/
   ```
3. When prompted for passwords, supply the `superset_ro` password for the `Medallion (Gold)` connection.

### Option B — API

```bash
# Re-zip the bundle
cd superset
zip -r /tmp/cobertura_zonas_bundle.zip bundle/graficos-cobertura/

# Import via assets endpoint (Superset 2.x+)
curl -X POST https://bi.badie.site/api/v1/assets/import/ \
  -H "Authorization: Bearer <token>" \
  -H "X-CSRFToken: <csrf>" \
  -F "bundle=@/tmp/cobertura_zonas_bundle.zip" \
  -F 'passwords={"databases/Medallion_Gold.yaml": "<superset_ro_password>"}'
```

The `passwords` field is a JSON object mapping the database YAML path (relative inside the ZIP) to the plaintext password. Superset injects it without storing it in the bundle.

## Notes

- The DB password is intentionally masked in `databases/Medallion_Gold.yaml`. Never commit real credentials.
- The `periodo` filter default is empty (`enableEmptyFilter: true`) so the dashboard does not lock out users on a stale `YYYY-MM`. Operators select a period manually after import.

## Caveats (drift between deck and dashboard)

The 5-zona logic + 2025 splice + AGUAS subdivision lives in **TWO places** in the repo, by design of this change (the dashboard does not migrate to a view/MV):

1. `src/services/graficos_cobertura/{constants.py, processor.py}` — drives the Python deck pipeline (PPTX/PNG/XLSX).
2. `superset/bundle/graficos-cobertura/datasets/Medallion_Gold/cobertura_zonas.yaml` (`sql:` field) — drives the Superset dashboard.

If a list changes (zone id_sucursal list, RUTAS_A_SUC16, SUBDIVISION_AGUAS tokens), both must be updated. The structural test `tests/test_graficos_cobertura_virtual_dataset.py` (RF-06) asserts that the SQL contains the reassigned rutas list — it does NOT cross-check against `constants.py::RUTAS_A_SUC16`. If a drift is suspected, run a manual cross-check or write an additional test that parses both and asserts equality on the int list.

**Optional source**: `gold.cob_sucursal_aguas`. If the table is absent in the target environment, the SQL guard `to_regclass('gold.cob_sucursal_aguas')::text IS NOT NULL` causes the AGUAS branch to return zero rows (graceful degradation). The deck pipeline has the same `table_exists` check on the Python side.

## Future: promote to a view (out of scope)

If the drift between the deck Python and the dashboard SQL becomes a maintenance burden, promote the same SQL into a governed view (e.g. `gold.v_cobertura_zonas`) and have both consumers point at it. No MV is required — a plain view suffices because the data is small and the queries are cheap. The bundle would change `database_uuid` (no longer needed) and `sql:` to `null`. Increment a follow-up SDD change; do NOT amend this one.
