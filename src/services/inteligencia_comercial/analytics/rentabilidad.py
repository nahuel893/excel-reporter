"""Rentabilidad: margen bruto, ventas bajo costo, cascada de descuentos y dispersion de precios.

Este modulo responde cuatro preguntas comerciales que la empresa no puede
contestar hoy sin abrir la contabilidad linea por linea:

  1. Cuanto margen bruto deja realmente cada generico, marca, sucursal y subcanal.
  2. Cuanta plata se pierde vendiendo por debajo del costo, y quien la pierde.
  3. Como se descompone el precio de lista hasta la plata que efectivamente entra
     (la "cascada" bruto -> descuento -> neto), y cuanto pesa la mercaderia
     entregada sin cargo.
  4. Que articulos se venden a precios distintos al mismo mes segun el cliente,
     que es el sintoma medible de la falta de control de precios.

Advertencias de negocio que atraviesan todo el modulo
-----------------------------------------------------
* `facturacion_neta` es BRUTO a precio de lista pese al nombre; el neto real es
  `subtotal_neto` (= facturacion_neta - descuentos). `subtotal_final` incluye
  impuestos y no sirve como neto. `bonificacion` es un PORCENTAJE, nunca se suma.
* Todos los pesos son NOMINALES. Con la inflacion argentina un peso de 2022 no es
  un peso de 2026: las series de plata NO se comparan entre periodos. Solo los
  bultos son comparables en el tiempo.
* `gold.fact_ventas_contabilidad` (la unica tabla con costo) llega hasta
  2026-05-05, mientras el resto del informe llega al corte. La tabla de margen
  NUNCA debe leerse al lado de las cifras 2026 como si fueran del mismo periodo.
* `id_vendedor` e `id_ruta` se reusan entre sucursales: todo cruce con
  dim_vendedor va por la clave compuesta (id_vendedor, id_sucursal).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.services.inteligencia_comercial import constants, stats
from src.services.inteligencia_comercial.contracts import (
    AnalysisContext,
    AnalysisResult,
    Alert,
    Headline,
)

NOMBRE = "Rentabilidad, descuentos y precios"

# ---------------------------------------------------------------------------
# Parametros de materialidad. Se explicitan porque cualquier ranking sin piso de
# volumen se llena de casos de una sola factura que no se pueden accionar.
# ---------------------------------------------------------------------------
# Marca: solo las 25 mas grandes por bultos. Hay >150 marcas y la cola larga
# aporta ruido, no decision.
TOP_MARCAS = 25
# Ofensores de venta bajo costo que se listan por cliente y por articulo.
TOP_OFENSORES = 30
# Fuga de descuentos: un cliente entra al analisis si facturo mas de $3.000.000
# brutos en la ventana y tiene al menos 20 lineas. Un preventista, mas de
# $20.000.000. Debajo de eso la tasa de descuento es un artefacto de 2 facturas.
MIN_BRUTO_CLIENTE = 3_000_000.0
MIN_LINEAS_CLIENTE = 20
MIN_BRUTO_PREVENTISTA = 20_000_000.0
# Umbral de z robusto. 3.5 es el corte clasico de Iglewicz-Hoaglin para el
# z modificado por MAD; con 3.0 la lista de auditoria se vuelve inmanejable.
UMBRAL_Z = 3.5
# Dispersion de precios: una celda (articulo, mes) necesita al menos 30 clientes
# distintos para que un p10/p90 signifique algo, y el articulo tiene que aparecer
# en al menos 4 meses para entrar al ranking.
MIN_CLIENTES_CELDA = 30
MIN_MESES_ARTICULO = 4
MIN_BULTOS_ARTICULO = 5_000.0
# Piso de ruido inflacionario. Con inflacion mensual del orden de 2-3%, un cliente
# que compra el dia 2 y otro el dia 28 pagan legitimamente distinto. Un CV por
# debajo de este valor NO es un problema de control de precios.
PISO_CV_INFLACION = 0.03

# Los tres ids consecutivos que la validacion encontro con ~-91% de margen, todos
# de CASA CENTRAL. El patron (ids pegados + misma sucursal + toda la perdida
# concentrada) huele a error de carga o liquidacion puntual, no a politica
# comercial, y hay que confirmarlo antes de sentar a nadie a discutir precios.
CLIENTES_ID_CONSECUTIVO = (207600, 207601, 207603)

ETIQUETA_TOTAL = "TOTAL GENERAL"


# ---------------------------------------------------------------------------
# Utilidades estadisticas ponderadas
#
# stats.py trae el toolkit sancionado (gini, hhi, robust_zscore, control_limits,
# etc.) pero no percentiles ponderados, que hacen falta porque el margen por
# linea se trae de la base como un HISTOGRAMA (margen redondeado a 3 decimales +
# cantidad de lineas). Traer 7,5 millones de lineas crudas para sacar una mediana
# no es viable; el histograma da la misma mediana con 0,1 punto de resolucion.
# ---------------------------------------------------------------------------


def percentiles_ponderados(valores, pesos, cuantiles) -> np.ndarray:
    """Percentiles de una distribucion con pesos (frecuencias).

    Reproduce exactamente la convencion de PERCENTILE_CONT de Postgres sobre los
    datos crudos: con N observaciones el cuantil q cae en el rango 1-basado
    r = q*(N-1)+1, y se interpola linealmente entre la observacion floor(r) y la
    ceil(r). Con datos empatados —que es lo normal aca, miles de lineas con el
    mismo margen— ambas caen en el mismo valor y no hay interpolacion.

    Importa que sea la misma convencion porque el margen por linea se lee de la
    base como un histograma: traer 7,5 millones de lineas crudas para sacar una
    mediana no es viable, y el histograma tiene que dar el mismo numero.

    Devuelve NaN por cuantil cuando no queda ningun peso positivo.
    """
    v = np.asarray(valores, dtype=float)
    w = np.asarray(pesos, dtype=float)
    qs = np.asarray(cuantiles, dtype=float)
    mask = np.isfinite(v) & np.isfinite(w) & (w > 0)
    v, w = v[mask], w[mask]
    if v.size == 0:
        return np.full(qs.shape, np.nan)

    orden = np.argsort(v, kind="mergesort")
    v, w = v[orden], w[orden]
    acumulado = np.cumsum(w)
    total = acumulado[-1]

    def valor_en_rango(rango: np.ndarray) -> np.ndarray:
        """Valor de la observacion que ocupa la posicion 1-basada `rango`."""
        indices = np.searchsorted(acumulado, np.clip(rango, 1.0, total), side="left")
        return v[np.clip(indices, 0, v.size - 1)]

    rangos = qs * (total - 1.0) + 1.0
    piso = np.floor(rangos)
    fraccion = rangos - piso
    bajo = valor_en_rango(piso)
    alto = valor_en_rango(piso + 1.0)
    return bajo + fraccion * (alto - bajo)


def mad_ponderada(valores, pesos) -> float:
    """Desvio absoluto mediano con pesos.

    Se usa en lugar del desvio estandar porque el desvio crudo del margen por
    linea llega a 1.250 en BOUTIQUE: unas pocas lineas con precio casi cero
    hacen explotar el cuadrado y tapan justo lo que se quiere ver.
    """
    v = np.asarray(valores, dtype=float)
    w = np.asarray(pesos, dtype=float)
    mediana = percentiles_ponderados(v, w, [0.5])[0]
    if not np.isfinite(mediana):
        return float("nan")
    return float(percentiles_ponderados(np.abs(v - mediana), w, [0.5])[0])


def _division_segura(numerador, denominador):
    """Division elemento a elemento que devuelve NaN en vez de romper con 0."""
    num = np.asarray(numerador, dtype=float)
    den = np.asarray(denominador, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den != 0, num / den, np.nan)


def _fila_total(df: pd.DataFrame, etiquetas: dict, sumas: list[str]) -> pd.DataFrame:
    """Construye una fila TOTAL GENERAL sumando las columnas indicadas."""
    fila = {col: np.nan for col in df.columns}
    fila.update(etiquetas)
    for col in sumas:
        if col in df.columns:
            fila[col] = float(pd.to_numeric(df[col], errors="coerce").sum())
    return pd.DataFrame([fila], columns=df.columns)


# ---------------------------------------------------------------------------
# Tabla 1 — margen
# ---------------------------------------------------------------------------

_CUANTILES_MARGEN = (0.05, 0.25, 0.50, 0.75, 0.95)

COLUMNAS_MARGEN = [
    "Dimension",
    "Valor",
    "Lineas",
    "Bultos",
    "Sucursales",
    "Venta Neta Nominal $",
    "Costo Nominal $",
    "Margen Bruto Nominal $",
    "Margen Ponderado %",
    "Margen Panel Constante %",
    "Margen p05 Linea %",
    "Margen p25 Linea %",
    "Margen Mediano Linea %",
    "Margen p75 Linea %",
    "Margen p95 Linea %",
    "Rango Intercuartil %",
    "MAD Margen Linea %",
    "% Lineas Bajo Costo",
    "Perdida Bajo Costo $",
    "Observacion",
]


def resumir_margen(grilla: pd.DataFrame, columna: str, etiqueta: str) -> pd.DataFrame:
    """Agrega la grilla de margen por una dimension y calcula dispersion robusta.

    `grilla` es el histograma que devuelve la base: una fila por combinacion de
    dimensiones y valor de margen redondeado (`margen_linea`), con la cantidad de
    lineas, bultos, venta y costo de esa combinacion.

    El margen ponderado por volumen (SUM(q*(p-c)) / SUM(q*p)) es la unica medida
    honesta a nivel agregado: el promedio simple de los margenes por linea le da
    el mismo peso a una venta de 1 bulto que a una de 1.000.
    """
    if grilla.empty or columna not in grilla.columns:
        return pd.DataFrame(columns=COLUMNAS_MARGEN)

    filas = []
    for valor, bloque in grilla.groupby(columna, dropna=False, sort=False):
        venta = float(bloque["venta"].sum())
        costo = float(bloque["costo"].sum())
        lineas = float(bloque["lineas"].sum())
        p05, p25, p50, p75, p95 = percentiles_ponderados(
            bloque["margen_linea"].values, bloque["lineas"].values, _CUANTILES_MARGEN
        )
        filas.append(
            {
                "Dimension": etiqueta,
                "Valor": "SIN DATO" if pd.isna(valor) else str(valor),
                "Lineas": lineas,
                "Bultos": float(bloque["bultos"].sum()),
                # Cuantas sucursales hay adentro del corte. En el bloque Anio es la
                # columna que delata si la red estaba completa o no ese anio.
                "Sucursales": (
                    float(bloque["sucursal"].nunique()) if "sucursal" in bloque.columns else np.nan
                ),
                "Venta Neta Nominal $": venta,
                "Costo Nominal $": costo,
                "Margen Bruto Nominal $": venta - costo,
                "Margen Ponderado %": (venta - costo) / venta if venta else np.nan,
                # Se completa despues, y solo en el bloque Anio (ver panel_constante_por_anio).
                "Margen Panel Constante %": np.nan,
                "Margen p05 Linea %": p05,
                "Margen p25 Linea %": p25,
                "Margen Mediano Linea %": p50,
                "Margen p75 Linea %": p75,
                "Margen p95 Linea %": p95,
                "Rango Intercuartil %": p75 - p25,
                "MAD Margen Linea %": mad_ponderada(
                    bloque["margen_linea"].values, bloque["lineas"].values
                ),
                "% Lineas Bajo Costo": (
                    float(bloque["lineas_bajo_costo"].sum()) / lineas if lineas else np.nan
                ),
                "Perdida Bajo Costo $": float(bloque["perdida_bajo_costo"].sum()),
                "Observacion": "",
            }
        )
    return pd.DataFrame(filas, columns=COLUMNAS_MARGEN)


def panel_constante_por_anio(grilla: pd.DataFrame) -> pd.DataFrame:
    """Margen por anio recalculado sobre las sucursales que operaron TODOS los anios.

    Esto NO es un refinamiento estadistico, es la correccion de un error de lectura
    que ya se cometio: la red no existio siempre. En 2022 facturaba una sola
    sucursal y en 2024 facturaban catorce, asi que la caida del margen anual mezcla
    dos cosas distintas — que el margen se haya deteriorado, y que la empresa haya
    abierto sucursales que rinden menos que CASA CENTRAL. Sin separarlas, el comite
    comercial lee "perdimos X puntos de margen" cuando buena parte de esa caida es
    simplemente que la mezcla de sucursales cambio.

    El panel constante responde la pregunta comparable: en las MISMAS sucursales,
    ¿que paso con el margen? Devuelve una fila por anio con la cantidad de
    sucursales de ese anio, el tamano del panel y el margen del panel.
    """
    vacio = pd.DataFrame(columns=["anio", "sucursales_anio", "sucursales_panel", "margen_panel"])
    if grilla.empty or not {"anio", "sucursal", "venta", "costo"}.issubset(grilla.columns):
        return vacio

    anios = grilla["anio"].nunique()
    presencia = grilla.groupby("sucursal")["anio"].nunique()
    panel = set(presencia[presencia == anios].index)

    filas = []
    for anio, bloque in grilla.groupby("anio", sort=True):
        sub = bloque[bloque["sucursal"].isin(panel)]
        venta = float(sub["venta"].sum())
        costo = float(sub["costo"].sum())
        filas.append(
            {
                "anio": anio,
                "sucursales_anio": float(bloque["sucursal"].nunique()),
                "sucursales_panel": float(len(panel)),
                "margen_panel": (venta - costo) / venta if venta else np.nan,
            }
        )
    return pd.DataFrame(filas, columns=vacio.columns)


def _anotar_composicion_anual(bloque: pd.DataFrame, grilla: pd.DataFrame) -> pd.DataFrame:
    """Pega el panel constante al bloque Anio y marca los anios de red incompleta."""
    panel = panel_constante_por_anio(grilla)
    if panel.empty:
        return bloque

    panel = panel.copy()
    panel["Valor"] = panel["anio"].astype(str)
    maximo = float(panel["sucursales_anio"].max())
    bloque = bloque.merge(
        panel[["Valor", "sucursales_anio", "sucursales_panel", "margen_panel"]],
        on="Valor",
        how="left",
    )
    bloque["Margen Panel Constante %"] = bloque["margen_panel"]

    def observar(fila: pd.Series) -> str:
        propias = fila.get("sucursales_anio")
        if not pd.notna(propias) or propias >= maximo:
            return ""
        return (
            f"RED INCOMPLETA: solo {propias:.0f} de {maximo:.0f} sucursales facturaban ese anio. "
            "El margen del anio NO es comparable contra los demas: parte de la variacion es "
            f"apertura de sucursales, no gestion. Comparar por 'Margen Panel Constante' "
            f"({fila['sucursales_panel']:.0f} sucursal(es) presentes en todos los anios)."
        )

    bloque["Observacion"] = bloque.apply(observar, axis=1)
    return bloque.drop(columns=["sucursales_anio", "sucursales_panel", "margen_panel"])


def construir_tabla_margen(grilla: pd.DataFrame, top_marcas: int = TOP_MARCAS) -> pd.DataFrame:
    """Arma la tabla larga de margen por anio, generico, marca, sucursal y subcanal.

    Cada dimension se ordena por venta descendente. Marca se recorta primero a las
    `top_marcas` mas grandes por bultos (la cola larga no es accionable) y recien
    despues se ordena por venta, para que el recorte no cambie el criterio de orden.
    La fila TOTAL GENERAL se recalcula sobre TODA la grilla, no sumando bloques:
    sumar los subtotales duplicaria la facturacion cinco veces.

    El bloque Anio se anota con el panel constante de sucursales, porque la red no
    existio siempre y sin esa aclaracion la serie anual se lee como deterioro de
    margen cuando en buena parte es apertura de sucursales.
    """
    if grilla.empty:
        return pd.DataFrame(columns=COLUMNAS_MARGEN)

    partes = []
    for columna, etiqueta, recorte in (
        ("anio", "Anio", None),
        ("generico", "Generico", None),
        ("marca", "Marca", top_marcas),
        ("sucursal", "Sucursal", None),
        ("subcanal", "Subcanal", None),
    ):
        bloque = resumir_margen(grilla, columna, etiqueta)
        if bloque.empty:
            continue
        if recorte:
            bloque = bloque.nlargest(recorte, "Bultos")
        if etiqueta == "Anio":
            bloque = bloque.sort_values("Valor")
            bloque = _anotar_composicion_anual(bloque, grilla)
        else:
            bloque = bloque.sort_values("Venta Neta Nominal $", ascending=False)
        partes.append(bloque)

    if not partes:
        return pd.DataFrame(columns=COLUMNAS_MARGEN)

    grilla_total = grilla.assign(_todo=ETIQUETA_TOTAL)
    total = resumir_margen(grilla_total, "_todo", "Total")
    total["Valor"] = ETIQUETA_TOTAL
    partes.append(total)

    return pd.concat(partes, ignore_index=True)[COLUMNAS_MARGEN]


# ---------------------------------------------------------------------------
# Tabla 2 — bajo_costo
# ---------------------------------------------------------------------------

COLUMNAS_BAJO_COSTO = [
    "Dimension",
    "Valor",
    "Lineas",
    "Bultos",
    "Venta Nominal $",
    "Costo Nominal $",
    "Perdida $",
    "Margen Ponderado %",
    "Primera Fecha",
    "Ultima Fecha",
    "Observacion",
]


# Un costo cargado por encima de este multiplo del precio de venta ya no es una
# decision comercial: nadie vende a un tercio del costo de forma deliberada y
# repetida. Es la firma de un precio_compra_neto mal cargado o de una unidad de
# medida cambiada, y hay que mandarlo a sistemas, no a comercial.
UMBRAL_COSTO_IMPLAUSIBLE = 2.0


def _observacion_bajo_costo(fila: pd.Series, marcar_costo: bool = True) -> str:
    """Etiqueta las filas que NO se pueden accionar sin verificar antes.

    `marcar_costo` se apaga en las filas agregadas (anio, sucursal): que un anio
    entero muestre un costo mayor al doble de la venta bajo costo es aritmetica
    del agregado, no la firma de un registro mal cargado. El aviso solo tiene
    sentido a nivel de cliente o articulo, que es lo que alguien puede ir a mirar.
    """
    notas = []
    id_cliente = fila.get("id_cliente")
    if pd.notna(id_cliente):
        id_cliente = int(id_cliente)
        if id_cliente in CLIENTES_ID_CONSECUTIVO:
            notas.append(
                "VERIFICAR ANTES DE ACCIONAR: ids consecutivos "
                f"{'/'.join(str(i) for i in CLIENTES_ID_CONSECUTIVO)}, todos CASA CENTRAL, "
                "margen cercano a -91%. Patron de error de carga o liquidacion, no de politica comercial"
            )
        if id_cliente in constants.CLIENTES_MOSTRADOR:
            notas.append("MOSTRADOR: bolsa de venta al publico, no es un cliente real")
    venta = fila.get("Venta Nominal $")
    costo = fila.get("Costo Nominal $")
    if (
        marcar_costo
        and pd.notna(venta)
        and pd.notna(costo)
        and venta > 0
        and costo > UMBRAL_COSTO_IMPLAUSIBLE * venta
    ):
        notas.append(
            f"COSTO IMPLAUSIBLE: el costo cargado es {costo / venta:.0f}x el precio de venta. "
            "Antes de tratarlo como problema comercial hay que revisar precio_compra_neto en sistemas"
        )
    primera, ultima = fila.get("Primera Fecha"), fila.get("Ultima Fecha")
    if pd.notna(primera) and pd.notna(ultima) and primera == ultima:
        notas.append(f"Toda la perdida en un solo dia ({primera}) con {int(fila['Lineas'])} lineas")
    return " | ".join(notas)


def resumir_bajo_costo(
    detalle: pd.DataFrame, claves: list[str], etiqueta: str, top: int | None = None
) -> pd.DataFrame:
    """Agrupa las lineas vendidas bajo costo por una clave y ordena por perdida.

    `detalle` trae una fila por (anio, sucursal, cliente, articulo) con lineas,
    bultos, venta, costo y el rango de fechas. La perdida es venta - costo y es
    negativa por construccion (son lineas con precio menor al costo).
    """
    if detalle.empty:
        return pd.DataFrame(columns=COLUMNAS_BAJO_COSTO)

    agregado = detalle.groupby(claves, dropna=False, sort=False).agg(
        Lineas=("lineas", "sum"),
        Bultos=("bultos", "sum"),
        venta=("venta", "sum"),
        costo=("costo", "sum"),
        primera=("primera", "min"),
        ultima=("ultima", "max"),
    )
    agregado = agregado.reset_index()

    agregado["Venta Nominal $"] = agregado["venta"].astype(float)
    agregado["Costo Nominal $"] = agregado["costo"].astype(float)
    agregado["Perdida $"] = agregado["venta"].astype(float) - agregado["costo"].astype(float)
    agregado["Margen Ponderado %"] = _division_segura(agregado["Perdida $"], agregado["venta"])
    agregado["Primera Fecha"] = agregado["primera"].astype(str)
    agregado["Ultima Fecha"] = agregado["ultima"].astype(str)
    agregado["Dimension"] = etiqueta
    if len(claves) == 2:
        # Los nombres se repiten (hay tres "CONSUMIDOR FINAL" distintos). El id
        # va pegado a la etiqueta para que la fila sea identificable en el ERP.
        agregado["Valor"] = (
            agregado[claves[1]].astype(str) + " (" + agregado[claves[0]].astype(str) + ")"
        )
    else:
        agregado["Valor"] = agregado[claves[-1]].astype(str)
    agregado["Lineas"] = agregado["Lineas"].astype(float)
    agregado["Bultos"] = agregado["Bultos"].astype(float)
    agregado["Observacion"] = agregado.apply(
        _observacion_bajo_costo, axis=1, marcar_costo=len(claves) == 2
    )

    agregado = agregado.sort_values("Perdida $")  # mas negativo primero
    if top is not None:
        agregado = agregado.head(top)
    return agregado[COLUMNAS_BAJO_COSTO].reset_index(drop=True)


def construir_bajo_costo(detalle: pd.DataFrame, top: int = TOP_OFENSORES) -> pd.DataFrame:
    """Tabla larga de venta bajo costo por anio, sucursal, cliente y articulo."""
    if detalle.empty:
        return pd.DataFrame(columns=COLUMNAS_BAJO_COSTO)

    partes = [
        resumir_bajo_costo(detalle, ["anio"], "Anio").sort_values("Valor"),
        resumir_bajo_costo(detalle, ["sucursal"], "Sucursal"),
        resumir_bajo_costo(detalle, ["id_cliente", "cliente"], "Cliente", top=top),
        resumir_bajo_costo(detalle, ["id_articulo", "articulo"], "Articulo", top=top),
    ]
    tabla = pd.concat(partes, ignore_index=True)

    # El TOTAL GENERAL se recalcula sobre el detalle completo, no sumando los
    # bloques: sumarlos contaria cuatro veces la misma perdida.
    venta = float(detalle["venta"].sum())
    costo = float(detalle["costo"].sum())
    total = pd.DataFrame(
        [
            {
                "Dimension": "Total",
                "Valor": ETIQUETA_TOTAL,
                "Lineas": float(detalle["lineas"].sum()),
                "Bultos": float(detalle["bultos"].sum()),
                "Venta Nominal $": venta,
                "Costo Nominal $": costo,
                "Perdida $": venta - costo,
                "Margen Ponderado %": (venta - costo) / venta if venta else np.nan,
                "Primera Fecha": str(detalle["primera"].min()),
                "Ultima Fecha": str(detalle["ultima"].max()),
                "Observacion": "",
            }
        ],
        columns=COLUMNAS_BAJO_COSTO,
    )

    return pd.concat([tabla, total], ignore_index=True)[COLUMNAS_BAJO_COSTO]


# ---------------------------------------------------------------------------
# Tabla 3 — cascada de descuentos
# ---------------------------------------------------------------------------

COLUMNAS_CASCADA = [
    "ambito",
    "concepto",
    "monto",
    "base_acumulada",
    "es_resta",
    "pct_bruto",
]

CONCEPTO_BRUTO = "Bruto a precio de lista"
CONCEPTO_SIN_CARGO = "Mercaderia sin cargo (a precio de lista)"
CONCEPTO_COMERCIAL = "Descuento comercial"
CONCEPTO_RESIDUO = "Ajuste / residuo de identidad"
CONCEPTO_NETO = "Neto realizado"
CONCEPTO_MEMO = "Memo: mercaderia sin cargo valuada a precio realizado"


def _cascada_de_totales(ambito: str, totales: pd.Series) -> list[dict]:
    """Convierte los totales de un ambito en los escalones de la cascada.

    El recorrido es: bruto de lista -> se descuenta lo entregado sin cargo
    (valuado a lista) -> se descuenta el resto del descuento comercial -> queda
    el neto realizado. La mercaderia sin cargo ya viene DENTRO de `descuentos`
    (esas lineas llevan bonificacion=100), asi que restarla aparte y despues
    restar `descuentos` completo contaria dos veces la misma plata.

    El escalon "residuo" existe porque la identidad
    subtotal_neto = facturacion_neta - descuentos se cumple en el 99,9963% de las
    lineas, no en el 100%. Mostrarlo es preferible a maquillar el cierre.
    """
    bruto = float(totales.get("bruto", 0.0) or 0.0)
    descuentos = float(totales.get("descuentos", 0.0) or 0.0)
    neto = float(totales.get("neto", 0.0) or 0.0)
    sin_cargo_lista = float(totales.get("sin_cargo_lista", 0.0) or 0.0)
    q_sin_cargo = float(totales.get("q_sin_cargo", 0.0) or 0.0)
    q_con_cargo = float(totales.get("q_con_cargo", 0.0) or 0.0)

    # La parte del descuento que no es mercaderia regalada. Si diera negativo la
    # valuacion de lo sin cargo supera el descuento total del ambito: se deja en
    # cero y la diferencia cae en el residuo, que es donde se ve el problema.
    comercial = descuentos - sin_cargo_lista
    if comercial < 0:
        comercial = 0.0
    residuo = neto - (bruto - sin_cargo_lista - comercial)

    precio_realizado = neto / q_con_cargo if q_con_cargo else np.nan
    sin_cargo_realizado = q_sin_cargo * precio_realizado if np.isfinite(precio_realizado) else np.nan

    def pct(valor):
        return valor / bruto if bruto else np.nan

    return [
        {
            "ambito": ambito,
            "concepto": CONCEPTO_BRUTO,
            "monto": bruto,
            "base_acumulada": bruto,
            "es_resta": False,
            "pct_bruto": pct(bruto),
        },
        {
            "ambito": ambito,
            "concepto": CONCEPTO_SIN_CARGO,
            "monto": sin_cargo_lista,
            "base_acumulada": bruto - sin_cargo_lista,
            "es_resta": True,
            "pct_bruto": pct(sin_cargo_lista),
        },
        {
            "ambito": ambito,
            "concepto": CONCEPTO_COMERCIAL,
            "monto": comercial,
            "base_acumulada": bruto - sin_cargo_lista - comercial,
            "es_resta": True,
            "pct_bruto": pct(comercial),
        },
        {
            "ambito": ambito,
            "concepto": CONCEPTO_RESIDUO,
            "monto": abs(residuo),
            "base_acumulada": neto,
            "es_resta": residuo < 0,
            "pct_bruto": pct(abs(residuo)),
        },
        {
            "ambito": ambito,
            "concepto": CONCEPTO_NETO,
            "monto": neto,
            "base_acumulada": neto,
            "es_resta": False,
            "pct_bruto": pct(neto),
        },
        {
            # Memo: NO forma parte del recorrido, es la misma mercaderia sin cargo
            # valuada a lo que realmente se cobra por bulto en vez de a lista.
            "ambito": ambito,
            "concepto": CONCEPTO_MEMO,
            "monto": sin_cargo_realizado,
            "base_acumulada": sin_cargo_realizado,
            "es_resta": True,
            "pct_bruto": pct(sin_cargo_realizado),
        },
    ]


def construir_cascada(base: pd.DataFrame) -> pd.DataFrame:
    """Cascada de descuentos total, por sucursal y por generico.

    `base` trae una fila por (sucursal, generico) con bruto, descuentos, neto,
    valor de lo entregado sin cargo y las cantidades. Todo lo demas se agrega
    aca, en pandas.
    """
    columnas_suma = [
        "bruto",
        "descuentos",
        "neto",
        "sin_cargo_lista",
        "q_sin_cargo",
        "q_con_cargo",
    ]
    if base.empty:
        return pd.DataFrame(columns=COLUMNAS_CASCADA)

    filas = list(_cascada_de_totales(ETIQUETA_TOTAL, base[columnas_suma].sum()))

    for columna, prefijo in (("sucursal", "Sucursal"), ("generico", "Generico")):
        if columna not in base.columns:
            continue
        agrupado = base.groupby(columna, dropna=False, sort=False)[columnas_suma].sum()
        agrupado = agrupado.sort_values("bruto", ascending=False)
        for valor, totales in agrupado.iterrows():
            etiqueta = "SIN DATO" if pd.isna(valor) else str(valor)
            filas.extend(_cascada_de_totales(f"{prefijo}: {etiqueta}", totales))

    return pd.DataFrame(filas, columns=COLUMNAS_CASCADA)


# ---------------------------------------------------------------------------
# Tabla 4 — fuga de descuentos (outliers robustos)
# ---------------------------------------------------------------------------

COLUMNAS_FUGA = [
    "entidad",
    "tipo",
    "sucursal",
    "bruto",
    "descuento",
    "tasa",
    "z_robusto",
    "exceso_vs_mediana",
    "lineas",
    "observacion",
]


def detectar_fuga_outliers(entidades: pd.DataFrame, umbral_z: float = UMBRAL_Z) -> pd.DataFrame:
    """Clientes y preventistas cuya tasa de descuento es un outlier robusto.

    La tasa se compara contra la MEDIANA de su propio tipo usando el z modificado
    (mediana + MAD) de stats.robust_zscore. El z clasico no sirve aca: los mismos
    casos extremos que se quieren detectar inflan el desvio estandar y terminan
    quedando dentro de sus propios limites.

    `exceso_vs_mediana` traduce el z a plata: cuanto descuento de mas gasto la
    entidad respecto de lo que habria gastado con la tasa mediana de su tipo.
    Es la cifra con la que se negocia, no el z.

    Espera que `entidades` YA venga filtrada por materialidad.
    """
    if entidades.empty:
        return pd.DataFrame(columns=COLUMNAS_FUGA)

    trabajo = entidades.copy()
    trabajo["tasa"] = _division_segura(trabajo["descuento"], trabajo["bruto"])

    salidas = []
    for tipo, bloque in trabajo.groupby("tipo", sort=False):
        bloque = bloque.copy()
        bloque["z_robusto"] = stats.robust_zscore(bloque["tasa"].values)
        mediana = float(np.nanmedian(bloque["tasa"].values))
        bloque["exceso_vs_mediana"] = (bloque["tasa"] - mediana) * bloque["bruto"]
        salidas.append(bloque[bloque["z_robusto"] > umbral_z])

    if not salidas:
        return pd.DataFrame(columns=COLUMNAS_FUGA)

    tabla = pd.concat(salidas, ignore_index=True)
    if tabla.empty:
        return pd.DataFrame(columns=COLUMNAS_FUGA)

    for columna in COLUMNAS_FUGA:
        if columna not in tabla.columns:
            tabla[columna] = ""
    tabla["observacion"] = tabla["observacion"].fillna("")
    # Un descuento que se come casi toda la factura no es una negociacion: o es
    # entrega sin cargo mal imputada o es un ajuste. Se avisa para que la
    # conversacion empiece por administracion y no por el cliente.
    aviso = "Descuento superior al 90% del bruto: verificar si es una operacion real o un ajuste contable"
    casi_total = tabla["tasa"] > 0.9
    tabla.loc[casi_total, "observacion"] = tabla.loc[casi_total, "observacion"].map(
        lambda previo: f"{previo} | {aviso}" if previo else aviso
    )

    tabla = tabla.sort_values("exceso_vs_mediana", ascending=False)
    tabla = tabla[COLUMNAS_FUGA].reset_index(drop=True)

    # Subtotales por tipo + TOTAL GENERAL.
    #
    # NADA es sumable entre tipos, tampoco el exceso. Clientes y preventistas son
    # DOS PARTICIONES DE LA MISMA VENTA: cada linea facturada tiene exactamente un
    # cliente y exactamente un preventista, asi que el descuento de un cliente
    # desviado ya esta contenido adentro del descuento de su preventista. Sumar los
    # dos bloques (incluido el exceso, que se deriva del mismo bruto y del mismo
    # descuento) cuenta la misma plata dos veces. Medido en la ventana de 12 meses:
    # los preventistas marcados como outlier concentran $1.343.277.000 de descuento,
    # y adentro de esa cifra ya viven los clientes outlier de su propia cartera.
    #
    # Por eso el TOTAL GENERAL informa la vista CLIENTE, que es la que se acciona
    # (se negocia con el cliente, no con el vendedor), y deja la vista PREVENTISTA
    # como un subtotal aparte para leer, no para sumar.
    cierres = []
    excesos: dict[str, float] = {}
    for tipo in ("Cliente", "Preventista"):
        bloque = tabla[tabla["tipo"] == tipo]
        if bloque.empty:
            continue
        excesos[tipo] = float(bloque["exceso_vs_mediana"].sum())
        cierres.append(
            _fila_total(
                tabla,
                {
                    "entidad": f"SUBTOTAL {tipo}",
                    "tipo": tipo,
                    "sucursal": "",
                    "observacion": (
                        f"{len(bloque)} entidades con z robusto > {umbral_z} (cola alta unicamente). "
                        "NO sumar contra el otro subtotal: es la misma venta cortada de otra forma"
                    ),
                },
                [],
            ).assign(
                bruto=float(bloque["bruto"].sum()),
                descuento=float(bloque["descuento"].sum()),
                lineas=float(bloque["lineas"].sum()),
                exceso_vs_mediana=excesos[tipo],
                tasa=(
                    float(bloque["descuento"].sum()) / float(bloque["bruto"].sum())
                    if float(bloque["bruto"].sum())
                    else np.nan
                ),
            )
        )

    exceso_cliente = excesos.get("Cliente")
    exceso_preventista = excesos.get("Preventista")
    if exceso_cliente is not None:
        detalle_total = (
            f"Exceso de la vista CLIENTE, que es la accionable. La vista PREVENTISTA "
            f"(${exceso_preventista:,.0f}) es la MISMA plata cortada por vendedor y NO se suma"
            if exceso_preventista is not None
            else "Exceso de la vista CLIENTE"
        )
        exceso_total = exceso_cliente
    else:
        detalle_total = "Sin clientes outlier; se informa la vista PREVENTISTA"
        exceso_total = exceso_preventista if exceso_preventista is not None else np.nan

    total = _fila_total(
        tabla,
        {
            "entidad": ETIQUETA_TOTAL,
            "tipo": "Total",
            "sucursal": "",
            "observacion": detalle_total,
        },
        [],
    ).assign(exceso_vs_mediana=exceso_total)
    return pd.concat([tabla, *cierres, total], ignore_index=True)[COLUMNAS_FUGA]


# ---------------------------------------------------------------------------
# Tabla 5 — dispersion de precios realizados
# ---------------------------------------------------------------------------

COLUMNAS_CELDAS = [
    "id_articulo",
    "mes",
    "clientes",
    "bultos",
    "neto",
    "cv",
    "p10",
    "p50",
    "p90",
    "ratio_p90_p10",
    "brecha_vs_mediana",
]

COLUMNAS_DISPERSION = [
    "articulo",
    "generico",
    "marca",
    "cortes_mensuales",
    "mes_referencia",
    "clientes_en_el_corte",
    "bultos",
    "neto_nominal",
    "cv_ponderado_pct",
    # Los nombres llevan 'precio' y 'pesos' a proposito: son montos en pesos, no
    # ratios, y la hoja infiere el formato de Excel a partir del nombre de la
    # columna. Un p10 sin esa pista sale sin simbolo de moneda y se lee como indice.
    "precio_p10",
    "precio_p50",
    "precio_p90",
    "ratio_p90_p10",
    "brecha_vs_mediana_pesos",
    "diagnostico",
]


def resumir_celdas_precio(
    base: pd.DataFrame, min_clientes: int = MIN_CLIENTES_CELDA
) -> pd.DataFrame:
    """Dispersion del precio realizado dentro de cada (articulo, mes) entre clientes.

    Precio realizado por cliente = subtotal_neto / cantidades_con_cargo. Se usa el
    NETO, no facturacion_neta: la facturacion es lista x cantidad y por definicion
    no tiene dispersion, con lo cual el analisis daria siempre cero.

    `brecha_vs_mediana` es la plata que faltaria para que todos los clientes que
    pagaron menos que la mediana del mes hubieran pagado la mediana. Es una COTA
    SUPERIOR: parte de ella es inflacion intramensual legitima.
    """
    if base.empty:
        return pd.DataFrame(columns=COLUMNAS_CELDAS)

    trabajo = base.copy()
    trabajo["precio"] = _division_segura(trabajo["neto"], trabajo["q"])
    trabajo = trabajo[np.isfinite(trabajo["precio"]) & (trabajo["precio"] > 0)]
    if trabajo.empty:
        return pd.DataFrame(columns=COLUMNAS_CELDAS)

    filas = []
    for (id_articulo, mes), bloque in trabajo.groupby(["id_articulo", "mes"], sort=False):
        if len(bloque) < min_clientes:
            continue
        precios = bloque["precio"].values
        p10, p50, p90 = np.percentile(precios, [10, 50, 90])
        debajo = bloque[bloque["precio"] < p50]
        filas.append(
            {
                "id_articulo": id_articulo,
                "mes": mes,
                "clientes": float(len(bloque)),
                "bultos": float(bloque["q"].sum()),
                "neto": float(bloque["neto"].sum()),
                "cv": stats.coefficient_of_variation(precios),
                "p10": float(p10),
                "p50": float(p50),
                "p90": float(p90),
                "ratio_p90_p10": float(p90 / p10) if p10 > 0 else np.nan,
                "brecha_vs_mediana": float(((p50 - debajo["precio"]) * debajo["q"]).sum()),
            }
        )
    return pd.DataFrame(filas, columns=COLUMNAS_CELDAS)


def _diagnostico_dispersion(cv: float) -> str:
    """Traduce el CV a una lectura de negocio, con el piso inflacionario adentro."""
    if not np.isfinite(cv):
        return "Sin dato"
    if cv < PISO_CV_INFLACION:
        return "Controlado (dentro del ruido inflacionario intramensual)"
    if cv < 2 * PISO_CV_INFLACION:
        return "Atencion: dispersion apenas por encima del ruido"
    return "Revisar politica de precios"


def rankear_dispersion(
    celdas: pd.DataFrame,
    articulos: pd.DataFrame,
    min_meses: int = MIN_MESES_ARTICULO,
    min_bultos: float = MIN_BULTOS_ARTICULO,
) -> pd.DataFrame:
    """Ranking de articulos por dispersion de precio, ponderada por volumen.

    El CV de cada mes se pondera por los bultos de ese mes: un mes flojo no puede
    definir el diagnostico de un SKU que mueve el grueso en otro mes.

    La banda de precios (p10/p50/p90 y su ratio) se informa SIEMPRE del ultimo mes
    disponible, no promediada entre meses. Con inflacion mensual del 2-3% un
    promedio de precios de meses distintos no es un precio de nada, y mezclar un
    p10 de enero con un p90 de julio inventaria una dispersion que no existe.
    """
    if celdas.empty:
        return pd.DataFrame(columns=COLUMNAS_DISPERSION)

    filas = []
    for id_articulo, bloque in celdas.groupby("id_articulo", sort=False):
        bultos = float(bloque["bultos"].sum())
        if len(bloque) < min_meses or bultos < min_bultos:
            continue
        pesos = bloque["bultos"].values.astype(float)
        cv = bloque["cv"].values.astype(float)
        validos = np.isfinite(cv) & (pesos > 0)
        cv_ponderado = float(np.average(cv[validos], weights=pesos[validos])) if validos.any() else np.nan
        ultimo = bloque.loc[bloque["mes"].idxmax()]
        filas.append(
            {
                "id_articulo": id_articulo,
                "cortes_mensuales": float(len(bloque)),
                "mes_referencia": str(ultimo["mes"]),
                "clientes_en_el_corte": float(ultimo["clientes"]),
                "bultos": bultos,
                "neto_nominal": float(bloque["neto"].sum()),
                "cv_ponderado_pct": cv_ponderado,
                "precio_p10": float(ultimo["p10"]),
                "precio_p50": float(ultimo["p50"]),
                "precio_p90": float(ultimo["p90"]),
                "ratio_p90_p10": float(ultimo["ratio_p90_p10"]),
                "brecha_vs_mediana_pesos": float(bloque["brecha_vs_mediana"].sum()),
            }
        )
    if not filas:
        return pd.DataFrame(columns=COLUMNAS_DISPERSION)

    tabla = pd.DataFrame(filas)
    if not articulos.empty:
        tabla = tabla.merge(articulos, on="id_articulo", how="left")
    for columna in ("articulo", "generico", "marca"):
        if columna not in tabla.columns:
            tabla[columna] = "SIN DATO"
        tabla[columna] = tabla[columna].fillna("SIN DATO")

    tabla["diagnostico"] = tabla["cv_ponderado_pct"].map(_diagnostico_dispersion)
    tabla = tabla.sort_values("cv_ponderado_pct", ascending=False)
    tabla = tabla[COLUMNAS_DISPERSION].reset_index(drop=True)

    total = _fila_total(
        tabla,
        {
            "articulo": ETIQUETA_TOTAL,
            "generico": "",
            "marca": "",
            "mes_referencia": "",
            "diagnostico": f"{len(tabla)} articulos analizados",
        },
        ["bultos", "neto_nominal", "brecha_vs_mediana_pesos"],
    )
    return pd.concat([tabla, total], ignore_index=True)[COLUMNAS_DISPERSION]


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

# Filtro comun: factura de venta, no anulada. Las devoluciones (DVVTA) y los
# presupuestos (PRVTA) no son ventas realizadas y ensucian cualquier tasa.
_FILTRO_DOC = "f.id_documento = 'FCVTA' AND NOT f.anulado"

# Margen por linea llevado a un histograma: se redondea a 3 decimales (0,1 punto
# de margen) y se acota a [-2, 2] para que unas pocas lineas con precio casi cero
# no generen millones de valores distintos. Con esto la consulta agrega en hash
# (rapido) en vez de ordenar 7,5 millones de filas cinco veces.
SQL_GRILLA_MARGEN = """
WITH base AS (
    SELECT
        EXTRACT(YEAR FROM f.fecha_comprobante)::int AS anio,
        COALESCE(da.generico, 'SIN GENERICO') AS generico,
        COALESCE(da.marca, 'SIN MARCA') AS marca,
        ds.descripcion AS sucursal,
        COALESCE(dc.des_subcanal_mkt, 'SIN SUBCANAL') AS subcanal,
        f.cantidades_con_cargo AS q,
        f.precio_unitario_neto AS p,
        f.precio_compra_neto AS c,
        GREATEST(-2.0, LEAST(2.0, round(
            ((f.precio_unitario_neto - f.precio_compra_neto) / f.precio_unitario_neto)::numeric, 3
        )))::float8 AS margen_linea
    FROM gold.fact_ventas_contabilidad f
    JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
    JOIN gold.dim_sucursal ds ON ds.id_sucursal = f.id_sucursal
    LEFT JOIN gold.dim_cliente dc ON dc.id_cliente = f.id_cliente
    WHERE {filtro}
      AND f.fecha_comprobante <= %(hasta)s::date
      AND f.cantidades_con_cargo > 0
      AND f.precio_unitario_neto > 0
      AND f.precio_compra_neto > 0
      AND NOT (COALESCE(da.generico, 'SIN GENERICO') = ANY(%(no_venta)s))
)
SELECT anio, generico, marca, sucursal, subcanal, margen_linea,
       COUNT(*) AS lineas,
       SUM(q) AS bultos,
       SUM(q * p) AS venta,
       SUM(q * c) AS costo,
       SUM(CASE WHEN p < c THEN 1 ELSE 0 END) AS lineas_bajo_costo,
       SUM(CASE WHEN p < c THEN q * (p - c) ELSE 0 END) AS perdida_bajo_costo
