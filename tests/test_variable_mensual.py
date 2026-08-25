"""Tests for the variable-mensual (INCENTIVO HERNAN) service.

The COUNTIFS these tests stand in for is the one that used to live in
``marcas_x_pdv``, so the fixtures are built around its edge cases: a brand that
nets to zero, a client with no sales of a generic, and the VALLE SALTA split.
"""
import zipfile

import pandas as pd
import pytest

from src.core import xlsx_blocks as xb
from src.services.variable_mensual import constants as K
from src.services.variable_mensual.processor import (
    agregar_lista_precio,
    agregar_zona,
    calcular_marcas_x_pdv,
    construir_clientes,
    construir_pivot_marcas,
    contar_marcas_por_pdv,
    preparar_cobertura,
)


def _ventas(filas):
    """Build AX-shaped rows from (cliente, generico, marca, sucursal, cantidad)."""
    return pd.DataFrame(
        [
            {
                "id_cliente": c,
                "generico": g,
                "marca": m,
                "sucursal": s,
                "zona": K.ZONA_POR_SUCURSAL[s],
                "cantidad": q,
            }
            for c, g, m, s, q in filas
        ]
    )


class TestZonaYListaDePrecio:
    """The two VLOOKUP-equivalent columns of AX."""

    def test_cada_sucursal_del_libro_tiene_zona(self):
        """suc!Q:R covers every branch label the sales query can emit."""
        assert set(K.ZONA_POR_SUCURSAL.values()) == {
            "SALTA Y VALLE",
            "SALTA INTERIOR",
            "QUEBRADA",
            "RAMAL",
        }

    def test_valle_salta_comparte_zona_con_casa_central(self):
        """The virtual branch scores inside SALTA Y VALLE, like the workbook had it."""
        df = agregar_zona(pd.DataFrame({"sucursal": ["VALLE SALTA", "1 - CASA CENTRAL"]}))
        assert df["zona"].tolist() == ["SALTA Y VALLE", "SALTA Y VALLE"]

    def test_sucursal_desconocida_queda_sin_zona(self):
        """An unmapped branch yields NaN so the service can warn instead of guessing."""
        df = agregar_zona(pd.DataFrame({"sucursal": ["99 - SUCURSAL NUEVA"]}))
        assert pd.isna(df["zona"].iloc[0])

    def test_lista_de_precio_se_resuelve_por_id(self):
        """gold has no price-list names, so the id is mapped from the pinned table."""
        df = agregar_lista_precio(pd.DataFrame({"id_lista_precio": [1, 7, 999]}))
        assert df["lista_precio"].tolist()[:2] == [
            "LISTA SALTA MAYORISTA",
            "INTERIOR MINORISTA",
        ]

    def test_lista_desconocida_queda_en_blanco(self):
        """An unknown id is left empty: a wrong label would skew the wholesale share."""
        df = agregar_lista_precio(pd.DataFrame({"id_lista_precio": [999]}))
        assert pd.isna(df["lista_precio"].iloc[0])

    def test_mayorista_esta_en_la_tabla_de_listas(self):
        """ramal/qbrd/inte match on these literals; losing one zeroes the mix."""
        nombres = set(K.LISTAS_DE_PRECIO.values())
        assert {"LISTA SALTA MAYORISTA", "INTERIOR MAYORISTA"} <= nombres


