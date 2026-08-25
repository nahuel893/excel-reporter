"""Demanda: estacionalidad, pronostico y anomalias.

Responde tres preguntas operativas distintas sobre la misma serie de volumen:

1. QUE FORMA TIENE EL ANO. La descomposicion multiplicativa separa tendencia de
   estacionalidad y devuelve, por generico, cuanto pesa cada mes respecto de un
   mes promedio. Es la base para dimensionar cupos y stock: CERVEZAS mueve algo
   mas del doble en diciembre que en junio, asi que un cupo mensual plano
   sub-dimensiona diciembre y sobra en junio.

2. QUE VIENE. Pronostico a 6 meses. No se despacha Holt-Winters a ciegas: se
   corre CONTRA una linea base ingenua estacional (el valor de hace 12 meses) y
   se elige el ganador por serie con un backtest de origen movil a 1 paso. En la
   validacion contra la base real, Holt-Winters PIERDE en las series grandes
   (CERVEZAS, FRATELLI B, AGUAS DANONE) y solo gana donde la ingenua se derrumba
   (VINOS). Ambos MAPE viajan en la tabla para que la eleccion sea auditable.

3. QUE SE SALIO DE CAUCE. Control estadistico de proceso sobre bultos diarios
   por sucursal. La version cruda del detector es inservible: la serie diaria es
   asimetrica a derecha, el limite inferior cae por debajo de cero en las 14
   sucursales y entonces 243 de 244 alarmas son de cola alta. Se corrige con
   transformacion logaritmica (banda multiplicativa y de verdad de dos colas),
   sin domingos (no hay reparto) y sin los genericos que no son articulos de
   venta.

Todo el volumen se mide en bultos y hectolitros. En Argentina una serie en pesos
no es comparable entre periodos: +45% nominal es +10.7% real, asi que cualquier
lectura que cruce meses tiene que ir en unidades fisicas.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.services.inteligencia_comercial import constants, stats
from src.services.inteligencia_comercial.contracts import (
    Alert,
    AnalysisContext,
    AnalysisResult,
    Headline,
)

# ---------------------------------------------------------------------------
# Etiquetas y parametros del modulo
# ---------------------------------------------------------------------------
NOMBRE = "Demanda: estacionalidad, pronostico y anomalias"

TOTAL_GENERAL = "TOTAL GENERAL"
SIN_CLASIFICAR = "SIN CLASIFICAR"

MESES_ES = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")
DIAS_ES = ("Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo")
DOMINGO = 6  # pandas dayofweek: lunes=0 .. domingo=6

# Un ciclo estacional necesita como minimo dos vueltas completas al calendario
# para que el promedio por posicion no sea el dato de un solo ano.
MIN_MESES_ESTACIONALIDAD = 24
# Holt-Winters exige 2*periodo+1 puntos; el backtest de origen movil ademas
# consume meses al final de la serie.
MIN_MESES_PRONOSTICO = 2 * constants.PERIODO_ESTACIONAL + 1
MIN_ORIGENES_BACKTEST = 4
# Un volumen chico convierte cualquier variacion en ruido porcentual: SIDRAS Y
# LICORES mueve 465 bultos/mes y su amplitud estacional medida da 28x.
MIN_BULTOS_PRONOSTICO = 50_000.0
# Si ni el ganador baja de este error, la serie no es pronosticable y se informa
# como tal en vez de publicar un numero que nadie deberia usar.
MAPE_MAX_ACEPTABLE = 40.0
# Meses de historia que acompanan al pronostico para que el grafico tenga contexto.
MESES_CONTEXTO_GRAFICO = 24

# SPC: menos de 20 observaciones por (sucursal, dia de semana) no alcanzan para
# estimar una mediana y una MAD estables.
MIN_OBS_SPC = 20
# Una alarma aislada es casi siempre local (un cliente grande, una carga tardia).
# El evento de empresa aparece cuando varias sucursales rompen el mismo dia.
MIN_SUCURSALES_EVENTO = 3

# Un mes se considera cerrado cuando la fecha de corte cubre al menos este
# porcentaje de sus dias. Sin este filtro el ultimo mes entra a la baja y
# arrastra la tendencia y el indice estacional hacia abajo.
COBERTURA_MES_COMPLETO = 0.95

# Un indice estacional solo se puede leer si el ruido mensual es mas chico que
# la senal que se pretende leer. Con un desvio residual multiplicativo de 0.35
# la dispersion mes a mes es de +/-35%, mas grande que casi cualquier
# oscilacion estacional real: el "pico" que muestra el indice es la ultima
# casualidad y no un patron de calendario.
MAX_DESVIO_RESIDUAL_LEGIBLE = 0.35
# Y por debajo de este volumen mensual una variacion porcentual deja de ser una
# instruccion operativa. Medido: SIDRAS Y LICORES movio 149 bultos en el mes de
# referencia y su amplitud pico/valle da 28x; decirle al deposito que refuerce
# stock por un +472% sobre 149 bultos es ruido disfrazado de orden.
MIN_BULTOS_MES_LECTURA = 1_000.0
LECTURA_SIN_DATO = "Sin lectura"

# Serie de referencia para los titulares. Es la que manda el negocio.
SERIE_PRINCIPAL = "CERVEZAS"

MODELO_HW = "Holt-Winters"
MODELO_NAIVE = "Naive estacional"


# ---------------------------------------------------------------------------
# SQL (solo lectura)
# ---------------------------------------------------------------------------


def _lista_sql(valores) -> str:
    """Arma una lista IN de SQL a partir de constantes internas."""
    items = ", ".join("'" + str(v).replace("'", "''") + "'" for v in valores)
    return f"({items})" if items else "('')"


def sql_serie_mensual() -> str:
    """Volumen mensual por generico. Excluye los genericos que no son venta.

    Se pide desde el arranque de fact_ventas porque la estacionalidad necesita
    toda la historia disponible, no la ventana rodante del resto del informe.
    """
    return f"""
        SELECT date_trunc('month', f.fecha_comprobante)::date AS mes,
               COALESCE(da.generico, '{SIN_CLASIFICAR}')      AS generico,
               SUM(f.cantidades_total)                        AS bultos,
               SUM(f.cantidad_total_htls)                     AS hectolitros,
               COUNT(*)                                       AS lineas,
               COUNT(DISTINCT f.id_cliente)                   AS clientes
        FROM gold.fact_ventas f
        JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
        WHERE f.fecha_comprobante BETWEEN %(desde)s AND %(hasta)s
          AND f.id_documento = %(doc)s
          AND NOT f.anulado
          AND (da.generico IS NULL
               OR da.generico NOT IN {_lista_sql(constants.GENERICOS_NO_VENTA)})
        GROUP BY 1, 2
        ORDER BY 1, 2
    """


def sql_diario_sucursal() -> str:
    """Bultos diarios por sucursal para el control estadistico de proceso.

    dim_sucursal se joinea por id_sucursal, que si es clave unica en esa
    dimension (a diferencia de id_vendedor / id_ruta, que se reusan entre
    sucursales y exigen clave compuesta).
    """
    return f"""
        SELECT f.fecha_comprobante      AS fecha,
               ds.descripcion           AS sucursal,
               SUM(f.cantidades_total)  AS bultos
        FROM gold.fact_ventas f
        JOIN gold.dim_sucursal ds ON ds.id_sucursal = f.id_sucursal
        JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
        WHERE f.fecha_comprobante BETWEEN %(desde)s AND %(hasta)s
          AND f.id_documento = %(doc)s
          AND NOT f.anulado
          AND (da.generico IS NULL
               OR da.generico NOT IN {_lista_sql(constants.GENERICOS_NO_VENTA)})
        GROUP BY 1, 2
        ORDER BY 1, 2
    """


def sql_participacion_mostrador() -> str:
    """Cuanto del volumen de la ventana sale por las cuentas de mostrador.

    No se descuenta: se informa. Las cuentas de mostrador son ventas reales,
    pero no son un cliente, y quien lea la serie tiene que saber que peso tienen.
    """
    return f"""
        SELECT CASE WHEN f.id_cliente IN {_lista_numeros(constants.CLIENTES_MOSTRADOR)}
                    THEN 'Mostrador' ELSE 'Clientes' END AS tipo_cuenta,
               SUM(f.cantidades_total) AS bultos
        FROM gold.fact_ventas f
        JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
        WHERE f.fecha_comprobante BETWEEN %(desde)s AND %(hasta)s
          AND f.id_documento = %(doc)s
          AND NOT f.anulado
          AND (da.generico IS NULL
               OR da.generico NOT IN {_lista_sql(constants.GENERICOS_NO_VENTA)})
        GROUP BY 1
    """


def sql_devoluciones() -> str:
    """Bultos facturados contra bultos devueltos en la ventana.

    Toda la serie de este modulo se arma con FCVTA, es decir BRUTA de
    devoluciones. Es una eleccion defendible -- para dimensionar reparto y
    deposito interesa lo que salio -- pero deja de serlo si no se declara: las
    DVVTA no son un residuo, y quien compare este volumen contra un tablero
    neteado va a encontrar una diferencia que no sabe explicar. Se mide y se
    publica el porcentaje real en las notas.
    """
    return f"""
        SELECT SUM(f.cantidades_total) FILTER (WHERE f.id_documento = %(doc)s)  AS bultos_facturados,
               SUM(f.cantidades_total) FILTER (WHERE f.id_documento = %(dev)s)  AS bultos_devueltos
        FROM gold.fact_ventas f
        JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
        WHERE f.fecha_comprobante BETWEEN %(desde)s AND %(hasta)s
          AND NOT f.anulado
          AND (da.generico IS NULL
               OR da.generico NOT IN {_lista_sql(constants.GENERICOS_NO_VENTA)})
    """


def _lista_numeros(valores) -> str:
    items = ", ".join(str(int(v)) for v in valores)
    return f"({items})" if items else "(NULL)"


# ---------------------------------------------------------------------------
# Utilidades de calendario
# ---------------------------------------------------------------------------


def es_mes_cerrado(fecha_corte: date, cobertura_minima: float = COBERTURA_MES_COMPLETO) -> bool:
    """True si la fecha de corte cubre casi todo su propio mes.

    El ultimo mes entra parcial casi siempre. Si se lo deja adentro sin control,
    la descomposicion lee una caida que no existe y el pronostico arranca de un
    nivel deprimido.
    """
    dias_del_mes = pd.Period(pd.Timestamp(fecha_corte), freq="M").days_in_month
    return (fecha_corte.day / dias_del_mes) >= cobertura_minima


def dias_habiles_faltantes_del_mes(fecha_corte: date, feriados=None) -> int:
    """Dias de reparto que le faltan al mes de corte para estar realmente cerrado.

    `es_mes_cerrado` acepta un mes con el 95% de sus dias, asi que el ultimo mes
    de la serie puede entrar completo a la vista del lector estando corto. Con
    corte al 30 de julio falta el 31, que es un viernes de reparto: el mes
    publica 26 de 27 dias utiles y queda ~3.8% por debajo de su nivel real. Ese
    faltante se arrastra al `bultos_referencia` de la alerta estacional y a los
    bultos esperados que salen de ahi, asi que hay que decirlo.
    """
    corte = pd.Timestamp(fecha_corte)
    fin = corte.to_period("M").end_time.normalize()
    if corte >= fin:
        return 0
    fechas_feriado = set(pd.to_datetime(list(feriados))) if feriados else set()
    rango = pd.date_range(corte + pd.Timedelta(days=1), fin, freq="D")
    return sum(1 for d in rango if d.dayofweek != DOMINGO and d not in fechas_feriado)


def etiqueta_mes(ts) -> str:
    """AAAA-MM, que ordena bien como texto y no depende del locale."""
    stamp = pd.Timestamp(ts)
    return f"{stamp.year:04d}-{stamp.month:02d}"


def agregar_total_general(
    df: pd.DataFrame,
    columna_etiqueta: str,
    columnas_suma: list[str],
    etiqueta: str = TOTAL_GENERAL,
) -> pd.DataFrame:
    """Agrega la fila TOTAL GENERAL al pie, sumando solo las columnas pedidas.

    Toda tabla con medidas se entrega totalizada: el lector tiene que poder
    cuadrar la tabla contra el total sin sumar a mano.
    """
    if df.empty:
        return df
    total = {col: np.nan for col in df.columns}
    total[columna_etiqueta] = etiqueta
    for col in columnas_suma:
        if col in df.columns:
            total[col] = pd.to_numeric(df[col], errors="coerce").sum(min_count=1)
    fechas = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    salida = pd.concat([df, pd.DataFrame([total])[df.columns]], ignore_index=True)
    # El concat con un NaN degrada las columnas de fecha a texto; se restauran
    # para que Excel las escriba como fecha y no como cadena.
    for col in fechas:
        salida[col] = pd.to_datetime(salida[col], errors="coerce")
    return salida


# ---------------------------------------------------------------------------
# Serie mensual
# ---------------------------------------------------------------------------


def normalizar_serie_mensual(crudo: pd.DataFrame, fecha_corte: date | None = None) -> pd.DataFrame:
    """Deja la consulta cruda en formato largo, tipado y sin genericos de no-venta.

    El filtro de GENERICOS_NO_VENTA ya va en el SQL; se repite aca porque este
    modulo tambien se testea con DataFrames armados a mano y la regla no puede
    depender de que la consulta la haya aplicado.
    """
    columnas = ["mes", "generico", "bultos", "hectolitros", "lineas", "clientes"]
    if crudo is None or crudo.empty:
        return pd.DataFrame(columns=columnas)

    df = crudo.copy()
    df["mes"] = pd.to_datetime(df["mes"]).dt.to_period("M").dt.to_timestamp()
    df["generico"] = df["generico"].fillna(SIN_CLASIFICAR).astype(str).str.strip()
    df = df[~df["generico"].isin(constants.GENERICOS_NO_VENTA)]
    for col in ("bultos", "hectolitros", "lineas", "clientes"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if fecha_corte is not None and not es_mes_cerrado(fecha_corte):
        # Mes en curso demasiado incompleto: se descarta entero.
        inicio_mes = pd.Timestamp(fecha_corte).to_period("M").to_timestamp()
        df = df[df["mes"] < inicio_mes]

    df = df.groupby(["mes", "generico"], as_index=False)[
        ["bultos", "hectolitros", "lineas", "clientes"]
    ].sum(min_count=1)
    return df.sort_values(["mes", "generico"]).reset_index(drop=True)[columnas]


def matriz_mensual(largo: pd.DataFrame, valor: str = "bultos") -> pd.DataFrame:
    """Pivotea a una grilla mensual COMPLETA (mes x generico).

    La grilla completa importa: si un mes falta en la base, sin reindexar la
    posicion 0..11 de la descomposicion se desalinea del calendario.
    """
    if largo.empty:
        return pd.DataFrame()
    piv = largo.pivot_table(index="mes", columns="generico", values=valor, aggfunc="sum")
    grilla = pd.date_range(piv.index.min(), piv.index.max(), freq="MS")
    piv = piv.reindex(grilla)
    piv.index.name = "mes"
    piv.columns.name = None
    return piv


def tabla_serie_mensual(largo: pd.DataFrame) -> pd.DataFrame:
    """Serie mensual ancha, lista para graficar: bultos y hectolitros por generico.

    Los meses en los que un generico todavia no existia quedan vacios, no en
    cero: AGUAS DANONE arranca en 2023-06 y poner cero antes inventaria una
    caida historica que nunca ocurrio.
    """
    if largo.empty:
        return pd.DataFrame()

    bultos = matriz_mensual(largo, "bultos")
    htls = matriz_mensual(largo, "hectolitros")
    orden = bultos.sum(min_count=1).sort_values(ascending=False).index.tolist()

    salida = pd.DataFrame({"mes": [etiqueta_mes(ts) for ts in bultos.index]})
    columnas_suma: list[str] = []
    for gen in orden:
        col_b, col_h = f"{gen} - Bultos", f"{gen} - Htl"
        salida[col_b] = bultos[gen].to_numpy()
        salida[col_h] = htls[gen].to_numpy() if gen in htls.columns else np.nan
        columnas_suma += [col_b, col_h]

    salida[f"{TOTAL_GENERAL} - Bultos"] = bultos.sum(axis=1, min_count=1).to_numpy()
    salida[f"{TOTAL_GENERAL} - Htl"] = htls.sum(axis=1, min_count=1).to_numpy()
    columnas_suma += [f"{TOTAL_GENERAL} - Bultos", f"{TOTAL_GENERAL} - Htl"]

    return agregar_total_general(salida, "mes", columnas_suma)


def preparar_serie(columna: pd.Series) -> pd.Series:
    """Recorta la serie a su tramo vivo e interpola huecos internos.

    Los ceros se tratan como falta de dato, no como demanda nula: en esta base un
    mes en cero es casi siempre un generico que todavia no se vendia o que ya
    dejo de venderse, no una caida real a cero.
    """
    serie = pd.to_numeric(columna, errors="coerce").astype(float)
    validos = serie.notna() & (serie > 0)
    if not validos.any():
        return pd.Series(dtype=float)
    primero = validos.idxmax()
    ultimo = validos[::-1].idxmax()
    serie = serie.loc[primero:ultimo]
    serie = serie.mask(serie <= 0)
    return serie.interpolate(limit_direction="both")


# ---------------------------------------------------------------------------
# Estacionalidad — con la correccion de fase
# ---------------------------------------------------------------------------


def reordenar_indices_por_mes_calendario(indices, mes_inicial: int) -> np.ndarray:
    """Rota los indices estacionales de POSICION a MES CALENDARIO.

    TRAMPA QUE YA COSTO UNA RESPUESTA MAL. `stats.seasonal_decompose` promedia
    por posicion `i % periodo`, de modo que el indice 0 corresponde al mes en el
    que ARRANCA la serie, no a enero. Etiquetar la posicion 0 como enero cuando
    la serie empieza en junio corre todo seis lugares: AGUAS DANONE (que arranca
    en junio de 2023) aparecia con pico en junio cuando su pico real es febrero.

    Con la serie arrancando en el mes `mes_inicial` (1..12), la posicion `j`
    corresponde al mes calendario ((mes_inicial - 1 + j) % 12) + 1. Invirtiendo:
    el mes calendario `c` esta en la posicion (c - mes_inicial) % 12.
    """
    valores = np.asarray(indices, dtype=float)
    periodo = valores.size
    if periodo == 0:
        return valores
    desplazamiento = (int(mes_inicial) - 1) % periodo
    return np.roll(valores, desplazamiento)


def tabla_estacionalidad(
    matriz: pd.DataFrame,
    min_meses: int = MIN_MESES_ESTACIONALIDAD,
    periodo: int = constants.PERIODO_ESTACIONAL,
) -> tuple[pd.DataFrame, list[tuple[str, int]]]:
    """Indices estacionales por generico, ya alineados al calendario.

    Devuelve (tabla, excluidos). Un generico se excluye cuando no llega a
    `min_meses` de historia utilizable: con menos de dos vueltas al calendario el
    "indice" de un mes es el dato de un solo ano.
    """
    columnas = (
        ["generico", "meses"]
        + [f"indice_{m.lower()}" for m in MESES_ES]
        + [
            "fuerza_estacional",
            "mes_pico",
            "indice_pico",
            "mes_valle",
            "indice_valle",
            "amplitud_pico_valle",
            "desvio_residual",
            "indice_legible",
        ]
    )
    if matriz is None or matriz.empty:
        return pd.DataFrame(columns=columnas), []

    orden = matriz.sum(min_count=1).sort_values(ascending=False).index.tolist()
    # El TOTAL GENERAL, si viene, cierra la tabla como fila de totalizacion.
    orden = [g for g in orden if g != TOTAL_GENERAL]
    if TOTAL_GENERAL in matriz.columns:
        orden.append(TOTAL_GENERAL)

    filas: list[dict] = []
    excluidos: list[tuple[str, int]] = []
    for generico in orden:
        serie = preparar_serie(matriz[generico])
        if len(serie) < max(min_meses, 2 * periodo):
            excluidos.append((generico, int(len(serie))))
            continue

        desc = stats.seasonal_decompose(serie, period=periodo, model="multiplicative")
        posicionales = desc.seasonal_indices.to_numpy(dtype=float)
        if not np.isfinite(posicionales).any():
            excluidos.append((generico, int(len(serie))))
            continue

        mes_inicial = pd.Timestamp(serie.index[0]).month
        calendario = reordenar_indices_por_mes_calendario(posicionales, mes_inicial)

        pico = int(np.nanargmax(calendario))
        valle = int(np.nanargmin(calendario))
        residual = desc.residual.dropna()

        fila = {"generico": generico, "meses": int(len(serie))}
        for i, mes in enumerate(MESES_ES):
            fila[f"indice_{mes.lower()}"] = float(calendario[i])
        fila["fuerza_estacional"] = float(desc.seasonal_strength)
        fila["mes_pico"] = MESES_ES[pico]
        fila["indice_pico"] = float(calendario[pico])
        fila["mes_valle"] = MESES_ES[valle]
        fila["indice_valle"] = float(calendario[valle])
        fila["amplitud_pico_valle"] = (
            float(calendario[pico] / calendario[valle]) if calendario[valle] > 0 else np.nan
        )
        fila["desvio_residual"] = float(residual.std(ddof=0)) if len(residual) > 1 else np.nan
        fila["indice_legible"] = etiqueta_legibilidad(fila["desvio_residual"])
        filas.append(fila)

    if not filas:
        return pd.DataFrame(columns=columnas), excluidos
    return pd.DataFrame(filas)[columnas], excluidos


def motivo_no_legible(
    desvio_residual: float,
    bultos_referencia: float = float("nan"),
    max_residual: float = MAX_DESVIO_RESIDUAL_LEGIBLE,
    min_bultos: float = MIN_BULTOS_MES_LECTURA,
) -> str:
    """Por que un indice estacional NO se puede convertir en una instruccion.

    Devuelve "" cuando el indice es legible. Dos motivos, medidos, no opinados:

      - RUIDO. El desvio del residuo multiplicativo es la dispersion que la
        estacionalidad NO explica. Por encima de `max_residual` el mes a mes se
        mueve mas que el propio patron estacional y el "pico" del indice es la
        ultima casualidad.
      - VOLUMEN. Un porcentaje sobre un volumen chico no es una orden operativa.

    Es exactamente el mismo criterio que `tabla_pronostico` ya aplicaba con
    MIN_BULTOS_PRONOSTICO. Sin este freno la hoja accionable le pedia al
    deposito "reforzar stock y cobranza" de SIDRAS Y LICORES sobre 149 bultos y
    un indice de amplitud 28x, y de SIN CLASIFICAR con amplitud 74x.
    """
    residual = float(desvio_residual) if desvio_residual is not None else float("nan")
    if np.isfinite(residual) and residual > max_residual:
        return f"ruido residual {residual:.2f} (>{max_residual:.2f})"
    base = float(bultos_referencia) if bultos_referencia is not None else float("nan")
    if np.isfinite(base) and base < min_bultos:
        return f"volumen de referencia {base:,.0f} bultos (<{min_bultos:,.0f})"
    return ""


def etiqueta_legibilidad(desvio_residual: float) -> str:
    """Columna de auditoria: si el indice de esa fila se puede leer o no."""
    motivo = motivo_no_legible(desvio_residual)
    return "Si" if not motivo else f"No: {motivo}"


def tabla_estacionalidad_alerta(
    estacionalidad: pd.DataFrame,
    mes_referencia: int,
    bultos_referencia: dict[str, float] | None = None,
    horizonte: int = 3,
) -> pd.DataFrame:
    """Lectura accionable de la estacionalidad: que se mueve en los proximos meses.

    Compara el indice de cada uno de los proximos `horizonte` meses contra el mes
    de referencia (el ultimo cerrado). Es la traduccion del indice a una decision:
    si el indice sube 30%, el deposito y la cobranza tienen que anticiparlo.
    """
    columnas = [
        "generico",
        "mes_referencia",
        "indice_referencia",
        "bultos_referencia",
        "orden",
        "mes",
        "indice",
        "variacion_vs_referencia",
        "bultos_esperados_estacional",
        "confiabilidad",
        "lectura",
    ]
    if estacionalidad is None or estacionalidad.empty:
        return pd.DataFrame(columns=columnas)

    bultos_referencia = bultos_referencia or {}
    pos_ref = (int(mes_referencia) - 1) % 12
    etiqueta_ref = MESES_ES[pos_ref]

    filas: list[dict] = []
    for _, fila in estacionalidad.iterrows():
        generico = fila["generico"]
        indice_ref = float(fila[f"indice_{etiqueta_ref.lower()}"])
        base = float(bultos_referencia.get(generico, np.nan))
        # El freno de ruido: una serie chica o dispersa entrega indices, no
        # instrucciones. Se muestran igual (la fila no se borra) pero con la
        # lectura anulada y el motivo a la vista.
        motivo = motivo_no_legible(fila.get("desvio_residual", np.nan), base)
        for paso in range(1, horizonte + 1):
            pos = (pos_ref + paso) % 12
            etiqueta = MESES_ES[pos]
            indice = float(fila[f"indice_{etiqueta.lower()}"])
            variacion = (indice / indice_ref - 1.0) if indice_ref > 0 else np.nan
            esperado = base * indice / indice_ref if (indice_ref > 0 and np.isfinite(base)) else np.nan
            filas.append(
                {
                    "generico": generico,
                    "mes_referencia": etiqueta_ref,
                    "indice_referencia": indice_ref,
                    "bultos_referencia": base,
                    "orden": paso,
                    "mes": etiqueta,
                    "indice": indice,
                    "variacion_vs_referencia": variacion,
                    "bultos_esperados_estacional": esperado,
                    "confiabilidad": "Legible" if not motivo else f"No legible: {motivo}",
                    "lectura": (
                        _lectura_estacional(variacion)
                        if not motivo
                        else f"{LECTURA_SIN_DATO}: {motivo}"
                    ),
                }
            )
    return pd.DataFrame(filas)[columnas]


def _lectura_estacional(variacion: float) -> str:
    """Traduce la variacion del indice a una instruccion corta."""
    if not np.isfinite(variacion):
        return "Sin lectura"
    if variacion >= 0.20:
        return "Pico: reforzar stock y cobranza"
    if variacion >= 0.05:
        return "Sube"
    if variacion <= -0.20:
        return "Valle: bajar compra"
    if variacion <= -0.05:
        return "Baja"
    return "Estable"


# ---------------------------------------------------------------------------
# Pronostico — Holt-Winters contra la linea base ingenua
# ---------------------------------------------------------------------------


def mape(reales, pronosticados) -> float:
    """Error porcentual absoluto medio, en puntos porcentuales.

    Los meses con valor real cero se descartan del promedio: dividir por cero
    convierte el MAPE en infinito y esconde el resto de la serie.
    """
    y = np.asarray(reales, dtype=float)
    p = np.asarray(pronosticados, dtype=float)
    if y.size == 0 or y.size != p.size:
        return float("nan")
    mascara = np.isfinite(y) & np.isfinite(p) & (y != 0)
    if not mascara.any():
        return float("nan")
    return float(np.mean(np.abs((y[mascara] - p[mascara]) / y[mascara])) * 100.0)


def pronostico_naive_estacional(valores, periodo: int, horizonte: int) -> np.ndarray:
    """Linea base: el proximo mes vale lo que valio el mismo mes del ano pasado.

    Es una linea de una sola instruccion y en las tres series mas grandes de la
    empresa le gana a un Holt-Winters optimizado. Sin ella, cualquier MAPE de un
    modelo sofisticado es infalsificable.
    """
    y = np.asarray(valores, dtype=float)
    n = y.size
    if n < periodo or horizonte <= 0:
        return np.full(max(horizonte, 0), np.nan)
    return np.array([y[n - periodo + ((h - 1) % periodo)] for h in range(1, horizonte + 1)])


def backtest_origen_movil(
    serie: pd.Series,
    periodo: int = constants.PERIODO_ESTACIONAL,
    meses: int = constants.BACKTEST_MESES,
    grid: int = 3,
) -> dict:
    """Backtest de origen movil a 1 paso: reajusta el modelo en cada mes.

    Es la unica comparacion honesta entre modelos. Un MAPE dentro de muestra
    premia al modelo con mas parametros; aca cada pronostico se emite viendo solo
    lo anterior, igual que en produccion.
    """
    y = pd.to_numeric(serie, errors="coerce").astype(float).to_numpy()
    n = y.size
    vacio = np.array([], dtype=float)
    salida = {
        "mape_hw": float("nan"),
        "mape_naive": float("nan"),
        "origenes": 0,
        "residuos_hw": vacio,
        "residuos_naive": vacio,
    }
    primer_origen = max(MIN_MESES_PRONOSTICO, n - meses)
    origenes = list(range(primer_origen, n))
    if len(origenes) < MIN_ORIGENES_BACKTEST:
        return salida

    reales, pred_hw, pred_naive = [], [], []
    for t in origenes:
        entrenamiento = y[:t]
        ajuste = stats.holt_winters_additive(
            pd.Series(entrenamiento), period=periodo, horizon=1, grid=grid
        )
        reales.append(y[t])
        pred_hw.append(float(ajuste.forecast[0]))
        pred_naive.append(float(entrenamiento[-periodo]))

    reales = np.asarray(reales, dtype=float)
    salida["mape_hw"] = mape(reales, pred_hw)
    salida["mape_naive"] = mape(reales, pred_naive)
    salida["origenes"] = len(origenes)
    salida["residuos_hw"] = reales - np.asarray(pred_hw, dtype=float)
    salida["residuos_naive"] = reales - np.asarray(pred_naive, dtype=float)
    return salida


def bandas_desde_residuos(punto: np.ndarray, residuos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Banda de prediccion calibrada con los errores REALES del backtest.

    Se usa el mismo criterio para los dos modelos, y son los errores fuera de
    muestra los que la definen: una banda armada con residuos dentro de muestra
    miente a favor del modelo con mas parametros, justo el que el backtest suele
    descartar. Se ensancha con raiz de h porque el error se acumula con el
    horizonte, y el limite inferior se acota en cero: un pronostico de volumen
    negativo no es informacion, es un artefacto del metodo.
    """
    punto = np.asarray(punto, dtype=float)
    residuos = np.asarray(residuos, dtype=float)
    residuos = residuos[np.isfinite(residuos)]
    if residuos.size < 2:
        return np.full(punto.size, np.nan), np.full(punto.size, np.nan)
    desvio = float(np.std(residuos, ddof=1))
    if not np.isfinite(desvio) or desvio == 0:
        return np.full(punto.size, np.nan), np.full(punto.size, np.nan)
    pasos = np.sqrt(np.arange(1, punto.size + 1, dtype=float))
    inferior = np.clip(punto - 1.96 * desvio * pasos, 0.0, None)
    return inferior, punto + 1.96 * desvio * pasos


