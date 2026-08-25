"""Tests de las transformaciones de analytics/demanda.py.

Sin base de datos: cada helper recibe DataFrames armados a mano y se contrasta
contra numeros calculados aparte. El test que mas importa es el de la fase de la
estacionalidad: la descomposicion devuelve indices por POSICION desde el arranque
de la serie, y etiquetarlos como si la posicion 0 fuera enero ya produjo una vez
una lectura equivocada (AGUAS DANONE con pico en junio).
"""
import numpy as np
import pandas as pd
import pytest

from src.services.inteligencia_comercial import constants
from src.services.inteligencia_comercial.analytics import demanda


# ── Helpers de fixture ───────────────────────────────────────────────────────

# Perfil estacional tipo cerveza: pico en diciembre, valle en junio.
PERFIL_CERVEZA = {
    1: 1.10, 2: 1.00, 3: 0.90, 4: 0.75, 5: 0.70, 6: 0.65,
    7: 0.95, 8: 1.10, 9: 1.15, 10: 1.15, 11: 1.20, 12: 1.35,
}


def _serie_estacional(inicio: str, meses: int, perfil: dict, nivel: float = 1000.0,
                      crecimiento: float = 0.0) -> pd.Series:
    """Serie mensual perfectamente estacional, sin ruido."""
    idx = pd.date_range(inicio, periods=meses, freq="MS")
    valores = [nivel * perfil[ts.month] * (1.0 + crecimiento * i) for i, ts in enumerate(idx)]
    serie = pd.Series(valores, index=idx)
    serie.index.name = "mes"
    return serie


def _matriz(series: dict[str, pd.Series]) -> pd.DataFrame:
    matriz = pd.DataFrame(series)
    matriz.index.name = "mes"
    return matriz


def _largo_minimo() -> pd.DataFrame:
    """Dos meses, tres genericos, uno de ellos de no-venta."""
    return pd.DataFrame(
        {
            "mes": ["2026-01-01", "2026-01-01", "2026-01-01", "2026-02-01", "2026-02-01"],
            "generico": ["CERVEZAS", "VINOS", "MARKETING", "CERVEZAS", "VINOS"],
            "bultos": [100.0, 20.0, 999.0, 150.0, 30.0],
            "hectolitros": [12.5, 1.5, 0.0, 18.75, 2.25],
            "lineas": [10, 4, 1, 12, 5],
            "clientes": [8, 3, 1, 9, 4],
        }
    )


# ── Correccion de fase de los indices estacionales ───────────────────────────


class TestReordenarIndicesPorMesCalendario:

    def test_serie_que_arranca_en_enero_no_se_mueve(self):
        indices = np.arange(1.0, 13.0)
        resultado = demanda.reordenar_indices_por_mes_calendario(indices, mes_inicial=1)
        assert list(resultado) == list(indices)

    def test_serie_que_arranca_en_junio_corre_los_indices_siete_lugares(self):
        # La posicion 0 es junio, la 1 julio, ... la 7 es enero.
        indices = np.array([60.0, 70.0, 80.0, 90.0, 100.0, 110.0,
                            120.0, 10.0, 20.0, 30.0, 40.0, 50.0])
        resultado = demanda.reordenar_indices_por_mes_calendario(indices, mes_inicial=6)
        # Enero debe quedar con el valor que estaba en la posicion 7.
        assert resultado[0] == 10.0
        # Y junio con el de la posicion 0.
        assert resultado[5] == 60.0
        assert list(resultado) == [10.0, 20.0, 30.0, 40.0, 50.0, 60.0,
                                   70.0, 80.0, 90.0, 100.0, 110.0, 120.0]

    def test_serie_que_arranca_en_diciembre(self):
        indices = np.array([99.0] + [1.0] * 11)
        resultado = demanda.reordenar_indices_por_mes_calendario(indices, mes_inicial=12)
        assert resultado[11] == 99.0  # diciembre
        assert resultado[0] == 1.0


