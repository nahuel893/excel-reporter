"""Tests for `scripts/vinos_danielito.py`.

The report normally has no upper bound: it runs to the last row loaded in the
warehouse. That is right for the standalone run, and wrong when the table goes
into a closed-month deck — a JULIO deck showing three days of AGOSTO reads as a
collapse in sales.

`--hasta` closes the window. It has to reach ALL THREE queries: volume, monthly
coverage and yearly coverage. Capping only the volume one would leave a client
counted in a month whose bultos are not on the same slide.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

_spec = importlib.util.spec_from_file_location(
    "vinos_danielito", RAIZ / "scripts" / "vinos_danielito.py")
danielito = importlib.util.module_from_spec(_spec)
sys.modules["vinos_danielito"] = danielito
_spec.loader.exec_module(danielito)


class LoaderFalso:
    """Guarda las consultas y devuelve un DataFrame vacio con las columnas justas."""

    COLUMNAS = {
        "cantidad": ["anio", "nm", "id_articulo", "cantidad"],
        "des_articulo": ["id_articulo", "des_articulo"],
        "clientes": ["anio", "nm", "clientes"],
    }

    def __init__(self):
        self.consultas = []

    def execute_query(self, sql):
        self.consultas.append(sql)
        for clave, columnas in self.COLUMNAS.items():
            if clave in sql:
                if clave == "clientes" and "nm" not in sql.split("SELECT anio")[-1]:
                    return pd.DataFrame(columns=["anio", "clientes"])
                return pd.DataFrame(columns=columnas)
        return pd.DataFrame()


@pytest.fixture
def loader():
    return LoaderFalso()


class TestTopeDeVentana:
    def test_sin_hasta_ninguna_consulta_tiene_tope(self, loader):
        danielito._cargar(loader)
        assert not any("<=" in sql for sql in loader.consultas)

    def test_el_tope_llega_a_las_tres_consultas_de_ventas(self, loader):
        danielito._cargar(loader, hasta="2026-07-31")
        con_fecha = [sql for sql in loader.consultas if "fact_ventas" in sql]
        assert len(con_fecha) == 3
        assert all("fecha_comprobante <= '2026-07-31'" in sql for sql in con_fecha)

    def test_el_tope_no_toca_la_consulta_de_articulos(self, loader):
        """`dim_articulo` no tiene fecha: meterle el tope la romperia."""
        danielito._cargar(loader, hasta="2026-07-31")
        articulos = [sql for sql in loader.consultas if "dim_articulo" in sql]
        assert articulos and all("fecha_comprobante" not in sql for sql in articulos)

    def test_el_piso_sigue_estando(self, loader):
        danielito._cargar(loader, hasta="2026-07-31")
        ventas = [sql for sql in loader.consultas if "fact_ventas" in sql]
        assert all(f"fecha_comprobante >= '{danielito.DESDE}'" in sql for sql in ventas)
