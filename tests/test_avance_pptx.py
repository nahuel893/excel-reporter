"""Tests for `scripts/avance_pptx.py`.

The fixtures rebuild the shape of the real workbook in miniature: two supervisor
bands, a roll-up band whose members are supervisor codes, and the two
single-line bands (DIRECTA, SUB DISTRIBUIDOR). That shape is what the block
detection has to survive.
"""
import importlib.util
import sys
from pathlib import Path

import openpyxl
import pytest


RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("avance_pptx", RAIZ / "scripts" / "avance_pptx.py")
avance_pptx = importlib.util.module_from_spec(_spec)
# @dataclass resolves annotations through sys.modules, so register before exec.
sys.modules["avance_pptx"] = avance_pptx
_spec.loader.exec_module(avance_pptx)


@pytest.fixture
def hoja_avance():
    """`Avance`-shaped sheet: B=vendedor, C=supervisor."""
    wb = openpyxl.Workbook()
    ws = wb.active
    filas = [
        (7, "Vendedor", "Super"),          # header, must be ignored
        (8, "ANA PEREZ", "GFLORES"),
        (9, "LUIS GOMEZ", "GFLORES"),
        (11, "MARIA RUIZ", "FGUANTAY"),
        (12, "JUAN DIAZ", "FGUANTAY"),
        (14, "DIRECTA", "GFARAH"),         # single-line band
        (15, "SUB DISTRIBUIDOR", "ANOGALES"),
        (17, "GFLORES", "GFARAH"),         # summary band: members are codes
        (18, "FGUANTAY", "GFARAH"),
    ]
    for fila, nombre, codigo in filas:
        ws.cell(fila, 2).value = nombre
        ws.cell(fila, 3).value = codigo
    return ws


class TestDeteccionDeBloques:
    def test_solo_los_supervisores_son_bloques(self, hoja_avance):
        codigos = [b.codigo for b in avance_pptx._bloques(hoja_avance, "B", "C", 20)]
        assert codigos == ["GFLORES", "FGUANTAY"]

    def test_la_banda_de_resumen_no_es_un_bloque(self, hoja_avance):
        """GFARAH agrupa codigos, no vendedores: no puede tener slide propio."""
        codigos = [b.codigo for b in avance_pptx._bloques(hoja_avance, "B", "C", 20)]
        assert "GFARAH" not in codigos

    def test_las_bandas_de_una_sola_linea_no_son_bloques(self, hoja_avance):
        codigos = [b.codigo for b in avance_pptx._bloques(hoja_avance, "B", "C", 20)]
        assert "ANOGALES" not in codigos

    def test_el_bloque_conserva_el_orden_de_la_hoja(self, hoja_avance):
        bloque = avance_pptx._bloques(hoja_avance, "B", "C", 20)[0]
        assert bloque.vendedores == ["ANA PEREZ", "LUIS GOMEZ"]
        assert bloque.filas == {"ANA PEREZ": 8, "LUIS GOMEZ": 9}

    def test_el_encabezado_no_entra_como_vendedor(self, hoja_avance):
        bloques = avance_pptx._bloques(hoja_avance, "B", "C", 20)
        assert all("Vendedor" not in b.vendedores for b in bloques)

    def test_rollup_es_el_codigo_que_agrupa_codigos(self, hoja_avance):
        assert avance_pptx._codigo_rollup(hoja_avance, "B", "C", 20) == "GFARAH"

    def test_otros_son_directa_y_sub_distribuidor(self, hoja_avance):
        sueltos = avance_pptx._otros(hoja_avance, "B", "C", 20, {"GFLORES", "FGUANTAY"})
        assert sueltos == [("DIRECTA", 14), ("SUB DISTRIBUIDOR", 15)]


