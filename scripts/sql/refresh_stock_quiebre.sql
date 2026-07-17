-- =============================================================================
-- refresh_stock_quiebre.sql
-- Refresh gold.mv_stock_quiebre with zero dashboard downtime.
--
-- CONCURRENTLY: readers are NOT blocked during refresh (requires the unique
-- index uix_mv_stock_quiebre_pk created by v_stock_quiebre.sql).
--
-- This script is called automatically by scripts/run_daily.py at the start of
-- the daily run (right after the resumen-mensual refresh, before reports run).
-- It can also be run manually at any time.
--
-- USAGE:
--   psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/refresh_stock_quiebre.sql
-- =============================================================================

REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_stock_quiebre;
