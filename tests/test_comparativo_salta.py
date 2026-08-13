"""Tests for the SALTA coverage-by-calibre comparison.

The metric is DISTINCT CLIENTS WITH BULTOS > 0, which is not additive. These
tests pin the two things that are easy to get wrong: the composite client key,
and the brand total being the union of the calibre sets.
"""
import pandas as pd
import pytest

from src.services.comparativo_salta.processor import (
    MARCA_TOTAL,
    asignar_zona,
    calibres_ordenados,
    construir_detalle_clientes,
    construir_resumen,
    contar_cobertura,
)
from src.services.comparativo_salta.service import _periodo_desplazado

_ETIQUETAS = {"actual": "Cob. Jul-2026", "anterior": "Cob. Jun-2026", "mmaa": "Cob. Jul-2025"}


def _df(filas):
    """filas: (id_cliente, id_sucursal, calibre, bultos)."""
    return pd.DataFrame(
        [
            {"id_cliente": c, "id_sucursal": s, "sucursal": "CASA CENTRAL",
             "id_ruta": 1, "preventista": "P", "razon_social": f"CLI {c}",
             "fantasia": "", "calibre": cal, "bultos": b}
            for c, s, cal, b in filas
        ]
    )


# ── conteo ───────────────────────────────────────────────────────────────

def test_cliente_que_compra_dos_calibres_cuenta_una_vez_en_el_total():
    df = _df([(1, 1, "1000CC", 5), (1, 1, "1200CC", 3)])
    assert contar_cobertura(df) == 1
    assert contar_cobertura(df, "1000CC") == 1
    assert contar_cobertura(df, "1200CC") == 1


def test_id_cliente_repetido_en_otra_sucursal_son_clientes_distintos():
    """Regla de oro: la clave es (id_cliente, id_sucursal), nunca el id solo."""
    df = _df([(100, 1, "1000CC", 5), (100, 3, "1000CC", 5)])
    assert contar_cobertura(df) == 2


def test_bultos_cero_o_negativo_no_cuentan():
    df = _df([(1, 1, "1000CC", 0), (2, 1, "1000CC", -4), (3, 1, "1000CC", 1)])
    assert contar_cobertura(df) == 1


def test_total_de_marca_es_la_union_no_el_neto():
    """Un cliente con +2 en 1200 y -2 en 1000 aparece en 1200, entonces en el total.

    Contar por neto lo dejaria afuera del total pero adentro del calibre, que es
    una tabla que se contradice a si misma.
    """
    df = _df([(1, 1, "1200CC", 2), (1, 1, "1000CC", -2)])
    assert contar_cobertura(df, "1200CC") == 1
    assert contar_cobertura(df) == 1


def test_total_nunca_es_menor_que_un_calibre():
    df = _df([(1, 1, "1200CC", 2), (2, 1, "1200CC", 1), (2, 1, "1000CC", -9)])
    total = contar_cobertura(df)
    for cal in ("1000CC", "1200CC"):
        assert total >= contar_cobertura(df, cal)


# ── tabla resumen ────────────────────────────────────────────────────────

def test_resumen_arma_fila_de_marca_y_una_por_calibre():
    actual = _df([(1, 1, "1000CC", 5), (2, 1, "1200CC", 3)])
    r = construir_resumen(actual, actual.iloc[0:0], actual.iloc[0:0], _ETIQUETAS)
    assert r.iloc[0]["Detalle"] == MARCA_TOTAL
    assert set(r["Detalle"][1:]) == {"SALTA 1000", "SALTA 1200"}


def test_resumen_calcula_las_dos_variaciones():
    actual = _df([(1, 1, "1000CC", 5), (2, 1, "1000CC", 5)])
    anterior = _df([(1, 1, "1000CC", 5)])
    mmaa = _df([(1, 1, "1000CC", 5), (2, 1, "1000CC", 5), (3, 1, "1000CC", 5)])
    r = construir_resumen(actual, anterior, mmaa, _ETIQUETAS).iloc[0]
    assert r["Var. mes ant."] == 2 - 1
    assert r["Var. MMAA"] == 2 - 3


def test_calibre_sin_venta_este_mes_sigue_apareciendo():
    """Si 1200 vendio el ano pasado y hoy no, la fila tiene que estar en 0."""
    actual = _df([(1, 1, "1000CC", 5)])
    mmaa = _df([(2, 1, "1200CC", 5)])
    r = construir_resumen(actual, actual.iloc[0:0], mmaa, _ETIQUETAS)
    fila = r[r["Detalle"] == "SALTA 1200"].iloc[0]
    assert fila[_ETIQUETAS["actual"]] == 0
    assert fila[_ETIQUETAS["mmaa"]] == 5 // 5  # 1 cliente


def test_calibres_ordenados_por_cobertura_del_periodo_actual():
    actual = _df([(1, 1, "473CC", 1), (2, 1, "473CC", 1), (3, 1, "1000CC", 1)])
    assert calibres_ordenados(actual) == ["473CC", "1000CC"]


