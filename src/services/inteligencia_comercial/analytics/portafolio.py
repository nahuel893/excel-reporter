"""Portafolio y canales: ABC-XYZ, mix por subcanal, cross-sell y ciclo de vida del SKU.

Responde cuatro preguntas comerciales que hoy nadie tiene contestadas con numeros:

1. **Que parte del catalogo paga la cuenta.** El ABC-XYZ cruza cuanto factura cada
   SKU (ABC sobre neto de los ultimos 12 meses) contra que tan predecible es su
   demanda (XYZ sobre el coeficiente de variacion de los bultos mensuales). La
   celda AX es la que hay que no quebrar nunca; la celda CZ es la que hay que
   discutir si sigue en la lista de precios.
2. **Si cada subcanal compra un surtido distinto.** Se arma la tabla de
   contingencia subcanal x generico en BULTOS y se calculan residuos de Pearson.
   Ojo con la lectura: la V de Cramer es chica (~0.11), asi que
   los residuos sirven para encontrar ANOMALIAS puntuales, no para afirmar que
   cada subcanal tiene un surtido estructuralmente diferente.
3. **Donde esta el espacio en blanco.** Penetracion por (subcanal, generico) y,
   por cliente, los genericos que NO compra y sus pares del mismo subcanal si.
   El ranking va por ARS-por-conversion y no por ARS totales, porque un equipo
   comercial trabaja listas de cuentas, no promedios.
4. **Que entra y que salio del catalogo.** SKUs lanzados en los ultimos 12 meses
   con su rampa mes a mes, y SKUs sin venta hace mas de 90 dias que todavia
   tienen stock.

Reglas de dominio que este modulo respeta y que ya costaron un numero equivocado:

* `facturacion_neta` es BRUTO a precio de lista; el neto real es `subtotal_neto`
  (= facturacion_neta - descuentos). Todo importe de este modulo es NETO y las
  columnas lo dicen. `bonificacion` es una TASA porcentual y nunca se suma.
* Los pesos NO se comparan entre periodos: la inflacion argentina hace que +45%
  nominal sea +10.7% real. Todo lo interperiodo va en BULTOS.
* Se excluyen los genericos que no son articulos de venta
  (`constants.GENERICOS_NO_VENTA`): material promocional, envases, equipos de
  frio. Sin ese filtro el stock muerto da ~100 veces mas grande.
* Se excluyen los presupuestos (`PRVTA`): son 100 lineas pero arrastran
  $1.8e9 y 85.104 bultos que nunca se facturaron.
* Los clientes mostrador (`constants.CLIENTES_MOSTRADOR`) se marcan y se informan,
  nunca se borran en silencio.
* Nada se redondea ni se trunca. El formato es tarea de Excel.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.services.inteligencia_comercial import constants, stats
from src.services.inteligencia_comercial.contracts import (
    Alert,
    AnalysisContext,
    AnalysisResult,
    Headline,
)

NOMBRE = "Portafolio y canales"
ETIQUETA_TOTAL = "TOTAL GENERAL"

# Solo facturas y devoluciones. PRVTA (presupuesto) no es una venta: son 100
# lineas en 12 meses pero suman $1.808e9 y 85.104 bultos que jamas se entregaron.
DOCUMENTOS_VENTA = (constants.DOC_FACTURA, constants.DOC_DEVOLUCION)

# Ventana corta usada para el cross-sell. Seis meses es lo que un supervisor
# acepta como "no compra"; con 12 meses una compra unica y vieja tapa la brecha.
MESES_CROSS_SELL = 6

# Un cliente entra al listado de brechas solo si sus pares del mismo subcanal
# compran ese generico en al menos este porcentaje. Debajo de eso la "brecha"
# es simplemente un producto que ese canal no consume.
UMBRAL_PENETRACION_BRECHA = 0.30

# Una celda (subcanal, generico) necesita una mediana de pares creible.
MIN_COMPRADORES_CELDA = 5
MIN_CLIENTES_SUBCANAL = 20

# Filas mostradas del detalle por cliente. El total de la tabla informa el
# universo completo, no solo lo mostrado.
MAX_FILAS_BRECHAS = 500

# Subcanales / genericos con menos de este share del volumen se agrupan en una
# fila "OTROS". Sin agrupar, la chi-cuadrado se apoya en celdas con esperado < 5
# y los residuos dejan de ser aproximadamente normales.
UMBRAL_COLA_CONTINGENCIA = 0.001
ETIQUETA_OTROS_FILA = "OTROS SUBCANALES"
ETIQUETA_OTROS_COL = "OTROS GENERICOS"

# Dias sin venta a partir de los cuales un SKU con stock se considera muerto.
DIAS_STOCK_MUERTO = 90

# Minimo de facturas para que las reglas de asociacion de una fuerza de ventas
# tengan sentido estadistico.
MIN_FACTURAS_FV = 500

# Las facturas NUNCA mezclan fuerza de ventas (verificado: 369.049 de 369.049
# facturas tienen exactamente una). Por eso las reglas se calculan DENTRO de
# cada fuerza: una regla que cruza preventa y autoventa mide la estructura de
# rutas, no el comportamiento del cliente.
ETIQUETAS_FUERZA_VENTAS = {
    1: "FV1 - Preventa",
    4: "FV4 - Autoventa",
    -1: "Sin fuerza de ventas asignada",
}


# ---------------------------------------------------------------------------
# Utilidades de calendario
# ---------------------------------------------------------------------------


def _sumar_meses(mes: date, n: int) -> date:
    """Corre `n` meses el primer dia de un mes."""
    total = mes.month - 1 + n
    return date(mes.year + total // 12, total % 12 + 1, 1)


def meses_completos_en_rango(desde: date, hasta: date) -> list[date]:
    """Primer dia de cada mes calendario INTEGRAMENTE contenido en [desde, hasta].

    El coeficiente de variacion se calcula solo sobre meses completos. Un mes
    partido (la ventana arranca un 28 y termina un 30) baja artificialmente el
    volumen de ese mes e infla el CV, que es justamente lo que clasifica al SKU
    como erratico. Preferimos perder dos meses de borde antes que mentir la clase.
    """
    if desde > hasta:
        return []
    primero = date(desde.year, desde.month, 1)
    if desde.day != 1:
        primero = _sumar_meses(primero, 1)
    meses: list[date] = []
    actual = primero
    while True:
        fin = _sumar_meses(actual, 1) - timedelta(days=1)
        if fin > hasta:
            break
        meses.append(actual)
        actual = _sumar_meses(actual, 1)
    return meses


def ventanas_interanuales(hasta: date, ini_actual: date) -> tuple[date, date, int]:
    """Ventana previa con EXACTAMENTE la misma cantidad de dias que la actual.

    La ventana actual es [ini_actual, hasta] y es inclusiva de las dos puntas.
    Restarle 12 meses a la fecha de corte no alcanza: con las fechas ancladas al
    dia 28 la actual daba 368 dias y la previa 365, y el crecimiento del total
    salia ~1 punto porcentual mas alto solo por los tres dias de mas. La previa
    se define entonces hacia atras desde ini_actual: [ini_actual - n, ini_actual - 1].

    Devuelve (inicio_previo, fin_previo, dias_de_cada_ventana).
    """
    dias = (hasta - ini_actual).days + 1
    fin_previo = ini_actual - timedelta(days=1)
    ini_previo = ini_actual - timedelta(days=dias)
    return ini_previo, fin_previo, dias


def agregar_total_general(
    df: pd.DataFrame,
    col_etiqueta: str,
    cols_suma: Sequence[str] = (),
    extras: dict | None = None,
) -> pd.DataFrame:
    """Agrega la fila TOTAL GENERAL al pie de una tabla.

    Toda tabla de ranking o con medidas la lleva: sin ella el lector arma el
    total a mano y se equivoca. Las columnas que no se pueden sumar (lift,
    penetracion, medianas) quedan vacias salvo que se pase un valor en `extras`,
    donde el llamador calcula la version correcta del agregado.
    """
    if df.empty:
        return df
    fila: dict = {col: np.nan for col in df.columns}
    fila[col_etiqueta] = ETIQUETA_TOTAL
    for col in cols_suma:
        if col in df.columns:
            fila[col] = pd.to_numeric(df[col], errors="coerce").sum()
    for col, valor in (extras or {}).items():
        fila[col] = valor
    salida = pd.concat([df, pd.DataFrame([fila], columns=df.columns)], ignore_index=True)
    # concat con una fila de NaN degrada los enteros nullable a float y el lector
    # termina viendo "22809.0" donde hay un codigo de articulo.
    for col, dtype in df.dtypes.items():
        if col != col_etiqueta and str(dtype) == "Int64":
            try:
                salida[col] = pd.to_numeric(salida[col], errors="coerce").astype("Int64")
            except (TypeError, ValueError):
                pass
    return salida


# ---------------------------------------------------------------------------
# ABC / XYZ
# ---------------------------------------------------------------------------


def clasificar_abc(neto: pd.Series, cortes: tuple[float, float] = constants.ABC_CORTES) -> pd.DataFrame:
    """Clasifica cada SKU en A/B/C por participacion acumulada del neto.

    A = SKUs que acumulan hasta el 80% del neto, B = hasta el 95%, C = el resto.
    El corte es inclusivo: el SKU que llega justo al 80% queda en A. Devuelve la
    participacion individual y la acumulada porque la tabla las muestra al lado
    de la clase para que el lector pueda auditar el corte.
    """
    valores = pd.to_numeric(neto, errors="coerce").fillna(0.0)
    if valores.empty:
        return pd.DataFrame(
            {"participacion": [], "participacion_acum": [], "clase_abc": []},
            index=valores.index,
        )
    total = float(valores.sum())
    if total <= 0:
        return pd.DataFrame(
            {
                "participacion": 0.0,
                "participacion_acum": np.nan,
                "clase_abc": "C",
            },
            index=valores.index,
        )
    orden = valores.sort_values(ascending=False, kind="mergesort")
    participacion = orden / total
    acumulada = participacion.cumsum()
    corte_a, corte_b = cortes
    # Tolerancia contra el error de punto flotante: 0,80 + 0,15 da 0,9500000000000001
    # y sin ella el SKU que cae JUSTO en el corte del 95% se va a clase C.
    tol = 1e-9
    clase = np.where(
        acumulada <= corte_a + tol, "A", np.where(acumulada <= corte_b + tol, "B", "C")
    )
    salida = pd.DataFrame(
        {
            "participacion": participacion,
            "participacion_acum": acumulada,
            "clase_abc": clase,
        },
        index=orden.index,
    )
    return salida.reindex(valores.index)


def calcular_cv_por_sku(matriz: pd.DataFrame) -> pd.DataFrame:
    """Coeficiente de variacion de la demanda mensual en bultos, por SKU.

    `matriz` es SKU x mes con NaN donde no hubo venta. La ventana de calculo
    arranca en el PRIMER mes con venta de cada SKU y de ahi en adelante los NaN
    valen cero. Si se rellenara desde el principio, un SKU lanzado en el mes 18
    cargaria 17 ceros falsos y saldria clasificado como erratico cuando en
    realidad es nuevo.

    Un SKU con ventana de un solo mes -o de ninguno, si solo vendio en los meses
    de borde partidos- no tiene CV definido: se marca `N/D` y NUNCA se descarta,
    porque son novedades y hay que verlas.
    """
    columnas = list(matriz.columns)
    filas = []
    for sku, serie in matriz.iterrows():
        presentes = np.flatnonzero(serie.notna().to_numpy())
        if presentes.size == 0:
            filas.append((sku, 0, 0, float("nan")))
            continue
        ventana = np.nan_to_num(serie.to_numpy(dtype=float)[presentes[0] :], nan=0.0)
        meses_ventana = int(ventana.size)
        meses_con_venta = int((ventana > 0).sum())
        cv = stats.coefficient_of_variation(ventana) if meses_ventana >= 2 else float("nan")
        filas.append((sku, meses_ventana, meses_con_venta, cv))
    return pd.DataFrame(
        filas, columns=["id_articulo", "meses_ventana_cv", "meses_con_venta", "cv"]
    ).set_index("id_articulo").reindex(matriz.index)


def clasificar_xyz(cv: pd.Series, cortes: tuple[float, float] = constants.XYZ_CORTES) -> pd.Series:
    """Traduce el CV a clase X/Y/Z, con una clase N/D explicita.

    X = CV < 0.50 (demanda estable, se planifica con un promedio movil),
    Y = 0.50 a 1.00 (variable), Z = mayor a 1.00 (erratica).
    N/D = el SKU no tiene al menos dos meses calendario COMPLETOS de historia
    (vendio en un solo mes completo, o solo en los meses de borde partidos): el
    CV no existe. Se muestra igual: son lanzamientos y discontinuados, y
    esconderlos borra el ciclo de vida.
    """
    corte_x, corte_y = cortes

    def _clase(valor) -> str:
        if valor is None or not np.isfinite(valor):
            return "N/D"
        if valor < corte_x:
            return "X"
        if valor < corte_y:
            return "Y"
        return "Z"

    return cv.map(_clase)


def etiquetar_celda(clase_abc: pd.Series, clase_xyz: pd.Series) -> pd.Series:
    """Nombre de la celda de la matriz: 'AX', 'CZ', y 'C N/D' cuando el CV no existe.

    El espacio separador en la clase N/D evita el ilegible 'CN/D'.
    """
    abc = clase_abc.astype(str)
    xyz = clase_xyz.astype(str)
    return pd.Series(
        np.where(xyz == "N/D", abc + " N/D", abc + xyz), index=abc.index, dtype="object"
    )


def construir_abc_xyz(
    ventas_sku_mes: pd.DataFrame,
    articulos: pd.DataFrame,
    meses_cv: Sequence[date],
) -> pd.DataFrame:
    """Arma la tabla SKU x (ABC, XYZ) lista para el workbook.

    `ventas_sku_mes` viene con columnas id_articulo, mes, ventana_actual, bultos,
    neto. El ABC se calcula sobre el neto de la ventana actual (12 meses) y el
    XYZ sobre los bultos mensuales de los meses completos de la ventana larga.
    """
    if ventas_sku_mes.empty:
        return pd.DataFrame()

    datos = ventas_sku_mes.copy()
    datos["mes"] = pd.to_datetime(datos["mes"])

    actual = datos[datos["ventana_actual"].astype(bool)]
    resumen = (
        actual.groupby("id_articulo")
        .agg(
            neto_12m=("neto", "sum"),
            bultos_12m=("bultos", "sum"),
            # Meses con movimiento DENTRO de la ventana de 12 meses, incluidos los
            # dos meses de borde partidos. Es el numero que el lector espera al
            # lado del neto de 12 meses; el conteo de la ventana del CV es otro y
            # va en su propia columna, porque descarta los bordes.
            meses_con_venta_12m=("mes", "nunique"),
        )
    )
    # Un SKU que solo vendio en la ventana previa no forma parte del ABC actual
    # pero sigue existiendo para el ciclo de vida; aca se lo deja fuera.
    resumen = resumen[resumen["neto_12m"].notna()]

    meses_validos = pd.to_datetime(pd.Series(list(meses_cv), dtype="object"))
    largo = datos[datos["mes"].isin(meses_validos)]
    matriz = largo.pivot_table(
        index="id_articulo", columns="mes", values="bultos", aggfunc="sum"
    )
    matriz = matriz.reindex(columns=sorted(matriz.columns))
    matriz = matriz.reindex(resumen.index)
    variabilidad = calcular_cv_por_sku(matriz)

    tabla = resumen.join(variabilidad)
    tabla = tabla.join(clasificar_abc(tabla["neto_12m"]))
    tabla["clase_xyz"] = clasificar_xyz(tabla["cv"])
    tabla["celda"] = etiquetar_celda(tabla["clase_abc"], tabla["clase_xyz"])

    dim = articulos.set_index("id_articulo")
    tabla = tabla.join(dim[["des_articulo", "generico", "marca"]])
    tabla = tabla.sort_values("neto_12m", ascending=False).reset_index()

    return pd.DataFrame(
        {
            "ID Articulo": tabla["id_articulo"].astype("Int64"),
            "Articulo": tabla["des_articulo"],
            "Generico": tabla["generico"],
            "Marca": tabla["marca"],
            "Neto 12m ($)": tabla["neto_12m"],
            "% Neto": tabla["participacion"],
            "% Neto Acumulado": tabla["participacion_acum"],
            "Clase ABC": tabla["clase_abc"],
            "Bultos 12m": tabla["bultos_12m"],
            "Meses con Venta (12m)": tabla["meses_con_venta_12m"].astype("Int64"),
            # OJO: estas dos columnas miden la ventana LARGA de meses completos, no
            # los 12 meses. Un SKU lanzado en el mes de borde tiene venta en 12m y
            # CERO meses completos: sin el sufijo el lector lee un error de datos.
            "Meses con Venta (meses completos)": tabla["meses_con_venta"].astype("Int64"),
            "Meses Ventana CV": tabla["meses_ventana_cv"].astype("Int64"),
            "CV Demanda Mensual": tabla["cv"],
            "Clase XYZ": tabla["clase_xyz"],
            "Celda": tabla["celda"],
        }
    )


def resumir_9box(abc_xyz: pd.DataFrame) -> pd.DataFrame:
    """Resumen de la matriz de 9 casilleros (mas la columna N/D del CV indefinido).

    Se ordena A->C y X->Z->N/D para que la lectura arranque arriba a la izquierda,
    que es donde esta el dinero.
    """
    if abc_xyz.empty:
        return pd.DataFrame()
    orden_abc = {"A": 0, "B": 1, "C": 2}
    orden_xyz = {"X": 0, "Y": 1, "Z": 2, "N/D": 3}
    resumen = (
        abc_xyz.groupby(["Clase ABC", "Clase XYZ"], dropna=False)
        .agg(skus=("ID Articulo", "count"), neto=("Neto 12m ($)", "sum"))
        .reset_index()
    )
    total_skus = float(resumen["skus"].sum())
    total_neto = float(resumen["neto"].sum())
    resumen["_a"] = resumen["Clase ABC"].map(orden_abc).fillna(9)
    resumen["_x"] = resumen["Clase XYZ"].map(orden_xyz).fillna(9)
    resumen = resumen.sort_values(["_a", "_x"]).drop(columns=["_a", "_x"])
    return pd.DataFrame(
        {
            "Celda": etiquetar_celda(resumen["Clase ABC"], resumen["Clase XYZ"]),
            "Clase ABC": resumen["Clase ABC"],
            "Clase XYZ": resumen["Clase XYZ"],
            "SKUs": resumen["skus"].astype("Int64"),
            "% SKUs": resumen["skus"] / total_skus if total_skus else np.nan,
            "Neto 12m ($)": resumen["neto"],
            "% Neto": resumen["neto"] / total_neto if total_neto else np.nan,
        }
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Contingencia subcanal x generico
# ---------------------------------------------------------------------------


def agrupar_colas(
    df: pd.DataFrame, columna: str, valor: str, umbral: float, etiqueta: str
) -> pd.DataFrame:
    """Colapsa en una sola categoria a las que aportan menos de `umbral` del total.

    La chi-cuadrado exige frecuencias esperadas razonables; con subcanales de 200
    bultos los residuos dejan de ser aproximadamente normales y aparecen falsas
    anomalias gigantes. Agrupar conserva el total, que es lo que no se puede perder.
    """
    if df.empty:
        return df
    total = float(pd.to_numeric(df[valor], errors="coerce").sum())
    if total <= 0:
        return df
    peso = df.groupby(columna)[valor].sum() / total
    chicas = set(peso[peso < umbral].index)
    if not chicas:
        return df
    salida = df.copy()
    salida[columna] = salida[columna].where(~salida[columna].isin(chicas), etiqueta)
    return salida


def construir_contingencia(canal_generico: pd.DataFrame) -> pd.DataFrame:
    """Tabla de contingencia subcanal x generico en BULTOS.

    Va en bultos y no en pesos por dos motivos: el mix de precios entre genericos
    distorsionaria el test, y los bultos son la unidad que el equipo comercial usa.
    """
    if canal_generico.empty:
        return pd.DataFrame()
    tabla = canal_generico.pivot_table(
        index="subcanal", columns="generico", values="bultos", aggfunc="sum", fill_value=0.0
    )
    # Un bulto negativo neto (devoluciones) rompe la chi-cuadrado; se lleva a cero
    # y se informa, porque no es una frecuencia valida.
    tabla = tabla.clip(lower=0.0)
    tabla = tabla.loc[tabla.sum(axis=1) > 0, tabla.sum(axis=0) > 0]
    return tabla.sort_index().rename_axis(index="subcanal", columns=None)


def formatear_contingencia(tabla: pd.DataFrame) -> pd.DataFrame:
    """Contingencia con columna TOTAL y fila TOTAL GENERAL."""
    if tabla.empty:
        return pd.DataFrame()
    salida = tabla.copy()
    salida["TOTAL"] = salida.sum(axis=1)
    salida = salida.reset_index().rename(columns={"subcanal": "Subcanal"})
    return agregar_total_general(salida, "Subcanal", cols_suma=list(salida.columns[1:]))


def formatear_residuos(residuos: pd.DataFrame) -> pd.DataFrame:
    """Residuos de Pearson, con una fila total que SI es aditiva.

    Los residuos no se suman: promediarlos o sumarlos no significa nada. Lo que
    si es aditivo es el cuadrado del residuo, que es exactamente la contribucion
    de cada generico al estadistico chi-cuadrado. Esa es la fila TOTAL GENERAL:
    dice que columna explica el desvio del surtido.
    """
    if residuos.empty:
        return pd.DataFrame()
    contribucion = (residuos**2).sum(axis=0)
    salida = (
        residuos.rename_axis(index="subcanal", columns=None)
        .reset_index()
        .rename(columns={"subcanal": "Subcanal"})
    )
    fila = {col: np.nan for col in salida.columns}
    fila["Subcanal"] = f"{ETIQUETA_TOTAL} (chi2 aportado por generico)"
    for col in residuos.columns:
        fila[col] = float(contribucion[col])
    return pd.concat([salida, pd.DataFrame([fila], columns=salida.columns)], ignore_index=True)


# ---------------------------------------------------------------------------
# Interanual por subcanal
# ---------------------------------------------------------------------------


def construir_canal_yoy(canal_periodo: pd.DataFrame) -> pd.DataFrame:
    """Bultos y clientes de cada subcanal, ultimos 12m contra los 12m previos.

    Solo se compara VOLUMEN entre periodos. Los pesos de dos anios distintos no
    son comparables en Argentina: el total de la compania crece +44% nominal y
    +10.7% real, asi que un ranking en pesos ordenaria por inflacion.

    La columna clave es Bultos/Cliente: un subcanal que crece en volumen pero
    pierde clientes esta profundizando y perdiendo ancho a la vez, y eso no se ve
    mirando solo el crecimiento.
    """
    if canal_periodo.empty:
        return pd.DataFrame()
    pivot = canal_periodo.pivot_table(
        index="subcanal", columns="periodo", values=["bultos", "clientes", "neto"], aggfunc="sum"
    )
    for medida in ("bultos", "clientes", "neto"):
        for periodo in ("actual", "previo"):
            if (medida, periodo) not in pivot.columns:
                pivot[(medida, periodo)] = 0.0
    pivot = pivot.fillna(0.0)

    bultos_act = pivot[("bultos", "actual")]
    bultos_pre = pivot[("bultos", "previo")]
    cli_act = pivot[("clientes", "actual")]
    cli_pre = pivot[("clientes", "previo")]

    tabla = pd.DataFrame(
        {
            "Subcanal": pivot.index,
            "Bultos 12m Actual": bultos_act.to_numpy(),
            "Bultos 12m Previo": bultos_pre.to_numpy(),
            "Delta Bultos": (bultos_act - bultos_pre).to_numpy(),
            "Delta % Bultos": _division(bultos_act - bultos_pre, bultos_pre).to_numpy(),
            "Clientes 12m Actual": pd.array(cli_act.to_numpy(), dtype="Int64"),
            "Clientes 12m Previo": pd.array(cli_pre.to_numpy(), dtype="Int64"),
            "Delta Clientes": pd.array((cli_act - cli_pre).to_numpy(), dtype="Int64"),
            "Delta % Clientes": _division(cli_act - cli_pre, cli_pre).to_numpy(),
            "Bultos/Cliente Actual": _division(bultos_act, cli_act).to_numpy(),
            "Bultos/Cliente Previo": _division(bultos_pre, cli_pre).to_numpy(),
            "Neto 12m Actual ($ nominal)": pivot[("neto", "actual")].to_numpy(),
        }
    )
    tabla["Delta % Bultos/Cliente"] = _division(
        tabla["Bultos/Cliente Actual"] - tabla["Bultos/Cliente Previo"],
        tabla["Bultos/Cliente Previo"],
    )
    return tabla.sort_values("Delta Bultos", ascending=False).reset_index(drop=True)


def _division(numerador, denominador):
    """Division elemento a elemento que devuelve NaN en vez de romper con cero."""
    num = pd.Series(numerador, dtype="float64").reset_index(drop=True)
    den = pd.Series(denominador, dtype="float64").reset_index(drop=True)
    return num.divide(den.where(den != 0))


# ---------------------------------------------------------------------------
# Cross-sell / espacio en blanco
# ---------------------------------------------------------------------------


def calcular_penetracion(
    cliente_generico: pd.DataFrame,
    min_compradores: int = MIN_COMPRADORES_CELDA,
    min_clientes: int = MIN_CLIENTES_SUBCANAL,
) -> pd.DataFrame:
    """Penetracion de cada generico dentro de cada subcanal, y su tamanio en pesos.

    `cliente_generico` es (id_cliente, subcanal, generico, neto, bultos) de los
    ultimos 6 meses. Se arma el producto cartesiano subcanal x generico para que
    las celdas con CERO compradores aparezcan: justamente ahi esta el espacio en
    blanco, y un groupby las borraria.

    La mediana de los compradores (no el promedio) es la referencia de conversion
    porque la distribucion de gasto esta dominada por unos pocos mayoristas.
    """
    columnas = [
        "subcanal",
        "generico",
        "clientes_activos",
        "compradores",
        "no_compradores",
        "penetracion",
        "neto_mediano",
        "neto_total",
        "oportunidad",
    ]
    if cliente_generico.empty:
        return pd.DataFrame(columns=columnas)

    base = cliente_generico.groupby("subcanal")["id_cliente"].nunique().rename("clientes_activos")
    base = base[base >= min_clientes]
    if base.empty:
        return pd.DataFrame(columns=columnas)

    celdas = cliente_generico.groupby(["subcanal", "generico"]).agg(
        compradores=("id_cliente", "nunique"),
        neto_mediano=("neto", "median"),
        neto_total=("neto", "sum"),
    )
    genericos = sorted(cliente_generico["generico"].dropna().unique())
    indice = pd.MultiIndex.from_product(
        [list(base.index), genericos], names=["subcanal", "generico"]
    )
    salida = celdas.reindex(indice)
    salida["compradores"] = salida["compradores"].fillna(0).astype("int64")
    salida["neto_total"] = salida["neto_total"].fillna(0.0)
    salida = salida.join(base, on="subcanal")
    salida["no_compradores"] = salida["clientes_activos"] - salida["compradores"]
    salida["penetracion"] = salida["compradores"] / salida["clientes_activos"]
    # Sin un piso de compradores la "mediana de pares" es el gasto de dos clientes
    # y dimensionar con eso es inventar.
    salida.loc[salida["compradores"] < min_compradores, "neto_mediano"] = np.nan
    salida["oportunidad"] = salida["no_compradores"] * salida["neto_mediano"]
    return salida.reset_index()[columnas]


def formatear_cross_sell(penetracion: pd.DataFrame) -> pd.DataFrame:
    """Ordena el espacio en blanco por ARS-POR-CONVERSION, no por ARS totales.

    35 clientes mayoristas a $2,03M cada uno valen mas para un equipo comercial
    que 5.010 almacenes a $105k: son una lista de cuentas que un supervisor
    trabaja en una semana contra un programa de rutas de un semestre.
    """
    if penetracion.empty:
        return pd.DataFrame()
    # Una celda sin no compradores no es espacio en blanco: esta saturada. Y una
    # celda cuya mediana de pares es cero no se puede dimensionar en pesos.
    datos = penetracion[
        penetracion["oportunidad"].notna()
        & (penetracion["no_compradores"] > 0)
        & (penetracion["oportunidad"] > 0)
    ].copy()
    if datos.empty:
        return pd.DataFrame()
    datos = datos.sort_values("neto_mediano", ascending=False).reset_index(drop=True)
    tabla = pd.DataFrame(
        {
            "Subcanal": datos["subcanal"],
            "Generico": datos["generico"],
            "Clientes Activos 6m": datos["clientes_activos"].astype("Int64"),
            "Compradores": datos["compradores"].astype("Int64"),
            "No Compradores": datos["no_compradores"].astype("Int64"),
            "Penetracion": datos["penetracion"],
            "Neto Mediano por Comprador 6m ($) = ARS por Conversion": datos["neto_mediano"],
            "Oportunidad Techo ($)": datos["oportunidad"],
        }
    )
    tabla["Rank por ARS/Conversion"] = np.arange(1, len(tabla) + 1)
    tabla["Rank por Oportunidad Total"] = (
        tabla["Oportunidad Techo ($)"].rank(ascending=False, method="min")
    )
    return tabla


def detectar_brechas_cliente(
    cliente_generico: pd.DataFrame,
    penetracion: pd.DataFrame,
    umbral: float = UMBRAL_PENETRACION_BRECHA,
) -> pd.DataFrame:
    """Por cliente, los genericos que NO compra y que sus pares del subcanal si.

    Solo se consideran celdas con penetracion por encima del umbral: si apenas el
    8% del subcanal compra ese generico, el que no lo compra no tiene una brecha,
    tiene un surtido normal para su canal.
    """
    columnas = ["id_cliente", "subcanal", "generico", "penetracion", "valor_estimado"]
    if cliente_generico.empty or penetracion.empty:
        return pd.DataFrame(columns=columnas)

    celdas = penetracion[
        (penetracion["penetracion"] >= umbral) & penetracion["neto_mediano"].notna()
    ][["subcanal", "generico", "penetracion", "neto_mediano"]]
    if celdas.empty:
        return pd.DataFrame(columns=columnas)

    clientes = cliente_generico[["id_cliente", "subcanal"]].drop_duplicates()
    candidatos = clientes.merge(celdas, on="subcanal", how="inner")

    compras = cliente_generico[["id_cliente", "generico"]].drop_duplicates()
    compras["_compra"] = True
    brechas = candidatos.merge(compras, on=["id_cliente", "generico"], how="left")
    brechas = brechas[brechas["_compra"].isna()].drop(columns="_compra")
    brechas = brechas.rename(columns={"neto_mediano": "valor_estimado"})
    return brechas[columnas].sort_values("valor_estimado", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Reglas de asociacion
# ---------------------------------------------------------------------------


def etiqueta_fuerza_ventas(fuerza) -> str:
    """Nombre legible de la fuerza de ventas, tolerante a un id nulo o no numerico.

    El SQL hace COALESCE(id_fuerza_ventas, -1), pero si un dia dim_vendedor deja
    de garantizarlo un unico NaN hacia caer el modulo ENTERO (int(nan) levanta
    ValueError) y el informe perdia las once tablas por una fila degenerada.
    """
    try:
        if fuerza is None or (isinstance(fuerza, float) and not np.isfinite(fuerza)):
            raise ValueError
        codigo = int(fuerza)
    except (TypeError, ValueError):
        return ETIQUETAS_FUERZA_VENTAS[-1]
    return ETIQUETAS_FUERZA_VENTAS.get(codigo, f"FV{codigo}")


def construir_reglas(
    baskets: pd.DataFrame,
    col_item: str,
    nivel: str,
    col_basket: str = "factura",
    col_fv: str = "id_fuerza_ventas",
    min_facturas: int = MIN_FACTURAS_FV,
) -> pd.DataFrame:
    """Reglas de asociacion calculadas DENTRO de cada fuerza de ventas.

    Ninguna factura mezcla fuerzas de ventas (verificado sobre 369.049 de
    369.049). Calcular las reglas sobre el pool completo produce anti-afinidades
    inventadas: FRATELLI B contra CERVEZAS da lift 0,28 no porque el cliente
    elija una u otra sino porque el 45% de las facturas de fernet son autoventa
    y la autoventa no lleva cerveza. Esa "regla" describe el diseno de rutas.
    """
    if baskets.empty:
        return pd.DataFrame()
    salida = []
    for fuerza, grupo in baskets.groupby(col_fv, dropna=False):
        pares = grupo[[col_basket, col_item]].dropna()
        if pares[col_basket].nunique() < min_facturas:
            continue
        reglas = stats.association_rules(
            pares,
            col_basket,
            col_item,
            min_support=constants.BASKET_MIN_SOPORTE,
            min_lift=constants.BASKET_MIN_LIFT,
            max_items=constants.BASKET_MAX_ITEMS,
        )
        if reglas.empty:
            continue
        reglas.insert(0, "Nivel", nivel)
        reglas.insert(0, "Fuerza de Ventas", etiqueta_fuerza_ventas(fuerza))
        reglas["Facturas de la Fuerza"] = int(pares[col_basket].nunique())
        salida.append(reglas)
    if not salida:
        return pd.DataFrame()
    return pd.concat(salida, ignore_index=True)


def formatear_reglas(reglas: pd.DataFrame) -> pd.DataFrame:
    """Renombra las reglas al castellano del informe y las ordena por lift."""
    if reglas.empty:
        return pd.DataFrame()
    datos = reglas.sort_values(
        ["Fuerza de Ventas", "Nivel", "lift"], ascending=[True, True, False]
    ).reset_index(drop=True)
    return pd.DataFrame(
        {
            "Fuerza de Ventas": datos["Fuerza de Ventas"],
            "Nivel": datos["Nivel"],
            "Si compra (antecedente)": datos["antecedente"],
            "Tambien compra (consecuente)": datos["consecuente"],
            # Enteros nullable: son conteos de facturas. Sin Int64 la fila
            # TOTAL GENERAL (que agrega un NaN) los degrada a float y la hoja
            # muestra "555.0" facturas.
            "Facturas con Ambos": pd.to_numeric(datos["baskets"]).astype("Int64"),
            "Facturas de la Fuerza": pd.to_numeric(
                datos["Facturas de la Fuerza"]
            ).astype("Int64"),
            "Soporte": datos["soporte"],
            "Confianza": datos["confianza"],
            "Lift": datos["lift"],
            "Leverage": datos["leverage"],
            "Conviccion": datos["conviccion"],
        }
    )


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------


def construir_cohorte_lanzamientos(
    ciclo: pd.DataFrame, articulos: pd.DataFrame, hasta: date, meses: int = 12
) -> pd.DataFrame:
    """SKUs cuya PRIMERA venta historica cae dentro de la ventana.

    "Primera venta historica" y no "primera venta de la ventana": si se mira solo
    la ventana, cualquier SKU que estuvo sin rotar un anio y volvio aparece como
    lanzamiento.
    """
    if ciclo.empty:
        return pd.DataFrame()
    datos = ciclo.copy()
    datos["primera_venta"] = pd.to_datetime(datos["primera_venta"])
    corte = pd.Timestamp(hasta) - pd.DateOffset(months=meses)
    nuevos = datos[datos["primera_venta"] > corte].copy()
    if nuevos.empty:
        return pd.DataFrame()
    dias = (pd.Timestamp(hasta) - nuevos["primera_venta"]).dt.days + 1
    nuevos["meses_vivo"] = dias / 30.4375
    nuevos = nuevos.merge(
        articulos[["id_articulo", "des_articulo", "generico", "marca"]], on="id_articulo", how="left"
    )
    # Un cartel luminoso o un tent card no es un lanzamiento de producto.
    nuevos = nuevos[
        nuevos["generico"].notna() & ~nuevos["generico"].isin(constants.GENERICOS_NO_VENTA)
    ]
    if nuevos.empty:
        return pd.DataFrame()
    nuevos["neto_por_mes"] = nuevos["neto_historia"] / nuevos["meses_vivo"].where(
        nuevos["meses_vivo"] > 0
    )
    nuevos["bultos_por_mes"] = nuevos["bultos_historia"] / nuevos["meses_vivo"].where(
        nuevos["meses_vivo"] > 0
    )
    nuevos = nuevos.sort_values("neto_por_mes", ascending=False).reset_index(drop=True)
    return pd.DataFrame(
        {
            "ID Articulo": nuevos["id_articulo"].astype("Int64"),
            "Articulo": nuevos["des_articulo"],
            "Generico": nuevos["generico"],
            "Marca": nuevos["marca"],
            "Primera Venta": nuevos["primera_venta"].dt.date,
            "Ultima Venta": pd.to_datetime(nuevos["ultima_venta"]).dt.date,
            "Meses Vivo": nuevos["meses_vivo"],
            "Bultos desde Lanzamiento": nuevos["bultos_historia"],
            "Neto desde Lanzamiento ($)": nuevos["neto_historia"],
            "Bultos por Mes": nuevos["bultos_por_mes"],
            "Neto por Mes ($)": nuevos["neto_por_mes"],
        }
    )


def construir_rampa(
    ventas_sku_mes: pd.DataFrame, cohorte_ids: Sequence, primeras_ventas: pd.Series, ultimo_mes: date
) -> pd.DataFrame:
    """Curva de rampa: bultos POR SKU vivo en cada mes desde el lanzamiento.

    Se reporta bultos por SKU y no bultos totales porque la cohorte esta
    censurada a la derecha: un SKU lanzado hace dos meses no puede aportar al mes
    11, asi que el total caeria solo por aritmetica de la muestra. El denominador
    es la cantidad de SKUs que YA PUDIERON llegar a ese mes.
    """
    if ventas_sku_mes.empty or len(cohorte_ids) == 0:
        return pd.DataFrame()
    datos = ventas_sku_mes[ventas_sku_mes["id_articulo"].isin(list(cohorte_ids))].copy()
    if datos.empty:
        return pd.DataFrame()
    datos["mes"] = pd.to_datetime(datos["mes"])

    lanzamiento = pd.to_datetime(pd.Series(primeras_ventas)).dt.to_period("M")
    lanzamiento = lanzamiento.reindex(datos["id_articulo"].values).reset_index(drop=True)
    indice_mes = datos["mes"].dt.to_period("M").reset_index(drop=True)
    datos = datos.reset_index(drop=True)
    datos["mes_desde_lanzamiento"] = (indice_mes - lanzamiento).apply(
        lambda x: x.n if pd.notna(x) else np.nan
    )
    datos = datos[datos["mes_desde_lanzamiento"].notna()]
    datos = datos[datos["mes_desde_lanzamiento"] >= 0]
    if datos.empty:
        return pd.DataFrame()

    volumen = datos.groupby("mes_desde_lanzamiento").agg(
        bultos=("bultos", "sum"), skus_con_venta=("id_articulo", "nunique")
    )

    # Denominador correcto: SKUs cuya edad ya alcanza ese mes.
    ultimo = pd.Period(ultimo_mes, freq="M")
    edades = (ultimo - pd.to_datetime(pd.Series(primeras_ventas)).dt.to_period("M")).apply(
        lambda x: x.n if pd.notna(x) else np.nan
    )
    edades = edades[edades.index.isin(list(cohorte_ids))]
    expuestos = {
        m: int((edades >= m).sum()) for m in volumen.index.astype(int)
    }
    volumen = volumen.reset_index()
    volumen["skus_expuestos"] = volumen["mes_desde_lanzamiento"].map(expuestos)
    volumen["bultos_por_sku"] = volumen["bultos"] / volumen["skus_expuestos"].where(
        volumen["skus_expuestos"] > 0
    )
    return pd.DataFrame(
        {
            "Mes desde Lanzamiento": volumen["mes_desde_lanzamiento"].astype("Int64"),
            "SKUs Expuestos": volumen["skus_expuestos"].astype("Int64"),
            "SKUs con Venta": volumen["skus_con_venta"].astype("Int64"),
            "Bultos": volumen["bultos"],
            "Bultos por SKU Expuesto": volumen["bultos_por_sku"],
        }
    ).sort_values("Mes desde Lanzamiento").reset_index(drop=True)


def construir_stock_muerto(
    stock: pd.DataFrame,
    ciclo: pd.DataFrame,
    articulos: pd.DataFrame,
    precios: pd.DataFrame,
    hasta: date,
    dias: int = DIAS_STOCK_MUERTO,
    excluir_no_venta: bool = True,
) -> pd.DataFrame:
    """SKUs con stock y sin venta hace mas de `dias` (o que nunca vendieron).

    `excluir_no_venta=False` reproduce el numero INGENUO, el que sale si no se
    filtran los genericos que no son articulos de venta. Existe a proposito: la
    diferencia entre los dos numeros es el hallazgo. Sin filtrar, un unico item
    promocional de 2022 (RASPADITAS, generico MARKETING) aporta 176.024 bultos y
    convierte una lista de liquidacion de una tarde en una alarma de inventario.
    """
    if stock.empty:
        return pd.DataFrame()
    datos = stock.merge(
        articulos[["id_articulo", "des_articulo", "generico", "marca"]], on="id_articulo", how="left"
    )
    if excluir_no_venta:
        datos = datos[~datos["generico"].isin(constants.GENERICOS_NO_VENTA)]
        # Un articulo sin generico en dim_articulo no se puede clasificar como
        # vendible; se excluye del numero real y se cuenta aparte en las notas.
        datos = datos[datos["generico"].notna()]
    datos = datos.merge(
        ciclo[["id_articulo", "ultima_venta", "primera_venta"]], on="id_articulo", how="left"
    )
    datos["ultima_venta"] = pd.to_datetime(datos["ultima_venta"])
    datos["dias_sin_venta"] = (pd.Timestamp(hasta) - datos["ultima_venta"]).dt.days
    nunca = datos["ultima_venta"].isna()
    muerto = datos[nunca | (datos["dias_sin_venta"] > dias)].copy()
    if muerto.empty:
        return pd.DataFrame()
    muerto = muerto.merge(precios, on="id_articulo", how="left")
    muerto["valor_neto"] = muerto["stock_bultos"] * muerto["precio_neto_medio"]
    muerto["estado"] = np.where(muerto["ultima_venta"].isna(), "Nunca vendido", "Sin rotacion")
    muerto = muerto.sort_values(["valor_neto", "stock_bultos"], ascending=False).reset_index(
        drop=True
    )
    return pd.DataFrame(
        {
            "ID Articulo": muerto["id_articulo"].astype("Int64"),
            "Articulo": muerto["des_articulo"],
            "Generico": muerto["generico"],
            "Marca": muerto["marca"],
            "Estado": muerto["estado"],
            "Ultima Venta": muerto["ultima_venta"].dt.date,
            "Dias sin Venta": muerto["dias_sin_venta"],
            "Stock Bultos": muerto["stock_bultos"],
            "Depositos": muerto["depositos"],
            "Precio Neto Medio ($)": muerto["precio_neto_medio"],
            "Valor Neto Estimado ($)": muerto["valor_neto"],
        }
    )


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_SQL_SKU_MES = """
SELECT fv.id_articulo,
       date_trunc('month', fv.fecha_comprobante)::date AS mes,
       (fv.fecha_comprobante >= %(ini_actual)s) AS ventana_actual,
       sum(fv.cantidades_total) AS bultos,
       sum(fv.subtotal_neto)    AS neto
