-- =============================================================================
-- v_resumen_mensual.sql
-- CREATE MATERIALIZED VIEW gold.mv_resumen_mensual
--
-- Encodes ALL business rules of the Python/Excel resumen mensual pipeline.
-- One row per (periodo, sucursal, generico, marca). No subtotal rows.
--
-- REFRESH MODEL:
--   The MV is refreshed once per daily run (scripts/run_daily.py calls
--   refresh_mv_resumen_mensual() at startup). The daily medallion ETL loads
--   fact_ventas before 07:00; reports run at 07:00 with fresh data; so the MV
--   is always current by the time Superset users query it.
--
--   Manual refresh:
--     psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/refresh_resumen_mensual.sql
--
-- USAGE (idempotent — safe to re-run):
--   psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/v_resumen_mensual.sql
--
-- MAINTENANCE:
--   The feriados CTE mirrors config/settings.py::FERIADOS exactly.
--   Update the DATE[] array every year to reflect the new public holiday list.
--   See: settings.py::FERIADOS (Argentina).
--
-- COLUMNS (RF-01):
--   periodo      TEXT    'YYYY-MM'
--   sucursal     TEXT    Post zona-virtual rename
--   grupo        TEXT    'CASA CENTRAL' | 'INTERIOR' | 'DIRECTA'
--   generico     TEXT
--   marca        TEXT
--   vtas_n1      NUMERIC Last working day with sales (<=LEAST(CURRENT_DATE, end_of_month))
--   vtas_n2      NUMERIC Second-to-last working day with sales
--   total_ventas NUMERIC SUM(cantidades_total); no anulado filter; PRVTA excluded for FRATELLI B only
--   tendencia    NUMERIC total_ventas * (habiles_mes / habiles_transcurridos); = total_ventas for closed months
--   mmaa         NUMERIC Same month prior year total
--   ma           NUMERIC Prior calendar month total
--   objetivo     NUMERIC | NULL  From gold.fact_cupos only; NULL when absent
--   tend_vs_obj  NUMERIC | NULL  tendencia/objetivo; NULL when objetivo NULL or 0
-- =============================================================================

-- Step 1: Drop the plain view if it exists (migration: view → materialized view)
DROP VIEW IF EXISTS gold.v_resumen_mensual CASCADE;

-- Step 2: Drop the materialized view if it already exists (idempotent re-run)
DROP MATERIALIZED VIEW IF EXISTS gold.mv_resumen_mensual CASCADE;

-- Step 3: Create the materialized view
CREATE MATERIALIZED VIEW gold.mv_resumen_mensual AS

WITH

-- ---------------------------------------------------------------------------
-- feriados: Argentina 2026 public holidays as a set of dates.
-- MAINTENANCE NOTE: mirror config/settings.py::FERIADOS exactly — update yearly.
-- ---------------------------------------------------------------------------
feriados AS (
    SELECT unnest(ARRAY[
        '2026-01-01',  -- Año Nuevo
        '2026-02-16',  -- Carnaval
        '2026-02-17',  -- Carnaval
        '2026-03-24',  -- Día de la Memoria
        '2026-04-02',  -- Día del Veterano
        '2026-04-03',  -- Viernes Santo
        '2026-05-01',  -- Día del Trabajador
        '2026-05-25',  -- Día de la Revolución de Mayo
        '2026-06-15',  -- Paso a la Inmortalidad Güemes
        '2026-06-20',  -- Día de la Bandera
        '2026-07-09',  -- Día de la Independencia
        '2026-08-17',  -- Paso a la Inmortalidad San Martín
        '2026-10-12',  -- Día del Respeto a la Diversidad Cultural
        '2026-11-23',  -- Día de la Soberanía Nacional
        '2026-12-08',  -- Inmaculada Concepción
        '2026-12-25'   -- Navidad
    ]::date[]) AS f
),

-- ---------------------------------------------------------------------------
-- periodos: distinct months present in fact_ventas.
-- ---------------------------------------------------------------------------
periodos AS (
    SELECT DISTINCT
        date_trunc('month', fecha_comprobante)::date AS periodo
    FROM gold.fact_ventas
),

