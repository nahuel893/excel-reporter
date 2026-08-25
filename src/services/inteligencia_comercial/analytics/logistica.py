"""Logistica: nivel de servicio, rechazos, devoluciones, stock y economia de rutas.

Esta familia responde a cinco preguntas que la gerencia comercial hace todos los
meses y que hoy se contestan de memoria:

  1. Que tan rapido entregamos y quien entrega mal (tabla "sla").
  2. Cuanta plata se nos vuelve y por que dimension (tabla "rechazos").
  3. Que productos se devuelven mas de lo que su propio volumen explica
     (tabla "devoluciones").
  4. Donde estamos por quebrar y donde tenemos el capital dormido (tabla "stock").
  5. Que rutas cuestan mas de lo que dejan (tabla "rutas").

Decisiones metodologicas que hay que respetar si se toca este archivo:

* El nivel de servicio se mide a nivel FACTURA, no a nivel linea. Una factura de
  40 renglones es UNA entrega; contarla 40 veces le da 40 veces mas peso a los
  pedidos grandes y rompe cualquier comparacion entre fleteros.
* Nunca se acusa a nadie por una diferencia que puede ser azar: cada tasa pasa
  por `stats.proportion_ztest` contra la tasa agregada de la red. Y como con
  n~20.000 entregas el test marca "significativo" casi todo, se agrega ademas
  un piso de significancia PRACTICA (BRECHA_MINIMA_*): solo se llama rezagado a
  quien es significativo Y ademas esta lejos del promedio.
* Toda cifra en pesos es NOMINAL en ARS y solo comparable dentro de la misma
  ventana. Las comparaciones entre periodos se hacen en bultos.
* `facturacion_neta` es BRUTO a precio de lista y `subtotal_neto` es el NETO
  (neto = bruto - descuentos). Cada columna monetaria lleva la etiqueta puesta.
* Los generico de `constants.GENERICOS_NO_VENTA` (marketing, envases, equipos de
  frio) y los pseudo-articulos sin generico quedan afuera de toda metrica de
  volumen: son material promocional y envase retornable, no mercaderia.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.services.inteligencia_comercial import constants as k
from src.services.inteligencia_comercial import stats
from src.services.inteligencia_comercial.contracts import (
    Alert,
    AnalysisContext,
    AnalysisResult,
    Headline,
)

NOMBRE = "Logistica y Nivel de Servicio"

# ---------------------------------------------------------------------------
# Parametros del analisis
# ---------------------------------------------------------------------------
# Los fleteros 0 y 33 no son transportistas: son venta de mostrador / retiro en
# deposito. Medidos entregan el 100,00% y el 99,84% en el dia con lead medio de
# 0,008 y 0,027 dias. Dejarlos adentro sube el OTIF de la red de 83,6% a 84,5%
# y ensucia la comparacion entre fleteros reales.
FLETEROS_SENTINELA = (0, 33)

# Un fletero o una sucursal necesita un minimo de entregas para que la
# comparacion sea legible. Por debajo el z-test ya lo declara no significativo,
# pero igual sacamos el ruido de la tabla.
MIN_ENTREGAS_SLA = 200

# Piso de significancia PRACTICA. Con ~20.000 entregas por fletero el z-test
# detecta diferencias de 2 puntos porcentuales: 54 de 62 fleteros dan
# "significativo" y la lista deja de ser accionable. Solo se acciona a partir de
# 5 pp de brecha contra la red.
BRECHA_MINIMA_OTIF = 0.05
BRECHA_MINIMA_RECHAZO = 0.02

# Lead time plausible. Hay 131 filas con fecha_entrega anterior a fecha_pedido
# (errores de carga, hasta -25 dias) y una cola larga de backorder real.
LEAD_MINIMO_DIAS = 0
LEAD_MAXIMO_DIAS = 60

# Piso de lineas para entrar al ranking de rechazo por cliente/articulo.
MIN_LINEAS_RECHAZO = 300
# Piso de bultos brutos para que una tasa de devolucion por articulo signifique
# algo. Con 200 bultos vendidos, 20 devueltos dan 10% que es puro ruido.
MIN_BULTOS_DEVOLUCION = 3000
# Umbral de |z robusto| para marcar un articulo como outlier de devolucion.
Z_ROBUSTO_OUTLIER = 3.5

# Cuantas entidades se muestran en las dimensiones largas (cliente, articulo).
TOP_RANKING = 40

# Ventana de velocidad para la cobertura de stock, en dias corridos.
DIAS_VELOCIDAD = 60

ETIQUETA_TOTAL = "TOTAL GENERAL"
ETIQUETA_RESTO = "RESTO"

# Veredicto de la entidad que no tiene muestra suficiente para ser juzgada.
VEREDICTO_MUESTRA_CHICA = "Sin evidencia (muestra chica)"
# Veredicto del que entrega peor que la red con evidencia Y con impacto.
VEREDICTO_REZAGADO = "Rezagado significativo"

ORDEN_DIAS = (
    "Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo",
)

# Orden de lectura de la tabla de stock: primero lo que urge.
ORDEN_ESTADO_STOCK = ("QUIEBRE", "SOBRESTOCK", "STOCK MUERTO", "NORMAL", "SIN MOVIMIENTO")


# ---------------------------------------------------------------------------
# Utilidades de fechas
# ---------------------------------------------------------------------------
def _restar_meses(fecha: date, meses: int) -> date:
    """Retrocede `meses` meses cuidando el fin de mes (dia tope 28)."""
    total = fecha.month - meses
    anio = fecha.year + (total - 1) // 12
    mes = (total - 1) % 12 + 1
    return date(anio, mes, min(fecha.day, 28))


def _es_fin_de_mes(fecha: date) -> bool:
    return (fecha + timedelta(days=1)).month != fecha.month


def alinear_a_mes_completo(fecha: date) -> date:
    """Adelanta la fecha al 1 del mes siguiente salvo que ya sea dia 1.

    La serie mensual de devoluciones tiene que arrancar en un mes COMPLETO. Sin
    esto, con hasta=2026-07-30 la ventana de 24 meses abria el 2024-07-28 y
    julio 2024 entraba con 27.667 bultos contra los ~290.000 de un mes normal:
    un muñon de truncamiento de 10x que se lee como un derrumbe de la venta.
    """
    if fecha.day == 1:
        return fecha
    if fecha.month == 12:
        return date(fecha.year + 1, 1, 1)
    return date(fecha.year, fecha.month + 1, 1)


def ventana_contabilidad(hasta: date, meses: int) -> tuple[date, date]:
    """Ventana utilizable de `fact_ventas_contabilidad`.

    El ETL contable va ~3 meses atrasado (corta el 2026-05-05) y ese ultimo mes
    es un muñon de 5 dias: su OTIF de 53,6% es un artefacto de truncamiento, no
    un derrumbe del servicio. Por eso la ventana termina en el ultimo mes
    COMPLETO anterior al corte.
    """
    corte = date.fromisoformat(k.FECHA_CORTE_CONTABILIDAD)
    fin = min(hasta, corte)
    if not _es_fin_de_mes(fin):
        fin = date(fin.year, fin.month, 1) - timedelta(days=1)
    return _restar_meses(fin, meses), fin


# ---------------------------------------------------------------------------
# Estadistica reutilizable
# ---------------------------------------------------------------------------
def percentil_ponderado(valores, pesos, q: float) -> float:
    """Percentil exacto de una distribucion dada como histograma.

    Traemos de la base el conteo de entregas por cada valor entero de lead time
    en vez de las 985.000 entregas una por una. El percentil sale igual de exacto
    y el resultado que viaja por red es de unas pocas miles de filas.
    """
    v = np.asarray(valores, dtype=float)
    w = np.asarray(pesos, dtype=float)
    mask = np.isfinite(v) & np.isfinite(w) & (w > 0)
    v, w = v[mask], w[mask]
    if v.size == 0:
        return float("nan")
    orden = np.argsort(v, kind="mergesort")
    v, w = v[orden], w[orden]
    acumulado = np.cumsum(w)
    idx = int(np.searchsorted(acumulado, q * acumulado[-1], side="left"))
    return float(v[min(idx, v.size - 1)])


def evaluar_proporcion(
    df: pd.DataFrame,
    col_exitos: str,
    col_n: str,
    brecha_minima: float,
    mayor_es_mejor: bool = True,
    etiqueta_peor: str = VEREDICTO_REZAGADO,
    etiqueta_mejor: str = "Mejor que la red",
) -> pd.DataFrame:
    """Compara la tasa de cada entidad contra la tasa agregada de la red.

    Devuelve el frame con Tasa / Tasa Red / Brecha vs Red / z / p-valor /
    Significativo / Veredicto. El veredicto es lo unico que se lee en la reunion:
    una entidad solo se llama rezagada cuando el z-test la separa del promedio Y
    la brecha supera el piso practico. Una sucursal con 40 entregas y 3 tardias
    no se acusa de nada.
    """
    out = df.copy()
    if out.empty:
        for col in ("Tasa", "Tasa Red", "Brecha vs Red", "z", "p-valor",
                    "Significativo", "Veredicto"):
            out[col] = pd.Series(dtype="float64" if col != "Veredicto" else "object")
        return out

    n_total = float(out[col_n].sum())
    exitos_total = float(out[col_exitos].sum())
    base = exitos_total / n_total if n_total > 0 else float("nan")

    pruebas = [
        stats.proportion_ztest(fila[col_exitos], fila[col_n], base)
        for _, fila in out.iterrows()
    ]
    out["Tasa"] = [p.rate for p in pruebas]
    out["Tasa Red"] = base
    out["Brecha vs Red"] = out["Tasa"] - base
    out["z"] = [p.z for p in pruebas]
    out["p-valor"] = [p.p_value for p in pruebas]
    out["Significativo"] = [p.significant for p in pruebas]

    peor = (out["Brecha vs Red"] < 0) == bool(mayor_es_mejor)
    grande = out["Brecha vs Red"].abs() >= brecha_minima
    veredicto = np.where(
        ~out["Significativo"].to_numpy(dtype=bool),
        VEREDICTO_MUESTRA_CHICA,
        np.where(
            ~grande.to_numpy(dtype=bool),
            "Significativo pero sin impacto practico",
            np.where(peor.to_numpy(dtype=bool), etiqueta_peor, etiqueta_mejor),
        ),
    )
    out["Veredicto"] = veredicto
    return out


# ---------------------------------------------------------------------------
# Formato de numeros para los textos (miles con punto, decimales con coma)
# ---------------------------------------------------------------------------
def _num(valor, decimales: int = 0) -> str:
    """Numero en formato argentino para meterlo dentro de una frase."""
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return "s/d"
    if not np.isfinite(valor):
        return "s/d"
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _pct(valor, decimales: int = 2) -> str:
    """Fraccion expresada como porcentaje, en formato argentino."""
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return "s/d"
    if not np.isfinite(valor):
        return "s/d"
    return _num(valor * 100.0, decimales) + "%"


def _pesos(valor, decimales: int = 0) -> str:
    return "$" + _num(valor, decimales)


# ---------------------------------------------------------------------------
# 1. Nivel de servicio (SLA)
# ---------------------------------------------------------------------------
COLUMNAS_SLA = [
    "Nivel", "Entidad", "Sucursal", "Entregas",
    "Lead Medio (dias)", "Lead p50 (dias)", "Lead p90 (dias)",
    "OTIF (<=1 dia)", "Tasa Red", "Brecha vs Red", "z", "p-valor",
    "Significativo", "Veredicto",
    "Bultos", "Neto Facturado (Nominal $)",
]

SQL_SLA = """
with entregas as (
    -- Grano FACTURA: una factura de 40 renglones es UNA entrega.
    select fvc.id_sucursal,
           fvc.id_fletero_carga,
           (min(fvc.fecha_entrega) - min(fvc.fecha_pedido)) as lead_dias,
           sum(fvc.subtotal_neto)    as neto,
           sum(fvc.cantidades_total) as bultos
    from gold.fact_ventas_contabilidad fvc
    where fvc.id_documento = 'FCVTA'
      and not fvc.anulado
      and fvc.fecha_comprobante >= %(desde)s
      and fvc.fecha_comprobante <= %(hasta)s
      and fvc.fecha_pedido is not null
      and fvc.fecha_entrega is not null
    group by fvc.id_documento, fvc.letra, fvc.serie, fvc.nro_doc,
             fvc.id_sucursal, fvc.id_fletero_carga
)
select ds.descripcion as sucursal,
       e.id_sucursal,
       e.id_fletero_carga,
       e.lead_dias,
       count(*)      as entregas,
       sum(e.bultos) as bultos,
       sum(e.neto)   as neto
