"""Tests for the cobertura-aguas processor.

The whole point of this report is the coverage criterion, so that is what the
tests pin down: group by client BEFORE filtering, composite client key, and the
fact that a group of marcas is the UNION of its marcas and never the sum.
"""
from unittest.mock import patch

import pandas as pd
import pytest

from src.core.data_loader import DataLoader
from src.services.cobertura_aguas import (
    CoberturaAguasConfig,
    CoberturaAguasService,
)
from src.services.cobertura_aguas.constants import (
    CONCEPTOS,
    MARCAS_AGUAS,
    MARCAS_MINERAL,
    MARCAS_SABORIZADA,
    TOTAL_AGUAS,
)
from src.services.cobertura_aguas.processor import (
    clientes_con_compra,
    construir_tabla,
)

MESES = ["2026-07", "2026-08"]


def _ventas(filas):
    """filas: (id_sucursal, marca, id_cliente, mes, cantidad)"""
    return pd.DataFrame(
        filas, columns=["id_sucursal", "marca", "id_cliente", "mes", "cantidad"]
    )


def _padron(filas):
    """filas: (id_sucursal, des_sucursal, padron)"""
    return pd.DataFrame(filas, columns=["id_sucursal", "des_sucursal", "padron"])


# --- clientes_con_compra ----------------------------------------------------

def test_agrupa_antes_de_filtrar_devolucion_total_no_cuenta():
    """Compra 5 y devuelve 5 en el mismo corte: neto 0, NO es cobertura.

    Filtrar linea por linea contaria la compra e ignoraria la devolucion.
    """
    df = _ventas([
        (1, "LEVITE", 100, "2026-07", 5.0),
        (1, "LEVITE", 100, "2026-07", -5.0),
    ])
    assert clientes_con_compra(df) == 0


def test_agrupa_antes_de_filtrar_compras_chicas_suman():
    """Dos compras de 0.2 y 0.3 son un cliente cubierto: el neto es 0.5 > 0."""
    df = _ventas([
        (1, "LEVITE", 100, "2026-07", 0.2),
        (1, "LEVITE", 100, "2026-07", 0.3),
    ])
    assert clientes_con_compra(df) == 1


def test_umbral_por_defecto_es_mayor_a_cero():
    df = _ventas([(1, "LEVITE", 100, "2026-07", 0.01)])
    assert clientes_con_compra(df) == 1


def test_umbral_explicito_no_se_hereda_del_default():
    df = _ventas([(1, "LEVITE", 100, "2026-07", 0.4)])
    assert clientes_con_compra(df) == 1
    assert clientes_con_compra(df, umbral=0.5) == 0


def test_clave_compuesta_mismo_id_en_dos_sucursales_son_dos_clientes():
    """id_cliente se REUSA entre sucursales: la clave es (id_cliente, id_sucursal)."""
    df = _ventas([
        (1, "LEVITE", 100, "2026-07", 3.0),
        (9, "LEVITE", 100, "2026-07", 3.0),
    ])
    assert clientes_con_compra(df) == 2


def test_un_cliente_dos_marcas_cuenta_una_sola_vez():
    df = _ventas([
        (1, "LEVITE", 100, "2026-07", 3.0),
        (1, "BRIO", 100, "2026-07", 3.0),
    ])
    assert clientes_con_compra(df) == 1


# --- construir_tabla --------------------------------------------------------

def test_grupo_es_union_no_suma():
    """AGUA SABORIZADA con el mismo cliente en LEVITE y BRIO es 1, no 2."""
    ventas = _ventas([
        (1, "LEVITE", 100, "2026-07", 3.0),
        (1, "BRIO", 100, "2026-07", 3.0),
    ])
    t = construir_tabla(ventas, _padron([(1, "CASA CENTRAL", 10)]), MESES)
    fila = t[(t.id_sucursal == 1) & (t.fila == "AGUA SABORIZADA")].iloc[0]
    assert fila["cob_acum"] == 1
    levite = t[(t.id_sucursal == 1) & (t.fila == "LEVITE")].iloc[0]
    brio = t[(t.id_sucursal == 1) & (t.fila == "BRIO")].iloc[0]
    assert levite["cob_acum"] == 1 and brio["cob_acum"] == 1
    # La suma de las marcas daria 2 — por eso el grupo NO se suma.
    assert fila["cob_acum"] != levite["cob_acum"] + brio["cob_acum"]