-- ---------------------------------------------------------------------------
-- dias: working-day counts per periodo.
--   habiles_mes           = total working days in the calendar month
--   habiles_transcurridos = working days up to LEAST(CURRENT_DATE, last_day_of_month)
--
-- For CLOSED months (periodo < current month):
--   corte = last_day_of_month  →  habiles_transcurridos = habiles_mes
--   → factor = 1  →  tendencia = total_ventas (no projection needed, no CASE required)
--
-- For the CURRENT month:
--   corte = CURRENT_DATE  →  habiles_transcurridos = days elapsed so far
--   → factor = habiles_mes / habiles_transcurridos  →  tendencia = projection
-- ---------------------------------------------------------------------------
dias AS (
    SELECT
        p.periodo,
        -- Total working days in the full calendar month
        SUM(CASE
            WHEN extract(dow FROM gs.d) <> 0   -- exclude Sundays (dow=0)
             AND gs.d NOT IN (SELECT f FROM feriados)
            THEN 1 ELSE 0
        END)                                          AS habiles_mes,
        -- Working days up to LEAST(CURRENT_DATE, last day of month)
        SUM(CASE
            WHEN gs.d <= LEAST(CURRENT_DATE, (p.periodo + interval '1 month - 1 day')::date)
             AND extract(dow FROM gs.d) <> 0
             AND gs.d NOT IN (SELECT f FROM feriados)
            THEN 1 ELSE 0
        END)                                          AS habiles_transcurridos
    FROM periodos p
    -- Generate every calendar day in the month as date
    CROSS JOIN LATERAL (
        SELECT generate_series(
            p.periodo,
            (p.periodo + interval '1 month - 1 day')::date,
            interval '1 day'
        )::date AS d
    ) gs
    GROUP BY p.periodo
),

-- ---------------------------------------------------------------------------
-- base: raw sales rows with zona-virtual renaming applied BEFORE grouping.
--
-- Zona-virtual logic (mirrors config/settings.py::ZONAS_VIRTUALES):
--   VALLE SALTA:        CASA CENTRAL + id_ruta IN (81,82,83,84,85,86,87,88,89,90,91,92,118,119,120,122)
--   SUB DISTRIBUIDORES: CASA CENTRAL + id_ruta = 93
--   DIRECTA SUCURSALES: id_ruta = 100 AND sucursal != 'CASA CENTRAL'
--   (DIRECTA logic mirrors _segregar_directa_sucursales in service.py)
--
-- Join: fact_ventas ← dim_articulo, dim_sucursal, dim_cliente (composite: id_cliente+id_sucursal)
-- Ventas: SUM(cantidades_total), NO filter on anulado.
-- PRVTA exclusion: ONLY for generico = 'FRATELLI B' (RF-03).
-- ---------------------------------------------------------------------------
base AS (
    SELECT
        date_trunc('month', fv.fecha_comprobante)::date AS periodo,
        CASE
            WHEN ds.descripcion = 'CASA CENTRAL'
                 AND dc.id_ruta_fv1 IN (81,82,83,84,85,86,87,88,89,90,91,92,118,119,120,122)
                THEN 'VALLE SALTA'
            WHEN ds.descripcion = 'CASA CENTRAL'
                 AND dc.id_ruta_fv1 = 93
                THEN 'SUB DISTRIBUIDORES'
            WHEN dc.id_ruta_fv1 = 100
                 AND ds.descripcion <> 'CASA CENTRAL'
                THEN 'DIRECTA SUCURSALES'
            ELSE ds.descripcion
        END                                              AS sucursal,
        da.generico,
        da.marca,
        fv.fecha_comprobante::date                       AS fecha,
        fv.cantidades_total                              AS q
    FROM gold.fact_ventas fv
    JOIN  gold.dim_articulo  da ON fv.id_articulo = da.id_articulo
    JOIN  gold.dim_sucursal  ds ON fv.id_sucursal = ds.id_sucursal
    LEFT JOIN gold.dim_cliente dc ON fv.id_cliente  = dc.id_cliente
                                  AND fv.id_sucursal = dc.id_sucursal
    WHERE da.generico IS NOT NULL
      -- PRVTA exclusion: only for FRATELLI B (RF-03)
      AND NOT (da.generico = 'FRATELLI B' AND fv.id_documento = 'PRVTA')
),