class TestTablaEstacionalidad:

    def test_cervezas_pico_en_diciembre_aunque_la_serie_arranque_en_junio(self):
        """Regresion de la trampa de fase: el pico debe ser Dic, no Jun."""
        matriz = _matriz({"CERVEZAS": _serie_estacional("2023-06-01", 40, PERFIL_CERVEZA)})
        tabla, excluidos = demanda.tabla_estacionalidad(matriz)
        fila = tabla.iloc[0]
        assert excluidos == []
        assert fila["mes_pico"] == "Dic"
        assert fila["mes_valle"] == "Jun"

    def test_los_indices_reproducen_el_perfil_usado_para_generar_la_serie(self):
        matriz = _matriz({"CERVEZAS": _serie_estacional("2023-06-01", 48, PERFIL_CERVEZA)})
        tabla, _ = demanda.tabla_estacionalidad(matriz)
        fila = tabla.iloc[0]
        # El perfil ya promedia 1.0 exactamente (12 valores que suman 12.0),
        # asi que los indices normalizados deben coincidir con el perfil.
        assert sum(PERFIL_CERVEZA.values()) == pytest.approx(12.0)
        assert fila["indice_dic"] == pytest.approx(1.35, abs=1e-6)
        assert fila["indice_jun"] == pytest.approx(0.65, abs=1e-6)
        assert fila["amplitud_pico_valle"] == pytest.approx(1.35 / 0.65, abs=1e-6)

    def test_serie_corta_queda_excluida_y_se_informa_con_sus_meses(self):
        matriz = _matriz({"PERNOD RICARD": _serie_estacional("2026-01-01", 6, PERFIL_CERVEZA)})
        tabla, excluidos = demanda.tabla_estacionalidad(matriz)
        assert tabla.empty
        assert excluidos == [("PERNOD RICARD", 6)]

    def test_el_total_general_va_al_pie_de_la_tabla(self):
        matriz = _matriz(
            {
                "CERVEZAS": _serie_estacional("2022-01-01", 36, PERFIL_CERVEZA),
                "VINOS": _serie_estacional("2022-01-01", 36, PERFIL_CERVEZA, nivel=10.0),
            }
        )
        matriz[demanda.TOTAL_GENERAL] = matriz.sum(axis=1)
        tabla, _ = demanda.tabla_estacionalidad(matriz)
        assert tabla["generico"].tolist() == ["CERVEZAS", "VINOS", demanda.TOTAL_GENERAL]


# ── Serie mensual ────────────────────────────────────────────────────────────


class TestNormalizarSerieMensual:

    def test_descarta_los_genericos_que_no_son_articulos_de_venta(self):
        largo = demanda.normalizar_serie_mensual(_largo_minimo())
        assert "MARKETING" in constants.GENERICOS_NO_VENTA
        assert set(largo["generico"]) == {"CERVEZAS", "VINOS"}
        assert largo["bultos"].sum() == pytest.approx(300.0)  # 100+20+150+30

    def test_el_generico_nulo_queda_etiquetado_y_no_se_pierde(self):
        crudo = pd.DataFrame(
            {
                "mes": ["2026-01-01"],
                "generico": [None],
                "bultos": [42.0],
                "hectolitros": [4.2],
                "lineas": [1],
                "clientes": [1],
            }
        )
        largo = demanda.normalizar_serie_mensual(crudo)
        assert largo.loc[0, "generico"] == demanda.SIN_CLASIFICAR
        assert largo.loc[0, "bultos"] == 42.0

    def test_descarta_el_mes_de_corte_cuando_esta_a_medio_transcurrir(self):
        from datetime import date

        largo = demanda.normalizar_serie_mensual(_largo_minimo(), date(2026, 2, 10))
        # Febrero se cae entero: al dia 10 solo cubre el 35% del mes.
        assert largo["mes"].max() == pd.Timestamp("2026-01-01")

    def test_conserva_el_mes_de_corte_cuando_esta_practicamente_cerrado(self):
        from datetime import date

        largo = demanda.normalizar_serie_mensual(_largo_minimo(), date(2026, 2, 28))
        assert largo["mes"].max() == pd.Timestamp("2026-02-01")


class TestEsMesCerrado:

    def test_el_ultimo_dia_del_mes_siempre_cierra(self):
        from datetime import date

        assert demanda.es_mes_cerrado(date(2026, 2, 28)) is True

    def test_el_dia_30_de_un_mes_de_31_cuenta_como_cerrado(self):
        from datetime import date

        # 30/31 = 96.8%, por encima del 95% exigido.
        assert demanda.es_mes_cerrado(date(2026, 7, 30)) is True

    def test_media_mes_no_cierra(self):
        from datetime import date

        assert demanda.es_mes_cerrado(date(2026, 7, 15)) is False


