"""Tests de las constantes de dominio.

Las reglas RFM se evaluan con 'gana la primera coincidencia', asi que el ORDEN
es logica, no presentacion. Una version anterior dejaba tres segmentos sin
ningun cliente porque una regla mas amplia los tapaba, y el segmento tapado era
justamente el de mayor prioridad comercial ('No perder'). Estos tests existen
para que eso no vuelva a pasar en silencio.
"""
import pytest

from src.services.inteligencia_comercial import constants as k


def segmento_de(r: int, f: int) -> str | None:
    """Resuelve un par (R,F) con la misma regla que usan los modulos."""
    for min_r, max_r, min_f, max_f, label, _accion in k.SEGMENTOS_RFM:
        if min_r <= r <= max_r and min_f <= f <= max_f:
            return label
    return None


CELDAS = [(r, f) for r in range(1, 6) for f in range(1, 6)]


class TestSegmentosRFM:
    def test_toda_celda_rfm_cae_en_algun_segmento(self):
        sin_segmento = [(r, f) for r, f in CELDAS if segmento_de(r, f) is None]
        assert sin_segmento == [], f"celdas sin segmento: {sin_segmento}"

    def test_todos_los_segmentos_son_alcanzables(self):
        declarados = {regla[4] for regla in k.SEGMENTOS_RFM}
        alcanzados = {segmento_de(r, f) for r, f in CELDAS}
        assert declarados == alcanzados, f"segmentos inalcanzables: {declarados - alcanzados}"

    def test_no_perder_gana_sobre_leales(self):
        # R2-3 con F4-5 es el cliente valioso que se esta yendo: es la lista de
        # llamados de la semana y no puede quedar diluido dentro de 'Leales'
        assert segmento_de(2, 5) == "No perder"
        assert segmento_de(3, 4) == "No perder"

    def test_el_mejor_cliente_es_campeon(self):
        assert segmento_de(5, 5) == "Campeones"

    def test_el_peor_cliente_esta_perdido(self):
        assert segmento_de(1, 1) == "Perdidos"

    def test_el_reciente_sin_historia_es_nuevo(self):
        assert segmento_de(5, 1) == "Nuevos"

    def test_el_que_compraba_mucho_y_desaparecio_hiberna(self):
        assert segmento_de(1, 5) == "Hibernando"

    def test_cada_segmento_trae_una_accion_concreta(self):
        for regla in k.SEGMENTOS_RFM:
            accion = regla[5]
            assert accion and len(accion) > 15, f"accion pobre en {regla[4]}"

    def test_todo_segmento_tiene_color(self):
        for regla in k.SEGMENTOS_RFM:
            assert regla[4] in k.SEGMENTO_COLORES

    def test_los_rangos_son_validos(self):
        for min_r, max_r, min_f, max_f, label, _ in k.SEGMENTOS_RFM:
            assert 1 <= min_r <= max_r <= 5, label
            assert 1 <= min_f <= max_f <= 5, label


class TestUniversos:
    def test_los_genericos_ccu_son_exactamente_cinco(self):
        assert len(k.GENERICOS_CCU) == 5
        assert "CERVEZAS" in k.GENERICOS_CCU
        # FRATELLI B es fernet, no es CCU
        assert "FRATELLI B" not in k.GENERICOS_CCU

    def test_marketing_no_es_articulo_de_venta(self):
        # dejarlo adentro inventa anomalias: 10.044 bultos facturados a $10 en total
        assert "MARKETING" in k.GENERICOS_NO_VENTA

    def test_los_envases_no_son_articulos_de_venta(self):
        for generico in ("ENVASES CCU", "ENVASES GASEOSAS", "ENVASES PALAU"):
            assert generico in k.GENERICOS_NO_VENTA

    def test_la_lista_de_mostrador_no_tiene_duplicados(self):
        assert len(k.CLIENTES_MOSTRADOR) == len(set(k.CLIENTES_MOSTRADOR))

    def test_el_agregado_mas_grande_esta_en_la_lista(self):
        # 70001 (PERICO) tiene fantasia vacia: filtrar solo por fantasia lo dejaba
        # afuera, y es el cliente #1 de toda la base por neto
        assert 70001 in k.CLIENTES_MOSTRADOR

    def test_hay_un_agregado_por_sucursal_al_menos(self):
        # los buckets de mostrador son por sucursal; menos de 14 significa que
        # la regla de identificacion volvio a quedar corta
        assert len(k.CLIENTES_MOSTRADOR) >= 14

    def test_anulado_no_se_usa_como_filtro_de_actividad(self):
        # 621 clientes anulado=true facturaron $717,7M en 6 meses
        assert k.USAR_ANULADO_COMO_FILTRO is False

    def test_abra_pampa_esta_marcada_como_cerrada(self):
        assert "SUCURSAL ABRA PAMPA" in k.SUCURSALES_CERRADAS


class TestParametros:
    def test_los_cortes_abc_son_crecientes(self):
        assert k.ABC_CORTES[0] < k.ABC_CORTES[1] < 1.0

    def test_los_cortes_xyz_son_crecientes(self):
        assert k.XYZ_CORTES[0] < k.XYZ_CORTES[1]

    def test_la_cobertura_de_quiebre_es_menor_que_la_de_sobrestock(self):
        assert k.COBERTURA_QUIEBRE_DIAS < k.COBERTURA_SOBRESTOCK_DIAS

    def test_el_spc_usa_log(self):
        # en bultos crudos el limite inferior cae por debajo de cero en las 14
        # sucursales y el detector solo puede disparar hacia arriba
        assert k.SPC_USAR_LOG is True

    def test_la_red_completa_es_posterior_al_onboarding(self):
        # antes de 2023-06-16 fact_ventas solo tiene CASA CENTRAL
        assert k.FECHA_RED_COMPLETA >= "2024-06-12"