-- ---------------------------------------------------------------------------
-- daily_totals: aggregate sales by (periodo, sucursal, generico, marca, fecha)
-- limited to working days and capped at LEAST(CURRENT_DATE, end_of_month).
-- Used to find N-1 and N-2 working days with sales via window functions.
-- ---------------------------------------------------------------------------
daily_totals AS (
    SELECT
        b.periodo,
        b.sucursal,
        b.generico,
        b.marca,
        b.fecha,
        SUM(b.q) AS daily_q
    FROM base b
    WHERE b.fecha <= LEAST(
            CURRENT_DATE,
            (b.periodo + interval '1 month - 1 day')::date
        )
      -- Only working days with sales (exclude Sundays and feriados)
      AND extract(dow FROM b.fecha) <> 0
      AND b.fecha NOT IN (SELECT f FROM feriados)
    GROUP BY b.periodo, b.sucursal, b.generico, b.marca, b.fecha
),

-- ---------------------------------------------------------------------------
-- ranked_days: rank working days with sales descending per partition.
--   rn=1 → most recent working day with sales (N-1)
--   rn=2 → second most recent working day with sales (N-2)
-- ---------------------------------------------------------------------------
ranked_days AS (
    SELECT
        periodo,
        sucursal,
        generico,
        marca,
        fecha,
        daily_q,
        ROW_NUMBER() OVER (
            PARTITION BY periodo, sucursal, generico, marca
            ORDER BY fecha DESC
        ) AS rn
    FROM daily_totals
),

-- ---------------------------------------------------------------------------
-- agg: aggregate per (periodo, sucursal, generico, marca).
--   total_ventas: full period sum (all dates, no working-day cutoff)
--   vtas_n1:      sales on the most-recent working day with sales (rn=1)
--   vtas_n2:      sales on the second-to-last working day with sales (rn=2)
-- ---------------------------------------------------------------------------
base_agg AS (
    SELECT
        periodo,
        sucursal,
        generico,
        marca,
        SUM(q) AS total_ventas
    FROM base
    GROUP BY periodo, sucursal, generico, marca
),

agg AS (
    SELECT
        ba.periodo,
        ba.sucursal,
        ba.generico,
        ba.marca,
        ba.total_ventas,
        COALESCE(rd1.daily_q, 0)  AS vtas_n1,
        COALESCE(rd2.daily_q, 0)  AS vtas_n2
    FROM base_agg ba
    LEFT JOIN ranked_days rd1
        ON  rd1.periodo  = ba.periodo
        AND rd1.sucursal = ba.sucursal
        AND rd1.generico = ba.generico
        AND rd1.marca    = ba.marca
        AND rd1.rn = 1
    LEFT JOIN ranked_days rd2
        ON  rd2.periodo  = ba.periodo
        AND rd2.sucursal = ba.sucursal
        AND rd2.generico = ba.generico
        AND rd2.marca    = ba.marca
        AND rd2.rn = 2
),

-- ---------------------------------------------------------------------------
-- cupos: objetivo from gold.fact_cupos only (RF-05).
--
-- fact_cupos.sucursal stores a prefixed string "NN - SUCURSAL NAME" — strip
-- the numeric prefix with REGEXP_REPLACE before zona-virtual relabeling.
--
-- Zona-virtual relabeling is applied to cupos so the join key matches agg.sucursal:
--   VALLE SALTA routes and SUB DISTRIBUIDORES route are relabeled.
--   DIRECTA SUCURSALES (id_ruta=100) is also relabeled.
--
-- SUM(cupo) aggregates to (periodo, sucursal, generico) grain — multiple
-- preventistas (routes) per sucursal/generico do NOT double-count when summed.
--
-- NOTE on fact_cupos granularity (verified from get_cupos_resumen_mensual):
--   fact_cupos has columns: periodo, sucursal (prefixed "NN - NAME"), id_ruta, generico, cupo.
--   It IS at route/preventista level (one row per preventista within a sucursal).
--   The Python service strips the prefix and applies zona-virtual renaming via
--   _segregar_directa_sucursales + aplicar_zonas_virtuales, then SUM(cupo).
--   This view replicates that logic directly in SQL.
-- ---------------------------------------------------------------------------
cupos AS (
    SELECT
        -- Strip leading "NN - " prefix from sucursal name (mirrors REGEXP_REPLACE in Python)
        CASE
            WHEN REGEXP_REPLACE(fc.sucursal, '^\d+ - ', '') = 'CASA CENTRAL'
                 AND fc.id_ruta IN (81,82,83,84,85,86,87,88,89,90,91,92,118,119,120,122)
                THEN 'VALLE SALTA'
            WHEN REGEXP_REPLACE(fc.sucursal, '^\d+ - ', '') = 'CASA CENTRAL'
                 AND fc.id_ruta = 93
                THEN 'SUB DISTRIBUIDORES'
            WHEN fc.id_ruta = 100
                 AND REGEXP_REPLACE(fc.sucursal, '^\d+ - ', '') <> 'CASA CENTRAL'
                THEN 'DIRECTA SUCURSALES'
            ELSE REGEXP_REPLACE(fc.sucursal, '^\d+ - ', '')
        END                                             AS sucursal,
        fc.generico,
        -- periodo in fact_cupos is stored as 'YYYY-MM'; convert to first-day-of-month date
        to_date(fc.periodo, 'YYYY-MM')                  AS periodo,
        SUM(fc.cupo)                                    AS objetivo
    FROM gold.fact_cupos fc
    WHERE fc.generico IS NOT NULL
    GROUP BY 1, 2, 3
)