# ── zonas ────────────────────────────────────────────────────────────────

def test_asignar_zona_renombra_por_ruta_sin_perder_filas():
    df = _df([(1, 1, "1000CC", 5), (2, 1, "1000CC", 5)])
    df.loc[0, "id_ruta"] = 81
    zonas = {"VALLE SALTA": {"sucursal_real": "CASA CENTRAL", "rutas": [81]}}
    out = asignar_zona(df, zonas)
    assert len(out) == len(df)  # grano cliente intacto
    assert set(out["sucursal"]) == {"VALLE SALTA", "CASA CENTRAL"}


# ── ventanas de comparacion ──────────────────────────────────────────────

@pytest.mark.parametrize("desde,hasta,meses,esperado", [
    ("2026-07-01", "2026-07-29", 1, ("2026-06-01", "2026-06-29")),
    ("2026-07-01", "2026-07-29", 12, ("2025-07-01", "2025-07-29")),
    # 31 de julio contra junio, que tiene 30: se recorta, no se desborda a julio
    ("2026-07-01", "2026-07-31", 1, ("2026-06-01", "2026-06-30")),
])
def test_periodo_desplazado_mantiene_ventanas_comparables(desde, hasta, meses, esperado):
    assert _periodo_desplazado(desde, hasta, meses=meses) == esperado


# ── detalle por cliente ──────────────────────────────────────────────────

def test_detalle_conserva_al_cliente_que_dejo_de_comprar():
    actual = _df([(1, 1, "1000CC", 5)])
    anterior = _df([(1, 1, "1000CC", 5), (2, 1, "1000CC", 8)])
    d = construir_detalle_clientes(actual, anterior, ["1000CC"])
    assert len(d) == 2
    perdido = d[d["razon_social"] == "CLI 2"].iloc[0]
    assert perdido["1000CC_actual"] == 0
    assert perdido["1000CC_anterior"] == 8


# ── bloques de columnas definidos a mano (incentivo) ─────────────────────

def _df_mes(filas):
    """filas: (id_cliente, preventista, sabor, calibre, bultos)."""
    return pd.DataFrame([
        {"id_cliente": c, "id_sucursal": 1, "sucursal": "CASA CENTRAL",
         "id_ruta": 1, "preventista": pv, "razon_social": f"CLI {c}",
         "fantasia": "", "sabor": s, "calibre": cal, "bultos": b}
        for c, pv, s, cal, b in filas
    ])


def _bloques():
    return [
        {"grupo": "AGO", "sabor": "NEGRA", "calibre": "1000",
         "meses": ["2025-08", "2026-07"], "cupo": 2500},
        {"grupo": "SEP", "sabor": "NEGRA", "calibre": "1000",
         "meses": ["2025-09", "2026-07"], "cupo": 2500},
    ]


def test_mismo_sabor_calibre_en_dos_bloques_no_colisiona():
    """El litro negro se mide en las dos campañas; son columnas distintas."""
    from src.services.comparativo_salta.processor import construir_cobertura_vendedor_bloques
    frames = {
        "2025-08": _df_mes([(1, "PV1", "NEGRA", "1000", 5)]),
        "2025-09": _df_mes([(1, "PV1", "NEGRA", "1000", 5), (2, "PV1", "NEGRA", "1000", 3)]),
        "2026-07": _df_mes([(1, "PV1", "NEGRA", "1000", 5)]),
    }
    r = construir_cobertura_vendedor_bloques(frames, _bloques())
    fila = r[r["Vendedor"] == "PV1"].iloc[0]
    assert fila["b0|2025-08"] == 1     # bloque agosto
    assert fila["b1|2025-09"] == 2     # bloque septiembre, otro mes
    assert fila["b0|2026-07"] == fila["b1|2026-07"] == 1   # julio repetido a propósito


def test_el_cupo_se_reparte_y_el_total_conserva_el_objetivo():
    """El cupo por fila ya no va vacío: se distribuye según la historia.

    El TOTAL sigue mostrando el objetivo íntegro que fijó comercial, no la suma
    de un reparto que podría no cerrar.
    """
    from src.services.comparativo_salta.processor import construir_cobertura_vendedor_bloques
    frames = {m: _df_mes([(1, "PV1", "NEGRA", "1000", 5)])
              for m in ("2025-08", "2025-09", "2026-07")}
    r = construir_cobertura_vendedor_bloques(frames, _bloques())
    vendedor = r[r["Vendedor"] == "PV1"].iloc[0]
    total = r[r["Sucursal"] == "TOTAL GENERAL"].iloc[0]
    assert vendedor["b0|Cupo"] == 2500   # único vendedor, se lleva todo
    assert total["b0|Cupo"] == 2500


