"""Tests del informe de quesos LA HUERTA.

Lo que se fija: que los kilos se conviertan POR ARTICULO antes de agregar, que
la cobertura no se sume entre meses, y que un articulo sin factor se denuncie
en vez de restar kilos en silencio.
"""
from pathlib import Path

import pandas as pd
import pytest

from src.services.quesos.constants import MARCA, MESES_CORTOS
from src.services.quesos.processor import (
    articulos_sin_factor,
    construir_anio,
    leer_factores,
)

FACTORES = {893102: 0.17, 893101: 3.8, 895121: 0.41}


def _ventas(filas):
    """filas: (mes, id_articulo, id_cliente, id_sucursal, bultos)"""
    return pd.DataFrame(
        filas, columns=["mes", "id_articulo", "id_cliente", "id_sucursal", "bultos"]
    )


# --- conversion a kilos -----------------------------------------------------

def test_kg_usa_el_factor_de_cada_articulo():
    """10 fetas de 0,17 y 2 barras de 3,8 no son 12 x un factor promedio."""
    v = _ventas([("2025-01", 893102, 1, 1, 10.0), ("2025-01", 893101, 1, 1, 2.0)])
    t = construir_anio(v, FACTORES, 2025)
    assert t.loc["Bultos", "ene"] == 12.0
    assert t.loc["Kg", "ene"] == pytest.approx(10 * 0.17 + 2 * 3.8)


def test_las_unidades_por_caja_no_entran():
    """`cantidades_total` de estos articulos ya viene en unidades.

    Verificado contra la planilla del proveedor: enero-2025, 370 unidades dan
    74,14 kg. Multiplicando ademas por unidades-por-caja daria 632,63.
    """
    v = _ventas([("2025-01", 893102, 1, 1, 370.0)])
    t = construir_anio(v, {893102: 0.2004}, 2025)
    assert t.loc["Kg", "ene"] == pytest.approx(74.148, abs=0.01)


def test_un_articulo_sin_factor_no_suma_kilos_pero_si_bultos():
    v = _ventas([("2025-01", 999999, 1, 1, 50.0)])
    t = construir_anio(v, FACTORES, 2025)
    assert t.loc["Bultos", "ene"] == 50.0
    assert t.loc["Kg", "ene"] == 0.0


def test_los_articulos_sin_factor_se_denuncian():
    """Si no se avisa, los kilos salen cortos y la fila parece sana."""
    v = _ventas([("2025-01", 893102, 1, 1, 5.0), ("2025-01", 999999, 1, 1, 50.0)])
    assert articulos_sin_factor(v, FACTORES) == [999999]


def test_un_articulo_con_factor_no_se_denuncia():
    v = _ventas([("2025-01", 893102, 1, 1, 5.0)])
    assert articulos_sin_factor(v, FACTORES) == []


# --- cobertura --------------------------------------------------------------

def test_la_cobertura_del_anio_no_es_la_suma_de_los_meses():
    """El mismo cliente en dos meses es UN cliente en el total."""
    v = _ventas([("2025-01", 893102, 7, 1, 5.0), ("2025-02", 893102, 7, 1, 5.0)])
    t = construir_anio(v, FACTORES, 2025)
    assert t.loc["Coberturas", "ene"] == 1
    assert t.loc["Coberturas", "feb"] == 1
    assert t.loc["Coberturas", "TOTAL"] == 1


def test_los_bultos_y_los_kilos_SI_se_suman():
    v = _ventas([("2025-01", 893102, 7, 1, 5.0), ("2025-02", 893102, 7, 1, 5.0)])
    t = construir_anio(v, FACTORES, 2025)
    assert t.loc["Bultos", "TOTAL"] == 10.0
    assert t.loc["Kg", "TOTAL"] == pytest.approx(10 * 0.17)


def test_agrupa_por_cliente_antes_de_filtrar():
    """Compra 5 y devuelve 5 en el mes: neto 0, no es cobertura."""
    v = _ventas([("2025-01", 893102, 7, 1, 5.0), ("2025-01", 893102, 7, 1, -5.0)])
    t = construir_anio(v, FACTORES, 2025)
    assert t.loc["Coberturas", "ene"] == 0


def test_clave_compuesta_de_cliente():
    """id_cliente se reusa entre sucursales."""
    v = _ventas([("2025-01", 893102, 7, 1, 5.0), ("2025-01", 893102, 7, 9, 5.0)])
    t = construir_anio(v, FACTORES, 2025)
    assert t.loc["Coberturas", "ene"] == 2


# --- forma del bloque -------------------------------------------------------

def test_el_bloque_tiene_los_doce_meses_y_el_total():
    t = construir_anio(_ventas([]), FACTORES, 2025)
    assert list(t.columns) == [*MESES_CORTOS, "TOTAL"]
    assert list(t.index) == ["Bultos", "Kg", "Coberturas"]
    assert t.loc["Bultos", "TOTAL"] == 0.0


def test_solo_toma_el_anio_pedido():
    v = _ventas([("2025-05", 893102, 1, 1, 10.0), ("2026-05", 893102, 1, 1, 99.0)])
    assert construir_anio(v, FACTORES, 2025).loc["Bultos", "TOTAL"] == 10.0
    assert construir_anio(v, FACTORES, 2026).loc["Bultos", "TOTAL"] == 99.0


# --- lectura del archivo de factores ---------------------------------------

def test_el_archivo_real_trae_los_factores():
    f = leer_factores("factor_conversion_quesos.xlsx")
    assert len(f) >= 34
    assert f[893101] == pytest.approx(3.8)     # barra
    assert f[893102] == pytest.approx(0.17)    # feta
    # Los tres que faltaban en la hoja 'queso' del avance branca.
    for cod in (895120, 895121, 895122):
        assert cod in f, f"falta {cod}: sin el, los kg de 2026 salen cortos"


def test_sin_archivo_de_factores_rompe_fuerte():
    """Un informe con la columna kg en cero se lee como 'no vendimos'."""
    with pytest.raises(FileNotFoundError, match="factores de quesos"):
        leer_factores("no-existe-quesos.xlsx")


def test_la_marca_es_la_huerta():
    assert MARCA == "LA HUERTA"


def test_el_config_es_valido():
    from src.config.resolver import load_report_config

    cfg = load_report_config(Path("configs/quesos.json"))
    assert cfg.tipo == "quesos"
    assert cfg.reportes[0].filtros.anios_mensual == [2025, 2026]
    assert "Gonzalo Farah" in cfg.reportes[0].enviar_a