FROM base
GROUP BY 1, 2, 3, 4, 5, 6
""".format(filtro=_FILTRO_DOC)

SQL_BAJO_COSTO = """
SELECT
    EXTRACT(YEAR FROM f.fecha_comprobante)::int AS anio,
    ds.descripcion AS sucursal,
    f.id_cliente,
    COALESCE(dc.razon_social, 'SIN DATO') AS cliente,
    f.id_articulo,
    COALESCE(da.des_articulo, 'SIN DATO') AS articulo,
    COUNT(*) AS lineas,
    SUM(f.cantidades_con_cargo) AS bultos,
    SUM(f.cantidades_con_cargo * f.precio_unitario_neto) AS venta,
    SUM(f.cantidades_con_cargo * f.precio_compra_neto) AS costo,
    MIN(f.fecha_comprobante) AS primera,
    MAX(f.fecha_comprobante) AS ultima
FROM gold.fact_ventas_contabilidad f
JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
JOIN gold.dim_sucursal ds ON ds.id_sucursal = f.id_sucursal
LEFT JOIN gold.dim_cliente dc ON dc.id_cliente = f.id_cliente
WHERE {filtro}
  AND f.fecha_comprobante <= %(hasta)s::date
  AND f.cantidades_con_cargo > 0
  AND f.precio_unitario_neto > 0
  AND f.precio_compra_neto > 0
  AND f.precio_unitario_neto < f.precio_compra_neto
  AND NOT (COALESCE(da.generico, 'SIN GENERICO') = ANY(%(no_venta)s))
