"""VariableMensualService — reloads the INCENTIVO HERNAN workbook from gold.

The workbook is not generated from scratch: the report sheets (``ramal``, ``qbrd``,
``inte``, ``salta``, ``ORIGINAL``, ``suc``) are Nahuel's, full of hand-tuned
formulas and objectives, and they stay exactly as they are. What this service
replaces is the base data underneath them — the blue-tabbed sheets — plus the
``marcas_x_pdv`` block that used to require a manual pivot refresh and a
copy-paste.

Everything is written with :mod:`src.core.xlsx_blocks`, which edits the target
worksheets' XML inside the zip and copies every other part byte-for-byte, so the
VBA project, styles, drawings and the remaining pivot caches survive.
"""
from __future__ import annotations

import logging
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from src.core import xlsx_blocks as xb
from src.core.periodos import periodo_mes
from src.services.base_service import BaseService
from src.services.variable_mensual import constants as K
from src.services.variable_mensual.formulas import (
    HOJAS_REPARABLES,
    contar_refs_rotas,
    reparar_hoja,
)
from src.services.variable_mensual.processor import (
    agregar_lista_precio,
    agregar_zona,
    calcular_marcas_x_pdv,
    construir_referencia_cobertura,
    construir_referencia_colon,
    construir_referencia_marca,
    construir_referencia_mayorista,
    construir_referencia_volumen,
    preparar_cobertura,
)

logger = logging.getLogger(__name__)


@dataclass
class VariableMensualConfig:
    """Configuration for a variable-mensual reload.

    Args:
        archivo: workbook to update. It is copied to ``salida`` first; the source
            is never written to.
        fecha_desde: inclusive start of the sales window, ``YYYY-MM-DD``.
        fecha_hasta: inclusive end of the sales window, ``YYYY-MM-DD``.
        salida: destination workbook. Defaults to ``archivo`` with a ``.bak``
            sibling of the previous version.
        genericos: generics loaded into AX.
        backup: keep a timestamped copy of the previous workbook.
    """

    archivo: str
    fecha_desde: str
    fecha_hasta: str
    salida: str | None = None
    genericos: list[str] = field(default_factory=lambda: list(K.GENERICOS))
    backup: bool = True


@dataclass
class VariableMensualResult:
    """What a reload wrote."""

    ruta_archivo: Path
    filas_ax: int
    filas_pivot: int
    puntos_de_venta: int
    filas_cober_marca: int
    filas_cober_gen: int
    filas_villa: int
    filas_referencia: int