def test_acumulado_no_es_la_suma_de_los_meses():
    """El mismo cliente compra los dos meses: mensual 1 y 1, acumulado 1."""
    ventas = _ventas([
        (1, "LEVITE", 100, "2026-07", 3.0),
        (1, "LEVITE", 100, "2026-08", 3.0),
    ])
    t = construir_tabla(ventas, _padron([(1, "CASA CENTRAL", 10)]), MESES)
    fila = t[(t.id_sucursal == 1) & (t.fila == "LEVITE")].iloc[0]
    assert fila["cob_2026-07"] == 1
    assert fila["cob_2026-08"] == 1
    assert fila["cob_acum"] == 1


def test_acumulado_totaliza_dentro_del_corte_completo():
    """Compra 5 en julio y devuelve 5 en agosto: cubierto en julio, no acumulado.

    El corte manda: en el acumulado el neto de los dos meses es 0.
    """
    ventas = _ventas([
        (1, "LEVITE", 100, "2026-07", 5.0),
        (1, "LEVITE", 100, "2026-08", -5.0),
    ])
    t = construir_tabla(ventas, _padron([(1, "CASA CENTRAL", 10)]), MESES)
    fila = t[(t.id_sucursal == 1) & (t.fila == "LEVITE")].iloc[0]
    assert fila["cob_2026-07"] == 1
    assert fila["cob_2026-08"] == 0
    assert fila["cob_acum"] == 0


def test_total_aguas_incluye_full_sport_pero_ningun_grupo_lo_hace():
    """FULL SPORT es aguas, pero no es mineral ni saborizada."""
    ventas = _ventas([(1, "FULL SPORT", 100, "2026-07", 3.0)])
    t = construir_tabla(ventas, _padron([(1, "CASA CENTRAL", 10)]), MESES)
    por_fila = t[t.id_sucursal == 1].set_index("fila")["cob_acum"]
    assert por_fila[TOTAL_AGUAS] == 1
    assert por_fila["AGUA MINERAL"] == 0
    assert por_fila["AGUA SABORIZADA"] == 0
    assert por_fila["FULL SPORT"] == 1


def test_peso_sobre_acumulado_usa_el_total_de_aguas_de_la_sucursal():
    ventas = _ventas([
        (1, "LEVITE", 100, "2026-07", 3.0),
        (1, "LEVITE", 101, "2026-07", 3.0),
        (1, "VILLA DEL SUR", 102, "2026-07", 3.0),
        (1, "VILLA DEL SUR", 103, "2026-07", 3.0),
    ])
    t = construir_tabla(ventas, _padron([(1, "CASA CENTRAL", 10)]), MESES)
    por_fila = t[t.id_sucursal == 1].set_index("fila")
    assert por_fila.loc[TOTAL_AGUAS, "cob_acum"] == 4
    assert por_fila.loc["LEVITE", "pct_acum"] == pytest.approx(0.5)
    assert por_fila.loc[TOTAL_AGUAS, "pct_acum"] == pytest.approx(1.0)