def test_el_total_recuenta_no_suma_vendedores():
    """Dos vendedores con el MISMO cliente: el total lo cuenta una sola vez.

    No pasa con la asignación real (un cliente tiene un preventista), pero el
    total tiene que ser un recuento igual: si mañana cambia la asignación, la
    cifra sigue siendo correcta.
    """
    from src.services.comparativo_salta.processor import construir_cobertura_vendedor_bloques
    frames = {m: _df_mes([(1, "PV1", "NEGRA", "1000", 5), (1, "PV2", "NEGRA", "1000", 5)])
              for m in ("2025-08", "2025-09", "2026-07")}
    r = construir_cobertura_vendedor_bloques(frames, _bloques())
    total = r[r["Sucursal"] == "TOTAL GENERAL"].iloc[0]
    assert total["b0|2025-08"] == 1        # un cliente, no dos
    assert r[r["Vendedor"] == "PV1"].iloc[0]["b0|2025-08"] == 1
    assert r[r["Vendedor"] == "PV2"].iloc[0]["b0|2025-08"] == 1


def test_cliente_sin_preventista_entra_como_sin_asignar():
    """Si se pierde, la suma de vendedores deja de cerrar contra el total."""
    from src.services.comparativo_salta.processor import construir_cobertura_vendedor_bloques
    df = _df_mes([(1, None, "NEGRA", "1000", 5)])
    frames = {m: df for m in ("2025-08", "2025-09", "2026-07")}
    r = construir_cobertura_vendedor_bloques(frames, _bloques())
    assert "(sin asignar)" in set(r["Vendedor"])


def test_merge_filters_propaga_los_bloques():
    """Regresión: merge_filters copia clave por clave; olvidar una la deja en None."""
    from src.config.models import GlobalFilters, ReportFilters
    from src.config.resolver import merge_filters

    g = GlobalFilters(fecha_desde="2026-07-01", fecha_hasta="2026-07-29")
    bloques = [{"sabor": "NEGRA", "calibre": "1000", "meses": ["2026-07"], "cupo": 10}]
    m = merge_filters(g, ReportFilters(bloques_vendedor=bloques, id_sucursal_vendedor=1))
    assert m["bloques_vendedor"] == bloques
    assert m["id_sucursal_vendedor"] == 1
    assert merge_filters(g, ReportFilters())["bloques_vendedor"] is None


# ── reparto del cupo ─────────────────────────────────────────────────────

def test_el_reparto_suma_exactamente_el_cupo():
    """Si no cierra, el objetivo global deja de ser el que fijó comercial."""
    from src.services.comparativo_salta.processor import distribuir_cupo
    base = {"A": 74, "B": 33, "C": 70, "D": 52, "E": 47, "F": 1}
    for total in (2500, 3500, 7, 1, 0):
        r = distribuir_cupo(base, total)
        assert sum(r.values()) == total, f"no cierra con total={total}"


def test_el_reparto_es_proporcional_a_la_historia():
    from src.services.comparativo_salta.processor import distribuir_cupo
    r = distribuir_cupo({"A": 100, "B": 50, "C": 50}, 200)
    assert r == {"A": 100, "B": 50, "C": 50}


def test_el_reparto_es_estable_entre_corridas():
    """Mismo input -> mismo output. Un empate no puede moverse de una corrida a otra."""
    from src.services.comparativo_salta.processor import distribuir_cupo
    base = {"C": 10, "A": 10, "B": 10, "D": 10}   # empate total
    assert distribuir_cupo(base, 10) == distribuir_cupo(base, 10)
    assert sum(distribuir_cupo(base, 10).values()) == 10


def test_sin_historia_reparte_parejo():
    """Todos en cero: mejor parejo que dejar el cupo sin asignar."""
    from src.services.comparativo_salta.processor import distribuir_cupo
    r = distribuir_cupo({"A": 0, "B": 0, "C": 0}, 10)
    assert sum(r.values()) == 10
    assert max(r.values()) - min(r.values()) <= 1


def test_el_cupo_repartido_llega_a_cada_fila_y_el_total_queda_entero():
    from src.services.comparativo_salta.processor import construir_cobertura_vendedor_bloques
    frames = {
        "2025-08": _df_mes([(1, "PV1", "NEGRA", "1000", 5), (2, "PV1", "NEGRA", "1000", 5),
                            (3, "PV2", "NEGRA", "1000", 5)]),
        "2025-09": _df_mes([(1, "PV1", "NEGRA", "1000", 5)]),
        "2026-07": _df_mes([(1, "PV1", "NEGRA", "1000", 5)]),
    }
    bloques = [{"grupo": "AGO", "sabor": "NEGRA", "calibre": "1000",
                "meses": ["2025-08", "2026-07"], "cupo": 300}]
    r = construir_cobertura_vendedor_bloques(frames, bloques)
    filas = r[~r["Sucursal"].astype(str).str.startswith("TOTAL")]
    # PV1 tiene 2 de 3 clientes históricos -> 200; PV2 -> 100
    assert dict(zip(filas["Vendedor"], filas["b0|Cupo"])) == {"PV1": 200, "PV2": 100}
    assert filas["b0|Cupo"].sum() == 300
    assert r[r["Sucursal"] == "TOTAL GENERAL"].iloc[0]["b0|Cupo"] == 300