GROUP BY 1, 2, 3, 4, 5, 6
""".format(filtro=_FILTRO_DOC)

SQL_CASCADA = """
SELECT
    ds.descripcion AS sucursal,
    COALESCE(da.generico, 'SIN GENERICO') AS generico,
    SUM(f.facturacion_neta) AS bruto,
    SUM(f.descuentos) AS descuentos,
    SUM(f.subtotal_neto) AS neto,
    SUM(f.precio_unitario_bruto * f.cantidades_sin_cargo) AS sin_cargo_lista,
    SUM(f.cantidades_sin_cargo) AS q_sin_cargo,
    SUM(f.cantidades_con_cargo) AS q_con_cargo,
    COUNT(*) AS lineas
FROM gold.fact_ventas f
JOIN gold.dim_sucursal ds ON ds.id_sucursal = f.id_sucursal
LEFT JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
WHERE {filtro}
  AND f.fecha_comprobante BETWEEN %(desde)s::date AND %(hasta)s::date
  AND NOT (COALESCE(da.generico, 'SIN GENERICO') = ANY(%(no_venta)s))
GROUP BY 1, 2
""".format(filtro=_FILTRO_DOC)

# Clave compuesta obligatoria: id_vendedor se reusa entre sucursales, por eso el
# grano incluye id_sucursal y el cruce con dim_vendedor va por las dos columnas.
SQL_FUGA = """
SELECT
    f.id_cliente,
    f.id_vendedor,
    f.id_sucursal,
    SUM(f.facturacion_neta) AS bruto,
    SUM(f.descuentos) AS descuento,
    SUM(f.subtotal_neto) AS neto,
    COUNT(*) AS lineas