def tabla_pronostico(
    matriz: pd.DataFrame,
    periodo: int = constants.PERIODO_ESTACIONAL,
    horizonte: int = constants.HORIZONTE_PRONOSTICO,
    meses_backtest: int = constants.BACKTEST_MESES,
    min_bultos: float = MIN_BULTOS_PRONOSTICO,
    meses_contexto: int = MESES_CONTEXTO_GRAFICO,
    grid: int = 3,
) -> tuple[pd.DataFrame, list[str]]:
    """Pronostico a `horizonte` meses del ganador del backtest, por serie.

    Devuelve (tabla, descartes). Se publica el modelo que gano el backtest y se
    deja el MAPE del perdedor en la misma fila: la eleccion tiene que poder
    discutirse con el numero a la vista, no por autoridad del metodo.
    """
    columnas = [
        "generico",
        "mes",
        "tipo",
        "bultos",
        "limite_inferior",
        "limite_superior",
        "modelo_elegido",
        "mape_hw",
        "mape_naive",
    ]
    if matriz is None or matriz.empty:
        return pd.DataFrame(columns=columnas), []

    orden = matriz.sum(min_count=1).sort_values(ascending=False).index.tolist()
    orden = [g for g in orden if g != TOTAL_GENERAL]
    if TOTAL_GENERAL in matriz.columns:
        orden.insert(0, TOTAL_GENERAL)

    filas: list[dict] = []
    descartes: list[str] = []
    for generico in orden:
        serie = preparar_serie(matriz[generico])
        volumen = float(serie.sum()) if len(serie) else 0.0
        if len(serie) < MIN_MESES_PRONOSTICO + MIN_ORIGENES_BACKTEST:
            descartes.append(f"{generico}: {len(serie)} meses utiles, se necesitan "
                             f"{MIN_MESES_PRONOSTICO + MIN_ORIGENES_BACKTEST}")
            continue
        if volumen < min_bultos:
            descartes.append(f"{generico}: {volumen:,.0f} bultos historicos, por debajo del piso")
            continue

        prueba = backtest_origen_movil(serie, periodo=periodo, meses=meses_backtest, grid=grid)
        mape_hw, mape_naive = prueba["mape_hw"], prueba["mape_naive"]
        if not (np.isfinite(mape_hw) or np.isfinite(mape_naive)):
            descartes.append(f"{generico}: el backtest no produjo un error medible")
            continue

        gana_hw = np.isfinite(mape_hw) and (not np.isfinite(mape_naive) or mape_hw < mape_naive)
        mejor = mape_hw if gana_hw else mape_naive
        if not np.isfinite(mejor) or mejor > MAPE_MAX_ACEPTABLE:
            descartes.append(
                f"{generico}: mejor MAPE {mejor:.1f}% supera el maximo aceptable "
                f"{MAPE_MAX_ACEPTABLE:.0f}%, serie no pronosticable"
            )
            continue

        y = serie.to_numpy(dtype=float)
        if gana_hw:
            ajuste = stats.holt_winters_additive(serie, period=periodo, horizon=horizonte, grid=grid)
            punto = np.clip(np.asarray(ajuste.forecast, dtype=float), 0.0, None)
            residuos = prueba["residuos_hw"]
            modelo = MODELO_HW
        else:
            punto = np.clip(pronostico_naive_estacional(y, periodo, horizonte), 0.0, None)
            residuos = prueba["residuos_naive"]
            modelo = MODELO_NAIVE
        inferior, superior = bandas_desde_residuos(punto, residuos)

        contexto = serie.iloc[-meses_contexto:]
        for fecha, valor in contexto.items():
            filas.append(
                {
                    "generico": generico,
                    "mes": etiqueta_mes(fecha),
                    "tipo": "Historico",
                    "bultos": float(valor),
                    "limite_inferior": np.nan,
                    "limite_superior": np.nan,
                    "modelo_elegido": modelo,
                    "mape_hw": mape_hw,
                    "mape_naive": mape_naive,
                }
            )

        futuros = pd.date_range(
            pd.Timestamp(serie.index[-1]) + pd.offsets.MonthBegin(1), periods=horizonte, freq="MS"
        )
        for i, fecha in enumerate(futuros):
            filas.append(
                {
                    "generico": generico,
                    "mes": etiqueta_mes(fecha),
                    "tipo": "Pronostico",
                    "bultos": float(punto[i]),
                    "limite_inferior": float(inferior[i]),
                    "limite_superior": float(superior[i]),
                    "modelo_elegido": modelo,
                    "mape_hw": mape_hw,
                    "mape_naive": mape_naive,
                }
            )

    if not filas:
        return pd.DataFrame(columns=columnas), descartes
    return pd.DataFrame(filas)[columnas], descartes


