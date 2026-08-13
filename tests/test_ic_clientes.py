"""Tests de las transformaciones puras de analytics/clientes.py.

Nada de base de datos: cada test arma un DataFrame chico a mano y verifica
numeros calculables con lapiz y papel. Lo que se prueba es la LOGICA DE NEGOCIO
(que cliente cae en que segmento, que plata esta en riesgo, que el puente
cuadre), no que pandas sepa sumar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.services.inteligencia_comercial import constants
from src.services.inteligencia_comercial.analytics import clientes


# ---------------------------------------------------------------------------
# Fixtures a mano
# ---------------------------------------------------------------------------


def _base_rfm() -> pd.DataFrame:
    """10 clientes con recencia, frecuencia y neto perfectamente escalonados.

    Al estar ordenados y sin empates, los quintiles caen de a dos clientes y el
    score de cada uno se puede anticipar de memoria.
    """
    return pd.DataFrame(
        {
            "id_cliente": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "cliente": [f"CLIENTE {i}" for i in range(1, 11)],
            # el cliente 1 compro ayer, el 10 hace 100 dias
            "recencia_dias": [1, 5, 10, 20, 30, 40, 55, 70, 85, 100],
            "frecuencia": [100, 90, 80, 70, 60, 50, 40, 30, 20, 10],
            "dias_compra": [50, 45, 40, 35, 30, 25, 20, 15, 10, 5],
            "meses_activos": [12, 12, 11, 11, 10, 9, 8, 6, 4, 2],
            "monetario_neto": [1000.0, 900.0, 800.0, 700.0, 600.0,
                               500.0, 400.0, 300.0, 200.0, 100.0],
            "monetario_bruto": [1100.0, 990.0, 880.0, 770.0, 660.0,
                                550.0, 440.0, 330.0, 220.0, 110.0],
            "descuento": [100.0, 90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0],
            "htls": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            "bultos": [100.0, 90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0, 20.0, 10.0],
            "sucursal": ["CASA CENTRAL"] * 10,
            "canal": ["CANAL DTT"] * 10,
            "subcanal": ["SUB"] * 10,
            "ramo": ["ALMACEN"] * 10,
            "localidad": ["SALTA"] * 10,
            "preventista": ["JUAN PEREZ"] * 10,
        }
    )


def _base_fuga() -> pd.DataFrame:
    """5 clientes con ritmos y atrasos elegidos para tocar cada estado."""
    return pd.DataFrame(
        {
            "id_cliente": [1, 2, 3, 4, 5],
            "cliente": ["AL DIA", "RECUPERABLE", "PERDIDO", "AL DIA GRANDE", "CERRADA"],
            "dias_compra_24m": [50, 40, 30, 200, 20],
            # el 4 es el mas grande de la base pero compra todos los dias: al dia
            "recencia_dias": [5, 20, 100, 1, 90],
            "gap_medio": [8.0, 10.0, 10.0, 1.0, 12.0],
            "gap_desvio": [2.0, 15.0, 5.0, 0.5, 6.0],
            "gap_p50": [7.0, 8.0, 9.0, 1.0, 10.0],
            "gap_p90": [10.0, 10.0, 10.0, 2.0, 15.0],
            "gap_max": [12.0, 60.0, 40.0, 3.0, 30.0],
            "neto_12m": [1_000.0, 5_000.0, 2_000.0, 9_000.0, 4_000.0],
            "sucursal": [
                "CASA CENTRAL", "CASA CENTRAL", "CASA CENTRAL",
                "CASA CENTRAL", "SUCURSAL ABRA PAMPA",
            ],
            "canal": ["CANAL DTT"] * 5,
            "ramo": ["ALMACEN"] * 5,
            "localidad": ["SALTA"] * 5,
            "preventista": ["JUAN PEREZ"] * 5,
        }
    )


def _base_puente() -> pd.DataFrame:
    """Un cliente por bucket, con los numeros elegidos para sumar redondo."""
    return pd.DataFrame(
        {
            "id_cliente": [1, 2, 3, 4, 5],
            "cliente": ["NUEVO", "REACTIVADO", "PERDIDO", "UPSELL", "DOWNSELL"],
            "neto_actual": [100.0, 50.0, 0.0, 300.0, 120.0],
            "neto_previo": [0.0, 0.0, 80.0, 200.0, 150.0],
            "bruto_actual": [110.0, 55.0, 0.0, 330.0, 132.0],
            "bruto_previo": [0.0, 0.0, 88.0, 220.0, 165.0],
            "htls_actual": [10.0, 5.0, 0.0, 30.0, 12.0],
            "htls_previo": [0.0, 0.0, 8.0, 20.0, 25.0],
            "lineas_historicas": [0, 7, 3, 40, 40],
            "sucursal": ["CASA CENTRAL"] * 5,
            "preventista": ["JUAN PEREZ"] * 5,
        }
    )


def _base_articulos() -> pd.DataFrame:
    """4 SKUs cuyo neto suma 1.000, para leer las participaciones de cabeza."""
    return pd.DataFrame(
        {
            "id_articulo": [10, 20, 30, 40],
            "articulo": ["CERVEZA GRANDE", "CERVEZA LATA", "AGUA 2L", "FERNET"],
            "generico": ["CERVEZAS", "CERVEZAS", "AGUAS DANONE", "FRATELLI B"],
            "marca": ["SALTA", "SCHNEIDER", "VILLA DEL SUR", "BRANCA"],
            "proveedor": ["CICSA", "CICSA", "CICSA", "FRATELLI BRANCA"],
            "neto": [500.0, 300.0, 150.0, 50.0],
            "bruto": [600.0, 330.0, 160.0, 55.0],
            "descuento": [100.0, 30.0, 10.0, 5.0],
            "htls": [50.0, 30.0, 15.0, 5.0],
            "bultos": [500.0, 300.0, 150.0, 50.0],
            "clientes": [900, 800, 400, 300],
        }
    )


# ---------------------------------------------------------------------------
# RFM
# ---------------------------------------------------------------------------


class TestCalcularRFM:
    def test_el_cliente_mas_reciente_y_mas_grande_recibe_555(self):
        rfm = clientes.calcular_rfm(_base_rfm())
        mejor = rfm[rfm["id_cliente"] == 1].iloc[0]
        assert mejor["score_r"] == 5
        assert mejor["score_f"] == 5
        assert mejor["score_m"] == 5
        assert mejor["celda_rfm"] == "555"

    def test_el_cliente_mas_viejo_y_mas_chico_recibe_111(self):
        rfm = clientes.calcular_rfm(_base_rfm())
        peor = rfm[rfm["id_cliente"] == 10].iloc[0]
        assert peor["celda_rfm"] == "111"

    def test_con_diez_clientes_sin_empates_los_quintiles_van_de_a_dos(self):
        # 10 clientes ordenados -> 2 por quintil: ids 1-2 son R5, 3-4 R4, etc.
        rfm = clientes.calcular_rfm(_base_rfm()).set_index("id_cliente")
        assert list(rfm.loc[[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "score_r"]) == [
            5, 5, 4, 4, 3, 3, 2, 2, 1, 1
        ]

    def test_la_recencia_se_puntua_al_reves_que_el_monto(self):
        # comprar hace poco es bueno: menos dias -> score mas alto
        rfm = clientes.calcular_rfm(_base_rfm()).set_index("id_cliente")
        assert rfm.loc[1, "recencia_dias"] < rfm.loc[10, "recencia_dias"]
        assert rfm.loc[1, "score_r"] > rfm.loc[10, "score_r"]

    def test_marca_los_clientes_mostrador_sin_borrarlos(self):
        base = _base_rfm()
        base.loc[0, "id_cliente"] = constants.CLIENTES_MOSTRADOR[0]
        rfm = clientes.calcular_rfm(base)
        assert len(rfm) == 10, "el mostrador se marca, nunca se descarta"
        assert rfm[rfm["id_cliente"] == constants.CLIENTES_MOSTRADOR[0]]["es_mostrador"].iat[0]
        assert rfm["es_mostrador"].sum() == 1

    def test_no_redondea_los_montos(self):
        base = _base_rfm()
        base.loc[0, "monetario_neto"] = 1000.37
        rfm = clientes.calcular_rfm(base)
        assert rfm[rfm["id_cliente"] == 1]["monetario_neto"].iat[0] == pytest.approx(1000.37)

    def test_devuelve_vacio_si_no_hay_clientes(self):
        assert clientes.calcular_rfm(pd.DataFrame()).empty


class TestAsignarSegmento:
    def test_r5_f5_es_campeon(self):
        etiqueta, accion = clientes.asignar_segmento(5, 5)
        assert etiqueta == "Campeones"
        assert accion.startswith("Sostener")

    def test_r1_f1_es_perdido(self):
        assert clientes.asignar_segmento(1, 1)[0] == "Perdidos"

    def test_r1_f5_es_hibernando(self):
        assert clientes.asignar_segmento(1, 5)[0] == "Hibernando"

    def test_r2_f1_es_en_riesgo(self):
        assert clientes.asignar_segmento(2, 1)[0] == "En riesgo"

    def test_gana_la_primera_regla_que_matchea(self):
        # "No perder" (2,3,4,5) esta ANTES que "Leales" (3,5,3,5) a proposito:
        # r=2 f=5 es el cliente que compraba seguido y se esta yendo, y esa es
        # la lista de llamados de la semana. Si quedara diluido en Leales, el
        # segmento de mayor prioridad comercial desapareceria del informe.
        assert clientes.asignar_segmento(2, 5)[0] == "No perder"
        assert clientes.asignar_segmento(3, 4)[0] == "No perder"
        # con f=3 ya no califica como "No perder" y r=2 lo deja en riesgo
        assert clientes.asignar_segmento(2, 3)[0] == "En riesgo"

    def test_r3_f1_necesita_atencion(self):
        # recencia media y baja frecuencia: hay que llamarlo antes de que caiga
        assert clientes.asignar_segmento(3, 1)[0] == "Necesitan atencion"

    def test_todos_los_segmentos_declarados_son_alcanzables(self):
        # una version anterior dejaba 'No perder', 'Nuevos' y 'Necesitan
        # atencion' con cero clientes porque una regla mas amplia los tapaba
        declarados = {regla[4] for regla in constants.SEGMENTOS_RFM}
        alcanzados = {
            clientes.asignar_segmento(r, f)[0]
            for r in range(1, 6)
            for f in range(1, 6)
        }
        assert declarados == alcanzados

    def test_un_par_fuera_de_rango_no_rompe_el_informe(self):
        etiqueta, _ = clientes.asignar_segmento(0, 0)
        assert etiqueta == "Sin clasificar"


class TestResumirRFM:
    def test_los_porcentajes_de_cada_segmento_suman_uno(self):
        resumen = clientes.resumir_rfm(clientes.calcular_rfm(_base_rfm()))
        detalle = resumen[resumen["Segmento"] != clientes.TOTAL_GENERAL]
        assert detalle["% Clientes"].sum() == pytest.approx(1.0)
        assert detalle["% Neto"].sum() == pytest.approx(1.0)

    def test_la_fila_total_general_cierra_los_clientes_y_el_neto(self):
        resumen = clientes.resumir_rfm(clientes.calcular_rfm(_base_rfm()))
        total = resumen[resumen["Segmento"] == clientes.TOTAL_GENERAL].iloc[0]
        assert total["Clientes"] == 10
        # 1000+900+...+100 = 5500
        assert total["Neto (12m)"] == pytest.approx(5500.0)
        assert total["Bruto (12m)"] == pytest.approx(6050.0)
        assert total["Descuento (12m)"] == pytest.approx(550.0)
        # 5500 / 10
        assert total["Ticket medio neto"] == pytest.approx(550.0)

    def test_queda_ordenado_por_neto_descendente(self):
        resumen = clientes.resumir_rfm(clientes.calcular_rfm(_base_rfm()))
        detalle = resumen[resumen["Segmento"] != clientes.TOTAL_GENERAL]
        assert list(detalle["Neto (12m)"]) == sorted(detalle["Neto (12m)"], reverse=True)

    def test_el_bruto_siempre_es_mayor_o_igual_al_neto(self):
        resumen = clientes.resumir_rfm(clientes.calcular_rfm(_base_rfm()))
        assert (resumen["Bruto (12m)"] >= resumen["Neto (12m)"]).all()
        # neto = bruto - descuento, la definicion que corrige el error de leer
        # facturacion_neta como si fuese neto
        assert np.allclose(
            resumen["Bruto (12m)"] - resumen["Descuento (12m)"], resumen["Neto (12m)"]
        )


class TestAgregarTotalRFM:
    def test_agrega_una_fila_de_cierre_con_los_totales(self):
        rfm = clientes.calcular_rfm(_base_rfm())
        con_total = clientes.agregar_total_rfm(rfm)
        assert len(con_total) == len(rfm) + 1
        ultima = con_total.iloc[-1]
        assert ultima["cliente"] == clientes.TOTAL_GENERAL
        assert ultima["monetario_neto"] == pytest.approx(5500.0)
        assert ultima["htls"] == pytest.approx(55.0)


# ---------------------------------------------------------------------------
# Fuga
# ---------------------------------------------------------------------------


class TestClasificarEstadoFuga:
    def test_dentro_del_propio_p90_esta_al_dia(self):
        assert clientes.clasificar_estado_fuga(9, 10, 3.0) == "Al dia"

    def test_justo_en_el_p90_todavia_esta_al_dia(self):
        assert clientes.clasificar_estado_fuga(10, 10, 3.0) == "Al dia"

    def test_hasta_tres_veces_el_p90_es_recuperable(self):
        assert clientes.clasificar_estado_fuga(11, 10, 3.0) == "Recuperable"
        assert clientes.clasificar_estado_fuga(30, 10, 3.0) == "Recuperable"

    def test_mas_de_tres_veces_el_p90_ya_esta_perdido(self):
        assert clientes.clasificar_estado_fuga(31, 10, 3.0) == "Perdido"

    def test_dos_clientes_con_la_misma_recencia_pueden_tener_estados_distintos(self):
        # 20 dias de silencio: normal para quien compra cada 30, grave para
        # quien compra cada 5. Ese es todo el punto del umbral por cliente.
        assert clientes.clasificar_estado_fuga(20, 30, 3.0) == "Al dia"
        assert clientes.clasificar_estado_fuga(20, 5, 3.0) == "Perdido"

    def test_sin_p90_medible_no_inventa_un_estado(self):
        assert clientes.clasificar_estado_fuga(20, 0, 3.0) == "Sin ritmo medible"
        assert clientes.clasificar_estado_fuga(np.nan, 10, 3.0) == "Sin ritmo medible"


class TestCalcularFuga:
    def test_calcula_exceso_ratio_y_cv_a_mano(self):
        fuga = clientes.calcular_fuga(_base_fuga()).set_index("id_cliente")
        # cliente 2: recencia 20, p90 10 -> exceso 10, ratio 2.0
        assert fuga.loc[2, "exceso_dias"] == pytest.approx(10.0)
        assert fuga.loc[2, "ratio"] == pytest.approx(2.0)
        # cv = desvio / medio = 15 / 10
        assert fuga.loc[2, "cv_ritmo"] == pytest.approx(1.5)

    def test_asigna_los_estados_esperados(self):
        fuga = clientes.calcular_fuga(_base_fuga()).set_index("id_cliente")
        assert fuga.loc[1, "estado"] == "Al dia"
        assert fuga.loc[2, "estado"] == "Recuperable"
        assert fuga.loc[3, "estado"] == "Perdido"

    def test_la_sucursal_cerrada_queda_fuera_de_lo_accionable(self):
        fuga = clientes.calcular_fuga(_base_fuga()).set_index("id_cliente")
        assert fuga.loc[5, "sucursal_cerrada"]
        assert not fuga.loc[5, "accionable"]
        # pero sigue en la tabla, con su plata visible
        assert fuga.loc[5, "neto_12m"] == pytest.approx(4_000.0)

    def test_el_mostrador_no_es_accionable_aunque_este_al_dia(self):
        base = _base_fuga()
        base.loc[3, "id_cliente"] = constants.CLIENTES_MOSTRADOR[0]
        fuga = clientes.calcular_fuga(base).set_index("id_cliente")
        fila = fuga.loc[constants.CLIENTES_MOSTRADOR[0]]
        assert fila["es_mostrador"]
        assert not fila["accionable"]

    def test_ordena_primero_lo_accionable_y_atrasado_por_plata(self):
        fuga = clientes.calcular_fuga(_base_fuga())
        # accionables atrasados: id 2 ($5.000) y id 3 ($2.000)
        assert list(fuga["id_cliente"])[:2] == [2, 3]

    def test_no_levanta_excepcion_con_p90_cero(self):
        base = _base_fuga()
        base.loc[0, "gap_p90"] = 0.0
        fuga = clientes.calcular_fuga(base).set_index("id_cliente")
        assert fuga.loc[1, "estado"] == "Sin ritmo medible"
        assert np.isnan(fuga.loc[1, "ratio"])


class TestResumirFugaTotal:
    def test_la_fila_total_suma_el_neto_y_cuenta_los_atrasados(self):
        fuga = clientes.calcular_fuga(_base_fuga())
        con_total = clientes.resumir_fuga_total(fuga)
        ultima = con_total.iloc[-1]
        assert ultima["cliente"] == clientes.TOTAL_GENERAL
        assert ultima["neto_12m"] == pytest.approx(21_000.0)
        # atrasados = todos menos los dos "Al dia" (id 1 y id 4):
        # el 2 recuperable, el 3 perdido y el 5 de la sucursal cerrada
        assert ultima["estado"] == "3 atrasados"


# ---------------------------------------------------------------------------
# Cohortes
# ---------------------------------------------------------------------------


def _edge_cohortes() -> pd.DataFrame:
    """Dos cohortes de 100 clientes cada una, con retencion elegida a mano."""
    return pd.DataFrame(
        {
            "mes_cohorte": [
                "2026-01-01", "2026-01-01", "2026-01-01",
                "2026-02-01", "2026-02-01",
            ],
            "mes_n": [0, 1, 2, 0, 1],
            "clientes": [100, 80, 60, 100, 50],
            "neto": [1000.0, 800.0, 600.0, 1000.0, 500.0],
        }
    )


class TestMatrizCohortes:
    def test_m0_siempre_es_cien_por_ciento(self):
        matriz = clientes.matriz_cohortes(_edge_cohortes(), "2026-03-31")
        detalle = matriz[~matriz["Cohorte"].str.startswith(clientes.TOTAL_GENERAL)]
        assert (detalle["M0"] == 1.0).all()

    def test_la_retencion_es_el_cociente_contra_el_tamano_de_la_cohorte(self):
        matriz = clientes.matriz_cohortes(_edge_cohortes(), "2026-03-31").set_index("Cohorte")
        assert matriz.loc["2026-01", "M1"] == pytest.approx(0.80)
        assert matriz.loc["2026-01", "M2"] == pytest.approx(0.60)
        assert matriz.loc["2026-02", "M1"] == pytest.approx(0.50)

    def test_no_reporta_meses_que_la_cohorte_todavia_no_vivio(self):
        # la cohorte de febrero, cortada en marzo, solo puede tener M0 y M1
        matriz = clientes.matriz_cohortes(_edge_cohortes(), "2026-03-31").set_index("Cohorte")
        assert np.isnan(matriz.loc["2026-02", "M2"])

    def test_el_promedio_ponderado_solo_usa_cohortes_lo_bastante_viejas(self):
        matriz = clientes.matriz_cohortes(_edge_cohortes(), "2026-03-31").set_index("Cohorte")
        fila = matriz.loc[f"{clientes.TOTAL_GENERAL} (promedio ponderado)"]
        # M1: (80 + 50) / (100 + 100) = 0.65
        assert fila["M1"] == pytest.approx(0.65)
        # M2: solo enero llego -> 60 / 100 = 0.60, febrero no diluye
        assert fila["M2"] == pytest.approx(0.60)
        assert fila["Clientes cohorte"] == pytest.approx(200.0)

    def test_un_mes_sin_actividad_dentro_del_triangulo_cuenta_como_cero(self):
        edge = pd.DataFrame(
            {
                "mes_cohorte": ["2026-01-01", "2026-01-01"],
                "mes_n": [0, 2],
                "clientes": [100, 40],
                "neto": [1000.0, 400.0],
            }
        )
        matriz = clientes.matriz_cohortes(edge, "2026-03-31").set_index("Cohorte")
        assert matriz.loc["2026-01", "M1"] == pytest.approx(0.0)
        assert matriz.loc["2026-01", "M2"] == pytest.approx(0.40)

    def test_devuelve_vacio_si_no_hay_cohortes(self):
        assert clientes.matriz_cohortes(pd.DataFrame(), "2026-03-31").empty


# ---------------------------------------------------------------------------
# Puente de crecimiento
# ---------------------------------------------------------------------------


class TestClasificarMovimiento:
    def test_sin_historia_previa_es_nuevo(self):
        assert clientes.clasificar_movimiento(0, 100, 0, 10, 0) == "Nuevos"

    def test_con_historia_vieja_pero_sin_ano_previo_es_reactivado(self):
        assert clientes.clasificar_movimiento(0, 100, 0, 10, 7) == "Reactivados"

    def test_dejo_de_comprar_es_perdido(self):
        assert clientes.clasificar_movimiento(80, 0, 8, 0, 3) == "Perdidos"

    def test_la_direccion_se_decide_por_volumen_no_por_pesos(self):
        # facturo 50% mas en pesos pero vendio menos producto: es Downsell.
        # Con inflacion del 45%, leerlo en pesos daria Upsell y seria mentira.
        assert clientes.clasificar_movimiento(100, 150, 20, 18, 40) == "Downsell"

    def test_mas_volumen_es_upsell(self):
        assert clientes.clasificar_movimiento(200, 300, 20, 30, 40) == "Upsell"

    def test_sin_hectolitros_desempata_el_neto(self):
        # SKUs sin factor de hectolitros (vinos, por ejemplo) mueven 0 htl
        assert clientes.clasificar_movimiento(100, 150, 0, 0, 40) == "Upsell"
        assert clientes.clasificar_movimiento(150, 100, 0, 0, 40) == "Downsell"


class TestConstruirPuente:
    def test_cada_cliente_cae_en_el_bucket_esperado(self):
        tabla, _ = clientes.construir_puente(_base_puente())
        detalle = tabla[tabla["Movimiento"] != clientes.TOTAL_GENERAL]
        assert set(detalle["Movimiento"]) == set(clientes.BUCKETS_PUENTE)
        assert (detalle["Clientes"] == 1).all()

    def test_los_buckets_suman_exactamente_el_delta_total_en_htl(self):
        tabla, recon = clientes.construir_puente(_base_puente())
        # htl actual 10+5+0+30+12 = 57 ; previo 0+0+8+20+25 = 53 ; delta 4
        assert recon["delta_total_htl"] == pytest.approx(4.0)
        assert recon["suma_buckets_htl"] == pytest.approx(recon["delta_total_htl"])
        detalle = tabla[tabla["Movimiento"] != clientes.TOTAL_GENERAL]
        assert detalle["Delta htl"].sum() == pytest.approx(4.0)

    def test_los_buckets_suman_exactamente_el_delta_total_en_neto(self):
        tabla, recon = clientes.construir_puente(_base_puente())
        # neto actual 100+50+0+300+120 = 570 ; previo 0+0+80+200+150 = 430
        assert recon["delta_total_neto"] == pytest.approx(140.0)
        assert recon["suma_buckets_neto"] == pytest.approx(140.0)
        detalle = tabla[tabla["Movimiento"] != clientes.TOTAL_GENERAL]
        assert detalle["Delta neto (nominal)"].sum() == pytest.approx(140.0)

    def test_el_crecimiento_real_se_mide_en_volumen(self):
        _, recon = clientes.construir_puente(_base_puente())
        # 4 / 53
        assert recon["crecimiento_real_htl"] == pytest.approx(4.0 / 53.0)
        # el nominal en pesos es mucho mayor: 140 / 430
        assert recon["crecimiento_nominal_neto"] == pytest.approx(140.0 / 430.0)
        assert recon["crecimiento_nominal_neto"] > recon["crecimiento_real_htl"]

    def test_los_porcentajes_del_delta_suman_uno(self):
        tabla, _ = clientes.construir_puente(_base_puente())
        detalle = tabla[tabla["Movimiento"] != clientes.TOTAL_GENERAL]
        assert detalle["% del delta htl"].sum() == pytest.approx(1.0)
        assert detalle["% del delta neto"].sum() == pytest.approx(1.0)

    def test_la_fila_total_general_trae_los_totales_de_las_dos_ventanas(self):
        tabla, _ = clientes.construir_puente(_base_puente())
        total = tabla[tabla["Movimiento"] == clientes.TOTAL_GENERAL].iloc[0]
        assert total["Clientes"] == 5
        assert total["Htl previo"] == pytest.approx(53.0)
        assert total["Htl actual"] == pytest.approx(57.0)
        assert total["Neto previo (nominal)"] == pytest.approx(430.0)
        assert total["Neto actual (nominal)"] == pytest.approx(570.0)

    def test_los_buckets_van_en_el_orden_de_lectura(self):
        tabla, _ = clientes.construir_puente(_base_puente())
        detalle = tabla[tabla["Movimiento"] != clientes.TOTAL_GENERAL]
        assert list(detalle["Movimiento"]) == list(clientes.BUCKETS_PUENTE)


# ---------------------------------------------------------------------------
# Concentracion
# ---------------------------------------------------------------------------


class TestShareTop:
    def test_el_mayor_de_cuatro_skus_que_suman_mil(self):
        assert clientes.share_top([500, 300, 150, 50], 1) == pytest.approx(0.50)
        assert clientes.share_top([500, 300, 150, 50], 2) == pytest.approx(0.80)

    def test_pedir_mas_elementos_de_los_que_hay_da_el_total(self):
        assert clientes.share_top([500, 300, 150, 50], 99) == pytest.approx(1.0)

    def test_los_negativos_se_clipean_a_cero(self):
        # una devolucion no resta participacion: se trata como cero
        assert clientes.share_top([100, -100], 1) == pytest.approx(1.0)

    def test_una_serie_toda_en_cero_no_rompe(self):
        assert np.isnan(clientes.share_top([0, 0, 0], 1))


class TestMedirConcentracion:
    def test_un_reparto_perfectamente_parejo_da_gini_cero(self):
        fila = clientes.medir_concentracion("Clientes", "Neto (12m)", [10, 10, 10, 10])
        assert fila["Gini"] == pytest.approx(0.0)
        # 4 iguales -> HHI = 4 * 25^2 = 2500 -> N efectivo 4
        assert fila["HHI"] == pytest.approx(2500.0)
        assert fila["N efectivo"] == pytest.approx(4.0)

    def test_cuenta_los_positivos_por_separado(self):
        fila = clientes.medir_concentracion("Clientes", "Neto (12m)", [10, 0, -5, 20])
        assert fila["N"] == 4
        assert fila["N positivos"] == 2

    def test_reporta_las_participaciones_de_cola(self):
        fila = clientes.medir_concentracion("Articulos", "Neto (12m)", [500, 300, 150, 50])
        assert fila["Top 1"] == pytest.approx(0.50)
        assert fila["Top 5"] == pytest.approx(1.0)

    def test_pareto_ochenta_sobre_cuatro_skus(self):
        fila = clientes.medir_concentracion("Articulos", "Neto (12m)", [500, 300, 150, 50])
        # 500+300 = 800 = 80% -> 2 de 4 articulos
        assert fila["% que hace el 80%"] == pytest.approx(0.5)
        assert fila["N que hace el 80%"] == pytest.approx(2.0)


class TestTablaConcentracion:
    def test_devuelve_las_cuatro_lecturas(self):
        tabla = clientes.tabla_concentracion([1, 2, 3], [1, 2, 3], [10, 1], [10, 1])
        assert len(tabla) == 4
        assert list(tabla["Universo"]) == ["Clientes", "Clientes", "Articulos", "Articulos"]
        assert list(tabla["Medida"]) == [
            "Neto (12m)", "Hectolitros (12m)", "Neto (12m)", "Hectolitros (12m)"
        ]

    def test_los_articulos_estan_mas_concentrados_que_los_clientes(self):
        clientes_neto = [10] * 100          # base pareja
        articulos_neto = [900, 50, 30, 20]  # un SKU se lleva todo
        tabla = clientes.tabla_concentracion(
            clientes_neto, clientes_neto, articulos_neto, articulos_neto
        )
        gini_cli = tabla[tabla["Universo"] == "Clientes"]["Gini"].iat[0]
        gini_art = tabla[tabla["Universo"] == "Articulos"]["Gini"].iat[0]
        assert gini_art > gini_cli


class TestTablaLorenz:
    def test_arranca_en_cero_y_termina_en_uno(self):
        lorenz = clientes.tabla_lorenz([1, 2, 3, 4], [500, 300, 150, 50])
        assert lorenz["% acumulado de la poblacion"].iat[0] == pytest.approx(0.0)
        assert lorenz["% acumulado de la poblacion"].iat[-1] == pytest.approx(1.0)
        assert lorenz["% acumulado del neto — clientes"].iat[-1] == pytest.approx(1.0)
        assert lorenz["% acumulado del neto — articulos"].iat[-1] == pytest.approx(1.0)

    def test_la_curva_nunca_va_por_encima_de_la_igualdad_perfecta(self):
        lorenz = clientes.tabla_lorenz([1, 2, 3, 4], [500, 300, 150, 50])
        assert (
            lorenz["% acumulado del neto — clientes"] <= lorenz["Igualdad perfecta"] + 1e-12
        ).all()

    def test_tiene_los_puntos_pedidos(self):
        assert len(clientes.tabla_lorenz([1, 2], [1, 2], puntos=21)) == 21


class TestTopArticulos:
    def test_ordena_por_neto_descendente(self):
        tabla = clientes.top_articulos(_base_articulos(), n=3)
        detalle = tabla[~tabla["Articulo"].str.startswith(clientes.TOTAL_GENERAL)]
        assert list(detalle["Articulo"]) == ["CERVEZA GRANDE", "CERVEZA LATA", "AGUA 2L"]

    def test_los_porcentajes_se_calculan_sobre_el_catalogo_completo(self):
        # se muestran 3 SKUs pero el denominador son los 4 (total 1000)
        tabla = clientes.top_articulos(_base_articulos(), n=3)
        detalle = tabla[~tabla["Articulo"].str.startswith(clientes.TOTAL_GENERAL)]
        assert list(detalle["% del neto"]) == pytest.approx([0.50, 0.30, 0.15])
        assert list(detalle["% acumulado"]) == pytest.approx([0.50, 0.80, 0.95])

    def test_la_fila_total_general_es_todo_el_catalogo_vendido(self):
        tabla = clientes.top_articulos(_base_articulos(), n=3)
        total = tabla.iloc[-1]
        assert total["Articulo"] == f"{clientes.TOTAL_GENERAL} (4 SKUs vendidos)"
        assert total["Neto (12m)"] == pytest.approx(1000.0)
        assert total["Bruto (12m)"] == pytest.approx(1145.0)
        assert total["Descuento (12m)"] == pytest.approx(145.0)
        assert total["% del neto"] == pytest.approx(1.0)

    def test_distingue_bruto_neto_y_descuento(self):
        tabla = clientes.top_articulos(_base_articulos(), n=4)
        detalle = tabla[~tabla["Articulo"].str.startswith(clientes.TOTAL_GENERAL)]
        assert np.allclose(
            detalle["Bruto (12m)"] - detalle["Descuento (12m)"], detalle["Neto (12m)"]
        )

    def test_devuelve_vacio_sin_articulos(self):
        assert clientes.top_articulos(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# Contrato del modulo
# ---------------------------------------------------------------------------


class TestContratoDelModulo:
    def test_el_sql_excluye_los_genericos_que_no_son_venta(self):
        query = clientes.sql_rfm("2025-07-29", "2026-07-30")
        for generico in constants.GENERICOS_NO_VENTA:
            assert f"'{generico}'" in query

    def test_el_sql_de_montos_usa_subtotal_neto_y_no_subtotal_final(self):
        for query in (
            clientes.sql_rfm("2025-07-29", "2026-07-30"),
            clientes.sql_fuga("2025-07-29", "2024-07-29", "2026-07-30"),
            clientes.sql_puente("2025-07-29", "2024-07-29", "2026-07-30"),
            clientes.sql_articulos("2025-07-29", "2026-07-30"),
        ):
            assert "subtotal_neto" in query
            assert "subtotal_final" not in query

    def test_ningun_sql_escribe_en_la_base(self):
        prohibido = ("insert ", "update ", "delete ", "drop ", "alter ", "create ", "truncate ")
        for query in (
            clientes.sql_rfm("2025-07-29", "2026-07-30"),
            clientes.sql_fuga("2025-07-29", "2024-07-29", "2026-07-30"),
            clientes.sql_cohortes("2026-07-30", "2024-07-01"),
            clientes.sql_puente("2025-07-29", "2024-07-29", "2026-07-30"),
            clientes.sql_articulos("2025-07-29", "2026-07-30"),
        ):
            texto = query.lower()
            for palabra in prohibido:
                assert palabra not in texto, f"{palabra!r} aparece en el SQL"

    def test_las_cohortes_arrancan_despues_del_alta_completa_de_la_red(self):
        query = clientes.sql_cohortes("2026-07-30", constants.FECHA_RED_COMPLETA)
        assert f"DATE '{constants.FECHA_RED_COMPLETA}'" in query

    def test_build_no_levanta_excepcion_si_la_base_falla(self):
        class ContextoRoto:
            fecha_hasta = "2026-07-30"
            meses_ventana = 12
            meses_historia = 24

            def desde(self, meses=None):
                return "2025-07-28" if (meses or 12) == 12 else "2024-07-28"

            def sql(self, query, params=None):
                raise RuntimeError("conexion caida")

        resultado = clientes.build(ContextoRoto())
        assert resultado.failed is True
        assert resultado.tables == {}
        assert any("conexion caida" in n for n in resultado.notes)

    def test_build_no_levanta_excepcion_si_no_hay_datos(self):
        class ContextoVacio:
            fecha_hasta = "2026-07-30"
            meses_ventana = 12
            meses_historia = 24

            def desde(self, meses=None):
                return "2025-07-28" if (meses or 12) == 12 else "2024-07-28"

            def sql(self, query, params=None):
                return pd.DataFrame()

        resultado = clientes.build(ContextoVacio())
        assert resultado.failed is True
        assert "clientes" in " ".join(resultado.notes).lower()


# ---------------------------------------------------------------------------
# Regresiones: cada test de aca abajo cubre un numero que ya salio mal.
# ---------------------------------------------------------------------------


class TestPresupuestosNoSonVenta:
    """PRVTA es un presupuesto, no una venta.

    En la ventana a 2026-07-30 eran 97 lineas contra 2,16 millones de facturas,
    pero arrastraban $ 1.758.094.000 de neto y 4.440 htl en 4 clientes. Uno de
    ellos cargo 1.745 htl en un solo dia, casi el doble del volumen diario de
    toda la empresa. Con eso adentro el crecimiento real daba 10,6% en vez de
    9,5% y aparecian clientes fantasma arriba del ranking.
    """

    QUERIES = (
        "sql_rfm",
        "sql_fuga",
        "sql_puente",
        "sql_articulos",
        "sql_cohortes",
    )

    def _query(self, nombre: str) -> str:
        if nombre == "sql_rfm":
            return clientes.sql_rfm("2025-07-28", "2026-07-30")
        if nombre == "sql_fuga":
            return clientes.sql_fuga("2025-07-28", "2024-07-28", "2026-07-30")
        if nombre == "sql_puente":
            return clientes.sql_puente("2025-07-28", "2024-07-26", "2026-07-30")
        if nombre == "sql_articulos":
            return clientes.sql_articulos("2025-07-28", "2026-07-30")
        return clientes.sql_cohortes("2026-07-30", "2024-07-01")

    @pytest.mark.parametrize("nombre", QUERIES)
    def test_ningun_sql_de_plata_ni_de_volumen_deja_entrar_presupuestos(self, nombre):
        query = self._query(nombre)
        assert f"'{constants.DOC_PRESUPUESTO}'" not in query

    @pytest.mark.parametrize("nombre", ("sql_rfm", "sql_puente", "sql_articulos"))
    def test_el_universo_se_declara_por_lista_blanca_de_comprobantes(self, nombre):
        # Enumerar los validos y no excluir PRVTA: si el ETL suma manana un
        # comprobante nuevo, no entra solo al informe.
        query = self._query(nombre)
        assert "id_documento IN" in query
        assert f"'{constants.DOC_FACTURA}'" in query
        assert f"'{constants.DOC_DEVOLUCION}'" in query

    def test_la_fuga_perfila_el_ritmo_solo_con_facturas(self):
        query = clientes.sql_fuga("2025-07-28", "2024-07-28", "2026-07-30")
        # El perfil de cadencia se arma con facturas; el neto en juego suma
        # tambien las devoluciones, que son plata que el cliente devolvio.
        assert f"id_documento = '{constants.DOC_FACTURA}'" in query
        assert f"'{constants.DOC_DEVOLUCION}'" in query


class TestVentanasComparables:
    """Comparar 367 dias contra 365 regala crecimiento inventado."""

    class _Ctx:
        """Reproduce el recorte de dia a 28 de AnalysisContext.desde."""

        fecha_hasta = "2026-07-30"
        meses_ventana = 12
        meses_historia = 24

        def desde(self, meses=None):
            return "2025-07-28" if (meses or 12) == 12 else "2024-07-28"

    def test_la_ventana_previa_dura_lo_mismo_que_la_actual(self):
        v = clientes._ventanas(self._Ctx())
        actual = (
            pd.Timestamp(v["hasta"]) - pd.Timestamp(v["desde_12"])
        ).days
        previa = (
            pd.Timestamp(v["desde_12"]) - pd.Timestamp(v["desde_previo"])
        ).days
        # 2025-07-29..2026-07-30 son 367 dias, no 365: el dia recortado a 28
        # alarga la ventana actual y hay que espejarlo en la previa.
        assert actual == 367
        assert previa == actual

    def test_el_arranque_de_la_ventana_previa_se_corre_hacia_atras(self):
        v = clientes._ventanas(self._Ctx())
        # 2025-07-28 menos 367 dias
        assert v["desde_previo"] == "2024-07-26"
        # y NO el desde_24 calendario, que daria una ventana de 365 dias
        assert v["desde_24"] == "2024-07-28"

    def test_las_ventanas_no_se_solapan(self):
        v = clientes._ventanas(self._Ctx())
        assert v["desde_previo"] < v["desde_12"] < v["hasta"]

    def test_el_puente_consulta_la_ventana_espejo_y_no_la_de_24_meses(self):
        v = clientes._ventanas(self._Ctx())
        query = clientes.sql_puente(v["desde_12"], v["desde_previo"], v["hasta"])
        assert f"DATE '{v['desde_previo']}'" in query
        assert f"DATE '{v['desde_24']}'" not in query


class TestBuildNuncaExplota:
    """El contrato dice failed=True, nunca una excepcion."""

    class _Ctx:
        fecha_hasta = "2026-07-30"
        meses_ventana = 12
        meses_historia = 24

        def __init__(self, puente):
            self._puente = puente

        def desde(self, meses=None):
            return "2025-07-28" if (meses or 12) == 12 else "2024-07-28"

        def sql(self, query, params=None):
            if "lineas_historicas" in query:
                return self._puente
            if "AGE(" in query:
                return pd.DataFrame(
                    {
                        "mes_cohorte": [pd.Timestamp("2025-01-01")],
                        "mes_n": [0],
                        "clientes": [1],
                        "neto": [1.0],
                    }
                )
            return pd.DataFrame()

    @staticmethod
    def _puente_con_volumen_previo_nulo() -> pd.DataFrame:
        """Un cliente se pierde y otro devuelve lo mismo: htl previo total = 0.

        Pasa de verdad en una sucursal que arranco dentro de la ventana o
        cuando las devoluciones compensan las ventas del periodo anterior.
        """
        return pd.DataFrame(
            {
                "id_cliente": [1, 2],
                "cliente": ["SE VA", "DEVOLVIO"],
                "neto_actual": [0.0, 10.0],
                "neto_previo": [100.0, 5.0],
                "bruto_actual": [0.0, 11.0],
                "bruto_previo": [110.0, 5.0],
                "htls_actual": [0.0, 1.0],
                "htls_previo": [5.0, -5.0],
                "lineas_historicas": [0, 0],
                "sucursal": ["CASA CENTRAL", "CASA CENTRAL"],
                "preventista": ["JUAN PEREZ", "JUAN PEREZ"],
            }
        )

    def test_con_volumen_previo_cero_no_divide_por_cero(self):
        resultado = clientes.build(self._Ctx(self._puente_con_volumen_previo_nulo()))
        assert "puente" in resultado.tables
        assert not any("ZeroDivision" in n for n in resultado.notes)

    def test_igual_emite_la_alerta_de_downsell_sin_el_porcentaje(self):
        resultado = clientes.build(self._Ctx(self._puente_con_volumen_previo_nulo()))
        sangria = [a for a in resultado.alerts if "downsell" in a.title.lower()]
        assert len(sangria) == 1
        assert "reconquistar" in sangria[0].detail

    def test_una_tabla_rota_no_se_lleva_puesto_el_resto_del_informe(self):
        class ContextoQueRompeTarde(self._Ctx):
            def sql(self, query, params=None):
                if "AGE(" in query:
                    raise RuntimeError("cohortes rotas")
                return super().sql(query, params)

        resultado = clientes.build(
            ContextoQueRompeTarde(self._puente_con_volumen_previo_nulo())
        )
        assert resultado.failed is False
        assert "puente" in resultado.tables
        assert any("cohortes rotas" in n for n in resultado.notes)


class TestFilaDeTotalesVisible:
    """El escritor de Excel resalta la fila de totales mirando la PRIMERA celda.

    Con la etiqueta en la segunda columna la fila se escribia igual, pero salia
    sin resaltar y el lector no la distinguia de un cliente mas.
    """

    def test_la_etiqueta_total_cae_en_la_primera_columna_del_listado_rfm(self):
        rfm = clientes.calcular_rfm(_base_rfm())
        tabla = clientes.agregar_total_rfm(rfm[clientes._COLUMNAS_RFM])
        assert tabla.columns[0] == "cliente"
        assert tabla.iloc[-1, 0] == clientes.TOTAL_GENERAL

    def test_la_etiqueta_total_cae_en_la_primera_columna_de_fuga(self):
        fuga = clientes.calcular_fuga(_base_fuga())
        tabla = clientes.resumir_fuga_total(fuga[clientes._COLUMNAS_FUGA])
        assert tabla.columns[0] == "cliente"
        assert tabla.iloc[-1, 0] == clientes.TOTAL_GENERAL

    def test_la_etiqueta_total_cae_en_la_primera_columna_de_articulos(self):
        tabla = clientes.top_articulos(_base_articulos(), n=2)
        assert tabla.columns[0] == "Articulo"
        assert str(tabla.iloc[-1, 0]).startswith(clientes.TOTAL_GENERAL)

    def test_las_columnas_de_medida_siguen_siendo_numericas_con_la_fila_total(self):
        # Meter "" en una columna de medida la vuelve texto y el escritor pierde
        # el formato numerico de TODA la columna.
        rfm = clientes.calcular_rfm(_base_rfm())
        tabla = clientes.agregar_total_rfm(rfm[clientes._COLUMNAS_RFM])
        for col in ("monetario_neto", "htls", "bultos", "dias_compra", "meses_activos"):
            assert pd.api.types.is_numeric_dtype(tabla[col]), col

    def test_la_fila_total_de_fuga_no_ensucia_las_columnas_de_ritmo(self):
        fuga = clientes.calcular_fuga(_base_fuga())
        tabla = clientes.resumir_fuga_total(fuga[clientes._COLUMNAS_FUGA])
        for col in ("gap_medio", "gap_p50", "cv_ritmo", "exceso_dias", "ratio"):
            assert pd.api.types.is_numeric_dtype(tabla[col]), col

    def test_las_medianas_de_la_fila_total_no_son_sumas(self):
        # Sumar dias de espera de miles de clientes no significa nada.
        fuga = clientes.calcular_fuga(_base_fuga())
        tabla = clientes.resumir_fuga_total(fuga[clientes._COLUMNAS_FUGA])
        ultima = tabla.iloc[-1]
        assert ultima["gap_p90"] == pytest.approx(np.median([10.0, 10.0, 10.0, 2.0, 15.0]))
        assert ultima["recencia_dias"] == pytest.approx(np.median([5, 20, 100, 1, 90]))


class TestPesosNominalesEtiquetados:
    """Con inflacion argentina, un delta de pesos entre periodos no es crecimiento."""

    def test_las_columnas_de_pesos_del_puente_dicen_nominal(self):
        tabla, _ = clientes.construir_puente(_base_puente())
        pesos = [c for c in tabla.columns if "Neto" in c]
        assert pesos, "el puente tiene que reportar pesos"
        for col in pesos:
            assert "nominal" in col.lower(), col

    def test_el_volumen_no_necesita_esa_aclaracion(self):
        tabla, _ = clientes.construir_puente(_base_puente())
        assert "Delta htl" in tabla.columns
        assert "nominal" not in "Delta htl".lower()