class TestTablaSerieMensual:

    def test_arma_columnas_de_bultos_y_htl_por_generico_con_total_general(self):
        largo = demanda.normalizar_serie_mensual(_largo_minimo())
        tabla = demanda.tabla_serie_mensual(largo)

        assert tabla["mes"].tolist() == ["2026-01", "2026-02", demanda.TOTAL_GENERAL]
        # CERVEZAS ordena primero por volumen.
        assert list(tabla.columns)[1:5] == [
            "CERVEZAS - Bultos", "CERVEZAS - Htl", "VINOS - Bultos", "VINOS - Htl",
        ]
        total = tabla.iloc[-1]
        assert total["CERVEZAS - Bultos"] == pytest.approx(250.0)
        assert total[f"{demanda.TOTAL_GENERAL} - Bultos"] == pytest.approx(300.0)
        assert total[f"{demanda.TOTAL_GENERAL} - Htl"] == pytest.approx(35.0)

    def test_el_mes_previo_a_que_exista_un_generico_queda_vacio_no_en_cero(self):
        crudo = pd.DataFrame(
            {
                "mes": ["2026-01-01", "2026-02-01", "2026-02-01"],
                "generico": ["CERVEZAS", "CERVEZAS", "AGUAS DANONE"],
                "bultos": [100.0, 120.0, 50.0],
                "hectolitros": [10.0, 12.0, 5.0],
                "lineas": [1, 1, 1],
                "clientes": [1, 1, 1],
            }
        )
        tabla = demanda.tabla_serie_mensual(demanda.normalizar_serie_mensual(crudo))
        enero = tabla.iloc[0]
        assert pd.isna(enero["AGUAS DANONE - Bultos"])


class TestPrepararSerie:

    def test_recorta_el_tramo_muerto_de_los_extremos(self):
        idx = pd.date_range("2026-01-01", periods=6, freq="MS")
        serie = demanda.preparar_serie(pd.Series([0.0, 0.0, 10.0, 12.0, 0.0, 0.0], index=idx))
        assert list(serie.index) == list(idx[2:4])
        assert list(serie) == [10.0, 12.0]

    def test_interpola_el_hueco_interno_en_lugar_de_leerlo_como_demanda_cero(self):
        idx = pd.date_range("2026-01-01", periods=3, freq="MS")
        serie = demanda.preparar_serie(pd.Series([10.0, 0.0, 20.0], index=idx))
        assert list(serie) == [10.0, 15.0, 20.0]


class TestAgregarTotalGeneral:

    def test_suma_solo_las_columnas_indicadas_y_deja_el_resto_vacio(self):
        df = pd.DataFrame({"sucursal": ["A", "B"], "bultos": [10.0, 5.0], "z": [3.5, -4.0]})
        salida = demanda.agregar_total_general(df, "sucursal", ["bultos"])
        assert salida.iloc[-1]["sucursal"] == demanda.TOTAL_GENERAL
        assert salida.iloc[-1]["bultos"] == pytest.approx(15.0)
        assert pd.isna(salida.iloc[-1]["z"])

    def test_conserva_el_tipo_fecha_de_la_columna(self):
        df = pd.DataFrame(
            {"fecha": pd.to_datetime(["2026-01-01"]), "sucursal": ["A"], "bultos": [10.0]}
        )
        salida = demanda.agregar_total_general(df, "sucursal", ["bultos"])
        assert pd.api.types.is_datetime64_any_dtype(salida["fecha"])
        assert pd.isna(salida.iloc[-1]["fecha"])


# ── Pronostico ───────────────────────────────────────────────────────────────


class TestMape:

    def test_error_porcentual_absoluto_medio_calculado_a_mano(self):
        # |100-110|/100 = 0.10 ; |200-180|/200 = 0.10 ; promedio 0.10 -> 10%
        assert demanda.mape([100.0, 200.0], [110.0, 180.0]) == pytest.approx(10.0)

    def test_ignora_los_meses_con_valor_real_cero(self):
        # El cero se descarta; queda solo |50-40|/50 = 0.20 -> 20%
        assert demanda.mape([0.0, 50.0], [5.0, 40.0]) == pytest.approx(20.0)

    def test_sin_datos_utiles_devuelve_nan(self):
        assert np.isnan(demanda.mape([0.0], [1.0]))


class TestPronosticoNaiveEstacional:

    def test_repite_el_valor_del_mismo_mes_del_ano_anterior(self):
        y = np.arange(1.0, 25.0)  # 24 meses: 1..24
        pron = demanda.pronostico_naive_estacional(y, periodo=12, horizonte=3)
        # Los proximos 3 meses valen lo que valieron 12 meses antes: 13, 14, 15.
        assert list(pron) == [13.0, 14.0, 15.0]

    def test_serie_mas_corta_que_el_periodo_no_produce_pronostico(self):
        pron = demanda.pronostico_naive_estacional(np.arange(5.0), periodo=12, horizonte=2)
        assert np.isnan(pron).all()


class TestBandasDesdeResiduos:

    def test_la_banda_se_ensancha_con_la_raiz_del_horizonte(self):
        residuos = np.array([-10.0, 10.0, -10.0, 10.0])  # desvio muestral = 11.547...
        inferior, superior = demanda.bandas_desde_residuos(np.array([1000.0, 1000.0]), residuos)
        desvio = float(np.std(residuos, ddof=1))
        assert superior[0] == pytest.approx(1000.0 + 1.96 * desvio)
        assert superior[1] == pytest.approx(1000.0 + 1.96 * desvio * np.sqrt(2.0))

    def test_el_limite_inferior_nunca_baja_de_cero(self):
        residuos = np.array([-500.0, 500.0, -400.0, 400.0])
        inferior, _ = demanda.bandas_desde_residuos(np.array([100.0]), residuos)
        assert inferior[0] == 0.0

    def test_sin_residuos_suficientes_devuelve_nan(self):
        inferior, superior = demanda.bandas_desde_residuos(np.array([10.0]), np.array([1.0]))
        assert np.isnan(inferior).all() and np.isnan(superior).all()


