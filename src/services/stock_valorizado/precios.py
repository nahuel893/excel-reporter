"""Loader for the external ERP price-list export.

There is no price column anywhere in ``gold``, so the valuation depends on an
xlsx exported by hand from the ERP. That makes this module the weakest link of
the report: a silently half-loaded price list produces a plausible-looking
number that is simply wrong. Every failure mode here therefore raises instead
of degrading.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Column names exactly as the ERP export writes them (accents included).
COLUMNA_ID = "Artículo"
COLUMNA_PRECIO = "Precio Base"
COLUMNA_PRECIO_FINAL = "Precio Final"

# Both price columns are mandatory: the report values the same stock twice, once
# per column, and a file carrying only one of them is the wrong export.
_COLUMNAS_PRECIO = {COLUMNA_PRECIO: "precio_base", COLUMNA_PRECIO_FINAL: "precio_final"}


def cargar_lista_precios(path: str | Path) -> pd.DataFrame:
    """Read the ERP price list and normalise it to id / base price / final price.

    Both prices are quoted per bulto (verified against the export:
    ``Precio Final / Presentación == Unit. Final``), so they multiply directly
    against ``cant_bultos`` with no unit conversion.

    ``Precio Final`` is not a variant of ``Precio Base`` — it is
    ``Precio Base * 1.21 + Imp. Internos`` (verified on all 2307 rows of the
    2026-08 export), i.e. VAT plus internal taxes. Note that 15 articles carry a
    zero base and a non-zero final, so the two valuations do not cover the same
    set of articles.

    Returns:
        DataFrame with exactly three columns: ``id_articulo`` (int64),
        ``precio_base`` and ``precio_final`` (float64), at full source precision.

    Raises:
        FileNotFoundError: The file does not exist.
        ValueError: A required column is missing, an article id repeats, or a
            price cannot be read as a number.
    """
    ruta = Path(path)
    if not ruta.is_file():
        raise FileNotFoundError(
            f"No se encontró la lista de precios en {ruta}. "
            "Exportala del ERP y dejala en esa ruta (o corregí lista_precios_path)."
        )

    df = pd.read_excel(ruta)

    faltantes = [c for c in (COLUMNA_ID, *_COLUMNAS_PRECIO) if c not in df.columns]
    if faltantes:
        raise ValueError(
            f"La lista de precios {ruta.name} no tiene la(s) columna(s) {faltantes}. "
            f"Columnas encontradas: {list(df.columns)}"
        )

    ids = pd.to_numeric(df[COLUMNA_ID], errors="coerce")
    if ids.isna().any():
        raise ValueError(
            f"La lista de precios {ruta.name} tiene {int(ids.isna().sum())} fila(s) "
            f"con '{COLUMNA_ID}' vacío o no numérico."
        )

    columnas = {"id_articulo": ids.astype("int64")}
    for origen, destino in _COLUMNAS_PRECIO.items():
        precios = pd.to_numeric(df[origen], errors="coerce")
        no_numericos = precios.isna() & df[origen].notna()
        if no_numericos.any():
            ejemplos = df.loc[no_numericos, origen].head(3).tolist()
            raise ValueError(
                f"La lista de precios {ruta.name} tiene {int(no_numericos.sum())} precio(s) "
                f"no numéricos en '{origen}'. Ejemplos: {ejemplos}"
            )
        columnas[destino] = precios.fillna(0.0)

    out = pd.DataFrame(columnas)

    duplicados = out.loc[out["id_articulo"].duplicated(keep=False), "id_articulo"].unique()
    if len(duplicados):
        raise ValueError(
            f"La lista de precios {ruta.name} tiene {len(duplicados)} artículo(s) "
            f"duplicados; no se puede elegir un precio. Ejemplos: {sorted(duplicados)[:5]}"
        )

    logger.info(
        "Lista de precios cargada: %s (%d artículos, actualizada %s)",
        ruta.name, len(out), fecha_actualizacion(ruta).strftime("%d-%m-%Y %H:%M"),
    )
    return out.reset_index(drop=True)


def fecha_actualizacion(path: str | Path) -> datetime:
    """Modification time of the price list — surfaced on the sheet so a stale
    file is visible rather than silently producing stale money."""
    return datetime.fromtimestamp(Path(path).stat().st_mtime)


# Prices are re-exported from the ERP by hand. Nothing in the pipeline notices
# when that stops happening: a four-month-old list produces a report that looks
# exactly as authoritative as a fresh one. This is the only guard against it.
MAX_DIAS_DEFAULT = 30


@dataclass(frozen=True)
class EstadoListaPrecios:
    """Freshness of the hand-maintained price list."""

    nombre: str
    mtime: datetime
    dias: int
    max_dias: int

    @property
    def vencida(self) -> bool:
        return self.dias > self.max_dias

    @property
    def leyenda(self) -> str:
        """One line for the sheet header — loud when stale, factual when not."""
        sello = self.mtime.strftime("%d-%m-%Y %H:%M")
        if not self.vencida:
            return f"lista '{self.nombre}' actualizada {sello} (hace {self.dias} d)"
        return (
            f"⚠ ATENCIÓN: LISTA DE PRECIOS DESACTUALIZADA — "
            f"'{self.nombre}' es del {sello}, hace {self.dias} días "
            f"(máximo {self.max_dias}). Los precios se cargan A MANO desde el ERP: "
            f"volvé a exportarla y regenerá el informe antes de usar estos importes."
        )


def estado_lista_precios(
    path: str | Path, max_dias: int = MAX_DIAS_DEFAULT, ahora: datetime | None = None
) -> EstadoListaPrecios:
    """Age of the price list against the freshness threshold.

    Age comes from the file's mtime, which is what actually changes when the
    export is replaced — a date written inside the file would go stale silently
    if someone re-saved without re-exporting.
    """
    ruta = Path(path)
    mtime = fecha_actualizacion(ruta)
    referencia = ahora or datetime.now()
    dias = max((referencia - mtime).days, 0)
    estado = EstadoListaPrecios(
        nombre=ruta.name, mtime=mtime, dias=dias, max_dias=max_dias
    )
    if estado.vencida:
        logger.warning(
            "Lista de precios VENCIDA: %s tiene %d días (máximo %d). "
            "Los importes valorizados pueden estar desactualizados.",
            estado.nombre, estado.dias, estado.max_dias,
        )
    return estado
