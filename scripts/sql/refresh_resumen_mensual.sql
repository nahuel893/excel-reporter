-- =============================================================================
-- refresh_resumen_mensual.sql
-- Refresh gold.mv_resumen_mensual with zero dashboard downtime.
--
-- CONCURRENTLY: readers are NOT blocked during refresh (requires the unique
-- index uix_mv_resumen_mensual_pk created by v_resumen_mensual.sql).
--
-- This script is called automatically by scripts/run_daily.py at the start of
-- the daily run (after the medallion ETL has loaded fact_ventas, before reports
-- are generated). It can also be run manually at any time.
--
-- USAGE:
--   psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/refresh_resumen_mensual.sql
-- =============================================================================

REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_resumen_mensual;
