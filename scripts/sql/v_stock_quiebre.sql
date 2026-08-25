-- =============================================================================
-- v_stock_quiebre.sql
-- CREATE MATERIALIZED VIEW gold.mv_stock_quiebre
--
-- Encodes the STOCK / quiebre-detection business logic previously kept in the
-- manual "Copia de Stock Badie.xlsm" workbook (Vista 1 — Mensual/Quiebre).
-- One row per (sucursal, id_articulo). No subtotal rows.
--
-- REFRESH MODEL:
--   Refreshed once per daily run (scripts/run_daily.py calls
--   _refresh_mv_stock_quiebre() right after the resumen-mensual refresh, before
--   any report runs).
--
--   Manual refresh:
--     psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/refresh_stock_quiebre.sql
--
-- USAGE (idempotent — safe to re-run):
--   psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/v_stock_quiebre.sql
--
-- MAINTENANCE:
--   The feriados CTE mirrors config/settings.py::FERIADOS exactly.
--   Update the DATE[] array every year to reflect the new public holiday list.
--   See: settings.py::FERIADOS (Argentina).
--
-- COLUMNS (RF-01):
--   sucursal                     TEXT     Raw sucursal (dim_deposito -> dim_sucursal). NO
--                                          VALLE SALTA / zona-virtual split (RF-15) — mirrors
--                                          the xlsm reference, which has no id_ruta on stock.
--   id_articulo                  INTEGER
--   des_articulo                 TEXT
--   generico                     TEXT
--   marca                        TEXT
--   stock_hoy_bultos              NUMERIC  Latest fact_stock snapshot (MAX(date_stock)),
--                                          summed over all depositos of the sucursal.
--   stock_hoy_htls                NUMERIC  Same snapshot, htls unit.
--   venta_mes_bultos               NUMERIC  SUM(cantidades_total), current calendar month,
--                                          from fact_ventas.
--   venta_mes_htls                 NUMERIC  SUM(cantidad_total_htls), current month.
--   dias_habiles_transcurridos      NUMERIC  Same constant value on every row (refresh-date
--                                          dependent, not per-article). See RF-02.
--   venta_diaria_bultos             NUMERIC  = venta_mes_bultos / NULLIF(dias_habiles_transcurridos, 0)
--   tendencia_bultos                NUMERIC  = venta_diaria_bultos * dias_habiles_totales_mes
--                                          (project convention: cantidad * dias_totales/dias_transcurridos;
--                                          parity column, not in the xlsm reference).
--   pedido_sugerido_15d_bultos      NUMERIC  = GREATEST(venta_diaria_bultos * 15 - stock_hoy_bultos, 0)
--   estado_semaforo                  TEXT    'ROJO' (stock = 0, OR <15d cobertura) | 'AMARILLO'
--                                          (15-30d) | 'VERDE' (>30d, or dormant stock>0 with
--                                          no/negative sales) — per-row band, drives the KPI count
--                                          cards (RF-12). Zero stock is ALWAYS ROJO (see CASE).
--
-- NON-GOALS (RF-04, RF-15):
--   `alcance_dias` (dias de cobertura) is NEVER a stored column here. It MUST be
--   computed in Superset as SUM(stock_hoy_bultos)/NULLIF(SUM(venta_diaria_bultos),0)
--   so it aggregates correctly at ANY grouping — a stored per-row ratio would be
--   mathematically wrong once summed/averaged across more than one row.
--   No `medida` long-format dimension (parallel _bultos/_htls columns instead —
--   supersedes the resumen-mensual long-format pattern for this MV, per spec RF-01
--   and universe-validation discovery).
--   No ROUND/TRUNC/::INTEGER anywhere — formatting is a Superset display concern only.
--
-- UNIVERSE / JOIN SEMANTICS (revised 2026-07-28 — surface every real quiebre):
--   gold.fact_stock emits a row per (article, deposito) EVERY day, including
--   zero-stock rows (verified: 34245 rows = 2283 articulos x 15 depositos on a
--   representative snapshot; 91% of rows are zero bultos). So the raw snapshot is
--   a full (article x deposito) cartesian — most of it zero noise.
--   The universe keeps a (sucursal, articulo) row when the article is active
--   (sold anywhere in the last 3 years, RF-05) AND, per sucursal, EITHER
--     * it has physical stock today (stock <> 0)  -> real inventory to report, OR
--     * this sucursal has sold it in the last 3 years (pares_activos) -> part of
--       the sucursal's real assortment, so a zero-stock row IS a quiebre to show.
--   This deliberately surfaces stock=0 / no-sale-this-month rows the prior
--   "stock<>0 OR sold-this-month" guard hid — the most critical quiebres (an item
--   often stops selling precisely because it hit zero). It does NOT fall back to
--   "every article in every sucursal": a zero-stock article a sucursal has NEVER
--   sold in 3 years stays out (that is the ~10k-row noise band).
--     * stock > 0, sales this month  -> colored by coverage (ROJO/AMARILLO/VERDE)
--     * stock = 0 (any/no sales)     -> hard quiebre -> ROJO (0 dias de alcance)
--     * stock > 0, NO sales          -> dormant stock -> VERDE (no quiebre risk)
--     * stock = 0, never sold here   -> not this sucursal's assortment -> excluded
--   venta_mes is LEFT-joined onto stock_hoy (COALESCE 0) so dormant stock and
--   zero-demand quiebres both survive. No FULL OUTER JOIN needed: a selling
--   article always has a (possibly zero) stock_hoy row.
-- =============================================================================

