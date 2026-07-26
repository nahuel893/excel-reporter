# Superset Bundle — Informes Badie

This directory contains the version-controlled exports of the BADIE SA Superset dashboards and all their dependent assets.

## Bundles

Two bundles are tracked here, each with its own dashboard, dataset, charts, and DB binding:

- `bundle/` — **Resumen Mensual** (`slug: resumen-mensual`), backed by `gold.mv_resumen_mensual` (a materialized view).
- `bundle/graficos-cobertura/` — **Cobertura Zonas** (`slug: cobertura-zonas`), backed by a **virtual dataset** whose `sql:` field encodes the 5-zona cobertura logic. No DDL on `gold`, no MV, no superuser.

## Cobertura Zonas (virtual dataset, additive)

`bundle/graficos-cobertura/` is a strict additive deliverable: the Python deck pipeline (`src/services/graficos_cobertura/*`) is untouched. See [`bundle/graficos-cobertura/README.md`](bundle/graficos-cobertura/README.md) for full details.

```
superset/bundle/graficos-cobertura/
├── metadata.yaml                          # Export metadata (version, type)
├── README.md                              # Bundle-specific notes
├── dashboards/Cobertura_Zonas.yaml        # Dashboard + 4 native filters
├── charts/C01..C08_*.yaml                 # 8 chart YAMLs (KPI, dist_bar, line, pivot, pie)
├── datasets/Medallion_Gold/cobertura_zonas.yaml   # Virtual dataset, sql: populated
└── databases/Medallion_Gold.yaml          # DB connection (REUSE, same UUID a842c321-...)
```

### Charts (8)

| # | Name | Type | What it shows |
|---|------|------|---|
| 1 | Clientes TOTAL | KPI / Big Number | SUM(clientes) for selected (periodo, generico) |
| 2 | NOA NORTE | KPI / Big Number | SUM(clientes) for NOA NORTE (rollup, NOT sum of others) |
| 3 | Marca × Mes | dist_bar | marca stacked bars across meses |
| 4 | Genérico × Mes | line | genérico trend across meses |
| 5 | Pivot Cobertura | pivot_table_v2 | zona (rows) × periodo (cols) |
| 6 | YoY Comparativo | dist_bar | anio_actual vs anio_anterior marca-stacked |
| 7 | Genérico Mix (%) | pie | generico share of total clientes |
| 8 | Clientes por Zona | KPI / Big Number (grouped) | one KPI per zona |

### Native filters (4)

| Filter | Column | `chartsInScope` | `tabsInScope` | `enableEmptyFilter` |
|--------|--------|-----------------|---------------|---------------------|
| Período | `periodo` | [1..8] | [] | true |
| Zona | `zona` | [1..8] | [] | true |
| Genérico | `generico` | [1..8] | [] | true |
| Marca | `marca` | [1..8] | [] | true |

### Database connection (REUSE)

Same `Medallion (Gold)` connection as Resumen Mensual: `uuid: a842c321-6955-4eea-9c30-01824a8d0039`, masked password `XXXXXXXXXX`, `host.docker.internal:5432`, `medallion_db`. Supply the real `superset_ro` password at import time.

### Re-import recipe

```bash
cd superset
zip -r /tmp/cobertura_zonas_bundle.zip bundle/graficos-cobertura/

curl -X POST https://bi.badie.site/api/v1/assets/import/ \
  -H "Authorization: Bearer <token>" \
  -H "X-CSRFToken: <csrf>" \
  -F "bundle=@/tmp/cobertura_zonas_bundle.zip" \
  -F 'passwords={"databases/Medallion_Gold.yaml": "<superset_ro_password>"}'
```

Or use the helper: `scripts/superset_reimport_cobertura.sh` (env-driven, prints chart listing at the end).

---

# Superset Bundle — Resumen Mensual

This directory contains the version-controlled export of the **Resumen Mensual** Superset dashboard and all its dependent assets.

## What is here