FROM gold.fact_ventas f
LEFT JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
WHERE {filtro}
  AND f.fecha_comprobante BETWEEN %(desde)s::date AND %(hasta)s::date
  AND NOT (COALESCE(da.generico, 'SIN GENERICO') = ANY(%(no_venta)s))
GROUP BY 1, 2, 3
""".format(filtro=_FILTRO_DOC)

SQL_DISPERSION = """
WITH articulos_materiales AS (
    SELECT f.id_articulo
    FROM gold.fact_ventas f
    JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
    WHERE {filtro}
      AND f.fecha_comprobante BETWEEN %(desde)s::date AND %(hasta)s::date
      AND NOT (COALESCE(da.generico, 'SIN GENERICO') = ANY(%(no_venta)s))
    GROUP BY 1
    HAVING SUM(f.cantidades_con_cargo) >= %(min_bultos)s
)
SELECT
    date_trunc('month', f.fecha_comprobante)::date AS mes,
    f.id_articulo,
    f.id_cliente,
    SUM(f.subtotal_neto) AS neto,
    SUM(f.cantidades_con_cargo) AS q
FROM gold.fact_ventas f
JOIN articulos_materiales am ON am.id_articulo = f.id_articulo
WHERE {filtro}
  AND f.fecha_comprobante BETWEEN %(desde)s::date AND %(hasta)s::date
  AND f.cantidades_con_cargo > 0
