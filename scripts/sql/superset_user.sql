-- =============================================================================
-- superset_user.sql
-- Postgres role for Apache Superset (read-only access to gold schema)
--
-- USAGE:
--   psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/superset_user.sql
--
-- IMPORTANT: Replace 'CHANGEME' with a strong random password before running
-- this script in any environment (dev, staging, or production).
-- Never commit the real password to version control.
--
-- This script is idempotent: safe to run multiple times.
-- Role privileges: NO superuser, NO CREATEDB, NO CREATEROLE.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- Step 1 — Create the role (idempotent via DO $$ block)
-- We use a DO block because CREATE ROLE has no IF NOT EXISTS in older PG
-- versions, and we want the script to be re-runnable without errors.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles WHERE rolname = 'superset_user'
   ) THEN
      -- LOGIN grants the role the ability to authenticate as a DB user.
      -- The password MUST be changed before deploying to production.
      -- Role has NO SUPERUSER, NO CREATEDB, NO CREATEROLE.
      CREATE ROLE superset_user WITH LOGIN PASSWORD 'CHANGEME';
      RAISE NOTICE 'Role superset_user created.';
   ELSE
      RAISE NOTICE 'Role superset_user already exists — skipping CREATE.';
   END IF;
END
$$;


-- ---------------------------------------------------------------------------
-- Step 2 — Revoke all default privileges on schema gold
-- By default Postgres may grant PUBLIC usage on newly created schemas.
-- We start from a clean slate: deny everything, then grant only what we need.
-- This is idempotent — REVOKE on a role that has no privileges is a no-op.
-- ---------------------------------------------------------------------------
REVOKE ALL ON SCHEMA gold FROM superset_user;


-- ---------------------------------------------------------------------------
-- Step 3 — Grant USAGE on schema gold
-- USAGE allows the role to resolve object names inside the schema (required
-- before any table-level SELECT can work). It does NOT imply table access.
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA gold TO superset_user;


-- ---------------------------------------------------------------------------
-- Step 4 — Grant SELECT on all current tables and views in schema gold
-- This covers every table/view that exists at the time this script is executed.
-- It is idempotent: re-running grants to tables already granted is a no-op.
-- ---------------------------------------------------------------------------
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO superset_user;


-- ---------------------------------------------------------------------------
-- Step 4b — Explicit GRANT SELECT on gold.mv_resumen_mensual (materialized view)
--
-- GRANT ON ALL TABLES covers regular tables and views. Materialized views are
-- NOT included in all PostgreSQL versions. An explicit grant ensures the MV
-- is accessible to superset_user regardless of PG version or execution order.
-- This is idempotent — safe to re-run.
-- ---------------------------------------------------------------------------
GRANT SELECT ON gold.mv_resumen_mensual TO superset_user;


-- ---------------------------------------------------------------------------
-- Step 5 — Alter default privileges for future tables and views
-- Without this, any new table or view created in gold (e.g. after a migration)
-- would require running this script again to expose it to superset_user.
-- ALTER DEFAULT PRIVILEGES applies to tables created by the current user in
-- future transactions within the gold schema.
-- Note: this must be run by the same role that will CREATE future tables
-- (typically the migration user or superuser running this script).
-- ---------------------------------------------------------------------------
ALTER DEFAULT PRIVILEGES IN SCHEMA gold
   GRANT SELECT ON TABLES TO superset_user;


-- =============================================================================
-- Verification (optional — run manually to confirm)
-- =============================================================================
-- SELECT has_schema_privilege('superset_user', 'gold', 'USAGE');
--   Expected: t
--
-- SELECT grantee, privilege_type
-- FROM information_schema.role_table_grants
-- WHERE grantee = 'superset_user' AND table_schema = 'gold'
-- LIMIT 5;
--   Expected: rows with SELECT for each gold.* table/view/materialized view
--
-- Attempt write (must fail with permission error):
-- SET ROLE superset_user;
-- INSERT INTO gold.fact_ventas VALUES (...);  -- Expected: ERROR: permission denied
-- RESET ROLE;
-- =============================================================================