class TestBacktestYTablaPronostico:

    def test_en_una_serie_estacional_pura_la_linea_base_ingenua_no_se_equivoca(self):
        """Sin tendencia ni ruido, el valor de hace 12 meses es exacto: MAPE 0."""
        serie = _serie_estacional("2022-01-01", 48, PERFIL_CERVEZA)
        prueba = demanda.backtest_origen_movil(serie, periodo=12, meses=12, grid=3)
        assert prueba["origenes"] == 12
        assert prueba["mape_naive"] == pytest.approx(0.0, abs=1e-9)
        assert len(prueba["residuos_naive"]) == 12
        assert np.allclose(prueba["residuos_naive"], 0.0)

    def test_holt_winters_gana_cuando_la_serie_crece_y_la_ingenua_se_queda_corta(self):
        """Con tendencia fuerte, repetir el ano pasado subestima sistematicamente."""
        serie = _serie_estacional("2022-01-01", 48, PERFIL_CERVEZA, crecimiento=0.03)
        prueba = demanda.backtest_origen_movil(serie, periodo=12, meses=12, grid=3)
        assert prueba["mape_hw"] < prueba["mape_naive"]

    def test_la_tabla_publica_el_ganador_y_deja_el_mape_del_perdedor(self):
        matriz = _matriz({"CERVEZAS": _serie_estacional("2022-01-01", 48, PERFIL_CERVEZA,
                                                        nivel=5000.0)})
        tabla, descartes = demanda.tabla_pronostico(matriz, min_bultos=1000.0, grid=3)
        assert descartes == []
        pron = tabla[tabla["tipo"] == "Pronostico"]
        assert len(pron) == constants.HORIZONTE_PRONOSTICO
        # Con empate en el backtest se despacha el modelo simple, no el complejo.
        assert set(pron["modelo_elegido"]) == {demanda.MODELO_NAIVE}
        # Los dos errores viajan en la tabla para que la eleccion sea auditable.
        assert pron.iloc[0]["mape_naive"] == pytest.approx(0.0, abs=1e-9)
        assert "mape_hw" in pron.columns and np.isfinite(pron.iloc[0]["mape_hw"])
        # La serie termina en 2025-12; el pronostico arranca en 2026-01.
        assert pron.iloc[0]["mes"] == "2026-01"
        # Enero vale nivel * 1.10 y la ingenua lo repite exacto.
        assert pron.iloc[0]["bultos"] == pytest.approx(5000.0 * 1.10)

    def test_la_serie_de_volumen_chico_se_descarta_con_su_motivo(self):
        matriz = _matriz({"JUGOS": _serie_estacional("2022-01-01", 48, PERFIL_CERVEZA, nivel=1.0)})
        tabla, descartes = demanda.tabla_pronostico(matriz, min_bultos=50_000.0, grid=3)
        assert tabla.empty
        assert len(descartes) == 1 and "por debajo del piso" in descartes[0]

    def test_la_serie_corta_se_descarta_por_falta_de_historia(self):
        matriz = _matriz({"PERNOD RICARD": _serie_estacional("2026-01-01", 8, PERFIL_CERVEZA)})
        tabla, descartes = demanda.tabla_pronostico(matriz, min_bultos=0.0, grid=3)
        assert tabla.empty
        assert "meses utiles" in descartes[0]


# ── Anomalias (SPC) ──────────────────────────────────────────────────────────


def _diario(fechas, sucursal, bultos):
    return pd.DataFrame({"fecha": fechas, "sucursal": sucursal, "bultos": bultos})


class TestPrepararDiario:

    def test_saca_los_domingos_porque_no_hay_reparto(self):
        # 2026-01-04 es domingo.
        crudo = _diario(["2026-01-02", "2026-01-04", "2026-01-05"], "CASA CENTRAL", [10.0, 1.0, 12.0])
        diario = demanda.preparar_diario(crudo)
        assert list(diario["fecha"].dt.day) == [2, 5]
        assert "Domingo" not in set(diario["dia"])

    def test_saca_los_dias_sin_bultos_positivos(self):
        crudo = _diario(["2026-01-02", "2026-01-05"], "CASA CENTRAL", [0.0, 12.0])
        diario = demanda.preparar_diario(crudo)
        assert len(diario) == 1

    def test_saca_los_feriados_declarados(self):
        crudo = _diario(["2026-01-01", "2026-01-02"], "CASA CENTRAL", [5.0, 12.0])
        diario = demanda.preparar_diario(crudo, feriados=["2026-01-01"])
        assert list(diario["fecha"].dt.day) == [2]

    def test_etiqueta_el_dia_de_la_semana_en_castellano(self):
        crudo = _diario(["2026-01-02"], "CASA CENTRAL", [10.0])  # viernes
        diario = demanda.preparar_diario(crudo)
        assert diario.loc[0, "dia"] == "Viernes"