def test_base_aguas_es_el_denominador_del_peso():
    """La columna de referencia tiene que ser el TOTAL AGUAS de esa sucursal."""
    ventas = _ventas([
        (1, "LEVITE", 100, "2026-07", 3.0),
        (1, "VILLA DEL SUR", 101, "2026-07", 3.0),
        (9, "LEVITE", 200, "2026-07", 3.0),
    ])
    padron = _padron([(1, "CASA CENTRAL", 10), (9, "SUCURSAL PERICO", 5)])
    t = construir_tabla(ventas, padron, MESES)
    for suc, esperado in ((1, 2), (9, 1)):
        b = t[t.id_sucursal == suc]
        assert (b["base_aguas"] == esperado).all()
        fila = b[b.fila == "LEVITE"].iloc[0]
        assert fila["pct_acum"] == pytest.approx(fila["cob_acum"] / fila["base_aguas"])
    # Y en el consolidado, la base es la del consolidado, no la de una sucursal.
    tg = t[t.es_total_general]
    assert (tg["base_aguas"] == 3).all()


def test_base_aguas_es_cero_sin_cobertura_y_no_rompe():
    ventas = _ventas([(1, "LEVITE", 100, "2026-07", 3.0)])
    t = construir_tabla(ventas, _padron([(1, "C", 10), (9, "P", 5)]), MESES)
    perico = t[t.id_sucursal == 9]
    assert (perico["base_aguas"] == 0).all()
    assert (perico["pct_acum"] == 0).all()


def test_peso_sobre_padron_no_anulado():
    ventas = _ventas([
        (1, "LEVITE", 100, "2026-07", 3.0),
        (1, "LEVITE", 101, "2026-07", 3.0),
    ])
    t = construir_tabla(ventas, _padron([(1, "CASA CENTRAL", 8)]), MESES)
    fila = t[(t.id_sucursal == 1) & (t.fila == "LEVITE")].iloc[0]
    assert fila["padron"] == 8
    assert fila["pct_padron"] == pytest.approx(0.25)


def test_sucursal_sin_ventas_aparece_en_cero():
    """Donde no vendemos tambien es informacion: la sucursal no se omite."""
    ventas = _ventas([(1, "LEVITE", 100, "2026-07", 3.0)])
    padron = _padron([(1, "CASA CENTRAL", 10), (9, "SUCURSAL PERICO", 5)])
    t = construir_tabla(ventas, padron, MESES)
    perico = t[t.id_sucursal == 9]
    assert len(perico) == len(CONCEPTOS)
    assert perico["cob_acum"].sum() == 0
    assert perico["pct_acum"].fillna(0).sum() == 0
    assert perico["padron"].unique().tolist() == [5]


def test_pct_acum_es_cero_si_la_sucursal_no_tiene_cobertura():
    """Sin denominador no se divide por cero: el peso queda en 0."""
    ventas = _ventas([(1, "LEVITE", 100, "2026-07", 3.0)])
    t = construir_tabla(ventas, _padron([(1, "C", 10), (9, "P", 5)]), MESES)
    assert (t[t.id_sucursal == 9]["pct_acum"] == 0).all()


def test_total_general_suma_entre_sucursales():
    """La cobertura SI es aditiva entre sucursales: cada cliente es de una sola."""
    ventas = _ventas([
        (1, "LEVITE", 100, "2026-07", 3.0),
        (9, "LEVITE", 100, "2026-07", 3.0),
    ])
    padron = _padron([(1, "CASA CENTRAL", 10), (9, "SUCURSAL PERICO", 5)])
    t = construir_tabla(ventas, padron, MESES)
    tg = t[t.es_total_general]
    fila = tg[tg.fila == "LEVITE"].iloc[0]
    assert fila["cob_acum"] == 2
    assert fila["padron"] == 15
    assert fila["pct_padron"] == pytest.approx(2 / 15)


def test_hay_una_sola_fila_de_total_general_por_concepto():
    ventas = _ventas([(1, "LEVITE", 100, "2026-07", 3.0)])
    t = construir_tabla(ventas, _padron([(1, "C", 10)]), MESES)
    tg = t[t.es_total_general]
    assert len(tg) == len(CONCEPTOS)
    assert tg["fila"].tolist() == [c.etiqueta for c in CONCEPTOS]


