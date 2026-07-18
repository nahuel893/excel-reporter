# Superset Bundle — Stock BADIE

Version-controlled export of the **Stock BADIE** dashboard (`slug: stock-badie`) on
https://bi.badie.site. Reimportable snapshot of dataset + charts + dashboard.

## Contents

```
superset/stock-badie/
├── metadata.yaml
├── databases/Medallion_Gold.yaml                 # DB connection (password masked)
├── datasets/Medallion_Gold/mv_stock_quiebre.yaml # dataset over gold.mv_stock_quiebre
├── charts/
│   ├── Quiebre_ROJO_15_dias_20.yaml              # KPI: # artículos ROJO (<15 días)
│   ├── Vigilar_AMARILLO_15-30_dias_21.yaml       # KPI: # AMARILLO (15-30 días)
│   ├── Cubierto_VERDE_30_dias_22.yaml            # KPI: # VERDE (>30 días)
│   └── Stock_Quiebre_por_sucursal_articulo_23.yaml # semáforo table
└── dashboards/Stock_BADIE_5.yaml                 # layout (tab Mensual) + native filters
```

## Vista 1 — Mensual (Quiebre)

Backed by the materialized view `gold.mv_stock_quiebre` (see
`scripts/sql/v_stock_quiebre.sql`), refreshed daily by `scripts/run_daily.py`.

- **KPIs**: count of articles in each semáforo band (ROJO / AMARILLO / VERDE).
- **Semáforo table**: one row per (sucursal, artículo) with Venta mes, Stock hoy,
  Días de alcance, Pedido sugerido (15d), ordered by pedido desc, with conditional
  formatting on **Días de alcance** (<15 red, 15-30 yellow, >30 green) and a totals row.
- **Native filters**: Genérico, Marca, Sucursal (multi-select).

### The one metric that must stay a metric

`Días de alcance` (alcance_dias) is defined in the dataset as
`SUM(stock_hoy_bultos) / NULLIF(SUM(venta_diaria_bultos), 0)` — a ratio. It is
**never** a stored column: a per-row ratio cannot be summed/averaged correctly once
grouped. Keeping it a Superset metric makes it correct at every aggregation (row,
sucursal subtotal, grand total).

## Re-import

```bash
cd superset/stock-badie
zip -r /tmp/stock_badie_bundle.zip .
curl -X POST https://bi.badie.site/api/v1/dashboard/import/ \
  -H "Authorization: Bearer <token>" -H "X-CSRFToken: <csrf>" \
  -F "formData=@/tmp/stock_badie_bundle.zip" \
  -F 'passwords={"databases/Medallion_Gold.yaml": "<superset_ro_password>"}'
```

The `gold.mv_stock_quiebre` MV must exist in the target DB first
(`scripts/sql/v_stock_quiebre.sql`), granted to `superset_ro`.

## Notes

- DB password is masked (`XXXXXXXXXX`) — never commit real credentials.
- Tab 2 (Histórico diario) is added by a later change (PR#2); this bundle is Tab 1 only.