class TestDetectarAnomalias:

    def _serie_estable_con_un_pico(self, pico: float, n: int = 30, base: float = 100.0,
                                   inicio: str = "2025-01-03") -> pd.DataFrame:
        """n viernes consecutivos alrededor de `base` bultos, salvo el ultimo.

        La variacion de +/-1% existe para que la MAD no colapse: una serie
        perfectamente constante no tiene escala y no admite carta de control.
        """
        fechas = pd.date_range(inicio, periods=n, freq="7D")  # mismo dia de semana
        bultos = [base * (1.0 + 0.01 * (-1) ** i) for i in range(n)]
        bultos[-1] = pico
        return _diario(fechas, "CASA CENTRAL", bultos)

    def test_detecta_el_pico_como_quiebre_alto(self):
        diario = demanda.preparar_diario(self._serie_estable_con_un_pico(10_000.0))
        quiebres, limites = demanda.detectar_anomalias(diario)
        assert len(quiebres) == 1
        assert quiebres.iloc[0]["direccion"] == "Alta"
        assert quiebres.iloc[0]["bultos"] == 10_000.0
        assert quiebres.iloc[0]["z"] > constants.SPC_SIGMAS
        assert limites.iloc[0]["observaciones"] == 30

    def test_detecta_la_caida_como_quiebre_bajo_gracias_a_la_escala_logaritmica(self):
        """En escala cruda el limite inferior cae bajo cero y la caida no se ve."""
        diario = demanda.preparar_diario(self._serie_estable_con_un_pico(1.0))
        quiebres, _ = demanda.detectar_anomalias(diario)
        assert len(quiebres) == 1
        assert quiebres.iloc[0]["direccion"] == "Baja"
        assert quiebres.iloc[0]["z"] < -constants.SPC_SIGMAS

    def test_los_limites_en_escala_logaritmica_quedan_siempre_por_encima_de_cero(self):
        diario = demanda.preparar_diario(self._serie_estable_con_un_pico(10_000.0))
        _, limites = demanda.detectar_anomalias(diario)
        assert (limites["limite_inf"] > 0).all()

    def test_un_grupo_con_pocas_observaciones_no_se_evalua(self):
        diario = demanda.preparar_diario(self._serie_estable_con_un_pico(10_000.0, n=10))
        quiebres, limites = demanda.detectar_anomalias(diario)
        assert quiebres.empty and limites.empty

    def test_cada_dia_de_la_semana_tiene_su_propio_juego_de_limites(self):
        """El sabado es estructuralmente distinto: sin estratificar parece caida."""
        viernes = self._serie_estable_con_un_pico(101.0, base=100.0, inicio="2025-01-03")
        sabados = self._serie_estable_con_un_pico(505.0, base=500.0, inicio="2025-01-04")
        diario = demanda.preparar_diario(pd.concat([viernes, sabados], ignore_index=True))
        quiebres, limites = demanda.detectar_anomalias(diario)
        centros = dict(zip(limites["dia"], limites["centro"]))
        assert centros["Viernes"] == pytest.approx(100.0, rel=0.02)
        assert centros["Sabado"] == pytest.approx(500.0, rel=0.02)
        # Ningun sabado se marca como quiebre pese a quintuplicar al viernes.
        assert quiebres.empty

    def test_una_serie_perfectamente_constante_no_admite_carta_de_control(self):
        diario = demanda.preparar_diario(
            _diario(pd.date_range("2025-01-03", periods=30, freq="7D"), "CASA CENTRAL", [100.0] * 30)
        )
        quiebres, limites = demanda.detectar_anomalias(diario)
        assert quiebres.empty and limites.empty


