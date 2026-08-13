"""Tests del modulo de analisis logistico (logica pura, sin base de datos).

Cada fixture es chica y esta armada a mano para que el resultado esperado se
pueda calcular con lapiz y papel. Nada aca toca la red ni el Data Warehouse.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.services.inteligencia_comercial.analytics.logistica import (
    BRECHA_MINIMA_OTIF,
    ETIQUETA_RESTO,
    ETIQUETA_TOTAL,
    VEREDICTO_MUESTRA_CHICA,
    VEREDICTO_REZAGADO,
    _num,
    _pct,
    _recortar_ranking,
    alinear_a_mes_completo,
    calcular_cobertura,
    evaluar_proporcion,
    peor_rezagado,
    percentil_ponderado,
    resumir_devoluciones,
    resumir_rechazos,
    resumir_rutas,
    resumir_sla,
    resumir_stock,
    ventana_contabilidad,
)


# ---------------------------------------------------------------------------
# percentil_ponderado
# ---------------------------------------------------------------------------
class TestPercentilPonderado:
    """Percentil exacto sobre un histograma (valor, cantidad de casos)."""

    VALORES = [0, 1, 2, 3]
    PESOS = [10, 50, 30, 10]  # 100 casos en total

    def test_mediana_cae_en_el_valor_que_cruza_la_mitad(self):
        # Acumulado 10 / 60 / 90 / 100 -> el caso 50 cae en el valor 1
        assert percentil_ponderado(self.VALORES, self.PESOS, 0.5) == 1.0

    def test_percentil_90_cae_justo_en_el_borde(self):
        # El acumulado llega exactamente a 90 en el valor 2
        assert percentil_ponderado(self.VALORES, self.PESOS, 0.9) == 2.0

    def test_percentil_95_pasa_al_ultimo_valor(self):
        assert percentil_ponderado(self.VALORES, self.PESOS, 0.95) == 3.0

    def test_ignora_los_valores_sin_peso(self):
        assert percentil_ponderado([0, 99], [10, 0], 0.9) == 0.0

    def test_serie_vacia_devuelve_nan(self):
        assert np.isnan(percentil_ponderado([], [], 0.5))

    def test_no_depende_del_orden_de_entrada(self):
        revuelto = percentil_ponderado([3, 0, 2, 1], [10, 10, 30, 50], 0.5)
        assert revuelto == 1.0


# ---------------------------------------------------------------------------
# ventana_contabilidad
# ---------------------------------------------------------------------------
class TestVentanaContabilidad:
    """La tabla contable corta el 2026-05-05 y ese mes es un muñon de 5 dias."""

    def test_recorta_al_ultimo_mes_completo_antes_del_corte(self):
        desde, hasta = ventana_contabilidad(date(2026, 7, 30), 12)
        assert hasta == date(2026, 4, 30)
        assert desde == date(2025, 4, 28)

    def test_respeta_un_hasta_anterior_al_corte_si_es_fin_de_mes(self):
        desde, hasta = ventana_contabilidad(date(2026, 1, 31), 6)
        assert hasta == date(2026, 1, 31)
        assert desde == date(2025, 7, 28)

    def test_un_hasta_a_mitad_de_mes_retrocede_al_mes_anterior(self):
        _, hasta = ventana_contabilidad(date(2025, 9, 12), 12)
        assert hasta == date(2025, 8, 31)


class TestAlinearAMesCompleto:
    """La serie mensual tiene que arrancar en un mes entero, no en un muñon."""

    def test_una_fecha_a_mitad_de_mes_salta_al_mes_siguiente(self):
        assert alinear_a_mes_completo(date(2024, 7, 28)) == date(2024, 8, 1)

    def test_el_dia_uno_se_deja_como_esta(self):
        assert alinear_a_mes_completo(date(2024, 8, 1)) == date(2024, 8, 1)

    def test_diciembre_cruza_el_año(self):
        assert alinear_a_mes_completo(date(2024, 12, 15)) == date(2025, 1, 1)


class TestPeorRezagado:
    """La alerta tiene que nombrar la brecha mas grande, no la primera fila."""

    @staticmethod
    def _tabla():
        # El bloque de sucursales va SIEMPRE antes que el de fleteros, asi que
        # iloc[0] devolvia la sucursal aunque el fletero fuera mucho peor.
        return pd.DataFrame(
            [
                {"Nivel": "Sucursal", "Entidad": "SUC CAFAYATE",
                 "Sucursal": "SUC CAFAYATE", "Veredicto": VEREDICTO_REZAGADO,
                 "Brecha vs Red": -0.066},
                {"Nivel": "Fletero", "Entidad": "Fletero 63",
                 "Sucursal": "SUC CAFAYATE", "Veredicto": VEREDICTO_REZAGADO,
                 "Brecha vs Red": -0.218},
                {"Nivel": "Sucursal", "Entidad": "SUC BUENA",
                 "Sucursal": "SUC BUENA", "Veredicto": "Mejor que la red",
                 "Brecha vs Red": 0.12},
            ]
        )

    def test_elige_la_mayor_brecha_y_no_la_primera_fila(self):
        peor = peor_rezagado(self._tabla())
        assert peor["Entidad"] == "Fletero 63"
        assert peor["Brecha vs Red"] == pytest.approx(-0.218)

    def test_ignora_a_los_que_no_son_rezagados(self):
        tabla = self._tabla()
        tabla.loc[tabla["Entidad"] == "Fletero 63", "Veredicto"] = "Mejor que la red"
        assert peor_rezagado(tabla)["Entidad"] == "SUC CAFAYATE"

    def test_sin_rezagados_devuelve_none(self):
        tabla = self._tabla()
        tabla["Veredicto"] = "Mejor que la red"
        assert peor_rezagado(tabla) is None

    def test_tabla_vacia_devuelve_none(self):
        assert peor_rezagado(pd.DataFrame()) is None


# ---------------------------------------------------------------------------
# evaluar_proporcion
# ---------------------------------------------------------------------------
class TestEvaluarProporcion:
    """Nadie se acusa por azar: hace falta z-test Y brecha practica."""

    @staticmethod
    def _frame():
        # Tasa agregada = (90 + 60 + 9) / (100 + 100 + 10) = 159 / 210
        return pd.DataFrame(
            {
                "Entidad": ["ALTA", "BAJA", "CHICA"],
                "ok": [90.0, 60.0, 9.0],
                "n": [100.0, 100.0, 10.0],
            }
        )

    def test_la_tasa_de_la_red_es_el_agregado_no_el_promedio(self):
        out = evaluar_proporcion(self._frame(), "ok", "n", BRECHA_MINIMA_OTIF)
        assert out["Tasa Red"].iloc[0] == pytest.approx(159 / 210)

    def test_calcula_la_tasa_y_la_brecha_de_cada_entidad(self):
        out = evaluar_proporcion(self._frame(), "ok", "n", BRECHA_MINIMA_OTIF)
        assert out.loc[0, "Tasa"] == pytest.approx(0.90)
        assert out.loc[1, "Tasa"] == pytest.approx(0.60)
        assert out.loc[1, "Brecha vs Red"] == pytest.approx(0.60 - 159 / 210)

    def test_una_muestra_chica_no_se_acusa_aunque_la_brecha_sea_grande(self):
        # CHICA tiene la misma tasa que ALTA (0,90) pero solo 10 casos
        out = evaluar_proporcion(self._frame(), "ok", "n", BRECHA_MINIMA_OTIF)
        assert out.loc[2, "Significativo"] is False or not out.loc[2, "Significativo"]
        assert out.loc[2, "Veredicto"] == "Sin evidencia (muestra chica)"

    def test_marca_rezagado_al_que_es_significativo_y_esta_lejos(self):
        out = evaluar_proporcion(self._frame(), "ok", "n", BRECHA_MINIMA_OTIF)
        assert out.loc[1, "Veredicto"] == "Rezagado significativo"
        assert out.loc[0, "Veredicto"] == "Mejor que la red"

    def test_significativo_pero_chico_no_se_acciona(self):
        # 0,52 contra 0,48 con 10.000 casos cada uno: z = 4, brecha de 2 puntos
        frame = pd.DataFrame({"ok": [5200.0, 4800.0], "n": [10000.0, 10000.0]})
        out = evaluar_proporcion(frame, "ok", "n", BRECHA_MINIMA_OTIF)
        assert out.loc[0, "z"] == pytest.approx(4.0)
        assert bool(out.loc[0, "Significativo"]) is True
        assert out.loc[0, "Veredicto"] == "Significativo pero sin impacto practico"
        assert out.loc[1, "Veredicto"] == "Significativo pero sin impacto practico"

    def test_cuando_menos_es_mejor_se_invierte_el_veredicto(self):
        # Misma tabla, pero la metrica es rechazo: la tasa ALTA es la mala
        out = evaluar_proporcion(
            self._frame(), "ok", "n", BRECHA_MINIMA_OTIF, mayor_es_mejor=False,
            etiqueta_peor="Rechazo alto", etiqueta_mejor="Rechazo bajo",
        )
        assert out.loc[0, "Veredicto"] == "Rechazo alto"
        assert out.loc[1, "Veredicto"] == "Rechazo bajo"

    def test_frame_vacio_no_rompe(self):
        out = evaluar_proporcion(pd.DataFrame(columns=["ok", "n"]), "ok", "n", 0.05)
        assert out.empty
        assert "Veredicto" in out.columns


# ---------------------------------------------------------------------------
# resumir_sla
# ---------------------------------------------------------------------------
class TestResumirSla:
    """El SLA se colapsa desde un histograma de lead time a nivel factura."""

    @staticmethod
    def _histograma():
        return pd.DataFrame(
            {
                "sucursal": ["SUC A", "SUC A", "SUC A", "SUC B", "SUC A"],
                "id_sucursal": [1, 1, 1, 2, 1],
                "id_fletero_carga": [11, 11, 11, 22, 0],  # el 0 es sentinela
                "lead_dias": [0, 1, 3, 5, 0],
                "entregas": [30, 50, 20, 100, 1000],
                "bultos": [300.0, 500.0, 200.0, 1000.0, 9999.0],
                "neto": [3000.0, 5000.0, 2000.0, 10000.0, 99999.0],
            }
        )

    def test_excluye_los_fleteros_sentinela_antes_de_todo(self):
        tabla = resumir_sla(self._histograma(), min_entregas=0)
        total = tabla[tabla["Entidad"] == ETIQUETA_TOTAL].iloc[0]
        # 30 + 50 + 20 + 100 = 200; las 1.000 del fletero 0 no cuentan
        assert total["Entregas"] == 200.0
        assert "Fletero 0" not in set(tabla["Entidad"])

    def test_otif_es_la_proporcion_de_entregas_en_un_dia_o_menos(self):
        tabla = resumir_sla(self._histograma(), min_entregas=0)
        suc_a = tabla[tabla["Entidad"] == "SUC A"].iloc[0]
        assert suc_a["OTIF (<=1 dia)"] == pytest.approx(80 / 100)
        total = tabla[tabla["Entidad"] == ETIQUETA_TOTAL].iloc[0]
        assert total["OTIF (<=1 dia)"] == pytest.approx(80 / 200)

    def test_lead_medio_pondera_por_cantidad_de_entregas(self):
        tabla = resumir_sla(self._histograma(), min_entregas=0)
        suc_a = tabla[tabla["Entidad"] == "SUC A"].iloc[0]
        # (0*30 + 1*50 + 3*20) / 100 = 1,1
        assert suc_a["Lead Medio (dias)"] == pytest.approx(1.1)
        total = tabla[tabla["Entidad"] == ETIQUETA_TOTAL].iloc[0]
        # (110 + 5*100) / 200 = 3,05
        assert total["Lead Medio (dias)"] == pytest.approx(3.05)

    def test_percentiles_salen_del_histograma_completo(self):
        tabla = resumir_sla(self._histograma(), min_entregas=0)
        suc_a = tabla[tabla["Entidad"] == "SUC A"].iloc[0]
        assert suc_a["Lead p50 (dias)"] == 1.0
        assert suc_a["Lead p90 (dias)"] == 3.0
        total = tabla[tabla["Entidad"] == ETIQUETA_TOTAL].iloc[0]
        assert total["Lead p50 (dias)"] == 3.0
        assert total["Lead p90 (dias)"] == 5.0

    def test_arma_un_bloque_por_sucursal_y_otro_por_fletero(self):
        tabla = resumir_sla(self._histograma(), min_entregas=0)
        assert set(tabla["Nivel"]) == {"Sucursal", "Fletero", "TOTAL"}
        fleteros = tabla[tabla["Nivel"] == "Fletero"]
        assert set(fleteros["Entidad"]) == {"Fletero 11", "Fletero 22"}
        # El fletero arrastra su sucursal para poder leerlo en contexto
        assert fleteros.set_index("Entidad").loc["Fletero 11", "Sucursal"] == "SUC A"

    def test_el_piso_de_entregas_saca_a_los_fleteros_chicos(self):
        tabla = resumir_sla(self._histograma(), min_entregas=150)
        assert tabla[tabla["Nivel"] == "Fletero"].empty
        # Las sucursales siguen estando y el total no cambia
        assert tabla[tabla["Entidad"] == ETIQUETA_TOTAL].iloc[0]["Entregas"] == 200.0

    def test_la_tabla_siempre_termina_en_total_general(self):
        tabla = resumir_sla(self._histograma(), min_entregas=0)
        assert tabla.iloc[-1]["Entidad"] == ETIQUETA_TOTAL
        assert tabla.iloc[-1]["Neto Facturado (Nominal $)"] == pytest.approx(20000.0)

    def test_histograma_vacio_devuelve_tabla_vacia_sin_romper(self):
        assert resumir_sla(pd.DataFrame()).empty

    def test_si_solo_hay_sentinelas_no_inventa_numeros(self):
        solo_sentinela = self._histograma().tail(1)
        assert resumir_sla(solo_sentinela).empty


# ---------------------------------------------------------------------------
# resumir_rechazos
# ---------------------------------------------------------------------------
class TestResumirRechazos:
    """Tasa, valor, Pareto y marcas de contexto del rechazo."""

    @staticmethod
    def _largo():
        return pd.DataFrame(
            [
                # Sucursales: 120 rechazos sobre 2.000 lineas -> tasa de red 6%
                {"dimension": "Sucursal", "entidad": "SUCURSAL ABRA PAMPA",
                 "id_entidad": "1", "n_lineas": 1000, "n_rechazo": 100,
                 "bultos_rechazo": 10.0, "valor_rechazo": 800.0,
                 "neto_facturado": 9000.0},
                {"dimension": "Sucursal", "entidad": "CASA CENTRAL",
                 "id_entidad": "2", "n_lineas": 1000, "n_rechazo": 20,
                 "bultos_rechazo": 2.0, "valor_rechazo": 200.0,
                 "neto_facturado": 19000.0},
                # Clientes: uno es una caja de mostrador, otro no llega al piso
                {"dimension": "Cliente", "entidad": "CAJA MOSTRADOR",
                 "id_entidad": "100", "n_lineas": 500, "n_rechazo": 50,
                 "bultos_rechazo": 5.0, "valor_rechazo": 400.0,
                 "neto_facturado": 4000.0},
                {"dimension": "Cliente", "entidad": "KIOSCO CHICO",
                 "id_entidad": "999", "n_lineas": 100, "n_rechazo": 90,
                 "bultos_rechazo": 9.0, "valor_rechazo": 900.0,
                 "neto_facturado": 100.0},
            ]
        )

    def test_la_tasa_de_rechazo_es_lineas_rechazadas_sobre_lineas_totales(self):
        tabla = resumir_rechazos(self._largo())
        abra = tabla[tabla["Entidad"] == "SUCURSAL ABRA PAMPA"].iloc[0]
        assert abra["Tasa Rechazo"] == pytest.approx(0.10)
        assert abra["Tasa Red"] == pytest.approx(0.06)

    def test_la_tasa_de_la_red_del_bloque_cliente_usa_todos_los_clientes(self):
        # Antes el piso de lineas se aplicaba ANTES de calcular la base, con lo
        # cual cada cliente se comparaba contra un promedio recortado.
        # Con los dos clientes: (50 + 90) / (500 + 100) = 140 / 600
        tabla = resumir_rechazos(self._largo())
        caja = tabla[tabla["Entidad"] == "CAJA MOSTRADOR"].iloc[0]
        assert caja["Tasa Red"] == pytest.approx(140 / 600)

    def test_el_bloque_cliente_conserva_todo_el_valor_rechazado(self):
        # El cliente chico aporta $900 de los $1.300 del bloque: si se lo recorta
        # antes de normalizar, el Share del resto se infla 3,25 veces.
        tabla = resumir_rechazos(self._largo())
        cli = tabla[tabla["Dimension"] == "Cliente"]
        assert cli["Valor Rechazado Neto (Nominal $)"].sum() == pytest.approx(1300.0)
        caja = cli[cli["Entidad"] == "CAJA MOSTRADOR"].iloc[0]
        assert caja["Share del Valor Rechazado"] == pytest.approx(400 / 1300)

    def test_el_total_general_sale_de_la_dimension_que_cubre_todo(self):
        tabla = resumir_rechazos(self._largo())
        total = tabla[tabla["Entidad"] == ETIQUETA_TOTAL].iloc[0]
        assert total["Lineas"] == pytest.approx(2000.0)
        assert total["Lineas con Rechazo"] == pytest.approx(120.0)
        assert total["Tasa Rechazo"] == pytest.approx(0.06)
        assert total["Valor Rechazado Neto (Nominal $)"] == pytest.approx(1000.0)

    def test_el_pareto_acumula_de_mayor_a_menor_dentro_de_la_dimension(self):
        tabla = resumir_rechazos(self._largo())
        suc = tabla[tabla["Dimension"] == "Sucursal"]
        assert list(suc["Share del Valor Rechazado"]) == pytest.approx([0.8, 0.2])
        assert list(suc["Pareto Acumulado"]) == pytest.approx([0.8, 1.0])

    def test_una_tasa_alta_y_significativa_se_llama_rechazo_alto(self):
        tabla = resumir_rechazos(self._largo())
        abra = tabla[tabla["Entidad"] == "SUCURSAL ABRA PAMPA"].iloc[0]
        assert abra["Veredicto"] == "Rechazo alto (significativo)"

    def test_marca_la_sucursal_cerrada_para_que_nadie_la_accione(self):
        tabla = resumir_rechazos(self._largo())
        abra = tabla[tabla["Entidad"] == "SUCURSAL ABRA PAMPA"].iloc[0]
        assert abra["Nota"].startswith("Sucursal cerrada el 2026-05-04")

    def test_marca_los_clientes_mostrador_en_vez_de_borrarlos(self):
        tabla = resumir_rechazos(self._largo())
        caja = tabla[tabla["Entidad"] == "CAJA MOSTRADOR"].iloc[0]
        assert "mostrador" in caja["Nota"].lower()
        assert caja["Valor Rechazado Neto (Nominal $)"] == pytest.approx(400.0)

    def test_el_piso_de_lineas_suprime_el_veredicto_pero_no_la_fila(self):
        # 90 de 100 lineas rechazadas es una tasa altisima, pero con 100 lineas
        # no se acusa a nadie. La fila se queda porque los $900 son plata real y
        # el bloque tiene que cuadrar contra el TOTAL GENERAL.
        tabla = resumir_rechazos(self._largo())
        kiosco = tabla[tabla["Entidad"] == "KIOSCO CHICO"].iloc[0]
        assert kiosco["Veredicto"] == VEREDICTO_MUESTRA_CHICA
        assert bool(kiosco["Significativo"]) is False
        assert kiosco["Valor Rechazado Neto (Nominal $)"] == pytest.approx(900.0)

    def test_el_piso_no_toca_las_dimensiones_cortas(self):
        # Una sucursal con pocas lineas igual se juzga: el piso es solo para las
        # dimensiones de cola larga.
        tabla = resumir_rechazos(self._largo(), min_lineas=100000)
        suc = tabla[tabla["Dimension"] == "Sucursal"]
        assert VEREDICTO_MUESTRA_CHICA not in set(suc["Veredicto"])

    def test_largo_vacio_devuelve_tabla_vacia(self):
        assert resumir_rechazos(pd.DataFrame()).empty


class TestRecortarRanking:
    """La cola larga se colapsa sumando importes, nunca sumando tasas."""

    @staticmethod
    def _bloque(n=5):
        return pd.DataFrame(
            {
                "Dimension": ["Cliente"] * n,
                "Entidad": [f"C{i}" for i in range(n)],
                "Lineas": [100.0] * n,
                "Lineas con Rechazo": [10.0] * n,
                "Tasa Rechazo": [0.1] * n,
                "Valor Rechazado Neto (Nominal $)": [float(n - i) for i in range(n)],
            }
        )

    def test_deja_el_top_y_agrega_una_fila_resto(self):
        out = _recortar_ranking(self._bloque(5), "Valor Rechazado Neto (Nominal $)", 2)
        assert len(out) == 3
        assert out.iloc[-1]["Entidad"].startswith(ETIQUETA_RESTO)
        assert "3 entidades" in out.iloc[-1]["Entidad"]

    def test_la_fila_resto_suma_importes_y_recalcula_la_tasa(self):
        out = _recortar_ranking(self._bloque(5), "Valor Rechazado Neto (Nominal $)", 2)
        resto = out.iloc[-1]
        # Los 3 de la cola valen 3 + 2 + 1 = 6
        assert resto["Valor Rechazado Neto (Nominal $)"] == pytest.approx(6.0)
        assert resto["Lineas"] == pytest.approx(300.0)
        # La tasa se recalcula: 30 / 300, NO 0,1 + 0,1 + 0,1
        assert resto["Tasa Rechazo"] == pytest.approx(0.1)

    def test_si_el_bloque_entra_entero_no_toca_nada(self):
        bloque = self._bloque(3)
        out = _recortar_ranking(bloque, "Valor Rechazado Neto (Nominal $)", 10)
        assert out.equals(bloque)


# ---------------------------------------------------------------------------
# resumir_devoluciones
# ---------------------------------------------------------------------------
class TestResumirDevoluciones:
    """La devolucion se mide contra la venta bruta del propio producto."""

    @staticmethod
    def _largo():
        filas = [
            {"dimension": "Generico", "entidad": "CERVEZAS",
             "bultos_bruto": 1000.0, "bultos_dev": 100.0,
             "bruto_pesos": 10000.0, "dev_pesos": 900.0},
            {"dimension": "Generico", "entidad": "VINOS",
             "bultos_bruto": 1000.0, "bultos_dev": 50.0,
             "bruto_pesos": 10000.0, "dev_pesos": 500.0},
        ]
        # Cuatro articulos comparables y uno que no llega al piso de bultos
        for nombre, dev in (("SIDRA ROTA", 500.0), ("A2", 100.0), ("A3", 110.0), ("A4", 90.0)):
            filas.append(
                {"dimension": "Articulo", "entidad": nombre,
                 "bultos_bruto": 1000.0, "bultos_dev": dev,
                 "bruto_pesos": 10000.0, "dev_pesos": dev * 10}
            )
        filas.append(
            {"dimension": "Articulo", "entidad": "ARTICULO CHICO",
             "bultos_bruto": 50.0, "bultos_dev": 40.0,
             "bruto_pesos": 500.0, "dev_pesos": 400.0}
        )
        return pd.DataFrame(filas)

    def test_la_tasa_es_autorreferencial_en_bultos_y_en_valor(self):
        tabla = resumir_devoluciones(self._largo(), piso_bultos=100)
        cervezas = tabla[tabla["Entidad"] == "CERVEZAS"].iloc[0]
        assert cervezas["Tasa Devolucion (bultos)"] == pytest.approx(0.10)
        assert cervezas["Tasa Devolucion (valor)"] == pytest.approx(0.09)

    def test_el_piso_de_bultos_saca_los_denominadores_ridiculos(self):
        tabla = resumir_devoluciones(self._largo(), piso_bultos=100)
        assert "ARTICULO CHICO" not in set(tabla["Entidad"])

    def test_marca_como_outlier_solo_al_articulo_estructuralmente_roto(self):
        tabla = resumir_devoluciones(self._largo(), piso_bultos=100)
        articulos = tabla[tabla["Dimension"] == "Articulo"].set_index("Entidad")
        # Tasas 0,50 / 0,11 / 0,10 / 0,09 -> mediana 0,105.
        # Desvios |x - 0,105| = 0,395 / 0,005 / 0,005 / 0,015 -> MAD = 0,010
        assert articulos.loc["SIDRA ROTA", "z Robusto"] == pytest.approx(
            (0.50 - 0.105) / (1.4826 * 0.010)
        )
        assert bool(articulos.loc["SIDRA ROTA", "Outlier"]) is True
        assert bool(articulos.loc["A2", "Outlier"]) is False

    def test_el_total_general_sale_de_la_dimension_generico(self):
        tabla = resumir_devoluciones(self._largo(), piso_bultos=100)
        total = tabla[tabla["Entidad"] == ETIQUETA_TOTAL].iloc[0]
        assert total["Bultos Vendidos (Bruto)"] == pytest.approx(2000.0)
        assert total["Bultos Devueltos"] == pytest.approx(150.0)
        assert total["Tasa Devolucion (bultos)"] == pytest.approx(0.075)
        assert total["Tasa Devolucion (valor)"] == pytest.approx(1400.0 / 20000.0)

    def test_marca_el_ultimo_mes_cuando_la_ventana_lo_corta(self):
        largo = pd.DataFrame(
            [
                {"dimension": "Mes", "entidad": m, "bultos_bruto": 100.0,
                 "bultos_dev": 5.0, "bruto_pesos": 1000.0, "dev_pesos": 50.0}
                for m in ("2026-06", "2026-07")
            ]
        )
        tabla = resumir_devoluciones(largo, mes_parcial="2026-07")
        por_mes = tabla.set_index("Entidad")
        assert "incompleto" in por_mes.loc["2026-07", "Nota"]
        assert por_mes.loc["2026-06", "Nota"] == ""

    def test_si_todas_las_dimensiones_quedan_vacias_no_rompe(self):
        # Un solo articulo por debajo del piso: no queda ningun bloque y antes
        # esto reventaba con KeyError('Entidad') en vez de devolver una tabla.
        largo = pd.DataFrame(
            [{"dimension": "Articulo", "entidad": "X", "bultos_bruto": 10.0,
              "bultos_dev": 1.0, "bruto_pesos": 100.0, "dev_pesos": 10.0}]
        )
        tabla = resumir_devoluciones(largo, piso_bultos=3000)
        # Queda solo el TOTAL GENERAL, calculado sobre el universo disponible
        assert len(tabla) == 1
        assert tabla.iloc[-1]["Entidad"] == ETIQUETA_TOTAL

    def test_los_meses_quedan_en_orden_cronologico(self):
        largo = pd.DataFrame(
            [
                {"dimension": "Mes", "entidad": m, "bultos_bruto": 100.0,
                 "bultos_dev": 5.0, "bruto_pesos": 1000.0, "dev_pesos": 50.0}
                for m in ("2026-03", "2026-01", "2026-02")
            ]
        )
        tabla = resumir_devoluciones(largo)
        meses = tabla[tabla["Dimension"] == "Mes"]["Entidad"].tolist()
        assert meses == ["2026-01", "2026-02", "2026-03"]

    def test_largo_vacio_devuelve_tabla_vacia(self):
        assert resumir_devoluciones(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# calcular_cobertura / resumir_stock
# ---------------------------------------------------------------------------
class TestCalcularCobertura:
    """Dias de cobertura y clasificacion de cada par sucursal-articulo."""

    @staticmethod
    def _pares():
        return pd.DataFrame(
            [
                # Rota bien: 200 bultos en 50 dias con venta = 4 por dia
                {"sucursal": "A", "articulo": "NORMAL", "generico": "CERVEZAS",
                 "marca": "SALTA", "stock_bultos": 100.0, "bultos_60d": 200.0,
                 "ndias": 50.0, "bultos_12m": 5000.0, "costo": 10.0},
                {"sucursal": "A", "articulo": "AL BORDE", "generico": "CERVEZAS",
                 "marca": "SALTA", "stock_bultos": 10.0, "bultos_60d": 200.0,
                 "ndias": 50.0, "bultos_12m": 5000.0, "costo": 10.0},
                {"sucursal": "A", "articulo": "DORMIDO", "generico": "CERVEZAS",
                 "marca": "SALTA", "stock_bultos": 1000.0, "bultos_60d": 200.0,
                 "ndias": 50.0, "bultos_12m": 5000.0, "costo": 10.0},
                # Tiene stock, no vendio en 60 dias, pero es un SKU vivo
                {"sucursal": "A", "articulo": "MUERTO", "generico": "VINOS",
                 "marca": "TORO", "stock_bultos": 50.0, "bultos_60d": 0.0,
                 "ndias": 0.0, "bultos_12m": 300.0, "costo": 20.0},
                # Envase retornable: nunca se vende, no es capital muerto
                {"sucursal": "A", "articulo": "ESQUELETO", "generico": "ENVASES CCU",
                 "marca": "ENVASES", "stock_bultos": 80.0, "bultos_60d": 0.0,
                 "ndias": 0.0, "bultos_12m": 0.0, "costo": 1000.0},
                # Pseudo-articulo sin generico (troquel promocional)
                {"sucursal": "A", "articulo": "TROQUEL", "generico": None,
                 "marca": None, "stock_bultos": 5.0, "bultos_60d": 0.0,
                 "ndias": 0.0, "bultos_12m": 0.0, "costo": 1.0},
            ]
        )

    def test_la_velocidad_divide_por_dias_con_venta_no_por_dias_corridos(self):
        cob = calcular_cobertura(self._pares()).set_index("Articulo")
        assert cob.loc["NORMAL", "Velocidad (bultos/dia)"] == pytest.approx(4.0)
        assert cob.loc["NORMAL", "Dias de Cobertura"] == pytest.approx(25.0)

    def test_clasifica_quiebre_normal_y_sobrestock(self):
        cob = calcular_cobertura(self._pares()).set_index("Articulo")
        assert cob.loc["AL BORDE", "Dias de Cobertura"] == pytest.approx(2.5)
        assert cob.loc["AL BORDE", "Estado"] == "QUIEBRE"
        assert cob.loc["NORMAL", "Estado"] == "NORMAL"
        assert cob.loc["DORMIDO", "Dias de Cobertura"] == pytest.approx(250.0)
        assert cob.loc["DORMIDO", "Estado"] == "SOBRESTOCK"

    def test_separa_stock_muerto_de_lo_que_nunca_se_vendio(self):
        cob = calcular_cobertura(self._pares()).set_index("Articulo")
        assert cob.loc["MUERTO", "Estado"] == "STOCK MUERTO"
        assert cob.loc["ESQUELETO", "Estado"] == "SIN MOVIMIENTO"
        assert cob.loc["TROQUEL", "Estado"] == "SIN MOVIMIENTO"

    def test_los_generico_no_vendibles_no_son_mercaderia(self):
        cob = calcular_cobertura(self._pares()).set_index("Articulo")
        assert bool(cob.loc["NORMAL", "Es Mercaderia"]) is True
        assert bool(cob.loc["ESQUELETO", "Es Mercaderia"]) is False
        assert bool(cob.loc["TROQUEL", "Es Mercaderia"]) is False

    def test_valua_el_stock_a_costo_sin_redondear(self):
        cob = calcular_cobertura(self._pares()).set_index("Articulo")
        assert cob.loc["DORMIDO", "Valor Stock a Costo (Nominal $)"] == pytest.approx(10000.0)

    def test_avisa_cuando_el_stock_viene_negativo(self):
        # Sobreventa o ajuste pendiente: descuenta capital de los totales y no
        # puede quedar mudo en la hoja.
        pares = self._pares()
        pares.loc[0, "stock_bultos"] = -8.0
        cob = calcular_cobertura(pares).set_index("Articulo")
        assert "Stock negativo" in cob.loc["NORMAL", "Nota"]
        assert cob.loc["NORMAL", "Valor Stock a Costo (Nominal $)"] == pytest.approx(-80.0)

    def test_avisa_cuando_no_hay_costo_de_compra(self):
        pares = self._pares()
        pares.loc[0, "costo"] = np.nan
        cob = calcular_cobertura(pares).set_index("Articulo")
        assert "Sin costo" in cob.loc["NORMAL", "Nota"]
        assert np.isnan(cob.loc["NORMAL", "Valor Stock a Costo (Nominal $)"])

    def test_pares_vacios_no_rompen(self):
        assert calcular_cobertura(pd.DataFrame()).empty


class TestResumirStock:
    """La tabla de stock solo muestra mercaderia vendible y cierra con total."""

    def _cobertura(self):
        return calcular_cobertura(TestCalcularCobertura._pares())

    def test_deja_afuera_envases_y_pseudo_articulos(self):
        tabla = resumir_stock(self._cobertura())
        articulos = set(tabla["Articulo"])
        assert "ESQUELETO" not in articulos
        assert "TROQUEL" not in articulos
        assert {"NORMAL", "AL BORDE", "DORMIDO", "MUERTO"} <= articulos

    def test_ordena_primero_lo_que_urge(self):
        tabla = resumir_stock(self._cobertura())
        assert tabla.iloc[0]["Estado"] == "QUIEBRE"

    def test_el_total_usa_cobertura_agregada_no_promedio_de_coberturas(self):
        tabla = resumir_stock(self._cobertura())
        total = tabla.iloc[-1]
        assert total["Articulo"] == ETIQUETA_TOTAL
        # Stock 100 + 10 + 1.000 + 50 = 1.160 sobre velocidad 4 + 4 + 4 = 12
        assert total["Stock (bultos)"] == pytest.approx(1160.0)
        assert total["Velocidad (bultos/dia)"] == pytest.approx(12.0)
        assert total["Dias de Cobertura"] == pytest.approx(1160.0 / 12.0)
        # 100*10 + 10*10 + 1.000*10 + 50*20 = 12.100
        assert total["Valor Stock a Costo (Nominal $)"] == pytest.approx(12100.0)

    def test_cobertura_vacia_devuelve_tabla_vacia(self):
        assert resumir_stock(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# resumir_rutas
# ---------------------------------------------------------------------------
class TestResumirRutas:
    """Economia de ruta con la clave compuesta (sucursal, ruta)."""

    @staticmethod
    def _rutas():
        return pd.DataFrame(
            [
                {"sucursal": "SUCURSAL A", "id_sucursal": 1, "id_ruta_fv1": 1,
                 "des_ruta": "RUTA UNO A", "preventista": "PEREZ",
                 "visitas": 100, "clientes": 20, "dias_activos": 50,
                 "bultos": 100.0, "neto": 1000.0, "bruto": 1100.0,
                 "lineas_x_visita": 2.0, "mediana_bultos_visita": 1.0,
                 "clientes_mostrador": 0},
                {"sucursal": "SUCURSAL B", "id_sucursal": 2, "id_ruta_fv1": 1,
                 "des_ruta": "RUTA UNO B", "preventista": "GOMEZ",
                 "visitas": 100, "clientes": 20, "dias_activos": 50,
                 "bultos": 1000.0, "neto": 10000.0, "bruto": 11000.0,
                 "lineas_x_visita": 5.0, "mediana_bultos_visita": 8.0,
                 "clientes_mostrador": 1},
                {"sucursal": "SUCURSAL A", "id_sucursal": 1, "id_ruta_fv1": 2,
                 "des_ruta": "RUTA DOS A", "preventista": "PEREZ",
                 "visitas": 100, "clientes": 20, "dias_activos": 50,
                 "bultos": 400.0, "neto": 4000.0, "bruto": 4400.0,
                 "lineas_x_visita": 3.0, "mediana_bultos_visita": 3.0,
                 "clientes_mostrador": 0},
                {"sucursal": "SUCURSAL B", "id_sucursal": 2, "id_ruta_fv1": 2,
                 "des_ruta": "RUTA DOS B", "preventista": "GOMEZ",
                 "visitas": 100, "clientes": 20, "dias_activos": 50,
                 "bultos": 500.0, "neto": 5000.0, "bruto": 5500.0,
                 "lineas_x_visita": 4.0, "mediana_bultos_visita": 4.0,
                 "clientes_mostrador": 0},
            ]
        )

    def test_la_clave_de_ruta_incluye_la_sucursal_porque_el_id_se_repite(self):
        tabla = resumir_rutas(self._rutas())
        claves = [c for c in tabla["Clave Ruta"] if c != ETIQUETA_TOTAL]
        assert "SUCURSAL A / 1" in claves
        assert "SUCURSAL B / 1" in claves
        assert len(set(claves)) == 4

    def test_drop_size_es_bultos_sobre_visitas_facturadas(self):
        tabla = resumir_rutas(self._rutas()).set_index("Clave Ruta")
        assert tabla.loc["SUCURSAL A / 1", "Drop Size (bultos/visita)"] == pytest.approx(1.0)
        assert tabla.loc["SUCURSAL B / 1", "Drop Size (bultos/visita)"] == pytest.approx(10.0)
        assert tabla.loc["SUCURSAL A / 1", "Neto por Visita (Nominal $)"] == pytest.approx(10.0)

    def test_marca_baja_densidad_al_cuartil_inferior(self):
        tabla = resumir_rutas(self._rutas()).set_index("Clave Ruta")
        # Drops 1 / 4 / 5 / 10 -> p25 = 3,25, solo la primera queda abajo
        assert tabla.loc["SUCURSAL A / 1", "Densidad"].startswith("Baja densidad")
        assert tabla.loc["SUCURSAL A / 2", "Densidad"] == "Normal"
        assert tabla.loc["SUCURSAL B / 1", "Densidad"] == "Normal"

    def test_ordena_de_la_ruta_mas_barata_de_servir_a_la_mas_cara(self):
        tabla = resumir_rutas(self._rutas())
        assert tabla.iloc[0]["Clave Ruta"] == "SUCURSAL A / 1"

    def test_el_total_recalcula_el_drop_sobre_los_agregados(self):
        tabla = resumir_rutas(self._rutas())
        total = tabla.iloc[-1]
        assert total["Clave Ruta"] == ETIQUETA_TOTAL
        assert total["Visitas Facturadas"] == pytest.approx(400.0)
        assert total["Bultos"] == pytest.approx(2000.0)
        assert total["Drop Size (bultos/visita)"] == pytest.approx(5.0)
        assert total["Clientes Mostrador"] == pytest.approx(1.0)

    def test_rutas_vacias_devuelven_tabla_vacia(self):
        assert resumir_rutas(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# Formato de numeros en los textos
# ---------------------------------------------------------------------------
class TestFormatoNumerico:
    """Los textos de alertas van en formato argentino, sin romper la prosa."""

    def test_miles_con_punto_y_decimales_con_coma(self):
        assert _num(1234567.891, 2) == "1.234.567,89"
        assert _num(0.5, 1) == "0,5"

    def test_porcentaje_desde_una_fraccion(self):
        assert _pct(0.0847, 2) == "8,47%"

    def test_los_valores_no_finitos_no_ensucian_el_texto(self):
        assert _num(float("nan")) == "s/d"
        assert _pct(None) == "s/d"
