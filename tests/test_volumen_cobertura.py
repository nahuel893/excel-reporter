"""Tests del informe de volumen y cobertura por sucursal.

Lo que se fija es la aritmetica de la cobertura, que es donde este informe se
puede equivocar sin que se note: que se agrupe por cliente ANTES de filtrar,
que el acumulado no sea la suma de los meses, que si sea aditiva entre
sucursales pero NO entre marcas, y que la clave del cliente sea compuesta.
"""
from pathlib import Path

import pandas as pd
import pytest

from src.services.volumen_cobertura.constants import RUTAS_EXCLUIDAS, etiqueta_mes
from src.services.volumen_cobertura.processor import (
    clientes_cubiertos,
    construir_bloques,
    construir_tabla,
    fila_total,
    matriz_sucursal_marca,
    meses_con_movimiento,
)

COLS = ["id_sucursal", "des_sucursal", "marca", "id_cliente", "mes", "bultos", "hectolitros"]


def _ventas(filas):
    """filas: (id_sucursal, des_sucursal, marca, id_cliente, mes, bultos, hl)"""
    return pd.DataFrame(filas, columns=COLS)


def _padron(filas):
    return pd.DataFrame(filas, columns=["id_sucursal", "padron"])


# --- cobertura: el orden agrupar/filtrar ------------------------------------

def test_agrupa_por_cliente_antes_de_filtrar():
    """Compra 5 y devuelve 5 en el corte: neto 0, no esta cubierto."""
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", -5.0, -0.4),
    ])
    assert clientes_cubiertos(v) == 0


def test_el_mismo_cliente_en_dos_marcas_es_uno_solo():
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (3, "CAFAYATE", "CHIVAS REGAL", 7, "2026-07", 3.0, 0.2),
    ])
    assert clientes_cubiertos(v) == 1


def test_clave_compuesta_de_cliente():
    """id_cliente se reusa entre sucursales: son dos clientes distintos."""
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (5, "METAN", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
    ])
    assert clientes_cubiertos(v) == 2


# --- aditividad -------------------------------------------------------------

def test_el_acumulado_no_es_la_suma_de_los_meses():
    """El mismo cliente en julio y agosto es UN cliente en el acumulado."""
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-08", 5.0, 0.4),
    ])
    t = construir_tabla(v, _padron([(3, 100)]))
    fila = t.iloc[0]
    assert fila["cob_2026-07"] == 1
    assert fila["cob_2026-08"] == 1
    assert fila["cob_acum"] == 1, "sumar los meses daria 2"


def test_los_bultos_y_los_hl_SI_se_suman_entre_meses():
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-08", 5.0, 0.4),
    ])
    fila = construir_tabla(v, _padron([(3, 100)])).iloc[0]
    assert fila["bultos_acum"] == 10.0
    assert fila["hl_acum"] == pytest.approx(0.8)


def test_la_cobertura_SI_es_aditiva_entre_sucursales():
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (5, "METAN", "ABSOLUT", 9, "2026-07", 5.0, 0.4),
    ])
    t = construir_tabla(v, _padron([(3, 100), (5, 50)]))
    total = fila_total(v, _padron([(3, 100), (5, 50)]), "des_sucursal")
    assert t["cob_acum"].sum() == 2
    assert total["cob_acum"] == 2


def test_la_cobertura_NO_es_aditiva_entre_marcas():
    """El mismo cliente compra dos marcas: el total es 1, no 2."""
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (3, "CAFAYATE", "CHIVAS REGAL", 7, "2026-07", 3.0, 0.2),
    ])
    t = construir_tabla(v, pd.DataFrame(), dimension="marca")
    total = fila_total(v, pd.DataFrame(), "marca")
    assert t["cob_acum"].sum() == 2, "cada marca cuenta a su cliente"
    assert total["cob_acum"] == 1, "el total NO puede sumar la columna"


# --- padron -----------------------------------------------------------------

def test_el_peso_sobre_padron_se_guarda_como_fraccion():
    """0.25 con number_format 0.0% se ve 25,0%. Guardar 25 daria 2500%."""
    v = _ventas([(3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4)])
    fila = construir_tabla(v, _padron([(3, 4)])).iloc[0]
    assert fila["pct_padron"] == pytest.approx(0.25)