from entregas e
join gold.dim_sucursal ds on ds.id_sucursal = e.id_sucursal
where e.lead_dias between %(lead_min)s and %(lead_max)s
group by 1, 2, 3, 4
"""


def _bloque_sla(histograma: pd.DataFrame, claves: list[str], nivel: str) -> pd.DataFrame:
    """Colapsa el histograma de lead time a una fila por entidad."""
    filas = []
    for valores, grupo in histograma.groupby(claves, dropna=False):
        valores = valores if isinstance(valores, tuple) else (valores,)
        entregas = float(grupo["entregas"].sum())
        lead = grupo["lead_dias"].to_numpy(dtype=float)
        peso = grupo["entregas"].to_numpy(dtype=float)
        ok1 = float(grupo.loc[grupo["lead_dias"] <= 1, "entregas"].sum())
        filas.append(
            {
                "Nivel": nivel,
                "Entidad": str(valores[0]),
                "Sucursal": str(valores[-1]),
                "Entregas": entregas,
                "_ok1": ok1,
                "Lead Medio (dias)": float((lead * peso).sum() / entregas) if entregas else float("nan"),
                "Lead p50 (dias)": percentil_ponderado(lead, peso, 0.5),
                "Lead p90 (dias)": percentil_ponderado(lead, peso, 0.9),
                "Bultos": float(grupo["bultos"].sum()),
                "Neto Facturado (Nominal $)": float(grupo["neto"].sum()),
            }
        )
    return pd.DataFrame(filas)


def resumir_sla(
    histograma: pd.DataFrame,
    sentinelas: tuple[int, ...] = FLETEROS_SENTINELA,
    min_entregas: int = MIN_ENTREGAS_SLA,
) -> pd.DataFrame:
    """Tabla de nivel de servicio por sucursal y por fletero, con veredicto.

    `histograma` viene de SQL_SLA: una fila por (sucursal, fletero, lead_dias)
    con el conteo de entregas. Los fleteros sentinela se sacan ANTES de calcular
    la tasa de la red, porque su 100% de cumplimiento no es transporte.
    """
    if histograma.empty:
        return pd.DataFrame(columns=COLUMNAS_SLA)

    datos = histograma.copy()
    datos = datos[~datos["id_fletero_carga"].isin(list(sentinelas))]
    if datos.empty:
        return pd.DataFrame(columns=COLUMNAS_SLA)

    por_sucursal = _bloque_sla(datos, ["sucursal"], "Sucursal")
    por_sucursal["Sucursal"] = por_sucursal["Entidad"]

    datos_fletero = datos.copy()
    datos_fletero["etiqueta_fletero"] = "Fletero " + datos_fletero["id_fletero_carga"].astype(str)
    por_fletero = _bloque_sla(datos_fletero, ["etiqueta_fletero", "sucursal"], "Fletero")
    # Un fletero opera en una sola sucursal (70 de 71 verificados), asi que la
    # comparacion entre fleteros arrastra la dificultad del territorio. Se deja
    # la sucursal en la fila para que se lea dentro de su contexto.
    por_fletero = por_fletero[por_fletero["Entregas"] >= min_entregas]

    bloques = []
    for bloque, nombre in ((por_sucursal, "Sucursal"), (por_fletero, "Fletero")):
        if bloque.empty:
            continue
        evaluado = evaluar_proporcion(
            bloque, "_ok1", "Entregas", BRECHA_MINIMA_OTIF, mayor_es_mejor=True,
            etiqueta_peor=VEREDICTO_REZAGADO,
            etiqueta_mejor="Mejor que la red",
        )
        evaluado = evaluado.rename(columns={"Tasa": "OTIF (<=1 dia)"})
        evaluado = evaluado.sort_values("Brecha vs Red")
        bloques.append(evaluado)

    tabla = pd.concat(bloques, ignore_index=True) if bloques else pd.DataFrame()

    total_entregas = float(datos["entregas"].sum())
    ok1_total = float(datos.loc[datos["lead_dias"] <= 1, "entregas"].sum())
    lead = datos["lead_dias"].to_numpy(dtype=float)
    peso = datos["entregas"].to_numpy(dtype=float)
    total = {
        "Nivel": "TOTAL",
        "Entidad": ETIQUETA_TOTAL,
        "Sucursal": ETIQUETA_TOTAL,
        "Entregas": total_entregas,
        "Lead Medio (dias)": float((lead * peso).sum() / total_entregas) if total_entregas else float("nan"),
        "Lead p50 (dias)": percentil_ponderado(lead, peso, 0.5),
        "Lead p90 (dias)": percentil_ponderado(lead, peso, 0.9),
        "OTIF (<=1 dia)": ok1_total / total_entregas if total_entregas else float("nan"),
        "Tasa Red": ok1_total / total_entregas if total_entregas else float("nan"),
        "Brecha vs Red": 0.0,
        "z": float("nan"),
        "p-valor": float("nan"),
        "Significativo": False,
        "Veredicto": "Red completa (sin fleteros sentinela)",
        "Bultos": float(datos["bultos"].sum()),
        "Neto Facturado (Nominal $)": float(datos["neto"].sum()),
    }
    tabla = pd.concat([tabla, pd.DataFrame([total])], ignore_index=True)
    return tabla.reindex(columns=COLUMNAS_SLA)


# ---------------------------------------------------------------------------
# 2. Rechazos
# ---------------------------------------------------------------------------
COLUMNAS_RECHAZO = [
    "Dimension", "Entidad", "Lineas", "Lineas con Rechazo", "Tasa Rechazo",
    "Tasa Red", "Brecha vs Red", "z", "p-valor", "Significativo", "Veredicto",
    "Bultos Rechazados", "Valor Rechazado Neto (Nominal $)",
    "Neto Facturado (Nominal $)", "Share del Valor Rechazado",
    "Pareto Acumulado", "Nota",
]

# `cantidades_rechazo` esta poblado UNICAMENTE en documentos DVVTA: 516.189 de
# 516.297 filas DVVTA y exactamente 0 de 6.964.475 filas FCVTA. Es decir, en
# este esquema rechazo y devolucion son el MISMO evento. Filtrar
# cantidades_rechazo > 0 sobre facturas devuelve el conjunto vacio.
SQL_RECHAZO = """
with base as materialized (
    select fvc.id_sucursal,
           fvc.id_cliente,
           fvc.id_articulo,
           fvc.id_fletero_carga,
           extract(isodow from fvc.fecha_comprobante)::int as dow,
           fvc.cantidades_rechazo,
           fvc.subtotal_neto
    from gold.fact_ventas_contabilidad fvc
    join gold.dim_articulo da on da.id_articulo = fvc.id_articulo
    where not fvc.anulado
      and fvc.id_documento in ('FCVTA', 'DVVTA')
      and fvc.fecha_comprobante >= %(desde)s
      and fvc.fecha_comprobante <= %(hasta)s
      and da.generico is not null
      and not (da.generico = any(%(no_venta)s))
),
clientes as (
    -- Agregado por id_cliente (que SI es unico global) para que el join no
    -- pueda abrir en abanico. fantasia viene vacia en muchos clientes, no nula,
    -- y ademas 494 clientes traen una fantasia de relleno hecha solo de guiones:
    -- si se toma tal cual, medio centenar de cuentas distintas aparecen en la
    -- hoja bajo el mismo nombre ilegible y no se puede llamar a ninguna. Se
    -- exige al menos un caracter alfanumerico para aceptarla.
    select id_cliente,
           max(nullif(trim(fantasia), '')) filter (
               where trim(fantasia) ~ '[[:alnum:]]'
           ) as fantasia,
           max(nullif(trim(razon_social), '')) as razon_social,
           max(nullif(trim(des_subcanal_mkt), '')) as subcanal
    from gold.dim_cliente group by 1
),
metricas_sucursal as (
    select 'Sucursal' as dimension, ds.descripcion as entidad,
           b.id_sucursal::text as id_entidad, {m}
    from base b join gold.dim_sucursal ds on ds.id_sucursal = b.id_sucursal
    group by 1, 2, 3
),
metricas_fletero as (
    select 'Fletero' as dimension,
           'Fletero ' || b.id_fletero_carga::text as entidad,
           b.id_fletero_carga::text as id_entidad, {m}
    from base b
    where not (b.id_fletero_carga = any(%(sentinelas)s))
    group by 1, 2, 3
),
metricas_cliente as (
    -- Cascada de nombre: fantasia util -> razon social con el id al lado (hay
    -- 12.000 clientes reales cuya razon social dice "CONSUMIDOR FINAL", asi que
    -- sin el id no se distinguen) -> el id pelado. Toda fila queda identificable.
    select 'Cliente' as dimension,
           coalesce(c.fantasia,
                    c.razon_social || ' [' || b.id_cliente::text || ']',
                    'CLIENTE ' || b.id_cliente::text) as entidad,
           b.id_cliente::text as id_entidad, {m}
    from base b left join clientes c on c.id_cliente = b.id_cliente
    group by 1, 2, 3
),
metricas_articulo as (
    select 'Articulo' as dimension, da.des_articulo as entidad,
           b.id_articulo::text as id_entidad, {m}
    from base b join gold.dim_articulo da on da.id_articulo = b.id_articulo
    group by 1, 2, 3
),
metricas_subcanal as (
    select 'Subcanal' as dimension,
           coalesce(c.subcanal, 'SIN SUBCANAL') as entidad,
           null::text as id_entidad, {m}
    from base b left join clientes c on c.id_cliente = b.id_cliente
    group by 1, 2, 3
),
metricas_dow as (
    select 'Dia de semana' as dimension,
           case b.dow when 1 then 'Lunes' when 2 then 'Martes' when 3 then 'Miercoles'
                      when 4 then 'Jueves' when 5 then 'Viernes' when 6 then 'Sabado'
                      else 'Domingo' end as entidad,
           b.dow::text as id_entidad, {m}
    from base b group by 1, 2, 3
)
select * from metricas_sucursal
union all select * from metricas_fletero
union all select * from metricas_cliente
union all select * from metricas_articulo
union all select * from metricas_subcanal
union all select * from metricas_dow
"""

_METRICAS_RECHAZO = """
           count(*) as n_lineas,
           count(*) filter (where b.cantidades_rechazo > 0) as n_rechazo,
           sum(b.cantidades_rechazo) filter (where b.cantidades_rechazo > 0) as bultos_rechazo,
           sum(-b.subtotal_neto) filter (where b.cantidades_rechazo > 0) as valor_rechazo,
           sum(b.subtotal_neto) filter (where coalesce(b.cantidades_rechazo, 0) = 0) as neto_facturado