FROM gold.fact_ventas fv
JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
WHERE NOT fv.anulado
  AND fv.id_documento IN %(docs)s
  AND fv.fecha_comprobante >= %(ini_largo)s
  AND fv.fecha_comprobante <= %(hasta)s
  AND da.generico IS NOT NULL
  AND da.generico NOT IN %(no_venta)s
GROUP BY 1, 2, 3
"""

_SQL_ARTICULOS = """
SELECT id_articulo, des_articulo, generico, marca
FROM gold.dim_articulo
"""

_SQL_CANAL_GENERICO = """
SELECT COALESCE(dc.des_subcanal_mkt, 'SIN SUBCANAL') AS subcanal,
       da.generico,
       sum(fv.cantidades_total) AS bultos,
       sum(fv.subtotal_neto)    AS neto
FROM gold.fact_ventas fv
JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
JOIN gold.dim_cliente  dc ON dc.id_cliente  = fv.id_cliente
WHERE NOT fv.anulado
  AND fv.id_documento IN %(docs)s
  AND fv.fecha_comprobante >= %(ini_actual)s
  AND fv.fecha_comprobante <= %(hasta)s
  AND da.generico IS NOT NULL
  AND da.generico NOT IN %(no_venta)s
GROUP BY 1, 2
"""

# El interanual exige ventanas de IGUAL CANTIDAD DE DIAS. La ventana actual es
# [ini_actual, hasta] y es INCLUSIVA de las dos puntas, asi que la previa NO puede
# ser [ini_largo, ini_actual): con las fechas ancladas al dia 28 que devuelve
# ctx.desde() eso daba 368 dias contra 365 y el crecimiento salia inflado ~1,5
# puntos porcentuales (13,7% declarado contra 12,2% real) solo por los tres dias
# de mas. Por eso la previa se define hacia atras desde ini_actual con la misma
# cantidad exacta de dias.
_SQL_CANAL_PERIODO = """
SELECT COALESCE(dc.des_subcanal_mkt, 'SIN SUBCANAL') AS subcanal,
       CASE WHEN fv.fecha_comprobante >= %(ini_actual)s THEN 'actual' ELSE 'previo' END AS periodo,
       count(DISTINCT fv.id_cliente) AS clientes,
       sum(fv.cantidades_total)      AS bultos,
       sum(fv.subtotal_neto)         AS neto
