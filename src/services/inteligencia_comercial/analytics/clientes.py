"""Base de clientes: RFM, fuga, cohortes, puente de crecimiento y concentracion.

Este modulo responde una sola pregunta comercial: *que esta pasando con la base
de clientes de BADIE y donde conviene poner el tiempo del preventista*.

Cinco lecturas, cada una con su tabla:

* ``rfm``           — quien es cada cliente hoy (recencia / frecuencia / monto).
* ``rfm_resumen``   — cuanto pesa cada segmento y que accion le corresponde.
* ``fuga``          — quien esta atrasado **respecto de su propio ritmo**, no de
  un umbral fijo: la base compra entre cada 2 y cada 500 dias, asi que una regla
  unica de "60 dias sin comprar" no detecta nada util.
* ``cohortes``      — cuanto dura un cliente nuevo.
* ``puente``        — de donde salio (o se fue) el crecimiento, en hectolitros
  primero y en pesos despues.
* ``concentracion`` — cuanto depende la empresa de pocos clientes y pocos SKUs.

Reglas de negocio que este archivo respeta y que ya costaron un numero mal una vez:

1. ``facturacion_neta`` es BRUTO a precio de lista; el neto real es
   ``subtotal_neto`` (= bruto - descuentos). Toda columna de pesos aclara si es
   "Bruto", "Neto" o "Descuento".
2. Nada se redondea ni se trunca: el formato es responsabilidad de Excel.
3. La inflacion argentina hace que los pesos NO sean comparables entre periodos:
   todo lo que cruza ventanas se mide en hectolitros; los pesos van como lectura
   secundaria y siempre etiquetados como nominales.
4. Se excluyen los genericos que no son articulos de venta (marketing, envases,
   equipos de frio, insumos) de todas las medidas.
5. Los clientes mostrador se MARCAN, no se borran, para que la facturacion siga
   reconciliando contra los totales de la empresa.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.services.inteligencia_comercial import constants
from src.services.inteligencia_comercial import stats
from src.services.inteligencia_comercial.contracts import (
    Alert,
    AnalysisContext,
    AnalysisResult,
    Headline,
)

NOMBRE = "Base de clientes"

# Etiqueta unica para la fila de cierre de cada tabla. Es un requisito del
# equipo comercial: ningun informe se entrega sin totalizar.
TOTAL_GENERAL = "TOTAL GENERAL"

# Buckets del puente de crecimiento, en el orden en que se leen.
BUCKETS_PUENTE = ("Nuevos", "Reactivados", "Perdidos", "Upsell", "Downsell")

# Cuantiles de la cola derecha que se reportan en la tabla de concentracion.
TOPS_CONCENTRACION = (1, 5, 10, 20, 50, 100)


# ---------------------------------------------------------------------------
# Helpers SQL
# ---------------------------------------------------------------------------


def _lista_sql(valores) -> str:
    """Arma una lista de literales SQL a partir de constantes del dominio."""
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in valores)


def _filtro_articulos_venta(alias: str = "da") -> str:
    """Excluye genericos que no son articulos de venta.

    Marketing, envases, equipos de frio e insumos llevan unidades pero no son
    una venta: dejarlos adentro ya produjo la mayor anomalia falsa del proyecto
    (10.044 bultos de MARKETING facturados a $10 en total).
    """
    return (
        f"AND ({alias}.generico IS NULL OR {alias}.generico NOT IN "
        f"({_lista_sql(constants.GENERICOS_NO_VENTA)}))"
    )


def _filtro_comprobantes_venta(alias: str = "fv") -> str:
    """Deja solo facturas y devoluciones. Un PRESUPUESTO no es una venta.

    ``fact_ventas`` guarda tambien PRVTA (presupuestos). Parecen inofensivos por
    la cantidad -- 97 lineas en los 12 meses a 2026-07-30 contra 2,16 millones de
    facturas -- pero arrastran $ 1.758.094.000 de neto y 4.440 htl repartidos en
    apenas 4 clientes: uno de ellos (id 207600, con la razon social en blanco)
    cargo 1.745 htl en un unico dia, casi el doble del volumen diario de TODA la
    empresa. Contarlos como venta inflaba el crecimiento real en hectolitros de
    9,5% a 10,6% y metia clientes fantasma en el top del ranking.

    Se enumeran los tipos validos en vez de excluir PRVTA para que un tipo de
    comprobante nuevo en el ETL no entre solo al informe.
    """
    return (
        f"AND {alias}.id_documento IN "
        f"('{constants.DOC_FACTURA}', '{constants.DOC_DEVOLUCION}')"
    )


def _iso(valor: str) -> str:
    """Valida que una fecha sea ISO antes de interpolarla en el SQL."""
    return date.fromisoformat(str(valor)).isoformat()


def _ventanas(ctx: AnalysisContext) -> dict[str, str]:
    """Ventanas movil actual y anterior, sin solapamiento y de igual duracion.

    Se define ``actual = (desde_12, hasta]``. La ventana previa NO puede salir de
    ``ctx.desde(24)``: como ``AnalysisContext.desde`` recorta el dia a 28, con
    ``fecha_hasta = 2026-07-30`` la actual queda de 367 dias y la de 24 meses
    daria una previa de 365. Comparar 367 dias contra 365 regala medio punto de
    crecimiento inventado (~2.100 htl), justo el tipo de error que este informe
    existe para evitar. Por eso ``desde_previo`` se calcula restando a
    ``desde_12`` exactamente los mismos dias que dura la ventana actual.

    ``desde_24`` se mantiene aparte porque el perfil de ritmo de compra de la
    tabla de fuga si quiere 24 meses calendario, no una ventana espejo.
    """
    hasta = _iso(ctx.fecha_hasta)
    desde_12 = _iso(ctx.desde(ctx.meses_ventana))
    desde_24 = _iso(ctx.desde(ctx.meses_historia))
    dias_ventana = (date.fromisoformat(hasta) - date.fromisoformat(desde_12)).days
    desde_previo = (
        date.fromisoformat(desde_12) - timedelta(days=dias_ventana)
    ).isoformat()
    return {
        "hasta": hasta,
        "desde_12": desde_12,
        "desde_24": desde_24,
        "desde_previo": desde_previo,
        "dias_ventana": str(dias_ventana),
    }


# ---------------------------------------------------------------------------
# SQL — solo lectura
# ---------------------------------------------------------------------------


def sql_rfm(desde_12: str, hasta: str) -> str:
    """Una fila por cliente activo en los ultimos 12 meses.

    ``frecuencia`` cuenta solo facturas (FCVTA): una devolucion no es una
    compra. Los montos, en cambio, incluyen devoluciones para que el neto del
    cliente sea el neto real que dejo en la empresa. Los presupuestos (PRVTA)
    quedan afuera de todo: no son plata cobrada ni producto entregado.
    """
    return f"""
WITH base AS (
    SELECT fv.id_cliente,
           fv.fecha_comprobante,
           fv.id_documento, fv.letra, fv.serie, fv.nro_doc, fv.id_sucursal,
           fv.subtotal_neto,
           fv.facturacion_neta,
           fv.descuentos,
           fv.cantidad_total_htls,
           fv.cantidades_total
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
    WHERE fv.anulado = false
      AND fv.fecha_comprobante >  DATE '{desde_12}'
      AND fv.fecha_comprobante <= DATE '{hasta}'
      {_filtro_comprobantes_venta()}
      {_filtro_articulos_venta()}
),
agg AS (
    SELECT id_cliente,
           MAX(fecha_comprobante) FILTER (WHERE id_documento = '{constants.DOC_FACTURA}')
               AS ultima_compra,
           COUNT(DISTINCT (id_documento, letra, serie, nro_doc, id_sucursal))
               FILTER (WHERE id_documento = '{constants.DOC_FACTURA}')   AS frecuencia,
           COUNT(DISTINCT fecha_comprobante)
               FILTER (WHERE id_documento = '{constants.DOC_FACTURA}')   AS dias_compra,
           COUNT(DISTINCT date_trunc('month', fecha_comprobante))
               FILTER (WHERE id_documento = '{constants.DOC_FACTURA}')   AS meses_activos,
           SUM(subtotal_neto)       AS monetario_neto,
           SUM(facturacion_neta)    AS monetario_bruto,
           SUM(descuentos)          AS descuento,
           SUM(cantidad_total_htls) AS htls,
           SUM(cantidades_total)    AS bultos
    FROM base
    GROUP BY id_cliente
)
SELECT a.id_cliente,
       COALESCE(NULLIF(TRIM(dc.fantasia), ''), dc.razon_social, 'SIN NOMBRE') AS cliente,
       (DATE '{hasta}' - a.ultima_compra) AS recencia_dias,
       a.frecuencia,
       a.dias_compra,
       a.meses_activos,
       a.monetario_neto,
       a.monetario_bruto,
       a.descuento,
       a.htls,
       a.bultos,
       COALESCE(ds.descripcion, 'SIN SUCURSAL')      AS sucursal,
       COALESCE(dc.des_canal_mkt, 'SIN CANAL')       AS canal,
       COALESCE(dc.des_subcanal_mkt, 'SIN SUBCANAL') AS subcanal,
       COALESCE(dc.des_ramo, 'SIN RAMO')             AS ramo,
       COALESCE(dc.des_localidad, 'SIN LOCALIDAD')   AS localidad,
       COALESCE(dc.des_personal_fv1, 'SIN ASIGNAR')  AS preventista