class TestDiasConEvento:

    def _quiebres(self, filas):
        return pd.DataFrame(
            filas, columns=["fecha", "sucursal", "dia", "bultos", "limite_inf",
                            "limite_sup", "z", "direccion"]
        ).assign(fecha=lambda d: pd.to_datetime(d["fecha"]))

    def test_solo_sobreviven_las_fechas_con_varias_sucursales_a_la_vez(self):
        quiebres = self._quiebres(
            [
                ("2026-01-05", "A", "Lunes", 10.0, 1.0, 5.0, 4.0, "Alta"),
                ("2026-01-05", "B", "Lunes", 20.0, 1.0, 5.0, 4.0, "Alta"),
                ("2026-01-05", "C", "Lunes", 30.0, 1.0, 5.0, -4.0, "Baja"),
                ("2026-01-06", "A", "Martes", 99.0, 1.0, 5.0, 4.0, "Alta"),
            ]
        )
        eventos = demanda.dias_con_evento(quiebres, min_sucursales=3)
        assert len(eventos) == 1
        fila = eventos.iloc[0]
        assert fila["fecha"] == pd.Timestamp("2026-01-05")
        assert fila["sucursales_en_alerta"] == 3
        assert fila["bultos"] == pytest.approx(60.0)
        assert fila["altas"] == 2 and fila["bajas"] == 1
        assert fila["direccion"] == "Alta"

    def test_sin_fechas_multiples_devuelve_tabla_vacia_con_las_columnas(self):
        quiebres = self._quiebres([("2026-01-06", "A", "Martes", 99.0, 1.0, 5.0, 4.0, "Alta")])
        eventos = demanda.dias_con_evento(quiebres, min_sucursales=3)
        assert eventos.empty
        assert "sucursales_en_alerta" in eventos.columns


# ── Alerta estacional accionable ─────────────────────────────────────────────


class TestTablaEstacionalidadAlerta:

    def _estacionalidad(self, desvio_residual=None) -> pd.DataFrame:
        fila = {"generico": "CERVEZAS", "meses": 48}
        # Indice 1.0 todos los meses salvo diciembre (1.5) y julio (0.5).
        for mes in demanda.MESES_ES:
            fila[f"indice_{mes.lower()}"] = 1.0
        fila["indice_dic"] = 1.5
        fila["indice_jul"] = 0.5
        if desvio_residual is not None:
            fila["desvio_residual"] = desvio_residual
        return pd.DataFrame([fila])

    def test_compara_los_proximos_tres_meses_contra_el_mes_de_referencia(self):
        tabla = demanda.tabla_estacionalidad_alerta(
            self._estacionalidad(), mes_referencia=10, bultos_referencia={"CERVEZAS": 1000.0}
        )
        assert tabla["mes"].tolist() == ["Nov", "Dic", "Ene"]
        assert tabla["mes_referencia"].unique().tolist() == ["Oct"]

    def test_la_variacion_y_los_bultos_esperados_salen_del_cociente_de_indices(self):
        tabla = demanda.tabla_estacionalidad_alerta(
            self._estacionalidad(), mes_referencia=10, bultos_referencia={"CERVEZAS": 1000.0}
        )
        diciembre = tabla[tabla["mes"] == "Dic"].iloc[0]
        # Referencia octubre = 1.0, diciembre = 1.5 -> +50% y 1500 bultos esperados.
        assert diciembre["variacion_vs_referencia"] == pytest.approx(0.5)
        assert diciembre["bultos_esperados_estacional"] == pytest.approx(1500.0)
        assert diciembre["lectura"] == "Pico: reforzar stock y cobranza"

    def test_marca_el_valle_cuando_el_indice_se_desploma(self):
        tabla = demanda.tabla_estacionalidad_alerta(
            self._estacionalidad(), mes_referencia=6, bultos_referencia={"CERVEZAS": 1000.0}
        )
        julio = tabla[tabla["mes"] == "Jul"].iloc[0]
        assert julio["variacion_vs_referencia"] == pytest.approx(-0.5)
        assert julio["lectura"] == "Valle: bajar compra"

    def test_el_mes_de_referencia_da_la_vuelta_al_ano(self):
        tabla = demanda.tabla_estacionalidad_alerta(
            self._estacionalidad(), mes_referencia=12, bultos_referencia={}
        )
        assert tabla["mes"].tolist() == ["Ene", "Feb", "Mar"]


# ── El freno de ruido sobre las lecturas accionables ─────────────────────────


class TestMotivoNoLegible:
    """Un indice no se convierte en instruccion si es ruido o si el volumen es chico."""

    def test_una_serie_grande_y_estable_es_legible(self):
        assert demanda.motivo_no_legible(0.09, 150_000.0) == ""

    def test_el_ruido_residual_alto_anula_la_lectura(self):
        # SIDRAS Y LICORES medido: residuo 0.63 sobre un maximo de 0.35.
        motivo = demanda.motivo_no_legible(0.63, 500_000.0)
        assert "ruido residual 0.63" in motivo

    def test_el_volumen_chico_anula_la_lectura_aunque_el_indice_sea_limpio(self):
        # JUGOS medido: residuo 0.26 (limpio) pero 63 bultos de referencia.
        motivo = demanda.motivo_no_legible(0.26, 63.0)
        assert "volumen de referencia 63 bultos" in motivo

    def test_el_volumen_desconocido_no_bloquea_por_si_solo(self):
        assert demanda.motivo_no_legible(0.10, float("nan")) == ""

    def test_el_residuo_desconocido_no_bloquea_por_si_solo(self):
        assert demanda.motivo_no_legible(float("nan"), 50_000.0) == ""

    def test_justo_en_el_piso_de_volumen_todavia_se_lee(self):
        assert demanda.motivo_no_legible(0.10, demanda.MIN_BULTOS_MES_LECTURA) == ""