FROM gold.fact_ventas fv
JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
JOIN gold.dim_cliente  dc ON dc.id_cliente  = fv.id_cliente
WHERE NOT fv.anulado
  AND fv.id_documento IN %(docs)s
  AND fv.fecha_comprobante >= %(ini_previo)s
  AND fv.fecha_comprobante <= %(hasta)s
  AND da.generico IS NOT NULL
  AND da.generico NOT IN %(no_venta)s
GROUP BY 1, 2
"""

_SQL_CLIENTE_GENERICO = """
SELECT fv.id_cliente,
       COALESCE(dc.des_subcanal_mkt, 'SIN SUBCANAL') AS subcanal,
       da.generico,
       sum(fv.subtotal_neto)    AS neto,
       sum(fv.cantidades_total) AS bultos
FROM gold.fact_ventas fv
JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
JOIN gold.dim_cliente  dc ON dc.id_cliente  = fv.id_cliente
WHERE NOT fv.anulado
  AND fv.id_documento IN %(docs)s
  AND fv.fecha_comprobante >= %(ini_cross)s
  AND fv.fecha_comprobante <= %(hasta)s
  AND da.generico IS NOT NULL
  AND da.generico NOT IN %(no_venta)s
GROUP BY 1, 2, 3
HAVING sum(fv.cantidades_total) > 0
"""

# La fuerza de ventas vive en dim_vendedor y la clave es COMPUESTA:
# id_vendedor se reusa entre sucursales, joinear solo por id duplica lineas.
_SQL_BASKETS = """
SELECT DISTINCT
       fv.id_sucursal::text || '|' || fv.id_documento || '|' || fv.letra || '|'
         || fv.serie::text || '|' || fv.nro_doc::text AS factura,
       COALESCE(dv.id_fuerza_ventas, -1) AS id_fuerza_ventas,
       da.generico,
       da.marca