FROM agg a
LEFT JOIN gold.dim_cliente  dc ON dc.id_cliente  = a.id_cliente
LEFT JOIN gold.dim_sucursal ds ON ds.id_sucursal = dc.id_sucursal
WHERE a.ultima_compra IS NOT NULL
"""


def sql_fuga(desde_12: str, desde_24: str, hasta: str) -> str:
    """Ritmo de compra propio de cada cliente sobre 24 meses.

    El p90 empirico de los intervalos entre compras ES el umbral de alarma: no
    hace falta un modelo de supervivencia para decir "este cliente ya paso el
    90% de sus propias esperas historicas".
    """
    return f"""
WITH dias AS (
    SELECT DISTINCT fv.id_cliente, fv.fecha_comprobante
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
    WHERE fv.anulado = false
      AND fv.id_documento = '{constants.DOC_FACTURA}'
      AND fv.fecha_comprobante >  DATE '{desde_24}'
      AND fv.fecha_comprobante <= DATE '{hasta}'
      {_filtro_articulos_venta()}
),
gaps AS (
    SELECT id_cliente,
           (fecha_comprobante - LAG(fecha_comprobante)
                OVER (PARTITION BY id_cliente ORDER BY fecha_comprobante)) AS gap_dias
    FROM dias
),
perfil AS (
    SELECT id_cliente,
           COUNT(*)                                              AS dias_compra_24m,
           AVG(gap_dias)                                         AS gap_medio,
           STDDEV_SAMP(gap_dias)                                 AS gap_desvio,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY gap_dias) AS gap_p50,
           PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY gap_dias) AS gap_p90,
           MAX(gap_dias)                                         AS gap_max
    FROM gaps
    GROUP BY id_cliente
),
ultima AS (
    SELECT id_cliente, MAX(fecha_comprobante) AS ultima_compra
    FROM dias GROUP BY id_cliente
),
neto12 AS (
    SELECT fv.id_cliente, SUM(fv.subtotal_neto) AS neto_12m
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
    WHERE fv.anulado = false
      AND fv.fecha_comprobante >  DATE '{desde_12}'
      AND fv.fecha_comprobante <= DATE '{hasta}'
      {_filtro_comprobantes_venta()}
      {_filtro_articulos_venta()}
    GROUP BY fv.id_cliente
)
SELECT p.id_cliente,
       COALESCE(NULLIF(TRIM(dc.fantasia), ''), dc.razon_social, 'SIN NOMBRE') AS cliente,
       p.dias_compra_24m,
       (DATE '{hasta}' - u.ultima_compra) AS recencia_dias,
       p.gap_medio,
       p.gap_desvio,
       p.gap_p50,
       p.gap_p90,
       p.gap_max,
       COALESCE(n.neto_12m, 0) AS neto_12m,
       COALESCE(ds.descripcion, 'SIN SUCURSAL')     AS sucursal,
       COALESCE(dc.des_canal_mkt, 'SIN CANAL')      AS canal,
       COALESCE(dc.des_ramo, 'SIN RAMO')            AS ramo,
       COALESCE(dc.des_localidad, 'SIN LOCALIDAD')  AS localidad,
       COALESCE(dc.des_personal_fv1, 'SIN ASIGNAR') AS preventista
FROM perfil p
JOIN ultima u USING (id_cliente)
LEFT JOIN neto12 n           ON n.id_cliente  = p.id_cliente
LEFT JOIN gold.dim_cliente  dc ON dc.id_cliente = p.id_cliente
LEFT JOIN gold.dim_sucursal ds ON ds.id_sucursal = dc.id_sucursal
WHERE p.dias_compra_24m >= {int(constants.CHURN_MIN_COMPRAS)}
"""


def sql_cohortes(hasta: str, desde_cohorte: str) -> str:
    """Lista de aristas (mes de cohorte, mes N, clientes) para la matriz.

    El mes de cohorte se calcula sobre TODA la historia disponible, pero solo se
    conservan las cohortes posteriores a ``FECHA_RED_COMPLETA``: antes de esa
    fecha fact_ventas todavia estaba incorporando sucursales y el alta del ETL
    se lee como una ola de captacion de clientes que nunca existio.
    """
    return f"""
WITH act AS (
    SELECT fv.id_cliente,
           date_trunc('month', fv.fecha_comprobante)::date AS mes,
           SUM(fv.subtotal_neto) AS neto
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
    WHERE fv.anulado = false
      AND fv.id_documento = '{constants.DOC_FACTURA}'
      AND fv.fecha_comprobante <= DATE '{hasta}'
      {_filtro_articulos_venta()}
    GROUP BY 1, 2
),
cohorte AS (
    SELECT id_cliente, MIN(mes) AS mes_cohorte
    FROM act
    GROUP BY id_cliente
)
SELECT c.mes_cohorte,
       (EXTRACT(YEAR  FROM AGE(a.mes, c.mes_cohorte)) * 12
      + EXTRACT(MONTH FROM AGE(a.mes, c.mes_cohorte)))::int AS mes_n,
       COUNT(DISTINCT a.id_cliente) AS clientes,
       SUM(a.neto)                  AS neto
FROM act a
JOIN cohorte c USING (id_cliente)
WHERE c.mes_cohorte >= DATE '{desde_cohorte}'
GROUP BY 1, 2
ORDER BY 1, 2
"""


def sql_puente(desde_12: str, desde_previo: str, hasta: str) -> str:
    """Volumen y neto de cada cliente en la ventana actual y en la anterior.

    ``desde_previo`` es el arranque de la ventana espejo (misma cantidad de dias
    que la actual), no el de 24 meses: comparar 367 dias contra 365 inventa
    crecimiento. ``lineas_historicas`` cuenta comprobantes anteriores a la
    ventana previa y es lo unico que distingue un cliente Nuevo de uno
    Reactivado. Presupuestos (PRVTA) afuera: no son venta.
    """
    return f"""
WITH v AS (
    SELECT fv.id_cliente,
           SUM(fv.subtotal_neto) FILTER (
             WHERE fv.fecha_comprobante >  DATE '{desde_12}'
               AND fv.fecha_comprobante <= DATE '{hasta}')        AS neto_actual,
           SUM(fv.subtotal_neto) FILTER (
             WHERE fv.fecha_comprobante >  DATE '{desde_previo}'
               AND fv.fecha_comprobante <= DATE '{desde_12}')     AS neto_previo,
           SUM(fv.facturacion_neta) FILTER (
             WHERE fv.fecha_comprobante >  DATE '{desde_12}'
               AND fv.fecha_comprobante <= DATE '{hasta}')        AS bruto_actual,
           SUM(fv.facturacion_neta) FILTER (
             WHERE fv.fecha_comprobante >  DATE '{desde_previo}'
               AND fv.fecha_comprobante <= DATE '{desde_12}')     AS bruto_previo,
           SUM(fv.cantidad_total_htls) FILTER (
             WHERE fv.fecha_comprobante >  DATE '{desde_12}'
               AND fv.fecha_comprobante <= DATE '{hasta}')        AS htls_actual,
           SUM(fv.cantidad_total_htls) FILTER (
             WHERE fv.fecha_comprobante >  DATE '{desde_previo}'
               AND fv.fecha_comprobante <= DATE '{desde_12}')     AS htls_previo,
           COUNT(*) FILTER (
             WHERE fv.fecha_comprobante <= DATE '{desde_previo}') AS lineas_historicas
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
    WHERE fv.anulado = false
      AND fv.fecha_comprobante <= DATE '{hasta}'
      {_filtro_comprobantes_venta()}
      {_filtro_articulos_venta()}
    GROUP BY fv.id_cliente
)
SELECT v.id_cliente,
       COALESCE(NULLIF(TRIM(dc.fantasia), ''), dc.razon_social, 'SIN NOMBRE') AS cliente,
       COALESCE(v.neto_actual,  0)  AS neto_actual,
       COALESCE(v.neto_previo,  0)  AS neto_previo,
       COALESCE(v.bruto_actual, 0)  AS bruto_actual,
       COALESCE(v.bruto_previo, 0)  AS bruto_previo,
       COALESCE(v.htls_actual,  0)  AS htls_actual,
       COALESCE(v.htls_previo,  0)  AS htls_previo,
       v.lineas_historicas,
       COALESCE(ds.descripcion, 'SIN SUCURSAL')     AS sucursal,
       COALESCE(dc.des_personal_fv1, 'SIN ASIGNAR') AS preventista