# ---------------------------------------------------------------------------
# Anomalias — control estadistico de proceso sobre bultos diarios
# ---------------------------------------------------------------------------


def preparar_diario(crudo: pd.DataFrame, feriados=None) -> pd.DataFrame:
    """Deja los dias que representan una jornada de reparto normal.

    Se van los domingos (no hay reparto: un domingo en cero no es una anomalia,
    es el calendario) y los feriados conocidos. Los dias sin bultos positivos
    tampoco entran porque el logaritmo no esta definido en cero.
    """
    columnas = ["fecha", "sucursal", "bultos", "dia_semana", "dia"]
    if crudo is None or crudo.empty:
        return pd.DataFrame(columns=columnas)

    df = crudo.copy()
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["sucursal"] = df["sucursal"].fillna("SIN SUCURSAL").astype(str).str.strip()
    df["bultos"] = pd.to_numeric(df["bultos"], errors="coerce")
    df["dia_semana"] = df["fecha"].dt.dayofweek
    df["dia"] = df["dia_semana"].map(lambda d: DIAS_ES[int(d)])

    df = df[df["dia_semana"] != DOMINGO]
    df = df[df["bultos"].notna() & (df["bultos"] > 0)]
    if feriados:
        fechas_feriado = set(pd.to_datetime(list(feriados)))
        df = df[~df["fecha"].isin(fechas_feriado)]
    return df.sort_values(["fecha", "sucursal"]).reset_index(drop=True)[columnas]