FROM gold.fact_ventas fv
JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
LEFT JOIN gold.dim_vendedor dv
       ON dv.id_vendedor = fv.id_vendedor
      AND dv.id_sucursal = fv.id_sucursal
WHERE NOT fv.anulado
  AND fv.id_documento = %(factura)s
  AND fv.fecha_comprobante >= %(ini_cross)s
  AND fv.fecha_comprobante <= %(hasta)s
  AND da.generico IS NOT NULL
  AND da.generico NOT IN %(no_venta)s
"""

_SQL_CICLO = """
SELECT fv.id_articulo,
       min(fv.fecha_comprobante) AS primera_venta,
       max(fv.fecha_comprobante) AS ultima_venta,
       sum(fv.cantidades_total)  AS bultos_historia,
       sum(fv.subtotal_neto)     AS neto_historia
FROM gold.fact_ventas fv
WHERE NOT fv.anulado
  AND fv.id_documento IN %(docs)s
  AND fv.fecha_comprobante <= %(hasta)s
GROUP BY 1
"""

_SQL_STOCK = """
WITH ultima AS (SELECT max(date_stock) AS d FROM gold.fact_stock)
SELECT fs.id_articulo,
       sum(fs.cant_bultos) AS stock_bultos,
       count(DISTINCT CASE WHEN fs.cant_bultos > 0 THEN fs.id_deposito END) AS depositos,
       max(fs.date_stock)  AS fecha_stock