-- Step 1: Drop the materialized view if it already exists (idempotent re-run)
DROP MATERIALIZED VIEW IF EXISTS gold.mv_stock_quiebre CASCADE;

-- Step 2: Create the materialized view
CREATE MATERIALIZED VIEW gold.mv_stock_quiebre AS

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
-- dias: current-month working-day counts (a single row, refresh-date scoped).
--   habiles_transcurridos = working days from the 1st of the month through
--                           CURRENT_DATE inclusive (mirrors NETWORKDAYS.INTL
--                           weekend-code 11 = Sunday-only weekend, + feriados).
--   habiles_mes           = total working days in the full calendar month
--                           (used only to compute tendencia_bultos).
-- ---------------------------------------------------------------------------
dias AS (
    SELECT
        COUNT(*) FILTER (
            WHERE extract(dow FROM gs.d) <> 0   -- exclude Sundays (dow=0); Saturdays count
              AND gs.d NOT IN (SELECT f FROM feriados)
              AND gs.d <= CURRENT_DATE
        ) AS habiles_transcurridos,
        COUNT(*) FILTER (
            WHERE extract(dow FROM gs.d) <> 0
              AND gs.d NOT IN (SELECT f FROM feriados)
        ) AS habiles_mes
    FROM (
        SELECT generate_series(
            date_trunc('month', CURRENT_DATE)::date,
            (date_trunc('month', CURRENT_DATE) + interval '1 month - 1 day')::date,
            interval '1 day'
        )::date AS d
    ) gs
),

-- ---------------------------------------------------------------------------
-- snap_date: latest fact_stock snapshot date.
-- ---------------------------------------------------------------------------
snap_date AS (
    SELECT MAX(date_stock) AS d FROM gold.fact_stock
),

-- ---------------------------------------------------------------------------
-- stock_hoy: latest snapshot rolled deposito -> sucursal via dim_deposito.id_sucursal
-- (numeric key — id_deposito is globally unique, no composite-key concern here).
-- ---------------------------------------------------------------------------
stock_hoy AS (
    SELECT
        dd.id_sucursal,
        fs.id_articulo,
        SUM(fs.cant_bultos)          AS stock_bultos,
        SUM(fs.cantidad_total_htls)  AS stock_htls
    FROM gold.fact_stock fs
    JOIN gold.dim_deposito dd ON fs.id_deposito = dd.id_deposito
    WHERE fs.date_stock = (SELECT d FROM snap_date)
    GROUP BY dd.id_sucursal, fs.id_articulo
),