FROM v
LEFT JOIN gold.dim_cliente  dc ON dc.id_cliente  = v.id_cliente
LEFT JOIN gold.dim_sucursal ds ON ds.id_sucursal = dc.id_sucursal
WHERE COALESCE(v.neto_actual, 0) <> 0
   OR COALESCE(v.neto_previo, 0) <> 0
   OR COALESCE(v.htls_actual, 0) <> 0
   OR COALESCE(v.htls_previo, 0) <> 0
"""


def sql_articulos(desde_12: str, hasta: str) -> str:
    """Neto, bruto, descuento, volumen y alcance de cada SKU vendido en 12 meses.

    Mismo universo de comprobantes que el RFM (facturas y devoluciones, sin
    presupuestos) para que el neto por articulo y el neto por cliente se puedan
    contrastar y la diferencia signifique algo.
    """
    return f"""
SELECT fv.id_articulo,
       COALESCE(da.des_articulo, 'SIN DESCRIPCION') AS articulo,
       COALESCE(da.generico, 'SIN GENERICO')        AS generico,
       COALESCE(da.marca, 'SIN MARCA')              AS marca,
       COALESCE(da.proveedor, 'SIN PROVEEDOR')      AS proveedor,
       SUM(fv.subtotal_neto)         AS neto,
       SUM(fv.facturacion_neta)      AS bruto,
       SUM(fv.descuentos)            AS descuento,
       SUM(fv.cantidad_total_htls)   AS htls,
       SUM(fv.cantidades_total)      AS bultos,
       COUNT(DISTINCT fv.id_cliente) AS clientes
FROM gold.fact_ventas fv
LEFT JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
WHERE fv.anulado = false
  AND fv.fecha_comprobante >  DATE '{desde_12}'
  AND fv.fecha_comprobante <= DATE '{hasta}'
  {_filtro_comprobantes_venta()}
  {_filtro_articulos_venta()}