class TestLecturaSoloParaSeriesLegibles:

    def _alerta(self, desvio, bultos):
        estacionalidad = TestTablaEstacionalidadAlerta()._estacionalidad(desvio_residual=desvio)
        return demanda.tabla_estacionalidad_alerta(
            estacionalidad, mes_referencia=10, bultos_referencia={"CERVEZAS": bultos}
        )

    def test_la_serie_ruidosa_no_recibe_orden_de_reforzar_stock(self):
        """Regresion: SIDRAS Y LICORES pedia reforzar stock sobre 149 bultos."""
        tabla = self._alerta(desvio=0.63, bultos=149.0)
        diciembre = tabla[tabla["mes"] == "Dic"].iloc[0]
        assert diciembre["lectura"].startswith(demanda.LECTURA_SIN_DATO)
        assert "Pico" not in diciembre["lectura"]
        assert diciembre["confiabilidad"].startswith("No legible")

    def test_la_fila_no_se_borra_y_conserva_el_indice_para_auditar(self):
        tabla = self._alerta(desvio=0.63, bultos=149.0)
        assert len(tabla) == 3
        diciembre = tabla[tabla["mes"] == "Dic"].iloc[0]
        assert diciembre["indice"] == pytest.approx(1.5)
        assert diciembre["variacion_vs_referencia"] == pytest.approx(0.5)

    def test_la_serie_grande_y_limpia_conserva_su_instruccion(self):
        tabla = self._alerta(desvio=0.09, bultos=150_000.0)
        diciembre = tabla[tabla["mes"] == "Dic"].iloc[0]
        assert diciembre["lectura"] == "Pico: reforzar stock y cobranza"
        assert diciembre["confiabilidad"] == "Legible"


class TestEtiquetaLegibilidad:

    def test_marca_si_cuando_el_residuo_es_bajo(self):
        assert demanda.etiqueta_legibilidad(0.09) == "Si"

    def test_marca_no_con_el_motivo_cuando_el_residuo_es_alto(self):
        assert demanda.etiqueta_legibilidad(0.73).startswith("No: ruido residual 0.73")

    def test_la_tabla_de_estacionalidad_trae_la_columna(self):
        matriz = _matriz({"CERVEZAS": _serie_estacional("2022-01-01", 36, PERFIL_CERVEZA)})
        tabla, _ = demanda.tabla_estacionalidad(matriz)
        # Serie perfectamente estacional: residuo practicamente nulo.
        assert tabla.iloc[0]["indice_legible"] == "Si"


# ── El mes de corte incompleto ───────────────────────────────────────────────


class TestDiasHabilesFaltantesDelMes:

    def test_el_corte_al_30_de_julio_deja_afuera_el_viernes_31(self):
        from datetime import date

        # 2026-07-31 es viernes: es un dia de reparto y falta.
        assert demanda.dias_habiles_faltantes_del_mes(date(2026, 7, 30)) == 1

    def test_el_ultimo_dia_del_mes_no_deja_nada_afuera(self):
        from datetime import date

        assert demanda.dias_habiles_faltantes_del_mes(date(2026, 6, 30)) == 0

    def test_los_domingos_no_cuentan_como_dia_de_reparto(self):
        from datetime import date

        # De 2026-05-29 (viernes) al 31: falta el sabado 30; el domingo 31 no cuenta.
        assert demanda.dias_habiles_faltantes_del_mes(date(2026, 5, 29)) == 1

    def test_el_feriado_declarado_tampoco_cuenta(self):
        from datetime import date

        assert demanda.dias_habiles_faltantes_del_mes(
            date(2026, 7, 30), feriados=["2026-07-31"]
        ) == 0


# ── Punto ciego del SPC: los dias sin factura ────────────────────────────────