def test_marcas_ajenas_a_aguas_se_ignoran():
    ventas = _ventas([
        (1, "LEVITE", 100, "2026-07", 3.0),
        (1, "HEINEKEN", 101, "2026-07", 99.0),
    ])
    t = construir_tabla(ventas, _padron([(1, "C", 10)]), MESES)
    assert t[t.fila == TOTAL_AGUAS]["cob_acum"].iloc[0] == 1
    assert "HEINEKEN" not in t["fila"].tolist()


def test_orden_de_filas_es_estable_y_agrupa_cada_familia():
    ventas = _ventas([(1, "LEVITE", 100, "2026-07", 3.0)])
    t = construir_tabla(ventas, _padron([(1, "C", 10)]), MESES)
    assert t[t.id_sucursal == 1]["fila"].tolist() == [c.etiqueta for c in CONCEPTOS]


def test_ventas_vacias_no_rompen():
    ventas = _ventas([])
    t = construir_tabla(ventas, _padron([(1, "C", 10)]), MESES)
    assert len(t) == len(CONCEPTOS) * 2  # la sucursal + TOTAL GENERAL
    assert t["cob_acum"].sum() == 0


def test_columnas_mensuales_siguen_el_orden_pedido():
    ventas = _ventas([(1, "LEVITE", 100, "2026-08", 3.0)])
    t = construir_tabla(ventas, _padron([(1, "C", 10)]), MESES)
    assert [c for c in t.columns if c.startswith("cob_2026")] == [
        "cob_2026-07", "cob_2026-08"
    ]


# --- contrato de la query ---------------------------------------------------
#
# Esta es la parte que hace que el numero cierre contra el ETL, y hasta ahora
# solo la sostenia un comentario. Si alguien saca el join compuesto o el filtro
# de fuerza de ventas, el informe sigue corriendo y da otro numero en silencio.

def _capturar_query(**kwargs) -> tuple[str, dict]:
    """Corre `get_ventas_cliente_marca_mes` sin base y devuelve (sql, params)."""
    dl = DataLoader.__new__(DataLoader)  # sin __init__: no abre conexion
    with patch.object(DataLoader, "execute_query", autospec=True) as ex:
        ex.return_value = pd.DataFrame()
        dl.get_ventas_cliente_marca_mes(
            marcas=list(MARCAS_AGUAS),
            fecha_desde="2026-07-01",
            fecha_hasta="2026-08-10",
            **kwargs,
        )
    _, sql, params = ex.call_args.args
    return sql, params


def test_query_joinea_dim_vendedor_por_clave_compuesta():
    """id_vendedor se reusa entre sucursales: joinear solo por el id da fan-out."""
    sql, _ = _capturar_query()
    assert "fv.id_vendedor = dv.id_vendedor" in sql
    assert "fv.id_sucursal = dv.id_sucursal" in sql


def test_query_filtra_por_fuerza_de_ventas():
    """Sin este filtro entran movimientos con id_vendedor = 0 (placeholder)."""
    sql, params = _capturar_query()
    assert "dv.id_fuerza_ventas = :id_fuerza_ventas" in sql
    assert params["id_fuerza_ventas"] == 1


def test_query_usa_cantidades_total_no_con_cargo():
    """Las bonificaciones CUENTAN: si el producto llego al pdv, esta cubierto."""
    sql, _ = _capturar_query()
    assert "SUM(fv.cantidades_total)" in sql
    assert "cantidades_con_cargo" not in sql


def test_query_excluye_comprobantes_anulados():
    sql, _ = _capturar_query()
    assert "fv.anulado = false" in sql


def test_query_no_aplica_umbral_devuelve_el_neto_crudo():
    """El umbral se aplica por corte en el processor, no en SQL."""
    sql, _ = _capturar_query()
    assert "HAVING" not in sql.upper()