"""

# Dimensiones donde la cola es larguisima (11.917 clientes, ~1.500 articulos) y
# hay que recortar para que la hoja sea legible.
DIMENSIONES_LARGAS = ("Cliente", "Articulo")
# Dimension que cubre el universo completo y sirve para el TOTAL GENERAL.
DIMENSION_UNIVERSO_RECHAZO = "Sucursal"


COLUMNAS_SUMABLES_RECHAZO = (
    "Lineas", "Lineas con Rechazo", "Bultos Rechazados",
    "Valor Rechazado Neto (Nominal $)", "Neto Facturado (Nominal $)",
    "Share del Valor Rechazado",
)


def _recortar_ranking(
    bloque: pd.DataFrame,
    columna_valor: str,
    top: int,
    columnas_sumables: tuple[str, ...] = COLUMNAS_SUMABLES_RECHAZO,
) -> pd.DataFrame:
    """Deja el top N por valor y colapsa la cola en una unica fila RESTO.

    Solo se suman los conteos y los importes: las tasas y los estadisticos de la
    cola se RECALCULAN sobre los agregados, porque sumar tasas no significa nada.
    """
    if len(bloque) <= top:
        return bloque
    ordenado = bloque.sort_values(columna_valor, ascending=False)
    cabeza = ordenado.head(top).copy()
    cola = ordenado.tail(len(ordenado) - top)

    fila = {col: np.nan for col in bloque.columns}
    for col in columnas_sumables:
        if col in cola.columns:
            fila[col] = float(pd.to_numeric(cola[col], errors="coerce").fillna(0.0).sum())
    lineas = fila.get("Lineas") or 0.0
    fila["Tasa Rechazo"] = (fila.get("Lineas con Rechazo", 0.0) / lineas) if lineas else np.nan
    fila["Dimension"] = bloque["Dimension"].iloc[0]
    fila["Entidad"] = f"{ETIQUETA_RESTO} ({_num(len(cola))} entidades)"
    fila["Significativo"] = False
    fila["Veredicto"] = "Cola agregada"
    fila["Pareto Acumulado"] = 1.0
    return pd.concat([cabeza, pd.DataFrame([fila])], ignore_index=True)


def resumir_rechazos(
    largo: pd.DataFrame,
    clientes_mostrador: tuple[int, ...] = k.CLIENTES_MOSTRADOR,
    sucursales_cerradas: dict[str, str] | None = None,
    min_lineas: int = MIN_LINEAS_RECHAZO,
    top: int = TOP_RANKING,
) -> pd.DataFrame:
    """Tasa y valor de rechazo por dimension, con z-test y Pareto.

    `largo` trae una fila por (dimension, entidad) con numerador y denominador.
    La tasa se juzga contra la tasa agregada de la red DENTRO de cada dimension,
    que es el unico agrupamiento donde la comparacion tiene sentido.
    """
    if largo.empty:
        return pd.DataFrame(columns=COLUMNAS_RECHAZO)

    sucursales_cerradas = sucursales_cerradas or k.SUCURSALES_CERRADAS
    datos = largo.copy()
    for col in ("n_lineas", "n_rechazo", "bultos_rechazo", "valor_rechazo", "neto_facturado"):
        datos[col] = pd.to_numeric(datos[col], errors="coerce").fillna(0.0)

    bloques = []
    for dimension, grupo in datos.groupby("dimension", sort=False):
        bloque = grupo.copy()
        if bloque.empty:
            continue
        bloque = bloque.rename(
            columns={
                "dimension": "Dimension",
                "entidad": "Entidad",
                "n_lineas": "Lineas",
                "n_rechazo": "Lineas con Rechazo",
                "bultos_rechazo": "Bultos Rechazados",
                "valor_rechazo": "Valor Rechazado Neto (Nominal $)",
                "neto_facturado": "Neto Facturado (Nominal $)",
            }
        )
        # El z-test y los denominadores de Share / Pareto se calculan sobre la
        # dimension COMPLETA, entidades chicas incluidas. Recortarlas ANTES era
        # un error grave: en la corrida real dejaba afuera 13.337 de 14.901
        # clientes y $1.944M de los $3.058M rechazados (el 64%), con lo cual el
        # Share se normalizaba contra un tercio del universo y la concentracion
        # se leia casi tres veces mas alta de lo que es. Ademas la tasa de la
        # red del bloque Cliente daba 4,95% en vez del 5,76% real de la red,
        # asi que cada cliente se juzgaba contra un promedio inventado.
        evaluado = evaluar_proporcion(
            bloque, "Lineas con Rechazo", "Lineas", BRECHA_MINIMA_RECHAZO,
            mayor_es_mejor=False,
            etiqueta_peor="Rechazo alto (significativo)",
            etiqueta_mejor="Rechazo bajo (significativo)",
        )
        evaluado = evaluado.rename(columns={"Tasa": "Tasa Rechazo"})
        if dimension in DIMENSIONES_LARGAS:
            # Con pocas lineas la TASA es ruido, pero el VALOR rechazado es
            # plata real. La fila se queda (para que el bloque cuadre contra el
            # TOTAL GENERAL) y lo unico que se suprime es el veredicto.
            chicas = evaluado["Lineas"] < min_lineas
            evaluado.loc[chicas, "Significativo"] = False
            evaluado.loc[chicas, "Veredicto"] = VEREDICTO_MUESTRA_CHICA
        total_valor = evaluado["Valor Rechazado Neto (Nominal $)"].clip(lower=0).sum()
        evaluado["Share del Valor Rechazado"] = (
            evaluado["Valor Rechazado Neto (Nominal $)"] / total_valor
            if total_valor > 0 else np.nan
        )
        evaluado = evaluado.sort_values("Valor Rechazado Neto (Nominal $)", ascending=False)
        evaluado["Pareto Acumulado"] = (
            evaluado["Share del Valor Rechazado"].cumsum()
        )
        if dimension == "Dia de semana":
            # El Pareto no significa nada sobre siete dias fijos, y ademas la
            # tabla se reordena por dia calendario: se anula para no confundir.
            evaluado["Pareto Acumulado"] = np.nan
            orden = {dia: i for i, dia in enumerate(ORDEN_DIAS)}
            evaluado = evaluado.sort_values("Entidad", key=lambda s: s.map(orden))
        if dimension in DIMENSIONES_LARGAS:
            evaluado = _recortar_ranking(
                evaluado, "Valor Rechazado Neto (Nominal $)", top
            )
        bloques.append(evaluado)

    tabla = pd.concat(bloques, ignore_index=True) if bloques else pd.DataFrame()

    # Marcas de contexto: nadie tiene que accionar una sucursal cerrada ni tratar
    # un mostrador como si fuera un cliente.
    mostrador = {str(cid) for cid in clientes_mostrador}
    notas = []
    for _, fila in tabla.iterrows():
        entidad = str(fila.get("Entidad", ""))
        id_entidad = str(fila.get("id_entidad", ""))
        if entidad in sucursales_cerradas:
            notas.append(f"Sucursal cerrada el {sucursales_cerradas[entidad]}: no accionar")
        elif fila.get("Dimension") == "Cliente" and id_entidad in mostrador:
            notas.append("Cliente mostrador: no es un cliente real, es una caja de venta directa")
        else:
            notas.append("")
    tabla["Nota"] = notas

    universo = datos[datos["dimension"] == DIMENSION_UNIVERSO_RECHAZO]
    if universo.empty:
        universo = datos[datos["dimension"] == datos["dimension"].iloc[0]]
    lineas = float(universo["n_lineas"].sum())
    rechazos = float(universo["n_rechazo"].sum())
    total = {
        "Dimension": "TOTAL",
        "Entidad": ETIQUETA_TOTAL,
        "Lineas": lineas,
        "Lineas con Rechazo": rechazos,
        "Tasa Rechazo": rechazos / lineas if lineas else float("nan"),
        "Tasa Red": rechazos / lineas if lineas else float("nan"),
        "Brecha vs Red": 0.0,
        "z": float("nan"),
        "p-valor": float("nan"),
        "Significativo": False,
        "Veredicto": "Red completa",
        "Bultos Rechazados": float(universo["bultos_rechazo"].sum()),
        "Valor Rechazado Neto (Nominal $)": float(universo["valor_rechazo"].sum()),
        "Neto Facturado (Nominal $)": float(universo["neto_facturado"].sum()),
        "Share del Valor Rechazado": 1.0,
        "Pareto Acumulado": 1.0,
        "Nota": "",
    }
    tabla = pd.concat([tabla, pd.DataFrame([total])], ignore_index=True)
    return tabla.reindex(columns=COLUMNAS_RECHAZO)


# ---------------------------------------------------------------------------
# 3. Devoluciones por producto
# ---------------------------------------------------------------------------
COLUMNAS_DEVOLUCION = [
    "Dimension", "Entidad", "Bultos Vendidos (Bruto)", "Bultos Devueltos",
    "Tasa Devolucion (bultos)", "Bruto Vendido (Nominal $)",
    "Bruto Devuelto (Nominal $)", "Tasa Devolucion (valor)",
    "z Robusto", "Outlier", "Nota",
]

# Se usa gold.fact_ventas y no fact_ventas_contabilidad porque la contable esta
# ~3 meses atrasada. Las filas DVVTA llevan cantidades y facturacion NEGATIVAS,
# de ahi el abs() en el numerador.
SQL_DEVOLUCION = """
with base as materialized (
    select fv.id_sucursal, fv.id_articulo, fv.id_documento,
           date_trunc('month', fv.fecha_comprobante)::date as mes,
           fv.cantidades_total, fv.facturacion_neta
    from gold.fact_ventas fv
    join gold.dim_articulo da on da.id_articulo = fv.id_articulo
    where not fv.anulado
      and fv.id_documento in ('FCVTA', 'DVVTA')
      and fv.fecha_comprobante >= %(desde)s
      and fv.fecha_comprobante <= %(hasta)s
      and da.generico is not null
      and not (da.generico = any(%(no_venta)s))
),
metricas_generico as (
    select 'Generico' as dimension, da.generico as entidad, {m}
    from base b join gold.dim_articulo da on da.id_articulo = b.id_articulo
    group by 1, 2
),
metricas_marca as (
    -- coalesce obligatorio: hay articulos con marca nula y sin esto la hoja
    -- termina con una fila de entidad NaN (24.857 bultos, $97,8M) que el equipo
    -- comercial no puede interpretar.
    select 'Marca' as dimension,
           coalesce(nullif(trim(da.marca), ''), 'SIN MARCA') as entidad, {m}
    from base b join gold.dim_articulo da on da.id_articulo = b.id_articulo
    group by 1, 2
),
metricas_sucursal as (
    select 'Sucursal' as dimension, ds.descripcion as entidad, {m}
    from base b join gold.dim_sucursal ds on ds.id_sucursal = b.id_sucursal
    group by 1, 2
),
metricas_mes as (
    select 'Mes' as dimension, to_char(b.mes, 'YYYY-MM') as entidad, {m}
    from base b group by 1, 2
),
metricas_articulo as (
    -- Sin el coalesce, un solo articulo con marca nula anula toda la
    -- concatenacion (|| con NULL da NULL) y la fila queda sin nombre.
    select 'Articulo' as dimension,
           da.des_articulo || ' ['
             || coalesce(nullif(trim(da.marca), ''), 'SIN MARCA') || ']' as entidad, {m}
    from base b join gold.dim_articulo da on da.id_articulo = b.id_articulo
    group by 1, 2
    having sum(b.cantidades_total) filter (where b.id_documento = 'FCVTA') >= %(piso_bultos)s
)
select * from metricas_generico
union all select * from metricas_marca
union all select * from metricas_sucursal
union all select * from metricas_mes
union all select * from metricas_articulo
"""

_METRICAS_DEVOLUCION = """
           sum(b.cantidades_total) filter (where b.id_documento = 'FCVTA') as bultos_bruto,
           sum(abs(b.cantidades_total)) filter (where b.id_documento = 'DVVTA') as bultos_dev,
           sum(b.facturacion_neta) filter (where b.id_documento = 'FCVTA') as bruto_pesos,
           sum(abs(b.facturacion_neta)) filter (where b.id_documento = 'DVVTA') as dev_pesos
