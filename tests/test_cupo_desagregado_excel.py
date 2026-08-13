"""Tests for the cupo-desagregado workbook builder (in-memory, no disk writes)."""
import pytest

from src.services.cupo_desagregado.constants import CATEGORIAS
from src.services.cupo_desagregado.excel_builder import construir_workbook
from src.services.cupo_desagregado.processor import Vendedor


def _vals(**kwargs):
    base = {c: 0.0 for c in CATEGORIAS}
    base.update(kwargs)
    return base


@pytest.fixture
def workbook():
    vendedores = [
        Vendedor("PEREZ JUAN", "CAFAYATE", 3, _vals(SALTA=100.0, CERVEZAS=100.0)),
        Vendedor("GOMEZ ANA", "JVG", 4, _vals(SALTA=40.0, CERVEZAS=40.0)),
    ]
    filas = [
        {"sucursal": "CAFAYATE", "vendedor": "PEREZ JUAN", "codigo": 1, "ruta": "RUTA A",
         "vals": _vals(SALTA=75.0, CERVEZAS=75.0)},
        {"sucursal": "CAFAYATE", "vendedor": "PEREZ JUAN", "codigo": 2, "ruta": "RUTA B",
         "vals": _vals(SALTA=25.0, CERVEZAS=25.0)},
        {"sucursal": "JVG", "vendedor": "GOMEZ ANA", "codigo": 1, "ruta": "VILLA LU-JU",
         "vals": _vals(SALTA=40.0, CERVEZAS=40.0)},
    ]
    return construir_workbook(filas, vendedores)


def _columna(ws, header):
    for cell in ws[1]:
        if cell.value == header:
            return cell.column
    raise AssertionError(f"columna {header!r} no encontrada en {ws.title}")


def _valores(ws, header):
    col = _columna(ws, header)
    return [ws.cell(row=r, column=col).value for r in range(2, ws.max_row + 1)]


class TestEstructura:
    def test_tres_hojas_en_orden(self, workbook):
        assert workbook.sheetnames == ["Cupo Ruta", "Cupo Preventa", "Resumen Sucursal"]

    def test_headers_cupo_ruta(self, workbook):
        ws = workbook["Cupo Ruta"]
        headers = [c.value for c in ws[1]]
        assert headers == ["SUCURSAL", "PREVENTISTA", "CÓDIGO", "RUTA"] + CATEGORIAS


class TestCodigoDeRuta:
    def test_formato_entero_sin_separador(self, workbook):
        # Gotcha: el codigo con formato "#,##0.00" sale como "1,00" y rompe joins.
        ws = workbook["Cupo Ruta"]
        col = _columna(ws, "CÓDIGO")
        formatos = {ws.cell(row=r, column=col).number_format
                    for r in range(2, ws.max_row + 1)
                    if isinstance(ws.cell(row=r, column=col).value, (int, float))}
        assert formatos == {"0"}

    def test_el_codigo_se_repite_entre_sucursales(self, workbook):
        # La clave unica es (SUCURSAL, CÓDIGO): el codigo 1 existe en dos sucursales.
        ws = workbook["Cupo Ruta"]
        codigos = [v for v in _valores(ws, "CÓDIGO") if isinstance(v, (int, float))]
        assert codigos.count(1) == 2


class TestTotales:
    def test_subtotal_por_vendedor(self, workbook):
        ws = workbook["Cupo Ruta"]
        preventistas = _valores(ws, "PREVENTISTA")
        assert "TOTAL PEREZ JUAN" in preventistas
        assert "TOTAL GOMEZ ANA" in preventistas

    def test_subtotal_suma_las_rutas_del_vendedor(self, workbook):
        ws = workbook["Cupo Ruta"]
        col_salta = _columna(ws, "SALTA")
        fila = next(r for r in range(2, ws.max_row + 1)
                    if ws.cell(row=r, column=2).value == "TOTAL PEREZ JUAN")
        assert ws.cell(row=fila, column=col_salta).value == 100.0

    @pytest.mark.parametrize("hoja,col_etiqueta", [
        ("Cupo Ruta", 2), ("Cupo Preventa", 2), ("Resumen Sucursal", 1),
    ])
    def test_toda_hoja_termina_en_total_general(self, workbook, hoja, col_etiqueta):
        ws = workbook[hoja]
        assert ws.cell(row=ws.max_row, column=col_etiqueta).value == "TOTAL GENERAL"

    def test_total_general_suma_todos_los_cupos(self, workbook):
        for hoja in ("Cupo Ruta", "Cupo Preventa", "Resumen Sucursal"):
            ws = workbook[hoja]
            col = _columna(ws, "SALTA")
            assert ws.cell(row=ws.max_row, column=col).value == pytest.approx(140.0)

    def test_total_general_esta_en_negrita(self, workbook):
        ws = workbook["Resumen Sucursal"]
        assert ws.cell(row=ws.max_row, column=1).font.bold is True


class TestResumenSucursal:
    def test_una_fila_por_sucursal(self, workbook):
        ws = workbook["Resumen Sucursal"]
        sucursales = [v for v in _valores(ws, "SUCURSAL") if v != "TOTAL GENERAL"]
        assert sucursales == ["CAFAYATE", "JVG"]
