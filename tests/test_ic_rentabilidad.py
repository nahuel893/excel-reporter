"""Tests del modulo de rentabilidad de Inteligencia Comercial.

Todo se prueba con DataFrames chicos armados a mano y valores calculables con
lapiz y papel. No hay base de datos: cada transformacion es una funcion de nivel
de modulo que recibe DataFrames y devuelve DataFrames.
"""
import numpy as np
import pandas as pd
import pytest

from src.services.inteligencia_comercial import constants
from src.services.inteligencia_comercial.analytics import rentabilidad as rent
from src.services.inteligencia_comercial.excel_style import (
    FMT_DATE,
    FMT_MONEY,
    FMT_PCT1,
)
from src.services.inteligencia_comercial.sheet_writer import infer_format
from src.services.inteligencia_comercial.analytics.rentabilidad import (
    COLUMNAS_BAJO_COSTO,
    COLUMNAS_MARGEN,
    CONCEPTO_BRUTO,
    CONCEPTO_COMERCIAL,
    CONCEPTO_MEMO,
    CONCEPTO_NETO,
    CONCEPTO_RESIDUO,
    CONCEPTO_SIN_CARGO,
    ETIQUETA_TOTAL,
    PISO_CV_INFLACION,
    construir_bajo_costo,
    construir_cascada,
    construir_tabla_margen,
    detectar_fuga_outliers,
    mad_ponderada,
    panel_constante_por_anio,
    percentiles_ponderados,
    preparar_entidades_fuga,
    rankear_dispersion,
    resumir_bajo_costo,
    resumir_celdas_precio,
    resumir_margen,
)


# ---------------------------------------------------------------------------
# percentiles_ponderados / mad_ponderada
# ---------------------------------------------------------------------------
class TestPercentilesPonderados:
    def test_mediana_de_valores_con_peso_uno_es_la_mediana_clasica(self):
        # 5 valores con peso 1: la mediana es el valor del medio.
        valores = [0.10, 0.20, 0.30, 0.40, 0.50]
        assert percentiles_ponderados(valores, [1, 1, 1, 1, 1], [0.5])[0] == pytest.approx(0.30)

    def test_el_peso_desplaza_la_mediana_hacia_el_valor_mas_frecuente(self):
        # 97 lineas al 10% y 3 lineas al 90%: la mediana tiene que quedar en 10%,
        # igual que PERCENTILE_CONT sobre las 100 lineas crudas.
        assert percentiles_ponderados([0.10, 0.90], [97, 3], [0.5])[0] == pytest.approx(0.10)

    def test_reproduce_percentile_cont_sobre_los_datos_crudos(self):
        # El histograma tiene que dar lo mismo que expandir las observaciones.
        crudo = [0.10] * 7 + [0.25] * 3 + [0.40] * 5
        histograma = percentiles_ponderados([0.10, 0.25, 0.40], [7, 3, 5], [0.25, 0.5, 0.75])
        esperado = np.percentile(crudo, [25, 50, 75])
        assert histograma == pytest.approx(esperado)

    def test_dos_valores_con_igual_peso_interpolan_al_medio(self):
        # Con pesos 1 y 1 las posiciones son 0.25 y 0.75; el cuantil 0.5 cae justo
        # en el medio de 0.20 y 0.40.
        assert percentiles_ponderados([0.20, 0.40], [1, 1], [0.5])[0] == pytest.approx(0.30)

    def test_devuelve_varios_cuantiles_en_orden(self):
        resultado = percentiles_ponderados([1.0, 2.0, 3.0, 4.0], [1, 1, 1, 1], [0.25, 0.75])
        assert resultado[0] < resultado[1]

    def test_sin_pesos_positivos_devuelve_nan(self):
        resultado = percentiles_ponderados([0.1, 0.2], [0, 0], [0.5])
        assert np.isnan(resultado[0])

    def test_serie_vacia_devuelve_nan_por_cuantil(self):
        resultado = percentiles_ponderados([], [], [0.25, 0.5, 0.75])
        assert len(resultado) == 3
        assert np.isnan(resultado).all()

    def test_ignora_valores_no_finitos(self):
        assert percentiles_ponderados([0.10, np.nan, 0.10], [1, 5, 1], [0.5])[0] == pytest.approx(0.10)