-- ---------------------------------------------------------------------------
-- venta_mes: current-calendar-month sales per (id_sucursal, id_articulo).
-- ---------------------------------------------------------------------------
venta_mes AS (
    SELECT
        fv.id_sucursal,
        fv.id_articulo,
        SUM(fv.cantidades_total)     AS venta_bultos,
        SUM(fv.cantidad_total_htls)  AS venta_htls
    FROM gold.fact_ventas fv
    WHERE fv.fecha_comprobante >= date_trunc('month', CURRENT_DATE)::date
      AND fv.fecha_comprobante <  (date_trunc('month', CURRENT_DATE) + interval '1 month')::date
    GROUP BY fv.id_sucursal, fv.id_articulo
),

-- ---------------------------------------------------------------------------
-- articulos_activos: 3-year no-sales exclusion, at ARTICLE level (RF-05).
-- ---------------------------------------------------------------------------
articulos_activos AS (
    SELECT DISTINCT id_articulo
    FROM gold.fact_ventas
    WHERE fecha_comprobante >= (CURRENT_DATE - interval '3 years')::date
),

-- ---------------------------------------------------------------------------
-- pares_activos: (sucursal, articulo) pairs sold in the last 3 years. Defines,
-- per sucursal, the real assortment — so a zero-stock row for a pair the
-- sucursal actually sells surfaces as a quiebre instead of being hidden.
-- ---------------------------------------------------------------------------
pares_activos AS (
    SELECT DISTINCT id_sucursal, id_articulo
    FROM gold.fact_ventas
    WHERE fecha_comprobante >= (CURRENT_DATE - interval '3 years')::date
),

-- ---------------------------------------------------------------------------
-- grano: universe = (sucursal, articulo) pairs where the article is active in
-- the last 3 years (RF-05) AND, per sucursal, either has physical stock today
-- (stock <> 0) OR was sold by that sucursal in the last 3 years (pares_activos —
-- see header note). venta_mes is LEFT-joined + COALESCE'd to 0 so both dormant
-- stock (stock>0, no sales -> VERDE) and zero-demand quiebres (stock=0, no sale
-- this month -> ROJO) surface instead of being dropped.
-- ---------------------------------------------------------------------------
grano AS (
    SELECT
        ds.descripcion       AS sucursal,
        s.id_articulo,
        da.des_articulo,
        da.generico,
        da.marca,
        s.stock_bultos,
        s.stock_htls,
        COALESCE(v.venta_bultos, 0)  AS venta_bultos,
        COALESCE(v.venta_htls, 0)    AS venta_htls,
        d.habiles_transcurridos,
        d.habiles_mes
    FROM stock_hoy s
    LEFT JOIN venta_mes v
        ON  v.id_sucursal = s.id_sucursal
        AND v.id_articulo = s.id_articulo
    JOIN gold.dim_sucursal ds ON ds.id_sucursal = s.id_sucursal
    JOIN gold.dim_articulo da ON da.id_articulo  = s.id_articulo
    CROSS JOIN dias d
    WHERE s.id_articulo IN (SELECT id_articulo FROM articulos_activos)
      AND (
          s.stock_bultos <> 0
          OR EXISTS (
              SELECT 1 FROM pares_activos pa
              WHERE pa.id_sucursal = s.id_sucursal
                AND pa.id_articulo = s.id_articulo
          )
      )
),

-- ---------------------------------------------------------------------------
-- computed: additive numerator/denominator formulas, precomputed once so the
-- final SELECT's estado_semaforo CASE can reference them without repeating
-- the NULLIF-guarded division expression multiple times.
-- ---------------------------------------------------------------------------
computed AS (
    SELECT
        sucursal,
        id_articulo,
        des_articulo,
        generico,
        marca,
        stock_bultos                                                        AS stock_hoy_bultos,
        stock_htls                                                          AS stock_hoy_htls,
        venta_bultos                                                        AS venta_mes_bultos,
        venta_htls                                                          AS venta_mes_htls,
        habiles_transcurridos::numeric                                      AS dias_habiles_transcurridos,
        venta_bultos / NULLIF(habiles_transcurridos, 0)                     AS venta_diaria_bultos,
        (venta_bultos / NULLIF(habiles_transcurridos, 0)) * habiles_mes      AS tendencia_bultos
    FROM grano
)