def test_query_agrupa_al_grano_de_cliente_y_mes():
    sql, params = _capturar_query()
    assert "GROUP BY 1, 2, 3, 4, 5" in sql
    assert params["fecha_desde"] == "2026-07-01"
    assert params["fecha_hasta"] == "2026-08-10"


def test_padron_activo_excluye_anulados():
    dl = DataLoader.__new__(DataLoader)
    with patch.object(DataLoader, "execute_query", autospec=True) as ex:
        ex.return_value = pd.DataFrame()
        dl.get_padron_activo()
    _, sql, _ = ex.call_args.args
    assert "dc.anulado = false" in sql
    assert "gold.dim_cliente" in sql


# --- exclusion de rutas -----------------------------------------------------

def test_excluir_rutas_usa_la_clave_compuesta():
    """(None, r) saca la ruta en todas; (s, r) solo en esa sucursal."""
    sql, params = DataLoader._excluir_rutas_sql([(None, 100), (1, 200)])
    assert "COALESCE(dc.id_ruta_fv1, -1) = :exr_ruta_0" in sql
    assert "fv.id_sucursal = :exr_suc_1" in sql
    assert "COALESCE(dc.id_ruta_fv1, -1) = :exr_ruta_1" in sql
    assert params == {"exr_ruta_0": 100, "exr_suc_1": 1, "exr_ruta_1": 200}
    # La global NO se ata a ninguna sucursal.
    assert "exr_suc_0" not in sql


def test_excluir_rutas_sin_lista_no_agrega_nada():
    assert DataLoader._excluir_rutas_sql(None) == ("", {})
    assert DataLoader._excluir_rutas_sql([]) == ("", {})


def test_ruta_nula_no_se_excluye():
    """COALESCE a -1: sin ficha de ruta no se sabe que es, y no se descarta."""
    sql, _ = DataLoader._excluir_rutas_sql([(None, 100)])
    assert "COALESCE(dc.id_ruta_fv1, -1)" in sql


def test_ventas_aplica_la_exclusion_de_rutas():
    sql, params = _capturar_query(rutas_excluidas=[(None, 100), (1, 200)])
    assert "AND NOT (" in sql
    assert params["exr_ruta_0"] == 100
    assert params["exr_ruta_1"] == 200
    # Necesita dim_cliente para la ruta, y por la clave compuesta.
    assert "LEFT JOIN gold.dim_cliente dc" in sql
    assert "fv.id_sucursal = dc.id_sucursal" in sql


def test_padron_aplica_la_exclusion_de_rutas():
    dl = DataLoader.__new__(DataLoader)
    with patch.object(DataLoader, "execute_query", autospec=True) as ex:
        ex.return_value = pd.DataFrame()
        dl.get_padron_activo(rutas_excluidas=[(None, 100), (1, 200)])
    _, sql, params = ex.call_args.args
    assert "AND NOT (" in sql
    assert params["exr_ruta_0"] == 100 and params["exr_ruta_1"] == 200


def test_las_rutas_excluidas_son_directa_y_chopera():
    """Ruta 100 = DIRECTA (todas las sucursales); 200 = CHOPERAS (casa central)."""
    from src.services.cobertura_aguas.constants import RUTAS_EXCLUIDAS
    assert RUTAS_EXCLUIDAS == ((None, 100), (1, 200))