class VariableMensualService(BaseService):
    """Reloads the base sheets of the INCENTIVO HERNAN workbook."""

    SERVICE_SLUG = "variable-mensual"
    GRANULARITY = "month"

    def generar_reporte(self, config: VariableMensualConfig) -> VariableMensualResult:
        """Reload the workbook's base data and recompute marcas_x_pdv.

        Args:
            config: what to load and where to write it.

        Returns:
            Row counts per sheet, for the caller to log or assert on.
        """
        origen = Path(config.archivo)
        if not origen.exists():
            raise FileNotFoundError(f"Workbook not found: {origen}")
        destino = Path(config.salida) if config.salida else origen

        # The COLON DULCE article list lives in the workbook, not in gold, so it
        # has to be read before the data is pulled.
        articulos_colon = self._articulos_colon_dulce(origen)
        datos = self._cargar_datos(config, articulos_colon)
        edits, drop = self._construir_ediciones(origen, datos)

        self._escribir(origen, destino, edits, drop, backup=config.backup)

        resultado = VariableMensualResult(
            ruta_archivo=destino,
            filas_ax=len(datos["ax"]),
            filas_pivot=len(datos["pivot"]),
            puntos_de_venta=len(datos["conteo"]),
            filas_cober_marca=len(datos["cober_marca"]),
            filas_cober_gen=len(datos["cober_gen"]),
            filas_villa=len(datos["villa"]),
            filas_referencia=len(datos["ref_cobertura"]),
        )
        logger.info(
            "variable-mensual: AX=%d, pivot=%d, PDV=%d, cober_marca=%d, "
            "cober_gen=%d, villa=%d, referencia=%d -> %s",
            resultado.filas_ax,
            resultado.filas_pivot,
            resultado.puntos_de_venta,
            resultado.filas_cober_marca,
            resultado.filas_cober_gen,
            resultado.filas_villa,
            resultado.filas_referencia,
            destino,
        )
        return resultado

    # ------------------------------------------------------------------ #
    # Data
    # ------------------------------------------------------------------ #

    def _cargar_datos(
        self,
        config: VariableMensualConfig,
        articulos_colon: list[int] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Pull every blue sheet's data and derive marcas_x_pdv from AX."""
        periodo = periodo_mes(config.fecha_hasta)

        ax = self.data_loader.get_ventas_variable_mensual(
            fecha_desde=config.fecha_desde,
            fecha_hasta=config.fecha_hasta,
            genericos=config.genericos,
            valle_salta_rutas=K.VALLE_SALTA_RUTAS,
            valle_salta_label=K.VALLE_SALTA_LABEL,
            casa_central_id=K.CASA_CENTRAL_ID,
        )
        ax = agregar_lista_precio(agregar_zona(ax))
        sin_zona = ax["zona"].isna().sum()
        if sin_zona:
            faltantes = sorted(ax.loc[ax["zona"].isna(), "sucursal"].unique())
            # AD is a VLOOKUP over suc!Q:R; a branch missing there would show #N/A
            # in the workbook, so surface it here instead of shipping broken cells.
            logger.warning(
                "%d filas sin zona en suc!Q:R — sucursales: %s", sin_zona, faltantes
            )

        pivot, conteo = calcular_marcas_x_pdv(ax, K.GENERICOS_MXPDV)

        cober_marca = preparar_cobertura(
            self.data_loader.get_cobertura_preventista_variable(
                periodo=periodo,
                nivel="marca",
                id_fuerza_ventas=K.ID_FUERZA_VENTAS,
                valle_salta_rutas=K.VALLE_SALTA_RUTAS,
                valle_salta_label=K.VALLE_SALTA_LABEL,
                casa_central_id=K.CASA_CENTRAL_ID,
                genericos_excluidos=K.GENERICOS_EXCLUIDOS_COBERTURA,
                marcas_excluidas=K.MARCAS_EXCLUIDAS_COBERTURA,
            ),
            concepto="marca",
        )
        cober_gen = preparar_cobertura(
            self.data_loader.get_cobertura_preventista_variable(
                periodo=periodo,
                nivel="generico",
                id_fuerza_ventas=K.ID_FUERZA_VENTAS,
                valle_salta_rutas=K.VALLE_SALTA_RUTAS,
                valle_salta_label=K.VALLE_SALTA_LABEL,
                casa_central_id=K.CASA_CENTRAL_ID,
                genericos=config.genericos,
            ),
            concepto="generico",
        )
        villa = self.data_loader.get_cobertura_marcas_union(
            fecha_desde=config.fecha_desde,
            fecha_hasta=config.fecha_hasta,
            marcas=K.MARCAS_VILLA,
            id_fuerza_ventas=K.ID_FUERZA_VENTAS,
            valle_salta_rutas=K.VALLE_SALTA_RUTAS,
            valle_salta_label=K.VALLE_SALTA_LABEL,
            casa_central_id=K.CASA_CENTRAL_ID,
        )
        villa["marca"] = K.MARCA_VILLA_LABEL
        villa = preparar_cobertura(villa, concepto="marca")

        datos = {
            "ax": ax,
            "pivot": pivot,
            "conteo": conteo,
            "cober_marca": cober_marca,
            "cober_gen": cober_gen,
            "villa": villa,
        }
        datos.update(
            self._construir_referencia(config, datos, articulos_colon or [])
        )
        return datos

    def _construir_referencia(
        self,
        config: VariableMensualConfig,
        datos: dict[str, pd.DataFrame],
        articulos_colon: list[int],
    ) -> dict[str, pd.DataFrame]:
        """Build the five blocks of ``referencia ma``.

        Every branch's share of its own zone, in coverage and in volume. The
        sheet excludes CASA CENTRAL and VALLE SALTA: it only feeds the interior
        zone reports.
        """
        sucursales = K.REFERENCIA_SUCURSALES
        ventas = datos["ax"][datos["ax"]["sucursal"].isin(sucursales)]

        cobertura_colon = self.data_loader.get_cobertura_articulos(
            fecha_desde=config.fecha_desde,
            fecha_hasta=config.fecha_hasta,
            articulos=articulos_colon,
        )
        # The query keys by branch id; the sheet labels are "<id> - <NAME>".
        por_id = {int(s.split(" - ")[0]): s for s in sucursales}
        cobertura_colon = cobertura_colon.assign(
            sucursal=cobertura_colon["id_sucursal"].map(por_id)
        ).dropna(subset=["sucursal"])

        return {
            "ref_cobertura": construir_referencia_cobertura(
                cober_gen=datos["cober_gen"],
                conteo=datos["conteo"],
                sucursales=sucursales,
                genericos=config.genericos,
                zona_por_sucursal=K.ZONA_POR_SUCURSAL,
                genericos_mxpdv=K.GENERICOS_MXPDV,
            ),
            "ref_volumen": construir_referencia_volumen(
                ventas=ventas,
                sucursales=sucursales,
                genericos=config.genericos,
                zona_por_sucursal=K.ZONA_POR_SUCURSAL,
            ),
            "ref_marca": construir_referencia_marca(
                cober_marca=datos["cober_marca"],
                sucursales=sucursales,
                marcas=K.REFERENCIA_MARCAS,
                zona_por_sucursal=K.ZONA_POR_SUCURSAL,
            ),
            "ref_colon": construir_referencia_colon(
                cobertura_colon=cobertura_colon,
                sucursales=sucursales,
                zona_por_sucursal=K.ZONA_POR_SUCURSAL,
                etiqueta=K.REFERENCIA_MARCA_COLON,
            ),
            "ref_mayorista": construir_referencia_mayorista(
                ventas=ventas,
                sucursales=sucursales,
                genericos=config.genericos,
                zona_por_sucursal=K.ZONA_POR_SUCURSAL,
                listas_mayoristas=K.LISTAS_MAYORISTAS,
            ),
        }

    # ------------------------------------------------------------------ #
    # Workbook edits
    # ------------------------------------------------------------------ #

    def _construir_ediciones(
        self, origen: Path, datos: dict[str, pd.DataFrame]
    ) -> tuple[dict[str, bytes], set[str]]:
        """Render every zip part this reload replaces or removes."""
        edits: dict[str, bytes] = {}
        drop: set[str] = set()

        with zipfile.ZipFile(origen) as zin:
            sheets = xb.map_sheet_files(zin)
            # One string table for the whole run: branch, brand, price-list and
            # generic names repeat across ~200k cells and are stored once each.
            strings = xb.load_shared_strings(zin)

            edits.update(self._editar_ax(zin, sheets, datos["ax"], strings))
            edits.update(
                self._editar_marcas_x_pdv(
                    zin, sheets, datos["pivot"], datos["conteo"], strings
                )
            )
            edits.update(self._editar_cobertura(zin, sheets, datos, strings))
            edits.update(self._editar_referencia(zin, sheets, datos, strings))
            edits.update(self._reparar_formulas(zin, sheets))
            edits.update(self._editar_workbook_y_pivots(zin))

            drop |= self._descartar_pivot_marcas_x_pdv(zin, sheets, edits)

            if strings.dirty:
                edits[xb.SHARED_STRINGS_PART] = strings.to_xml()

        return edits, drop

    def _editar_ax(
        self,
        zin: zipfile.ZipFile,
        sheets: dict[str, str],
        ax: pd.DataFrame,
        strings: xb.SharedStrings,
    ) -> dict[str, bytes]:
        """Rebuild AX and stretch the ``aexcel`` table to the new last row."""
        sheet_file = sheets[K.SHEET_AX]
        # Fresh specs per run: rebuild_table_sheet fills in sampled styles in place.
        columns = [_clonar(spec) for spec in K.AX_COLUMNS]
        edits = {
            sheet_file: xb.rebuild_table_sheet(
                zin, sheet_file, columns, ax, header_rows=1, strings=strings
            )
        }

        table_file = _tabla_de_hoja(zin, sheet_file)
        if table_file:
            table_xml = zin.read(table_file).decode("utf-8")
            # The table ref is what makes AD/AE reach the foot of the data: Excel
            # fills a table's formula columns for every row inside ``ref``.
            edits[table_file] = xb.resize_table(table_xml, len(ax) + 1).encode("utf-8")
        return edits

    def _editar_marcas_x_pdv(
        self,
        zin: zipfile.ZipFile,
        sheets: dict[str, str],
        pivot: pd.DataFrame,
        conteo: pd.DataFrame,
        strings: xb.SharedStrings,
    ) -> dict[str, bytes]:
        """Paste the pivot, the client list and the brand counts into their ranges."""
        sheet_file = sheets[K.SHEET_MXPDV]
        original = zin.read(sheet_file).decode("utf-8")
        anterior = _ultima_fila_usada(original)

        blocks = [
            xb.Block(
                first_row=K.MXPDV_PIVOT_FIRST_ROW,
                columns=[_clonar(spec) for spec in K.MXPDV_PIVOT_COLUMNS],
                data=pivot,
                clear_through=anterior,
            ),
            xb.Block(
                first_row=K.MXPDV_CLIENTES_FIRST_ROW,
                columns=[_clonar(spec) for spec in K.MXPDV_CLIENTES_COLUMNS],
                data=conteo,
                clear_through=anterior,
            ),
            xb.Block(
                first_row=K.MXPDV_CONTEO_FIRST_ROW,
                columns=[_clonar(spec) for spec in K.MXPDV_CONTEO_COLUMNS],
                data=conteo,
                clear_through=anterior,
            ),
        ]
        return {sheet_file: xb.patch_blocks(original, blocks, strings)}

    def _editar_cobertura(
        self,
        zin: zipfile.ZipFile,
        sheets: dict[str, str],
        datos: dict[str, pd.DataFrame],
        strings: xb.SharedStrings,
    ) -> dict[str, bytes]:
        """Reload the three coverage sheets and resize their tables."""
        planes = [
            (K.SHEET_COBER_MARCA, datos["cober_marca"], "marca"),
            (K.SHEET_COBER_GEN, datos["cober_gen"], "generico"),
            (K.SHEET_VILLA, datos["villa"], "marca"),
        ]
        edits: dict[str, bytes] = {}
        for nombre, df, concepto in planes:
            sheet_file = sheets[nombre]
            columns = K.cober_columns(K.COBER_TABLE[nombre], concepto)
            edits[sheet_file] = xb.rebuild_table_sheet(
                zin, sheet_file, columns, df, header_rows=1, strings=strings
            )
            table_file = _tabla_de_hoja(zin, sheet_file)
            if table_file:
                table_xml = zin.read(table_file).decode("utf-8")
                edits[table_file] = xb.resize_table(table_xml, len(df) + 1).encode("utf-8")
        return edits

    def _articulos_colon_dulce(self, origen: Path) -> list[int]:
        """Article ids from the workbook's ``art_colon_dulce`` sheet.

        Nothing in gold marks these products, so the sheet is the only source of
        truth — it is one of the blue sheets Nahuel keeps by hand. Only column A
        is read, and only numeric cells, so the descriptions beside them are
        ignored.
        """
        import re

        with zipfile.ZipFile(origen) as zin:
            sheets = xb.map_sheet_files(zin)
            if K.SHEET_ART_COLON not in sheets:
                logger.warning("Falta la hoja '%s': COLON DULCE queda en cero",
                               K.SHEET_ART_COLON)
                return []
            xml = zin.read(sheets[K.SHEET_ART_COLON]).decode("utf-8")

        articulos: list[int] = []
        for attrs, valor in re.findall(
            r'<c r="A\d+"([^>]*)>\s*<v>([^<]+)</v>', xml
        ):
            if 't="s"' in attrs or 't="str"' in attrs:
                continue
            try:
                articulos.append(int(float(valor)))
            except ValueError:
                continue
        if not articulos:
            logger.warning("'%s' no tiene codigos de articulo", K.SHEET_ART_COLON)
        return sorted(set(articulos))

    def _editar_referencia(
        self,
        zin: zipfile.ZipFile,
        sheets: dict[str, str],
        datos: dict[str, pd.DataFrame],
        strings: xb.SharedStrings,
    ) -> dict[str, bytes]:
        """Write the five side-by-side blocks of ``referencia ma``."""
        sheet_file = sheets[K.SHEET_REFERENCIA]
        original = zin.read(sheet_file).decode("utf-8")
        anterior = _ultima_fila_usada(original)

        planes = [
            (K.REFERENCIA_COBERTURA_COLUMNS, datos["ref_cobertura"]),
            (K.REFERENCIA_VOLUMEN_COLUMNS, datos["ref_volumen"]),
            (K.REFERENCIA_MARCA_COLUMNS, datos["ref_marca"]),
            (K.REFERENCIA_COLON_COLUMNS, datos["ref_colon"]),
            (K.REFERENCIA_MAYORISTA_COLUMNS, datos["ref_mayorista"]),
        ]
        blocks = [
            xb.Block(
                first_row=K.REFERENCIA_FIRST_ROW,
                columns=[_clonar(spec) for spec in columnas],
                data=df,
                # Column D used to trail 3.500 rows of leftovers below the block.
                clear_through=anterior,
            )
            for columnas, df in planes
        ]
        edits = {sheet_file: xb.patch_blocks(original, blocks, strings)}

        table_file = _tabla_de_hoja(zin, sheet_file)
        if table_file:
            table_xml = zin.read(table_file).decode("utf-8")
            ultima = K.REFERENCIA_FIRST_ROW + len(datos["ref_cobertura"]) - 1
            edits[table_file] = xb.resize_table(table_xml, ultima).encode("utf-8")
        return edits

    def _reparar_formulas(
        self, zin: zipfile.ZipFile, sheets: dict[str, str]
    ) -> dict[str, bytes]:
        """Restore the workbook's pre-existing broken ``#REF!`` formulas.

        These were already broken when the workbook arrived — the wholesale-mix
        tables in ``suc`` and the per-branch MIX MAY rows had been showing
        ``#REF!`` for a long time. Repair is idempotent, so running it every time
        costs nothing and keeps the sheets correct if someone reopens an old copy.
        """
        edits: dict[str, bytes] = {}
        for hoja in HOJAS_REPARABLES:
            if hoja not in sheets:
                continue
            xml = zin.read(sheets[hoja]).decode("utf-8")
            if "#REF!" not in xml:
                continue
            nuevo, reparadas = reparar_hoja(hoja, xml)
            if not reparadas:
                continue
            edits[sheets[hoja]] = nuevo.encode("utf-8")
            quedan = contar_refs_rotas(nuevo)
            logger.info(
                "%s: %d formulas #REF! reparadas%s",
                hoja,
                reparadas,
                f", quedan {quedan} sin patron conocido" if quedan else "",
            )
        return edits

    def _editar_workbook_y_pivots(self, zin: zipfile.ZipFile) -> dict[str, bytes]:
        """Force a full recalc and make the surviving pivots re-read their source.

        Formula cells are written without a cached value, and the pivots feeding
        ``cober_colon_dulce`` and ``suc`` sit on top of sheets this reload just
        rewrote — without these two flags the workbook would open showing the
        previous run's numbers.
        """
        edits: dict[str, bytes] = {}

        workbook_xml = zin.read("xl/workbook.xml").decode("utf-8")
        edits["xl/workbook.xml"] = xb.force_full_recalc(workbook_xml).encode("utf-8")

        for name in zin.namelist():
            if name.startswith("xl/pivotCache/pivotCacheDefinition"):
                cache_xml = zin.read(name).decode("utf-8")
                edits[name] = xb.refresh_pivot_caches_on_load(cache_xml).encode("utf-8")
        return edits

    def _descartar_pivot_marcas_x_pdv(
        self, zin: zipfile.ZipFile, sheets: dict[str, str], edits: dict[str, bytes]
    ) -> set[str]:
        """Remove pivotTable1, whose range Python now writes directly.

        A pivot table and pasted values cannot share A3:F60803: on refresh the
        pivot would overwrite whatever is there. Since the grouping now happens in
        Python, the pivot part, its relationship and its content-type entry go.
        """
        sheet_file = sheets[K.SHEET_MXPDV]
        rels_path = sheet_file.replace("worksheets/", "worksheets/_rels/") + ".rels"
        if rels_path not in zin.namelist():
            return set()

        rels = zin.read(rels_path).decode("utf-8")
        import re

        match = re.search(
            r'<Relationship[^>]*Type="[^"]*/pivotTable"[^>]*Target="([^"]+)"[^>]*/>', rels
        )
        if not match:
            return set()

        target = match.group(1).replace("../", "xl/")
        edits[rels_path] = rels.replace(match.group(0), "").encode("utf-8")

        content_types = zin.read("[Content_Types].xml").decode("utf-8")
        edits["[Content_Types].xml"] = re.sub(
            rf'<Override PartName="/{re.escape(target)}"[^>]*/>', "", content_types
        ).encode("utf-8")

        drop = {target}
        pivot_rels = target.replace("pivotTables/", "pivotTables/_rels/") + ".rels"
        if pivot_rels in zin.namelist():
            drop.add(pivot_rels)
        return drop

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #

    def _escribir(
        self,
        origen: Path,
        destino: Path,
        edits: dict[str, bytes],
        drop: set[str],
        backup: bool,
    ) -> None:
        """Write the new workbook, backing up the previous one first."""
        if backup and destino.exists():
            marca = date.today().isoformat()
            respaldo = destino.with_suffix(f".{marca}.bak{destino.suffix}")
            shutil.copy2(destino, respaldo)
            logger.info("Backup: %s", respaldo)

        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        xb.edit_workbook(str(origen), str(temporal), edits, drop)
        temporal.replace(destino)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _clonar(spec: xb.ColumnSpec) -> xb.ColumnSpec:
    """Copy a column spec so sampled styles never leak between runs."""
    return xb.ColumnSpec(
        letter=spec.letter,
        kind=spec.kind,
        source=spec.source,
        formula=spec.formula,
        style=spec.style,
        is_string=spec.is_string,
    )


def _tabla_de_hoja(zin: zipfile.ZipFile, sheet_file: str) -> str | None:
    """Path of the Excel table attached to a worksheet, if any."""
    import os
    import re

    rels_path = sheet_file.replace("worksheets/", "worksheets/_rels/") + ".rels"
    if rels_path not in zin.namelist():
        return None
    rels = zin.read(rels_path).decode("utf-8", "replace")
    match = re.search(r'Target="([^"]*tables/[^"]+)"', rels)
    if not match:
        return None
    target = match.group(1)
    if target.startswith("/"):
        return target.lstrip("/")
    return os.path.normpath("xl/worksheets/" + target).replace("\\", "/")


def _ultima_fila_usada(sheet_xml: str) -> int:
    """Highest row number present in a worksheet, used to wipe stale rows."""
    import re

    filas = [int(n) for n in re.findall(r'<row\b[^>]*?\br="(\d+)"', sheet_xml)]
    return max(filas) if filas else 0
