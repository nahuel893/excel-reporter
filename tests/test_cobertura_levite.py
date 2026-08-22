"""Tests para el servicio y procesador de Cobertura Levite por Calibre."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.services.cobertura_levite.processor import (
    extraer_calibre,
    ordenar_calibres,
    procesar_cobertura_sucursal_calibre,
    procesar_clientes_compradores,
)
from src.services.cobertura_levite.service import (
    CoberturaLeviteConfig,
    CoberturaLeviteService,
)


def test_extraer_calibre_varios():
    assert extraer_calibre("LEVITE POMELO S/GAS 1500*6") == "1500cc"
    assert extraer_calibre("LEVITE POMELO S/GAS 2250*6") == "2250cc"
    assert extraer_calibre("LEVITE NARANJA S/GAS 500*12") == "500cc"
    assert extraer_calibre("LEVITE NARANJA 500*6") == "500cc"
    assert extraer_calibre("LEVITE POMELO S/GAS 1000*6") == "1000cc"
    assert extraer_calibre("LEVITE FIZZ LIMON 575*12") == "575cc"
    assert extraer_calibre("LEVITE POMELO 300*12") == "300cc"
    assert extraer_calibre("LEVITE POMELO S/GAS 2000*6") == "2000cc"
    assert extraer_calibre("LEVITE MANZANA S/GAS 2500*6") == "2500cc"
    assert extraer_calibre("VISSU LEVITE") == "OTRO"
    assert extraer_calibre(None) == "OTRO"


def test_ordenar_calibres():
    entrada = ["2250cc", "500cc", "1500cc", "300cc", "1000cc"]
    esperado = ["300cc", "500cc", "1000cc", "1500cc", "2250cc"]
    assert ordenar_calibres(entrada) == esperado


def test_procesar_cobertura_sucursal_calibre_vacio():
    df_ventas = pd.DataFrame(columns=["id_sucursal", "sucursal", "id_cliente", "calibre", "id_articulo", "bultos"])
    df_padron = pd.DataFrame([{"id_sucursal": 1, "sucursal": "CASA CENTRAL", "padron": 100}])
    calibres = ["500cc", "1500cc"]
    
    df_matriz, df_resumen = procesar_cobertura_sucursal_calibre(df_ventas, df_padron, calibres)
    assert len(df_matriz) == 2  # 1 sucursal + TOTAL GENERAL
    assert df_matriz.loc[df_matriz["sucursal"] == "CASA CENTRAL", "cob_total"].iloc[0] == 0
    assert len(df_resumen) == 3  # 2 calibres + TOTAL LEVITE


def test_procesar_cobertura_sucursal_calibre_con_datos():
    df_ventas = pd.DataFrame([
        {"id_sucursal": 1, "sucursal": "CASA CENTRAL", "id_cliente": 101, "calibre": "500cc", "id_articulo": 1, "bultos": 2.0},
        {"id_sucursal": 1, "sucursal": "CASA CENTRAL", "id_cliente": 101, "calibre": "1500cc", "id_articulo": 2, "bultos": 1.0},
        {"id_sucursal": 1, "sucursal": "CASA CENTRAL", "id_cliente": 102, "calibre": "1500cc", "id_articulo": 2, "bultos": 3.0},
        {"id_sucursal": 2, "sucursal": "ORAN", "id_cliente": 201, "calibre": "2250cc", "id_articulo": 3, "bultos": 5.0},
    ])
    df_padron = pd.DataFrame([
        {"id_sucursal": 1, "sucursal": "CASA CENTRAL", "padron": 10},
        {"id_sucursal": 2, "sucursal": "ORAN", "padron": 10},
    ])
    calibres = ["500cc", "1500cc", "2250cc"]
    
    df_matriz, df_resumen = procesar_cobertura_sucursal_calibre(df_ventas, df_padron, calibres)
    
    # CASA CENTRAL: 2 clientes unicos, cob 500cc = 1, cob 1500cc = 2
    cc = df_matriz[df_matriz["sucursal"] == "CASA CENTRAL"].iloc[0]
    assert cc["cob_500cc"] == 1
    assert cc["cob_1500cc"] == 2
    assert cc["cob_2250cc"] == 0
    assert cc["cob_total"] == 2
    assert cc["pct_cob_total"] == 0.2
    
    # TOTAL GENERAL: 3 clientes unicos
    tg = df_matriz[df_matriz["es_total_general"]].iloc[0]
    assert tg["cob_total"] == 3
    assert tg["vol_total"] == 11.0


def test_procesar_clientes_compradores():
    df_ventas = pd.DataFrame([
        {"id_sucursal": 1, "sucursal": "CASA CENTRAL", "id_cliente": 101, "cliente": "JUAN", "id_ruta": 5, "vendedor": "PEDRO", "calibre": "500cc", "bultos": 2.0},
        {"id_sucursal": 1, "sucursal": "CASA CENTRAL", "id_cliente": 101, "cliente": "JUAN", "id_ruta": 5, "vendedor": "PEDRO", "calibre": "1500cc", "bultos": 1.0},
        {"id_sucursal": 1, "sucursal": "CASA CENTRAL", "id_cliente": 102, "cliente": "ANA", "id_ruta": 5, "vendedor": "PEDRO", "calibre": "1500cc", "bultos": 3.0},
    ])
    calibres = ["500cc", "1500cc", "2250cc"]
    df_cli = procesar_clientes_compradores(df_ventas, calibres)
    
    assert len(df_cli) == 2
    cli101 = df_cli[df_cli["id_cliente"] == 101].iloc[0]
    assert cli101["500cc"] == 2.0
    assert cli101["1500cc"] == 1.0
    assert cli101["2250cc"] == 0.0
    assert cli101["total_bultos"] == 3.0
    assert cli101["calibres_comprados"] == 2


# --- matriz calibre x marca -------------------------------------------------

import pandas as pd
import pytest

from src.services.cobertura_levite.processor import CATEGORIAS, matriz_calibre_marca

COLS_MM = ["id_sucursal", "sucursal", "id_cliente", "marca", "calibre", "bultos"]


def _v(filas):
    return pd.DataFrame(filas, columns=COLS_MM)


def test_la_cobertura_no_se_suma_entre_calibres():
    """El que compra 500 y 1500 de la misma marca es UN cliente en el total."""
    v = _v([
        (1, "S", 7, "LEVITE", "500cc", 5.0),
        (1, "S", 7, "LEVITE", "1500cc", 5.0),
    ])
    df, _ = matriz_calibre_marca(v)
    fila_total = df[df["calibre"] == "TOTAL"].iloc[0]
    assert df[df["calibre"] == "500cc"].iloc[0]["LEVITE"] == 1
    assert df[df["calibre"] == "1500cc"].iloc[0]["LEVITE"] == 1
    assert fila_total["LEVITE"] == 1, "sumar los calibres daria 2"


def test_la_cobertura_no_se_suma_entre_marcas():
    """El que compra LEVITE y BRIO es UNO en el total de saborizadas."""
    v = _v([
        (1, "S", 7, "LEVITE", "1500cc", 5.0),
        (1, "S", 7, "BRIO", "1500cc", 5.0),
    ])
    df, _ = matriz_calibre_marca(v)
    fila = df[df["calibre"] == "1500cc"].iloc[0]
    assert fila["LEVITE"] == 1 and fila["BRIO"] == 1
    assert fila["TOTAL AGUA SABORIZADA"] == 1, "sumar las marcas daria 2"


def test_full_sport_es_isotonica_y_no_saborizada():
    """FULL SPORT suma al TOTAL AGUAS pero NO al de saborizadas."""
    v = _v([
        (1, "S", 7, "FULL SPORT", "500cc", 5.0),
        (1, "S", 9, "LEVITE", "500cc", 5.0),
    ])
    df, bloques = matriz_calibre_marca(v)
    fila = df[df["calibre"] == "500cc"].iloc[0]
    assert fila["TOTAL ISOTONICA"] == 1
    assert fila["TOTAL AGUA SABORIZADA"] == 1, "solo LEVITE"
    assert fila["TOTAL AGUAS"] == 2
    etiquetas = [e for e, _ in bloques]
    assert "ISOTONICA" in etiquetas


def test_agrupa_por_cliente_antes_de_filtrar():
    """Compra 5 y devuelve 5: neto 0, no esta cubierto."""
    v = _v([
        (1, "S", 7, "LEVITE", "500cc", 5.0),
        (1, "S", 7, "LEVITE", "500cc", -5.0),
    ])
    df, _ = matriz_calibre_marca(v)
    assert df[df["calibre"] == "500cc"].iloc[0]["LEVITE"] == 0


def test_clave_compuesta_de_cliente():
    """id_cliente se reusa entre sucursales: son dos clientes."""
    v = _v([
        (1, "S1", 7, "LEVITE", "500cc", 5.0),
        (5, "S5", 7, "LEVITE", "500cc", 5.0),
    ])
    df, _ = matriz_calibre_marca(v)
    assert df[df["calibre"] == "500cc"].iloc[0]["LEVITE"] == 2


def test_una_marca_sin_ventas_no_genera_columna():
    """Una columna entera en cero es ruido en un cuadro que se mira de un vistazo."""
    v = _v([(1, "S", 7, "LEVITE", "500cc", 5.0)])
    df, bloques = matriz_calibre_marca(v)
    assert "BRIO" not in df.columns
    assert bloques == [("AGUA SABORIZADA", ["LEVITE"])]


def test_los_calibres_van_de_menor_a_mayor():
    v = _v([
        (1, "S", 7, "LEVITE", "2250cc", 5.0),
        (1, "S", 7, "LEVITE", "500cc", 5.0),
        (1, "S", 7, "LEVITE", "1500cc", 5.0),
    ])
    df, _ = matriz_calibre_marca(v)
    assert list(df["calibre"]) == ["500cc", "1500cc", "2250cc", "TOTAL"]


def test_las_categorias_separan_mineral_saborizada_e_isotonica():
    grupos = dict(CATEGORIAS)
    assert grupos["AGUA MINERAL"] == ("VILLA DEL SUR", "VILLAVICENCIO")
    assert grupos["AGUA SABORIZADA"] == ("LEVITE", "BRIO")
    assert grupos["ISOTONICA"] == ("FULL SPORT",)


# --- config y entrega -------------------------------------------------------

def test_el_config_manda_a_los_tres_por_mail_y_wpp():
    from pathlib import Path

    from src.config.resolver import load_report_config

    cfg = load_report_config(Path("configs/cobertura_levite.json"))
    envios = cfg.reportes[0].enviar_a
    for nombre in ("Sebastian Dellamea", "Antonio Cabrerizo", "Gonzalo Farah"):
        assert "email" in envios[nombre].via, f"{nombre} sin mail"
        assert "whatsapp" in envios[nombre].via, f"{nombre} sin whatsapp"
    assert cfg.filtros.enviar_email is True
    assert cfg.filtros.enviar_whatsapp is True


def test_el_config_captura_una_hoja_por_generico():
    from pathlib import Path

    from src.config.resolver import load_report_config

    cap = load_report_config(Path("configs/cobertura_levite.json")).reportes[0].capture_images
    assert [c.hoja for c in cap] == ["Aguas", "Cervezas"]


def test_el_config_no_escribe_el_rango_a_mano():
    """El alto de la hoja depende de los calibres que se vendieron: un rango
    fijo recorta filas unos meses y deja franjas vacias otros."""
    from pathlib import Path

    from src.config.resolver import load_report_config

    cap = load_report_config(Path("configs/cobertura_levite.json")).reportes[0].capture_images
    assert all(c.rango == "auto:hoja" for c in cap)


def test_el_config_solo_toma_casa_central():
    from pathlib import Path

    from src.config.resolver import load_report_config

    assert load_report_config(Path("configs/cobertura_levite.json")).filtros.sucursales_ids == [1]


def test_la_ventana_es_relativa():
    """Sin esto el informe diario sale con el mes escrito en el JSON."""
    from pathlib import Path

    from src.config.resolver import load_report_config

    assert load_report_config(Path("configs/cobertura_levite.json")).filtros.fecha_modo == "mes_a_hoy"


def test_esta_registrado_en_el_daily():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("rd_lev", "scripts/run_daily.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rd_lev"] = mod
    spec.loader.exec_module(mod)
    srv = {s.nombre: s for s in mod.SERVICIOS}
    assert "cobertura-levite" in srv
    assert srv["cobertura-levite"].fecha_modo == "mes_a_hoy"


# --- calibre en cervezas ----------------------------------------------------


def test_extraer_calibre_acepta_la_x_como_multiplicador():
    """`HEINEKEN 330 X 24 VNR` usa X, no *. Sin esto el articulo cae en OTRO
    y sus clientes desaparecen de la fila de 330cc."""
    assert extraer_calibre("HEINEKEN  330 X 24 VNR") == "330cc"
    assert extraer_calibre("SALTA RUBIA 1200 X 10") == "1200cc"


def test_extraer_calibre_de_cervezas():
    assert extraer_calibre("IMPERIAL GOLDEN 473*24 LATA") == "473cc"
    assert extraer_calibre("IMPERIAL RUB 710*24 1412") == "710cc"
    assert extraer_calibre("SALTA RUBIA 1200 * 10") == "1200cc"
    assert extraer_calibre("MILLER RUB 600 * 12") == "600cc"
    assert extraer_calibre("SALTA NEGRA 1000 * 12 VR") == "1000cc"


def test_el_barril_no_tiene_calibre():
    """30 litros es un barril de chopp: no es un envase de la grilla."""
    assert extraer_calibre("IMPERIAL RUB * 30 LITROS") == "OTRO"


# --- cuadro generalizado ----------------------------------------------------

from src.services.cobertura_levite.processor import CUADROS

CERVEZAS = (("PRINCIPALES", ("SALTA", "HEINEKEN", "IMPERIAL", "MILLER")),)


def test_el_barril_cuenta_en_el_total_aunque_no_tenga_fila_de_calibre():
    """Quien solo compro chopp esta cubierto en CERVEZAS. Descartarlo antes de
    totalizar lo borraria del total, que es una cobertura del generico."""
    v = _v([
        (1, "S", 7, "IMPERIAL", "473cc", 5.0),
        (1, "S", 9, "IMPERIAL", "OTRO", 5.0),
    ])
    df, _ = matriz_calibre_marca(
        v, CERVEZAS, total_label="TOTAL CERVEZAS", con_subtotales=False
    )
    assert list(df["calibre"]) == ["473cc", "TOTAL"], "OTRO no es una fila"
    assert df[df["calibre"] == "TOTAL"].iloc[0]["TOTAL CERVEZAS"] == 2


def test_sin_subtotales_no_aparece_la_columna_de_categoria():
    """En cervezas se piden las 4 marcas y el total del generico, nada mas."""
    v = _v([(1, "S", 7, "SALTA", "473cc", 5.0)])
    df, bloques = matriz_calibre_marca(
        v, CERVEZAS, total_label="TOTAL CERVEZAS", con_subtotales=False
    )
    assert "TOTAL PRINCIPALES" not in df.columns
    assert "TOTAL CERVEZAS" in df.columns


def test_el_total_del_generico_incluye_marcas_que_no_son_columna():
    """SCHNEIDER no es una de las principales pero es CERVEZAS: suma al total."""
    v = _v([
        (1, "S", 7, "SALTA", "473cc", 5.0),
        (1, "S", 9, "SCHNEIDER", "473cc", 5.0),
    ])
    df, _ = matriz_calibre_marca(
        v, CERVEZAS, total_label="TOTAL CERVEZAS", con_subtotales=False
    )
    fila = df[df["calibre"] == "473cc"].iloc[0]
    assert fila["SALTA"] == 1
    assert "SCHNEIDER" not in df.columns
    assert fila["TOTAL CERVEZAS"] == 2


def test_los_bloques_fijos_fuerzan_la_columna_aunque_no_haya_ventas():
    """Los tres cuadros de una hoja comparan periodos: si una marca vendio en
    julio y no en agosto, la columna tiene que seguir estando o los cuadros
    dejan de estar alineados."""
    v = _v([(1, "S", 7, "LEVITE", "500cc", 5.0)])
    fijos = [("AGUA SABORIZADA", ["LEVITE", "BRIO"])]
    df, bloques = matriz_calibre_marca(v, bloques=fijos)
    assert bloques == fijos
    assert df[df["calibre"] == "500cc"].iloc[0]["BRIO"] == 0


def test_los_calibres_fijos_fuerzan_la_fila_aunque_no_haya_ventas():
    v = _v([(1, "S", 7, "LEVITE", "500cc", 5.0)])
    df, _ = matriz_calibre_marca(v, calibres=["500cc", "1500cc"])
    assert list(df["calibre"]) == ["500cc", "1500cc", "TOTAL"]
    assert df[df["calibre"] == "1500cc"].iloc[0]["LEVITE"] == 0


def test_hay_un_cuadro_para_aguas_y_otro_para_cervezas():
    por_generico = {c.generico: c for c in CUADROS}
    assert set(por_generico) == {"AGUAS DANONE", "CERVEZAS"}
    assert por_generico["AGUAS DANONE"].total_label == "TOTAL AGUAS"

    cerv = por_generico["CERVEZAS"]
    assert cerv.total_label == "TOTAL CERVEZAS"
    assert cerv.con_subtotales is False
    assert [m for _, ms in cerv.categorias for m in ms] == [
        "SALTA", "HEINEKEN", "IMPERIAL", "MILLER",
    ]
    assert cerv.marcas_total is None, "el total abarca TODAS las marcas del generico"


def test_el_total_de_aguas_se_queda_en_las_cinco_marcas_del_generico():
    """SER esta en el generico pero fuera del universo comercial del informe."""
    aguas = {c.generico: c for c in CUADROS}["AGUAS DANONE"]
    assert set(aguas.marcas_total) == {
        "VILLA DEL SUR", "VILLAVICENCIO", "LEVITE", "BRIO", "FULL SPORT",
    }


def test_las_filas_siguen_a_las_columnas():
    """Un calibre que solo vendio una marca SIN columna no genera fila: la
    fila saldria toda en cero salvo el total. KUNSTMAN 470cc es CERVEZAS pero
    no es una de las cuatro principales."""
    from src.services.cobertura_levite.service import CoberturaLeviteService

    df = pd.DataFrame(
        [
            (1, "S", 7, "CERVEZAS", "SALTA", "473cc", 5.0),
            (1, "S", 9, "CERVEZAS", "KUNSTMAN", "470cc", 5.0),
        ],
        columns=["id_sucursal", "sucursal", "id_cliente", "generico", "marca", "calibre", "bultos"],
    )
    cuadro = {c.generico: c for c in CUADROS}["CERVEZAS"]
    bloques, calibres = CoberturaLeviteService._ejes([("X", df)], cuadro)

    assert calibres == ["473cc"], "470cc no tiene ninguna columna que mostrar"
    # El total del generico sigue contando a KUNSTMAN.
    cuadro_df, _ = matriz_calibre_marca(
        df, cuadro.categorias, total_label=cuadro.total_label,
        con_subtotales=False, bloques=bloques, calibres=calibres,
    )
    assert cuadro_df[cuadro_df["calibre"] == "TOTAL"].iloc[0]["TOTAL CERVEZAS"] == 2
