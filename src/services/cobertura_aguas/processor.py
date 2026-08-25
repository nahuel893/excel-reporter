"""Coverage arithmetic for the aguas report — no database, no Excel.

Everything here follows the one criterion that matters:

    1. definir el corte  2. totalizar por cliente DENTRO del corte
    3. filtrar por umbral (por defecto > 0)  4. contar

Grouping BEFORE filtering is the whole point. Filtering line by line would count
the client who returned everything they bought, and would drop the one who
reached the threshold across several small invoices.
"""
from __future__ import annotations

import pandas as pd

from .constants import CONCEPTOS, TOTAL_AGUAS, Concepto

# Columnas que espera `construir_tabla` en el dataframe de ventas.
COLUMNAS_VENTAS = ["id_sucursal", "marca", "id_cliente", "mes", "cantidad"]

# La clave del cliente es COMPUESTA. `id_cliente` se reusa entre sucursales, asi
# que contarlo solo mezclaria clientes distintos en uno.
CLAVE_CLIENTE = ["id_sucursal", "id_cliente"]


def clientes_con_compra(ventas: pd.DataFrame, umbral: float = 0.0) -> int:
    """Cuenta clientes distintos cuyo neto DENTRO del corte supera el umbral.

    `ventas` ya viene recortada al corte que se quiere medir (sucursal, marcas,
    meses). El umbral por defecto es `> 0` y no se hereda de otro informe: si un
    reporte necesita otro piso, lo pasa explicito.
    """
    if ventas.empty:
        return 0
    neto = ventas.groupby(CLAVE_CLIENTE, sort=False)["cantidad"].sum()
    return int((neto > umbral).sum())


def _fila(
    ventas: pd.DataFrame,
    concepto: Concepto,
    meses: list[str],
    umbral: float,
) -> dict:
    """Cobertura mensual y acumulada de un concepto sobre un subconjunto dado."""
    del_concepto = ventas[ventas["marca"].isin(concepto.marcas)]
    fila = {
        f"cob_{mes}": clientes_con_compra(
            del_concepto[del_concepto["mes"] == mes], umbral
        )
        for mes in meses
    }
    # El acumulado NO es la union de los conjuntos mensuales: se totaliza sobre
    # la ventana entera y recien ahi se filtra. El cliente que compra 5 en julio
    # y devuelve 5 en agosto queda cubierto en julio y fuera del acumulado.
    fila["cob_acum"] = clientes_con_compra(del_concepto, umbral)
    return fila


def _bloque(
    ventas: pd.DataFrame,
    meses: list[str],
    padron: int,
    umbral: float,
) -> list[dict]:
    """Las filas de un bloque (una sucursal, o el consolidado) ya con sus pesos."""
    filas = [
        {"fila": c.etiqueta, "tipo": c.tipo, **_fila(ventas, c, meses, umbral)}
        for c in CONCEPTOS
    ]
    # Denominador de los pesos: la cobertura acumulada de TODAS las aguas del
    # bloque. Es el ultimo concepto, y se lee de la fila ya calculada en vez de
    # sumar las marcas — entre marcas la cobertura no es aditiva.
    base = next(f["cob_acum"] for f in filas if f["fila"] == TOTAL_AGUAS)
    for f in filas:
        # `base_aguas` viaja como columna propia para que el denominador de
        # `pct_acum` se pueda leer al lado del porcentaje, igual que `padron`.
        # Un porcentaje sin su base obliga a buscar la fila TOTAL AGUAS a mano.
        f["base_aguas"] = base
        f["pct_acum"] = f["cob_acum"] / base if base else 0.0
        f["padron"] = padron
        f["pct_padron"] = f["cob_acum"] / padron if padron else 0.0
    return filas


def construir_tabla(
    ventas: pd.DataFrame,
    padron: pd.DataFrame,
    meses: list[str],
    umbral: float = 0.0,
) -> pd.DataFrame:
    """Tabla larga: una fila por sucursal x concepto, mas el bloque TOTAL GENERAL.

    Args:
        ventas: grano cliente — ``id_sucursal, marca, id_cliente, mes, cantidad``.
            Una fila por (sucursal, marca, cliente, mes) con la cantidad neta.
        padron: ``id_sucursal, des_sucursal, padron`` — clientes NO anulados.
            Manda el padron: una sucursal sin ventas igual aparece, en cero,
            porque donde no vendemos tambien es informacion.
        meses: meses a abrir, en orden, como ``YYYY-MM``.
        umbral: piso de bultos para considerar cubierto al cliente.

    Returns:
        Columnas: ``id_sucursal, sucursal, fila, tipo, cob_<mes>..., cob_acum,
        pct_acum, padron, pct_padron, es_total_general``.
    """
    ventas = ventas[ventas["marca"].isin(
        [m for c in CONCEPTOS for m in c.marcas]
    )] if not ventas.empty else ventas

    filas: list[dict] = []
    for suc in padron.sort_values("id_sucursal").itertuples(index=False):
        de_la_suc = ventas[ventas["id_sucursal"] == suc.id_sucursal] \
            if not ventas.empty else ventas
        for f in _bloque(de_la_suc, meses, int(suc.padron), umbral):
            filas.append({
                "id_sucursal": suc.id_sucursal,
                "sucursal": suc.des_sucursal,
                "es_total_general": False,
                **f,
            })

    # TOTAL GENERAL. La cobertura SI es aditiva entre sucursales (cada cliente
    # pertenece a una sola), pero se cuenta desde el grano igual: sumar filas
    # arrastraria cualquier error de arriba sin que se note.
    for f in _bloque(ventas, meses, int(padron["padron"].sum()), umbral):
        filas.append({
            "id_sucursal": None,
            "sucursal": "TOTAL GENERAL",
            "es_total_general": True,
            **f,
        })

    columnas = (
        ["id_sucursal", "sucursal", "fila", "tipo"]
        + [f"cob_{m}" for m in meses]
        + ["cob_acum", "base_aguas", "pct_acum", "padron", "pct_padron",
           "es_total_general"]
    )
    return pd.DataFrame(filas)[columnas]