"""

DIMENSION_UNIVERSO_DEVOLUCION = "Generico"


def resumir_devoluciones(
    largo: pd.DataFrame,
    piso_bultos: float = MIN_BULTOS_DEVOLUCION,
    umbral_z: float = Z_ROBUSTO_OUTLIER,
    top: int = TOP_RANKING,
    sucursales_cerradas: dict[str, str] | None = None,
    mes_parcial: str | None = None,
) -> pd.DataFrame:
    """Devoluciones como porcentaje de la venta BRUTA del propio producto.

    La tasa es autorreferencial a proposito: medida en valor absoluto, el ranking
    de devoluciones no es mas que el ranking de los productos que mas se venden.
    Dividiendo por la venta bruta del mismo producto aparece el que esta
    estructuralmente roto y no el que simplemente es grande.
    """
    if largo.empty:
        return pd.DataFrame(columns=COLUMNAS_DEVOLUCION)

    sucursales_cerradas = sucursales_cerradas or k.SUCURSALES_CERRADAS
    datos = largo.copy()
    for col in ("bultos_bruto", "bultos_dev", "bruto_pesos", "dev_pesos"):
        datos[col] = pd.to_numeric(datos[col], errors="coerce").fillna(0.0)

    datos = datos.rename(
        columns={
            "dimension": "Dimension",
            "entidad": "Entidad",
            "bultos_bruto": "Bultos Vendidos (Bruto)",
            "bultos_dev": "Bultos Devueltos",
            "bruto_pesos": "Bruto Vendido (Nominal $)",
            "dev_pesos": "Bruto Devuelto (Nominal $)",
        }
    )
    datos["Tasa Devolucion (bultos)"] = np.where(
        datos["Bultos Vendidos (Bruto)"] > 0,
        datos["Bultos Devueltos"] / datos["Bultos Vendidos (Bruto)"],
        np.nan,
    )
    datos["Tasa Devolucion (valor)"] = np.where(
        datos["Bruto Vendido (Nominal $)"] > 0,
        datos["Bruto Devuelto (Nominal $)"] / datos["Bruto Vendido (Nominal $)"],
        np.nan,
    )
    datos["z Robusto"] = np.nan
    datos["Outlier"] = False

    bloques = []
    for dimension, grupo in datos.groupby("Dimension", sort=False):
        bloque = grupo.copy()
        if dimension == "Articulo":
            bloque = bloque[bloque["Bultos Vendidos (Bruto)"] >= piso_bultos]
            if bloque.empty:
                continue
            # z robusto (mediana + MAD) para que un puñado de SKU extremos no
            # inflen el desvio y terminen escondiendose a si mismos.
            bloque["z Robusto"] = stats.robust_zscore(
                bloque["Tasa Devolucion (bultos)"].to_numpy(dtype=float)
            )
            bloque["Outlier"] = bloque["z Robusto"].abs() >= umbral_z
            bloque = bloque.sort_values("Tasa Devolucion (bultos)", ascending=False).head(top)
        elif dimension == "Mes":
            bloque = bloque.sort_values("Entidad")
        else:
            bloque = bloque.sort_values("Tasa Devolucion (bultos)", ascending=False)
        bloques.append(bloque)

    # Si TODAS las dimensiones quedaron vacias (por ejemplo, solo llegaron
    # articulos por debajo del piso de bultos) no hay frame del que sacar
    # "Entidad": armarlo vacio explicitamente evita el KeyError.
    tabla = (
        pd.concat(bloques, ignore_index=True)
        if bloques
        else pd.DataFrame(columns=COLUMNAS_DEVOLUCION)
    )
    notas_fila = []
    for _, fila in tabla.iterrows():
        entidad = str(fila["Entidad"])
        if entidad in sucursales_cerradas:
            notas_fila.append(f"Sucursal cerrada el {sucursales_cerradas[entidad]}: no accionar")
        elif mes_parcial and fila["Dimension"] == "Mes" and entidad == mes_parcial:
            notas_fila.append(
                "Mes incompleto: la ventana corta antes de fin de mes, la tasa "
                "es comparable pero los volumenes no"
            )
        else:
            notas_fila.append("")
    tabla["Nota"] = notas_fila

    universo = datos[datos["Dimension"] == DIMENSION_UNIVERSO_DEVOLUCION]
    if universo.empty:
        universo = datos[datos["Dimension"] == datos["Dimension"].iloc[0]]
    bultos = float(universo["Bultos Vendidos (Bruto)"].sum())
    devueltos = float(universo["Bultos Devueltos"].sum())
    bruto = float(universo["Bruto Vendido (Nominal $)"].sum())
    dev_pesos = float(universo["Bruto Devuelto (Nominal $)"].sum())
    total = {
        "Dimension": "TOTAL",
        "Entidad": ETIQUETA_TOTAL,
        "Bultos Vendidos (Bruto)": bultos,
        "Bultos Devueltos": devueltos,
        "Tasa Devolucion (bultos)": devueltos / bultos if bultos else float("nan"),
        "Bruto Vendido (Nominal $)": bruto,
        "Bruto Devuelto (Nominal $)": dev_pesos,
        "Tasa Devolucion (valor)": dev_pesos / bruto if bruto else float("nan"),
        "z Robusto": np.nan,
        "Outlier": False,
        "Nota": "",
    }
    tabla = pd.concat([tabla, pd.DataFrame([total])], ignore_index=True)
    return tabla.reindex(columns=COLUMNAS_DEVOLUCION)


# ---------------------------------------------------------------------------
# 4. Cobertura de stock
# ---------------------------------------------------------------------------
COLUMNAS_STOCK = [
    "Estado", "Sucursal", "Articulo", "Generico", "Marca",
    "Stock (bultos)", "Venta 60d (bultos)", "Dias con Venta",
    "Velocidad (bultos/dia)", "Dias de Cobertura",
    "Costo Unitario (Nominal $)", "Valor Stock a Costo (Nominal $)",
    "Es Mercaderia", "SKU con Venta 12m", "Nota",
]

# CASA CENTRAL tiene DOS depositos (1 y 10) que hay que sumar antes de hablar de
# stock por sucursal. fact_stock es una grilla densa (15 depositos x 2.300
# articulos por dia) donde solo el 8,7% de las celdas tiene stock: contar filas
# NO es contar SKU.
SQL_STOCK = """
with ultima as (
    select max(date_stock) as d from gold.fact_stock where date_stock <= %(hasta)s
),
stk as (
    select dd.id_sucursal, fs.id_articulo, sum(fs.cant_bultos) as stock_bultos
    from gold.fact_stock fs
    join gold.dim_deposito dd on dd.id_deposito = fs.id_deposito
    where fs.date_stock = (select d from ultima)
    group by 1, 2
),
vel as (
    select fv.id_sucursal, fv.id_articulo,
           sum(fv.cantidades_total) as bultos_60d,
           count(distinct fv.fecha_comprobante) as ndias
    from gold.fact_ventas fv
    where fv.fecha_comprobante > (select d from ultima) - %(dias_vel)s
      and fv.fecha_comprobante <= (select d from ultima)
      and fv.id_documento = 'FCVTA' and not fv.anulado
    group by 1, 2
),
vivos as (
    select fv.id_articulo, sum(fv.cantidades_total) as bultos_12m
    from gold.fact_ventas fv
    where fv.fecha_comprobante > (select d from ultima) - 365
      and fv.fecha_comprobante <= (select d from ultima)
      and fv.id_documento = 'FCVTA' and not fv.anulado
    group by 1
),
costo as (
    -- Solo facturas vivas: sin el filtro entraban 91 presupuestos (PRVTA) con
    -- un costo medio de $38.752 contra los $16.958 de una factura real, y 3 de
    -- ellos ademas anulados. En un articulo de poco movimiento ese promedio
    -- envenenado duplica la valuacion del capital inmovilizado.
    select id_articulo, avg(precio_compra_neto) as costo
    from gold.fact_ventas_contabilidad
    where fecha_comprobante >= %(desde_costo)s
      and precio_compra_neto > 0
      and id_documento = 'FCVTA'
      and not anulado
    group by 1
)
select (select d from ultima) as fecha_stock,
       ds.descripcion as sucursal, s.id_sucursal, s.id_articulo,
       da.des_articulo as articulo, da.generico, da.marca,
       s.stock_bultos,
       coalesce(v.bultos_60d, 0) as bultos_60d,
       coalesce(v.ndias, 0) as ndias,
       coalesce(w.bultos_12m, 0) as bultos_12m,
       c.costo
from stk s
join gold.dim_sucursal ds on ds.id_sucursal = s.id_sucursal
left join gold.dim_articulo da on da.id_articulo = s.id_articulo
left join vel v on v.id_sucursal = s.id_sucursal and v.id_articulo = s.id_articulo
left join vivos w on w.id_articulo = s.id_articulo
left join costo c on c.id_articulo = s.id_articulo
where s.stock_bultos <> 0 or coalesce(v.bultos_60d, 0) > 0
"""

SQL_MV_QUIEBRE = """
select estado_semaforo, count(*) as pares,
       sum(stock_hoy_bultos) as stock_bultos,
       sum(venta_diaria_bultos) as velocidad
