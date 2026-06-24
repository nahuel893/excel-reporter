# scripts/sql — SQL Scripts

All scripts in this directory are **idempotent**: safe to run multiple times without side effects.

## Apply convention

Run each script directly with `psql`:

```bash
# Apply the resumen mensual materialized view (idempotent DROP+CREATE)
psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/v_resumen_mensual.sql

# Refresh the materialized view (run by the daily flow; also runnable manually)
psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/refresh_resumen_mensual.sql

# Provision the Superset read-only role
psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/superset_user.sql

# Provision the BD Agent read-only role (existing script)
psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/agent_user.sql
```

Replace `CHANGEME` with a real password before running `superset_user.sql` or `agent_user.sql` in any environment.

## Scripts

| File | Purpose |
|---|---|
| `v_resumen_mensual.sql` | `MATERIALIZED VIEW gold.mv_resumen_mensual` (DROP+CREATE, unique index for CONCURRENTLY) — encodes all resumen mensual business rules for Superset |
| `refresh_resumen_mensual.sql` | `REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_resumen_mensual` — run by the daily flow so the dashboard is current |
| `superset_user.sql` | Read-only Postgres role for Apache Superset (`superset_user`) |
| `agent_user.sql` | Read-only Postgres role for the WhatsApp BD Agent (`agent_user`) |

## Role scripts pattern

Role scripts follow the `agent_user.sql` convention:
1. `DO $$` block for idempotent role creation (checks `pg_catalog.pg_roles`)
2. `REVOKE ALL ON SCHEMA gold FROM <role>` — clean slate
3. `GRANT USAGE ON SCHEMA gold TO <role>` — schema visibility
4. `GRANT SELECT ON ALL TABLES IN SCHEMA gold TO <role>` — current tables
5. `ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO <role>` — future tables

## Yearly maintenance

`v_resumen_mensual.sql` contains a hardcoded `DATE[]` array of Argentina public holidays.
Update the `feriados` CTE at the start of each year to match `config/settings.py::FERIADOS`.