FROM gold.fact_stock fs
JOIN ultima ON fs.date_stock = ultima.d
GROUP BY 1
HAVING sum(fs.cant_bultos) > 0
"""


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------


def _fallo(motivo: str) -> AnalysisResult:
    return AnalysisResult(name=NOMBRE, failed=True, notes=[motivo])


def build(ctx: AnalysisContext) -> AnalysisResult:
    """Corre el analisis de portafolio y canales.

    Nunca levanta excepcion: si falta la data o queda degenerada devuelve
    `failed=True` con el motivo en `notes`, porque el workbook se arma igual con
    el resto de los modulos.
    """
    try:
        return _build(ctx)
    except Exception as exc:  # noqa: BLE001 - el informe no puede caerse por un modulo
        return _fallo(f"Portafolio y canales no pudo ejecutarse: {type(exc).__name__}: {exc}")


def _build(ctx: AnalysisContext) -> AnalysisResult:
    hasta = ctx.hasta
    ini_actual = ctx.desde(ctx.meses_ventana)
    ini_largo = ctx.desde(ctx.meses_historia)
    ini_cross = ctx.desde(MESES_CROSS_SELL)
    # Ventanas del interanual, con la MISMA cantidad de dias las dos. Ver el
    # comentario de _SQL_CANAL_PERIODO: la version anterior comparaba 368 contra
    # 365 dias e inflaba el crecimiento.
    _ini_previo, _fin_previo, dias_ventana = ventanas_interanuales(
        hasta, date.fromisoformat(ini_actual)
    )
    ini_previo = _ini_previo.isoformat()
    fin_previo = _fin_previo.isoformat()
    params = {
        "hasta": hasta.isoformat(),
        "ini_actual": ini_actual,
        "ini_largo": ini_largo,
        "ini_previo": ini_previo,
        "ini_cross": ini_cross,
        "docs": DOCUMENTOS_VENTA,
        "factura": constants.DOC_FACTURA,
        "no_venta": tuple(constants.GENERICOS_NO_VENTA),
    }

    ventas_sku_mes = ctx.sql(_SQL_SKU_MES, params)
    if ventas_sku_mes.empty:
        return _fallo(
            f"No hay ventas entre {ini_largo} y {hasta.isoformat()} una vez excluidos "
            "los genericos que no son articulos de venta."
        )
    articulos = ctx.sql(_SQL_ARTICULOS)

    tablas: dict[str, pd.DataFrame] = {}
    notas: list[str] = []
    alertas: list[Alert] = []
    headlines: list[Headline] = []

    notas.append(
        "Todos los importes son NETOS (subtotal_neto = facturacion_neta - descuentos). "
        "facturacion_neta es BRUTO a precio de lista y sobrestima el ingreso en ~10,1%; "
        "subtotal_final incluye impuestos. La columna 'bonificacion' es una TASA "
        "porcentual y no se suma en ningun lado."
    )
    notas.append(
        f"Ventana actual {ini_actual} a {hasta.isoformat()} ({dias_ventana} dias); ventana "
        f"previa del interanual {ini_previo} a {fin_previo} (los mismos {dias_ventana} dias, "
        "sin solapamiento); ventana larga del CV "
        f"{ini_largo} a {hasta.isoformat()}; ventana de cross-sell {ini_cross} a "
        f"{hasta.isoformat()}."
    )
    notas.append(
        "Se excluyen los presupuestos (PRVTA): 100 lineas en la ventana pero $1.808e9 y "
        "85.104 bultos que nunca se facturaron. Se incluyen las devoluciones (DVVTA), "
        "asi que las cifras son netas de devolucion."
    )
    notas.append(
        "Se excluyen de todo volumen los genericos que no son articulos de venta: "
        + ", ".join(constants.GENERICOS_NO_VENTA)
        + "."
    )

    # ---------------- ABC / XYZ ----------------
    meses_cv = meses_completos_en_rango(date.fromisoformat(ini_largo), hasta)
    abc_xyz = construir_abc_xyz(ventas_sku_mes, articulos, meses_cv)
    if abc_xyz.empty:
        return _fallo("No quedaron SKUs con neto en los ultimos 12 meses.")

    box = resumir_9box(abc_xyz)
    neto_total = float(abc_xyz["Neto 12m ($)"].sum())
    skus_activos = int(len(abc_xyz))
    neto_a = float(abc_xyz.loc[abc_xyz["Clase ABC"] == "A", "Neto 12m ($)"].sum())
    skus_a = int((abc_xyz["Clase ABC"] == "A").sum())
    share_a = neto_a / neto_total if neto_total else float("nan")
    fila_ax = box[box["Celda"] == "AX"]
    share_ax = float(fila_ax["% Neto"].iloc[0]) if not fila_ax.empty else float("nan")
    skus_ax = int(fila_ax["SKUs"].iloc[0]) if not fila_ax.empty else 0
    fila_cz = box[box["Celda"] == "CZ"]
    skus_cz = int(fila_cz["SKUs"].iloc[0]) if not fila_cz.empty else 0
    share_cz = float(fila_cz["% Neto"].iloc[0]) if not fila_cz.empty else float("nan")
    skus_nd = int((abc_xyz["Clase XYZ"] == "N/D").sum())

    tablas["abc_xyz"] = agregar_total_general(
        abc_xyz,
        "Articulo",
        cols_suma=["Neto 12m ($)", "% Neto", "Bultos 12m"],
        extras={"ID Articulo": np.nan, "% Neto Acumulado": 1.0},
    )
    tablas["abc_xyz_box"] = agregar_total_general(
        box, "Celda", cols_suma=["SKUs", "% SKUs", "Neto 12m ($)", "% Neto"]
    )
    notas.append(
        f"ABC sobre neto de {ctx.meses_ventana} meses con cortes "
        f"{constants.ABC_CORTES[0]:.0%}/{constants.ABC_CORTES[1]:.0%} (corte inclusivo). "
        f"XYZ sobre el coeficiente de variacion de los bultos mensuales de los "
        f"{len(meses_cv)} meses calendario COMPLETOS del rango; los meses de borde "
        "quedan fuera porque un mes partido infla el CV. El CV usa desviacion "
        "poblacional (stats.coefficient_of_variation, ddof=0)."
    )
    skus_sin_mes_completo = int((abc_xyz["Meses Ventana CV"] == 0).sum())
    notas.append(
        f"{skus_nd} SKUs no llegan a dos meses calendario completos de historia, asi que su "
        f"CV es indefinido y quedan en la clase XYZ 'N/D'. De esos, {skus_sin_mes_completo} "
        "no tienen NINGUN mes completo: vendieron unicamente en los meses de borde partidos "
        f"(tipicamente el mes en curso), por eso muestran 'Meses Ventana CV' = 0 y "
        "'Meses con Venta (meses completos)' = 0 al lado de un neto de 12 meses que puede ser "
        "grande. No es un error de datos: son lanzamientos del ultimo mes. La columna "
        "'Meses con Venta (12m)' es la que hay que leer para saber si el SKU se movio."
    )

    # ---------------- Contingencia subcanal x generico ----------------
    canal_generico = ctx.sql(_SQL_CANAL_GENERICO, params)
    residuo_min = None
    if not canal_generico.empty:
        agrupado = agrupar_colas(
            canal_generico, "subcanal", "bultos", UMBRAL_COLA_CONTINGENCIA, ETIQUETA_OTROS_FILA
        )
        agrupado = agrupar_colas(
            agrupado, "generico", "bultos", UMBRAL_COLA_CONTINGENCIA, ETIQUETA_OTROS_COL
        )
        contingencia = construir_contingencia(agrupado)
        if not contingencia.empty and min(contingencia.shape) > 1:
            chi = stats.chi_square_residuals(contingencia)
            tablas["canal_generico"] = formatear_contingencia(contingencia)
            tablas["canal_generico_residuos"] = formatear_residuos(chi.residuals)
            notas.append(
                f"Contingencia subcanal x generico en BULTOS de los ultimos "
                f"{ctx.meses_ventana} meses: chi2 = {chi.statistic:,.0f}, gl = {chi.dof}, "
                f"p = {chi.p_value:.3g}, V de Cramer = {chi.cramers_v:.4f}. "
                "IMPORTANTE: la V de Cramer es CHICA. El test da significativo porque N es "
                "enorme, no porque el efecto sea grande. Los residuos sirven para detectar "
                "anomalias puntuales; NO habilitan a decir que cada subcanal tiene un "
                "surtido estructuralmente distinto. Son residuos de PEARSON, "
                "(observado - esperado) / raiz(esperado): su varianza real es menor que 1, asi "
                "que subestiman -nunca exageran- el desvio. Sirven para ORDENAR celdas, no "
                "para leerlos como un z de tabla normal."
            )
            notas.append(
                "Subcanales y genericos que aportan menos del "
                f"{UMBRAL_COLA_CONTINGENCIA:.1%} del volumen se agrupan en "
                f"'{ETIQUETA_OTROS_FILA}' / '{ETIQUETA_OTROS_COL}' para que las frecuencias "
                "esperadas soporten la chi-cuadrado. Los bultos negativos netos "
                "(devoluciones) se llevan a cero: no son una frecuencia valida."
            )
            notas.append(
                "La fila TOTAL GENERAL de los residuos NO es una suma de residuos (no son "
                "aditivos) sino la contribucion de cada generico al chi2, que si lo es."
            )
            apilado = chi.residuals.stack()
            if not apilado.empty:
                idx_min = apilado.idxmin()
                residuo_min = (idx_min[0], idx_min[1], float(apilado.min()))
                observado = float(contingencia.loc[idx_min[0], idx_min[1]])
                esperado = float(chi.expected.loc[idx_min[0], idx_min[1]])
                # No calificar el subcanal de "chico" sin medirlo: el hueco mas
                # grande suele caer en un subcanal de POCOS CLIENTES pero MUCHO
                # volumen, y llamarlo chico invita a desestimar la alerta.
                volumen_sub = float(contingencia.loc[idx_min[0]].sum())
                share_sub = volumen_sub / float(contingencia.values.sum())
                alertas.append(
                    Alert(
                        severity="critica",
                        title=f"Agujero estructural: {idx_min[0]} x {idx_min[1]}",
                        detail=(
                            f"{idx_min[0]} compra {observado:,.0f} bultos de {idx_min[1]} contra "
                            f"{esperado:,.0f} esperados por su tamanio (residuo de Pearson "
                            f"{residuo_min[2]:.1f}). Es el hueco mas grande del mix en "
                            f"{ctx.meses_ventana} meses: faltan {esperado - observado:,.0f} bultos. "
                            f"No es un subcanal marginal: mueve {volumen_sub:,.0f} bultos, "
                            f"{share_sub:.1%} del volumen total, concentrado en pocas cuentas "
                            "direccionables. Se resuelve con logistica y economia de pallet, no "
                            "con guion de preventa."
                        ),
                        amount=esperado - observado,
                    )
                )

    # ---------------- Interanual por subcanal ----------------
    canal_periodo = ctx.sql(_SQL_CANAL_PERIODO, params)
    yoy = construir_canal_yoy(canal_periodo)
    if not yoy.empty:
        bul_act = float(yoy["Bultos 12m Actual"].sum())
        bul_pre = float(yoy["Bultos 12m Previo"].sum())
        cli_act = float(yoy["Clientes 12m Actual"].sum())
        cli_pre = float(yoy["Clientes 12m Previo"].sum())
        bxc_act = bul_act / cli_act if cli_act else np.nan
        bxc_pre = bul_pre / cli_pre if cli_pre else np.nan
        tablas["canal_yoy"] = agregar_total_general(
            yoy,
            "Subcanal",
            cols_suma=[
                "Bultos 12m Actual",
                "Bultos 12m Previo",
                "Delta Bultos",
                "Clientes 12m Actual",
                "Clientes 12m Previo",
                "Delta Clientes",
                "Neto 12m Actual ($ nominal)",
            ],
            extras={
                "Delta % Bultos": (bul_act - bul_pre) / bul_pre if bul_pre else np.nan,
                "Delta % Clientes": (cli_act - cli_pre) / cli_pre if cli_pre else np.nan,
                "Bultos/Cliente Actual": bxc_act,
                "Bultos/Cliente Previo": bxc_pre,
                "Delta % Bultos/Cliente": (bxc_act - bxc_pre) / bxc_pre if bxc_pre else np.nan,
            },
        )
        notas.append(
            f"Las dos ventanas del interanual miden exactamente {dias_ventana} dias cada una "
            f"({ini_actual} a {hasta.isoformat()} contra {ini_previo} a {fin_previo}). No "
            "alcanza con correr 12 meses: las fechas ancladas al dia 28 daban 368 dias contra "
            "365 e inflaban el crecimiento del total ~1,5 puntos porcentuales solo por los "
            "tres dias de mas."
        )
        notas.append(
            "El interanual por subcanal se compara SOLO en bultos. Los pesos de dos anios "
            "distintos no son comparables en Argentina (+45% nominal equivale a ~+10,7% "
            "real): un ranking en pesos ordena por inflacion. La columna de neto esta como "
            "referencia de tamanio y esta etiquetada como nominal. Los clientes SI se pueden "
            "sumar en la fila TOTAL porque dim_cliente asigna exactamente un subcanal por "
            "cliente, pero el subcanal es el vigente HOY: un cliente reclasificado arrastra "
            "su historia al subcanal nuevo."
        )
        # Erosion de ancho: crece en volumen pero pierde clientes.
        erosion = yoy[
            (yoy["Delta Bultos"] > 0)
            & (yoy["Delta Clientes"] < 0)
            & (yoy["Bultos 12m Previo"] > 0)
        ].sort_values("Delta Bultos", ascending=False)
        if not erosion.empty:
            fila = erosion.iloc[0]
            alertas.append(
                Alert(
                    severity="alta",
                    title=f"{fila['Subcanal']} gana volumen y pierde ancho",
                    detail=(
                        f"{fila['Subcanal']} crecio {fila['Delta % Bultos']:+.1%} en bultos "
                        f"({fila['Delta Bultos']:+,.0f}) pero perdio "
                        f"{abs(fila['Delta Clientes']):,.0f} clientes "
                        f"({fila['Delta % Clientes']:+.1%}). Los bultos por cliente pasaron de "
                        f"{fila['Bultos/Cliente Previo']:,.1f} a "
                        f"{fila['Bultos/Cliente Actual']:,.1f} "
                        f"({fila['Delta % Bultos/Cliente']:+.1%}): la profundidad tapa la caida "
                        "de cobertura. Es lo contrario de lo que asume una organizacion que se "
                        "mide por cobertura."
                    ),
                    amount=float(fila["Delta Bultos"]),
                )
            )

    # ---------------- Cross-sell ----------------
    cliente_generico = ctx.sql(_SQL_CLIENTE_GENERICO, params)
    mostrador = 0
    top_oportunidad = None
    if not cliente_generico.empty:
        mostrador = int(
            cliente_generico.loc[
                cliente_generico["id_cliente"].isin(constants.CLIENTES_MOSTRADOR), "id_cliente"
            ].nunique()
        )
        base_cross = cliente_generico[
            ~cliente_generico["id_cliente"].isin(constants.CLIENTES_MOSTRADOR)
        ]
        penetracion = calcular_penetracion(base_cross)
        cross = formatear_cross_sell(penetracion)
        if not cross.empty:
            tablas["cross_sell"] = agregar_total_general(
                cross,
                "Subcanal",
                cols_suma=["No Compradores", "Oportunidad Techo ($)"],
                extras={"Generico": f"{len(cross):,} celdas con espacio en blanco"},
            )
            notas.append(
                "En la fila TOTAL de cross_sell, 'No Compradores' suma pares "
                "(cliente, generico) y NO clientes distintos: un mismo cliente aparece una "
                "vez por cada generico que no compra."
            )
            top_oportunidad = cross.sort_values(
                "Oportunidad Techo ($)", ascending=False
            ).iloc[0]

            # La penetracion de referencia se calcula SIN los clientes mostrador
            # (uno solo factura ~9.479 veces al anio y torceria toda la
            # penetracion), pero el detalle por cliente si los incluye MARCADOS.
            # La regla es marcar, no borrar en silencio: si se los saca de las
            # dos puntas la columna 'Es Mostrador' dice siempre NO y miente.
            brechas = detectar_brechas_cliente(cliente_generico, penetracion)
            if not brechas.empty:
                detalle = brechas.copy()
                es_mostrador = detalle["id_cliente"].isin(constants.CLIENTES_MOSTRADOR)
                detalle["Es Mostrador"] = np.where(es_mostrador, "SI", "NO")
                total_brechas = float(brechas["valor_estimado"].sum())
                brechas_mostrador = int(es_mostrador.sum())
                valor_mostrador = float(detalle.loc[es_mostrador, "valor_estimado"].sum())
                mostradas = detalle.head(MAX_FILAS_BRECHAS)
                tabla_brechas = pd.DataFrame(
                    {
                        "ID Cliente": mostradas["id_cliente"].astype("Int64"),
                        "Subcanal": mostradas["subcanal"],
                        "Generico sin Comprar": mostradas["generico"],
                        "Penetracion de sus Pares": mostradas["penetracion"],
                        "Valor Estimado 6m ($ techo)": mostradas["valor_estimado"],
                        "Es Mostrador": mostradas["Es Mostrador"],
                    }
                )
                tablas["cross_sell_clientes"] = agregar_total_general(
                    tabla_brechas,
                    "Subcanal",
                    extras={
                        "Generico sin Comprar": f"{len(brechas):,} brechas (universo completo)",
                        "Valor Estimado 6m ($ techo)": total_brechas,
                    },
                )
                notas.append(
                    f"Detalle por cliente: {len(brechas):,} brechas por "
                    f"${total_brechas:,.0f} en {MESES_CROSS_SELL} meses. La hoja muestra las "
                    f"{MAX_FILAS_BRECHAS} de mayor valor; la fila TOTAL GENERAL informa el "
                    f"universo completo. De ese universo, {brechas_mostrador:,} brechas por "
                    f"${valor_mostrador:,.0f} corresponden a clientes mostrador (columna "
                    "'Es Mostrador' = SI): estan marcadas y NO se trabajan como cuentas, pero "
                    "no se borran para que el total reconcilie."
                )
        notas.append(
            "El dimensionamiento del cross-sell (no compradores x mediana de sus pares) es un "
            "TECHO, no un pronostico. Asume que todo no comprador convierte a la mediana y no "
            "aplica ninguna restriccion de surtido, lista de precios, cobertura de ruta ni "
            "abastecimiento. En particular, un generico que se entrega por autoventa puede ser "
            "fisicamente inalcanzable para un cliente que solo tiene ruta de preventa."
        )
        notas.append(
            f"Ranking del cross-sell por ARS-POR-CONVERSION y no por ARS totales: pocos "
            "clientes de alto ticket son una lista de cuentas trabajable, mientras que miles "
            "de conversiones chicas son un programa de un semestre."
        )
        notas.append(
            f"Se detectaron {mostrador} clientes mostrador (constants.CLIENTES_MOSTRADOR): son "
            "cajas de venta por mostrador, no cuentas. Uno solo de ellos factura ~9.479 veces "
            "al anio, asi que quedan FUERA de los denominadores de penetracion y de las "
            "medianas de pares (tabla cross_sell), pero SI aparecen en el detalle por cliente "
            "marcados en la columna 'Es Mostrador'. Se marcan, no se borran."
        )
        notas.append(
            f"Celdas (subcanal, generico) dimensionadas solo con {MIN_COMPRADORES_CELDA}+ "
            f"compradores y subcanales de {MIN_CLIENTES_SUBCANAL}+ clientes activos; las "
            "brechas por cliente exigen ademas penetracion de pares >= "
            f"{UMBRAL_PENETRACION_BRECHA:.0%}."
        )

    # ---------------- Reglas de asociacion ----------------
    baskets = ctx.sql(_SQL_BASKETS, params)
    if not baskets.empty:
        baskets["factura"] = baskets["factura"].astype("category")
        reglas_gen = construir_reglas(
            baskets[["factura", "id_fuerza_ventas", "generico"]].drop_duplicates(),
            "generico",
            "Generico",
        )
        reglas_marca = construir_reglas(
            baskets[["factura", "id_fuerza_ventas", "marca"]].dropna().drop_duplicates(),
            "marca",
            "Marca",
        )
        reglas = pd.concat(
            [r for r in (reglas_gen, reglas_marca) if not r.empty], ignore_index=True
        ) if (not reglas_gen.empty or not reglas_marca.empty) else pd.DataFrame()
        if not reglas.empty:
            formateadas = formatear_reglas(reglas)
            tablas["reglas"] = agregar_total_general(
                formateadas,
                "Fuerza de Ventas",
                extras={"Nivel": f"{len(formateadas):,} reglas"},
            )
        # Cuantas facturas llevan un solo generico: es el techo estructural del soporte.
        por_factura = baskets.groupby("factura", observed=True)["generico"].nunique()
        facturas = int(len(por_factura))
        una_sola = int((por_factura == 1).sum())
        notas.append(
            "Las reglas de asociacion se calculan DENTRO de cada fuerza de ventas. Ninguna "
            "factura mezcla fuerzas (verificado sobre 369.049 de 369.049), asi que una regla "
            "que cruza preventa y autoventa mide el diseno de rutas y no el comportamiento del "
            "cliente: por eso FRATELLI B contra CERVEZAS da lift 0,28 en el pool completo."
        )
        if facturas:
            notas.append(
                f"De {facturas:,} facturas de la ventana de cross-sell, {una_sola:,} "
                f"({una_sola / facturas:.1%}) llevan un UNICO generico. Eso limita "
                "estructuralmente el soporte de cualquier regla: la canasta es muy fina y la "
                "factura probablemente no sea la unidad de canasta correcta (un mismo cliente "
                "genera 2 o 3 facturas el mismo dia)."
            )
        conteo_reglas = (
            formatear_reglas(reglas).groupby(["Nivel", "Fuerza de Ventas"]).size()
            if not reglas.empty
            else pd.Series(dtype="int64")
        )
        notas.append(
            "Reglas que superan soporte >= "
            f"{constants.BASKET_MIN_SOPORTE:.0%} y lift >= {constants.BASKET_MIN_LIFT}: "
            + (
                "; ".join(f"{nivel} {fv}: {n}" for (nivel, fv), n in conteo_reglas.items())
                or "ninguna"
            )
            + ". A nivel GENERICO sobreviven poquisimas y ninguna en autoventa: los genericos "
            "grandes (CERVEZAS 67% de las facturas, AGUAS DANONE 38%) son practicamente "
            "independientes entre si, de modo que su lift ronda 1,0 y no pasa el filtro. Eso "
            "no es un defecto del calculo, es el resultado: el mix por factura no tiene "
            "estructura de canasta a nivel generico. La senal esta a nivel MARCA."
        )

    # ---------------- Ciclo de vida ----------------
    ciclo = ctx.sql(_SQL_CICLO, params)
    precios = (
        ventas_sku_mes.groupby("id_articulo")[["neto", "bultos"]]
        .sum()
        .assign(precio_neto_medio=lambda d: d["neto"] / d["bultos"].where(d["bultos"] > 0))
        .reset_index()[["id_articulo", "precio_neto_medio"]]
    )
    if not ciclo.empty:
        cohorte = construir_cohorte_lanzamientos(ciclo, articulos, hasta, ctx.meses_ventana)
        if not cohorte.empty:
            tablas["ciclo_vida"] = agregar_total_general(
                cohorte,
                "Articulo",
                cols_suma=[
                    "Bultos desde Lanzamiento",
                    "Neto desde Lanzamiento ($)",
                ],
                extras={"Generico": f"{len(cohorte):,} SKUs nuevos"},
            )
            primeras = ciclo.set_index("id_articulo")["primera_venta"]
            rampa = construir_rampa(
                ventas_sku_mes,
                cohorte["ID Articulo"].tolist(),
                primeras,
                date(hasta.year, hasta.month, 1),
            )
            if not rampa.empty:
                tablas["ciclo_vida_rampa"] = agregar_total_general(
                    rampa, "Mes desde Lanzamiento", cols_suma=["Bultos"]
                )
                notas.append(
                    "La rampa de lanzamientos esta censurada a la derecha: los meses altos "
                    "descansan en pocos SKUs. Por eso se reportan bultos POR SKU EXPUESTO "
                    "(SKUs que ya pudieron alcanzar ese mes de vida) y no bultos totales, que "
                    "caerian solo por aritmetica de la muestra. El mes 0 es un mes PARCIAL "
                    "(arranca el dia del lanzamiento, no el dia 1) y por eso siempre parece un "
                    "pozo: no lo es."
                )

    stock = ctx.sql(_SQL_STOCK)
    if not stock.empty and not ciclo.empty:
        muerto_real = construir_stock_muerto(
            stock, ciclo, articulos, precios, hasta, excluir_no_venta=True
        )
        muerto_naive = construir_stock_muerto(
            stock, ciclo, articulos, precios, hasta, excluir_no_venta=False
        )
        bultos_real = float(muerto_real["Stock Bultos"].sum()) if not muerto_real.empty else 0.0
        bultos_naive = float(muerto_naive["Stock Bultos"].sum()) if not muerto_naive.empty else 0.0
        valor_real = (
            float(muerto_real["Valor Neto Estimado ($)"].sum(skipna=True))
            if not muerto_real.empty
            else 0.0
        )
        stock_total = float(stock["stock_bultos"].sum())
        fecha_stock = pd.to_datetime(stock["fecha_stock"]).max().date()
        # Un SKU muerto de verdad puede no tener NINGUNA venta en la ventana larga,
        # y entonces no hay precio realizado con que valuarlo. Si no se informa la
        # cobertura, el lector suma el valor y cree que cubre todos los bultos.
        if muerto_real.empty:
            sin_precio = 0
            bultos_sin_precio = 0.0
        else:
            faltante = muerto_real["Precio Neto Medio ($)"].isna()
            sin_precio = int(faltante.sum())
            bultos_sin_precio = float(muerto_real.loc[faltante, "Stock Bultos"].sum())
        bultos_valuados = bultos_real - bultos_sin_precio
        if not muerto_real.empty:
            tablas["ciclo_vida_stock_muerto"] = agregar_total_general(
                muerto_real,
                "Articulo",
                cols_suma=["Stock Bultos", "Valor Neto Estimado ($)"],
                extras={"Generico": f"{len(muerto_real):,} SKUs"},
            )
        notas.append(
            f"Stock muerto medido sobre la foto del {fecha_stock.isoformat()} "
            f"(gold.fact_stock arranca el {constants.FECHA_INICIO_STOCK}: no hay historia, no "
            "hay rotacion ni curva de antiguedad posible). Valuado a precio NETO medio "
            "realizado de la ventana larga, no a costo: fact_precio_vigente y "
            "fact_precio_historico estan vacias."
        )
        notas.append(
            f"COBERTURA DE LA VALUACION: {sin_precio:,} de {len(muerto_real):,} SKUs muertos no "
            "tuvieron ninguna venta en la ventana larga y por lo tanto NO tienen precio "
            f"realizado con que valuarse. Son {bultos_sin_precio:,.0f} de {bultos_real:,.0f} "
            f"bultos ({bultos_sin_precio / bultos_real:.0%} del stock muerto) que entran en la "
            f"columna de bultos y aportan $0 a la valuacion. El valor informado cubre solo "
            f"{bultos_valuados:,.0f} bultos: es un PISO, no el valor del stock muerto. "
            "Ademas, el precio medio promedia 24 meses de una economia con ~45% de inflacion "
            "anual, asi que subestima el valor de reposicion de hoy."
            if bultos_real > 0
            else "No quedo stock muerto real que valuar."
        )
        if not muerto_real.empty:
            por_generico = (
                muerto_real.groupby("Generico")["Stock Bultos"].sum().sort_values(ascending=False)
            )
            top = por_generico.head(3)
            notas.append(
                "Composicion del stock muerto ya filtrado, por generico: "
                + "; ".join(
                    f"{g} {v:,.0f} bultos ({v / bultos_real:.0%})" for g, v in top.items()
                )
                + ". OJO: BOUTIQUE es merchandising y NO figura en "
                "constants.GENERICOS_NO_VENTA (si tiene ventas, 2.535 bultos en 12 meses, por "
                "eso no se lo puede excluir automaticamente). Si ademas se lo aparta, la "
                f"obsolescencia de bebida propiamente dicha baja a "
                f"{bultos_real - por_generico.get('BOUTIQUE', 0.0):,.0f} bultos. Es la "
                "diferencia entre una alarma de inventario y una lista de liquidacion de una "
                "tarde."
            )
        if bultos_naive > 0:
            alertas.append(
                Alert(
                    severity="media",
                    title="El stock muerto es una ilusion de higiene de datos",
                    detail=(
                        f"Sin filtrar, {bultos_naive:,.0f} bultos parecen muertos "
                        f"({bultos_naive / stock_total:.1%} del stock). Excluyendo los genericos "
                        f"que no son articulos de venta quedan {bultos_real:,.0f} bultos reales "
                        f"en {len(muerto_real):,} SKUs: {bultos_naive / bultos_real:,.0f} veces "
                        f"menos. De esos bultos solo {bultos_valuados:,.0f} "
                        f"({bultos_valuados / bultos_real:.0%}) tienen precio realizado con que "
                        f"valuarse, y valen ${valor_real:,.0f} netos: es un PISO, no el valor "
                        f"del stock muerto ({sin_precio:,} SKUs nunca vendieron en la ventana y "
                        "aportan $0). La diferencia es "
                        "material promocional, envases, esqueletos y equipos de frio. Cualquier "
                        "KPI de inventario que no filtre esos genericos esta mal por dos "
                        "ordenes de magnitud."
                    ),
                    amount=valor_real,
                )
                if bultos_real > 0
                else Alert(
                    severity="media",
                    title="El stock muerto es una ilusion de higiene de datos",
                    detail=(
                        f"Sin filtrar, {bultos_naive:,.0f} bultos parecen muertos; excluyendo "
                        "los genericos que no son articulos de venta no queda stock muerto real."
                    ),
                    amount=0.0,
                )
            )

    # ---------------- Headlines y alerta de concentracion ----------------
    headlines.append(
        Headline(
            label="SKUs activos (12m)",
            value=skus_activos,
            number_format="#,##0",
            note=f"Con venta neta entre {ini_actual} y {hasta.isoformat()}.",
        )
    )
    headlines.append(
        Headline(
            label="% del neto en clase A",
            value=share_a,
            number_format="0.0%",
            note=f"{skus_a} SKUs de {skus_activos}.",
        )
    )
    headlines.append(
        Headline(
            label="Share de la celda AX",
            value=share_ax,
            number_format="0.0%",
            note=f"{skus_ax} SKUs de alto valor y demanda estable (CV < {constants.XYZ_CORTES[0]}).",
        )
    )
    if top_oportunidad is not None:
        headlines.append(
            Headline(
                label="Mayor oportunidad de cross-sell",
                value=float(top_oportunidad["Oportunidad Techo ($)"]),
                number_format="$ #,##0",
                note=(
                    f"{top_oportunidad['Subcanal']} x {top_oportunidad['Generico']}: "
                    f"{top_oportunidad['No Compradores']:,.0f} no compradores x "
                    f"${top_oportunidad['Neto Mediano por Comprador 6m ($) = ARS por Conversion']:,.0f} "
                    f"de mediana ({MESES_CROSS_SELL} meses). Es un techo, no un pronostico."
                ),
            )
        )

    alertas.insert(
        0,
        Alert(
            severity="alta",
            title="La concentracion del portafolio esta muy por encima de un Pareto normal",
            detail=(
                f"{skus_a} SKUs ({skus_a / skus_activos:.1%} del catalogo activo) explican "
                f"{share_a:.1%} del neto de 12 meses (${neto_a:,.0f} de ${neto_total:,.0f}). "
                f"La sola celda AX concentra {share_ax:.1%} en {skus_ax} SKUs: es demanda "
                "estable y se planifica con un promedio movil, no hace falta modelo. "
                f"En el otro extremo, {skus_cz} SKUs CZ aportan {share_cz:.1%}: cada uno "
                "consume un alta, un precio, una posicion de picking y una linea de lista."
            ),
            amount=neto_a,
        ),
    )

    notas.append(
        "Los identificadores id_vendedor e id_ruta se reusan entre sucursales: todo join "
        "contra dim_vendedor de este modulo usa la clave compuesta (id_vendedor, id_sucursal). "
        "id_cliente si es unico global."
    )
    notas.append(
        "dim_cliente.anulado no se usa como filtro de actividad: 621 clientes marcados como "
        "anulados facturaron $717,7M en los ultimos 6 meses. La actividad se define por venta "
        "observada."
    )

    return AnalysisResult(
        name=NOMBRE,
        tables=tablas,
        headlines=headlines,
        alerts=alertas,
        notes=notas,
    )