from gold.mv_stock_quiebre
group by 1
"""


def calcular_cobertura(
    pares: pd.DataFrame,
    dias_quiebre: float = k.COBERTURA_QUIEBRE_DIAS,
    dias_sobrestock: float = k.COBERTURA_SOBRESTOCK_DIAS,
    genericos_no_venta: tuple[str, ...] = k.GENERICOS_NO_VENTA,
) -> pd.DataFrame:
    """Dias de cobertura por (sucursal, articulo) y clasificacion del estado.

    Cobertura = stock actual / velocidad diaria de los ultimos 60 dias. El divisor
    es la cantidad de DIAS CON VENTA, no los 60 dias corridos, para que domingos
    y feriados no diluyan artificialmente la velocidad.

    Estados:
      QUIEBRE        rota y no llega a `dias_quiebre` dias.
      SOBRESTOCK     rota pero tiene mas de `dias_sobrestock` dias encima.
      NORMAL         rota dentro de la banda.
      STOCK MUERTO   tiene stock, no vendio en 60 dias, PERO es un SKU vivo
                     (vendio algo en la red en los ultimos 12 meses).
      SIN MOVIMIENTO tiene stock y no vendio nunca: envase retornable, material
                     de marketing, articulo discontinuado. NO es capital muerto
                     recuperable y por eso no entra en la cifra de stock muerto.
    """
    if pares.empty:
        return pd.DataFrame(columns=[*COLUMNAS_STOCK, "id_sucursal", "id_articulo"])

    df = pares.copy()
    for col in ("stock_bultos", "bultos_60d", "ndias", "bultos_12m", "costo"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")

    with np.errstate(divide="ignore", invalid="ignore"):
        df["Velocidad (bultos/dia)"] = np.where(
            (df["bultos_60d"] > 0) & (df["ndias"] > 0),
            df["bultos_60d"] / df["ndias"].replace(0, np.nan),
            np.nan,
        )
        df["Dias de Cobertura"] = np.where(
            df["Velocidad (bultos/dia)"] > 0,
            df["stock_bultos"] / df["Velocidad (bultos/dia)"],
            np.nan,
        )
    df["Valor Stock a Costo (Nominal $)"] = df["stock_bultos"] * df["costo"]

    generico = df["generico"].astype("object")
    df["Es Mercaderia"] = generico.notna() & ~generico.isin(list(genericos_no_venta))
    df["SKU con Venta 12m"] = df["bultos_12m"].fillna(0) > 0

    rota = df["Velocidad (bultos/dia)"] > 0
    estado = np.where(
        rota & (df["Dias de Cobertura"] < dias_quiebre), "QUIEBRE",
        np.where(
            rota & (df["Dias de Cobertura"] > dias_sobrestock), "SOBRESTOCK",
            np.where(
                rota, "NORMAL",
                np.where(df["SKU con Venta 12m"], "STOCK MUERTO", "SIN MOVIMIENTO"),
            ),
        ),
    )
    df["Estado"] = estado

    df = df.rename(
        columns={
            "sucursal": "Sucursal",
            "articulo": "Articulo",
            "generico": "Generico",
            "marca": "Marca",
            "stock_bultos": "Stock (bultos)",
            "bultos_60d": "Venta 60d (bultos)",
            "ndias": "Dias con Venta",
            "costo": "Costo Unitario (Nominal $)",
        }
    )
    # El stock del sistema puede venir NEGATIVO (sobreventa o ajuste pendiente).
    # Esos pares arrastran un valor a costo negativo que descuenta capital que
    # si existe, asi que van marcados en vez de quedar mudos en la hoja.
    df["Nota"] = np.where(
        df["Stock (bultos)"] < 0,
        "Stock negativo en el sistema (sobreventa o ajuste pendiente): "
        "descuenta capital en los totales",
        np.where(
            df["Costo Unitario (Nominal $)"].isna(),
            "Sin costo de compra: el capital de este par queda subvaluado",
            "",
        ),
    )
    return df


def resumir_stock(cobertura: pd.DataFrame) -> pd.DataFrame:
    """Tabla de stock: solo mercaderia vendible, ordenada por urgencia, con TOTAL.

    Los generico no vendibles se sacan de la tabla porque envases retornables y
    material de marketing representan el 46% del valor aparente del inventario y
    convierten cualquier veredicto de capital en un numero falso.
    """
    if cobertura.empty:
        return pd.DataFrame(columns=COLUMNAS_STOCK)

    tabla = cobertura[cobertura["Es Mercaderia"]].copy()
    if tabla.empty:
        return pd.DataFrame(columns=COLUMNAS_STOCK)

    orden = {estado: i for i, estado in enumerate(ORDEN_ESTADO_STOCK)}
    tabla["_orden"] = tabla["Estado"].map(orden).fillna(len(orden))
    tabla["_peso"] = np.where(
        tabla["Estado"].eq("QUIEBRE"),
        tabla["Velocidad (bultos/dia)"].fillna(0.0),
        tabla["Valor Stock a Costo (Nominal $)"].fillna(0.0),
    )
    tabla = tabla.sort_values(["_orden", "_peso"], ascending=[True, False])

    stock_total = float(tabla["Stock (bultos)"].sum())
    velocidad_total = float(tabla["Velocidad (bultos/dia)"].sum(skipna=True))
    total = {
        "Estado": "TOTAL",
        "Sucursal": ETIQUETA_TOTAL,
        "Articulo": ETIQUETA_TOTAL,
        "Generico": "",
        "Marca": "",
        "Stock (bultos)": stock_total,
        "Venta 60d (bultos)": float(tabla["Venta 60d (bultos)"].sum()),
        "Dias con Venta": np.nan,
        "Velocidad (bultos/dia)": velocidad_total,
        # Cobertura agregada de la red: stock total sobre velocidad total. No es
        # el promedio de las coberturas individuales, que estaria dominado por
        # los articulos lentisimos.
        "Dias de Cobertura": stock_total / velocidad_total if velocidad_total > 0 else np.nan,
        "Costo Unitario (Nominal $)": np.nan,
        "Valor Stock a Costo (Nominal $)": float(
            tabla["Valor Stock a Costo (Nominal $)"].sum(skipna=True)
        ),
        "Es Mercaderia": True,
        "SKU con Venta 12m": True,
        "Nota": "Solo mercaderia vendible (sin envases ni marketing)",
    }
    tabla = pd.concat([tabla, pd.DataFrame([total])], ignore_index=True)
    return tabla.reindex(columns=COLUMNAS_STOCK)


# ---------------------------------------------------------------------------
# 5. Economia de rutas
# ---------------------------------------------------------------------------
COLUMNAS_RUTAS = [
    "Clave Ruta", "Sucursal", "Ruta", "Descripcion Ruta", "Preventista",
    "Visitas Facturadas", "Clientes", "Dias Activos", "Bultos",
    "Neto (Nominal $)", "Bruto (Nominal $)",
    "Drop Size (bultos/visita)", "Drop Mediano (bultos/visita)",
    "Neto por Visita (Nominal $)", "Lineas por Visita",
    "Clientes Mostrador", "Densidad", "Nota",
]

# id_ruta NO es unico global: el 100 'DIRECTA' existe en 8 sucursales con drop
# size de 3,34 a 72,32 bultos. La clave real es (id_sucursal, id_ruta_fv1) y
# dim_cliente se joinea por (id_cliente, id_sucursal). Sin eso el analisis de
# rutas es directamente falso.
SQL_RUTAS = """
with facturas as (
    select fv.id_sucursal, fv.id_cliente, fv.fecha_comprobante,
           fv.id_documento, fv.letra, fv.serie, fv.nro_doc,
           sum(fv.cantidades_total) as bultos,
           sum(fv.subtotal_neto)    as neto,
           sum(fv.facturacion_neta) as bruto,
           count(*) as lineas
    from gold.fact_ventas fv
    join gold.dim_articulo da on da.id_articulo = fv.id_articulo
    where fv.fecha_comprobante >= %(desde)s
      and fv.fecha_comprobante <= %(hasta)s
      and fv.id_documento = 'FCVTA' and not fv.anulado
      and da.generico is not null
      and not (da.generico = any(%(no_venta)s))
    group by 1, 2, 3, 4, 5, 6, 7
)
select ds.descripcion as sucursal,
       f.id_sucursal,
       dc.id_ruta_fv1,
       max(dc.des_ruta_fv1)     as des_ruta,
       max(dc.des_personal_fv1) as preventista,
       count(*)                            as visitas,
       count(distinct f.id_cliente)        as clientes,
       count(distinct f.fecha_comprobante) as dias_activos,
       count(distinct f.id_cliente) filter (where f.id_cliente = any(%(mostrador)s)) as clientes_mostrador,
       sum(f.bultos) as bultos,
       sum(f.neto)   as neto,
       sum(f.bruto)  as bruto,
       avg(f.lineas) as lineas_x_visita,
       percentile_cont(0.5) within group (order by f.bultos) as mediana_bultos_visita
from facturas f
join gold.dim_cliente dc
  on dc.id_cliente = f.id_cliente
 and dc.id_sucursal = f.id_sucursal     -- REGLA DE ORO: clave compuesta