GROUP BY 1, 2, 3
HAVING SUM(f.cantidades_con_cargo) > 0 AND SUM(f.subtotal_neto) > 0
""".format(filtro=_FILTRO_DOC)

# Devoluciones. NO entran en ninguna tabla (una devolucion no es una venta
# realizada y ensucia toda tasa de descuento), pero hay que MEDIRLAS para poder
# decir de que tamano es lo que se dejo afuera. Si son materiales, el "Neto
# realizado" del informe no reconcilia contra un estado de resultados y el lector
# tiene derecho a saberlo antes de llevarlo a una reunion.
SQL_DEVOLUCIONES = """
SELECT SUM(f.subtotal_neto) AS neto, COUNT(*) AS lineas
FROM gold.fact_ventas f
LEFT JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
WHERE f.id_documento = 'DVVTA' AND NOT f.anulado
  AND f.fecha_comprobante BETWEEN %(desde)s::date AND %(hasta)s::date
  AND NOT (COALESCE(da.generico, 'SIN GENERICO') = ANY(%(no_venta)s))
"""

SQL_DIM_CLIENTE = """
SELECT id_cliente,
       COALESCE(razon_social, 'SIN DATO') AS cliente,
       COALESCE(des_subcanal_mkt, 'SIN SUBCANAL') AS subcanal
FROM gold.dim_cliente
"""

SQL_DIM_VENDEDOR = """
SELECT dv.id_vendedor, dv.id_sucursal,
       COALESCE(dv.des_vendedor, 'SIN DATO') AS vendedor,
       ds.descripcion AS sucursal
FROM gold.dim_vendedor dv
JOIN gold.dim_sucursal ds ON ds.id_sucursal = dv.id_sucursal
"""

SQL_DIM_SUCURSAL = "SELECT id_sucursal, descripcion AS sucursal FROM gold.dim_sucursal"

SQL_DIM_ARTICULO = """
SELECT id_articulo,
       COALESCE(des_articulo, 'SIN DATO') AS articulo,
       COALESCE(generico, 'SIN GENERICO') AS generico,
       COALESCE(marca, 'SIN MARCA') AS marca