class TestDiasSinFactura:

    def test_cuenta_el_dia_habil_en_el_que_la_sucursal_no_facturo_nada(self):
        # Lunes a viernes, pero el miercoles no existe como fila.
        fechas = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-08", "2026-01-09"])
        diario = demanda.preparar_diario(_diario(fechas, "CASA CENTRAL", [10.0] * 4))
        ceros, panel = demanda.dias_sin_factura(diario)
        assert ceros == 1
        assert panel == 5

    def test_el_domingo_del_medio_no_cuenta_como_dia_perdido(self):
        # Sabado 2026-01-03 y lunes 2026-01-05: el domingo 4 no es dia de reparto.
        fechas = pd.to_datetime(["2026-01-03", "2026-01-05"])
        diario = demanda.preparar_diario(_diario(fechas, "CASA CENTRAL", [10.0, 12.0]))
        assert demanda.dias_sin_factura(diario) == (0, 2)

    def test_el_feriado_tampoco_cuenta_como_dia_perdido(self):
        fechas = pd.to_datetime(["2026-01-05", "2026-01-07"])
        diario = demanda.preparar_diario(_diario(fechas, "CASA CENTRAL", [10.0, 12.0]))
        assert demanda.dias_sin_factura(diario, feriados=["2026-01-06"]) == (0, 2)

    def test_el_rango_es_por_sucursal_para_no_contar_la_que_todavia_no_abrio(self):
        """Una sucursal que arranca tarde no arrastra los dias previos como paradas."""
        vieja = _diario(pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"]), "A", [10.0] * 3)
        nueva = _diario(pd.to_datetime(["2026-01-07"]), "B", [5.0])
        diario = demanda.preparar_diario(pd.concat([vieja, nueva], ignore_index=True))
        assert demanda.dias_sin_factura(diario) == (0, 4)

    def test_sin_datos_devuelve_cero(self):
        assert demanda.dias_sin_factura(pd.DataFrame()) == (0, 0)


class TestSqlDevoluciones:

    def test_mide_facturado_y_devuelto_en_la_misma_consulta(self):
        consulta = demanda.sql_devoluciones()
        assert "bultos_facturados" in consulta and "bultos_devueltos" in consulta
        assert "%(dev)s" in consulta and "%(doc)s" in consulta
        # Y sigue excluyendo los genericos que no son articulos de venta.
        assert "MARKETING" in consulta
        for prohibida in ("INSERT ", "UPDATE ", "DELETE ", "DROP "):
            assert prohibida not in consulta.upper()


# ── Crecimiento real ─────────────────────────────────────────────────────────


class TestCrecimiento12mHtl:

    def test_compara_los_ultimos_doce_meses_contra_los_doce_previos(self):
        idx = pd.date_range("2024-01-01", periods=24, freq="MS")
        # Primeros 12 meses: 100 htl/mes. Ultimos 12: 110 htl/mes -> +10%.
        largo = pd.DataFrame(
            {
                "mes": idx,
                "generico": ["CERVEZAS"] * 24,
                "bultos": [1000.0] * 24,
                "hectolitros": [100.0] * 12 + [110.0] * 12,
                "lineas": [1] * 24,
                "clientes": [1] * 24,
            }
        )
        ultimos, previos, variacion = demanda.crecimiento_12m_htl(largo)
        assert ultimos == pytest.approx(1320.0)
        assert previos == pytest.approx(1200.0)
        assert variacion == pytest.approx(0.10)

    def test_con_menos_de_dos_anos_no_se_puede_medir(self):
        idx = pd.date_range("2026-01-01", periods=6, freq="MS")
        largo = pd.DataFrame(
            {
                "mes": idx,
                "generico": ["CERVEZAS"] * 6,
                "bultos": [1.0] * 6,
                "hectolitros": [1.0] * 6,
                "lineas": [1] * 6,
                "clientes": [1] * 6,
            }
        )
        assert np.isnan(demanda.crecimiento_12m_htl(largo)[2])


# ── Robustez ante datos degenerados ──────────────────────────────────────────


class TestTablasVaciasNoRompen:

    def test_ninguna_transformacion_levanta_excepcion_con_entrada_vacia(self):
        vacio = pd.DataFrame()
        assert demanda.normalizar_serie_mensual(vacio).empty
        assert demanda.tabla_serie_mensual(pd.DataFrame(columns=["mes", "generico"])).empty
        assert demanda.tabla_estacionalidad(vacio)[0].empty
        assert demanda.tabla_pronostico(vacio)[0].empty
        assert demanda.preparar_diario(vacio).empty
        assert demanda.detectar_anomalias(vacio)[0].empty
        assert demanda.dias_con_evento(vacio).empty
        assert demanda.tabla_estacionalidad_alerta(vacio, 1).empty
        assert demanda.agregar_total_general(vacio, "x", []).empty

    def test_el_sql_solo_lee(self):
        for consulta in (
            demanda.sql_serie_mensual(),
            demanda.sql_diario_sucursal(),
            demanda.sql_participacion_mostrador(),
        ):
            texto = consulta.upper()
            assert texto.lstrip().startswith("\n        SELECT") or "SELECT" in texto
            for prohibida in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE "):
                assert prohibida not in texto