join gold.dim_sucursal ds on ds.id_sucursal = f.id_sucursal
where dc.id_ruta_fv1 is not null
group by 1, 2, 3
having count(*) >= %(min_visitas)s
"""

MIN_VISITAS_RUTA = 200


def resumir_rutas(
    rutas: pd.DataFrame,
    sucursales_cerradas: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Economia por ruta: drop size y cuartil de densidad.

    El drop size (bultos por visita facturada) es el proxy directo del costo de
    servir: una ruta con 1 bulto por parada consume el mismo dia de camion que
    una de 10. Se reporta el promedio Y la mediana porque la distribucion es muy
    asimetrica a la derecha y el promedio miente en las rutas con un cliente
    grande adentro.
    """
    if rutas.empty:
        return pd.DataFrame(columns=COLUMNAS_RUTAS)

    sucursales_cerradas = sucursales_cerradas or k.SUCURSALES_CERRADAS
    df = rutas.copy()
    for col in ("visitas", "clientes", "dias_activos", "bultos", "neto", "bruto",
                "lineas_x_visita", "mediana_bultos_visita", "clientes_mostrador"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")

    df["Drop Size (bultos/visita)"] = np.where(
        df["visitas"] > 0, df["bultos"] / df["visitas"], np.nan
    )
    df["Neto por Visita (Nominal $)"] = np.where(
        df["visitas"] > 0, df["neto"] / df["visitas"], np.nan
    )
    corte_p25 = float(np.nanpercentile(df["Drop Size (bultos/visita)"], 25))
    df["Densidad"] = np.where(
        df["Drop Size (bultos/visita)"] <= corte_p25,
        "Baja densidad (cuartil inferior)",
        "Normal",
    )
    df["Clave Ruta"] = (
        df["sucursal"].astype(str) + " / " + df["id_ruta_fv1"].astype("Int64").astype(str)
    )
    df["Nota"] = [
        f"Sucursal cerrada el {sucursales_cerradas[s]}: no accionar"
        if str(s) in sucursales_cerradas else ""
        for s in df["sucursal"]
    ]
    df = df.rename(
        columns={
            "sucursal": "Sucursal",
            "id_ruta_fv1": "Ruta",
            "des_ruta": "Descripcion Ruta",
            "preventista": "Preventista",
            "visitas": "Visitas Facturadas",
            "clientes": "Clientes",
            "dias_activos": "Dias Activos",
            "bultos": "Bultos",
            "neto": "Neto (Nominal $)",
            "bruto": "Bruto (Nominal $)",
            "lineas_x_visita": "Lineas por Visita",
            "mediana_bultos_visita": "Drop Mediano (bultos/visita)",
            "clientes_mostrador": "Clientes Mostrador",
        }
    )
    df = df.sort_values("Drop Size (bultos/visita)")

    visitas = float(df["Visitas Facturadas"].sum())
    bultos = float(df["Bultos"].sum())
    neto = float(df["Neto (Nominal $)"].sum())
    total = {
        "Clave Ruta": ETIQUETA_TOTAL,
        "Sucursal": ETIQUETA_TOTAL,
        "Ruta": pd.NA,
        "Descripcion Ruta": "",
        "Preventista": "",
        "Visitas Facturadas": visitas,
        "Clientes": float(df["Clientes"].sum()),
        "Dias Activos": np.nan,
        "Bultos": bultos,
        "Neto (Nominal $)": neto,
        "Bruto (Nominal $)": float(df["Bruto (Nominal $)"].sum()),
        "Drop Size (bultos/visita)": bultos / visitas if visitas else np.nan,
        "Drop Mediano (bultos/visita)": np.nan,
        "Neto por Visita (Nominal $)": neto / visitas if visitas else np.nan,
        "Lineas por Visita": np.nan,
        "Clientes Mostrador": float(df["Clientes Mostrador"].sum()),
        "Densidad": "",
        "Nota": (
            "Clientes sumados por ruta: un cliente puede aparecer en mas de una ruta "
            "y por eso el total no es el padron unico"
        ),
    }
    df = pd.concat([df, pd.DataFrame([total])], ignore_index=True)
    return df.reindex(columns=COLUMNAS_RUTAS)


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------
def peor_rezagado(tabla: pd.DataFrame) -> pd.Series | None:
    """La entidad con la MAYOR brecha negativa de OTIF, o None si no hay ninguna.

    Hay que buscarla por brecha y no por posicion: la tabla de SLA trae el
    bloque de sucursales antes que el de fleteros, asi que la primera fila
    rezagada es siempre una sucursal. En la corrida real eso hacia que la alerta
    acusara a SUCURSAL CAFAYATE (-6,6 pp) y dejara sin nombrar al fletero 63
    (-21,8 pp, z=-57,5), que es el problema de verdad.
    """
    if tabla.empty or "Veredicto" not in tabla.columns:
        return None
    rezagados = tabla[tabla["Veredicto"] == VEREDICTO_REZAGADO]
    if rezagados.empty:
        return None
    return rezagados.nsmallest(1, "Brecha vs Red").iloc[0]


def _fila_total(tabla: pd.DataFrame, columna: str) -> pd.Series | None:
    """Devuelve la fila TOTAL GENERAL de una tabla, o None si no esta."""
    if tabla.empty or columna not in tabla.columns:
        return None
    coincidencias = tabla[tabla[columna].astype(str) == ETIQUETA_TOTAL]
    return coincidencias.iloc[-1] if not coincidencias.empty else None


def _valor(fila, columna, defecto=float("nan")):
    if fila is None or columna not in fila.index:
        return defecto
    valor = fila[columna]
    return defecto if pd.isna(valor) else float(valor)


def build(ctx: AnalysisContext) -> AnalysisResult:
    """Corre la familia logistica completa. Nunca levanta excepcion."""
    resultado = AnalysisResult(name=NOMBRE)
    notas = resultado.notes
    alertas = resultado.alerts
    headlines = resultado.headlines

    no_venta = list(k.GENERICOS_NO_VENTA)
    hasta = ctx.hasta

    notas.append(
        "Toda cifra en pesos es NOMINAL en ARS. Con la inflacion argentina las "
        "series en pesos NO son comparables entre periodos: las comparaciones "
        "interanuales de esta familia se hacen siempre en bultos."
    )
    notas.append(
        "facturacion_neta es BRUTO a precio de lista y subtotal_neto es el NETO "
        "(neto = bruto - descuentos). Cada columna monetaria lleva la etiqueta."
    )
    notas.append(
        "Se excluyen de todo volumen los generico no vendibles "
        f"({', '.join(no_venta)}) y los pseudo-articulos sin generico (troqueles, "
        "tapas promocionales): son material promocional y envase retornable."
    )

    # -- 1. SLA ------------------------------------------------------------
    tabla_sla = pd.DataFrame()
    try:
        desde_c, hasta_c = ventana_contabilidad(hasta, ctx.meses_ventana)
        histograma = ctx.sql(
            SQL_SLA,
            {
                "desde": desde_c.isoformat(),
                "hasta": hasta_c.isoformat(),
                "lead_min": LEAD_MINIMO_DIAS,
                "lead_max": LEAD_MAXIMO_DIAS,
            },
        )
        tabla_sla = resumir_sla(histograma)
        resultado.tables["sla"] = tabla_sla
        notas.append(
            f"Nivel de servicio medido entre {desde_c.isoformat()} y {hasta_c.isoformat()} "
            f"sobre gold.fact_ventas_contabilidad, que corta el "
            f"{k.FECHA_CORTE_CONTABILIDAD} (~3 meses de atraso del ETL contable). "
            "La ventana termina en el ultimo mes COMPLETO: el mes de corte es un "
            "muñon de 5 dias cuyo OTIF de 53,6% es un artefacto de truncamiento."
        )
        notas.append(
            "El SLA se calcula a nivel FACTURA (id_documento, letra, serie, nro_doc, "
            "id_sucursal): una factura de 40 renglones es UNA entrega. Lead time = "
            "fecha_entrega - fecha_pedido, acotado a 0..60 dias (hay 131 filas con "
            "entrega anterior al pedido, errores de carga)."
        )
        notas.append(
            f"Fleteros sentinela excluidos {FLETEROS_SENTINELA}: no son "
            "transportistas sino venta de mostrador / retiro en deposito "
            "(100,00% y 99,84% de cumplimiento con lead medio de 0,008 y 0,027 dias). "
            "Dejarlos adentro infla el OTIF de la red casi un punto."
        )
        notas.append(
            "El z-test contra la tasa de la red se complementa con un piso de "
            f"significancia practica de {BRECHA_MINIMA_OTIF:.0%} de brecha: con ~20.000 "
            "entregas por fletero el test declara significativo casi todo y la lista "
            "deja de ser accionable. Solo se llama rezagado a quien cumple ambas."
        )
        notas.append(
            "No existe gold.dim_fletero: id_fletero_carga es un entero pelado sin "
            "nombre, empresa ni tarifa. Ademas 70 de 71 fleteros operan en UNA sola "
            "sucursal, asi que la comparacion entre fleteros arrastra la dificultad "
            "del territorio; leerla dentro de cada sucursal."
        )
        notas.append(
            "fecha_entrega esta nula en ~5,5% de las filas. El lead time es "
            "condicional a que la entrega se haya registrado, lo que podria "
            "correlacionar con las entregas problematicas."
        )
    except Exception as exc:  # pragma: no cover - depende de la BD
        notas.append(f"No se pudo calcular el nivel de servicio: {exc}")

    # -- 2. Rechazos -------------------------------------------------------
    tabla_rechazos = pd.DataFrame()
    try:
        desde_c, hasta_c = ventana_contabilidad(hasta, ctx.meses_ventana)
        largo = ctx.sql(
            SQL_RECHAZO.format(m=_METRICAS_RECHAZO),
            {
                "desde": desde_c.isoformat(),
                "hasta": hasta_c.isoformat(),
                "no_venta": no_venta,
                "sentinelas": list(FLETEROS_SENTINELA),
            },
        )
        tabla_rechazos = resumir_rechazos(largo)
        resultado.tables["rechazos"] = tabla_rechazos
        notas.append(
            "ESTRUCTURAL: cantidades_rechazo esta poblado UNICAMENTE en documentos "
            "DVVTA (516.189 de 516.297 filas DVVTA y exactamente 0 de 6.964.475 "
            "filas FCVTA). En este esquema rechazo y devolucion son el MISMO evento: "
            "cualquier consulta que filtre cantidades_rechazo > 0 sobre facturas "
            "devuelve el conjunto vacio."
        )
        notas.append(
            "La tasa de rechazo es lineas con rechazo sobre el total de lineas "
            "(FCVTA + DVVTA) de la ventana. El valor rechazado es NETO "
            "(subtotal_neto con signo invertido)."
        )
        notas.append(
            f"En las dimensiones largas (Cliente, Articulo) la tasa de la red, el "
            f"Share del Valor Rechazado y el Pareto se calculan sobre el universo "
            f"COMPLETO de la dimension, no sobre las entidades grandes. Las que "
            f"tienen menos de {_num(MIN_LINEAS_RECHAZO)} lineas siguen sumando su "
            "valor pero no reciben veredicto, porque su tasa es ruido. Recortar "
            "antes de normalizar dejaba afuera dos tercios del valor rechazado por "
            "cliente y exageraba la concentracion casi tres veces."
        )
        notas.append(
            f"Las dimensiones Cliente y Articulo se muestran recortadas al top "
            f"{TOP_RANKING} por valor rechazado mas una fila {ETIQUETA_RESTO} que "
            "agrega la cola: el bloque cuadra igual contra el TOTAL GENERAL."
        )
        notas.append(
            "El codigo id_rechazo esta poblado y discrimina bien, pero NO existe "
            "tabla de dimension para el en todo el esquema gold: los 26 codigos no "
            "se pueden interpretar. Decodificarlos es la brecha de metadatos de "
            "mayor apalancamiento de esta familia."
        )
    except Exception as exc:  # pragma: no cover
        notas.append(f"No se pudo calcular el analisis de rechazos: {exc}")

    # -- 3. Devoluciones ---------------------------------------------------
    tabla_devoluciones = pd.DataFrame()
    try:
        desde_h = alinear_a_mes_completo(
            _restar_meses(hasta, ctx.meses_historia)
        ).isoformat()
        mes_parcial = None if _es_fin_de_mes(hasta) else hasta.strftime("%Y-%m")
        largo = ctx.sql(
            SQL_DEVOLUCION.format(m=_METRICAS_DEVOLUCION),
            {
                "desde": desde_h,
                "hasta": hasta.isoformat(),
                "no_venta": no_venta,
                "piso_bultos": MIN_BULTOS_DEVOLUCION,
            },
        )
        tabla_devoluciones = resumir_devoluciones(largo, mes_parcial=mes_parcial)
        resultado.tables["devoluciones"] = tabla_devoluciones
        notas.append(
            f"Devoluciones medidas sobre gold.fact_ventas entre {desde_h} y "
            f"{hasta.isoformat()} (~{ctx.meses_historia} meses). Se usa fact_ventas y "
            "no la contable porque esta ultima esta ~3 meses atrasada. La ventana "
            "arranca el 1 de un mes para que el primer punto de la serie mensual "
            "no sea un muñon de pocos dias"
            + (
                f"; el ultimo mes ({mes_parcial}) SI esta incompleto y va marcado "
                "en la columna Nota."
                if mes_parcial
                else "."
            )
        )
        notas.append(
            "La tasa de devolucion de un producto se mide contra la venta BRUTA de "
            "ESE MISMO producto. Medida en valor absoluto, el ranking de "
            "devoluciones no seria mas que el ranking de los productos que mas se "
            f"venden. Piso de {_num(MIN_BULTOS_DEVOLUCION)} bultos brutos para que "
            "la tasa por articulo signifique algo."
        )
        notas.append(
            "Los outliers de devolucion se marcan con z robusto (mediana + MAD "
            f"escalada, |z| >= {Z_ROBUSTO_OUTLIER}) y no con z clasico: un puñado de "
            "SKU extremos inflaria el desvio estandar y terminaria escondiendose a "
            "si mismo."
        )
    except Exception as exc:  # pragma: no cover
        notas.append(f"No se pudo calcular el analisis de devoluciones: {exc}")

    # -- 4. Stock ----------------------------------------------------------
    tabla_stock = pd.DataFrame()
    cobertura = pd.DataFrame()
    try:
        pares = ctx.sql(
            SQL_STOCK,
            {
                "hasta": hasta.isoformat(),
                "dias_vel": DIAS_VELOCIDAD,
                "desde_costo": _restar_meses(hasta, 12).isoformat(),
            },
        )
        cobertura = calcular_cobertura(pares)
        tabla_stock = resumir_stock(cobertura)
        resultado.tables["stock"] = tabla_stock
        fecha_stock = (
            str(pares["fecha_stock"].iloc[0]) if not pares.empty else "desconocida"
        )
        notas.append(
            f"Cobertura de stock sobre la foto del {fecha_stock}. "
            f"gold.fact_stock arranca cerca de {k.FECHA_INICIO_STOCK} (el primer "
            "snapshot medido es del 2026-02-08): NO hay historia anterior, por lo "
            "tanto esta familia NO reporta rotacion historica, curvas de "
            "antiguedad ni evolucion de inventario. Solo la foto actual."
        )
        notas.append(
            f"Dias de cobertura = stock / velocidad diaria de los ultimos "
            f"{DIAS_VELOCIDAD} dias, donde el divisor es la cantidad de DIAS CON "
            "VENTA y no los dias corridos, para que domingos y feriados no diluyan "
            "la velocidad. En articulos muy lentos ese divisor es chico y la "
            "cobertura se vuelve inestable: el conjunto de sobrestock es mas robusto "
            "que el de quiebre."
        )
        notas.append(
            "CASA CENTRAL mapea a DOS depositos (1 y 10) que se suman antes de "
            "hablar de stock por sucursal. fact_stock es una grilla densa "
            "(15 depositos x ~2.300 articulos por dia) donde solo el 8,7% de las "
            "celdas tiene stock: contar filas de fact_stock NO es contar SKU."
        )
        notas.append(
            "El costo sale de avg(precio_compra_neto) de los ultimos 12 meses de la "
            "tabla contable, porque gold.fact_precio_vigente, fact_precio_historico "
            "y dim_lista_precio estan VACIAS. PERNOD RICARD no tiene "
            "precio_compra_neto utilizable, asi que su capital queda sin valuar y "
            "el sobrestock esta subestimado."
        )
    except Exception as exc:  # pragma: no cover
        notas.append(f"No se pudo calcular la cobertura de stock: {exc}")

    # Contraste con la vista materializada que ya existe en gold.
    try:
        mv = ctx.sql(SQL_MV_QUIEBRE)
        pares_mv = int(pd.to_numeric(mv["pares"], errors="coerce").fillna(0).sum())
        semaforo = ", ".join(
            f"{fila.estado_semaforo} {int(fila.pares)}" for fila in mv.itertuples()
        )
        notas.append(
            f"gold.mv_stock_quiebre SI existe y tiene {_num(pares_mv)} pares "
            f"({semaforo}). Es lo que su nombre sugiere y resuelve bien el rollup "
            "deposito->sucursal y el divisor de dias habiles, pero NO reemplaza este "
            "analisis: (a) su velocidad usa solo la venta del mes en curso, asi que "
            "los primeros dias de cada mes es violentamente inestable frente a la "
            "ventana movil de 60 dias; (b) no trae costo, asi que no puede valuar el "
            "capital inmovilizado; (c) no expone dias de cobertura ni tiene concepto "
            "de sobrestock (todo lo mayor a 30 dias es VERDE, que es exactamente al "
            "reves del problema de capital); (d) depende de CURRENT_DATE, asi que no "
            "es reproducible historicamente. Se usa como control cruzado, no como "
            "fuente."
        )
    except Exception as exc:  # pragma: no cover
        notas.append(f"No se pudo leer gold.mv_stock_quiebre: {exc}")

    # -- 5. Rutas ----------------------------------------------------------
    tabla_rutas = pd.DataFrame()
    try:
        desde_v = ctx.desde(ctx.meses_ventana)
        rutas = ctx.sql(
            SQL_RUTAS,
            {
                "desde": desde_v,
                "hasta": hasta.isoformat(),
                "no_venta": no_venta,
                "mostrador": list(k.CLIENTES_MOSTRADOR),
                "min_visitas": MIN_VISITAS_RUTA,
            },
        )
        tabla_rutas = resumir_rutas(rutas)
        resultado.tables["rutas"] = tabla_rutas
        notas.append(
            f"Economia de rutas entre {desde_v} y {hasta.isoformat()}, sobre rutas "
            f"con al menos {MIN_VISITAS_RUTA} visitas facturadas. Una visita es una "
            "FACTURA, no una linea."
        )
        notas.append(
            "REGLA DE ORO aplicada: id_ruta NO es unico global (el 100 'DIRECTA' "
            "existe en 8 sucursales con drop size de 3,34 a 72,32 bultos, y 30 de 99 "
            "ids se repiten entre sucursales). La clave es (id_sucursal, id_ruta_fv1) "
            "y dim_cliente se joinea por (id_cliente, id_sucursal)."
        )
        notas.append(
            "Se reporta el drop size promedio Y el mediano: la distribucion de "
            "bultos por visita es muy asimetrica a la derecha y el promedio miente "
            "en las rutas que tienen un cliente grande adentro."
        )
    except Exception as exc:  # pragma: no cover
        notas.append(f"No se pudo calcular la economia de rutas: {exc}")

    notas.append(
        f"Clientes mostrador marcados y no eliminados ({len(k.CLIENTES_MOSTRADOR)} "
        "ids): son cajas de venta directa, no clientes reales, pero su facturacion "
        "tiene que seguir cuadrando contra los totales."
    )
    if k.SUCURSALES_CERRADAS:
        cerradas = ", ".join(f"{s} ({f})" for s, f in k.SUCURSALES_CERRADAS.items())
        notas.append(
            f"Sucursales cerradas marcadas en las tablas: {cerradas}. Aparecen para "
            "que el numero cuadre, pero no hay que accionarlas."
        )
    # -- Headlines ---------------------------------------------------------
    fila_sla = _fila_total(tabla_sla, "Entidad")
    if fila_sla is not None:
        headlines.append(
            Headline(
                label="OTIF (entregas en <= 1 dia)",
                value=_valor(fila_sla, "OTIF (<=1 dia)"),
                number_format="0.0%",
                note=(
                    f"{_num(_valor(fila_sla, 'Entregas'))} entregas a nivel factura "
                    "(sin fleteros sentinela)"
                ),
                higher_is_better=True,
            )
        )
        headlines.append(
            Headline(
                label="Lead time p90 (dias)",
                value=_valor(fila_sla, "Lead p90 (dias)"),
                number_format="#,##0.0",
                note="9 de cada 10 entregas llegan dentro de este plazo",
                higher_is_better=False,
            )
        )

    fila_rech = _fila_total(tabla_rechazos, "Entidad")
    if fila_rech is not None:
        headlines.append(
            Headline(
                label="Valor rechazado (neto nominal)",
                value=_valor(fila_rech, "Valor Rechazado Neto (Nominal $)"),
                number_format="$ #,##0",
                note=f"ventana contable de {ctx.meses_ventana} meses; ARS nominales",
                higher_is_better=False,
            )
        )

    fila_dev = _fila_total(tabla_devoluciones, "Entidad")
    if fila_dev is not None:
        headlines.append(
            Headline(
                label="Tasa de devolucion (bultos)",
                value=_valor(fila_dev, "Tasa Devolucion (bultos)"),
                number_format="0.00%",
                note=(
                    "bultos devueltos sobre bultos brutos vendidos en "
                    f"{ctx.meses_historia} meses"
                ),
                higher_is_better=False,
            )
        )

    if not cobertura.empty:
        mercaderia = cobertura[cobertura["Es Mercaderia"]]
        quiebre = mercaderia[mercaderia["Estado"] == "QUIEBRE"]
        sobrestock = mercaderia[mercaderia["Estado"] == "SOBRESTOCK"]
        vel_riesgo = float(quiebre["Velocidad (bultos/dia)"].sum())
        headlines.append(
            Headline(
                label="SKU en riesgo de quiebre",
                value=int(len(quiebre)),
                number_format="#,##0",
                note=(
                    f"pares sucursal-articulo con menos de {k.COBERTURA_QUIEBRE_DIAS} "
                    f"dias de cobertura; mueven {_num(vel_riesgo)} bultos por dia"
                ),
                higher_is_better=False,
            )
        )
        headlines.append(
            Headline(
                label="Capital inmovilizado en sobrestock",
                value=float(sobrestock["Valor Stock a Costo (Nominal $)"].sum(skipna=True)),
                number_format="$ #,##0",
                note=(
                    f"{len(sobrestock)} pares con mas de "
                    f"{k.COBERTURA_SOBRESTOCK_DIAS} dias de cobertura; valuados a costo nominal"
                ),
                higher_is_better=False,
            )
        )

    # -- Alertas -----------------------------------------------------------
    if not tabla_sla.empty:
        rezagados = tabla_sla[tabla_sla["Veredicto"] == VEREDICTO_REZAGADO]
        peor = peor_rezagado(tabla_sla)
        if peor is not None:
            fleteros = rezagados[rezagados["Nivel"] == "Fletero"]
            # Una sucursal no se lee "de si misma"; el fletero si arrastra su
            # territorio y por eso lleva la sucursal al lado.
            donde = f" de {peor['Sucursal']}" if peor["Nivel"] == "Fletero" else ""
            alertas.append(
                Alert(
                    severity="alta",
                    title="Rezagados de servicio con evidencia estadistica",
                    detail=(
                        f"{len(rezagados)} entidades ({len(fleteros)} fleteros) estan "
                        f"por debajo del OTIF de la red de forma significativa y con al "
                        f"menos {_pct(BRECHA_MINIMA_OTIF, 0)} de brecha. La peor es "
                        f"{peor['Entidad']}{donde}: entrega el "
                        f"{_pct(peor['OTIF (<=1 dia)'])} dentro del dia contra el "
                        f"{_pct(peor['Tasa Red'])} de la red "
                        f"(brecha de {_num(peor['Brecha vs Red'] * 100, 1)} puntos, "
                        f"z={_num(peor['z'], 1)}) sobre {_num(peor['Entregas'])} entregas "
                        f"que mueven {_pesos(peor['Neto Facturado (Nominal $)'])} netos "
                        "nominales."
                    ),
                    amount=float(rezagados["Neto Facturado (Nominal $)"].sum()),
                )
            )
        ruido = tabla_sla[tabla_sla["Veredicto"] == "Significativo pero sin impacto practico"]
        if not ruido.empty:
            alertas.append(
                Alert(
                    severity="info",
                    title="La significancia estadistica sola no alcanza para accionar",
                    detail=(
                        f"{len(ruido)} entidades dan significativas en el z-test pero su "
                        f"brecha contra la red no llega a {_pct(BRECHA_MINIMA_OTIF, 0)}. "
                        "Con decenas de miles de entregas el test detecta diferencias de "
                        "dos puntos: sin el piso de efecto practico la lista de rezagados "
                        "seria casi toda la flota y no serviria para decidir nada."
                    ),
                )
            )

    if not tabla_rechazos.empty:
        clientes = tabla_rechazos[tabla_rechazos["Dimension"] == "Cliente"]
        clientes = clientes[~clientes["Entidad"].astype(str).str.startswith(ETIQUETA_RESTO)]
        if not clientes.empty:
            top10 = clientes.nlargest(min(10, len(clientes)), "Valor Rechazado Neto (Nominal $)")
            alertas.append(
                Alert(
                    severity="alta",
                    title="El rechazo esta concentrado en un puñado de cuentas",
                    detail=(
                        f"Los {len(top10)} clientes con mas devolucion concentran "
                        f"{_pesos(top10['Valor Rechazado Neto (Nominal $)'].sum())} netos "
                        f"nominales: el {_pct(top10['Share del Valor Rechazado'].sum(), 1)} "
                        "de todo el valor rechazado por clientes en la ventana. Es una "
                        "conversacion de credito y cobranzas con unas pocas cuentas y no "
                        "un programa de flota."
                    ),
                    amount=float(top10["Valor Rechazado Neto (Nominal $)"].sum()),
                )
            )
        sucursales = tabla_rechazos[
            (tabla_rechazos["Dimension"] == "Sucursal")
            & (tabla_rechazos["Veredicto"] == "Rechazo alto (significativo)")
        ]
        if not sucursales.empty:
            peor = sucursales.nlargest(1, "Tasa Rechazo").iloc[0]
            alertas.append(
                Alert(
                    severity="alta",
                    title="Sucursal con rechazo significativamente alto",
                    detail=(
                        f"{peor['Entidad']} rechaza el {_pct(peor['Tasa Rechazo'])} de sus "
                        f"lineas contra el {_pct(peor['Tasa Red'])} de la red "
                        f"(z={_num(peor['z'], 1)} sobre {_num(peor['Lineas'])} lineas) y "
                        f"acumula {_pesos(peor['Valor Rechazado Neto (Nominal $)'])} netos "
                        "nominales devueltos."
                    ),
                    amount=float(peor["Valor Rechazado Neto (Nominal $)"]),
                )
            )
        dow = tabla_rechazos[tabla_rechazos["Dimension"] == "Dia de semana"]
        if len(dow) >= 2:
            peor_dia = dow.nlargest(1, "Tasa Rechazo").iloc[0]
            mejor_dia = dow.nsmallest(1, "Tasa Rechazo").iloc[0]
            alertas.append(
                Alert(
                    severity="media",
                    title="El rechazo tiene firma de dia de semana",
                    detail=(
                        f"{peor_dia['Entidad']} rechaza el {_pct(peor_dia['Tasa Rechazo'])} "
                        f"de sus lineas contra el {_pct(mejor_dia['Tasa Rechazo'])} de "
                        f"{mejor_dia['Entidad']}, con "
                        f"{_pesos(peor_dia['Valor Rechazado Neto (Nominal $)'])} netos "
                        "nominales del peor dia. Una brecha asi entre dias apunta a un "
                        "defecto de carga o de ruteo y no a la demanda."
                    ),
                    amount=float(peor_dia["Valor Rechazado Neto (Nominal $)"]),
                )
            )
        cerradas = tabla_rechazos[
            tabla_rechazos["Nota"].astype(str).str.startswith("Sucursal cerrada")
        ]
        if not cerradas.empty:
            fila = cerradas.iloc[0]
            alertas.append(
                Alert(
                    severity="info",
                    title="Hay una sucursal cerrada dentro del ranking de rechazos",
                    detail=(
                        f"{fila['Entidad']} figura con {_pct(fila['Tasa Rechazo'])} de "
                        f"rechazo sobre {_num(fila['Lineas'])} lineas "
                        f"({fila['Veredicto']}), pero es una sucursal cerrada. Esta en la "
                        "tabla para que los totales cuadren; no hay nada que accionar ahi."
                    ),
                )
            )

    if not tabla_devoluciones.empty:
        outliers = tabla_devoluciones[tabla_devoluciones["Outlier"].fillna(False).astype(bool)]
        if not outliers.empty:
            peor = outliers.nlargest(1, "Tasa Devolucion (bultos)").iloc[0]
            alertas.append(
                Alert(
                    severity="alta",
                    title="Productos rotos por tasa propia, no por tamaño",
                    detail=(
                        f"{len(outliers)} articulos superan un z robusto de "
                        f"{_num(Z_ROBUSTO_OUTLIER, 1)} sobre su propia tasa de devolucion. "
                        f"El peor es {peor['Entidad']}: vuelve el "
                        f"{_pct(peor['Tasa Devolucion (bultos)'])} de sus propios bultos "
                        f"brutos ({_pesos(peor['Bruto Devuelto (Nominal $)'])} devueltos "
                        f"sobre {_pesos(peor['Bruto Vendido (Nominal $)'])} vendidos, "
                        "ambos brutos nominales). Ese patron es venta en consignacion y se "
                        "corrige con pedido en firme o con tope de devolucion; no es un "
                        "defecto de entrega."
                    ),
                    amount=float(outliers["Bruto Devuelto (Nominal $)"].sum()),
                )
            )

    if not cobertura.empty:
        mercaderia = cobertura[cobertura["Es Mercaderia"]]
        rotando = mercaderia[mercaderia["Velocidad (bultos/dia)"] > 0]
        quiebre = mercaderia[mercaderia["Estado"] == "QUIEBRE"]
        sobrestock = mercaderia[mercaderia["Estado"] == "SOBRESTOCK"]
        muerto = mercaderia[mercaderia["Estado"] == "STOCK MUERTO"]
        sin_movimiento = cobertura[cobertura["Stock (bultos)"] > 0]
        sin_movimiento = sin_movimiento[
            sin_movimiento["Estado"].isin(["STOCK MUERTO", "SIN MOVIMIENTO"])
        ]

        if not quiebre.empty and not rotando.empty:
            vel_riesgo = float(quiebre["Velocidad (bultos/dia)"].sum())
            vel_total = float(rotando["Velocidad (bultos/dia)"].sum())
            en_cero = int((quiebre["Stock (bultos)"] <= 0).sum())
            alertas.append(
                Alert(
                    severity="critica",
                    title="Riesgo de quiebre sobre una porcion enorme del volumen",
                    detail=(
                        f"{len(quiebre)} pares sucursal-articulo estan por debajo de "
                        f"{k.COBERTURA_QUIEBRE_DIAS} dias de cobertura y mueven "
                        f"{_num(vel_riesgo)} bultos por dia: el "
                        f"{_pct(vel_riesgo / vel_total, 1)} de toda la velocidad vendible "
                        f"de la red. {en_cero} de esos pares ya estan en cero con demanda "
                        "viva, o sea que hoy no se pueden servir."
                    ),
                    amount=None,
                )
            )
        if not sobrestock.empty:
            capital_over = float(sobrestock["Valor Stock a Costo (Nominal $)"].sum(skipna=True))
            capital_total = float(mercaderia["Valor Stock a Costo (Nominal $)"].sum(skipna=True))
            share = capital_over / capital_total if capital_total else float("nan")
            alertas.append(
                Alert(
                    severity="alta",
                    title="Capital dormido en sobrestock, conviviendo con los quiebres",
                    detail=(
                        f"{_pesos(capital_over)} a costo nominal en {len(sobrestock)} pares "
                        f"con mas de {k.COBERTURA_SOBRESTOCK_DIAS} dias de cobertura: el "
                        f"{_pct(share, 1)} del capital en mercaderia vendible. Que "
                        "convivan quiebre y sobrestock apunta a un problema de asignacion "
                        "entre sucursales y no a un exceso de compra."
                    ),
                    amount=capital_over,
                )
            )
        naive = float(sin_movimiento["Valor Stock a Costo (Nominal $)"].sum(skipna=True))
        genuino = float(muerto["Valor Stock a Costo (Nominal $)"].sum(skipna=True))
        alertas.append(
            Alert(
                severity="media",
                title="Stock muerto: el numero ingenuo no es el numero real",
                detail=(
                    "Contando todo lo que tiene stock y no vendio en "
                    f"{DIAS_VELOCIDAD} dias salen {_pesos(naive)} a costo nominal en "
                    f"{len(sin_movimiento)} pares. La mayor parte de eso son envases "
                    "retornables y material de marketing que por definicion nunca se "
                    "venden. El stock muerto REAL -mercaderia vendible, con venta en la "
                    f"red en los ultimos 12 meses y cero movimiento en {DIAS_VELOCIDAD} "
                    f"dias- es {_pesos(genuino)} en {len(muerto)} pares."
                ),
                amount=genuino,
            )
        )

    if not tabla_rutas.empty:
        rutas_reales = tabla_rutas[tabla_rutas["Clave Ruta"] != ETIQUETA_TOTAL]
        bajas = rutas_reales[
            rutas_reales["Densidad"].astype(str).str.startswith("Baja densidad")
        ]
        visitas_totales = float(rutas_reales["Visitas Facturadas"].sum())
        bultos_totales = float(rutas_reales["Bultos"].sum())
        if not bajas.empty and visitas_totales > 0 and bultos_totales > 0:
            share_visitas = float(bajas["Visitas Facturadas"].sum()) / visitas_totales
            share_bultos = float(bajas["Bultos"].sum()) / bultos_totales
            peor = bajas.iloc[0]
            alertas.append(
                Alert(
                    severity="alta",
                    title="El cuartil de rutas de baja densidad consume mucho mas de lo que deja",
                    detail=(
                        f"{len(bajas)} rutas absorben el {_pct(share_visitas, 1)} de las "
                        f"visitas facturadas y devuelven apenas el {_pct(share_bultos, 1)} "
                        f"de los bultos. La peor es {peor['Clave Ruta']} "
                        f"({peor['Preventista']}) con {_num(peor['Drop Size (bultos/visita)'], 2)} "
                        f"bultos por visita y una mediana de "
                        f"{_num(peor['Drop Mediano (bultos/visita)'], 2)}: es un problema "
                        "de frecuencia de visita, no de demanda."
                    ),
                    amount=float(bajas["Neto (Nominal $)"].sum()),
                )
            )

    if not resultado.tables:
        resultado.failed = True
        notas.append(
            "La familia logistica no produjo ninguna tabla: revisar conectividad y "
            "disponibilidad de gold.fact_ventas_contabilidad / gold.fact_stock."
        )
    return resultado
