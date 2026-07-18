-- =============================================================================
-- refresh_stock_quiebre.sql
-- Refresh gold.mv_stock_quiebre with zero dashboard downtime.
--
-- CONCURRENTLY: readers are NOT blocked during refresh (requires the unique
-- index uix_mv_stock_quiebre_pk created by v_stock_quiebre.sql).
--
-- scripts/run_daily.py runs this same REFRESH statement inline (via SQLAlchemy)
-- at the start of the daily run, right after the resumen-mensual refresh and
-- before reports run. This .sql file is the manual/documented equivalent.
--
-- USAGE:
--   psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/refresh_stock_quiebre.sql
-- =============================================================================

REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_stock_quiebre;