-- ---------------------------------------------------------------------------
-- Final SELECT: join all CTEs and compute derived columns.
-- ---------------------------------------------------------------------------
SELECT
    -- periodo as text 'YYYY-MM' for Superset filter compatibility
    to_char(a.periodo, 'YYYY-MM')                                       AS periodo,
    a.sucursal,
    -- grupo derivation (RF-02): applied AFTER zona-virtual rename
    CASE
        WHEN a.sucursal IN ('CASA CENTRAL', 'VALLE SALTA', 'SUB DISTRIBUIDORES')
            THEN 'CASA CENTRAL'
        WHEN a.sucursal = 'DIRECTA SUCURSALES'
            THEN 'DIRECTA'
        ELSE 'INTERIOR'
    END                                                                  AS grupo,
    a.generico,
    a.marca,

    -- N-1 and N-2 day slices (0 when no sales on that day)
    a.vtas_n1,
    a.vtas_n2,

    -- Total sales for the period
    a.total_ventas,

    -- Tendencia: projection for current month, = total_ventas for closed months.
    -- LEAST(CURRENT_DATE, end_of_month) ensures habiles_transcurridos = habiles_mes for closed months
    -- → factor = 1 → tendencia = total_ventas automatically.
    a.total_ventas * d.habiles_mes::numeric
        / NULLIF(d.habiles_transcurridos, 0)                            AS tendencia,

    -- MMAA: same month prior year (full calendar month)
    mmaa.total_ventas                                                    AS mmaa,

    -- MA: prior calendar month (full)
    ma.total_ventas                                                      AS ma,

    -- Objetivo: from fact_cupos only; NULL when no matching row (RF-05)
    c.objetivo,

    -- Tend vs Obj: NULL when objetivo is NULL or 0 (NULLIF guard) (RF-05)
    (
        a.total_ventas * d.habiles_mes::numeric
            / NULLIF(d.habiles_transcurridos, 0)
    ) / NULLIF(c.objetivo, 0)                                           AS tend_vs_obj

FROM agg a
JOIN dias d
    ON d.periodo = a.periodo

-- MMAA: same (sucursal, generico, marca) one year back
LEFT JOIN agg mmaa
    ON  mmaa.periodo  = (a.periodo - interval '1 year')::date
    AND mmaa.sucursal = a.sucursal
    AND mmaa.generico = a.generico
    AND mmaa.marca    = a.marca

-- MA: same (sucursal, generico, marca) one month back
LEFT JOIN agg ma
    ON  ma.periodo  = (a.periodo - interval '1 month')::date
    AND ma.sucursal = a.sucursal
    AND ma.generico = a.generico
    AND ma.marca    = a.marca

-- Objetivo: left join so NULL is preserved when absent
LEFT JOIN cupos c
    ON  c.periodo  = a.periodo
    AND c.sucursal = a.sucursal
    AND c.generico = a.generico;


-- =============================================================================
-- Step 4: Unique index on natural key (required for REFRESH ... CONCURRENTLY)
--
-- Natural key: (periodo, sucursal, generico, marca).
-- marca can be NULL (14 nulls verified in 2026-05) — use NULLS NOT DISTINCT
-- (PostgreSQL 15+) so NULLs compare equal for uniqueness purposes.
-- =============================================================================
CREATE UNIQUE INDEX uix_mv_resumen_mensual_pk
    ON gold.mv_resumen_mensual (periodo, sucursal, generico, marca)
    NULLS NOT DISTINCT;