class TestSumas:
    """Totals are the sum of the rows shown, never a cell of the workbook.

    Two of the workbook's own total rows are stale (see the module docstring),
    so reading them would put a total on the slide that its own rows contradict.
    """

    @pytest.fixture
    def hoja(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        for fila, venta in [(2, 100.5), (3, 200.25), (4, None)]:
            ws.cell(fila, 4).value = venta
        ws.cell(5, 4).value = "#REF!"
        return ws

    def test_suma_ignora_vacios(self, hoja):
        assert avance_pptx._sumar(hoja, [2, 3, 4], "D") == pytest.approx(300.75)

    def test_suma_ignora_errores_de_formula(self, hoja):
        assert avance_pptx._sumar(hoja, [2, 3, 5], "D") == pytest.approx(300.75)

    def test_suma_sin_ningun_numero_es_none(self, hoja):
        assert avance_pptx._sumar(hoja, [4, 5], "D") is None

    def test_la_suma_no_redondea(self, hoja):
        ws = hoja
        ws.cell(6, 4).value = 0.3333333333
        assert avance_pptx._sumar(ws, [6], "D") == 0.3333333333


class TestRatio:
    def test_ratio_normal(self):
        assert avance_pptx._ratio(90, 100) == pytest.approx(0.9)

    def test_denominador_cero_no_rompe(self):
        """DIRECTA no tiene cupo: la celda queda en '-', no en 0 ni en #DIV/0!."""
        assert avance_pptx._ratio(2054.18, 0) is None

    def test_numerador_none(self):
        assert avance_pptx._ratio(None, 100) is None


class TestFormato:
    def test_miles_con_punto_y_decimal_con_coma(self):
        assert avance_pptx._fmt(23340.65, "num") == "23.340,7"

    def test_pdv_sin_decimales(self):
        assert avance_pptx._fmt(1593, "pdv") == "1.593"

    def test_porcentaje_entero(self):
        assert avance_pptx._fmt(0.9695, "pct") == "97%"

    def test_vacio_se_muestra_como_guion(self):
        assert avance_pptx._fmt(None, "num") == "-"

    def test_los_errores_de_formula_no_son_numero(self):
        assert avance_pptx._numero("#DIV/0!") is None
        assert avance_pptx._numero(True) is None
        assert avance_pptx._numero(0) == 0


class TestSemaforo:
    def test_cumplido_va_en_verde(self):
        assert avance_pptx._color_pct(1.04) == avance_pptx.VERDE

    def test_entre_90_y_100_va_en_ambar(self):
        assert avance_pptx._color_pct(0.93) == avance_pptx.AMBAR

    def test_debajo_de_90_va_en_rojo(self):
        assert avance_pptx._color_pct(0.72) == avance_pptx.ROJO

    def test_sin_dato_no_pinta(self):
        assert avance_pptx._color_pct(None) is None


class TestColumnasAditivas:
    """A percentage is a ratio: summing it across rows is meaningless."""

    def test_las_columnas_de_porcentaje_quedan_fuera(self):
        aditivas = set(avance_pptx._cols_aditivas_avance())
        porcentajes = {pct for _n, _v, pct, _f in avance_pptx.AVANCE_CATEGORIAS}
        assert not (aditivas & porcentajes)
        assert avance_pptx.AVANCE_TOTAL[3] not in aditivas

    def test_cobertura_suma_pdv_obj_y_faltan(self):
        aditivas = avance_pptx._cols_aditivas_cobertura()
        for _nombre, pdv, obj, falta, pct in avance_pptx.COBER_GENERICOS:
            assert pdv in aditivas and obj in aditivas and falta in aditivas
            assert pct not in aditivas


class TestDiagnostico:
    def test_detecta_una_fila_de_total_desactualizada(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(2, 4).value = 100.0
        ws.cell(3, 4).value = 50.0
        ws.cell(4, 4).value = 100.0  # total row that forgot row 3
        bloque = avance_pptx.Bloque(codigo="GFLORES",
                                    vendedores=["A", "B"],
                                    filas={"A": 2, "B": 3})
        avisos = avance_pptx._diagnostico(ws, "Avance", bloque, ["D"], 4, "total del bloque")
        assert len(avisos) == 1
        assert "150.00" in avisos[0] and "100.00" in avisos[0]

    def test_no_avisa_cuando_el_total_cierra(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(2, 4).value = 100.0
        ws.cell(3, 4).value = 50.0
        ws.cell(4, 4).value = 150.0
        bloque = avance_pptx.Bloque(codigo="GFLORES",
                                    vendedores=["A", "B"],
                                    filas={"A": 2, "B": 3})
        assert avance_pptx._diagnostico(ws, "Avance", bloque, ["D"], 4, "total") == []


class TestLayoutDeColumnas:
    def test_volumen_muestra_venta_y_porcentaje_por_categoria(self):
        cols = avance_pptx._cols_volumen_avance()
        # 6 categorias x (venta, %) + total cerveza (venta, cupo, %)
        assert len(cols) == len(avance_pptx.AVANCE_CATEGORIAS) * 2 + 3

    def test_cobertura_muestra_cuatro_columnas_por_generico(self):
        cols = avance_pptx._cols_cobertura()
        assert len(cols) == len(avance_pptx.COBER_GENERICOS) * 4

    def test_los_cuatro_genericos_pedidos_estan_y_pernod_no(self):
        nombres = [n for n, *_ in avance_pptx.COBER_GENERICOS]
        assert nombres == ["CERVEZAS", "AGUAS DANONE", "VINOS CCU", "SIDRAS Y LICORES"]