FROM gold.dim_articulo
"""


# ---------------------------------------------------------------------------
# Armado de las entidades de fuga (clientes + preventistas)
# ---------------------------------------------------------------------------


def preparar_entidades_fuga(
    base: pd.DataFrame,
    clientes: pd.DataFrame,
    vendedores: pd.DataFrame,
    sucursales: pd.DataFrame,
    min_bruto_cliente: float = MIN_BRUTO_CLIENTE,
    min_lineas_cliente: int = MIN_LINEAS_CLIENTE,
    min_bruto_preventista: float = MIN_BRUTO_PREVENTISTA,
) -> pd.DataFrame:
    """Arma la tabla de entidades (clientes y preventistas) con su descuento.

    El grano de entrada es (id_cliente, id_vendedor, id_sucursal), asi que el
    mismo dato sirve para las dos vistas sin volver a la base. El cruce con
    dim_vendedor usa la clave compuesta (id_vendedor, id_sucursal): cruzar solo
    por id_vendedor duplicaria ventas contra las filas de otras sucursales.
    """
    if base.empty:
        return pd.DataFrame(columns=["entidad", "tipo", "sucursal", "bruto", "descuento", "lineas", "observacion"])

    por_cliente = base.groupby("id_cliente", as_index=False).agg(
        bruto=("bruto", "sum"), descuento=("descuento", "sum"), lineas=("lineas", "sum")
    )
    por_cliente = por_cliente.merge(clientes, on="id_cliente", how="left")
    principal = (
        base.sort_values("bruto", ascending=False)
        .drop_duplicates("id_cliente")[["id_cliente", "id_sucursal"]]
        .merge(sucursales, on="id_sucursal", how="left")
    )
    por_cliente = por_cliente.merge(principal[["id_cliente", "sucursal"]], on="id_cliente", how="left")
    por_cliente = por_cliente[
        (por_cliente["bruto"] > min_bruto_cliente) & (por_cliente["lineas"] >= min_lineas_cliente)
    ].copy()
    por_cliente["tipo"] = "Cliente"
    por_cliente["entidad"] = (
        por_cliente["cliente"].fillna("SIN DATO") + " (" + por_cliente["id_cliente"].astype(str) + ")"
    )
    por_cliente["observacion"] = np.where(
        por_cliente["id_cliente"].isin(constants.CLIENTES_MOSTRADOR),
        "MOSTRADOR: bolsa de venta al publico, no es un cliente real",
        "",
    )

    por_vendedor = base.groupby(["id_vendedor", "id_sucursal"], as_index=False).agg(
        bruto=("bruto", "sum"), descuento=("descuento", "sum"), lineas=("lineas", "sum")
    )
    por_vendedor = por_vendedor.merge(
        vendedores.drop(columns=["sucursal"]), on=["id_vendedor", "id_sucursal"], how="left"
    )
    # La sucursal sale siempre de dim_sucursal: hay id_vendedor que facturan sin
    # tener fila en dim_vendedor de esa sucursal, y sin esto quedarian "SIN DATO"
    # justo en la columna que permite ubicarlos.
    por_vendedor = por_vendedor.merge(sucursales, on="id_sucursal", how="left")
    por_vendedor = por_vendedor[por_vendedor["bruto"] > min_bruto_preventista].copy()
    por_vendedor["tipo"] = "Preventista"
    por_vendedor["entidad"] = (
        por_vendedor["vendedor"].fillna("SIN NOMBRE EN dim_vendedor")
        + " (id "
        + por_vendedor["id_vendedor"].astype(str)
        + ") / "
        + por_vendedor["sucursal"].fillna("SIN SUCURSAL")
    )
    # DIRECTA no es una persona: es una etiqueta de canal reusada en varias
    # sucursales. Se deja en la tabla porque el descuento es real, pero se marca
    # para que nadie le haga un descargo a un preventista inexistente.
    por_vendedor["observacion"] = np.where(
        por_vendedor["vendedor"].fillna("").str.upper().str.contains("DIRECTA"),
        "CANAL, no una persona: no accionar como desvio individual",
        "",
    )

    columnas = ["entidad", "tipo", "sucursal", "bruto", "descuento", "lineas", "observacion"]
    return pd.concat([por_cliente[columnas], por_vendedor[columnas]], ignore_index=True)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def _fila(tabla: pd.DataFrame, columna: str, valor: str) -> pd.Series | None:
    """Devuelve la primera fila cuyo `columna` vale `valor`, o None."""
    if tabla.empty or columna not in tabla.columns:
        return None
    encontrado = tabla[tabla[columna] == valor]
    if encontrado.empty:
        return None
    return encontrado.iloc[0]


def build(ctx: AnalysisContext) -> AnalysisResult:
    """Ejecuta el analisis de rentabilidad completo.

    Nunca levanta excepcion: si la base no responde o los datos son degenerados,
    devuelve un AnalysisResult con failed=True y el motivo en `notes`.
    """
    resultado = AnalysisResult(name=NOMBRE)
    no_venta = list(constants.GENERICOS_NO_VENTA)

    # La contabilidad esta desfasada respecto de fact_ventas: el corte efectivo
    # del margen es el minimo entre el corte del informe y el fin de la tabla.
    corte_margen = min(ctx.fecha_hasta, constants.FECHA_CORTE_CONTABILIDAD)
    desde_12m = ctx.desde(ctx.meses_ventana)

    try:
        grilla = ctx.sql(SQL_GRILLA_MARGEN, {"hasta": corte_margen, "no_venta": no_venta})
        detalle_bajo = ctx.sql(SQL_BAJO_COSTO, {"hasta": corte_margen, "no_venta": no_venta})
        base_cascada = ctx.sql(
            SQL_CASCADA, {"desde": desde_12m, "hasta": ctx.fecha_hasta, "no_venta": no_venta}
        )
        base_fuga = ctx.sql(
            SQL_FUGA, {"desde": desde_12m, "hasta": ctx.fecha_hasta, "no_venta": no_venta}
        )
        base_dispersion = ctx.sql(
            SQL_DISPERSION,
            {
                "desde": desde_12m,
                "hasta": ctx.fecha_hasta,
                "no_venta": no_venta,
                "min_bultos": MIN_BULTOS_ARTICULO,
            },
        )
        devoluciones = ctx.sql(
            SQL_DEVOLUCIONES, {"desde": desde_12m, "hasta": ctx.fecha_hasta, "no_venta": no_venta}
        )
        dim_clientes = ctx.sql(SQL_DIM_CLIENTE)
        dim_vendedores = ctx.sql(SQL_DIM_VENDEDOR)
        dim_sucursales = ctx.sql(SQL_DIM_SUCURSAL)
        dim_articulos = ctx.sql(SQL_DIM_ARTICULO)
    except Exception as error:  # noqa: BLE001 - el informe no puede caerse por una tabla
        resultado.failed = True
        resultado.notes.append(f"No se pudo leer la base para Rentabilidad: {error}")
        return resultado

    if grilla.empty and base_cascada.empty and base_dispersion.empty:
        resultado.failed = True
        resultado.notes.append(
            "Rentabilidad sin datos: ninguna de las consultas devolvio filas para la ventana pedida."
        )
        return resultado

    # -- Tablas -------------------------------------------------------------
    # El armado tambien va protegido, no solo el SQL. Un dato degenerado que la
    # base devuelve legitimamente (una columna toda en NaN, un grupo con un solo
    # elemento) no puede tumbar el libro entero: el contrato de este modulo es
    # devolver failed=True con el motivo, nunca levantar.
    try:
        tabla_margen = construir_tabla_margen(grilla)
        tabla_bajo = construir_bajo_costo(detalle_bajo)
        tabla_cascada = construir_cascada(base_cascada)
        entidades = preparar_entidades_fuga(base_fuga, dim_clientes, dim_vendedores, dim_sucursales)
        tabla_fuga = detectar_fuga_outliers(entidades)
        celdas = resumir_celdas_precio(base_dispersion)
        tabla_dispersion = rankear_dispersion(celdas, dim_articulos)
    except Exception as error:  # noqa: BLE001
        resultado.failed = True
        resultado.notes.append(
            f"Rentabilidad no pudo construir sus tablas: {type(error).__name__}: {error}"
        )
        return resultado

    resultado.tables = {
        "margen": tabla_margen,
        "bajo_costo": tabla_bajo,
        "cascada": tabla_cascada,
        "fuga_outliers": tabla_fuga,
        "dispersion": tabla_dispersion,
    }

    # -- Numeros de portada -------------------------------------------------
    total_margen = _fila(tabla_margen, "Valor", ETIQUETA_TOTAL)
    total_bajo = _fila(tabla_bajo, "Valor", ETIQUETA_TOTAL)
    cascada_total = tabla_cascada[tabla_cascada["ambito"] == ETIQUETA_TOTAL] if not tabla_cascada.empty else pd.DataFrame()

    margen_pond = float(total_margen["Margen Ponderado %"]) if total_margen is not None else np.nan
    perdida_bajo = float(total_bajo["Perdida $"]) if total_bajo is not None else np.nan

    bruto_12m = descuento_12m = neto_12m = sin_cargo_12m = np.nan
    if not cascada_total.empty:
        def _monto(concepto):
            fila = cascada_total[cascada_total["concepto"] == concepto]
            return float(fila["monto"].iloc[0]) if not fila.empty else np.nan

        bruto_12m = _monto(CONCEPTO_BRUTO)
        neto_12m = _monto(CONCEPTO_NETO)
        sin_cargo_12m = _monto(CONCEPTO_SIN_CARGO)
        descuento_12m = _monto(CONCEPTO_SIN_CARGO) + _monto(CONCEPTO_COMERCIAL)

    tasa_fuga = descuento_12m / bruto_12m if bruto_12m and np.isfinite(bruto_12m) else np.nan

    resultado.headlines = [
        Headline(
            label="Margen bruto ponderado",
            value=margen_pond,
            number_format="0.0%",
            note=f"Contabilidad 2022-01-03 a {corte_margen}. NO es el mismo periodo que el resto del informe.",
            higher_is_better=True,
        ),
        Headline(
            label="Margen destruido vendiendo bajo costo",
            value=abs(perdida_bajo) if np.isfinite(perdida_bajo) else np.nan,
            number_format='$ #,##0',
            note=(
                "Pesos NOMINALES acumulados de toda la historia contable "
                f"(2022-01-03 a {corte_margen}). Suma de lineas facturadas a menos del costo de compra."
            ),
            higher_is_better=False,
        ),
        Headline(
            label="Fuga de descuentos",
            value=tasa_fuga,
            number_format="0.0%",
            note=f"Descuento total sobre bruto de lista, ultimos {ctx.meses_ventana} meses a {ctx.fecha_hasta}.",
            higher_is_better=False,
        ),
        Headline(
            label="Neto realizado",
            value=neto_12m,
            number_format='$ #,##0',
            note=f"Pesos NOMINALES de los ultimos {ctx.meses_ventana} meses. No comparable contra otros periodos.",
            higher_is_better=True,
        ),
    ]

    # -- Alertas ------------------------------------------------------------
    # Las alertas y las notas se arman aparte y con red propia: son texto derivado
    # de tablas que YA estan calculadas y guardadas. Si una alerta falla al
    # redactarse, se pierde esa prosa, no las cinco tablas ni los indicadores.
    try:
        resultado.alerts = _construir_alertas(
            tabla_margen=tabla_margen,
            tabla_bajo=tabla_bajo,
            tabla_cascada=tabla_cascada,
            tabla_fuga=tabla_fuga,
            detalle_bajo=detalle_bajo,
            perdida_bajo=perdida_bajo,
            margen_pond=margen_pond,
            corte_margen=corte_margen,
        )
    except Exception as error:  # noqa: BLE001
        resultado.alerts = []
        resultado.notes.append(
            f"Rentabilidad: no se pudieron redactar las alertas ({type(error).__name__}: {error}). "
            "Las tablas del analisis estan completas; lo que falta es el resumen de portada."
        )

    # -- Notas metodologicas -----------------------------------------------
    metodologia: list[str] = []
    try:
        metodologia = _construir_notas(
            ctx=ctx,
            corte_margen=corte_margen,
            desde_12m=desde_12m,
            grilla=grilla,
            celdas=celdas,
            tabla_dispersion=tabla_dispersion,
            bruto_12m=bruto_12m,
            sin_cargo_12m=sin_cargo_12m,
            neto_12m=neto_12m,
            devoluciones=devoluciones,
        )
    except Exception as error:  # noqa: BLE001
        metodologia = [
            f"Rentabilidad: no se pudo armar la metodologia ({type(error).__name__}: {error}). "
            "ATENCION: las tablas estan, pero sin sus advertencias. No usarlas sin revisar el modulo."
        ]
    resultado.notes = [*resultado.notes, *metodologia]
    return resultado


def _construir_alertas(
    *,
    tabla_margen: pd.DataFrame,
    tabla_bajo: pd.DataFrame,
    tabla_cascada: pd.DataFrame,
    tabla_fuga: pd.DataFrame,
    detalle_bajo: pd.DataFrame,
    perdida_bajo: float,
    margen_pond: float,
    corte_margen: str,
) -> list[Alert]:
    """Cuatro hallazgos que no pueden quedar enterrados adentro de una tabla."""
    alertas: list[Alert] = []

    # 1) Venta bajo costo.
    if np.isfinite(perdida_bajo) and perdida_bajo < 0:
        lineas = float(detalle_bajo["lineas"].sum()) if not detalle_bajo.empty else 0.0
        bultos = float(detalle_bajo["bultos"].sum()) if not detalle_bajo.empty else 0.0
        # Parte de la "perdida" no es comercial sino un costo mal cargado. Se
        # separa para no mandar a nadie a renegociar precios contra un bug de ETL.
        sospechoso = detalle_bajo[
            detalle_bajo["costo"] > UMBRAL_COSTO_IMPLAUSIBLE * detalle_bajo["venta"]
        ]
        perdida_sospechosa = (
            float(sospechoso["venta"].sum() - sospechoso["costo"].sum()) if not sospechoso.empty else 0.0
        )
        alertas.append(
            Alert(
                severity="critica",
                title="Se vende por debajo del costo de forma sistematica",
                detail=(
                    f"{lineas:,.0f} lineas y {bultos:,.0f} bultos se facturaron a menos del costo de compra, "
                    f"destruyendo ${abs(perdida_bajo):,.0f} nominales de margen bruto hasta {corte_margen}. "
                    f"De ese total, ${abs(perdida_sospechosa):,.0f} "
                    f"({abs(perdida_sospechosa) / abs(perdida_bajo):.0%}) corresponde a lineas con un costo "
                    f"cargado por encima de {UMBRAL_COSTO_IMPLAUSIBLE:.0f}x el precio de venta, que casi con "
                    "seguridad es un error de carga y hay que resolver en sistemas antes de tocar precios. "
                    "El detalle por sucursal, cliente y articulo esta en la hoja 'bajo_costo'."
                ),
                amount=abs(perdida_bajo),
            )
        )

    # 2) Gobierno del descuento: peor sucursal contra la mejor.
    #
    # La brecha se informa DESCOMPUESTA. El descuento total de una sucursal mezcla
    # dos palancas que no se manejan igual: la mercaderia entregada sin cargo (accion
    # comercial, muchas veces financiada por el proveedor, se decide por campana) y
    # el descuento comercial en factura (gobierno de precios, se decide por cliente).
    # Presentar la brecha total como plata "recuperable con politica de precios"
    # promete algo que solo se cobra sacando promociones. Medido en la ventana: de
    # los 9,2 puntos que separan CASA CENTRAL de SUCURSAL LIBERTADOR, 5,0 puntos son
    # mercaderia sin cargo y solo 4,3 son descuento en factura.
    if not tabla_cascada.empty:
        sucursales = tabla_cascada[tabla_cascada["ambito"].str.startswith("Sucursal: ")]
        brutos = sucursales[sucursales["concepto"] == CONCEPTO_BRUTO].set_index("ambito")["monto"]
        sin_cargo = sucursales[sucursales["concepto"] == CONCEPTO_SIN_CARGO].set_index("ambito")["monto"]
        comercial = sucursales[sucursales["concepto"] == CONCEPTO_COMERCIAL].set_index("ambito")["monto"]
        tasas = ((sin_cargo + comercial) / brutos).dropna()
        tasa_sin_cargo = (sin_cargo / brutos).dropna()
        tasa_comercial = (comercial / brutos).dropna()
        # Solo sucursales con volumen: una sucursal chica distorsiona el contraste.
        materiales = brutos[brutos > brutos.sum() * 0.01].index
        tasas = tasas.reindex(materiales).dropna()
        if len(tasas) >= 2:
            peor, mejor = tasas.idxmax(), tasas.idxmin()
            bruto_peor = float(brutos[peor])
            brecha_comercial = float(tasa_comercial.get(peor, np.nan) - tasa_comercial.get(mejor, np.nan))
            brecha_sin_cargo = float(tasa_sin_cargo.get(peor, np.nan) - tasa_sin_cargo.get(mejor, np.nan))
            valor_comercial = brecha_comercial * bruto_peor
            valor_sin_cargo = brecha_sin_cargo * bruto_peor
            alertas.append(
                Alert(
                    severity="alta",
                    title="Gobierno del descuento: la brecha entre sucursales, separada en sus dos palancas",
                    detail=(
                        f"{peor.replace('Sucursal: ', '')} entrega {tasas[peor]:.2%} de descuento total sobre "
                        f"bruto contra {tasas[mejor]:.2%} de {mejor.replace('Sucursal: ', '')}. Esa brecha NO es "
                        "una sola cosa: "
                        f"{brecha_comercial * 100:.1f} puntos son descuento comercial en factura "
                        f"(${valor_comercial:,.0f} nominales, la parte que se corrige con politica de precios) y "
                        f"{brecha_sin_cargo * 100:.1f} puntos son mercaderia entregada sin cargo "
                        f"(${valor_sin_cargo:,.0f} nominales, que es accion comercial y solo se recupera dando de "
                        "baja promociones). El numero accionable es el primero. "
                        "Antes de atribuirlo a politica interna hay que verificar que la mezcla de generico y de "
                        "subcanal sea comparable: este calculo NO la controla."
                    ),
                    amount=float(valor_comercial) if np.isfinite(valor_comercial) else None,
                )
            )

    # 3) La anomalia de los ids consecutivos.
    if not detalle_bajo.empty and "id_cliente" in detalle_bajo.columns:
        sospechosos = detalle_bajo[detalle_bajo["id_cliente"].isin(CLIENTES_ID_CONSECUTIVO)]
        if not sospechosos.empty:
            perdida = float(sospechosos["venta"].sum() - sospechosos["costo"].sum())
            lineas = float(sospechosos["lineas"].sum())
            # Hay que mirar las dos puntas del rango, no solo la primera fecha: con
            # solo `primera` un cliente que arranca en septiembre y sigue comprando
            # hasta enero se reporta igual que uno que facturo todo en un solo dia,
            # y "toda la perdida en un dia" es justamente lo que hace sospechar de
            # un error de carga en vez de una politica comercial.
            fechas = pd.to_datetime(
                pd.concat([sospechosos["primera"], sospechosos["ultima"]]), errors="coerce"
            )
            dias = int(fechas.dropna().nunique())
            alertas.append(
                Alert(
                    severity="alta",
                    title="Los tres peores destructores de margen tienen ids consecutivos: verificar antes de confrontar",
                    detail=(
                        f"Los clientes {'/'.join(str(i) for i in CLIENTES_ID_CONSECUTIVO)} son ids consecutivos, "
                        f"todos de CASA CENTRAL, con margen cercano a -91% y ${abs(perdida):,.0f} de perdida en "
                        f"{lineas:,.0f} lineas concentradas en {dias} fecha(s). Un cliente concentra toda su perdida "
                        "en un solo dia. Ese patron es propio de un error de carga de costo o una liquidacion puntual, "
                        "NO de una politica comercial: hay que confirmarlo con administracion antes de sentar a nadie."
                    ),
                    amount=abs(perdida),
                )
            )

    # 4) Brecha de margen: sucursal contra subcanal, sin decidir de antemano cual gana.
    #
    # Antes esta alerta se titulaba "la brecha entre sucursales es mayor que la
    # brecha entre canales" sin haber calculado nunca la brecha entre canales. Con
    # los datos de la ventana la afirmacion es FALSA: la brecha de sucursales es de
    # 10,1 puntos (CASA CENTRAL 23,12% vs LA QUIACA 13,07%) y la de subcanales es de
    # 13,6 (RESTAURANTE 25,87% vs SUBDISTRIBUIDOR 12,24%). Ahora se miden las dos y
    # se dice cual es mayor, porque de eso depende donde se pone la gente: reordenar
    # sucursales o reordenar la politica por canal son proyectos distintos.
    brechas = {}
    for dimension in ("Sucursal", "Subcanal"):
        bloque = (
            tabla_margen[tabla_margen["Dimension"] == dimension]
            if not tabla_margen.empty
            else pd.DataFrame()
        )
        if len(bloque) < 2:
            continue
        materiales = bloque[
            bloque["Venta Neta Nominal $"] > bloque["Venta Neta Nominal $"].sum() * 0.01
        ]
        materiales = materiales[materiales["Margen Ponderado %"].notna()]
        if len(materiales) < 2:
            continue
        mejor = materiales.loc[materiales["Margen Ponderado %"].idxmax()]
        peor = materiales.loc[materiales["Margen Ponderado %"].idxmin()]
        brecha = float(mejor["Margen Ponderado %"] - peor["Margen Ponderado %"])
        brechas[dimension] = {
            "mejor": mejor,
            "peor": peor,
            "brecha": brecha,
            "valor": brecha * float(peor["Venta Neta Nominal $"]),
        }

    if brechas:
        dominante = max(brechas, key=lambda clave: brechas[clave]["brecha"])
        datos = brechas[dominante]
        otro = "Subcanal" if dominante == "Sucursal" else "Sucursal"
        comparacion = ""
        if otro in brechas:
            comparacion = (
                f" Para dimensionarlo: la brecha por {otro.lower()} es de "
                f"{brechas[otro]['brecha'] * 100:.1f} puntos "
                f"({brechas[otro]['mejor']['Valor']} {brechas[otro]['mejor']['Margen Ponderado %']:.2%} contra "
                f"{brechas[otro]['peor']['Valor']} {brechas[otro]['peor']['Margen Ponderado %']:.2%}), "
                f"o sea que el margen se explica mas por {dominante.lower()} que por {otro.lower()}."
            )
        alertas.append(
            Alert(
                severity="media",
                title=f"La mayor brecha de margen esta entre {dominante.lower()}es, no en otro corte",
                detail=(
                    f"{datos['mejor']['Valor']} rinde {datos['mejor']['Margen Ponderado %']:.2%} de margen "
                    f"ponderado contra {datos['peor']['Margen Ponderado %']:.2%} de {datos['peor']['Valor']}: "
                    f"{datos['brecha'] * 100:.1f} puntos de diferencia. Cerrar esa brecha en "
                    f"{datos['peor']['Valor']} vale ${datos['valor']:,.0f} nominales acumulados."
                    f"{comparacion} "
                    f"Dato de contabilidad hasta {corte_margen}, no del periodo corriente, y acumulado de "
                    "varios anios con inflacion adentro: el porcentaje es comparable, la plata no. "
                    f"Margen ponderado de la compania: {margen_pond:.2%}."
                ),
                amount=float(datos["valor"]),
            )
        )

    # Extra util: tamano de la lista de auditoria de descuentos.
    if not tabla_fuga.empty:
        cuerpo = tabla_fuga[
            (tabla_fuga["entidad"] != ETIQUETA_TOTAL)
            & (~tabla_fuga["entidad"].astype(str).str.startswith("SUBTOTAL"))
        ]
        if not cuerpo.empty:
            # Las dos vistas NO se suman: cada linea facturada tiene un cliente y un
            # preventista, asi que el exceso del cliente ya esta adentro del exceso
            # de su preventista. Se informa la vista cliente como cifra accionable y
            # la vista preventista al lado, explicitamente como el mismo dinero.
            por_tipo = cuerpo.groupby("tipo")["exceso_vs_mediana"].sum()
            exceso_cliente = float(por_tipo.get("Cliente", 0.0))
            exceso_preventista = float(por_tipo.get("Preventista", 0.0))
            clientes = int((cuerpo["tipo"] == "Cliente").sum())
            preventistas = int((cuerpo["tipo"] == "Preventista").sum())
            alertas.append(
                Alert(
                    severity="alta",
                    title="Lista de auditoria de descuentos lista para trabajar",
                    detail=(
                        f"{clientes} clientes concentran ${exceso_cliente:,.0f} nominales de descuento por "
                        "encima de lo que habrian gastado a la tasa mediana de su grupo (z robusto > "
                        f"{UMBRAL_Z}, cola alta). En paralelo, {preventistas} preventistas quedan marcados por "
                        f"${exceso_preventista:,.0f}, que es LA MISMA plata cortada por vendedor y no se suma a "
                        "la anterior. La cifra a perseguir es la de clientes; la de preventistas dice por que "
                        "mostrador se fue."
                    ),
                    amount=exceso_cliente,
                )
            )

    return alertas


def _construir_notas(
    *,
    ctx: AnalysisContext,
    corte_margen: str,
    desde_12m: str,
    grilla: pd.DataFrame,
    celdas: pd.DataFrame,
    tabla_dispersion: pd.DataFrame,
    bruto_12m: float,
    sin_cargo_12m: float,
    neto_12m: float,
    devoluciones: pd.DataFrame | None = None,
) -> list[str]:
    """Notas metodologicas obligatorias para la hoja Metodologia."""
    notas = [
        # OBLIGATORIA: desfasaje temporal del margen.
        "MARGEN — La tabla 'margen' sale de gold.fact_ventas_contabilidad, que cubre 2022-01-03 a "
        f"{corte_margen}, mientras el resto del informe llega a {ctx.fecha_hasta}. NUNCA presentar el "
        "margen al lado de las cifras 2026 como si fueran del mismo periodo: el ETL contable esta unos "
        "tres meses atrasado y las dos tablas nunca se cruzaron por ese motivo.",
        "MARGEN — Margen bruto ponderado por volumen = SUM(q*(p-c)) / SUM(q*p) con q=cantidades_con_cargo, "
        "p=precio_unitario_neto, c=precio_compra_neto. Es la unica medida agregada honesta: el promedio "
        "simple de margenes por linea le da el mismo peso a una venta de 1 bulto que a una de 1.000.",
        "MARGEN — La dispersion se informa con percentiles y MAD, NUNCA con media y desvio estandar. El "
        "desvio crudo del margen por linea llega a 64 en CERVEZAS y a 1.250 en BOUTIQUE porque unas pocas "
        "lineas con precio casi cero hacen explotar el cuadrado.",
        "MARGEN — Los percentiles se calculan sobre un histograma del margen por linea redondeado a 3 "
        "decimales y acotado a [-2, 2] (resolucion de 0,1 punto de margen). Se valido contra "
        "PERCENTILE_CONT sobre los datos crudos y reproduce p25/p50/p75 al segundo decimal, sin tener que "
        "traer 7,5 millones de lineas a memoria.",
        # OBLIGATORIA: la red no existio siempre, y sin esto la serie anual miente.
        "MARGEN — La serie de margen por anio NO es una serie comparable tal cual: la red crecio de una "
        "sucursal a catorce dentro del periodo, y las sucursales nuevas rinden menos margen que CASA "
        "CENTRAL. Parte de la caida anual es cambio de mezcla de sucursales, no deterioro de gestion. Por "
        "eso el bloque Anio trae la columna 'Sucursales' (cuantas facturaban ese anio), la columna 'Margen "
        "Panel Constante' (el mismo margen recalculado solo sobre las sucursales presentes en TODOS los "
        "anios) y una 'Observacion' que marca los anios de red incompleta. Comparar anios por el panel "
        "constante; el margen sin corregir sirve para saber cuanto gano la empresa, no para juzgar gestion.",
        f"PESOS — Todos los importes son NOMINALES y sin deflactar. Con la inflacion argentina un +45% "
        "nominal puede ser +10,7% real: las series de plata NO se comparan entre periodos. Solo los bultos "
        "y los hectolitros son comparables en el tiempo. Los porcentajes de margen son ratios del mismo "
        "periodo y son mucho mas seguros, aunque tambien se distorsionan si el precio de venta y el de "
        "compra se actualizan en fechas distintas.",
        "COLUMNAS DE PLATA — 'facturacion_neta' es BRUTO a precio de lista pese al nombre (verificado: "
        "precio_unitario_bruto * cantidades_total). El neto real es 'subtotal_neto' = facturacion_neta - "
        "descuentos, identidad que se cumple en el 99,9963% de 1,3 millones de lineas de 2026. "
        "'subtotal_final' incluye impuestos y no es neto. 'bonificacion' es un PORCENTAJE, jamas se suma.",
        "CASCADA — La mercaderia sin cargo ya viene DENTRO de 'descuentos' (esas lineas llevan "
        "bonificacion=100), por eso el escalon 'Descuento comercial' es descuentos menos lo entregado sin "
        "cargo: restar las dos cosas por separado contaria la misma plata dos veces. El escalon 'Ajuste / "
        "residuo de identidad' muestra el 0,004% de lineas donde la identidad no cierra en vez de "
        "maquillar el cuadre.",
        "CASCADA — El renglon 'Memo' NO forma parte del recorrido: es la misma mercaderia sin cargo "
        "valuada al precio realizado por bulto (neto / cantidades_con_cargo) en lugar de a precio de lista, "
        "que es lo que efectivamente se resigno de caja.",
        f"FUGA — Materialidad: un cliente entra si facturo mas de ${MIN_BRUTO_CLIENTE:,.0f} brutos y tiene "
        f"al menos {MIN_LINEAS_CLIENTE} lineas en la ventana; un preventista, mas de "
        f"${MIN_BRUTO_PREVENTISTA:,.0f}. Debajo de eso la tasa de descuento es un artefacto de dos facturas.",
        f"FUGA — El outlier se define con el z modificado de mediana + MAD (stats.robust_zscore) con corte "
        f"z > {UMBRAL_Z}, el criterio de Iglewicz-Hoaglin, aplicado SOLO A LA COLA ALTA: interesa quien "
        "descuenta de mas, no quien descuenta de menos. El z clasico no sirve: los mismos casos "
        "extremos que se quieren detectar inflan el desvio estandar y quedan dentro de sus propios limites.",
        "FUGA — Clientes y preventistas son DOS PARTICIONES DE LA MISMA VENTA: toda linea facturada tiene "
        "exactamente un cliente y exactamente un preventista, con lo cual el descuento de un cliente "
        "desviado ya esta contenido en el de su preventista. Ni el bruto, ni el descuento, ni el exceso se "
        "suman entre los dos bloques. El TOTAL GENERAL informa la vista CLIENTE, que es con quien se "
        "negocia; la vista PREVENTISTA queda como subtotal separado para leer, no para sumar.",
        "FUGA — Los preventistas se cruzan con dim_vendedor por la clave compuesta (id_vendedor, "
        "id_sucursal). id_vendedor se reusa entre sucursales; cruzar solo por el id duplica ventas contra "
        "filas de otras sucursales. Las entradas 'DIRECTA' son una etiqueta de canal reusada en varias "
        "sucursales, no una persona, y estan marcadas para que no se accionen como desvio individual.",
        # OBLIGATORIA: piso de ruido inflacionario en dispersion.
        f"DISPERSION — La inflacion argentina intramensual, del orden de 2-3%, es el piso de ruido: un "
        "cliente que compra el dia 2 y otro que compra el 28 pagan legitimamente distinto por el mismo "
        f"articulo. Un coeficiente de variacion por debajo de {PISO_CV_INFLACION:.0%} NO es un problema de "
        "control de precios y la columna 'diagnostico' lo dice explicitamente. La 'brecha_vs_mediana' es "
        "por el mismo motivo una COTA SUPERIOR de la plata recuperable, no una promesa.",
        "DISPERSION — Precio realizado por cliente = subtotal_neto / cantidades_con_cargo. Se usa el neto y "
        "no facturacion_neta porque la facturacion es lista x cantidad y por construccion no tiene "
        "dispersion: el analisis daria siempre cero.",
        f"DISPERSION — Materialidad: cada celda (articulo, mes) necesita al menos {MIN_CLIENTES_CELDA} "
        f"clientes distintos, y el articulo entra al ranking con al menos {MIN_MESES_ARTICULO} meses y "
        f"{MIN_BULTOS_ARTICULO:,.0f} bultos en la ventana.",
        "DISPERSION — La celda es (articulo, mes) para TODA la empresa: NO se abre por sucursal. Un mismo "
        "articulo puede tener legitimamente otro precio en LA QUIACA que en CASA CENTRAL por flete y por "
        "competencia local, y esa diferencia entra al CV como si fuera descontrol de precios. El ranking "
        "sirve para elegir donde mirar, no para condenar un articulo: antes de llevarlo a una reunion hay "
        "que confirmar que la banda p10-p90 se abre DENTRO de una misma sucursal y no entre sucursales.",
        f"BAJO COSTO — No todo lo que aparece bajo costo es una decision comercial. Las lineas cuyo "
        f"costo cargado supera {UMBRAL_COSTO_IMPLAUSIBLE:.0f} veces el precio de venta se marcan como "
        "'COSTO IMPLAUSIBLE' en la columna Observacion: nadie vende a un tercio del costo de forma "
        "deliberada y repetida, esa es la firma de un precio_compra_neto mal cargado o de una unidad de "
        "medida cambiada. Van a sistemas, no a comercial.",
        "DISPERSION — La banda p10/p50/p90 y su ratio se informan del ultimo mes disponible (columna "
        "'mes_referencia'), no promediados entre meses: con inflacion mensual del 2-3% un promedio de "
        "precios de meses distintos no es el precio de nada, y mezclar un p10 de enero con un p90 de julio "
        "inventaria dispersion que no existe. El CV si es ponderado por bultos a lo largo de toda la ventana.",
        f"UNIVERSO — Se excluyen de todo el modulo los genericos que no son articulos de venta "
        f"({', '.join(constants.GENERICOS_NO_VENTA)}): llevan unidades pero no facturacion, y dejarlos "
        "adentro genera anomalias falsas de volumen. Se toman solo comprobantes FCVTA no anulados. "
        "Esto hace que las cifras NO coincidan con analisis previos que dejaban ENVASES CCU adentro: "
        "el envase retornable tiene una mecanica de deposito, no es un producto que se comercialice, y "
        "arrastra por si solo una cuarta parte de las lineas nominalmente bajo costo.",
        "UNIVERSO — Los clientes de mostrador (bolsas de venta al publico) se MARCAN en la columna "
        "'Observacion' en vez de borrarse, para que la facturacion siga reconciliando contra los totales.",
        f"VENTANAS — Cascada, fuga y dispersion usan los ultimos {ctx.meses_ventana} meses "
        f"({desde_12m} a {ctx.fecha_hasta}) sobre gold.fact_ventas. Margen y venta bajo costo usan toda la "
        f"historia de gold.fact_ventas_contabilidad hasta {corte_margen}.",
    ]

    if bruto_12m and np.isfinite(bruto_12m):
        notas.append(
            f"CASCADA — Cierre medido de la ventana: bruto de lista ${bruto_12m:,.0f} nominales, "
            f"mercaderia sin cargo ${sin_cargo_12m:,.0f}, neto realizado ${neto_12m:,.0f}."
        )

    # Tamano de lo que se dejo afuera al quedarse solo con FCVTA.
    if devoluciones is not None and not devoluciones.empty:
        neto_dev = float(pd.to_numeric(devoluciones["neto"], errors="coerce").fillna(0.0).sum())
        lineas_dev = float(pd.to_numeric(devoluciones["lineas"], errors="coerce").fillna(0.0).sum())
        if lineas_dev:
            proporcion = abs(neto_dev) / neto_12m if neto_12m and np.isfinite(neto_12m) else np.nan
            notas.append(
                "DEVOLUCIONES — Todo el modulo trabaja solo con comprobantes FCVTA: las devoluciones "
                f"(DVVTA) NO se restan. En la ventana suman ${neto_dev:,.0f} nominales en {lineas_dev:,.0f} "
                + (f"lineas, un {proporcion:.1%} del neto realizado. " if np.isfinite(proporcion) else "lineas. ")
                + "Se excluyen a proposito, porque una devolucion mezclada con una venta distorsiona toda "
                "tasa de descuento y todo margen por linea, pero eso significa que el 'Neto realizado' de "
                "este informe es venta FACTURADA y no reconcilia contra un estado de resultados sin ese "
                "ajuste. Si la proporcion sube de un digito hay que revisar por que se devuelve tanto."
            )

    # Validacion del metodo de dispersion: un SKU de precio unico debe dar CV ~0.
    if not tabla_dispersion.empty:
        cuerpo = tabla_dispersion[tabla_dispersion["articulo"] != ETIQUETA_TOTAL]
        cuerpo = cuerpo[np.isfinite(cuerpo["cv_ponderado_pct"])]
        if not cuerpo.empty:
            mejor = cuerpo.loc[cuerpo["cv_ponderado_pct"].idxmin()]
            notas.append(
                "DISPERSION (validacion del metodo) — El articulo mejor controlado de la ventana es "
                f"'{mejor['articulo']}' con CV ponderado {mejor['cv_ponderado_pct']:.2%}, "
                f"ratio p90/p10 {mejor['ratio_p90_p10']:.3f} sobre {mejor['bultos']:,.0f} bultos. "
                "Un SKU de precio verdaderamente unico (tipicamente envase retornable) devuelve CV cercano "
                "a cero, lo que prueba que la dispersion medida en los demas articulos es varianza real de "
                "politica de precios y no ruido del metodo."
            )
    if not celdas.empty:
        notas.append(
            f"DISPERSION — Se analizaron {len(celdas):,} celdas (articulo, mes) que superaron el piso de "
            f"{MIN_CLIENTES_CELDA} clientes, sobre {celdas['id_articulo'].nunique():,} articulos."
        )
    if not grilla.empty:
        notas.append(
            f"MARGEN — Base: {float(grilla['lineas'].sum()):,.0f} lineas de contabilidad con precio de "
            "venta y de compra positivos (precio_compra_neto esta poblado en ~99% de las filas)."
        )
    return notas
