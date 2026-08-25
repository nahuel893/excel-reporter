"""Domain constants and hard-won data caveats for the Inteligencia Comercial report.

Everything here was measured against the live gold schema, not assumed. The
comments record WHY each value exists, because most of them encode a trap that
already produced a wrong number once.
"""
from __future__ import annotations

SERVICE_SLUG = "inteligencia-comercial"

# ---------------------------------------------------------------------------
# Revenue semantics — the single most important correction in this report
# ---------------------------------------------------------------------------
# Measured on 1,300,117 lines of 2026:
#   facturacion_neta == precio_unitario_bruto * cantidades_total  (93.95% exact)
#   subtotal_neto    == facturacion_neta - descuentos             (99.9963% exact)
# So despite its name, `facturacion_neta` is GROSS at list price and
# `subtotal_neto` is the real net. Treating facturacion_neta as net overstates
# revenue by the whole discount: 10.11% in 2026 ($4.53e9).
# `subtotal_final` is NOT net either — it is tax-inclusive (median ratio 1.322
# vs subtotal_neto) and cannot be converted with a fixed divisor.
COL_BRUTO = "facturacion_neta"
COL_NETO = "subtotal_neto"
COL_DESCUENTO = "descuentos"
# `bonificacion` is a PERCENTAGE RATE, not a peso amount. Never sum it.
COL_BONIF_RATE = "bonificacion"

# ---------------------------------------------------------------------------
# Document types
# ---------------------------------------------------------------------------
DOC_FACTURA = "FCVTA"
DOC_DEVOLUCION = "DVVTA"  # negative amounts
DOC_PRESUPUESTO = "PRVTA"

# ---------------------------------------------------------------------------
# Product universe
# ---------------------------------------------------------------------------
# The 5 CCU genericos. Anything else is not CCU.
GENERICOS_CCU = (
    "CERVEZAS",
    "AGUAS DANONE",
    "VINOS CCU",
    "SIDRAS Y LICORES",
    "PERNOD RICARD",
)

# Genericos that carry unit counts but are not articles of sale: promotional
# material, returnable-container shells, coolers, dispensers, supplies.
# Excluding them is mandatory for any volume metric. Leaving MARKETING in
# produced the single largest false anomaly found during validation: SUCURSAL
# LIBERTADOR on 2026-07-20 showed 13,033 bultos (z=48.9) of which 10,044 were
# MARKETING invoiced at $10.04 in total, against 510 bultos of actual beer.
GENERICOS_NO_VENTA = (
    "MARKETING",
    "MARKETING BRANCA",
    "ENVASES CCU",
    "ENVASES GASEOSAS",
    "ENVASES PALAU",
    "EQUIPOS DE FRIO",
    "DISPENSER",
    "INSUMOS",
)

# ---------------------------------------------------------------------------
# Client universe
# ---------------------------------------------------------------------------
# Counter-sale buckets, not clients — essentially one per branch. The largest
# (70001, PERICO) invoices 12,048 times in two years and would top every
# frequency ranking, dragging the RFM quintile cutoffs for the whole base.
#
# IDENTIFICATION RULE (both conditions must hold; regenerate with it, do not
# hand-edit): razon_social IS the fiscal condition ("CONSUMIDOR FINAL" /
# "MOSTRADOR", ignoring punctuation) AND fantasia is empty or the same string.
#   - Filtering on fantasia alone misses 70001, 100004, 140001 and 61081, whose
#     fantasia is blank. That single omission left the #1 client of the entire
#     base ($1.84e9 net) inside the RFM population.
#   - Filtering on razon_social alone wrongly swallows ~12k real clients whose
#     legal-name field simply carries the fiscal condition, e.g. 100908
#     "RIOS FERNANDO MAYORISTA" and 112200 "HUMAHUACA MYM".
# Flagged, never deleted, so revenue still reconciles against the totals.
CLIENTES_MOSTRADOR = (
    100, 20002, 20518, 20833, 20834, 20835, 20855, 20920, 30887, 40001,
    50001, 51359, 61081, 70001, 72841, 73938, 80001, 80879, 90844, 100004,
    113217, 130383, 140001, 140845, 200289, 201636, 201637, 201638, 201639, 201640,
    201642, 201643, 201644, 201645, 201646, 201647, 201648, 201649, 201650, 201651,
    201652, 201653, 201654, 201655, 201656, 201657, 201658, 201736, 201747, 201852,
    202300, 202329, 202401, 202438, 203217, 203560, 203741, 205620, 208188, 208189,
)

# dim_cliente.anulado is NOT a reliable active/inactive flag: 621 clients marked
# anulado=true still transacted $717.7M in the last 6 months. Every analysis
# here defines "active" by observed sales activity instead.
USAR_ANULADO_COMO_FILTRO = False

# ---------------------------------------------------------------------------
# Network history — cohort analysis needs this guard
# ---------------------------------------------------------------------------
# fact_ventas only contains CASA CENTRAL before 2023-06-16; the other 13
# sucursales were onboarded in a burst between 2023-06-16 and 2024-06-12.
# A cohort built from 2022 would read that ETL onboarding as a customer
# acquisition wave. Cohorts therefore start after the network is complete.
FECHA_RED_COMPLETA = "2024-07-01"