def dias_sin_factura(diario: pd.DataFrame, feriados=None) -> tuple[int, int]:
    """Dias habiles en los que una sucursal no facturo NADA. Punto ciego del detector.

    Devuelve (dias_sin_factura, panel_completo).

    La consulta devuelve una fila por (fecha, sucursal) SOLO si hubo
    facturacion, y el logaritmo ademas exige un valor positivo. Es decir que la
    caida mas extrema posible -- una sucursal que no despacho un solo bulto --
    no existe como fila y por lo tanto NO puede marcarse como quiebre bajo. En
    la ventana de validacion son 106 dias-sucursal sobre un panel de 4.195
    (2,5%), concentrados en las sucursales chicas del norte. Se cuentan y se
    informan para que nadie lea "sin alarmas" como "no paro ninguna sucursal".

    El rango se toma por sucursal (primera a ultima factura observada) para no
    contar como parada los meses en que una sucursal todavia no operaba o ya
    habia cerrado: ABRA PAMPA dejo de facturar el 2026-05-04.
    """
    if diario is None or diario.empty:
        return 0, 0
    fechas_feriado = set(pd.to_datetime(list(feriados))) if feriados else set()
    faltantes = 0
    for _, grupo in diario.groupby("sucursal"):
        rango = pd.date_range(grupo["fecha"].min(), grupo["fecha"].max(), freq="D")
        habiles = sum(1 for d in rango if d.dayofweek != DOMINGO and d not in fechas_feriado)
        faltantes += max(habiles - len(grupo), 0)
    return faltantes, len(diario) + faltantes


