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