-- ---------------------------------------------------------------------------
-- Final SELECT: pedido_sugerido (GREATEST floor at 0) + estado_semaforo band.
-- Both are non-linear (cannot be reconstructed from SUM() at Superset query
-- time), so they are precomputed here, per-row, then SUM/COUNT'd in Superset.
-- ---------------------------------------------------------------------------
SELECT
    sucursal,
    id_articulo,
    des_articulo,
    generico,
    marca,
    stock_hoy_bultos,
    stock_hoy_htls,
    venta_mes_bultos,
    venta_mes_htls,
    dias_habiles_transcurridos,
    venta_diaria_bultos,
    tendencia_bultos,
    GREATEST(venta_diaria_bultos * 15 - stock_hoy_bultos, 0)                 AS pedido_sugerido_15d_bultos,
    CASE
        WHEN stock_hoy_bultos <= 0
            THEN 'ROJO'   -- hard quiebre: sin stock = 0 dias de alcance. ALWAYS red,
                          -- regardless of current demand (revised 2026-07-28). This
                          -- MUST precede the "no demand -> VERDE" branch below, or a
                          -- zero-stock article with no sales this month would be
                          -- painted green — the bug this fix removes.
        WHEN venta_diaria_bultos IS NULL OR venta_diaria_bultos <= 0
            THEN 'VERDE'  -- dormant stock (stock>0, no sales) OR net-negative sales
                          -- (returns > sales): inventory on hand, no quiebre risk.
                          -- <= 0 keeps this consistent with the pedido floor
                          -- GREATEST(..., 0); a bare "= 0" would leave net-negative
                          -- velocity dividing into a negative alcance and falsely
                          -- flagging over-stocked articles as ROJO. Only reached when
                          -- stock > 0 (stock <= 0 is caught above).
        WHEN stock_hoy_bultos / venta_diaria_bultos < 15
            THEN 'ROJO'
        WHEN stock_hoy_bultos / venta_diaria_bultos <= 30
            THEN 'AMARILLO'
        ELSE 'VERDE'
    END                                                                     AS estado_semaforo
FROM computed;


-- =============================================================================
-- Step 3: Unique index on the RF-01 grain (required for REFRESH ... CONCURRENTLY)
--
-- Grain: (sucursal, id_articulo). Neither column is nullable in this MV — every
-- row comes from stock_hoy (grouped by id_sucursal, id_articulo — so at most one
-- row per pair; the LEFT JOIN to venta_mes, itself grouped by the same key, never
-- fans out) through dim_sucursal (sucursal always resolves), so no NULLS NOT
-- DISTINCT clause is needed (unlike mv_resumen_mensual's marca key).
-- =============================================================================
CREATE UNIQUE INDEX uix_mv_stock_quiebre_pk
    ON gold.mv_stock_quiebre (sucursal, id_articulo);


-- =============================================================================
-- Step 4: Re-grant read access to Superset roles.
--
-- WHY: DROP MATERIALIZED VIEW ... CASCADE resets all privileges on the object.
-- A daily REFRESH does NOT reset grants, but re-running this DDL script does.
-- These DO blocks are idempotent: if a role does not exist the EXCEPTION handler
-- swallows the error so the script never fails in environments where that role
-- has not been provisioned yet.
--
-- Roles:
--   superset_ro   — live Superset connection ("Medallion (Gold)" database)
--   superset_user — alternative read-only role from scripts/sql/superset_user.sql
-- =============================================================================
DO $$
BEGIN
    GRANT USAGE  ON SCHEMA gold              TO superset_ro;
    GRANT SELECT ON gold.mv_stock_quiebre    TO superset_ro;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

DO $$
BEGIN
    GRANT USAGE  ON SCHEMA gold              TO superset_user;
    GRANT SELECT ON gold.mv_stock_quiebre    TO superset_user;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;