def detectar_anomalias(
    diario: pd.DataFrame,
    sigmas: float = constants.SPC_SIGMAS,
    usar_log: bool = constants.SPC_USAR_LOG,
    min_obs: int = MIN_OBS_SPC,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carta de control robusta por (sucursal, dia de semana).

    Devuelve (quiebres, limites).

    Tres decisiones que hacen la diferencia entre un detector y una alarma que
    nadie mira:
      - mediana y MAD en lugar de media y desvio: los outliers que se buscan no
        pueden ensanchar su propio limite.
      - escala logaritmica: la serie diaria es asimetrica a derecha y en escala
        cruda el limite inferior cae bajo cero en las 14 sucursales, con lo cual
        la cola baja es inalcanzable y el detector queda de una sola cola.
      - un juego de limites por dia de semana: el sabado es estructuralmente
        distinto en varias sucursales y sin estratificar todos los sabados
        parecen caidas.
    """
    cols_quiebre = ["fecha", "sucursal", "dia", "bultos", "limite_inf", "limite_sup", "z", "direccion"]
    cols_limites = ["sucursal", "dia", "observaciones", "centro", "limite_inf", "limite_sup", "quiebres"]
    if diario is None or diario.empty:
        return pd.DataFrame(columns=cols_quiebre), pd.DataFrame(columns=cols_limites)

    quiebres: list[pd.DataFrame] = []
    limites: list[dict] = []
    for (sucursal, dia_semana), grupo in diario.groupby(["sucursal", "dia_semana"], sort=True):
        if len(grupo) < min_obs:
            continue
        grupo = grupo.sort_values("fecha")
        crudos = grupo["bultos"].astype(float)
        valores = np.log(crudos) if usar_log else crudos

        banda = stats.control_limits(pd.Series(valores.to_numpy()), sigmas=sigmas)
        escala = (banda.upper - banda.center) / sigmas
        if not np.isfinite(escala) or escala == 0:
            continue

        z = (valores.to_numpy() - banda.center) / escala
        inferior = float(np.exp(banda.lower)) if usar_log else float(banda.lower)
        superior = float(np.exp(banda.upper)) if usar_log else float(banda.upper)
        centro = float(np.exp(banda.center)) if usar_log else float(banda.center)

        marca = np.abs(z) > sigmas
        limites.append(
            {
                "sucursal": sucursal,
                "dia": DIAS_ES[int(dia_semana)],
                "observaciones": int(len(grupo)),
                "centro": centro,
                "limite_inf": inferior,
                "limite_sup": superior,
                "quiebres": int(marca.sum()),
            }
        )
        if not marca.any():
            continue
        detalle = grupo.loc[marca, ["fecha", "sucursal", "dia", "bultos"]].copy()
        detalle["limite_inf"] = inferior
        detalle["limite_sup"] = superior
        detalle["z"] = z[marca]
        detalle["direccion"] = np.where(z[marca] > 0, "Alta", "Baja")
        quiebres.append(detalle)

    tabla_limites = (
        pd.DataFrame(limites)[cols_limites].sort_values(["sucursal", "dia"]).reset_index(drop=True)
        if limites
        else pd.DataFrame(columns=cols_limites)
    )
    if not quiebres:
        return pd.DataFrame(columns=cols_quiebre), tabla_limites

    tabla = pd.concat(quiebres, ignore_index=True)[cols_quiebre]
    tabla = tabla.reindex(tabla["z"].abs().sort_values(ascending=False).index).reset_index(drop=True)
    return tabla, tabla_limites


def dias_con_evento(
    quiebres: pd.DataFrame, min_sucursales: int = MIN_SUCURSALES_EVENTO
) -> pd.DataFrame:
    """Fechas en las que varias sucursales rompieron a la vez.

    Es el filtro que separa la senal del ruido. En la validacion, solo el 12.6%
    de los quiebres cae en fechas con 3 o mas sucursales simultaneas: el resto
    son eventos locales. Una alarma de empresa tiene que exigir esta condicion o
    se convierte en spam.
    """
    columnas = ["fecha", "sucursales_en_alerta", "sucursales", "bultos", "altas", "bajas", "direccion"]
    if quiebres is None or quiebres.empty:
        return pd.DataFrame(columns=columnas)

    filas: list[dict] = []
    for fecha, grupo in quiebres.groupby("fecha", sort=True):
        cantidad = int(grupo["sucursal"].nunique())
        if cantidad < min_sucursales:
            continue
        altas = int((grupo["direccion"] == "Alta").sum())
        bajas = int((grupo["direccion"] == "Baja").sum())
        filas.append(
            {
                "fecha": fecha,
                "sucursales_en_alerta": cantidad,
                "sucursales": ", ".join(sorted(grupo["sucursal"].unique())),
                "bultos": float(grupo["bultos"].sum()),
                "altas": altas,
                "bajas": bajas,
                "direccion": "Alta" if altas >= bajas else "Baja",
            }
        )
    if not filas:
        return pd.DataFrame(columns=columnas)
    return pd.DataFrame(filas)[columnas].sort_values("fecha").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Lecturas de negocio
# ---------------------------------------------------------------------------


def crecimiento_12m_htl(largo: pd.DataFrame) -> tuple[float, float, float]:
    """Hectolitros de los ultimos 12 meses contra los 12 previos.

    En hectolitros, no en pesos: con inflacion argentina una serie nominal no
    mide crecimiento, mide inflacion.
    """
    if largo.empty:
        return float("nan"), float("nan"), float("nan")
    por_mes = largo.groupby("mes")["hectolitros"].sum(min_count=1).sort_index()
    if len(por_mes) < 24:
        return float("nan"), float("nan"), float("nan")
    ultimos = float(por_mes.iloc[-12:].sum())
    previos = float(por_mes.iloc[-24:-12].sum())
    variacion = (ultimos / previos - 1.0) if previos > 0 else float("nan")
    return ultimos, previos, variacion


def _valor(tabla: pd.DataFrame, generico: str, columna: str, defecto=float("nan")):
    """Lee una celda de una tabla indexada por generico, sin romper si no esta."""
    if tabla is None or tabla.empty or "generico" not in tabla.columns:
        return defecto
    fila = tabla.loc[tabla["generico"] == generico]
    if fila.empty or columna not in fila.columns:
        return defecto
    return fila.iloc[0][columna]


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build(ctx: AnalysisContext) -> AnalysisResult:
    """Construye el analisis de demanda completo.

    Nunca levanta excepcion: si la base no devuelve serie utilizable, marca
    `failed` y explica en las notas por que. Un informe que se cae deja al equipo
    comercial sin nada; uno que dice "no hay historia suficiente" al menos dice
    la verdad.
    """
    resultado = AnalysisResult(name=NOMBRE)
    hasta = ctx.fecha_hasta

    # -- 1. Serie mensual --------------------------------------------------
    try:
        crudo_mensual = ctx.sql(
            sql_serie_mensual(),
            {"desde": "2000-01-01", "hasta": hasta, "doc": constants.DOC_FACTURA},
        )
    except Exception as exc:  # pragma: no cover - depende de la base
        resultado.failed = True
        resultado.notes.append(f"No se pudo leer la serie mensual de ventas: {exc}")
        return resultado

    largo = normalizar_serie_mensual(crudo_mensual, ctx.hasta)
    if largo.empty:
        resultado.failed = True
        resultado.notes.append(
            "La consulta de volumen mensual no devolvio filas utilizables "
            f"hasta {hasta}; sin serie no hay estacionalidad ni pronostico."
        )
        return resultado

    resultado.tables["serie_mensual"] = tabla_serie_mensual(largo)
    feriados = _feriados_configurados()
    if not es_mes_cerrado(ctx.hasta):
        resultado.notes.append(
            f"El mes de corte ({etiqueta_mes(ctx.hasta)}) quedo fuera de la serie: la fecha "
            f"de corte {hasta} cubre menos del {COBERTURA_MES_COMPLETO:.0%} de sus dias y un mes "
            "parcial se lee como una caida que no ocurrio."
        )
    else:
        # El mes de corte entro a la serie por superar el umbral de cobertura,
        # pero eso no lo vuelve completo: hay que decir cuanto le falta o el
        # lector compara un mes corto contra meses enteros sin saberlo.
        faltan = dias_habiles_faltantes_del_mes(ctx.hasta, feriados)
        if faltan:
            resultado.notes.append(
                f"ATENCION: el ultimo mes de la serie ({etiqueta_mes(ctx.hasta)}) esta INCOMPLETO. "
                f"El corte al {hasta} lo deja sin {faltan} dia(s) habil(es) de reparto, asi que su "
                "volumen es un PISO y no un cierre. Afecta al ultimo punto de la serie, al "
                "'bultos_referencia' de la alerta estacional y a los bultos esperados que se "
                "derivan de el, y hace que la ventana de 12 meses sea unos dias mas corta que la "
                "ventana previa contra la que se compara."
            )

    matriz = matriz_mensual(largo, "bultos")
    matriz[TOTAL_GENERAL] = matriz.sum(axis=1, min_count=1)

    # -- 2. Estacionalidad -------------------------------------------------
    estacionalidad, excluidos = tabla_estacionalidad(matriz)
    resultado.tables["estacionalidad"] = estacionalidad
    if excluidos:
        detalle = ", ".join(f"{g} ({m} meses)" for g, m in excluidos)
        resultado.notes.append(
            f"Genericos sin indice estacional por historia insuficiente "
            f"(<{MIN_MESES_ESTACIONALIDAD} meses utiles): {detalle}."
        )

    # -- 3. Pronostico -----------------------------------------------------
    pronostico, descartes = tabla_pronostico(matriz)
    resultado.tables["pronostico"] = pronostico
    if descartes:
        resultado.notes.append("Series descartadas del pronostico: " + "; ".join(descartes) + ".")

    # -- 4. Anomalias ------------------------------------------------------
    desde_spc = ctx.desde(ctx.meses_ventana)
    quiebres = pd.DataFrame()
    eventos = pd.DataFrame()
    try:
        crudo_diario = ctx.sql(
            sql_diario_sucursal(),
            {"desde": desde_spc, "hasta": hasta, "doc": constants.DOC_FACTURA},
        )
        diario = preparar_diario(crudo_diario, feriados)
        quiebres, limites = detectar_anomalias(diario)
        eventos = dias_con_evento(quiebres)

        resultado.tables["anomalias"] = agregar_total_general(
            quiebres, "sucursal", ["bultos"]
        )
        resultado.tables["anomalias_limites"] = agregar_total_general(
            limites, "sucursal", ["observaciones", "quiebres"]
        )
        resultado.tables["anomalias_dias"] = agregar_total_general(
            eventos, "sucursales", ["sucursales_en_alerta", "bultos", "altas", "bajas"]
        )
        evaluados = int(len(diario))
        if evaluados:
            resultado.notes.append(
                f"SPC sobre {evaluados:,} dias-sucursal entre {desde_spc} y {hasta}: "
                f"{len(quiebres):,} quiebres ({len(quiebres) / evaluados:.2%} de los dias "
                f"evaluados), {int((quiebres['direccion'] == 'Alta').sum())} altos y "
                f"{int((quiebres['direccion'] == 'Baja').sum())} bajos. La banda es de dos colas "
                "de verdad gracias a la escala logaritmica."
            )
        else:
            resultado.notes.append("SPC sin dias evaluables en la ventana.")
        ceros, panel = dias_sin_factura(diario, feriados)
        if ceros:
            resultado.notes.append(
                f"PUNTO CIEGO del detector: {ceros:,} dias-sucursal habiles del panel "
                f"({ceros / panel:.1%} de {panel:,}) no tienen ninguna factura. Un dia en cero no "
                "genera fila en la consulta y el logaritmo tampoco admite el cero, asi que la "
                "caida mas extrema posible -- una sucursal que no despacho nada -- NO puede "
                "aparecer como quiebre bajo. 'Sin alarmas' no equivale a 'no paro ninguna "
                "sucursal': esos dias hay que mirarlos aparte."
            )
        resultado.notes.append(
            "Limites de control: mediana +/- "
            f"{constants.SPC_SIGMAS:g} * 1.4826 * MAD sobre el LOGARITMO de los bultos, "
            "estratificados por (sucursal, dia de semana), sin domingos ni feriados y sin "
            "genericos que no son articulos de venta. En escala cruda el limite inferior cae "
            "por debajo de cero y el detector queda de una sola cola."
        )
        if feriados:
            resultado.notes.append(
                f"La lista de feriados de config/settings.py cubre {len(feriados)} fechas y no "
                "abarca todos los anos de la ventana: algun feriado viejo puede aparecer como "
                "quiebre bajo."
            )
    except Exception as exc:  # pragma: no cover - depende de la base
        resultado.notes.append(f"No se pudo correr el control de anomalias: {exc}")

    # -- 5. Alerta estacional accionable -----------------------------------
    ultimo_mes = pd.Timestamp(matriz.index[-1])
    base_bultos = {
        gen: float(matriz[gen].iloc[-1])
        for gen in matriz.columns
        if pd.notna(matriz[gen].iloc[-1])
    }
    resultado.tables["estacionalidad_alerta"] = tabla_estacionalidad_alerta(
        estacionalidad, ultimo_mes.month, base_bultos
    )

    # -- 6. Participacion de las cuentas de mostrador ----------------------
    try:
        mostrador = ctx.sql(
            sql_participacion_mostrador(),
            {"desde": desde_spc, "hasta": hasta, "doc": constants.DOC_FACTURA},
        )
        total_bultos = float(pd.to_numeric(mostrador["bultos"], errors="coerce").sum())
        fila = mostrador.loc[mostrador["tipo_cuenta"] == "Mostrador", "bultos"]
        bultos_mostrador = float(fila.iloc[0]) if len(fila) else 0.0
        if total_bultos > 0:
            resultado.notes.append(
                f"Las {len(constants.CLIENTES_MOSTRADOR)} cuentas de mostrador explican "
                f"{bultos_mostrador:,.0f} de {total_bultos:,.0f} bultos "
                f"({bultos_mostrador / total_bultos:.2%}) en la ventana de anomalias. No se "
                "descuentan: son venta real, pero no son un cliente."
            )
    except Exception as exc:  # pragma: no cover - depende de la base
        resultado.notes.append(f"No se pudo medir la participacion de mostrador: {exc}")

    # -- 6 bis. Peso de las devoluciones (la serie es BRUTA) ---------------
    try:
        devol = ctx.sql(
            sql_devoluciones(),
            {
                "desde": desde_spc,
                "hasta": hasta,
                "doc": constants.DOC_FACTURA,
                "dev": constants.DOC_DEVOLUCION,
            },
        )
        facturado = float(pd.to_numeric(devol["bultos_facturados"], errors="coerce").iloc[0])
        devuelto = abs(float(pd.to_numeric(devol["bultos_devueltos"], errors="coerce").iloc[0]))
        if np.isfinite(facturado) and facturado > 0 and np.isfinite(devuelto):
            resultado.notes.append(
                f"La serie es BRUTA de devoluciones: se arma solo con {constants.DOC_FACTURA} y no "
                f"descuenta {constants.DOC_DEVOLUCION}. En la ventana de anomalias se devolvieron "
                f"{devuelto:,.0f} bultos contra {facturado:,.0f} facturados "
                f"({devuelto / facturado:.2%}). Es lo correcto para dimensionar reparto y deposito "
                "-- interesa lo que salio del deposito -- pero un tablero neteado va a mostrar "
                "menos volumen que este por ese mismo porcentaje."
            )
    except Exception as exc:  # pragma: no cover - depende de la base
        resultado.notes.append(f"No se pudo medir el peso de las devoluciones: {exc}")

    # -- 7. Titulares ------------------------------------------------------
    htl_ultimos, htl_previos, variacion = crecimiento_12m_htl(largo)
    if np.isfinite(htl_ultimos):
        resultado.headlines.append(
            Headline(
                label="Volumen 12m calendario (htl)",
                value=htl_ultimos,
                number_format="#,##0",
                delta=variacion if np.isfinite(variacion) else None,
                note=(
                    f"Contra {htl_previos:,.0f} htl de los 12 meses previos, por meses "
                    "calendario completos. En hectolitros porque una serie en pesos con "
                    "inflacion no mide crecimiento. Ver conciliacion en Metodologia."
                ),
            )
        )

    amplitud = _valor(estacionalidad, SERIE_PRINCIPAL, "amplitud_pico_valle")
    if np.isfinite(amplitud):
        pico = _valor(estacionalidad, SERIE_PRINCIPAL, "mes_pico", "")
        valle = _valor(estacionalidad, SERIE_PRINCIPAL, "mes_valle", "")
        resultado.headlines.append(
            Headline(
                label=f"Amplitud estacional {SERIE_PRINCIPAL}",
                value=float(amplitud),
                number_format='#,##0.00"x"',
                note=f"Pico {pico} vs valle {valle}. Un cupo mensual plano no sirve para esta serie.",
                higher_is_better=False,
            )
        )

    if not pronostico.empty:
        principal = pronostico.loc[pronostico["generico"] == SERIE_PRINCIPAL]
        if principal.empty:
            principal = pronostico
        fila = principal.iloc[0]
        modelo = str(fila["modelo_elegido"])
        error = float(fila["mape_hw"] if modelo == MODELO_HW else fila["mape_naive"])
        perdedor = float(fila["mape_naive"] if modelo == MODELO_HW else fila["mape_hw"])
        resultado.headlines.append(
            Headline(
                label=f"Error del pronostico {fila['generico']}",
                value=error / 100.0,
                number_format="0.0%",
                note=(
                    f"MAPE a 1 mes del modelo elegido ({modelo}) en backtest de origen movil "
                    f"sobre {constants.BACKTEST_MESES} meses. El competidor quedo en "
                    f"{perdedor:.1f}%."
                ),
                higher_is_better=False,
            )
        )

    resultado.headlines.append(
        Headline(
            label="Dias-sucursal fuera de control",
            value=int(len(quiebres)),
            number_format="#,##0",
            note=(
                f"{int(len(eventos))} fechas con {MIN_SUCURSALES_EVENTO} o mas sucursales "
                "rompiendo a la vez: esos son los eventos de empresa."
            ),
            higher_is_better=False,
        )
    )

    # -- 8. Alertas --------------------------------------------------------
    resultado.alerts.extend(_alerta_contraestacional(estacionalidad))
    resultado.alerts.extend(_alerta_quiebre_estructural(largo))
    resultado.alerts.extend(_alerta_eventos(eventos))

    # -- 9. Notas de metodo ------------------------------------------------
    resultado.notes.extend(_notas_metodo(largo, estacionalidad))
    return resultado


def _feriados_configurados() -> list[str]:
    """Feriados declarados en la configuracion del proyecto, si estan."""
    try:
        from config.settings import FERIADOS

        return list(FERIADOS)
    except Exception:  # pragma: no cover - configuracion opcional
        return []


def _alerta_contraestacional(estacionalidad: pd.DataFrame) -> list[Alert]:
    """FRATELLI B contra CERVEZAS: dos picos en meses opuestos.

    No es una curiosidad estadistica. El fernet pico en invierno y la cerveza en
    verano significa que el deposito puede alternar el espacio en lugar de
    pelearlo, y que la caja no tiene un unico valle profundo.
    """
    if estacionalidad is None or estacionalidad.empty:
        return []
    pico_cerveza = _valor(estacionalidad, "CERVEZAS", "mes_pico", "")
    pico_fernet = _valor(estacionalidad, "FRATELLI B", "mes_pico", "")
    if not pico_cerveza or not pico_fernet or pico_cerveza == pico_fernet:
        return []

    distancia = abs(MESES_ES.index(pico_cerveza) - MESES_ES.index(pico_fernet))
    distancia = min(distancia, 12 - distancia)
    if distancia < 4:
        return []

    amp_cerveza = _valor(estacionalidad, "CERVEZAS", "amplitud_pico_valle")
    amp_fernet = _valor(estacionalidad, "FRATELLI B", "amplitud_pico_valle")
    return [
        Alert(
            severity="alta",
            title="FRATELLI B es contra-estacional a CERVEZAS",
            detail=(
                f"CERVEZAS pico en {pico_cerveza} (amplitud {amp_cerveza:.2f}x) y FRATELLI B "
                f"pico en {pico_fernet} (amplitud {amp_fernet:.2f}x): {distancia} meses de "
                "distancia entre picos. Es un hecho de deposito y de caja, no una curiosidad: "
                "el espacio de almacenamiento y el capital de trabajo se pueden alternar entre "
                "las dos categorias en vez de competir."
            ),
        )
    ]


def _alerta_quiebre_estructural(largo: pd.DataFrame) -> list[Alert]:
    """AGUAS DANONE arranca a mitad de la historia y reemplaza a AGUAS Y SODAS.

    Su serie tiene un corte estructural: comparar contra los meses previos a su
    aparicion mide un cambio de nomenclatura, no de demanda.
    """
    if largo.empty:
        return []
    alertas: list[Alert] = []
    danone = largo.loc[largo["generico"] == "AGUAS DANONE", "mes"]
    if danone.empty:
        return []
    inicio = pd.Timestamp(danone.min())
    inicio_serie = pd.Timestamp(largo["mes"].min())
    if inicio <= inicio_serie:
        return []

    sodas = largo.loc[largo["generico"] == "AGUAS Y SODAS"]
    detalle_sodas = ""
    if not sodas.empty:
        antes = float(sodas.loc[sodas["mes"] < inicio, "bultos"].sum())
        despues = float(sodas.loc[sodas["mes"] >= inicio, "bultos"].sum())
        if antes > 0:
            detalle_sodas = (
                f" AGUAS Y SODAS movia {antes:,.0f} bultos antes de esa fecha y "
                f"{despues:,.0f} despues."
            )
    alertas.append(
        Alert(
            severity="media",
            title="AGUAS DANONE tiene un corte estructural en su serie",
            detail=(
                f"El generico AGUAS DANONE recien aparece en {etiqueta_mes(inicio)}, con la "
                f"serie de ventas arrancando en {etiqueta_mes(inicio_serie)}.{detalle_sodas} "
                "Su historia previa esta bajo otro generico, asi que toda comparacion interanual "
                "que cruce ese corte mide un cambio de nomenclatura y no de demanda. Los indices "
                "estacionales de AGUAS DANONE se calculan solo sobre el tramo posterior."
            ),
        )
    )
    return alertas


def _alerta_eventos(eventos: pd.DataFrame) -> list[Alert]:
    """Fechas en las que la empresa entera se salio de cauce."""
    if eventos is None or eventos.empty:
        return []
    partes = []
    for _, fila in eventos.iterrows():
        partes.append(
            f"{pd.Timestamp(fila['fecha']).date()} ({int(fila['sucursales_en_alerta'])} sucursales, "
            f"{fila['direccion'].lower()}, {float(fila['bultos']):,.0f} bultos)"
        )
    return [
        Alert(
            severity="alta",
            title=f"{len(eventos)} fechas con quiebre simultaneo en varias sucursales",
            detail=(
                "Dias en los que "
                f"{MIN_SUCURSALES_EVENTO} o mas sucursales salieron de sus limites de control a "
                "la vez, es decir eventos de empresa y no incidentes locales: "
                + "; ".join(partes)
                + ". Conviene revisarlos uno por uno: suelen ser cargas diferidas, promociones "
                "o liquidaciones."
            ),
            amount=float(eventos["bultos"].sum()),
        )
    ]


def _notas_metodo(largo: pd.DataFrame, estacionalidad: pd.DataFrame) -> list[str]:
    """Notas de metodologia para la hoja correspondiente."""
    notas = [
        "Todo el volumen va en bultos (cantidades_total) y hectolitros "
        "(cantidad_total_htls). Ninguna serie de este modulo va en pesos: con la "
        "inflacion argentina una serie nominal no es comparable entre periodos "
        "(+45% nominal equivale a +10.7% real).",
        f"Se excluyen de todo el volumen los genericos que no son articulos de venta "
        f"({', '.join(constants.GENERICOS_NO_VENTA)}). Dejar MARKETING adentro produjo la "
        "mayor falsa anomalia detectada en la validacion: 10.044 bultos facturados a $10,04 "
        "en total.",
        "Estacionalidad: descomposicion clasica multiplicativa con media movil centrada de "
        f"{constants.PERIODO_ESTACIONAL} meses. Los indices se rotan al mes calendario segun el "
        "mes de arranque de cada serie; sin esa rotacion la posicion 0 del algoritmo se lee "
        "como enero y toda la estacionalidad queda corrida.",
        "Los meses en cero se tratan como falta de dato y se interpolan; en esta base un cero "
        "mensual es casi siempre un generico que aun no se vendia o que dejo de venderse.",
        "Pronostico: se corren Holt-Winters aditivo y una linea base ingenua estacional (el "
        f"valor de hace {constants.PERIODO_ESTACIONAL} meses) y se eligen por backtest de origen "
        f"movil a 1 paso sobre los ultimos {constants.BACKTEST_MESES} meses. Se publica el "
        "ganador y se deja el MAPE del perdedor en la misma fila. Holt-Winters no se despacha a "
        "ciegas: en la validacion perdio en las series mas grandes.",
        f"Series con mejor MAPE por encima de {MAPE_MAX_ACEPTABLE:.0f}% se declaran no "
        "pronosticables y no se publican con un numero.",
        "Los limites del pronostico salen del desvio de los errores del backtest fuera de "
        "muestra (el mismo criterio para los dos modelos), ensanchados con raiz del horizonte, "
        "y el limite inferior se acota en cero.",
    ]
    notas.append(
        "Un indice estacional solo se convierte en instruccion cuando se puede leer: se anula la "
        f"lectura de las series con desvio residual por encima de {MAX_DESVIO_RESIDUAL_LEGIBLE:.2f} "
        f"(el ruido mensual tapa al patron) o con menos de {MIN_BULTOS_MES_LECTURA:,.0f} bultos en "
        "el mes de referencia (un porcentaje sobre un volumen chico no es una orden de compra). "
        "Los indices siguen publicandose con la columna 'confiabilidad' al lado, porque el "
        "problema no es que el numero exista sino que se lo obedezca."
    )
    if estacionalidad is not None and not estacionalidad.empty:
        notas.append(
            f"La fila {TOTAL_GENERAL} de estacionalidad es la descomposicion de la serie "
            "agregada de la empresa, no el promedio de las filas."
        )
        ilegibles = estacionalidad.loc[
            estacionalidad.get("indice_legible", pd.Series(dtype=str)).astype(str).str.startswith("No"),
            "generico",
        ].tolist()
        if ilegibles:
            notas.append(
                "Series cuyo indice estacional es ruido y NO deben usarse para decidir compra ni "
                f"stock: {', '.join(ilegibles)}."
            )
    if not largo.empty:
        notas.append(
            f"Historia utilizada: {etiqueta_mes(largo['mes'].min())} a "
            f"{etiqueta_mes(largo['mes'].max())} ({largo['mes'].nunique()} meses)."
        )
    return notas