class TestMadPonderada:
    def test_serie_constante_da_mad_cero(self):
        assert mad_ponderada([0.25, 0.25, 0.25], [10, 5, 1]) == pytest.approx(0.0)

    def test_mad_de_una_serie_simetrica(self):
        # Valores 1,2,3,4,5 con peso 1: mediana 3, desvios 2,1,0,1,2 -> mediana 1.
        assert mad_ponderada([1, 2, 3, 4, 5], [1, 1, 1, 1, 1]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# margen
# ---------------------------------------------------------------------------
def _grilla_margen():
    """Histograma minimo: dos genericos, dos anios, margenes conocidos.

    CERVEZAS: 100 lineas al 30% de margen (venta 1000, costo 700).
    VINOS   : 100 lineas al 10% (venta 500, costo 450) y 100 al -10% bajo costo
              (venta 100, costo 110).
    """
    return pd.DataFrame(
        [
            {
                "anio": 2025, "generico": "CERVEZAS", "marca": "SALTA",
                "sucursal": "CASA CENTRAL", "subcanal": "ALMACEN",
                "margen_linea": 0.30, "lineas": 100, "bultos": 500.0,
                "venta": 1000.0, "costo": 700.0,
                "lineas_bajo_costo": 0, "perdida_bajo_costo": 0.0,
            },
            {
                "anio": 2026, "generico": "VINOS", "marca": "TORO",
                "sucursal": "SUCURSAL METAN", "subcanal": "KIOSCO",
                "margen_linea": 0.10, "lineas": 100, "bultos": 200.0,
                "venta": 500.0, "costo": 450.0,
                "lineas_bajo_costo": 0, "perdida_bajo_costo": 0.0,
            },
            {
                "anio": 2026, "generico": "VINOS", "marca": "TORO",
                "sucursal": "SUCURSAL METAN", "subcanal": "KIOSCO",
                "margen_linea": -0.10, "lineas": 100, "bultos": 100.0,
                "venta": 100.0, "costo": 110.0,
                "lineas_bajo_costo": 100, "perdida_bajo_costo": -10.0,
            },
        ]
    )


class TestResumirMargen:
    def test_margen_ponderado_usa_venta_y_costo_no_el_promedio_de_lineas(self):
        # VINOS: venta 600, costo 560 -> (600-560)/600 = 6.67%. El promedio simple
        # de los margenes por linea daria 0%, que es la respuesta equivocada.
        tabla = resumir_margen(_grilla_margen(), "generico", "Generico")
        vinos = tabla[tabla["Valor"] == "VINOS"].iloc[0]
        assert vinos["Margen Ponderado %"] == pytest.approx(40.0 / 600.0)

    def test_suma_lineas_bultos_venta_y_costo_del_grupo(self):
        tabla = resumir_margen(_grilla_margen(), "generico", "Generico")
        vinos = tabla[tabla["Valor"] == "VINOS"].iloc[0]
        assert vinos["Lineas"] == pytest.approx(200.0)
        assert vinos["Bultos"] == pytest.approx(300.0)
        assert vinos["Venta Neta Nominal $"] == pytest.approx(600.0)
        assert vinos["Costo Nominal $"] == pytest.approx(560.0)
        assert vinos["Margen Bruto Nominal $"] == pytest.approx(40.0)

    def test_porcentaje_de_lineas_bajo_costo(self):
        # VINOS: 100 de 200 lineas bajo costo = 50%.
        tabla = resumir_margen(_grilla_margen(), "generico", "Generico")
        vinos = tabla[tabla["Valor"] == "VINOS"].iloc[0]
        assert vinos["% Lineas Bajo Costo"] == pytest.approx(0.5)
        assert vinos["Perdida Bajo Costo $"] == pytest.approx(-10.0)

    def test_dispersion_reportada_con_percentiles_y_mad(self):
        # VINOS tiene la mitad de las lineas en -0.10 y la mitad en 0.10:
        # la mediana cae en 0 y el MAD en 0.10.
        tabla = resumir_margen(_grilla_margen(), "generico", "Generico")
        vinos = tabla[tabla["Valor"] == "VINOS"].iloc[0]
        assert vinos["Margen Mediano Linea %"] == pytest.approx(0.0)
        assert vinos["MAD Margen Linea %"] == pytest.approx(0.10)
        assert vinos["Rango Intercuartil %"] == pytest.approx(
            vinos["Margen p75 Linea %"] - vinos["Margen p25 Linea %"]
        )

    def test_generico_de_una_sola_linea_reporta_su_propio_margen(self):
        tabla = resumir_margen(_grilla_margen(), "generico", "Generico")
        cervezas = tabla[tabla["Valor"] == "CERVEZAS"].iloc[0]
        assert cervezas["Margen Ponderado %"] == pytest.approx(0.30)
        assert cervezas["Margen Mediano Linea %"] == pytest.approx(0.30)

    def test_grilla_vacia_devuelve_tabla_vacia_sin_romper(self):
        assert resumir_margen(pd.DataFrame(), "generico", "Generico").empty


class TestConstruirTablaMargen:
    def test_incluye_las_cinco_dimensiones_y_el_total(self):
        tabla = construir_tabla_margen(_grilla_margen())
        assert set(tabla["Dimension"]) == {"Anio", "Generico", "Marca", "Sucursal", "Subcanal", "Total"}

    def test_el_total_general_no_es_la_suma_de_los_bloques(self):
        # Cinco dimensiones sobre la misma base: sumar los bloques quintuplicaria
        # la facturacion. El total se recalcula sobre la grilla completa.
        tabla = construir_tabla_margen(_grilla_margen())
        total = tabla[tabla["Valor"] == ETIQUETA_TOTAL].iloc[0]
        assert total["Venta Neta Nominal $"] == pytest.approx(1600.0)
        assert total["Costo Nominal $"] == pytest.approx(1260.0)
        assert total["Margen Ponderado %"] == pytest.approx(340.0 / 1600.0)

    def test_hay_exactamente_una_fila_total_general(self):
        tabla = construir_tabla_margen(_grilla_margen())
        assert (tabla["Valor"] == ETIQUETA_TOTAL).sum() == 1

    def test_recorta_las_marcas_al_tope_pedido(self):
        grilla = _grilla_margen()
        tabla = construir_tabla_margen(grilla, top_marcas=1)
        assert (tabla["Dimension"] == "Marca").sum() == 1

    def test_las_marcas_quedan_ordenadas_por_venta_despues_del_recorte(self):
        # El recorte es por bultos, pero el bloque se presenta por venta: TORO
        # mueve menos bultos que SALTA y tambien menos venta, asi que va segundo.
        grilla = _grilla_margen()
        marcas = construir_tabla_margen(grilla)
        marcas = marcas[marcas["Dimension"] == "Marca"]
        ventas = list(marcas["Venta Neta Nominal $"])
        assert ventas == sorted(ventas, reverse=True)

    def test_cuenta_las_sucursales_de_cada_corte(self):
        tabla = construir_tabla_margen(_grilla_margen())
        total = tabla[tabla["Valor"] == ETIQUETA_TOTAL].iloc[0]
        # CASA CENTRAL y SUCURSAL METAN.
        assert total["Sucursales"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# panel constante de sucursales (trampa de composicion de la red)
# ---------------------------------------------------------------------------
def _grilla_red_creciendo():
    """2022 factura una sola sucursal; 2023 facturan dos.

    CASA CENTRAL: 2022 venta 1000 / costo 700 (30%), 2023 venta 1000 / costo 750 (25%).
    SUCURSAL METAN aparece recien en 2023 con venta 1000 / costo 900 (10%).

    Sin corregir, el margen cae de 30% a 17,5%. En el panel constante (solo CASA
    CENTRAL, la unica presente en los dos anios) cae de 30% a 25%: mas de la mitad
    de la caida aparente es apertura de sucursales, no gestion.
    """
    def fila(anio, sucursal, venta, costo, margen):
        return {
            "anio": anio, "generico": "CERVEZAS", "marca": "SALTA",
            "sucursal": sucursal, "subcanal": "ALMACEN",
            "margen_linea": margen, "lineas": 10, "bultos": 100.0,
            "venta": venta, "costo": costo,
            "lineas_bajo_costo": 0, "perdida_bajo_costo": 0.0,
        }

    return pd.DataFrame(
        [
            fila(2022, "CASA CENTRAL", 1000.0, 700.0, 0.30),
            fila(2023, "CASA CENTRAL", 1000.0, 750.0, 0.25),
            fila(2023, "SUCURSAL METAN", 1000.0, 900.0, 0.10),
        ]
    )


class TestPanelConstantePorAnio:
    def test_el_panel_son_las_sucursales_presentes_en_todos_los_anios(self):
        panel = panel_constante_por_anio(_grilla_red_creciendo())
        assert list(panel["sucursales_panel"]) == [1.0, 1.0]
        assert list(panel["sucursales_anio"]) == [1.0, 2.0]

    def test_el_margen_del_panel_ignora_las_sucursales_nuevas(self):
        panel = panel_constante_por_anio(_grilla_red_creciendo()).set_index("anio")
        assert panel.loc[2022, "margen_panel"] == pytest.approx(0.30)
        assert panel.loc[2023, "margen_panel"] == pytest.approx(0.25)

    def test_grilla_vacia_devuelve_panel_vacio(self):
        assert panel_constante_por_anio(pd.DataFrame()).empty


class TestComposicionAnualEnLaTablaDeMargen:
    def test_el_anio_de_red_incompleta_queda_marcado(self):
        tabla = construir_tabla_margen(_grilla_red_creciendo())
        anios = tabla[tabla["Dimension"] == "Anio"].set_index("Valor")
        assert "RED INCOMPLETA" in anios.loc["2022", "Observacion"]
        assert anios.loc["2023", "Observacion"] == ""

    def test_el_margen_sin_corregir_exagera_la_caida(self):
        tabla = construir_tabla_margen(_grilla_red_creciendo())
        anios = tabla[tabla["Dimension"] == "Anio"].set_index("Valor")
        # Serie cruda: 30% -> 17,5% (2000 de venta contra 1650 de costo).
        assert anios.loc["2022", "Margen Ponderado %"] == pytest.approx(0.30)
        assert anios.loc["2023", "Margen Ponderado %"] == pytest.approx(0.175)
        # Panel constante: 30% -> 25%.
        assert anios.loc["2022", "Margen Panel Constante %"] == pytest.approx(0.30)
        assert anios.loc["2023", "Margen Panel Constante %"] == pytest.approx(0.25)

    def test_el_panel_constante_solo_se_completa_en_el_bloque_anio(self):
        tabla = construir_tabla_margen(_grilla_red_creciendo())
        fuera = tabla[tabla["Dimension"] != "Anio"]
        assert fuera["Margen Panel Constante %"].isna().all()


# ---------------------------------------------------------------------------
# bajo costo
# ---------------------------------------------------------------------------
def _detalle_bajo_costo():
    """Tres casos: uno normal, uno de mostrador y uno con costo implausible."""
    return pd.DataFrame(
        [
            {
                "anio": 2025, "sucursal": "CASA CENTRAL",
                "id_cliente": 5000, "cliente": "ALMACEN DON JOSE",
                "id_articulo": 10, "articulo": "SALTA RUBIA 1200*10",
                "lineas": 4, "bultos": 100.0, "venta": 1000.0, "costo": 1200.0,
                "primera": "2025-03-01", "ultima": "2025-08-15",
            },
            {
                "anio": 2025, "sucursal": "CASA CENTRAL",
                "id_cliente": 207603, "cliente": "GARCIA JORGE ALBERTO",
                "id_articulo": 20, "articulo": "SIDRA REAL 1888 750*6",
                "lineas": 2, "bultos": 50.0, "venta": 500.0, "costo": 1000.0,
                "primera": "2025-09-23", "ultima": "2025-09-23",
            },
            {
                "anio": 2026, "sucursal": "SUCURSAL METAN",
                "id_cliente": 100, "cliente": "CONSUMIDOR FINAL",
                "id_articulo": 30, "articulo": "CANCILLER BLEND 1125*6",
                "lineas": 1, "bultos": 2.0, "venta": 10.0, "costo": 5000.0,
                "primera": "2026-01-20", "ultima": "2026-01-20",
            },
        ]
    )


class TestResumirBajoCosto:
    def test_la_perdida_es_venta_menos_costo_y_es_negativa(self):
        tabla = resumir_bajo_costo(_detalle_bajo_costo(), ["anio"], "Anio")
        anio_2025 = tabla[tabla["Valor"] == "2025"].iloc[0]
        # 1000 + 500 de venta contra 1200 + 1000 de costo.
        assert anio_2025["Perdida $"] == pytest.approx(-700.0)
        assert anio_2025["Margen Ponderado %"] == pytest.approx(-700.0 / 1500.0)

    def test_ordena_de_la_perdida_mas_grande_a_la_mas_chica(self):
        tabla = resumir_bajo_costo(_detalle_bajo_costo(), ["sucursal"], "Sucursal")
        assert tabla.iloc[0]["Valor"] == "SUCURSAL METAN"  # -4990 contra -700

    def test_la_etiqueta_del_cliente_lleva_el_id_pegado(self):
        tabla = resumir_bajo_costo(_detalle_bajo_costo(), ["id_cliente", "cliente"], "Cliente")
        assert "ALMACEN DON JOSE (5000)" in set(tabla["Valor"])

    def test_marca_los_ids_consecutivos_para_verificar_antes_de_accionar(self):
        tabla = resumir_bajo_costo(_detalle_bajo_costo(), ["id_cliente", "cliente"], "Cliente")
        fila = tabla[tabla["Valor"].str.contains("207603")].iloc[0]
        assert "VERIFICAR ANTES DE ACCIONAR" in fila["Observacion"]
        assert "un solo dia" in fila["Observacion"]

    def test_marca_los_clientes_de_mostrador(self):
        assert 100 in constants.CLIENTES_MOSTRADOR
        tabla = resumir_bajo_costo(_detalle_bajo_costo(), ["id_cliente", "cliente"], "Cliente")
        fila = tabla[tabla["Valor"].str.contains("(100)", regex=False)].iloc[0]
        assert "MOSTRADOR" in fila["Observacion"]

    def test_marca_el_costo_implausible_como_problema_de_sistemas(self):
        # Costo 5000 contra venta 10: 500x. Eso no es politica comercial.
        tabla = resumir_bajo_costo(_detalle_bajo_costo(), ["id_articulo", "articulo"], "Articulo")
        fila = tabla[tabla["Valor"].str.contains("CANCILLER")].iloc[0]
        assert "COSTO IMPLAUSIBLE" in fila["Observacion"]

    def test_no_marca_costo_implausible_en_filas_agregadas(self):
        # Que un anio entero acumule costo mayor al doble de la venta bajo costo
        # es aritmetica del agregado, no un registro mal cargado.
        tabla = resumir_bajo_costo(_detalle_bajo_costo(), ["anio"], "Anio")
        fila = tabla[tabla["Valor"] == "2026"].iloc[0]
        assert fila["Costo Nominal $"] > 2 * fila["Venta Nominal $"]
        assert "COSTO IMPLAUSIBLE" not in fila["Observacion"]

    def test_no_marca_costo_implausible_cuando_la_diferencia_es_comercial(self):
        tabla = resumir_bajo_costo(_detalle_bajo_costo(), ["id_articulo", "articulo"], "Articulo")
        fila = tabla[tabla["Valor"].str.contains("SALTA RUBIA")].iloc[0]
        assert "COSTO IMPLAUSIBLE" not in fila["Observacion"]

    def test_respeta_el_tope_de_ofensores(self):
        tabla = resumir_bajo_costo(_detalle_bajo_costo(), ["id_cliente", "cliente"], "Cliente", top=2)
        assert len(tabla) == 2


class TestConstruirBajoCosto:
    def test_total_general_se_calcula_sobre_el_detalle_no_sumando_bloques(self):
        tabla = construir_bajo_costo(_detalle_bajo_costo())
        total = tabla[tabla["Valor"] == ETIQUETA_TOTAL].iloc[0]
        assert total["Venta Nominal $"] == pytest.approx(1510.0)
        assert total["Costo Nominal $"] == pytest.approx(7200.0)
        assert total["Perdida $"] == pytest.approx(-5690.0)
        assert total["Lineas"] == pytest.approx(7.0)

    def test_el_total_cubre_el_rango_de_fechas_completo(self):
        total = construir_bajo_costo(_detalle_bajo_costo())
        fila = total[total["Valor"] == ETIQUETA_TOTAL].iloc[0]
        assert fila["Primera Fecha"] == "2025-03-01"
        assert fila["Ultima Fecha"] == "2026-01-20"

    def test_detalle_vacio_devuelve_tabla_vacia(self):
        assert construir_bajo_costo(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# cascada de descuentos
# ---------------------------------------------------------------------------
def _base_cascada():
    """Bruto 1000, sin cargo a lista 100, descuentos 250, neto 750: cierra exacto."""
    return pd.DataFrame(
        [
            {
                "sucursal": "CASA CENTRAL", "generico": "CERVEZAS",
                "bruto": 800.0, "descuentos": 200.0, "neto": 600.0,
                "sin_cargo_lista": 80.0, "q_sin_cargo": 8.0, "q_con_cargo": 60.0,
            },
            {
                "sucursal": "SUCURSAL METAN", "generico": "CERVEZAS",
                "bruto": 200.0, "descuentos": 50.0, "neto": 150.0,
                "sin_cargo_lista": 20.0, "q_sin_cargo": 2.0, "q_con_cargo": 15.0,
            },
        ]
    )


class TestConstruirCascada:
    def test_el_recorrido_del_total_cierra_en_el_neto(self):
        tabla = construir_cascada(_base_cascada())
        total = tabla[tabla["ambito"] == ETIQUETA_TOTAL].set_index("concepto")
        assert total.loc[CONCEPTO_BRUTO, "monto"] == pytest.approx(1000.0)
        assert total.loc[CONCEPTO_SIN_CARGO, "monto"] == pytest.approx(100.0)
        assert total.loc[CONCEPTO_COMERCIAL, "monto"] == pytest.approx(150.0)
        assert total.loc[CONCEPTO_NETO, "monto"] == pytest.approx(750.0)

    def test_el_descuento_comercial_no_cuenta_dos_veces_la_mercaderia_sin_cargo(self):
        # descuentos totales 250, de los cuales 100 son mercaderia regalada:
        # el escalon comercial tiene que ser 150, no 250.
        tabla = construir_cascada(_base_cascada())
        total = tabla[tabla["ambito"] == ETIQUETA_TOTAL].set_index("concepto")
        assert total.loc[CONCEPTO_COMERCIAL, "monto"] == pytest.approx(150.0)

    def test_la_base_acumulada_baja_escalon_por_escalon(self):
        tabla = construir_cascada(_base_cascada())
        total = tabla[tabla["ambito"] == ETIQUETA_TOTAL].set_index("concepto")
        assert total.loc[CONCEPTO_BRUTO, "base_acumulada"] == pytest.approx(1000.0)
        assert total.loc[CONCEPTO_SIN_CARGO, "base_acumulada"] == pytest.approx(900.0)
        assert total.loc[CONCEPTO_COMERCIAL, "base_acumulada"] == pytest.approx(750.0)
        assert total.loc[CONCEPTO_NETO, "base_acumulada"] == pytest.approx(750.0)

    def test_los_escalones_de_descuento_estan_marcados_como_resta(self):
        tabla = construir_cascada(_base_cascada())
        total = tabla[tabla["ambito"] == ETIQUETA_TOTAL].set_index("concepto")
        assert bool(total.loc[CONCEPTO_SIN_CARGO, "es_resta"]) is True
        assert bool(total.loc[CONCEPTO_COMERCIAL, "es_resta"]) is True
        assert bool(total.loc[CONCEPTO_BRUTO, "es_resta"]) is False
        assert bool(total.loc[CONCEPTO_NETO, "es_resta"]) is False

    def test_el_residuo_es_cero_cuando_la_identidad_cierra(self):
        tabla = construir_cascada(_base_cascada())
        total = tabla[tabla["ambito"] == ETIQUETA_TOTAL].set_index("concepto")
        assert total.loc[CONCEPTO_RESIDUO, "monto"] == pytest.approx(0.0)

    def test_el_residuo_expone_la_identidad_que_no_cierra(self):
        # Neto 900 contra bruto 1000 menos descuentos 250: sobran 150.
        base = pd.DataFrame(
            [{
                "sucursal": "SUCURSAL PERICO", "generico": "CERVEZAS",
                "bruto": 1000.0, "descuentos": 250.0, "neto": 900.0,
                "sin_cargo_lista": 100.0, "q_sin_cargo": 10.0, "q_con_cargo": 90.0,
            }]
        )
        total = construir_cascada(base).set_index("concepto")
        residuo = total.loc[CONCEPTO_RESIDUO]
        assert residuo["monto"].iloc[0] == pytest.approx(150.0)
        assert bool(residuo["es_resta"].iloc[0]) is False

    def test_el_memo_valua_lo_sin_cargo_al_precio_realizado(self):
        # Neto 750 sobre 75 bultos con cargo -> $10/bulto. 10 bultos sin cargo = $100.
        tabla = construir_cascada(_base_cascada())
        total = tabla[tabla["ambito"] == ETIQUETA_TOTAL].set_index("concepto")
        assert total.loc[CONCEPTO_MEMO, "monto"] == pytest.approx(100.0)

    def test_abre_por_sucursal_y_por_generico(self):
        tabla = construir_cascada(_base_cascada())
        ambitos = set(tabla["ambito"])
        assert "Sucursal: CASA CENTRAL" in ambitos
        assert "Sucursal: SUCURSAL METAN" in ambitos
        assert "Generico: CERVEZAS" in ambitos

    def test_el_pct_bruto_del_neto_es_la_realizacion(self):
        tabla = construir_cascada(_base_cascada())
        total = tabla[tabla["ambito"] == ETIQUETA_TOTAL].set_index("concepto")
        assert total.loc[CONCEPTO_NETO, "pct_bruto"] == pytest.approx(0.75)

    def test_base_vacia_devuelve_tabla_vacia(self):
        assert construir_cascada(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# fuga de descuentos
# ---------------------------------------------------------------------------
# Tasas de una poblacion sana: mediana 10%, MAD 1 punto (sigma robusta 1,4826
# puntos). Un cliente al 50% queda a z = 0,40 / 0,014826 = 27, muy por encima de
# 3,5; el que esta al 12% queda a z = 1,35 y NO es outlier.
_TASAS_SANAS = [0.08, 0.09, 0.09, 0.10, 0.10, 0.10, 0.10, 0.11, 0.11, 0.12]


def _clientes_sanos(bruto: float = 1_000_000.0) -> list[dict]:
    return [
        {
            "entidad": f"CLIENTE {i}", "tipo": "Cliente", "sucursal": "CASA CENTRAL",
            "bruto": bruto, "descuento": bruto * tasa, "lineas": 50.0, "observacion": "",
        }
        for i, tasa in enumerate(_TASAS_SANAS)
    ]


def _entidades_fuga():
    """Diez clientes alrededor del 10% de descuento y uno al 50%: ese es el outlier."""
    filas = _clientes_sanos()
    filas.append(
        {
            "entidad": "DERROCHADOR SRL", "tipo": "Cliente", "sucursal": "CASA CENTRAL",
            "bruto": 1_000_000.0, "descuento": 500_000.0, "lineas": 50.0, "observacion": "",
        }
    )
    return pd.DataFrame(filas)


class TestDetectarFugaOutliers:
    def test_aisla_solo_a_la_entidad_desviada(self):
        tabla = detectar_fuga_outliers(_entidades_fuga())
        cuerpo = tabla[~tabla["entidad"].astype(str).str.startswith(("SUBTOTAL", ETIQUETA_TOTAL))]
        assert list(cuerpo["entidad"]) == ["DERROCHADOR SRL"]

    def test_la_tasa_es_descuento_sobre_bruto(self):
        tabla = detectar_fuga_outliers(_entidades_fuga())
        assert tabla.iloc[0]["tasa"] == pytest.approx(0.50)

    def test_el_exceso_es_la_plata_por_encima_de_la_tasa_mediana(self):
        # Mediana 10%, tasa 50%, bruto 1.000.000 -> 400.000 de descuento de mas.
        tabla = detectar_fuga_outliers(_entidades_fuga())
        assert tabla.iloc[0]["exceso_vs_mediana"] == pytest.approx(400_000.0)

    def test_una_poblacion_sin_desviados_no_produce_outliers(self):
        assert detectar_fuga_outliers(pd.DataFrame(_clientes_sanos())).empty

    def test_una_poblacion_perfectamente_constante_no_inventa_outliers(self):
        # Con MAD cero la sigma robusta colapsa: stats.robust_zscore devuelve
        # ceros y el modulo prefiere no reportar nada antes que reportar falsos.
        constantes = pd.DataFrame(
            [
                {
                    "entidad": f"CLIENTE {i}", "tipo": "Cliente", "sucursal": "CASA CENTRAL",
                    "bruto": 1_000_000.0, "descuento": 100_000.0, "lineas": 50.0, "observacion": "",
                }
                for i in range(10)
            ]
        )
        assert detectar_fuga_outliers(constantes).empty

    def test_ordena_por_exceso_descendente(self):
        entidades = _entidades_fuga()
        entidades.loc[len(entidades)] = {
            "entidad": "DERROCHADOR MENOR", "tipo": "Cliente", "sucursal": "CASA CENTRAL",
            "bruto": 100_000.0, "descuento": 50_000.0, "lineas": 50.0, "observacion": "",
        }
        tabla = detectar_fuga_outliers(entidades)
        cuerpo = tabla[~tabla["entidad"].astype(str).str.startswith(("SUBTOTAL", ETIQUETA_TOTAL))]
        assert list(cuerpo["entidad"]) == ["DERROCHADOR SRL", "DERROCHADOR MENOR"]

    def test_cada_tipo_se_compara_contra_su_propia_mediana(self):
        # Los preventistas viven al 40%: un cliente al 50% es outlier de clientes,
        # pero un preventista al 40% no lo es de preventistas.
        entidades = _entidades_fuga()
        preventistas = pd.DataFrame(
            [
                {
                    "entidad": f"PREVENTISTA {i}", "tipo": "Preventista", "sucursal": "CASA CENTRAL",
                    "bruto": 50_000_000.0, "descuento": 50_000_000.0 * (tasa + 0.30),
                    "lineas": 900.0, "observacion": "",
                }
                for i, tasa in enumerate(_TASAS_SANAS)
            ]
        )
        tabla = detectar_fuga_outliers(pd.concat([entidades, preventistas], ignore_index=True))
        cuerpo = tabla[~tabla["entidad"].astype(str).str.startswith(("SUBTOTAL", ETIQUETA_TOTAL))]
        assert set(cuerpo["tipo"]) == {"Cliente"}

    def test_avisa_cuando_el_descuento_se_come_casi_toda_la_factura(self):
        entidades = _entidades_fuga()
        entidades.loc[entidades["entidad"] == "DERROCHADOR SRL", "descuento"] = 980_000.0
        tabla = detectar_fuga_outliers(entidades)
        assert "90%" in tabla.iloc[0]["observacion"]

    def test_el_total_no_suma_bruto_ni_descuento_entre_vistas(self):
        tabla = detectar_fuga_outliers(_entidades_fuga())
        total = tabla[tabla["entidad"] == ETIQUETA_TOTAL].iloc[0]
        assert total["exceso_vs_mediana"] == pytest.approx(400_000.0)
        assert np.isnan(total["bruto"])
        assert np.isnan(total["descuento"])

    def test_el_total_informa_la_vista_cliente_y_no_suma_la_del_preventista(self):
        # Cliente y preventista son dos particiones de la MISMA venta: el exceso del
        # cliente ya esta adentro del de su preventista. Sumarlos daria 400.000 +
        # 5.000.000 = 5.400.000 de plata que no existe dos veces.
        entidades = _entidades_fuga()
        preventistas = pd.DataFrame(
            [
                {
                    "entidad": f"PREVENTISTA {i}", "tipo": "Preventista", "sucursal": "CASA CENTRAL",
                    "bruto": 50_000_000.0, "descuento": 50_000_000.0 * tasa,
                    "lineas": 900.0, "observacion": "",
                }
                for i, tasa in enumerate(_TASAS_SANAS)
            ]
            + [
                {
                    "entidad": "PREVENTISTA DERROCHADOR", "tipo": "Preventista",
                    "sucursal": "CASA CENTRAL", "bruto": 50_000_000.0,
                    "descuento": 50_000_000.0 * 0.20, "lineas": 900.0, "observacion": "",
                }
            ]
        )
        tabla = detectar_fuga_outliers(pd.concat([entidades, preventistas], ignore_index=True))
        indexada = tabla.set_index("entidad")
        # Mediana de preventistas 10%, el desviado al 20% sobre 50M -> 5.000.000.
        assert indexada.loc["SUBTOTAL Preventista", "exceso_vs_mediana"] == pytest.approx(5_000_000.0)
        assert indexada.loc["SUBTOTAL Cliente", "exceso_vs_mediana"] == pytest.approx(400_000.0)
        total = indexada.loc[ETIQUETA_TOTAL, "exceso_vs_mediana"]
        assert total == pytest.approx(400_000.0)
        assert total != pytest.approx(5_400_000.0)

    def test_el_total_avisa_que_la_vista_preventista_es_la_misma_plata(self):
        entidades = _entidades_fuga()
        preventistas = pd.DataFrame(
            [
                {
                    "entidad": f"PREVENTISTA {i}", "tipo": "Preventista", "sucursal": "CASA CENTRAL",
                    "bruto": 50_000_000.0, "descuento": 50_000_000.0 * tasa,
                    "lineas": 900.0, "observacion": "",
                }
                for i, tasa in enumerate(_TASAS_SANAS + [0.20])
            ]
        )
        tabla = detectar_fuga_outliers(pd.concat([entidades, preventistas], ignore_index=True))
        total = tabla[tabla["entidad"] == ETIQUETA_TOTAL].iloc[0]
        assert "MISMA plata" in total["observacion"]
        assert "NO se suma" in total["observacion"]

    def test_agrega_subtotal_por_tipo(self):
        tabla = detectar_fuga_outliers(_entidades_fuga())
        assert "SUBTOTAL Cliente" in set(tabla["entidad"])

    def test_el_subtotal_advierte_que_no_se_suma_contra_el_otro(self):
        tabla = detectar_fuga_outliers(_entidades_fuga())
        fila = tabla[tabla["entidad"] == "SUBTOTAL Cliente"].iloc[0]
        assert "NO sumar" in fila["observacion"]

    def test_el_corte_es_solo_de_cola_alta(self):
        # Quien descuenta MUY POR DEBAJO de la mediana no es una fuga: no puede
        # entrar a la lista de auditoria de descuentos.
        entidades = _entidades_fuga()
        entidades.loc[len(entidades)] = {
            "entidad": "TACANO SA", "tipo": "Cliente", "sucursal": "CASA CENTRAL",
            "bruto": 1_000_000.0, "descuento": 0.0, "lineas": 50.0, "observacion": "",
        }
        tabla = detectar_fuga_outliers(entidades)
        assert "TACANO SA" not in set(tabla["entidad"])

    def test_entrada_vacia_devuelve_tabla_vacia(self):
        assert detectar_fuga_outliers(pd.DataFrame()).empty


class TestPrepararEntidadesFuga:
    def test_arma_clientes_y_preventistas_desde_el_mismo_grano(self):
        base = pd.DataFrame(
            [
                {"id_cliente": 1, "id_vendedor": 7, "id_sucursal": 1,
                 "bruto": 10_000_000.0, "descuento": 1_000_000.0, "neto": 9_000_000.0, "lineas": 40},
                {"id_cliente": 2, "id_vendedor": 7, "id_sucursal": 1,
                 "bruto": 20_000_000.0, "descuento": 2_000_000.0, "neto": 18_000_000.0, "lineas": 60},
            ]
        )
        clientes = pd.DataFrame(
            [{"id_cliente": 1, "cliente": "UNO", "subcanal": "ALMACEN"},
             {"id_cliente": 2, "cliente": "DOS", "subcanal": "KIOSCO"}]
        )
        vendedores = pd.DataFrame(
            [{"id_vendedor": 7, "id_sucursal": 1, "vendedor": "ROSSI", "sucursal": "CASA CENTRAL"}]
        )
        sucursales = pd.DataFrame([{"id_sucursal": 1, "sucursal": "CASA CENTRAL"}])

        entidades = preparar_entidades_fuga(base, clientes, vendedores, sucursales)
        assert set(entidades["tipo"]) == {"Cliente", "Preventista"}
        # El preventista acumula el bruto de sus dos clientes.
        preventista = entidades[entidades["tipo"] == "Preventista"].iloc[0]
        assert preventista["bruto"] == pytest.approx(30_000_000.0)
        assert "ROSSI" in preventista["entidad"]
        assert "CASA CENTRAL" in preventista["entidad"]

    def test_el_mismo_id_vendedor_en_dos_sucursales_son_dos_entidades(self):
        # La regla de oro: id_vendedor se reusa entre sucursales.
        base = pd.DataFrame(
            [
                {"id_cliente": 1, "id_vendedor": 100, "id_sucursal": 1,
                 "bruto": 30_000_000.0, "descuento": 1_000_000.0, "neto": 29_000_000.0, "lineas": 40},
                {"id_cliente": 2, "id_vendedor": 100, "id_sucursal": 2,
                 "bruto": 40_000_000.0, "descuento": 2_000_000.0, "neto": 38_000_000.0, "lineas": 50},
            ]
        )
        clientes = pd.DataFrame(
            [{"id_cliente": 1, "cliente": "UNO", "subcanal": "ALMACEN"},
             {"id_cliente": 2, "cliente": "DOS", "subcanal": "KIOSCO"}]
        )
        vendedores = pd.DataFrame(
            [
                {"id_vendedor": 100, "id_sucursal": 1, "vendedor": "DIRECTA", "sucursal": "CASA CENTRAL"},
                {"id_vendedor": 100, "id_sucursal": 2, "vendedor": "DIRECTA", "sucursal": "SUCURSAL GUEMES"},
            ]
        )
        sucursales = pd.DataFrame(
            [{"id_sucursal": 1, "sucursal": "CASA CENTRAL"},
             {"id_sucursal": 2, "sucursal": "SUCURSAL GUEMES"}]
        )
        entidades = preparar_entidades_fuga(base, clientes, vendedores, sucursales)
        preventistas = entidades[entidades["tipo"] == "Preventista"]
        assert len(preventistas) == 2
        assert preventistas["bruto"].max() == pytest.approx(40_000_000.0)
        # DIRECTA es un canal, no una persona: tiene que quedar marcado.
        assert all("CANAL" in obs for obs in preventistas["observacion"])

    def test_filtra_por_materialidad(self):
        base = pd.DataFrame(
            [{"id_cliente": 1, "id_vendedor": 7, "id_sucursal": 1,
              "bruto": 1_000.0, "descuento": 100.0, "neto": 900.0, "lineas": 2}]
        )
        clientes = pd.DataFrame([{"id_cliente": 1, "cliente": "UNO", "subcanal": "ALMACEN"}])
        vendedores = pd.DataFrame(
            [{"id_vendedor": 7, "id_sucursal": 1, "vendedor": "ROSSI", "sucursal": "CASA CENTRAL"}]
        )
        sucursales = pd.DataFrame([{"id_sucursal": 1, "sucursal": "CASA CENTRAL"}])
        assert preparar_entidades_fuga(base, clientes, vendedores, sucursales).empty

    def test_marca_los_clientes_de_mostrador(self):
        id_mostrador = constants.CLIENTES_MOSTRADOR[0]
        base = pd.DataFrame(
            [{"id_cliente": id_mostrador, "id_vendedor": 7, "id_sucursal": 1,
              "bruto": 10_000_000.0, "descuento": 1_000_000.0, "neto": 9_000_000.0, "lineas": 40}]
        )
        clientes = pd.DataFrame(
            [{"id_cliente": id_mostrador, "cliente": "CONSUMIDOR FINAL", "subcanal": "ALMACEN"}]
        )
        vendedores = pd.DataFrame(
            [{"id_vendedor": 7, "id_sucursal": 1, "vendedor": "ROSSI", "sucursal": "CASA CENTRAL"}]
        )
        sucursales = pd.DataFrame([{"id_sucursal": 1, "sucursal": "CASA CENTRAL"}])
        entidades = preparar_entidades_fuga(base, clientes, vendedores, sucursales)
        cliente = entidades[entidades["tipo"] == "Cliente"].iloc[0]
        assert "MOSTRADOR" in cliente["observacion"]


# ---------------------------------------------------------------------------
# dispersion de precios
# ---------------------------------------------------------------------------
def _base_dispersion(precios, mes="2026-06-01", id_articulo=1, cantidad=10.0):
    """Una fila por cliente con el precio realizado que se le quiere imponer."""
    return pd.DataFrame(
        [
            {"mes": mes, "id_articulo": id_articulo, "id_cliente": 1000 + i,
             "neto": precio * cantidad, "q": cantidad}
            for i, precio in enumerate(precios)
        ]
    )


class TestResumirCeldasPrecio:
    def test_un_sku_de_precio_unico_devuelve_cv_cero(self):
        # La validacion del metodo: un retornable de precio unico no puede dar
        # dispersion. Si diera, el metodo estaria midiendo ruido propio.
        celdas = resumir_celdas_precio(_base_dispersion([100.0] * 30))
        assert celdas.iloc[0]["cv"] == pytest.approx(0.0)
        assert celdas.iloc[0]["ratio_p90_p10"] == pytest.approx(1.0)
        assert celdas.iloc[0]["brecha_vs_mediana"] == pytest.approx(0.0)

    def test_calcula_el_precio_realizado_como_neto_sobre_bultos(self):
        celdas = resumir_celdas_precio(_base_dispersion([100.0] * 30, cantidad=4.0))
        assert celdas.iloc[0]["p50"] == pytest.approx(100.0)
        assert celdas.iloc[0]["bultos"] == pytest.approx(120.0)
        assert celdas.iloc[0]["neto"] == pytest.approx(12_000.0)

    def test_ignora_las_celdas_con_pocos_clientes(self):
        assert resumir_celdas_precio(_base_dispersion([100.0] * 29)).empty

    def test_el_piso_de_clientes_es_configurable(self):
        celdas = resumir_celdas_precio(_base_dispersion([100.0] * 5), min_clientes=5)
        assert len(celdas) == 1

    def test_la_brecha_vs_mediana_cuenta_solo_a_los_que_pagaron_menos(self):
        # 20 clientes a $100 y 20 a $50, 10 bultos cada uno. Mediana $100 (numpy
        # interpola entre los dos centrales: 50 y 100 -> 75).
        celdas = resumir_celdas_precio(_base_dispersion([100.0] * 20 + [50.0] * 20))
        fila = celdas.iloc[0]
        assert fila["p50"] == pytest.approx(75.0)
        # Los 20 baratos pagaron 25 menos por bulto sobre 10 bultos cada uno.
        assert fila["brecha_vs_mediana"] == pytest.approx(20 * 25.0 * 10.0)

    def test_calcula_percentiles_y_ratio_de_la_banda(self):
        precios = [float(p) for p in range(100, 140)]  # 40 clientes, 100..139
        celdas = resumir_celdas_precio(_base_dispersion(precios))
        fila = celdas.iloc[0]
        assert fila["p10"] == pytest.approx(np.percentile(precios, 10))
        assert fila["p90"] == pytest.approx(np.percentile(precios, 90))
        assert fila["ratio_p90_p10"] == pytest.approx(fila["p90"] / fila["p10"])

    def test_base_vacia_devuelve_celdas_vacias(self):
        assert resumir_celdas_precio(pd.DataFrame()).empty


class TestRankearDispersion:
    def _celdas(self, cv_por_mes, bultos_por_mes, id_articulo=1):
        return pd.DataFrame(
            [
                {
                    "id_articulo": id_articulo, "mes": f"2026-0{i + 1}-01",
                    "clientes": 40.0, "bultos": bultos, "neto": bultos * 100.0,
                    "cv": cv, "p10": 90.0, "p50": 100.0, "p90": 110.0,
                    "ratio_p90_p10": 110.0 / 90.0, "brecha_vs_mediana": 1_000.0,
                }
                for i, (cv, bultos) in enumerate(zip(cv_por_mes, bultos_por_mes))
            ]
        )

    def test_el_cv_se_pondera_por_los_bultos_del_mes(self):
        # 0.10 con 900 bultos y 0.50 con 100: (0.10*900 + 0.50*100)/1000 = 0.14.
        celdas = self._celdas([0.10, 0.50, 0.10, 0.10], [900, 100, 900, 900])
        tabla = rankear_dispersion(celdas, pd.DataFrame(), min_bultos=100)
        fila = tabla[tabla["articulo"] != ETIQUETA_TOTAL].iloc[0]
        esperado = (0.10 * 900 + 0.50 * 100 + 0.10 * 900 + 0.10 * 900) / 2800
        assert fila["cv_ponderado_pct"] == pytest.approx(esperado)

    def test_la_banda_de_precios_sale_del_ultimo_mes_no_del_promedio(self):
        celdas = self._celdas([0.05] * 4, [100] * 4)
        celdas.loc[celdas.index[-1], ["p10", "p50", "p90"]] = [200.0, 210.0, 220.0]
        tabla = rankear_dispersion(celdas, pd.DataFrame(), min_bultos=100)
        fila = tabla[tabla["articulo"] != ETIQUETA_TOTAL].iloc[0]
        assert fila["mes_referencia"] == "2026-04-01"
        assert fila["precio_p50"] == pytest.approx(210.0)

    def test_descarta_articulos_con_pocos_meses(self):
        celdas = self._celdas([0.10] * 2, [1000] * 2)
        assert rankear_dispersion(celdas, pd.DataFrame(), min_meses=4).empty

    def test_descarta_articulos_sin_volumen_material(self):
        celdas = self._celdas([0.10] * 4, [10] * 4)
        assert rankear_dispersion(celdas, pd.DataFrame(), min_bultos=5_000).empty

    def test_el_cv_bajo_se_diagnostica_como_ruido_inflacionario(self):
        celdas = self._celdas([PISO_CV_INFLACION / 3] * 4, [1000] * 4)
        tabla = rankear_dispersion(celdas, pd.DataFrame(), min_bultos=100)
        fila = tabla[tabla["articulo"] != ETIQUETA_TOTAL].iloc[0]
        assert "Controlado" in fila["diagnostico"]

    def test_el_cv_alto_se_diagnostica_como_problema_de_precios(self):
        celdas = self._celdas([0.25] * 4, [1000] * 4)
        tabla = rankear_dispersion(celdas, pd.DataFrame(), min_bultos=100)
        fila = tabla[tabla["articulo"] != ETIQUETA_TOTAL].iloc[0]
        assert "Revisar" in fila["diagnostico"]

    def test_ordena_de_mayor_a_menor_dispersion(self):
        celdas = pd.concat(
            [
                self._celdas([0.05] * 4, [1000] * 4, id_articulo=1),
                self._celdas([0.30] * 4, [1000] * 4, id_articulo=2),
            ],
            ignore_index=True,
        )
        articulos = pd.DataFrame(
            [{"id_articulo": 1, "articulo": "CONTROLADO", "generico": "VINOS", "marca": "TORO"},
             {"id_articulo": 2, "articulo": "DISPERSO", "generico": "CERVEZAS", "marca": "SALTA"}]
        )
        tabla = rankear_dispersion(celdas, articulos, min_bultos=100)
        assert tabla.iloc[0]["articulo"] == "DISPERSO"

    def test_lleva_fila_total_general_con_la_brecha_acumulada(self):
        celdas = self._celdas([0.10] * 4, [1000] * 4)
        tabla = rankear_dispersion(celdas, pd.DataFrame(), min_bultos=100)
        total = tabla[tabla["articulo"] == ETIQUETA_TOTAL].iloc[0]
        assert total["brecha_vs_mediana_pesos"] == pytest.approx(4_000.0)
        assert total["bultos"] == pytest.approx(4_000.0)

    def test_celdas_vacias_devuelven_tabla_vacia(self):
        assert rankear_dispersion(pd.DataFrame(), pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# Formato de Excel inferido del nombre de la columna
#
# La hoja no recibe formatos de este modulo: los deduce del NOMBRE de cada
# columna (sheet_writer.infer_format). Por eso el nombre es parte del contrato y
# no un detalle cosmetico. Ya paso: 'Margen Ponderado' caia en el formato entero
# y un margen de 0,2027 se imprimia como "0" en la hoja que se lleva a la
# reunion, y 'meses' / 'clientes_mes_referencia' caian en formato fecha, con lo
# cual un conteo de 4 meses salia como 04/01/1900 y 341 clientes como 06/12/1900.
# ---------------------------------------------------------------------------
class TestFormatoInferidoDeLasColumnas:
    def test_toda_columna_de_ratio_sale_en_porcentaje(self):
        for columna in COLUMNAS_MARGEN + COLUMNAS_BAJO_COSTO:
            if "Margen" in columna and "$" not in columna:
                assert infer_format(columna) == FMT_PCT1, columna
            if columna in ("Rango Intercuartil %", "% Lineas Bajo Costo"):
                assert infer_format(columna) == FMT_PCT1, columna

    def test_ningun_conteo_termina_con_formato_de_fecha(self):
        for columna in ("cortes_mensuales", "clientes_en_el_corte", "Lineas", "Bultos",
                        "Sucursales", "lineas", "bultos"):
            assert infer_format(columna) != FMT_DATE, columna

    def test_los_precios_de_la_dispersion_salen_como_plata(self):
        for columna in ("precio_p10", "precio_p50", "precio_p90",
                        "brecha_vs_mediana_pesos", "neto_nominal"):
            assert infer_format(columna) == FMT_MONEY, columna

    def test_el_cv_sale_en_porcentaje_y_no_como_indice_suelto(self):
        assert infer_format("cv_ponderado_pct") == FMT_PCT1


# ---------------------------------------------------------------------------
# build() completo, con una base falsa
#
# Los tests de arriba prueban cada transformacion por separado y ninguno tocaba
# jamas la redaccion de alertas ni de notas. Por eso un simple cambio de nombre
# de columna dejo una referencia colgada en una alerta que solo estallaba contra
# la base real, y encima escapaba de build() porque el try/except cubria solo el
# SQL. Estas pruebas recorren el camino entero sin base de datos.
# ---------------------------------------------------------------------------
_COLUMNAS_SQL = {
    "grilla": ["anio", "generico", "marca", "sucursal", "subcanal", "margen_linea",
               "lineas", "bultos", "venta", "costo", "lineas_bajo_costo", "perdida_bajo_costo"],
    "bajo": ["anio", "sucursal", "id_cliente", "cliente", "id_articulo", "articulo",
             "lineas", "bultos", "venta", "costo", "primera", "ultima"],
    "cascada": ["sucursal", "generico", "bruto", "descuentos", "neto",
                "sin_cargo_lista", "q_sin_cargo", "q_con_cargo", "lineas"],
    "fuga": ["id_cliente", "id_vendedor", "id_sucursal", "bruto", "descuento", "neto", "lineas"],
    "dispersion": ["mes", "id_articulo", "id_cliente", "neto", "q"],
    "devoluciones": ["neto", "lineas"],
    "dim_cliente": ["id_cliente", "cliente", "subcanal"],
    "dim_vendedor": ["id_vendedor", "id_sucursal", "vendedor", "sucursal"],
    "dim_sucursal": ["id_sucursal", "sucursal"],
    "dim_articulo": ["id_articulo", "articulo", "generico", "marca"],
}


class _ContextoFalso:
    """Reemplaza a AnalysisContext devolviendo DataFrames en vez de ir a la base."""

    def __init__(self, respuestas, fecha_hasta="2026-07-30", meses_ventana=12):
        self._respuestas = respuestas
        self.data_loader = None
        self.fecha_hasta = fecha_hasta
        self.meses_ventana = meses_ventana
        self.meses_historia = 24

    def desde(self, meses=None):
        return "2025-07-30"

    def sql(self, query, params=None):
        for clave, consulta in (
            ("grilla", rent.SQL_GRILLA_MARGEN),
            ("bajo", rent.SQL_BAJO_COSTO),
            ("cascada", rent.SQL_CASCADA),
            ("fuga", rent.SQL_FUGA),
            ("dispersion", rent.SQL_DISPERSION),
            ("devoluciones", rent.SQL_DEVOLUCIONES),
            ("dim_cliente", rent.SQL_DIM_CLIENTE),
            ("dim_vendedor", rent.SQL_DIM_VENDEDOR),
            ("dim_sucursal", rent.SQL_DIM_SUCURSAL),
            ("dim_articulo", rent.SQL_DIM_ARTICULO),
        ):
            if query is consulta:
                return self._respuestas[clave]
        raise AssertionError(f"consulta no prevista: {query[:60]}")


def _respuestas_completas():
    """Una empresa chica pero completa: dos sucursales, dos subcanales, dos anios."""
    datos = {clave: pd.DataFrame(columns=cols) for clave, cols in _COLUMNAS_SQL.items()}

    datos["grilla"] = pd.DataFrame(
        [
            {"anio": a, "generico": g, "marca": m, "sucursal": s, "subcanal": c,
             "margen_linea": mg, "lineas": 50, "bultos": 300.0, "venta": v, "costo": co,
             "lineas_bajo_costo": lbc, "perdida_bajo_costo": pbc}
            for a, g, m, s, c, mg, v, co, lbc, pbc in [
                (2025, "CERVEZAS", "SALTA", "CASA CENTRAL", "ALMACEN", 0.30, 10_000.0, 7_000.0, 0, 0.0),
                (2025, "VINOS", "TORO", "CASA CENTRAL", "KIOSCO", 0.10, 5_000.0, 4_500.0, 0, 0.0),
                (2026, "CERVEZAS", "SALTA", "CASA CENTRAL", "ALMACEN", 0.25, 12_000.0, 9_000.0, 0, 0.0),
                (2026, "CERVEZAS", "SALTA", "SUCURSAL METAN", "ALMACEN", 0.05, 8_000.0, 7_600.0, 5, -200.0),
                (2026, "VINOS", "TORO", "SUCURSAL METAN", "KIOSCO", -0.05, 3_000.0, 3_150.0, 20, -150.0),
            ]
        ]
    )
    datos["bajo"] = pd.DataFrame(
        [
            {"anio": 2026, "sucursal": "SUCURSAL METAN", "id_cliente": 5000,
             "cliente": "ALMACEN DON JOSE", "id_articulo": 10, "articulo": "SALTA RUBIA",
             "lineas": 5, "bultos": 40.0, "venta": 800.0, "costo": 1_000.0,
             "primera": "2026-02-01", "ultima": "2026-04-20"},
            {"anio": 2025, "sucursal": "CASA CENTRAL", "id_cliente": 207603,
             "cliente": "GARCIA JORGE ALBERTO", "id_articulo": 20, "articulo": "SIDRA REAL",
             "lineas": 2, "bultos": 10.0, "venta": 100.0, "costo": 1_100.0,
             "primera": "2025-09-23", "ultima": "2025-09-23"},
        ]
    )
    datos["cascada"] = pd.DataFrame(
        [
            {"sucursal": "CASA CENTRAL", "generico": "CERVEZAS", "bruto": 100_000.0,
             "descuentos": 20_000.0, "neto": 80_000.0, "sin_cargo_lista": 8_000.0,
             "q_sin_cargo": 80.0, "q_con_cargo": 800.0, "lineas": 500},
            {"sucursal": "SUCURSAL METAN", "generico": "VINOS", "bruto": 60_000.0,
             "descuentos": 4_800.0, "neto": 55_200.0, "sin_cargo_lista": 600.0,
             "q_sin_cargo": 6.0, "q_con_cargo": 550.0, "lineas": 300},
        ]
    )
    datos["fuga"] = pd.DataFrame(
        [
            {"id_cliente": i, "id_vendedor": 7, "id_sucursal": 1,
             "bruto": 10_000_000.0, "descuento": 10_000_000.0 * tasa,
             "neto": 10_000_000.0 * (1 - tasa), "lineas": 40}
            for i, tasa in enumerate(_TASAS_SANAS + [0.60], start=1)
        ]
    )
    datos["dispersion"] = pd.DataFrame(
        [
            {"mes": f"2026-0{mes}-01", "id_articulo": 1, "id_cliente": 1000 + i,
             "neto": (100.0 + (i % 7) * 5) * 20.0, "q": 20.0}
            for mes in (1, 2, 3, 4)
            for i in range(35)
        ]
    )
    datos["devoluciones"] = pd.DataFrame([{"neto": -4_000.0, "lineas": 12}])
    datos["dim_cliente"] = pd.DataFrame(
        [{"id_cliente": i, "cliente": f"CLIENTE {i}", "subcanal": "ALMACEN"}
         for i in range(1, 12)]
    )
    datos["dim_vendedor"] = pd.DataFrame(
        [{"id_vendedor": 7, "id_sucursal": 1, "vendedor": "ROSSI", "sucursal": "CASA CENTRAL"}]
    )
    datos["dim_sucursal"] = pd.DataFrame(
        [{"id_sucursal": 1, "sucursal": "CASA CENTRAL"},
         {"id_sucursal": 2, "sucursal": "SUCURSAL METAN"}]
    )
    datos["dim_articulo"] = pd.DataFrame(
        [{"id_articulo": 1, "articulo": "SALTA RUBIA 1000*12", "generico": "CERVEZAS",
          "marca": "SALTA"}]
    )
    return datos


class TestBuildCompleto:
    def test_devuelve_las_cinco_tablas_con_alertas_y_notas(self):
        resultado = rent.build(_ContextoFalso(_respuestas_completas()))
        assert resultado.failed is False
        assert set(resultado.tables) == {
            "margen", "bajo_costo", "cascada", "fuga_outliers", "dispersion"
        }
        # El camino de alertas y notas se recorre de verdad, no solo el de tablas.
        assert resultado.alerts, "no se redacto ninguna alerta"
        assert resultado.notes, "no se redacto ninguna nota"

    def test_toda_alerta_tiene_titulo_y_detalle_redactados(self):
        resultado = rent.build(_ContextoFalso(_respuestas_completas()))
        for alerta in resultado.alerts:
            assert alerta.title.strip()
            assert alerta.detail.strip()
            assert alerta.severity in {"critica", "alta", "media", "info"}

    def test_ninguna_alerta_afirma_una_comparacion_que_no_calculo(self):
        # La alerta de brecha de margen tiene que nombrar la dimension ganadora
        # medida, no una conclusion escrita de antemano.
        resultado = rent.build(_ContextoFalso(_respuestas_completas()))
        brecha = [a for a in resultado.alerts if "brecha de margen" in a.title]
        assert brecha, "falta la alerta de brecha de margen"
        assert "sucursales" in brecha[0].title or "subcanales" in brecha[0].title

    def test_la_nota_de_devoluciones_informa_lo_que_quedo_afuera(self):
        resultado = rent.build(_ContextoFalso(_respuestas_completas()))
        assert any("DEVOLUCIONES" in n for n in resultado.notes)

    def test_sin_datos_devuelve_failed_en_vez_de_romper(self):
        vacias = {clave: pd.DataFrame(columns=cols) for clave, cols in _COLUMNAS_SQL.items()}
        resultado = rent.build(_ContextoFalso(vacias))
        assert resultado.failed is True
        assert resultado.notes

    def test_si_la_base_falla_no_levanta_excepcion(self):
        class Roto(_ContextoFalso):
            def sql(self, query, params=None):
                raise RuntimeError("conexion caida")

        resultado = rent.build(Roto(_respuestas_completas()))
        assert resultado.failed is True
        assert "conexion caida" in resultado.notes[0]

    def test_una_alerta_rota_no_se_lleva_puestas_las_tablas(self, monkeypatch):
        # Contrato duro: build() no levanta NUNCA. Si la redaccion de una alerta
        # falla, las tablas ya calculadas tienen que sobrevivir.
        def explota(**kwargs):
            raise KeyError("Margen Ponderado")

        monkeypatch.setattr(rent, "_construir_alertas", explota)
        resultado = rent.build(_ContextoFalso(_respuestas_completas()))
        assert resultado.alerts == []
        assert not resultado.tables["margen"].empty
        assert any("no se pudieron redactar las alertas" in n for n in resultado.notes)