```
superset/
└── bundle/
    ├── metadata.yaml                          # Export metadata (version, type)
    ├── dashboards/
    │   └── Resumen_Mensual_2.yaml             # Dashboard layout + native filters
    ├── charts/
    │   ├── Resumen_Tendencia_TOTAL_1.yaml     # KPI card: Tendencia TOTAL
    │   ├── Resumen_Casa_Central_2.yaml        # KPI card: Casa Central
    │   ├── Resumen_Interior_3.yaml            # KPI card: Interior
    │   ├── Resumen__Cumplimiento_4.yaml       # KPI card: % Cumplimiento
    │   ├── Resumen_Detalle_por_sucursal_5.yaml # Semáforo table by sucursal
    │   └── Resumen_Tendencia_vs_Objetivo_6.yaml # Bar chart: trend vs. target
    ├── datasets/
    │   └── Medallion_Gold/
    │       └── mv_resumen_mensual.yaml        # Dataset on gold.mv_resumen_mensual
    └── databases/
        └── Medallion_Gold.yaml                # DB connection (password masked)
```

## Dashboard overview

**Resumen Mensual** (`slug: resumen-mensual`) displays monthly sales KPIs from the `gold.mv_resumen_mensual` materialized view.

The MV is in **LONG format**: one row per `(periodo, sucursal, generico, marca, medida)` where `medida` is either `BULTOS` (unit quantities) or `HTLS` (hectoliter equivalents).

### Charts (6)

| # | Name | Type |
|---|------|------|
| 1 | Tendencia TOTAL | KPI / Big Number |
| 2 | Casa Central | KPI / Big Number |
| 3 | Interior | KPI / Big Number |
| 4 | % Cumplimiento | KPI / Big Number |
| 5 | Detalle por sucursal | Table (semáforo conditional formatting) |
| 6 | Tendencia vs Objetivo | Bar chart |

### Native filters (3)

| Filter | Column | Default |
|--------|--------|---------|
| Genérico | `generico` | CERVEZAS |
| Período | `periodo` | current month (YYYY-MM) |
| Medida | `medida` | BULTOS |

### Database connection

- **Connection name**: Medallion (Gold)
- **Role**: `superset_ro` (read-only Postgres role)
- **Host**: `host.docker.internal:5432` (Superset runs in Docker; resolves to the host's Postgres)
- **Database**: `medallion_db`
- **Password**: masked (`XXXXXXXXXX`) in the exported YAML — supply it at import time (see below)

## How to re-import

### Option A — Superset UI

1. Go to **Settings → Import dashboards** (or `Manage → Import`).
2. Upload `bundle/` as a ZIP (re-zip the bundle directory first):
   ```bash
   cd superset
   zip -r resumen_mensual_bundle.zip bundle/
   ```
3. When prompted for passwords, supply the `superset_ro` password for the `Medallion (Gold)` connection.

### Option B — API

```bash
# Re-zip the bundle
cd superset
zip -r /tmp/resumen_mensual_bundle.zip bundle/

# Import via assets endpoint (Superset 2.x+)
curl -X POST https://bi.badie.site/api/v1/assets/import/ \
  -H "Authorization: Bearer <token>" \
  -H "X-CSRFToken: <csrf>" \
  -F "bundle=@/tmp/resumen_mensual_bundle.zip" \
  -F 'passwords={"databases/Medallion_Gold.yaml": "<superset_ro_password>"}'

# Alternative: dashboard-specific endpoint
curl -X POST https://bi.badie.site/api/v1/dashboard/import/ \
  -H "Authorization: Bearer <token>" \
  -H "X-CSRFToken: <csrf>" \
  -F "formData=@/tmp/resumen_mensual_bundle.zip" \
  -F 'passwords={"databases/Medallion_Gold.yaml": "<superset_ro_password>"}'
```

The `passwords` field is a JSON object mapping the database YAML path (relative inside the ZIP) to the plaintext password. Superset injects it without storing it in the bundle.

## Notes

- The DB password is intentionally masked in `databases/Medallion_Gold.yaml`. Never commit real credentials.
- The `periodo` filter default (`2026-06`) is captured at export time and should be updated manually after re-import, or left to users to change via the filter bar.
- If the `gold.mv_resumen_mensual` MV does not exist in the target environment, refresh it before using the dashboard:
  ```sql
  REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_resumen_mensual;
  ```
