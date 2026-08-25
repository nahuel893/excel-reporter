"""Tests de las transformaciones puras de analytics/portafolio.py.

Sin base de datos: cada test arma un DataFrame chico a mano y compara contra
numeros calculados a mano, no contra lo que devuelve el codigo.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.services.inteligencia_comercial import constants
from src.services.inteligencia_comercial.analytics.portafolio import (
    ETIQUETA_TOTAL,
    agregar_total_general,
    agrupar_colas,
    calcular_cv_por_sku,
    calcular_penetracion,
    clasificar_abc,
    clasificar_xyz,
    construir_abc_xyz,
    construir_canal_yoy,
    construir_cohorte_lanzamientos,
    construir_contingencia,
    construir_rampa,
    construir_reglas,
    construir_stock_muerto,
    detectar_brechas_cliente,
    etiqueta_fuerza_ventas,
    etiquetar_celda,
    formatear_reglas,
    formatear_contingencia,
    formatear_cross_sell,
    formatear_residuos,
    meses_completos_en_rango,
    resumir_9box,
    ventanas_interanuales,
)


# ---------------------------------------------------------------------------
# agregar_total_general
# ---------------------------------------------------------------------------
class TestAgregarTotalGeneral:
    def test_suma_solo_las_columnas_pedidas(self):
        df = pd.DataFrame({"Marca": ["A", "B"], "Neto": [10.0, 5.0], "Lift": [2.0, 3.0]})
        salida = agregar_total_general(df, "Marca", cols_suma=["Neto"])
        assert len(salida) == 3
        assert salida.iloc[-1]["Marca"] == ETIQUETA_TOTAL
        assert salida.iloc[-1]["Neto"] == 15.0
        # Lift no se suma: 2 + 3 = 5 seria una mentira.
        assert pd.isna(salida.iloc[-1]["Lift"])

    def test_los_extras_pisan_el_agregado(self):
        df = pd.DataFrame({"Marca": ["A", "B"], "Bultos": [10.0, 30.0], "Ratio": [1.0, 3.0]})
        salida = agregar_total_general(df, "Marca", cols_suma=["Bultos"], extras={"Ratio": 2.0})
        assert salida.iloc[-1]["Bultos"] == 40.0
        assert salida.iloc[-1]["Ratio"] == 2.0

    def test_conserva_los_enteros_nullable(self):
        df = pd.DataFrame({"Marca": ["A"], "ID": pd.array([22809], dtype="Int64")})
        salida = agregar_total_general(df, "Marca")
        assert str(salida["ID"].dtype) == "Int64"
        assert salida.iloc[0]["ID"] == 22809

    def test_tabla_vacia_no_agrega_nada(self):
        assert agregar_total_general(pd.DataFrame(), "Marca").empty


# ---------------------------------------------------------------------------
# clasificar_abc
# ---------------------------------------------------------------------------
class TestClasificarAbc:
    def test_corte_80_95_es_inclusivo(self):
        # Acumulados a mano: 0,80 / 0,95 / 0,99 / 1,00.
        neto = pd.Series([80.0, 15.0, 4.0, 1.0], index=["a", "b", "c", "d"])
        salida = clasificar_abc(neto)
        assert list(salida["clase_abc"]) == ["A", "B", "C", "C"]
        assert salida.loc["a", "participacion"] == pytest.approx(0.80)
        assert salida.loc["b", "participacion_acum"] == pytest.approx(0.95)

    def test_ordena_por_neto_aunque_llegue_desordenado(self):
        neto = pd.Series([1.0, 80.0, 15.0, 4.0], index=["d", "a", "b", "c"])
        salida = clasificar_abc(neto)
        # El indice de salida respeta el de entrada, la clase sale del ranking.
        assert list(salida.index) == ["d", "a", "b", "c"]
        assert salida.loc["a", "clase_abc"] == "A"
        assert salida.loc["d", "clase_abc"] == "C"

    def test_total_no_positivo_deja_todo_en_c(self):
        neto = pd.Series([0.0, 0.0], index=["a", "b"])
        salida = clasificar_abc(neto)
        assert list(salida["clase_abc"]) == ["C", "C"]


# ---------------------------------------------------------------------------
# calcular_cv_por_sku / clasificar_xyz
# ---------------------------------------------------------------------------
class TestCalcularCvPorSku:
    def _matriz(self):
        meses = pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"])
        return pd.DataFrame(
            [
                [np.nan, 10.0, 20.0],  # nuevo: ventana [10, 20]
                [5.0, 5.0, 5.0],  # constante
                [np.nan, np.nan, 7.0],  # un solo mes de ventana
                [4.0, np.nan, 4.0],  # el hueco intermedio vale cero
            ],
            index=[1, 2, 3, 4],
            columns=meses,
        )

    def test_la_ventana_arranca_en_la_primera_venta(self):
        salida = calcular_cv_por_sku(self._matriz())
        # media 15, desvio poblacional 5 -> CV = 1/3. Si rellenara desde el
        # principio la ventana seria [0, 10, 20] y el CV daria ~0,8165.
        assert salida.loc[1, "meses_ventana_cv"] == 2
        assert salida.loc[1, "cv"] == pytest.approx(1 / 3)

    def test_serie_constante_tiene_cv_cero(self):
        salida = calcular_cv_por_sku(self._matriz())
        assert salida.loc[2, "cv"] == pytest.approx(0.0)
        assert salida.loc[2, "meses_con_venta"] == 3

    def test_un_solo_mes_de_ventana_deja_el_cv_indefinido(self):
        salida = calcular_cv_por_sku(self._matriz())
        assert salida.loc[3, "meses_ventana_cv"] == 1
        assert np.isnan(salida.loc[3, "cv"])

    def test_el_hueco_posterior_al_lanzamiento_cuenta_como_cero(self):
        salida = calcular_cv_por_sku(self._matriz())
        # ventana [4, 0, 4]: media 8/3, desvio poblacional sqrt(32/9) -> CV = sqrt(2)/2
        assert salida.loc[4, "meses_ventana_cv"] == 3
        assert salida.loc[4, "meses_con_venta"] == 2
        assert salida.loc[4, "cv"] == pytest.approx(np.sqrt(2) / 2)


class TestClasificarXyz:
    def test_cortes_050_y_100(self):
        cv = pd.Series([0.0, 0.49, 0.50, 0.99, 1.00, 3.4, np.nan])
        assert list(clasificar_xyz(cv)) == ["X", "X", "Y", "Y", "Z", "Z", "N/D"]

    def test_el_cv_indefinido_no_se_descarta(self):
        cv = pd.Series([np.nan, np.nan])
        assert list(clasificar_xyz(cv)) == ["N/D", "N/D"]


class TestEtiquetarCelda:
    def test_separa_la_clase_indefinida(self):
        abc = pd.Series(["A", "C", "B"])
        xyz = pd.Series(["X", "N/D", "Z"])
        assert list(etiquetar_celda(abc, xyz)) == ["AX", "C N/D", "BZ"]


# ---------------------------------------------------------------------------
# construir_abc_xyz + resumir_9box
# ---------------------------------------------------------------------------
class TestConstruirAbcXyz:
    def _ventas(self):
        meses = ["2026-01-01", "2026-02-01", "2026-03-01"]
        filas = []
        # SKU 1: 80 de neto en la ventana actual, demanda estable (10/10/10).
        for mes in meses:
            filas.append((1, mes, True, 10.0, 80.0 / 3))
        # SKU 2: 20 de neto, demanda erratica (1/0/9) -> se llena con cero.
        for mes, bultos in zip(meses, [1.0, 0.0, 9.0]):
            filas.append((2, mes, True, bultos, 20.0 / 3))
        return pd.DataFrame(
            filas, columns=["id_articulo", "mes", "ventana_actual", "bultos", "neto"]
        )

    def _articulos(self):
        return pd.DataFrame(
            {
                "id_articulo": [1, 2],
                "des_articulo": ["CERVEZA GRANDE", "SIDRA RARA"],
                "generico": ["CERVEZAS", "SIDRAS Y LICORES"],
                "marca": ["SALTA", "REAL"],
            }
        )

    def test_arma_la_celda_y_ordena_por_neto(self):
        meses = [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
        tabla = construir_abc_xyz(self._ventas(), self._articulos(), meses)
        assert list(tabla["ID Articulo"]) == [1, 2]
        assert tabla.loc[0, "Clase ABC"] == "A"  # acumulado 0,80 -> corte inclusivo
        assert tabla.loc[0, "Clase XYZ"] == "X"  # CV = 0
        assert tabla.loc[0, "Celda"] == "AX"
        assert tabla.loc[0, "Neto 12m ($)"] == pytest.approx(80.0)
        # SKU 2: media 10/3, desvio poblacional sqrt(1058/9)/... -> CV > 1
        assert tabla.loc[1, "Clase XYZ"] == "Z"
        assert tabla.loc[1, "Celda"] == "CZ"

    def test_los_meses_de_borde_quedan_fuera_del_cv(self):
        # Solo se pasan dos meses completos: el tercero no entra en la ventana.
        meses = [date(2026, 1, 1), date(2026, 2, 1)]
        tabla = construir_abc_xyz(self._ventas(), self._articulos(), meses)
        fila = tabla[tabla["ID Articulo"] == 2].iloc[0]
        # ventana [1, 0]: media 0,5, desvio poblacional 0,5 -> CV = 1,0 -> clase Z
        assert fila["Meses Ventana CV"] == 2
        assert fila["CV Demanda Mensual"] == pytest.approx(1.0)

    def test_sin_ventas_devuelve_vacio(self):
        assert construir_abc_xyz(pd.DataFrame(), self._articulos(), []).empty

    def test_el_sku_lanzado_en_el_mes_de_borde_no_muestra_cero_meses_con_venta(self):
        """Regresion: un lanzamiento del mes en curso decia 'Meses con Venta = 0'.

        El SKU 3 vende SOLO en marzo y marzo NO es un mes completo del rango del
        CV, asi que el conteo de la ventana del CV es 0. Antes esa era la unica
        columna de meses y la fila quedaba con neto de 12 meses contra 0 meses con
        venta, que un lector lee como error de datos. El conteo de la ventana de
        12 meses tiene que decir 1.
        """
        ventas = pd.concat(
            [
                self._ventas(),
                pd.DataFrame(
                    [(3, "2026-03-01", True, 5.0, 500.0)],
                    columns=["id_articulo", "mes", "ventana_actual", "bultos", "neto"],
                ),
            ],
            ignore_index=True,
        )
        articulos = pd.concat(
            [
                self._articulos(),
                pd.DataFrame(
                    [(3, "FERNET NUEVO", "FRATELLI B", "BUHERO")],
                    columns=["id_articulo", "des_articulo", "generico", "marca"],
                ),
            ],
            ignore_index=True,
        )
        # Solo enero y febrero son meses completos: marzo queda afuera.
        tabla = construir_abc_xyz(ventas, articulos, [date(2026, 1, 1), date(2026, 2, 1)])
        fila = tabla[tabla["ID Articulo"] == 3].iloc[0]
        assert fila["Meses con Venta (12m)"] == 1
        assert fila["Meses con Venta (meses completos)"] == 0
        assert fila["Meses Ventana CV"] == 0
        assert fila["Clase XYZ"] == "N/D"
        assert fila["Neto 12m ($)"] == pytest.approx(500.0)

    def test_cuenta_los_meses_con_venta_de_la_ventana_de_doce_meses(self):
        meses = [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
        tabla = construir_abc_xyz(self._ventas(), self._articulos(), meses).set_index(
            "ID Articulo"
        )
        # Los dos SKUs tienen una fila por cada uno de los tres meses.
        assert tabla.loc[1, "Meses con Venta (12m)"] == 3
        assert tabla.loc[2, "Meses con Venta (12m)"] == 3


class TestResumir9Box:
    def test_cuenta_skus_y_neto_por_celda(self):
        abc_xyz = pd.DataFrame(
            {
                "ID Articulo": [1, 2, 3, 4],
                "Neto 12m ($)": [70.0, 10.0, 15.0, 5.0],
                "Clase ABC": ["A", "A", "B", "C"],
                "Clase XYZ": ["X", "X", "Y", "N/D"],
            }
        )
        box = resumir_9box(abc_xyz)
        ax = box[box["Celda"] == "AX"].iloc[0]
        assert ax["SKUs"] == 2
        assert ax["Neto 12m ($)"] == pytest.approx(80.0)
        assert ax["% Neto"] == pytest.approx(0.80)
        assert ax["% SKUs"] == pytest.approx(0.50)
        # El casillero del CV indefinido existe y no se pierde.
        assert "C N/D" in set(box["Celda"])

    def test_ordena_de_a_a_c_y_de_x_a_nd(self):
        abc_xyz = pd.DataFrame(
            {
                "ID Articulo": [1, 2, 3],
                "Neto 12m ($)": [1.0, 1.0, 1.0],
                "Clase ABC": ["C", "A", "C"],
                "Clase XYZ": ["N/D", "X", "Z"],
            }
        )
        assert list(resumir_9box(abc_xyz)["Celda"]) == ["AX", "CZ", "C N/D"]


# ---------------------------------------------------------------------------
# Contingencia
# ---------------------------------------------------------------------------
class TestAgruparColas:
    def test_colapsa_las_categorias_chicas(self):
        df = pd.DataFrame(
            {
                "subcanal": ["GRANDE", "CHICO", "MINIMO"],
                "bultos": [990.0, 9.0, 1.0],
            }
        )
        salida = agrupar_colas(df, "subcanal", "bultos", 0.02, "OTROS")
        assert set(salida["subcanal"]) == {"GRANDE", "OTROS"}
        # El total se conserva: agrupar no puede perder volumen.
        assert salida["bultos"].sum() == pytest.approx(1000.0)

    def test_sin_colas_devuelve_lo_mismo(self):
        df = pd.DataFrame({"subcanal": ["A", "B"], "bultos": [50.0, 50.0]})
        salida = agrupar_colas(df, "subcanal", "bultos", 0.02, "OTROS")
        assert list(salida["subcanal"]) == ["A", "B"]


class TestContingencia:
    def _canal(self):
        return pd.DataFrame(
            {
                "subcanal": ["ALMACEN", "ALMACEN", "MAYORISTA", "MAYORISTA"],
                "generico": ["CERVEZAS", "AGUAS DANONE", "CERVEZAS", "AGUAS DANONE"],
                "bultos": [60.0, 40.0, 90.0, 10.0],
            }
        )

    def test_pivotea_a_subcanal_por_generico(self):
        tabla = construir_contingencia(self._canal())
        assert tabla.loc["ALMACEN", "CERVEZAS"] == 60.0
        assert tabla.loc["MAYORISTA", "AGUAS DANONE"] == 10.0
        assert tabla.values.sum() == pytest.approx(200.0)

    def test_los_bultos_negativos_se_llevan_a_cero(self):
        canal = self._canal()
        canal.loc[1, "bultos"] = -40.0
        tabla = construir_contingencia(canal)
        assert tabla.loc["ALMACEN", "AGUAS DANONE"] == 0.0

    def test_formatear_agrega_columna_total_y_fila_total(self):
        salida = formatear_contingencia(construir_contingencia(self._canal()))
        assert salida.iloc[0]["TOTAL"] == pytest.approx(100.0)
        assert salida.iloc[-1]["Subcanal"] == ETIQUETA_TOTAL
        assert salida.iloc[-1]["CERVEZAS"] == pytest.approx(150.0)

    def test_la_fila_total_de_residuos_es_el_chi2_por_columna(self):
        residuos = pd.DataFrame(
            [[2.0, -2.0], [-3.0, 3.0]],
            index=pd.Index(["ALMACEN", "MAYORISTA"], name="subcanal"),
            columns=["CERVEZAS", "AGUAS DANONE"],
        )
        salida = formatear_residuos(residuos)
        assert salida.iloc[-1]["Subcanal"].startswith(ETIQUETA_TOTAL)
        # 2^2 + 3^2 = 13, que es aditivo; los residuos crudos no lo son.
        assert salida.iloc[-1]["CERVEZAS"] == pytest.approx(13.0)
        assert salida.iloc[-1]["AGUAS DANONE"] == pytest.approx(13.0)


# ---------------------------------------------------------------------------
# Interanual por subcanal
# ---------------------------------------------------------------------------
class TestConstruirCanalYoy:
    def _periodo(self):
        return pd.DataFrame(
            {
                "subcanal": ["ALMACEN", "ALMACEN", "RESTAURANTE", "RESTAURANTE"],
                "periodo": ["actual", "previo", "actual", "previo"],
                "bultos": [1200.0, 1000.0, 80.0, 100.0],
                "clientes": [8.0, 10.0, 5.0, 5.0],
                "neto": [24000.0, 15000.0, 1600.0, 1500.0],
            }
        )

    def test_calcula_deltas_de_volumen_y_de_clientes(self):
        tabla = construir_canal_yoy(self._periodo()).set_index("Subcanal")
        alm = tabla.loc["ALMACEN"]
        assert alm["Delta Bultos"] == pytest.approx(200.0)
        assert alm["Delta % Bultos"] == pytest.approx(0.20)
        assert alm["Delta Clientes"] == -2
        assert alm["Delta % Clientes"] == pytest.approx(-0.20)

    def test_bultos_por_cliente_muestra_la_erosion_de_ancho(self):
        tabla = construir_canal_yoy(self._periodo()).set_index("Subcanal")
        alm = tabla.loc["ALMACEN"]
        assert alm["Bultos/Cliente Previo"] == pytest.approx(100.0)
        assert alm["Bultos/Cliente Actual"] == pytest.approx(150.0)
        assert alm["Delta % Bultos/Cliente"] == pytest.approx(0.50)

    def test_ordena_por_delta_de_bultos_descendente(self):
        tabla = construir_canal_yoy(self._periodo())
        assert list(tabla["Subcanal"]) == ["ALMACEN", "RESTAURANTE"]

    def test_el_neto_es_solo_del_periodo_actual(self):
        tabla = construir_canal_yoy(self._periodo()).set_index("Subcanal")
        # No existe columna de neto previo: los pesos no se comparan entre anios.
        assert "Neto 12m Previo ($)" not in tabla.columns
        assert tabla.loc["ALMACEN", "Neto 12m Actual ($ nominal)"] == pytest.approx(24000.0)


# ---------------------------------------------------------------------------
# Cross-sell
# ---------------------------------------------------------------------------
class TestCalcularPenetracion:
    def _clientes(self):
        # 4 clientes de ALMACEN: 4 compran CERVEZAS, 2 compran VINOS.
        filas = [
            (1, "ALMACEN", "CERVEZAS", 100.0),
            (2, "ALMACEN", "CERVEZAS", 200.0),
            (3, "ALMACEN", "CERVEZAS", 300.0),
            (4, "ALMACEN", "CERVEZAS", 400.0),
            (1, "ALMACEN", "VINOS", 10.0),
            (2, "ALMACEN", "VINOS", 30.0),
        ]
        return pd.DataFrame(filas, columns=["id_cliente", "subcanal", "generico", "neto"]).assign(
            bultos=1.0
        )

    def test_penetracion_y_mediana_de_pares(self):
        salida = calcular_penetracion(
            self._clientes(), min_compradores=2, min_clientes=2
        ).set_index(["subcanal", "generico"])
        vinos = salida.loc[("ALMACEN", "VINOS")]
        assert vinos["clientes_activos"] == 4
        assert vinos["compradores"] == 2
        assert vinos["no_compradores"] == 2
        assert vinos["penetracion"] == pytest.approx(0.50)
        # Mediana de [10, 30] = 20 (no el promedio de los 4 clientes).
        assert vinos["neto_mediano"] == pytest.approx(20.0)
        assert vinos["oportunidad"] == pytest.approx(40.0)

    def test_la_celda_saturada_no_tiene_oportunidad(self):
        salida = calcular_penetracion(
            self._clientes(), min_compradores=2, min_clientes=2
        ).set_index(["subcanal", "generico"])
        assert salida.loc[("ALMACEN", "CERVEZAS"), "penetracion"] == pytest.approx(1.0)
        assert salida.loc[("ALMACEN", "CERVEZAS"), "oportunidad"] == pytest.approx(0.0)

    def test_sin_compradores_suficientes_no_se_dimensiona(self):
        salida = calcular_penetracion(
            self._clientes(), min_compradores=3, min_clientes=2
        ).set_index(["subcanal", "generico"])
        assert np.isnan(salida.loc[("ALMACEN", "VINOS"), "neto_mediano"])
        assert np.isnan(salida.loc[("ALMACEN", "VINOS"), "oportunidad"])

    def test_subcanal_chico_se_descarta_entero(self):
        salida = calcular_penetracion(self._clientes(), min_compradores=1, min_clientes=99)
        assert salida.empty

    def test_las_celdas_con_cero_compradores_aparecen(self):
        clientes = self._clientes()
        clientes = pd.concat(
            [
                clientes,
                pd.DataFrame(
                    [(9, "KIOSCO", "VINOS", 50.0, 1.0), (10, "KIOSCO", "VINOS", 70.0, 1.0)],
                    columns=["id_cliente", "subcanal", "generico", "neto", "bultos"],
                ),
            ],
            ignore_index=True,
        )
        salida = calcular_penetracion(clientes, min_compradores=2, min_clientes=2).set_index(
            ["subcanal", "generico"]
        )
        # KIOSCO no compra CERVEZAS: es espacio en blanco y no puede desaparecer.
        assert salida.loc[("KIOSCO", "CERVEZAS"), "compradores"] == 0
        assert salida.loc[("KIOSCO", "CERVEZAS"), "penetracion"] == pytest.approx(0.0)


class TestFormatearCrossSell:
    def test_ordena_por_ars_por_conversion_no_por_ars_total(self):
        penetracion = pd.DataFrame(
            {
                "subcanal": ["ALMACEN", "MAYORISTA"],
                "generico": ["GASEOSAS", "FRATELLI B"],
                "clientes_activos": [5000, 160],
                "compradores": [1000, 125],
                "no_compradores": [4000, 35],
                "penetracion": [0.20, 0.78],
                "neto_mediano": [100_000.0, 2_000_000.0],
                "neto_total": [1.0, 1.0],
                "oportunidad": [400_000_000.0, 70_000_000.0],
            }
        )
        tabla = formatear_cross_sell(penetracion)
        # MAYORISTA vale menos en total pero mucho mas por conversion: va primero.
        assert list(tabla["Subcanal"]) == ["MAYORISTA", "ALMACEN"]
        assert list(tabla["Rank por ARS/Conversion"]) == [1, 2]
        assert tabla.loc[0, "Rank por Oportunidad Total"] == 2

    def test_descarta_las_celdas_sin_espacio_en_blanco(self):
        penetracion = pd.DataFrame(
            {
                "subcanal": ["ALMACEN"],
                "generico": ["CERVEZAS"],
                "clientes_activos": [100],
                "compradores": [100],
                "no_compradores": [0],
                "penetracion": [1.0],
                "neto_mediano": [500.0],
                "neto_total": [1.0],
                "oportunidad": [0.0],
            }
        )
        assert formatear_cross_sell(penetracion).empty


class TestDetectarBrechasCliente:
    def test_lista_solo_lo_que_los_pares_si_compran(self):
        cliente_generico = pd.DataFrame(
            {
                "id_cliente": [1, 2, 3, 1],
                "subcanal": ["ALMACEN"] * 4,
                "generico": ["CERVEZAS", "CERVEZAS", "CERVEZAS", "VINOS"],
                "neto": [10.0, 20.0, 30.0, 40.0],
                "bultos": [1.0] * 4,
            }
        )
        penetracion = pd.DataFrame(
            {
                "subcanal": ["ALMACEN", "ALMACEN"],
                "generico": ["CERVEZAS", "VINOS"],
                "clientes_activos": [3, 3],
                "compradores": [3, 1],
                "no_compradores": [0, 2],
                "penetracion": [1.0, 1 / 3],
                "neto_mediano": [20.0, 40.0],
                "neto_total": [60.0, 40.0],
                "oportunidad": [0.0, 80.0],
            }
        )
        # Con umbral 0,30 la celda VINOS (33%) califica: faltan los clientes 2 y 3.
        brechas = detectar_brechas_cliente(cliente_generico, penetracion, umbral=0.30)
        assert set(brechas["id_cliente"]) == {2, 3}
        assert set(brechas["generico"]) == {"VINOS"}
        assert brechas["valor_estimado"].sum() == pytest.approx(80.0)

    def test_con_umbral_alto_no_hay_brecha(self):
        cliente_generico = pd.DataFrame(
            {
                "id_cliente": [1, 2],
                "subcanal": ["ALMACEN", "ALMACEN"],
                "generico": ["VINOS", "CERVEZAS"],
                "neto": [10.0, 20.0],
                "bultos": [1.0, 1.0],
            }
        )
        penetracion = pd.DataFrame(
            {
                "subcanal": ["ALMACEN"],
                "generico": ["VINOS"],
                "clientes_activos": [2],
                "compradores": [1],
                "no_compradores": [1],
                "penetracion": [0.50],
                "neto_mediano": [10.0],
                "neto_total": [10.0],
                "oportunidad": [10.0],
            }
        )
        assert detectar_brechas_cliente(cliente_generico, penetracion, umbral=0.90).empty

    def test_el_cliente_mostrador_aparece_en_el_detalle_para_poder_marcarlo(self):
        """Regresion: la columna 'Es Mostrador' decia siempre NO.

        La penetracion se calcula SIN los clientes mostrador (uno solo factura
        ~9.479 veces al anio), pero el detalle por cliente los recibe igual: la
        regla de dominio es marcar, no borrar en silencio. Si se los saca de las
        dos puntas la columna existe y miente.
        """
        mostrador = constants.CLIENTES_MOSTRADOR[0]
        cliente_generico = pd.DataFrame(
            {
                "id_cliente": [1, 2, mostrador],
                "subcanal": ["ALMACEN"] * 3,
                "generico": ["VINOS", "VINOS", "CERVEZAS"],
                "neto": [10.0, 30.0, 500.0],
                "bultos": [1.0, 1.0, 1.0],
            }
        )
        penetracion = pd.DataFrame(
            {
                "subcanal": ["ALMACEN"],
                "generico": ["VINOS"],
                "clientes_activos": [2],
                "compradores": [2],
                "no_compradores": [0],
                "penetracion": [1.0],
                "neto_mediano": [20.0],
                "neto_total": [40.0],
                "oportunidad": [0.0],
            }
        )
        brechas = detectar_brechas_cliente(cliente_generico, penetracion, umbral=0.30)
        assert list(brechas["id_cliente"]) == [mostrador]
        assert brechas.iloc[0]["valor_estimado"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Reglas de asociacion
# ---------------------------------------------------------------------------
class TestEtiquetaFuerzaVentas:
    def test_traduce_los_codigos_conocidos(self):
        assert etiqueta_fuerza_ventas(1) == "FV1 - Preventa"
        assert etiqueta_fuerza_ventas(4.0) == "FV4 - Autoventa"

    def test_un_codigo_desconocido_se_muestra_igual(self):
        assert etiqueta_fuerza_ventas(7) == "FV7"

    def test_un_id_nulo_no_puede_voltear_el_modulo(self):
        # Regresion: int(nan) levantaba ValueError y el build entero devolvia
        # failed=True, perdiendo las once tablas por una sola fila degenerada.
        assert etiqueta_fuerza_ventas(np.nan) == "Sin fuerza de ventas asignada"
        assert etiqueta_fuerza_ventas(None) == "Sin fuerza de ventas asignada"
        assert etiqueta_fuerza_ventas("SIN DATO") == "Sin fuerza de ventas asignada"


class TestConstruirReglas:
    def _baskets(self, fuerza):
        # 600 facturas: 300 llevan CERVEZAS+VINOS y 300 llevan solo AGUAS.
        filas = []
        for i in range(600):
            if i < 300:
                filas += [(f"f{i}", fuerza, "CERVEZAS"), (f"f{i}", fuerza, "VINOS")]
            else:
                filas.append((f"f{i}", fuerza, "AGUAS DANONE"))
        return pd.DataFrame(filas, columns=["factura", "id_fuerza_ventas", "generico"])

    def test_con_fuerza_de_ventas_nula_no_rompe_y_etiqueta_el_grupo(self):
        salida = construir_reglas(
            self._baskets(np.nan), "generico", "Generico", min_facturas=100
        )
        assert not salida.empty
        assert set(salida["Fuerza de Ventas"]) == {"Sin fuerza de ventas asignada"}

    def test_descarta_la_fuerza_con_pocas_facturas(self):
        assert construir_reglas(
            self._baskets(1), "generico", "Generico", min_facturas=10_000
        ).empty

    def test_los_conteos_de_facturas_quedan_enteros(self):
        # Regresion: eran int64, la fila TOTAL GENERAL los degradaba a float y la
        # hoja mostraba "555.0" facturas.
        reglas = construir_reglas(self._baskets(1), "generico", "Generico", min_facturas=100)
        salida = formatear_reglas(reglas)
        assert str(salida["Facturas con Ambos"].dtype) == "Int64"
        assert str(salida["Facturas de la Fuerza"].dtype) == "Int64"
        total = agregar_total_general(salida, "Fuerza de Ventas")
        assert str(total["Facturas con Ambos"].dtype) == "Int64"
        assert total.iloc[0]["Facturas de la Fuerza"] == 600


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------
class TestCohorteLanzamientos:
    def _ciclo(self):
        return pd.DataFrame(
            {
                "id_articulo": [1, 2, 3],
                "primera_venta": ["2026-04-01", "2020-01-01", "2026-05-01"],
                "ultima_venta": ["2026-07-30", "2026-07-30", "2026-07-30"],
                "bultos_historia": [100.0, 999.0, 50.0],
                "neto_historia": [1000.0, 9999.0, 500.0],
            }
        )

    def _articulos(self):
        return pd.DataFrame(
            {
                "id_articulo": [1, 2, 3],
                "des_articulo": ["COLON SELECTO", "SALTA RUBIA", "CARTEL LUMINOSO"],
                "generico": ["VINOS CCU", "CERVEZAS", "MARKETING"],
                "marca": ["COLON", "SALTA", None],
            }
        )

    def test_solo_entran_los_de_primera_venta_historica_reciente(self):
        cohorte = construir_cohorte_lanzamientos(
            self._ciclo(), self._articulos(), date(2026, 7, 30), meses=12
        )
        # El 2 es viejo y el 3 es material promocional: queda solo el 1.
        assert list(cohorte["ID Articulo"]) == [1]

    def test_excluye_los_genericos_que_no_son_articulo_de_venta(self):
        assert "MARKETING" in constants.GENERICOS_NO_VENTA
        cohorte = construir_cohorte_lanzamientos(
            self._ciclo(), self._articulos(), date(2026, 7, 30), meses=12
        )
        assert "MARKETING" not in set(cohorte["Generico"])

    def test_calcula_el_neto_por_mes_de_vida(self):
        cohorte = construir_cohorte_lanzamientos(
            self._ciclo(), self._articulos(), date(2026, 7, 30), meses=12
        )
        fila = cohorte.iloc[0]
        # 2026-04-01 a 2026-07-30 inclusive = 121 dias = 121/30,4375 meses.
        assert fila["Meses Vivo"] == pytest.approx(121 / 30.4375)
        assert fila["Neto por Mes ($)"] == pytest.approx(1000.0 / (121 / 30.4375))


class TestConstruirRampa:
    def test_el_denominador_corrige_la_censura_a_derecha(self):
        ventas = pd.DataFrame(
            {
                "id_articulo": [1, 1, 2],
                "mes": ["2026-05-01", "2026-06-01", "2026-07-01"],
                "ventana_actual": [True, True, True],
                "bultos": [100.0, 200.0, 30.0],
                "neto": [1.0, 1.0, 1.0],
            }
        )
        primeras = pd.Series(
            {1: pd.Timestamp("2026-05-10"), 2: pd.Timestamp("2026-07-05")},
        )
        rampa = construir_rampa(ventas, [1, 2], primeras, date(2026, 7, 1)).set_index(
            "Mes desde Lanzamiento"
        )
        # Mes 0: aportan los dos SKUs (100 + 30) y los dos estan expuestos.
        assert rampa.loc[0, "Bultos"] == pytest.approx(130.0)
        assert rampa.loc[0, "SKUs Expuestos"] == 2
        assert rampa.loc[0, "Bultos por SKU Expuesto"] == pytest.approx(65.0)
        # Mes 1: solo el SKU 1 pudo llegar, asi que el denominador es 1, no 2.
        assert rampa.loc[1, "SKUs Expuestos"] == 1
        assert rampa.loc[1, "Bultos por SKU Expuesto"] == pytest.approx(200.0)

    def test_sin_cohorte_devuelve_vacio(self):
        assert construir_rampa(pd.DataFrame(), [], pd.Series(dtype="object"), date(2026, 7, 1)).empty


class TestStockMuerto:
    def _stock(self):
        return pd.DataFrame(
            {
                "id_articulo": [1, 2, 3],
                "stock_bultos": [10.0, 176024.0, 5.0],
                "depositos": [2, 1, 1],
                "fecha_stock": ["2026-07-30"] * 3,
            }
        )

    def _ciclo(self):
        return pd.DataFrame(
            {
                "id_articulo": [1, 2],
                "primera_venta": ["2024-01-01", "2022-01-01"],
                "ultima_venta": ["2026-01-01", "2022-06-10"],
            }
        )

    def _articulos(self):
        return pd.DataFrame(
            {
                "id_articulo": [1, 2, 3],
                "des_articulo": ["VINO VIEJO", "RASPADITAS", "SIN GENERICO"],
                "generico": ["VINOS FINOS", "MARKETING", None],
                "marca": ["X", "Y", None],
            }
        )

    def _precios(self):
        return pd.DataFrame({"id_articulo": [1], "precio_neto_medio": [100.0]})

    def test_el_filtro_de_genericos_cambia_el_numero_en_dos_ordenes(self):
        real = construir_stock_muerto(
            self._stock(),
            self._ciclo(),
            self._articulos(),
            self._precios(),
            date(2026, 7, 30),
            excluir_no_venta=True,
        )
        ingenuo = construir_stock_muerto(
            self._stock(),
            self._ciclo(),
            self._articulos(),
            self._precios(),
            date(2026, 7, 30),
            excluir_no_venta=False,
        )
        # Real: solo el vino (10 bultos). Ingenuo: suma RASPADITAS (176.024, generico
        # MARKETING) y el articulo sin generico (5) -> 176.039, casi 18.000 veces mas.
        assert real["Stock Bultos"].sum() == pytest.approx(10.0)
        assert ingenuo["Stock Bultos"].sum() == pytest.approx(176039.0)
        assert set(real["ID Articulo"]) == {1}

    def test_marca_los_que_nunca_vendieron(self):
        ingenuo = construir_stock_muerto(
            self._stock(),
            self._ciclo(),
            self._articulos(),
            self._precios(),
            date(2026, 7, 30),
            excluir_no_venta=False,
        ).set_index("ID Articulo")
        assert ingenuo.loc[3, "Estado"] == "Nunca vendido"
        assert ingenuo.loc[2, "Estado"] == "Sin rotacion"

    def test_valua_a_precio_neto_y_deja_sin_valuar_lo_que_no_tiene_precio(self):
        real = construir_stock_muerto(
            self._stock(),
            self._ciclo(),
            self._articulos(),
            self._precios(),
            date(2026, 7, 30),
            excluir_no_venta=True,
        ).set_index("ID Articulo")
        assert real.loc[1, "Valor Neto Estimado ($)"] == pytest.approx(1000.0)

    def test_no_marca_como_muerto_lo_que_roto_hace_poco(self):
        ciclo = self._ciclo().copy()
        ciclo.loc[0, "ultima_venta"] = "2026-07-01"  # 29 dias
        real = construir_stock_muerto(
            self._stock(),
            ciclo,
            self._articulos(),
            self._precios(),
            date(2026, 7, 30),
            excluir_no_venta=True,
        )
        assert real.empty


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------
class TestMesesCompletosEnRango:
    def test_descarta_los_meses_de_borde_partidos(self):
        # Enero arranca el 28 (partido) y abril corta el 29, un dia antes de cerrar.
        meses = meses_completos_en_rango(date(2026, 1, 28), date(2026, 4, 29))
        assert meses == [date(2026, 2, 1), date(2026, 3, 1)]

    def test_el_mes_que_cierra_justo_el_ultimo_dia_si_entra(self):
        meses = meses_completos_en_rango(date(2026, 3, 1), date(2026, 4, 30))
        assert meses == [date(2026, 3, 1), date(2026, 4, 1)]

    def test_incluye_el_mes_que_arranca_el_dia_uno(self):
        meses = meses_completos_en_rango(date(2026, 2, 1), date(2026, 3, 31))
        assert meses == [date(2026, 2, 1), date(2026, 3, 1)]

    def test_rango_invertido_devuelve_vacio(self):
        assert meses_completos_en_rango(date(2026, 5, 1), date(2026, 1, 1)) == []


class TestVentanasInteranuales:
    def test_las_dos_ventanas_miden_la_misma_cantidad_de_dias(self):
        # Es el caso real: ctx.desde(12) ancla el inicio al dia 28 y el corte cae
        # el 30, asi que la ventana actual tiene 368 dias, no 365.
        ini_previo, fin_previo, dias = ventanas_interanuales(
            date(2026, 7, 30), date(2025, 7, 28)
        )
        assert dias == 368
        assert fin_previo == date(2025, 7, 27)
        assert ini_previo == date(2024, 7, 25)
        assert (fin_previo - ini_previo).days + 1 == dias

    def test_la_previa_termina_el_dia_anterior_al_inicio_de_la_actual(self):
        # Sin solapamiento: si la previa llegara hasta ini_actual, ese dia se
        # contaria en los dos periodos.
        ini_previo, fin_previo, dias = ventanas_interanuales(
            date(2026, 1, 31), date(2026, 1, 1)
        )
        assert dias == 31
        assert fin_previo == date(2025, 12, 31)
        assert ini_previo == date(2025, 12, 1)

    def test_ventana_de_un_solo_dia(self):
        ini_previo, fin_previo, dias = ventanas_interanuales(
            date(2026, 7, 30), date(2026, 7, 30)
        )
        assert dias == 1
        assert (ini_previo, fin_previo) == (date(2026, 7, 29), date(2026, 7, 29))
