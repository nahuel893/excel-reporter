"""Transformations behind the variable-mensual workbook.

The interesting one is :func:`calcular_marcas_x_pdv`, which replaces what used to
be a pivot table plus a column of COUNTIFS.
"""
from __future__ import annotations

import pandas as pd

from src.services.variable_mensual.constants import (
    GENERICOS_MXPDV,
    LISTAS_DE_PRECIO,
    ZONA_POR_SUCURSAL,
)


def agregar_zona(df: pd.DataFrame, columna_sucursal: str = "sucursal") -> pd.DataFrame:
    """Add the ``zona`` column the workbook derives with VLOOKUP over suc!Q:R."""
    out = df.copy()
    out["zona"] = out[columna_sucursal].map(ZONA_POR_SUCURSAL)
    return out


def agregar_lista_precio(df: pd.DataFrame) -> pd.DataFrame:
    """Turn ``id_lista_precio`` into the name AX column V carries.

    Unknown ids are left blank rather than guessed: the original export had blank
    price lists too, and a wrong label would silently change the wholesale share.
    """
    out = df.copy()
    out["lista_precio"] = out["id_lista_precio"].map(LISTAS_DE_PRECIO)
    return out


def construir_pivot_marcas(ventas: pd.DataFrame) -> pd.DataFrame:
    """Reproduce pivotTable1: net units per client x generic x brand x branch x zone.

    This is the A3:F block of ``marcas_x_pdv``. The pivot summed
    ``Cantidades Totales`` over exactly these five row fields, so the aggregation
    here is a straight groupby with the same keys.

    Args:
        ventas: AX-shaped rows with id_cliente, generico, marca, sucursal, zona,
            cantidad.

    Returns:
        DataFrame sorted the way the pivot laid it out, so the pasted range keeps
        the reading order Nahuel is used to.
    """
    columnas = ["id_cliente", "generico", "marca", "sucursal", "zona"]
    pivot = (
        ventas.groupby(columnas, as_index=False, dropna=False)["cantidad"]
        .sum()
        .sort_values(columnas, kind="mergesort")
        .reset_index(drop=True)
    )
    return pivot


def construir_clientes(pivot: pd.DataFrame) -> pd.DataFrame:
    """The J:L block — one row per point of sale.

    The workbook built this by copying the pivot's client column and removing
    duplicates. A client only ever belongs to one branch here, because the branch
    is already part of the pivot key.
    """
    clientes = (
        pivot[["id_cliente", "sucursal", "zona"]]
        .drop_duplicates()
        .sort_values(["id_cliente", "sucursal"], kind="mergesort")
        .reset_index(drop=True)
    )
    return clientes


def contar_marcas_por_pdv(
    pivot: pd.DataFrame,
    clientes: pd.DataFrame,
    genericos: list[str] | None = None,
) -> pd.DataFrame:
    """How many brands of each generic every point of sale bought.

    This is the N/O/P block, previously
    ``COUNTIFS($A:$A,$J3,$B:$B,N$1,$F:$F,">0")``: count the pivot rows for that
    client and generic whose summed quantity is strictly positive. Because the
    pivot already totals per brand, one qualifying row IS one brand — a client who
    bought and fully returned a brand nets to zero and does not count.

    Args:
        pivot: output of :func:`construir_pivot_marcas`.
        clientes: output of :func:`construir_clientes`, defining row order.
        genericos: generics to score, in column order. Defaults to the three the
            workbook scores.

    Returns:
        ``clientes`` with one integer column per generic, aligned row for row.
    """
    genericos = genericos or GENERICOS_MXPDV

    positivos = pivot[pivot["cantidad"] > 0]
    conteo = (
        positivos.groupby(["id_cliente", "sucursal", "generico"], dropna=False)
        .size()
        .unstack("generico", fill_value=0)
    )

    out = clientes.copy()
    index = pd.MultiIndex.from_frame(out[["id_cliente", "sucursal"]])
    for generico in genericos:
        if generico in conteo.columns:
            out[generico] = conteo[generico].reindex(index, fill_value=0).to_numpy()
        else:
            out[generico] = 0
    return out