GROUP BY 1, 2, 3, 4, 5
"""


# ---------------------------------------------------------------------------
# Transformaciones puras — todas testeables sin base de datos
# ---------------------------------------------------------------------------


def _fila_total_vacia(df: pd.DataFrame) -> dict:
    """Esqueleto de la fila TOTAL GENERAL con el tipo correcto en cada columna.

    Poner "" en una columna de medida la convierte a texto para todo el
    DataFrame, y el escritor de Excel deja de poder alinearla o formatearla como
    numero. Las columnas numericas van con NaN (el escritor lo traduce a celda
    vacia) y las de texto con cadena vacia.
    """
    fila: dict = {}
    for col in df.columns:
        serie = df[col]
        if pd.api.types.is_bool_dtype(serie) or not pd.api.types.is_numeric_dtype(serie):
            fila[col] = ""
        else:
            fila[col] = np.nan
    return fila


def _numerico(df: pd.DataFrame, columnas) -> pd.DataFrame:
    """Fuerza a float las columnas de medida (psycopg2 devuelve Decimal)."""
    salida = df.copy()
    for col in columnas:
        if col in salida.columns:
            salida[col] = pd.to_numeric(salida[col], errors="coerce").fillna(0.0)
    return salida


def asignar_segmento(score_r: int, score_f: int) -> tuple[str, str]:
    """Aplica ``SEGMENTOS_RFM`` con la regla "gana la primera coincidencia".

    Devuelve (segmento, accion). Si ningun rango cubre el par, el cliente queda
    como "Sin clasificar" en lugar de romper el informe.
    """
    for min_r, max_r, min_f, max_f, etiqueta, accion in constants.SEGMENTOS_RFM:
        if min_r <= score_r <= max_r and min_f <= score_f <= max_f:
            return etiqueta, accion
    return "Sin clasificar", "Revisar reglas de segmentacion."


def calcular_rfm(df: pd.DataFrame) -> pd.DataFrame:
    """Puntua la base y le pega segmento, accion y marca de mostrador.

    La recencia se puntua al reves (``ascending=False``): comprar hace 1 dia
    vale 5 y comprar hace 300 dias vale 1.
    """
    if df.empty:
        return pd.DataFrame()

    out = _numerico(
        df,
        ["recencia_dias", "frecuencia", "dias_compra", "meses_activos",
         "monetario_neto", "monetario_bruto", "descuento", "htls", "bultos"],
    )

    out["score_r"] = stats.quantile_score(
        out["recencia_dias"], bins=constants.RFM_BINS, ascending=False
    ).astype(int)
    out["score_f"] = stats.quantile_score(
        out["frecuencia"], bins=constants.RFM_BINS, ascending=True
    ).astype(int)
    out["score_m"] = stats.quantile_score(
        out["monetario_neto"], bins=constants.RFM_BINS, ascending=True
    ).astype(int)

    out["celda_rfm"] = (
        out["score_r"].astype(str) + out["score_f"].astype(str) + out["score_m"].astype(str)
    )
    segmentos = [asignar_segmento(r, f) for r, f in zip(out["score_r"], out["score_f"])]
    out["segmento"] = [s for s, _ in segmentos]
    out["accion"] = [a for _, a in segmentos]

    out["es_mostrador"] = out["id_cliente"].isin(constants.CLIENTES_MOSTRADOR)
    return out.sort_values("monetario_neto", ascending=False).reset_index(drop=True)


def resumir_rfm(df_rfm: pd.DataFrame) -> pd.DataFrame:
    """Cuanto pesa cada segmento: clientes, neto, ticket, recencia y frecuencia."""
    if df_rfm.empty:
        return pd.DataFrame()

    total_clientes = float(len(df_rfm))
    total_neto = float(df_rfm["monetario_neto"].sum())

    grupos = df_rfm.groupby("segmento", dropna=False)
    resumen = pd.DataFrame(
        {
            "Clientes": grupos["id_cliente"].count(),
            "Neto (12m)": grupos["monetario_neto"].sum(),
            "Bruto (12m)": grupos["monetario_bruto"].sum(),
            "Descuento (12m)": grupos["descuento"].sum(),
            "Recencia mediana (dias)": grupos["recencia_dias"].median(),
            "Frecuencia mediana": grupos["frecuencia"].median(),
        }
    ).reset_index()
    resumen = resumen.rename(columns={"segmento": "Segmento"})

    resumen["% Clientes"] = resumen["Clientes"] / total_clientes if total_clientes else np.nan
    resumen["% Neto"] = resumen["Neto (12m)"] / total_neto if total_neto else np.nan
    # Ticket medio = neto del segmento sobre sus clientes. No es el ticket por
    # comprobante: es lo que deja al ano un cliente promedio del segmento.
    resumen["Ticket medio neto"] = resumen["Neto (12m)"] / resumen["Clientes"]

    acciones = {
        etiqueta: accion for _, _, _, _, etiqueta, accion in constants.SEGMENTOS_RFM
    }
    resumen["Accion"] = resumen["Segmento"].map(acciones).fillna("Revisar reglas de segmentacion.")

    resumen = resumen.sort_values("Neto (12m)", ascending=False).reset_index(drop=True)

    total = {
        "Segmento": TOTAL_GENERAL,
        "Clientes": resumen["Clientes"].sum(),
        "Neto (12m)": resumen["Neto (12m)"].sum(),
        "Bruto (12m)": resumen["Bruto (12m)"].sum(),
        "Descuento (12m)": resumen["Descuento (12m)"].sum(),
        "Recencia mediana (dias)": df_rfm["recencia_dias"].median(),
        "Frecuencia mediana": df_rfm["frecuencia"].median(),
        "% Clientes": 1.0,
        "% Neto": 1.0,
        "Ticket medio neto": (
            float(resumen["Neto (12m)"].sum()) / float(resumen["Clientes"].sum())
            if resumen["Clientes"].sum()
            else np.nan
        ),
        "Accion": "",
    }
    resumen = pd.concat([resumen, pd.DataFrame([total])], ignore_index=True)

    columnas = [
        "Segmento", "Clientes", "% Clientes", "Neto (12m)", "% Neto",
        "Ticket medio neto", "Recencia mediana (dias)", "Frecuencia mediana",
        "Bruto (12m)", "Descuento (12m)", "Accion",
    ]
    return resumen[columnas]


def clasificar_estado_fuga(recencia: float, gap_p90: float, ratio_corte: float) -> str:
    """Traduce el atraso relativo en una decision.

    Dentro del propio p90 -> "Al dia". Hasta ``ratio_corte`` veces ese p90 el
    cliente todavia se recupera con una llamada. Mas alla ya se fue.
    """
    if not np.isfinite(recencia) or not np.isfinite(gap_p90) or gap_p90 <= 0:
        return "Sin ritmo medible"
    if recencia <= gap_p90:
        return "Al dia"
    if recencia / gap_p90 <= ratio_corte:
        return "Recuperable"
    return "Perdido"


def calcular_fuga(df: pd.DataFrame) -> pd.DataFrame:
    """Marca atraso, severidad y regularidad de ritmo de cada cliente.

    ``accionable`` es False para las sucursales cerradas y para los clientes
    mostrador: la lista que se entrega al preventista tiene que poder llamarse
    por telefono.
    """
    if df.empty:
        return pd.DataFrame()

    out = _numerico(
        df,
        ["dias_compra_24m", "recencia_dias", "gap_medio", "gap_desvio",
         "gap_p50", "gap_p90", "gap_max", "neto_12m"],
    )

    out["exceso_dias"] = out["recencia_dias"] - out["gap_p90"]
    with np.errstate(divide="ignore", invalid="ignore"):
        out["ratio"] = np.where(out["gap_p90"] > 0, out["recencia_dias"] / out["gap_p90"], np.nan)
        # cv < 0.5 = cliente metronomico (la alarma es casi segura);
        # cv > 1.5 = erratico, conviene suprimir la alarma.
        out["cv_ritmo"] = np.where(
            out["gap_medio"] > 0, out["gap_desvio"] / out["gap_medio"], np.nan
        )

    out["estado"] = [
        clasificar_estado_fuga(r, p, constants.CHURN_RATIO_RECUPERABLE)
        for r, p in zip(out["recencia_dias"], out["gap_p90"])
    ]

    cerradas = set(constants.SUCURSALES_CERRADAS)
    out["sucursal_cerrada"] = out["sucursal"].isin(cerradas)
    out["es_mostrador"] = out["id_cliente"].isin(constants.CLIENTES_MOSTRADOR)
    out["accionable"] = ~out["sucursal_cerrada"] & ~out["es_mostrador"]

    # Primero lo que se puede trabajar hoy, de mayor a menor plata en juego.
    out["_orden"] = np.where(
        out["accionable"] & out["estado"].isin(["Recuperable", "Perdido"]), 0, 1
    )
    out = out.sort_values(
        ["_orden", "neto_12m"], ascending=[True, False]
    ).drop(columns="_orden").reset_index(drop=True)

    return out


def resumir_fuga_total(df_fuga: pd.DataFrame) -> pd.DataFrame:
    """Agrega la fila TOTAL GENERAL al final de la tabla de fuga.

    ``gap_p90`` y ``recencia_dias`` van como MEDIANA, no como suma: sumar dias
    de espera de 16.000 clientes no significa nada. La etiqueta va en ``cliente``
    y esa columna se escribe primera, que es donde el escritor de Excel busca la
    palabra TOTAL para resaltar la fila.
    """
    if df_fuga.empty:
        return df_fuga
    total = _fila_total_vacia(df_fuga)
    total["cliente"] = TOTAL_GENERAL
    total["neto_12m"] = float(df_fuga["neto_12m"].sum())
    total["dias_compra_24m"] = float(df_fuga["dias_compra_24m"].sum())
    total["gap_p90"] = float(df_fuga["gap_p90"].median())
    total["recencia_dias"] = float(df_fuga["recencia_dias"].median())
    total["estado"] = f"{int((df_fuga['estado'] != 'Al dia').sum())} atrasados"
    return pd.concat([df_fuga, pd.DataFrame([total])], ignore_index=True)


def matriz_cohortes(df_edge: pd.DataFrame, hasta: str) -> pd.DataFrame:
    """Matriz de retencion mensual con fila de promedio ponderado por tamano.

    Retencion = % de la cohorte que compro en el mes N exacto. Una cohorte solo
    aparece en la columna N si ya vivio N meses; el resto queda vacio para no
    mezclar "no compro" con "todavia no paso".
    """
    if df_edge.empty:
        return pd.DataFrame()

    df = df_edge.copy()
    df["mes_cohorte"] = pd.to_datetime(df["mes_cohorte"])
    df["mes_n"] = pd.to_numeric(df["mes_n"], errors="coerce").astype(int)
    df["clientes"] = pd.to_numeric(df["clientes"], errors="coerce").fillna(0.0)

    pivot = df.pivot_table(
        index="mes_cohorte", columns="mes_n", values="clientes", aggfunc="sum"
    ).sort_index()

    corte = pd.Timestamp(hasta).to_period("M")
    edades = np.array([(corte - m).n for m in pivot.index.to_period("M")], dtype=float)
    n_max = int(pivot.columns.max())
    pivot = pivot.reindex(columns=range(n_max + 1))

    # Dentro del triangulo observable, ausencia = 0 clientes; fuera, NaN.
    columnas = np.array(pivot.columns, dtype=float)
    observable = pd.DataFrame(
        columnas[None, :] <= edades[:, None], index=pivot.index, columns=pivot.columns
    )
    conteos = pivot.where(observable).fillna(0.0).where(observable)

    tamano = conteos[0]
    retencion = conteos.div(tamano, axis=0)

    salida = pd.DataFrame({"Cohorte": pivot.index.strftime("%Y-%m")})
    salida["Clientes cohorte"] = tamano.values
    for n in retencion.columns:
        salida[f"M{n}"] = retencion[n].values

    # Promedio ponderado por tamano de cohorte, usando en cada N solo las
    # cohortes que ya cumplieron N meses (censura a derecha).
    fila = {"Cohorte": f"{TOTAL_GENERAL} (promedio ponderado)",
            "Clientes cohorte": float(tamano.sum())}
    for n in retencion.columns:
        activos = conteos[n]
        mask = activos.notna()
        base = tamano[mask].sum()
        fila[f"M{n}"] = float(activos[mask].sum() / base) if base else np.nan
    salida = pd.concat([salida, pd.DataFrame([fila])], ignore_index=True)
    return salida


def clasificar_movimiento(
    neto_previo: float, neto_actual: float,
    htls_previo: float, htls_actual: float,
    lineas_historicas: float,
) -> str:
    """Ubica un cliente en el puente de crecimiento.

    La direccion (Upsell/Downsell) se decide por HECTOLITROS, que es la unica
    medida comparable entre periodos con la inflacion argentina. Si el volumen
    no se movio (SKUs sin factor de hectolitros) se desempata con el neto.
    """
    activo_previo = neto_previo != 0 or htls_previo != 0
    activo_actual = neto_actual != 0 or htls_actual != 0

    if not activo_previo and activo_actual:
        return "Nuevos" if float(lineas_historicas or 0) == 0 else "Reactivados"
    if activo_previo and not activo_actual:
        return "Perdidos"
    if not activo_previo and not activo_actual:
        return "Perdidos"

    delta_htls = htls_actual - htls_previo
    delta = delta_htls if delta_htls != 0 else (neto_actual - neto_previo)
    return "Upsell" if delta > 0 else "Downsell"


def construir_puente(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Puente de crecimiento en hectolitros (real) y en pesos netos (nominal).

    Los cinco buckets particionan la base, asi que la suma de los deltas tiene
    que dar exactamente el delta total. Se devuelve la reconciliacion medida.
    """
    if df.empty:
        return pd.DataFrame(), {}

    out = _numerico(
        df,
        ["neto_actual", "neto_previo", "bruto_actual", "bruto_previo",
         "htls_actual", "htls_previo", "lineas_historicas"],
    )
    out["bucket"] = [
        clasificar_movimiento(np_, na, hp, ha, lh)
        for np_, na, hp, ha, lh in zip(
            out["neto_previo"], out["neto_actual"],
            out["htls_previo"], out["htls_actual"], out["lineas_historicas"],
        )
    ]
    out["delta_htls"] = out["htls_actual"] - out["htls_previo"]
    out["delta_neto"] = out["neto_actual"] - out["neto_previo"]

    grupos = out.groupby("bucket")
    tabla = pd.DataFrame(
        {
            "Clientes": grupos["id_cliente"].count(),
            "Htl previo": grupos["htls_previo"].sum(),
            "Htl actual": grupos["htls_actual"].sum(),
            "Delta htl": grupos["delta_htls"].sum(),
            # Los pesos cruzan dos periodos: con la inflacion argentina NO son
            # comparables, van marcados "nominal" en el encabezado para que
            # nadie lea el delta de pesos como crecimiento.
            "Neto previo (nominal)": grupos["neto_previo"].sum(),
            "Neto actual (nominal)": grupos["neto_actual"].sum(),
            "Delta neto (nominal)": grupos["delta_neto"].sum(),
        }
    ).reset_index().rename(columns={"bucket": "Movimiento"})

    orden = {b: i for i, b in enumerate(BUCKETS_PUENTE)}
    tabla["_orden"] = tabla["Movimiento"].map(orden).fillna(len(orden))
    tabla = tabla.sort_values("_orden").drop(columns="_orden").reset_index(drop=True)

    delta_htl_total = float(out["htls_actual"].sum() - out["htls_previo"].sum())
    delta_neto_total = float(out["neto_actual"].sum() - out["neto_previo"].sum())
    tabla["% del delta htl"] = (
        tabla["Delta htl"] / delta_htl_total if delta_htl_total else np.nan
    )
    tabla["% del delta neto"] = (
        tabla["Delta neto (nominal)"] / delta_neto_total if delta_neto_total else np.nan
    )

    total = {
        "Movimiento": TOTAL_GENERAL,
        "Clientes": tabla["Clientes"].sum(),
        "Htl previo": float(out["htls_previo"].sum()),
        "Htl actual": float(out["htls_actual"].sum()),
        "Delta htl": delta_htl_total,
        "Neto previo (nominal)": float(out["neto_previo"].sum()),
        "Neto actual (nominal)": float(out["neto_actual"].sum()),
        "Delta neto (nominal)": delta_neto_total,
        "% del delta htl": 1.0 if delta_htl_total else np.nan,
        "% del delta neto": 1.0 if delta_neto_total else np.nan,
    }
    tabla = pd.concat([tabla, pd.DataFrame([total])], ignore_index=True)

    reconciliacion = {
        "suma_buckets_htl": float(tabla.iloc[:-1]["Delta htl"].sum()),
        "delta_total_htl": delta_htl_total,
        "suma_buckets_neto": float(tabla.iloc[:-1]["Delta neto (nominal)"].sum()),
        "delta_total_neto": delta_neto_total,
        "htl_previo": float(out["htls_previo"].sum()),
        "htl_actual": float(out["htls_actual"].sum()),
        "neto_previo": float(out["neto_previo"].sum()),
        "neto_actual": float(out["neto_actual"].sum()),
    }
    reconciliacion["crecimiento_real_htl"] = (
        reconciliacion["delta_total_htl"] / reconciliacion["htl_previo"]
        if reconciliacion["htl_previo"]
        else np.nan
    )
    reconciliacion["crecimiento_nominal_neto"] = (
        reconciliacion["delta_total_neto"] / reconciliacion["neto_previo"]
        if reconciliacion["neto_previo"]
        else np.nan
    )
    columnas = [
        "Movimiento", "Clientes", "Htl previo", "Htl actual", "Delta htl",
        "% del delta htl", "Neto previo (nominal)", "Neto actual (nominal)",
        "Delta neto (nominal)", "% del delta neto",
    ]
    return tabla[columnas], reconciliacion


