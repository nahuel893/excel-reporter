"""La ventana relativa: `fecha_modo` en el config, resuelta por main.py.

Existe porque las fechas guardadas en un JSON envejecen. El daily las patchea
en cada corrida, pero `main.py --config` usaba lo que quedaba escrito, y el
informe de FULL SPORT salio con junio-julio cuando tenia que ser julio-agosto.
"""
import json
from datetime import date
from unittest.mock import patch

import pytest

from src.config.resolver import load_report_config
from src.core.periodos import (
    es_primer_dia_habil_del_mes,
    rango_mes_a_hoy,
    rango_mes_completo,
    resolver_ventana,
)

from pathlib import Path

CONFIG_FULL_SPORT = Path("configs/ventas_cober_preventista_marca.json")
CONFIG_AGUAS = Path("configs/cobertura_aguas.json")


# --- resolver_ventana -------------------------------------------------------

def test_mes_a_hoy_devuelve_el_mes_en_curso():
    assert resolver_ventana("mes_a_hoy", date(2026, 8, 12)) == ("2026-08-01", "2026-08-12")


def test_mes_a_hoy_el_primer_dia_habil_manda_el_mes_anterior_cerrado():
    """1-08-2026 es sabado y aca el sabado ES habil, asi que cae en la regla."""
    assert resolver_ventana("mes_a_hoy", date(2026, 8, 1)) == ("2026-07-01", "2026-07-31")


def test_mes_completo_cierra_con_limite_exclusivo():
    """Para el SQL que usa `fecha_comprobante < :fecha_hasta`."""
    assert resolver_ventana("mes_completo", date(2026, 8, 12)) == ("2026-08-01", "2026-08-13")


def test_hoy_es_un_solo_dia():
    assert resolver_ventana("hoy", date(2026, 8, 12)) == ("2026-08-12", "2026-08-12")


def test_un_modo_mal_escrito_rompe_fuerte():
    """No puede caer en silencio a las fechas guardadas: ese ES el bug."""
    with pytest.raises(ValueError, match="fecha_modo desconocido"):
        resolver_ventana("mes_a_ayer", date(2026, 8, 12))


def test_el_domingo_no_es_dia_habil():
    assert not es_primer_dia_habil_del_mes(date(2026, 11, 1))  # domingo


def test_mes_a_hoy_y_mes_completo_difieren_solo_en_el_limite():
    hoy = date(2026, 8, 12)
    a_hoy, completo = rango_mes_a_hoy(hoy), rango_mes_completo(hoy)
    assert a_hoy[0] == completo[0]
    assert a_hoy[1] == "2026-08-12" and completo[1] == "2026-08-13"


def test_cruza_el_anio():
    assert resolver_ventana("mes_a_hoy", date(2026, 1, 15)) == ("2026-01-01", "2026-01-15")


# --- integracion con el config ---------------------------------------------

def test_full_sport_declara_ventana_relativa():
    """Si alguien la saca, el informe vuelve a salir con el mes equivocado."""
    cfg = load_report_config(CONFIG_FULL_SPORT)
    assert cfg.filtros.fecha_modo == "mes_a_hoy"


def test_full_sport_manda_a_preventa_salta_y_a_gonzalo():
    cfg = load_report_config(CONFIG_FULL_SPORT)
    assert set(cfg.reportes[0].enviar_a) == {"Preventa Salta", "Gonzalo Farah"}


def test_sin_fecha_modo_las_fechas_del_config_se_respetan():
    """La ventana relativa es opt-in: sin el campo, nada cambia."""
    cfg = load_report_config(CONFIG_AGUAS)
    assert cfg.filtros.fecha_modo is None
    assert cfg.filtros.fecha_desde == "2026-06-01"


def test_main_reescribe_las_fechas_cuando_hay_fecha_modo(tmp_path):
    """El contrato completo: main.py pisa lo guardado con la ventana resuelta."""
    import main

    cfg = json.loads(CONFIG_FULL_SPORT.read_text())
    cfg["filtros"]["fecha_desde"] = "2020-01-01"   # deliberadamente viejas
    cfg["filtros"]["fecha_hasta"] = "2020-01-31"
    # Sin destinatarios: al test le interesa la ventana, y con el catalogo vacio
    # la validacion de contactos cortaria antes de llegar a _run_reportes.
    cfg["reportes"][0]["enviar_a"] = {}
    destino = tmp_path / "cfg.json"
    destino.write_text(json.dumps(cfg))

    visto = {}

    def _capturar(report_config, contactos, **kw):
        visto["desde"] = report_config.filtros.fecha_desde
        visto["hasta"] = report_config.filtros.fecha_hasta
        return 0

    with patch.object(main, "_run_reportes", _capturar):
        main._run_report_config(destino, contactos_path=tmp_path / "no-hay.json")

    esperado = rango_mes_a_hoy(date.today())
    assert (visto["desde"], visto["hasta"]) == esperado
    assert visto["desde"] != "2020-01-01"