def test_cobertura_y_padron_usan_EXACTAMENTE_las_mismas_rutas():
    """Si divergen, el peso sobre padron compara universos distintos.

    Es el error silencioso mas facil de cometer en este informe: se filtra el
    numerador, se olvida el denominador, y el porcentaje sigue pareciendo sano.
    """
    from src.services.cobertura_aguas.constants import RUTAS_EXCLUIDAS

    fake = _LoaderFalso()
    pedidos = {}

    def _ventas_spy(**kw):
        pedidos["ventas"] = kw.get("rutas_excluidas")
        return _ventas([])

    def _padron_spy(**kw):
        pedidos["padron"] = kw.get("rutas_excluidas")
        return _padron([(1, "C", 10)])

    fake.get_ventas_cliente_marca_mes = _ventas_spy
    fake.get_padron_activo = _padron_spy
    svc = CoberturaAguasService(data_loader=fake)
    # Sin escribir el xlsx: al test le interesa con que se pidieron los datos.
    with patch.object(CoberturaAguasService, "_build_workbook", autospec=True):
        svc.generar_reporte(CoberturaAguasConfig(fecha="2026-08-10"))
    assert pedidos["ventas"] == pedidos["padron"] == list(RUTAS_EXCLUIDAS)


# --- servicio ---------------------------------------------------------------

class _LoaderFalso:
    def __init__(self, ventas=None, padron=None):
        self.ventas, self.padron = ventas, padron
        self.pedido = None

    def get_ventas_cliente_marca_mes(self, **kw):
        self.pedido = kw
        return self.ventas if self.ventas is not None else _ventas([])

    def get_padron_activo(self, **kw):
        self.pedido_padron = kw
        return self.padron if self.padron is not None else _padron([(1, "C", 10)])


def test_servicio_deriva_los_meses_de_la_fecha():
    """Los meses NUNCA se escriben en el config: se derivan o se desincronizan."""
    svc = CoberturaAguasService(data_loader=_LoaderFalso())
    assert svc._meses(CoberturaAguasConfig(fecha="2026-08-10")) == ["2026-07", "2026-08"]
    assert svc._meses(CoberturaAguasConfig(fecha="2026-01-05")) == ["2025-12", "2026-01"]
    assert svc._meses(CoberturaAguasConfig(fecha="2026-08-10", meses=3)) == [
        "2026-06", "2026-07", "2026-08"
    ]


def test_servicio_rechaza_una_ventana_vacia():
    svc = CoberturaAguasService(data_loader=_LoaderFalso())
    with pytest.raises(ValueError, match="meses debe ser >= 1"):
        svc._meses(CoberturaAguasConfig(fecha="2026-08-10", meses=0))


def test_servicio_pide_la_ventana_completa_desde_el_primer_mes():
    svc = CoberturaAguasService(data_loader=(fake := _LoaderFalso()))
    svc._fetch(CoberturaAguasConfig(fecha="2026-08-10"), ["2026-07", "2026-08"])
    assert fake.pedido["fecha_desde"] == "2026-07-01"
    assert fake.pedido["fecha_hasta"] == "2026-08-10"
    assert set(fake.pedido["marcas"]) == set(MARCAS_AGUAS)


def test_servicio_sin_padron_falla_fuerte():
    """Sin denominador no hay pesos: mejor romper que publicar 0% en todo."""
    svc = CoberturaAguasService(data_loader=_LoaderFalso(padron=_padron([])))
    with pytest.raises(RuntimeError, match="padron"):
        svc.generar_reporte(CoberturaAguasConfig(fecha="2026-08-10"))


def test_padron_en_cero_no_divide_por_cero():
    ventas = _ventas([(1, "LEVITE", 100, "2026-07", 3.0)])
    t = construir_tabla(ventas, _padron([(1, "C", 0)]), MESES)
    assert (t["pct_padron"] == 0).all()


def test_constantes_cubren_las_cinco_marcas_de_aguas():
    assert set(MARCAS_AGUAS) == {
        "VILLA DEL SUR", "VILLAVICENCIO", "LEVITE", "BRIO", "FULL SPORT"
    }
    assert set(MARCAS_MINERAL) == {"VILLA DEL SUR", "VILLAVICENCIO"}
    assert set(MARCAS_SABORIZADA) == {"LEVITE", "BRIO"}
    # FULL SPORT no entra en ningun grupo — es isotonica, no agua saborizada.
    assert "FULL SPORT" not in MARCAS_MINERAL + MARCAS_SABORIZADA