def share_top(values, k: int) -> float:
    """Participacion de los k mayores sobre el total (valores negativos a cero)."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    arr = np.clip(arr, 0, None)
    total = arr.sum()
    if arr.size == 0 or total <= 0:
        return float("nan")
    arr = np.sort(arr)[::-1]
    return float(arr[: max(int(k), 0)].sum() / total)


def medir_concentracion(universo: str, medida: str, values) -> dict:
    """Gini, HHI, N efectivo, Pareto 80 y participaciones de cola de una serie."""
    arr = np.asarray(pd.to_numeric(pd.Series(values), errors="coerce"), dtype=float)
    arr = arr[np.isfinite(arr)]
    positivos = arr[arr > 0]
    indice_hhi = stats.hhi(arr)
    pareto = stats.pareto_share(arr, 0.80)
    fila = {
        "Universo": universo,
        "Medida": medida,
        "N": int(arr.size),
        "N positivos": int(positivos.size),
        "Gini": stats.gini(arr),
        "HHI": indice_hhi,
        "N efectivo": (10000.0 / indice_hhi) if np.isfinite(indice_hhi) and indice_hhi > 0 else np.nan,
        "% que hace el 80%": pareto,
        "N que hace el 80%": (
            float(np.ceil(pareto * arr.size)) if np.isfinite(pareto) else np.nan
        ),
    }
    for k in TOPS_CONCENTRACION:
        fila[f"Top {k}"] = share_top(arr, k)
    return fila


def tabla_concentracion(neto_clientes, htl_clientes, neto_articulos, htl_articulos) -> pd.DataFrame:
    """Cuatro lecturas de concentracion: clientes y articulos, en neto y en volumen."""
    filas = [
        medir_concentracion("Clientes", "Neto (12m)", neto_clientes),
        medir_concentracion("Clientes", "Hectolitros (12m)", htl_clientes),
        medir_concentracion("Articulos", "Neto (12m)", neto_articulos),
        medir_concentracion("Articulos", "Hectolitros (12m)", htl_articulos),
    ]
    return pd.DataFrame(filas)


def tabla_lorenz(neto_clientes, neto_articulos, puntos: int = 101) -> pd.DataFrame:
    """Curvas de Lorenz remuestreadas, listas para graficar."""
    grid, cum_cli = stats.lorenz_curve(neto_clientes, points=puntos)
    _, cum_art = stats.lorenz_curve(neto_articulos, points=puntos)
    return pd.DataFrame(
        {
            "% acumulado de la poblacion": grid,
            "Igualdad perfecta": grid,
            "% acumulado del neto — clientes": cum_cli,
            "% acumulado del neto — articulos": cum_art,
        }
    )


def top_articulos(df_art: pd.DataFrame, n: int = 25) -> pd.DataFrame:
    """Top N SKUs por neto, con participacion y acumulado, mas TOTAL GENERAL.

    El TOTAL GENERAL es el de TODO el catalogo vendido, no el subtotal del top:
    solo asi se lee de un vistazo cuanto explica el top N.
    """
    if df_art.empty:
        return pd.DataFrame()

    df = _numerico(df_art, ["neto", "bruto", "descuento", "htls", "bultos", "clientes"])
    total_neto = float(df["neto"].sum())

    top = df.sort_values("neto", ascending=False).head(int(n)).reset_index(drop=True)
    top["% del neto"] = top["neto"] / total_neto if total_neto else np.nan
    top["% acumulado"] = top["% del neto"].cumsum()

    total = {
        "id_articulo": np.nan,
        "articulo": f"{TOTAL_GENERAL} ({len(df)} SKUs vendidos)",
        "generico": "",
        "marca": "",
        "proveedor": "",
        "neto": total_neto,
        "bruto": float(df["bruto"].sum()),
        "descuento": float(df["descuento"].sum()),
        "htls": float(df["htls"].sum()),
        "bultos": float(df["bultos"].sum()),
        "clientes": np.nan,
        "% del neto": 1.0,
        "% acumulado": 1.0,
    }
    salida = pd.concat([top, pd.DataFrame([total])], ignore_index=True)
    salida = salida.rename(
        columns={
            "id_articulo": "Id articulo",
            "articulo": "Articulo",
            "generico": "Generico",
            "marca": "Marca",
            "proveedor": "Proveedor",
            "neto": "Neto (12m)",
            "bruto": "Bruto (12m)",
            "descuento": "Descuento (12m)",
            "htls": "Hectolitros (12m)",
            "bultos": "Bultos (12m)",
            "clientes": "Clientes que lo compran",
        }
    )
    # "Articulo" primero: es la columna donde el escritor busca la etiqueta
    # TOTAL para resaltar la fila de cierre.
    columnas = [
        "Articulo", "Id articulo", "Generico", "Marca", "Proveedor",
        "Neto (12m)", "% del neto", "% acumulado", "Bruto (12m)",
        "Descuento (12m)", "Hectolitros (12m)", "Bultos (12m)",
        "Clientes que lo compran",
    ]
    return salida[columnas]


def agregar_total_rfm(df_rfm: pd.DataFrame) -> pd.DataFrame:
    """Cierra el listado de clientes con la fila TOTAL GENERAL.

    La etiqueta va en ``cliente``, que es la primera columna de la tabla: el
    escritor del workbook detecta la fila de totales mirando la primera celda,
    asi que dejarla en la segunda columna hacia que la fila se escribiera pero
    sin resaltar, y el lector no la veia.
    """
    if df_rfm.empty:
        return df_rfm
    total = _fila_total_vacia(df_rfm)
    total["cliente"] = TOTAL_GENERAL
    for col in ("monetario_neto", "monetario_bruto", "descuento", "htls", "bultos", "frecuencia"):
        if col in df_rfm.columns:
            total[col] = float(df_rfm[col].sum())
    total["recencia_dias"] = float(df_rfm["recencia_dias"].median())
    total["segmento"] = f"{len(df_rfm)} clientes activos"
    return pd.concat([df_rfm, pd.DataFrame([total])], ignore_index=True)


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------

# El NOMBRE del cliente va primero, no el id: ahi es donde el escritor del
# workbook busca la palabra TOTAL para resaltar la fila de cierre, y ademas es
# lo primero que quiere leer un preventista.
_COLUMNAS_RFM = [
    "cliente", "id_cliente", "es_mostrador", "sucursal", "canal", "subcanal",
    "ramo", "localidad", "preventista", "recencia_dias", "frecuencia",
    "dias_compra", "meses_activos", "monetario_neto", "monetario_bruto",
    "descuento", "htls", "bultos", "score_r", "score_f", "score_m",
    "celda_rfm", "segmento", "accion",
]

_COLUMNAS_FUGA = [
    "cliente", "id_cliente", "sucursal", "sucursal_cerrada", "es_mostrador",
    "accionable", "canal", "ramo", "localidad", "preventista",
    "dias_compra_24m", "gap_medio", "gap_p50", "gap_p90", "cv_ritmo",
    "recencia_dias", "exceso_dias", "ratio", "estado", "neto_12m",
]


def build(ctx: AnalysisContext) -> AnalysisResult:
    """Ejecuta el analisis completo de base de clientes.

    Nunca levanta excepcion: ante datos faltantes o degenerados devuelve
    ``failed=True`` con la explicacion en ``notes``. La red de seguridad esta
    aca y no adentro de cada bloque porque el informe es un anexo de un workbook
    mas grande: si esta hoja explota, las otras nueve tampoco se entregan. Lo
    que se alcanzo a calcular antes del error se conserva.
    """
    resultado = AnalysisResult(name=NOMBRE)
    try:
        _construir(ctx, resultado)
    except Exception as exc:
        resultado.notes.append(
            f"El analisis se corto por un error inesperado: {type(exc).__name__}: {exc}. "
            "Las tablas que ya estaban calculadas se entregan igual."
        )
        if not resultado.tables:
            resultado.failed = True
    return resultado


def _construir(ctx: AnalysisContext, resultado: AnalysisResult) -> None:
    """Cuerpo del analisis. Escribe sobre ``resultado`` en vez de devolverlo."""
    try:
        ventanas = _ventanas(ctx)
    except Exception as exc:
        resultado.failed = True
        resultado.notes.append(f"No se pudo resolver la ventana de analisis: {exc}")
        return

    hasta = ventanas["hasta"]
    desde_12 = ventanas["desde_12"]
    desde_24 = ventanas["desde_24"]
    desde_previo = ventanas["desde_previo"]
    dias_ventana = ventanas["dias_ventana"]
    desde_cohorte = constants.FECHA_RED_COMPLETA

    resultado.notes.append(
        f"Ventana actual: {(date.fromisoformat(desde_12) + timedelta(days=1)).isoformat()} "
        f"a {hasta}. Ventana previa: "
        f"{(date.fromisoformat(desde_previo) + timedelta(days=1)).isoformat()} a {desde_12}. "
        f"Las dos duran exactamente {dias_ventana} dias y no se solapan: por eso el "
        "puente reconcilia exacto y el crecimiento no viene inflado por comparar "
        "una ventana mas larga contra una mas corta."
    )
    resultado.notes.append(
        "Solo se cuentan facturas (FCVTA) y devoluciones (DVVTA). Los presupuestos "
        "(PRVTA) quedan afuera de la plata y del volumen: no son venta. Son pocas "
        "lineas pero con montos enormes concentrados en un punado de clientes, y "
        "contarlos movia el crecimiento real mas de un punto porcentual."
    )
    resultado.notes.append(
        "Pesos: 'Neto' = subtotal_neto (bruto menos descuentos, el ingreso real); "
        "'Bruto' = facturacion_neta (precio de lista, pese al nombre de la columna); "
        "'Descuento' = descuentos. subtotal_final NO se usa: incluye impuestos."
    )
    resultado.notes.append(
        "Se excluyen de todas las medidas los genericos que no son articulos de "
        f"venta ({', '.join(constants.GENERICOS_NO_VENTA)})."
    )
    resultado.notes.append(
        "Los pesos son NOMINALES y solo comparables dentro de una misma ventana. "
        "Toda comparacion entre periodos se lee en hectolitros."
    )

    errores: list[str] = []

    # -- RFM ---------------------------------------------------------------
    df_rfm = pd.DataFrame()
    try:
        crudo = ctx.sql(sql_rfm(desde_12, hasta))
        df_rfm = calcular_rfm(crudo)
    except Exception as exc:
        errores.append(f"RFM: {exc}")

    if df_rfm.empty:
        errores.append("RFM: no hay clientes con compras en la ventana de 12 meses.")
    else:
        columnas = [c for c in _COLUMNAS_RFM if c in df_rfm.columns]
        resultado.tables["rfm"] = agregar_total_rfm(df_rfm[columnas])
        resultado.tables["rfm_resumen"] = resumir_rfm(df_rfm)

        mostrador = df_rfm[df_rfm["es_mostrador"]]
        resultado.notes.append(
            f"{len(mostrador)} clientes mostrador quedan MARCADOS (columna es_mostrador) "
            f"y no borrados: aportan {float(mostrador['monetario_neto'].sum()):,.0f} de neto "
            "y sacarlos descuadraria el total contra la facturacion de la empresa. "
            "Para trabajo comercial hay que filtrarlos."
        )
        etiquetas_definidas = {e for _, _, _, _, e, _ in constants.SEGMENTOS_RFM}
        ausentes = sorted(etiquetas_definidas - set(df_rfm["segmento"].unique()))
        if ausentes:
            resultado.notes.append(
                "Con la regla 'gana la primera coincidencia' de SEGMENTOS_RFM, "
                f"estos segmentos quedan vacios porque una regla anterior mas amplia "
                f"los absorbe: {', '.join(ausentes)}. Si el negocio los quiere ver, "
                "hay que reordenar SEGMENTOS_RFM (no es un problema de este modulo)."
            )

    # -- Fuga --------------------------------------------------------------
    df_fuga = pd.DataFrame()
    try:
        crudo = ctx.sql(sql_fuga(desde_12, desde_24, hasta))
        df_fuga = calcular_fuga(crudo)
    except Exception as exc:
        errores.append(f"Fuga: {exc}")

    if df_fuga.empty:
        errores.append("Fuga: ningun cliente alcanza el minimo de compras para medir su ritmo.")
    else:
        columnas = [c for c in _COLUMNAS_FUGA if c in df_fuga.columns]
        resultado.tables["fuga"] = resumir_fuga_total(df_fuga[columnas])
        resultado.notes.append(
            f"Fuga: solo entran clientes con al menos {constants.CHURN_MIN_COMPRAS} dias de "
            "compra en 24 meses; por debajo el p90 propio no significa nada. El umbral de "
            "alarma es el p90 de los intervalos DEL PROPIO CLIENTE, porque la cadencia de la "
            "base va de 2 a mas de 500 dias y una regla fija no sirve para nadie."
        )
        resultado.notes.append(
            "Las sucursales cerradas ("
            + ", ".join(f"{s} (ultimo dia {f})" for s, f in constants.SUCURSALES_CERRADAS.items())
            + ") y los clientes mostrador quedan con accionable=False y FUERA de la lista "
            "de trabajo: sus clientes figuran 100% atrasados por el cierre, no por fuga."
        )

    # -- Cohortes ----------------------------------------------------------
    try:
        crudo = ctx.sql(sql_cohortes(hasta, desde_cohorte))
        matriz = matriz_cohortes(crudo, hasta)
        if matriz.empty:
            errores.append("Cohortes: no hay cohortes posteriores a la fecha de red completa.")
        else:
            resultado.tables["cohortes"] = matriz
            resultado.notes.append(
                f"Cohortes desde {desde_cohorte} ({constants.FECHA_RED_COMPLETA}): antes de esa "
                "fecha fact_ventas solo tiene CASA CENTRAL y el alta de las otras 13 sucursales "
                "en el ETL se leeria como una ola de captacion que nunca existio."
            )
            resultado.notes.append(
                "Retencion = compro en ESE mes exacto. Un cliente que saltea un mes y vuelve "
                "figura caido y resucitado; la fila de promedio ponderado suaviza ese ruido. "
                "El ultimo mes de la ventana esta incompleto y baja artificialmente la ultima "
                "diagonal."
            )
            # El promedio ponderado de cada M usa SOLO las cohortes que ya
            # cumplieron esa edad. En los M altos eso deja una o dos cohortes, y
            # como las mas viejas son las mejores, la fila deja de bajar e
            # incluso sube. No es que la retencion mejore a los dos anos: es
            # supervivencia de la muestra, y hay que decirlo.
            cohortes_por_m = {
                col: int(matriz.iloc[:-1][col].notna().sum())
                for col in matriz.columns
                if str(col).startswith("M")
            }
            fragiles = [c for c, n in cohortes_por_m.items() if n <= 3]
            if fragiles:
                resultado.notes.append(
                    "En la fila de promedio ponderado, cada M promedia solo las cohortes que "
                    f"ya cumplieron esa edad. Desde {fragiles[0]} quedan 3 cohortes o menos "
                    f"(hasta {fragiles[-1]}, con {cohortes_por_m[fragiles[-1]]}), asi que si "
                    "la curva deja de bajar ahi NO es que la retencion mejore: es que solo "
                    "sobreviven las cohortes mas viejas, que son las mejores. Leer esa cola "
                    "como tendencia es un error."
                )
    except Exception as exc:
        errores.append(f"Cohortes: {exc}")

    # -- Puente ------------------------------------------------------------
    reconciliacion: dict = {}
    puente = pd.DataFrame()
    try:
        crudo = ctx.sql(sql_puente(desde_12, desde_previo, hasta))
        puente, reconciliacion = construir_puente(crudo)
    except Exception as exc:
        errores.append(f"Puente: {exc}")

    if puente.empty:
        errores.append("Puente: no hay clientes activos en ninguna de las dos ventanas.")
    else:
        resultado.tables["puente"] = puente
        resultado.notes.append(
            "En el puente, Upsell/Downsell se decide por HECTOLITROS, no por pesos. Por eso "
            "hay muchos mas clientes en Downsell que los que mostraria una lectura en pesos: "
            "con inflacion casi todo el mundo factura mas aunque venda menos producto."
        )
        diff_htl = abs(reconciliacion["suma_buckets_htl"] - reconciliacion["delta_total_htl"])
        diff_neto = abs(reconciliacion["suma_buckets_neto"] - reconciliacion["delta_total_neto"])
        tolerancia_htl = max(1e-6, abs(reconciliacion["delta_total_htl"]) * 1e-9)
        tolerancia_neto = max(1e-3, abs(reconciliacion["delta_total_neto"]) * 1e-9)
        cuadra = diff_htl <= tolerancia_htl and diff_neto <= tolerancia_neto
        resultado.notes.append(
            "Reconciliacion del puente: los buckets suman "
            f"{reconciliacion['suma_buckets_htl']:,.4f} htl contra un delta total de "
            f"{reconciliacion['delta_total_htl']:,.4f} htl (diferencia {diff_htl:.2e}); "
            f"en neto suman {reconciliacion['suma_buckets_neto']:,.2f} contra "
            f"{reconciliacion['delta_total_neto']:,.2f} (diferencia {diff_neto:.2e}). "
            + ("Cuadra exacto." if cuadra else "NO CUADRA: revisar la clasificacion.")
        )
        if not cuadra:
            errores.append("Puente: los buckets no reconcilian contra el delta total.")

    # -- Concentracion -----------------------------------------------------
    df_art = pd.DataFrame()
    try:
        df_art = _numerico(
            ctx.sql(sql_articulos(desde_12, hasta)),
            ["neto", "bruto", "descuento", "htls", "bultos", "clientes"],
        )
    except Exception as exc:
        errores.append(f"Articulos: {exc}")

    if not df_rfm.empty and not df_art.empty:
        resultado.tables["concentracion"] = tabla_concentracion(
            df_rfm["monetario_neto"], df_rfm["htls"], df_art["neto"], df_art["htls"]
        )
        resultado.tables["lorenz"] = tabla_lorenz(df_rfm["monetario_neto"], df_art["neto"])
        resultado.tables["top_articulos"] = top_articulos(df_art, 25)
        resultado.notes.append(
            "concentracion y lorenz son tablas de indices (Gini, HHI, participaciones): "
            "no llevan fila TOTAL GENERAL porque sumar coeficientes no significa nada. "
            "El total de pesos y volumen esta en top_articulos y en rfm."
        )
        resultado.notes.append(
            "Gini y HHI se calculan clipeando negativos a cero: la curva de Lorenz no esta "
            "definida sobre valores negativos, y los netos negativos son devoluciones."
        )
        # Las dos tablas salen del mismo universo de comprobantes, asi que la
        # unica diferencia legitima son los clientes que en la ventana solo
        # tienen devoluciones: no tienen fecha de ultima compra y por eso el
        # listado RFM los deja afuera. Ese resto tiene que ser NEGATIVO o cero.
        # Si diera positivo estariamos colando comprobantes que no son venta
        # (fue exactamente lo que pasaba con los presupuestos PRVTA), asi que la
        # nota lo dice en vez de justificarlo de antemano.
        neto_articulos = float(df_art["neto"].sum())
        neto_clientes = float(df_rfm["monetario_neto"].sum())
        resto = neto_articulos - neto_clientes
        diagnostico = (
            "Son clientes que en la ventana solo registran devoluciones y ninguna "
            "factura: no tienen recencia de compra, asi que el listado RFM los deja "
            "afuera. Al ser solo devoluciones, el resto da negativo, como corresponde."
            if resto <= 0
            else "REVISAR: el resto deberia ser negativo (solo devoluciones). Que de "
            "positivo significa que entro al neto algun comprobante que no es una "
            "venta cobrada."
        )
        resultado.notes.append(
            f"El neto por articulo suma $ {neto_articulos:,.0f} y el neto por cliente "
            f"$ {neto_clientes:,.0f}: la diferencia es $ {resto:,.0f}. {diagnostico}"
        )
    elif not errores:
        errores.append("Concentracion: faltan datos de clientes o de articulos.")

    # -- Headlines ---------------------------------------------------------
    if not df_rfm.empty:
        clientes_activos = int(len(df_rfm))
        neto_12m = float(df_rfm["monetario_neto"].sum())
        bruto_12m = float(df_rfm["monetario_bruto"].sum())
        resultado.headlines.append(
            Headline(
                label="Clientes activos (12m)",
                value=clientes_activos,
                number_format="#,##0",
                note="Con al menos una factura en la ventana movil de 12 meses.",
            )
        )
        resultado.headlines.append(
            Headline(
                label="Neto 12m (nominal)",
                value=neto_12m,
                number_format='$ #,##0',
                note=(
                    f"subtotal_neto. El bruto a precio de lista es $ {bruto_12m:,.0f}; "
                    f"la diferencia son $ {bruto_12m - neto_12m:,.0f} de descuentos "
                    f"({(bruto_12m - neto_12m) / bruto_12m:.1%} del bruto)."
                    if bruto_12m
                    else "subtotal_neto."
                ),
            )
        )

    if reconciliacion:
        resultado.headlines.append(
            Headline(
                label="Crecimiento real por cliente (htl)",
                value=reconciliacion.get("crecimiento_real_htl", np.nan),
                number_format="0.0%",
                delta=reconciliacion.get("crecimiento_real_htl"),
                note=(
                    "Ventana movil de 12m desde la fecha de corte, sobre el universo de "
                    "clientes del puente. El nominal en pesos es "
                    f"{reconciliacion.get('crecimiento_nominal_neto', float('nan')):.1%} "
                    "y esta inflado. Ver la nota de conciliacion en Metodologia: la hoja "
                    "de demanda mide meses calendario y da una cifra levemente distinta."
                ),
            )
        )

    neto_recuperable = 0.0
    if not df_fuga.empty and not df_rfm.empty:
        accionables = df_fuga[df_fuga["accionable"]]
        recuperables = accionables[accionables["estado"] == "Recuperable"]
        perdidos = accionables[accionables["estado"] == "Perdido"]
        neto_recuperable = float(recuperables["neto_12m"].sum())
        neto_perdido = float(perdidos["neto_12m"].sum())
        base_neto = float(df_rfm["monetario_neto"].sum())
        pct_recuperable = neto_recuperable / base_neto if base_neto else np.nan
        resultado.headlines.append(
            Headline(
                label="% del neto en riesgo recuperable",
                value=pct_recuperable,
                number_format="0.0%",
                higher_is_better=False,
                note=(
                    f"$ {neto_recuperable:,.0f} en {len(recuperables)} clientes atrasados "
                    f"hasta {constants.CHURN_RATIO_RECUPERABLE:g}x su propio p90. "
                    f"Otros $ {neto_perdido:,.0f} en {len(perdidos)} clientes ya perdidos."
                ),
            )
        )
        resultado.alerts.append(
            Alert(
                severity="alta",
                title="Hay plata recuperable con una llamada esta semana",
                detail=(
                    f"{len(recuperables)} clientes accionables estan atrasados hasta "
                    f"{constants.CHURN_RATIO_RECUPERABLE:g}x su propio p90 de compra y "
                    f"representan $ {neto_recuperable:,.0f} de neto de los ultimos 12 meses "
                    f"({pct_recuperable:.1%} de la base). Los que superan ese umbral "
                    f"($ {neto_perdido:,.0f} en {len(perdidos)} clientes) ya no vuelven: "
                    "no conviene gastar tiempo de preventa ahi."
                ),
                amount=neto_recuperable,
            )
        )

        cerrados = df_fuga[df_fuga["sucursal_cerrada"]]
        if len(cerrados):
            resultado.alerts.append(
                Alert(
                    severity="critica",
                    title="Sucursal cerrada, no es fuga comercial",
                    detail=(
                        ", ".join(
                            f"{s} dejo de facturar el {f}"
                            for s, f in constants.SUCURSALES_CERRADAS.items()
                        )
                        + f". Sus {len(cerrados)} clientes figuran atrasados por el cierre y "
                        f"arrastran $ {float(cerrados['neto_12m'].sum()):,.0f} de neto de 12 meses. "
                        "Estan excluidos de la lista accionable. Si el cierre NO estaba "
                        "previsto, entonces es una alimentacion del ETL que murio y nadie vio."
                    ),
                    amount=float(cerrados["neto_12m"].sum()),
                )
            )

    if not puente.empty:
        sin_total = puente[puente["Movimiento"] != TOTAL_GENERAL].set_index("Movimiento")
        downsell_htl = float(sin_total.get("Delta htl", pd.Series(dtype=float)).get("Downsell", 0.0))
        perdidos_htl = float(sin_total.get("Delta htl", pd.Series(dtype=float)).get("Perdidos", 0.0))
        downsell_clientes = int(sin_total.get("Clientes", pd.Series(dtype=float)).get("Downsell", 0))
        perdidos_clientes = int(sin_total.get("Clientes", pd.Series(dtype=float)).get("Perdidos", 0))
        htl_previo = float(reconciliacion.get("htl_previo", 0.0) or 0.0)
        arrastre = abs(downsell_htl) + abs(perdidos_htl)
        if arrastre > 0:
            # Cada division va guardada por su denominador. El volumen previo
            # puede dar cero (una sucursal nueva, o devoluciones que compensan
            # las ventas) y ahi la alerta tiene que degradarse, no tumbar el
            # informe entero.
            partes = [
                f"{downsell_clientes:,} clientes que SIGUEN comprando destruyeron "
                f"{abs(downsell_htl):,.0f} htl contra el periodo anterior, mientras que "
                f"los {perdidos_clientes:,} clientes que se perdieron del todo restaron "
                f"{abs(perdidos_htl):,.0f} htl."
            ]
            if perdidos_htl:
                partes.append(
                    f"El downsell pesa {abs(downsell_htl) / abs(perdidos_htl):.1f}x mas "
                    "que la fuga."
                )
            if htl_previo > 0:
                partes.append(
                    f"Entre los dos hay que reconquistar {arrastre:,.0f} htl "
                    f"({arrastre / htl_previo:.1%} del volumen del periodo previo) antes "
                    "de crecer un solo hectolitro."
                )
            else:
                partes.append(
                    f"Entre los dos hay que reconquistar {arrastre:,.0f} htl."
                )
            partes.append(
                "Un programa de retencion apuntado solo a 'clientes que dejaron de "
                "comprar' ataca la mitad chica del problema."
            )
            resultado.alerts.append(
                Alert(
                    severity="alta",
                    title="La sangria es el downsell, no la fuga",
                    detail=" ".join(partes),
                    amount=arrastre,
                )
            )

    concentracion = resultado.tables.get("concentracion")
    if concentracion is not None and not concentracion.empty:
        cli = concentracion[
            (concentracion["Universo"] == "Clientes") & (concentracion["Medida"] == "Neto (12m)")
        ]
        art = concentracion[
            (concentracion["Universo"] == "Articulos") & (concentracion["Medida"] == "Neto (12m)")
        ]
        if not cli.empty:
            resultado.headlines.append(
                Headline(
                    label="Gini de clientes (neto 12m)",
                    value=float(cli.iloc[0]["Gini"]),
                    number_format="0.000",
                    higher_is_better=False,
                    note=(
                        f"N efectivo {float(cli.iloc[0]['N efectivo']):,.0f} clientes; "
                        f"el mayor pesa {float(cli.iloc[0]['Top 1']):.2%}. "
                        "Desigual pero sin dependencia de un solo cliente."
                    ),
                )
            )
        if not art.empty and not df_art.empty:
            top1 = df_art.sort_values("neto", ascending=False).iloc[0]
            share1 = float(art.iloc[0]["Top 1"])
            resultado.headlines.append(
                Headline(
                    label="Participacion del SKU #1",
                    value=share1,
                    number_format="0.0%",
                    higher_is_better=False,
                    note=f"{top1['articulo']} sobre el neto de 12 meses.",
                )
            )
            resultado.alerts.append(
                Alert(
                    severity="critica",
                    title="El riesgo de concentracion esta en el producto, no en el cliente",
                    detail=(
                        f"{top1['articulo']} hace por si solo el {share1:.2%} del neto de 12 meses. "
                        f"El HHI de articulos es {float(art.iloc[0]['HHI']):,.0f} "
                        f"(N efectivo {float(art.iloc[0]['N efectivo']):,.1f} SKUs) y el "
                        f"{float(art.iloc[0]['% que hace el 80%']):.1%} del catalogo vendido "
                        f"({float(art.iloc[0]['N que hace el 80%']):,.0f} SKUs) hace el 80% del "
                        f"neto. Del lado de los clientes el HHI es apenas "
                        f"{float(cli.iloc[0]['HHI']):,.1f}. Un quiebre de stock o un cambio de "
                        "precio en un solo articulo mueve una porcion enorme de la facturacion."
                    ),
                    amount=float(top1["neto"]),
                )
            )

    if errores:
        resultado.notes.extend(errores)
    if not resultado.tables:
        resultado.failed = True
        resultado.notes.append(
            "El analisis de base de clientes no produjo ninguna tabla: ver los errores arriba."
        )