# SUCURSAL ABRA PAMPA stopped operating: last invoice 2026-05-04, and the ramp
# down is unmistakable (mar 2,779 bultos / apr 3,106 / may 133 with 24 clients
# / then nothing). Its 125 clients read as 100% churned, which is a closure and
# not a commercial failure. Surfaced explicitly so nobody actions the list.
SUCURSALES_CERRADAS = {
    "SUCURSAL ABRA PAMPA": "2026-05-04",
}

# ---------------------------------------------------------------------------
# Table coverage — do not present these side by side as if contemporaneous
# ---------------------------------------------------------------------------
# fact_ventas             : 2022-01-03 .. current
# fact_ventas_contabilidad: 2022-01-03 .. 2026-05-05  (accounting ETL ~3m stale)
# fact_stock              : 2026-02-15 .. current     (no history before that)
# fact_precio_*, dim_lista_precio: EMPTY (0 rows)
FECHA_CORTE_CONTABILIDAD = "2026-05-05"
FECHA_INICIO_STOCK = "2026-02-15"

# ---------------------------------------------------------------------------
# Analysis parameters
# ---------------------------------------------------------------------------
RFM_BINS = 5
# Minimum distinct purchase days in 24m for a client's own p90 gap to mean
# anything. Below this the churn test is noise; those clients are handled by
# the RFM "Nuevos / Ocasionales" segment instead.
CHURN_MIN_COMPRAS = 4
# A client 1-3x past their own p90 gap is recoverable; beyond 3x they are gone.
CHURN_RATIO_RECUPERABLE = 3.0

# ABC on cumulative revenue share; XYZ on coefficient of variation of monthly demand.
ABC_CORTES = (0.80, 0.95)
XYZ_CORTES = (0.50, 1.00)

# Market basket. Invoices never mix fuerza de ventas (verified on 369,049 of
# 369,049 invoices), so any rule spanning preventa (FV1) and autoventa (FV4) is
# an artifact of route structure, not consumer behaviour. Rules are therefore
# computed within a single fuerza de ventas.
BASKET_MIN_SOPORTE = 0.01
BASKET_MIN_LIFT = 1.05
BASKET_MAX_ITEMS = 40

# Seasonality / forecasting
PERIODO_ESTACIONAL = 12
HORIZONTE_PRONOSTICO = 6
# Holt-Winters is NOT shipped blindly. On a rolling-origin backtest it loses to
# a seasonal-naive baseline on the three largest series (CERVEZAS 10.3% vs 9.3%
# MAPE, FRATELLI B 11.2% vs 8.9%, AGUAS DANONE 21.2% vs 10.9%) and only earns
# its keep where the naive baseline collapses (VINOS 16.1% vs 64.2%). The
# report backtests both and reports the winner per series.
BACKTEST_MESES = 12

# SPC. Raw bultos is a broken detector: the lower control limit falls below zero
# at all 14 sucursales, so 243 of 244 breaches are upper-tail and the low side
# is structurally unreachable. A log transform makes the band multiplicative and
# two-sided, and Sundays must be excluded because there is no delivery.
SPC_SIGMAS = 3.0
SPC_USAR_LOG = True

# Stock. Days of cover = stock / average daily sales velocity.
COBERTURA_QUIEBRE_DIAS = 7
COBERTURA_SOBRESTOCK_DIAS = 90

# ---------------------------------------------------------------------------
# RFM segment rules, evaluated in order; FIRST MATCH WINS, so they are ordered
# from most specific to most general.
# (min_r, max_r, min_f, max_f, label, action)
#
# Ordering is not cosmetic. An earlier version listed "Leales" as R2-5 x F3-5
# before the narrower rules, which swallowed "No perder", "Nuevos" and
# "Necesitan atencion" entirely: three segments came back with zero clients and
# the highest-priority call list in the whole model silently disappeared.
# The rules below tile all 25 (R,F) cells exactly once — the test suite asserts
# both full coverage and that every segment is reachable.
# ---------------------------------------------------------------------------
SEGMENTOS_RFM: tuple[tuple[int, int, int, int, str, str], ...] = (
    (4, 5, 4, 5, "Campeones", "Sostener. Reconocimiento y acceso prioritario a novedades."),
    # Antes que Leales: compraban mucho y ya se estan yendo. Es la lista de llamados.
    (2, 3, 4, 5, "No perder", "PRIORIDAD MAXIMA: alto valor ya derivando. Llamar esta semana."),
    (3, 5, 3, 5, "Leales", "Aumentar ticket: cross-sell de genericos con brecha vs sus pares."),
    (5, 5, 1, 2, "Nuevos", "Onboarding. Asegurar la segunda y tercera compra."),
    (4, 4, 1, 3, "Prometedores", "Aumentar frecuencia. Son recientes pero compran poco."),
    (3, 3, 1, 3, "Necesitan atencion", "Contacto proactivo antes de que caigan a En riesgo."),
    (2, 2, 1, 3, "En riesgo", "Reactivacion con oferta puntual."),
    (1, 1, 3, 5, "Hibernando", "Eran valiosos. Campana de recuperacion dirigida."),
    (1, 1, 1, 2, "Perdidos", "Bajo costo de recupero. No asignar tiempo de preventa."),
)

SEGMENTO_COLORES = {
    "Campeones": "1E7B4F",
    "Leales": "2E8B57",
    "Prometedores": "63BE7B",
    "Nuevos": "9ACD8A",
    "Necesitan atencion": "B8860B",
    "No perder": "B3261E",
    "En riesgo": "D2691E",
    "Hibernando": "8B7355",
    "Perdidos": "6B7280",
}