class TestPivotMarcas:
    """The A3:F block — what pivotTable1 used to produce."""

    def test_agrupa_por_las_cinco_claves_del_pivot(self):
        """Two lines of the same brand and client collapse into one row."""
        ventas = _ventas(
            [
                (1, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", 3),
                (1, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", 2),
            ]
        )
        pivot = construir_pivot_marcas(ventas)
        assert len(pivot) == 1
        assert pivot["cantidad"].iloc[0] == 5

    def test_no_redondea_las_cantidades(self):
        """Quantities are fractional (0,0417 = one bottle of a 24-pack)."""
        ventas = _ventas([(1, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", 0.0417)])
        assert construir_pivot_marcas(ventas)["cantidad"].iloc[0] == pytest.approx(0.0417)

    def test_separa_marcas_del_mismo_generico(self):
        ventas = _ventas(
            [
                (1, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", 3),
                (1, "CERVEZAS", "SCHNEIDER", "1 - CASA CENTRAL", 1),
            ]
        )
        assert len(construir_pivot_marcas(ventas)) == 2


class TestConteoDeMarcasPorPdv:
    """The N/O/P block — COUNTIFS(..., F:F, ">0")."""

    def test_cuenta_una_marca_por_fila_con_neto_positivo(self):
        ventas = _ventas(
            [
                (1, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", 3),
                (1, "CERVEZAS", "SCHNEIDER", "1 - CASA CENTRAL", 1),
                (1, "AGUAS DANONE", "LEVITE", "1 - CASA CENTRAL", 2),
            ]
        )
        _, conteo = calcular_marcas_x_pdv(ventas)
        fila = conteo.iloc[0]
        assert fila["CERVEZAS"] == 2
        assert fila["AGUAS DANONE"] == 1
        assert fila["VINOS CCU"] == 0

    def test_una_marca_que_neteo_en_cero_no_cuenta(self):
        """Bought and fully returned inside the window: the brand is not covered."""
        ventas = _ventas(
            [
                (1, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", 5),
                (1, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", -5),
                (1, "CERVEZAS", "SCHNEIDER", "1 - CASA CENTRAL", 1),
            ]
        )
        _, conteo = calcular_marcas_x_pdv(ventas)
        assert conteo.iloc[0]["CERVEZAS"] == 1

    def test_neto_negativo_no_cuenta(self):
        ventas = _ventas([(1, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", -2)])
        _, conteo = calcular_marcas_x_pdv(ventas)
        assert conteo.iloc[0]["CERVEZAS"] == 0

    def test_un_cliente_por_fila(self):
        """The J:L block is deduplicated: one row per point of sale."""
        ventas = _ventas(
            [
                (1, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", 3),
                (1, "AGUAS DANONE", "LEVITE", "1 - CASA CENTRAL", 2),
                (2, "CERVEZAS", "SALTA", "6 - SUCURSAL ORAN", 1),
            ]
        )
        _, conteo = calcular_marcas_x_pdv(ventas)
        assert conteo["id_cliente"].tolist() == [1, 2]
        assert conteo["zona"].tolist() == ["SALTA Y VALLE", "RAMAL"]

    def test_el_conteo_queda_alineado_con_la_lista_de_clientes(self):
        """N/O/P are read row-by-row against J:L; a shifted join would corrupt every average."""
        ventas = _ventas(
            [
                (7, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", 1),
                (3, "AGUAS DANONE", "LEVITE", "6 - SUCURSAL ORAN", 1),
                (5, "VINOS CCU", "QUARA", "9 - SUCURSAL PERICO", 1),
            ]
        )
        pivot = construir_pivot_marcas(ventas)
        clientes = construir_clientes(pivot)
        conteo = contar_marcas_por_pdv(pivot, clientes)
        assert conteo["id_cliente"].tolist() == clientes["id_cliente"].tolist()
        assert conteo.loc[conteo.id_cliente == 7, "CERVEZAS"].iloc[0] == 1
        assert conteo.loc[conteo.id_cliente == 3, "AGUAS DANONE"].iloc[0] == 1
        assert conteo.loc[conteo.id_cliente == 5, "VINOS CCU"].iloc[0] == 1

    def test_promedio_por_zona_ignora_los_pdv_sin_el_generico(self):
        """Reproduces T = SUMIFS(N)/COUNTIFS(N,">0"): the divisor skips zeroes."""
        ventas = _ventas(
            [
                (1, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", 1),
                (1, "CERVEZAS", "SCHNEIDER", "1 - CASA CENTRAL", 1),
                (2, "CERVEZAS", "SALTA", "1 - CASA CENTRAL", 1),
                (3, "AGUAS DANONE", "LEVITE", "1 - CASA CENTRAL", 1),
            ]
        )
        _, conteo = calcular_marcas_x_pdv(ventas)
        cervezas = conteo["CERVEZAS"]
        # Client 3 bought no beer at all, so it is out of the average: (2+1)/2.
        assert cervezas.sum() / (cervezas > 0).sum() == pytest.approx(1.5)


class TestPrepararCobertura:
    """Coverage sheets carry a 0-based index in Column1."""

    def test_agrega_indice_desde_cero(self):
        df = pd.DataFrame(
            {"sucursal": ["1 - CASA CENTRAL"] * 3, "concepto": ["A", "B", "C"], "clientes": [1, 2, 3]}
        )
        out = preparar_cobertura(df, concepto="marca")
        assert out["orden"].tolist() == [0, 1, 2]
        assert "marca" in out.columns

    def test_no_toca_el_conteo_de_clientes(self):
        df = pd.DataFrame({"concepto": ["A"], "clientes": [42]})
        assert preparar_cobertura(df, concepto="marca")["clientes"].iloc[0] == 42


class TestPlanDeColumnasAX:
    """The AX column plan is what decides which fields survive the reload."""

    def test_cubre_las_31_columnas_de_la_tabla(self):
        assert len(K.AX_COLUMNS) == 31
        assert K.AX_COLUMNS[-1].letter == "AE"

    def test_las_columnas_que_alguien_lee_traen_datos(self):
        """C, D, F, M, P, T, V, W, AC hold values; AD and AE hold formulas."""
        con_datos = {c.letter for c in K.AX_COLUMNS if c.kind == xb.VALUE}
        assert con_datos == {"C", "D", "F", "M", "P", "T", "V", "W", "AC"}

    def test_zona_y_colon_dulce_siguen_siendo_formulas(self):
        formulas = {c.letter: c.formula for c in K.AX_COLUMNS if c.kind == xb.FORMULA}
        assert set(formulas) == {"AD", "AE"}
        assert "suc!Q:R" in formulas["AD"]
        assert "art_colon_dulce!A:C" in formulas["AE"]

    def test_el_resto_queda_en_blanco(self):
        en_blanco = {c.letter for c in K.AX_COLUMNS if c.kind == xb.BLANK}
        assert len(en_blanco) == 20
        assert "Q" in en_blanco  # Precio
        assert "X" in en_blanco  # Supervisor


class TestSharedStrings:
    """Text is interned so 150k rows do not carry duplicated strings."""

    def test_reusa_una_entrada_existente(self):
        tabla = xb.SharedStrings(
            '<?xml version="1.0"?><sst count="1" uniqueCount="1">'
            "<si><t>CERVEZAS</t></si></sst>"
        )
        assert tabla.intern("CERVEZAS") == 0
        assert tabla.dirty is False

    def test_agrega_las_nuevas_al_final(self):
        tabla = xb.SharedStrings("<sst><si><t>CERVEZAS</t></si></sst>")
        assert tabla.intern("AGUAS DANONE") == 1
        assert tabla.intern("AGUAS DANONE") == 1
        assert tabla.dirty is True

    def test_escapa_el_xml(self):
        tabla = xb.SharedStrings(None)
        tabla.intern("A & B")
        assert b"A &amp; B" in tabla.to_xml()

    def test_los_indices_originales_no_se_mueven(self):
        """Cells already pointing at the table must keep resolving to the same text."""
        tabla = xb.SharedStrings(
            "<sst><si><t>UNO</t></si><si><t>DOS</t></si><si><t>TRES</t></si></sst>"
        )
        tabla.intern("CUATRO")
        assert tabla.intern("DOS") == 1
        assert b"<si><t>TRES</t></si>" in tabla.to_xml()


class TestPatchBlocks:
    """Blocks must land in place without disturbing their neighbours."""

    HOJA = (
        '<?xml version="1.0"?><worksheet><dimension ref="A1:V100"/><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="R1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2"><v>10</v></c><c r="R2"><f>SUM(A:A)</f><v>99</v></c></row>'
        '<row r="3"><c r="A3"><v>11</v></c></row>'
        '<row r="4"><c r="A4"><v>12</v></c></row>'
        "</sheetData></worksheet>"
    )

    def _bloque(self, valores, clear_through=None):
        return xb.Block(
            first_row=2,
            columns=[xb.ColumnSpec("A", xb.VALUE, source="v")],
            data=pd.DataFrame({"v": valores}),
            clear_through=clear_through,
        )

    def test_escribe_el_bloque(self):
        salida = xb.patch_blocks(self.HOJA, [self._bloque([7, 8])]).decode()
        assert '<c r="A2"><v>7</v></c>' in salida
        assert '<c r="A3"><v>8</v></c>' in salida

    def test_conserva_las_celdas_vecinas(self):
        """R2 holds a formula the report reads; the block must not evict it."""
        salida = xb.patch_blocks(self.HOJA, [self._bloque([7, 8])]).decode()
        assert "<f>SUM(A:A)</f>" in salida
        assert '<c r="R1" t="s"><v>1</v></c>' in salida

    def test_borra_las_filas_colgadas(self):
        """A shorter reload must prune the previous run's leftovers."""
        salida = xb.patch_blocks(self.HOJA, [self._bloque([7], clear_through=4)]).decode()
        assert '<c r="A2"><v>7</v></c>' in salida
        assert '<c r="A3"' not in salida
        assert '<c r="A4"' not in salida

    def test_la_dimension_abarca_las_columnas_que_sobreviven(self):
        """A dimension stopping at the block would hide R:V from every reader."""
        salida = xb.patch_blocks(self.HOJA, [self._bloque([7, 8])]).decode()
        assert '<dimension ref="A1:R4"/>' in salida


class TestResizeTable:
    """The table ref is what stretches a table's formula columns to the last row."""

    TABLA = (
        '<table ref="A1:AE147591" totalsRowShown="0">'
        '<autoFilter ref="A1:AE147591"/></table>'
    )

    def test_mueve_ref_y_autofilter(self):
        salida = xb.resize_table(self.TABLA, 100)
        assert 'ref="A1:AE100"' in salida
        assert '<autoFilter ref="A1:AE100"/>' in salida

    def test_conserva_la_ultima_columna(self):
        assert "AE" in xb.resize_table(self.TABLA, 5)


class TestForceFullRecalc:
    """Formula cells are written without a cached value, so a recalc is mandatory."""

    def test_agrega_el_flag(self):
        salida = xb.force_full_recalc('<workbook><calcPr calcId="144525"/></workbook>')
        assert 'fullCalcOnLoad="1"' in salida

    def test_es_idempotente(self):
        una = xb.force_full_recalc('<workbook><calcPr calcId="1"/></workbook>')
        assert xb.force_full_recalc(una).count("fullCalcOnLoad") == 1

    def test_lo_crea_si_no_existe(self):
        salida = xb.force_full_recalc("<workbook><sheets/></workbook>")
        assert 'fullCalcOnLoad="1"' in salida


class TestRefreshPivotCaches:
    """Pivots sitting on reloaded sheets must re-read them when the file opens."""

    def test_agrega_refresh_on_load(self):
        salida = xb.refresh_pivot_caches_on_load(
            '<pivotCacheDefinition recordCount="5"><cacheSource/></pivotCacheDefinition>'
        )
        assert 'refreshOnLoad="1"' in salida

    def test_es_idempotente(self):
        xml = '<pivotCacheDefinition refreshOnLoad="1"><cacheSource/></pivotCacheDefinition>'
        assert xb.refresh_pivot_caches_on_load(xml).count("refreshOnLoad") == 1


class TestEditWorkbook:
    """The zip driver must leave untouched parts byte-identical."""

    @pytest.fixture
    def libro(self, tmp_path):
        ruta = tmp_path / "origen.xlsx"
        with zipfile.ZipFile(ruta, "w") as z:
            z.writestr("a.xml", "<a/>")
            z.writestr("b.xml", "<b/>")
            z.writestr("c.xml", "<c/>")
        return ruta

    def test_reemplaza_solo_lo_indicado(self, libro, tmp_path):
        destino = tmp_path / "destino.xlsx"
        xb.edit_workbook(str(libro), str(destino), {"b.xml": b"<b2/>"})
        with zipfile.ZipFile(destino) as z:
            assert z.read("a.xml") == b"<a/>"
            assert z.read("b.xml") == b"<b2/>"
            assert z.read("c.xml") == b"<c/>"

    def test_descarta_las_partes_pedidas(self, libro, tmp_path):
        destino = tmp_path / "destino.xlsx"
        xb.edit_workbook(str(libro), str(destino), {}, drop={"c.xml"})
        with zipfile.ZipFile(destino) as z:
            assert set(z.namelist()) == {"a.xml", "b.xml"}

    def test_no_toca_el_origen(self, libro, tmp_path):
        antes = libro.read_bytes()
        xb.edit_workbook(str(libro), str(tmp_path / "destino.xlsx"), {"a.xml": b"<z/>"})
        assert libro.read_bytes() == antes


class TestReferenciaMa:
    """The five blocks of `referencia ma` — each branch's share of its zone."""

    SUCURSALES = [
        "3 - SUCURSAL CAFAYATE",
        "5 - SUCURSAL METAN",
        "6 - SUCURSAL ORAN",
    ]
    ZONAS = {
        "3 - SUCURSAL CAFAYATE": "SALTA INTERIOR",
        "5 - SUCURSAL METAN": "SALTA INTERIOR",
        "6 - SUCURSAL ORAN": "RAMAL",
    }

    def _cober_gen(self, filas):
        # Columns are declared even when empty: a query returning no rows still
        # has them, and the builder groups by name.
        return pd.DataFrame(
            [{"sucursal": s, "generico": g, "clientes": c} for s, g, c in filas],
            columns=["sucursal", "generico", "clientes"],
        )

    def _ventas(self, filas):
        return pd.DataFrame(
            [
                {"sucursal": s, "generico": g, "cantidad": q, "lista_precio": l}
                for s, g, q, l in filas
            ]
        )

    def test_la_participacion_se_calcula_sobre_la_zona(self):
        from src.services.variable_mensual.processor import construir_referencia_cobertura

        out = construir_referencia_cobertura(
            cober_gen=self._cober_gen(
                [("3 - SUCURSAL CAFAYATE", "CERVEZAS", 300),
                 ("5 - SUCURSAL METAN", "CERVEZAS", 700),
                 ("6 - SUCURSAL ORAN", "CERVEZAS", 50)]
            ),
            conteo=pd.DataFrame(columns=["sucursal", "CERVEZAS"]),
            sucursales=self.SUCURSALES,
            genericos=["CERVEZAS"],
            zona_por_sucursal=self.ZONAS,
            genericos_mxpdv=["CERVEZAS"],
        )
        interior = out[out.zona == "SALTA INTERIOR"]
        assert interior["total_zona"].tolist() == [1000, 1000]
        assert interior["participacion"].tolist() == [0.3, 0.7]
        # ORAN is alone in RAMAL, so it is the whole zone.
        assert out.loc[out.sucursal == "6 - SUCURSAL ORAN", "participacion"].iloc[0] == 1.0

    def test_las_participaciones_de_una_zona_suman_uno(self):
        from src.services.variable_mensual.processor import construir_referencia_cobertura

        out = construir_referencia_cobertura(
            cober_gen=self._cober_gen(
                [("3 - SUCURSAL CAFAYATE", "CERVEZAS", 379),
                 ("5 - SUCURSAL METAN", "CERVEZAS", 509)]
            ),
            conteo=pd.DataFrame(columns=["sucursal", "CERVEZAS"]),
            sucursales=self.SUCURSALES,
            genericos=["CERVEZAS"],
            zona_por_sucursal=self.ZONAS,
            genericos_mxpdv=["CERVEZAS"],
        )
        interior = out[out.zona == "SALTA INTERIOR"]
        assert interior["participacion"].sum() == pytest.approx(1.0)

    def test_una_sucursal_sin_ventas_queda_en_cero_no_desaparece(self):
        """Dropping the row would shift every row below and repoint the reports."""
        from src.services.variable_mensual.processor import construir_referencia_cobertura

        out = construir_referencia_cobertura(
            cober_gen=self._cober_gen([("3 - SUCURSAL CAFAYATE", "CERVEZAS", 300)]),
            conteo=pd.DataFrame(columns=["sucursal", "CERVEZAS"]),
            sucursales=self.SUCURSALES,
            genericos=["CERVEZAS"],
            zona_por_sucursal=self.ZONAS,
            genericos_mxpdv=["CERVEZAS"],
        )
        assert out["sucursal"].tolist() == self.SUCURSALES
        assert out.loc[out.sucursal == "5 - SUCURSAL METAN", "valor"].iloc[0] == 0

    def test_zona_sin_cobertura_no_rompe_la_division(self):
        from src.services.variable_mensual.processor import construir_referencia_cobertura

        out = construir_referencia_cobertura(
            cober_gen=self._cober_gen([]),
            conteo=pd.DataFrame(columns=["sucursal", "CERVEZAS"]),
            sucursales=self.SUCURSALES,
            genericos=["CERVEZAS"],
            zona_por_sucursal=self.ZONAS,
            genericos_mxpdv=["CERVEZAS"],
        )
        assert out["participacion"].tolist() == [0.0, 0.0, 0.0]

    def test_el_volumen_va_en_bultos(self):
        """Verified against the pasted values: units, never hectolitres."""
        from src.services.variable_mensual.processor import construir_referencia_volumen

        out = construir_referencia_volumen(
            ventas=self._ventas(
                [("3 - SUCURSAL CAFAYATE", "CERVEZAS", 5097.6583, "INTERIOR MINORISTA"),
                 ("5 - SUCURSAL METAN", "CERVEZAS", 1512.1566, "INTERIOR MAYORISTA")]
            ),
            sucursales=self.SUCURSALES,
            genericos=["CERVEZAS"],
            zona_por_sucursal=self.ZONAS,
        )
        cafayate = out[out.sucursal == "3 - SUCURSAL CAFAYATE"].iloc[0]
        assert cafayate["valor"] == pytest.approx(5097.6583)
        assert cafayate["total_zona"] == pytest.approx(6609.8149)

    def test_la_marca_se_busca_por_su_nombre_en_gold_no_por_la_etiqueta(self):
        """The sheet writes "Imperial"; gold stores IMPERIAL."""
        from src.services.variable_mensual.processor import construir_referencia_marca

        out = construir_referencia_marca(
            cober_marca=pd.DataFrame(
                [{"sucursal": "3 - SUCURSAL CAFAYATE", "marca": "IMPERIAL", "clientes": 191}]
            ),
            sucursales=self.SUCURSALES,
            marcas={"Imperial": "IMPERIAL"},
            zona_por_sucursal=self.ZONAS,
        )
        fila = out[out.sucursal == "3 - SUCURSAL CAFAYATE"].iloc[0]
        assert fila["marca"] == "Imperial"
        assert fila["valor"] == 191

    def test_colon_dulce_conserva_el_orden_de_sucursales(self):
        from src.services.variable_mensual.processor import construir_referencia_colon

        out = construir_referencia_colon(
            cobertura_colon=pd.DataFrame(
                [{"sucursal": "5 - SUCURSAL METAN", "clientes": 212}]
            ),
            sucursales=self.SUCURSALES,
            zona_por_sucursal=self.ZONAS,
            etiqueta="COLON DULCE",
        )
        assert out["sucursal"].tolist() == self.SUCURSALES
        assert out["marca"].unique().tolist() == ["COLON DULCE"]
        assert out.loc[out.sucursal == "3 - SUCURSAL CAFAYATE", "valor"].iloc[0] == 0

    def test_los_tres_ratios_del_bloque_mayorista(self):
        """AL divides by the zone's WHOLESALE volume, not by its total volume."""
        from src.services.variable_mensual.processor import construir_referencia_mayorista

        out = construir_referencia_mayorista(
            ventas=self._ventas(
                [("3 - SUCURSAL CAFAYATE", "CERVEZAS", 60.0, "INTERIOR MAYORISTA"),
                 ("3 - SUCURSAL CAFAYATE", "CERVEZAS", 40.0, "INTERIOR MINORISTA"),
                 ("5 - SUCURSAL METAN", "CERVEZAS", 20.0, "INTERIOR MAYORISTA"),
                 ("5 - SUCURSAL METAN", "CERVEZAS", 80.0, "INTERIOR MINORISTA")]
            ),
            sucursales=self.SUCURSALES,
            genericos=["CERVEZAS"],
            zona_por_sucursal=self.ZONAS,
            listas_mayoristas=["INTERIOR MAYORISTA"],
        )
        cafayate = out[out.sucursal == "3 - SUCURSAL CAFAYATE"].iloc[0]
        assert cafayate["volumen_sucursal"] == 100.0
        assert cafayate["mayorista_sucursal"] == 60.0
        assert cafayate["volumen_zona"] == 200.0
        assert cafayate["mayorista_zona"] == 80.0
        assert cafayate["pct_mayo_zona"] == pytest.approx(0.40)      # 80/200
        assert cafayate["pct_participacion"] == pytest.approx(0.75)  # 60/80
        assert cafayate["pct_mayo_sucursal"] == pytest.approx(0.60)  # 60/100

    def test_sub_distribuidores_no_es_mayorista(self):
        """Confirmed against the pasted values, which excluded it."""
        from src.services.variable_mensual.processor import construir_referencia_mayorista

        out = construir_referencia_mayorista(
            ventas=self._ventas(
                [("3 - SUCURSAL CAFAYATE", "CERVEZAS", 50.0, "SUB DISTRIBUIDORES INTERIOR"),
                 ("3 - SUCURSAL CAFAYATE", "CERVEZAS", 50.0, "INTERIOR MAYORISTA")]
            ),
            sucursales=self.SUCURSALES,
            genericos=["CERVEZAS"],
            zona_por_sucursal=self.ZONAS,
            listas_mayoristas=K.LISTAS_MAYORISTAS,
        )
        assert out.iloc[0]["mayorista_sucursal"] == 50.0

    def test_las_trece_sucursales_excluyen_casa_central(self):
        """The sheet only feeds the interior zone reports."""
        assert len(K.REFERENCIA_SUCURSALES) == 13
        assert "1 - CASA CENTRAL" not in K.REFERENCIA_SUCURSALES
        assert "VALLE SALTA" not in K.REFERENCIA_SUCURSALES
        assert all(s in K.ZONA_POR_SUCURSAL for s in K.REFERENCIA_SUCURSALES)

    def test_las_siete_marcas_foco(self):
        assert len(K.REFERENCIA_MARCAS) == 7
        assert K.REFERENCIA_MARCAS["Imperial"] == "IMPERIAL"


class TestReparacionDeFormulas:
    """The 162 `#REF!` formulas the workbook arrived with.

    Every one is a SUMIFS whose ranges were lost by a past edit. They are
    recoverable because a healthy sibling with the same shape sits next to each.
    """

    def test_repara_la_venta_mayorista_de_suc(self):
        """Three criteria: branch, price list, generic."""
        from src.services.variable_mensual.formulas import reparar_formula

        rota = "+SUMIFS(#REF!,#REF!,suc!$A3,#REF!,suc!$A$1,#REF!,suc!B$2)"
        assert reparar_formula("suc", rota) == (
            "+SUMIFS(AX!$T:$T,AX!$F:$F,suc!$A3,AX!$V:$V,suc!$A$1,AX!$W:$W,suc!B$2)"
        )

    def test_repara_la_venta_total_de_suc(self):
        """Two criteria: branch and generic, with no price-list filter."""
        from src.services.variable_mensual.formulas import reparar_formula

        rota = "+SUMIFS(#REF!,#REF!,suc!$A7,#REF!,suc!B$2)"
        assert reparar_formula("suc", rota) == (
            "+SUMIFS(AX!$T:$T,AX!$F:$F,suc!$A7,AX!$W:$W,suc!B$2)"
        )

    def test_el_cuadro_de_htls_suma_hectolitros_no_bultos(self):
        """Its generic criterion points at row 26; the mix tables point at row 2."""
        from src.services.variable_mensual.formulas import reparar_formula

        rota = "+SUMIFS(#REF!,#REF!,suc!$A28,#REF!,suc!B$26)"
        assert "AX!$AC:$AC" in reparar_formula("suc", rota)
        rota_mix = "+SUMIFS(#REF!,#REF!,suc!$A7,#REF!,suc!B$2)"
        assert "AX!$T:$T" in reparar_formula("suc", rota_mix)

    def test_el_mix_por_sucursal_lee_el_bloque_mayorista_de_referencia_ma(self):
        from src.services.variable_mensual.formulas import reparar_formula

        rota = "+SUMIFS(#REF!,#REF!,inte!AG$2,#REF!,inte!X8)"
        assert reparar_formula("inte", rota) == (
            "+SUMIFS('referencia ma'!$AM:$AM,'referencia ma'!$AD:$AD,"
            "inte!AG$2,'referencia ma'!$AF:$AF,inte!X8)"
        )

    def test_conserva_el_iferror_que_envuelve(self):
        from src.services.variable_mensual.formulas import reparar_formula

        rota = "+IFERROR(SUMIFS(#REF!,#REF!,qbrd!BS$2,#REF!,qbrd!BN18),0)"
        reparada = reparar_formula("qbrd", rota)
        assert reparada.startswith("+IFERROR(SUMIFS('referencia ma'!$AM:$AM")
        assert reparada.endswith(",0)")

    def test_no_toca_una_formula_sana(self):
        from src.services.variable_mensual.formulas import reparar_formula

        sana = "+SUMIFS(AX!$AC:$AC,AX!$F:$F,AG$2,AX!$W:$W,inte!$E4)"
        assert reparar_formula("inte", sana) == sana

    def test_es_idempotente(self):
        """The service runs it on every reload; a second pass must be a no-op."""
        from src.services.variable_mensual.formulas import reparar_formula

        una = reparar_formula("suc", "+SUMIFS(#REF!,#REF!,suc!$A7,#REF!,suc!B$2)")
        assert reparar_formula("suc", una) == una

    def test_deja_intacto_lo_que_no_sabe_reparar(self):
        """Six formulas in `inte` are lookups into a table that no longer exists."""
        from src.services.variable_mensual.formulas import reparar_formula

        rara = "VLOOKUP(CONCATENATE($DT$3,DJ5),#REF!,2,0)"
        assert reparar_formula("inte", rara) == rara

    def test_no_cruza_el_limite_de_una_celda(self):
        """An earlier version used [^,]+ and matched across cells in the raw XML."""
        from src.services.variable_mensual.formulas import reparar_hoja

        xml = (
            "<sheetData><row r=\"7\">"
            '<c r="B7"><f>+SUMIFS(#REF!,#REF!,suc!$A7,#REF!,suc!B$2)</f><v>0</v></c>'
            '<c r="C7"><f>+SUMIFS(#REF!,#REF!,suc!$A7,#REF!,suc!C$2)</f><v>0</v></c>'
            "</row></sheetData>"
        )
        nuevo, reparadas = reparar_hoja("suc", xml)
        assert reparadas == 2
        assert "AX!$W:$W,suc!B$2" in nuevo
        assert "AX!$W:$W,suc!C$2" in nuevo
        assert "#REF!" not in nuevo

    def test_cuenta_solo_las_formulas_rotas_no_los_valores(self):
        from src.services.variable_mensual.formulas import contar_refs_rotas

        xml = (
            '<c r="A1"><f>+SUMIFS(#REF!,#REF!,suc!$A7,#REF!,suc!B$2)</f><v>#REF!</v></c>'
            '<c r="A2"><f>+SUM(A1)</f><v>#REF!</v></c>'
        )
        assert contar_refs_rotas(xml) == 1