def test_padron_en_cero_no_rompe():
    v = _ventas([(3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4)])
    fila = construir_tabla(v, _padron([(3, 0)])).iloc[0]
    assert fila["pct_padron"] == 0.0


def test_el_padron_del_total_solo_suma_las_sucursales_con_movimiento():
    v = _ventas([(3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4)])
    total = fila_total(v, _padron([(3, 100), (5, 999)]), "des_sucursal")
    assert total["padron"] == 100


# --- forma de la tabla ------------------------------------------------------

def test_un_mes_sin_movimiento_no_genera_columnas():
    """Tres columnas en cero se leen como un bug, no como 'todavia no existia'."""
    v = _ventas([(3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4)])
    assert meses_con_movimiento(v) == ["2026-07"]
    assert "bultos_2026-06" not in construir_tabla(v, _padron([(3, 100)])).columns


def test_las_sucursales_se_ordenan_por_volumen():
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (5, "METAN", "ABSOLUT", 9, "2026-07", 50.0, 4.0),
    ])
    t = construir_tabla(v, _padron([(3, 100), (5, 100)]))
    assert list(t["des_sucursal"]) == ["METAN", "CAFAYATE"]


def test_sin_ventas_devuelve_tabla_vacia():
    assert construir_tabla(_ventas([]), _padron([])).empty


# --- bloques por sucursal ---------------------------------------------------

def test_un_bloque_por_sucursal_ordenado_por_volumen():
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (5, "METAN", "ABSOLUT", 9, "2026-07", 50.0, 4.0),
    ])
    bloques = construir_bloques(v)
    assert [etiqueta for etiqueta, _, _ in bloques] == ["METAN", "CAFAYATE"]


def test_el_bloque_solo_lista_las_marcas_que_esa_sucursal_vendio():
    """12 sucursales x 20 marcas es casi todo ceros, y los ceros tapan el dato."""
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (5, "METAN", "CHIVAS REGAL", 9, "2026-07", 50.0, 4.0),
    ])
    bloques = {etiqueta: filas for etiqueta, filas, _ in construir_bloques(v)}
    assert list(bloques["CAFAYATE"]["marca"]) == ["ABSOLUT"]
    assert list(bloques["METAN"]["marca"]) == ["CHIVAS REGAL"]


def test_el_subtotal_del_bloque_no_suma_la_cobertura_de_sus_marcas():
    """Un cliente que compra dos marcas es UNO en el subtotal de la sucursal."""
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (3, "CAFAYATE", "CHIVAS REGAL", 7, "2026-07", 3.0, 0.2),
    ])
    _, filas, subtotal = construir_bloques(v)[0]
    assert filas["cob_acum"].sum() == 2
    assert subtotal["cob_acum"] == 1
    assert subtotal["bultos_acum"] == 8.0, "los bultos SI se suman"


def test_el_subtotal_se_etiqueta_con_la_sucursal():
    v = _ventas([(3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4)])
    _, _, subtotal = construir_bloques(v)[0]
    assert subtotal["marca"] == "TOTAL CAFAYATE"


def test_sin_ventas_no_hay_bloques():
    assert construir_bloques(_ventas([])) == []


def test_la_matriz_marca_con_cero_lo_que_no_llego():
    v = _ventas([
        (3, "CAFAYATE", "ABSOLUT", 7, "2026-07", 5.0, 0.4),
        (5, "METAN", "CHIVAS REGAL", 9, "2026-07", 3.0, 0.2),
    ])
    m = matriz_sucursal_marca(v)
    assert m.loc["CAFAYATE", "CHIVAS REGAL"] == 0.0
    assert m.loc["METAN", "CHIVAS REGAL"] == 3.0


# --- criterio ---------------------------------------------------------------

def test_se_excluye_la_ruta_directa_en_todas_las_sucursales():
    """DIRECTA no es un preventista: infla cobertura y padron por igual."""
    assert (None, 100) in RUTAS_EXCLUIDAS


def test_etiqueta_de_mes():
    assert etiqueta_mes("2026-07") == "Jul 26"
    assert etiqueta_mes("2026-12") == "Dic 26"


def test_el_config_de_pernod_es_valido():
    from src.config.resolver import load_report_config

    cfg = load_report_config(Path("configs/pernod_sucursales.json"))
    assert cfg.tipo == "volumen-cobertura"
    assert cfg.filtros.genericos == ["PERNOD RICARD"]
    assert cfg.filtros.sucursales_excluidas == [1]