def calcular_marcas_x_pdv(
    ventas: pd.DataFrame,
    genericos: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build both halves of the marcas_x_pdv sheet from AX-shaped sales.

    Returns:
        ``(pivot, conteo)`` — the A:F block and the J:P block. The R:V averages
        stay as workbook formulas and read the second one.
    """
    pivot = construir_pivot_marcas(ventas)
    clientes = construir_clientes(pivot)
    conteo = contar_marcas_por_pdv(pivot, clientes, genericos)
    return pivot, conteo


def preparar_cobertura(df: pd.DataFrame, concepto: str) -> pd.DataFrame:
    """Shape a coverage query into the sheet layout (Column1 is a 0-based index)."""
    out = df.copy()
    if "concepto" in out.columns and concepto != "concepto":
        out = out.rename(columns={"concepto": concepto})
    out = out.reset_index(drop=True)
    out.insert(0, "orden", range(len(out)))
    return out


# --------------------------------------------------------------------------- #
# referencia ma
# --------------------------------------------------------------------------- #


def _participacion(parte: pd.Series, total: pd.Series) -> pd.Series:
    """parte / total, with 0 where the zone has nothing (never a division error)."""
    return (parte / total.where(total != 0)).fillna(0.0)


def _con_totales_de_zona(
    df: pd.DataFrame, claves: list[str], valor: str = "valor"
) -> pd.DataFrame:
    """Add the zone total for each row and the row's share of it.

    ``claves`` are the columns that define a zone total, e.g. ``["zona",
    "generico"]``. This is only sound because coverage and volume are both
    additive across branches inside a zone — the pasted values confirm it: the
    four SALTA INTERIOR branches summed exactly to the zone total.
    """
    totales = df.groupby(claves, as_index=False)[valor].sum()
    totales = totales.rename(columns={valor: "total_zona"})
    out = df.merge(totales, on=claves, how="left")
    out["participacion"] = _participacion(out[valor], out["total_zona"])
    return out


def _grilla(sucursales: list[str], conceptos, columna: str) -> pd.DataFrame:
    """Full branch x concept grid, in the sheet's fixed row order.

    The sheet has a row per combination whether or not there were sales, so the
    grid is built first and the data is merged onto it. A branch that sold
    nothing shows 0, not a missing row — dropping the row would shift every row
    below it and silently repoint the report sheets.
    """
    filas = [
        {"sucursal": sucursal, columna: concepto}
        for concepto in conceptos
        for sucursal in sucursales
    ]
    return pd.DataFrame(filas)


def construir_referencia_cobertura(
    cober_gen: pd.DataFrame,
    conteo: pd.DataFrame,
    sucursales: list[str],
    genericos: list[str],
    zona_por_sucursal: dict[str, str],
    genericos_mxpdv: list[str],
) -> pd.DataFrame:
    """Block A:G — coverage per branch and generic, plus its share of the zone.

    Column D (M X PDV) is informational: nothing in the workbook reads it. It is
    filled with the same average marcas_x_pdv computes, so both sheets agree.
    """
    grilla = _grilla(sucursales, genericos, "generico")
    grilla["zona"] = grilla["sucursal"].map(zona_por_sucursal)

    cobertura = (
        cober_gen.groupby(["sucursal", "generico"], as_index=False)["clientes"]
        .sum()
        .rename(columns={"clientes": "valor"})
    )
    out = grilla.merge(cobertura, on=["sucursal", "generico"], how="left")
    out["valor"] = out["valor"].fillna(0)
    out = _con_totales_de_zona(out, ["zona", "generico"])

    promedios = {}
    for sucursal in sucursales:
        fila = conteo[conteo["sucursal"] == sucursal]
        for generico in genericos_mxpdv:
            if generico not in fila.columns:
                continue
            con_marca = (fila[generico] > 0).sum()
            promedios[(sucursal, generico)] = (
                fila[generico].sum() / con_marca if con_marca else None
            )
    out["marcas_x_pdv"] = [
        promedios.get((s, g)) for s, g in zip(out["sucursal"], out["generico"])
    ]
    return out


def construir_referencia_volumen(
    ventas: pd.DataFrame,
    sucursales: list[str],
    genericos: list[str],
    zona_por_sucursal: dict[str, str],
) -> pd.DataFrame:
    """Block I:N — volume in units per branch and generic, and its zone share.

    Units, not hectolitres: the pasted values matched ``cantidades_total`` to the
    fourth decimal, and did not match the htls column at all.
    """
    grilla = _grilla(sucursales, genericos, "generico")
    grilla["zona"] = grilla["sucursal"].map(zona_por_sucursal)

    volumen = (
        ventas.groupby(["sucursal", "generico"], as_index=False)["cantidad"]
        .sum()
        .rename(columns={"cantidad": "valor"})
    )
    out = grilla.merge(volumen, on=["sucursal", "generico"], how="left")
    out["valor"] = out["valor"].fillna(0.0)
    return _con_totales_de_zona(out, ["zona", "generico"])


def construir_referencia_marca(
    cober_marca: pd.DataFrame,
    sucursales: list[str],
    marcas: dict[str, str],
    zona_por_sucursal: dict[str, str],
) -> pd.DataFrame:
    """Block P:V — coverage of the focus brands per branch, and its zone share.

    Args:
        marcas: ``{label written in the sheet: brand as stored in gold}``.
    """
    grilla = _grilla(sucursales, list(marcas), "marca")
    grilla["zona"] = grilla["sucursal"].map(zona_por_sucursal)
    grilla["marca_gold"] = grilla["marca"].map(marcas)

    cobertura = (
        cober_marca.groupby(["sucursal", "marca"], as_index=False)["clientes"]
        .sum()
        .rename(columns={"marca": "marca_gold", "clientes": "valor"})
    )
    out = grilla.merge(cobertura, on=["sucursal", "marca_gold"], how="left")
    out["valor"] = out["valor"].fillna(0)
    out = _con_totales_de_zona(out, ["zona", "marca"])
    return out.drop(columns=["marca_gold"])


def construir_referencia_colon(
    cobertura_colon: pd.DataFrame,
    sucursales: list[str],
    zona_por_sucursal: dict[str, str],
    etiqueta: str,
) -> pd.DataFrame:
    """Block W:AB — coverage of the COLON DULCE articles per branch."""
    out = pd.DataFrame({"sucursal": sucursales})
    out["zona"] = out["sucursal"].map(zona_por_sucursal)
    out["marca"] = etiqueta
    out = out.merge(
        cobertura_colon.rename(columns={"clientes": "valor"})[["sucursal", "valor"]],
        on="sucursal",
        how="left",
    )
    out["valor"] = out["valor"].fillna(0)
    return _con_totales_de_zona(out, ["zona", "marca"])


def construir_referencia_mayorista(
    ventas: pd.DataFrame,
    sucursales: list[str],
    genericos: list[str],
    zona_por_sucursal: dict[str, str],
    listas_mayoristas: list[str],
) -> pd.DataFrame:
    """Block AD:AN — the wholesale split of volume, per branch and generic.

    Three different ratios, all confirmed against the pasted values:

    - ``pct_mayo_zona``      = wholesale / total, for the whole zone
    - ``pct_participacion``  = the branch's share of its zone's WHOLESALE volume
      (not of its total volume — that trips people up)
    - ``pct_mayo_sucursal``  = wholesale / total, for the branch
    """
    grilla = _grilla(sucursales, genericos, "generico")
    grilla["zona"] = grilla["sucursal"].map(zona_por_sucursal)

    ventas = ventas.copy()
    ventas["es_mayorista"] = ventas["lista_precio"].isin(listas_mayoristas)
    ventas["cantidad_mayorista"] = ventas["cantidad"].where(ventas["es_mayorista"], 0.0)

    por_sucursal = ventas.groupby(["sucursal", "generico"], as_index=False)[
        ["cantidad", "cantidad_mayorista"]
    ].sum()
    out = grilla.merge(por_sucursal, on=["sucursal", "generico"], how="left")
    out[["cantidad", "cantidad_mayorista"]] = out[
        ["cantidad", "cantidad_mayorista"]
    ].fillna(0.0)
    out = out.rename(
        columns={
            "cantidad": "volumen_sucursal",
            "cantidad_mayorista": "mayorista_sucursal",
        }
    )

    zona = out.groupby(["zona", "generico"], as_index=False)[
        ["volumen_sucursal", "mayorista_sucursal"]
    ].sum()
    zona = zona.rename(
        columns={
            "volumen_sucursal": "volumen_zona",
            "mayorista_sucursal": "mayorista_zona",
        }
    )
    out = out.merge(zona, on=["zona", "generico"], how="left")

    out["pct_mayo_zona"] = _participacion(out["mayorista_zona"], out["volumen_zona"])
    out["pct_participacion"] = _participacion(
        out["mayorista_sucursal"], out["mayorista_zona"]
    )
    out["pct_mayo_sucursal"] = _participacion(
        out["mayorista_sucursal"], out["volumen_sucursal"]
    )
    return out
