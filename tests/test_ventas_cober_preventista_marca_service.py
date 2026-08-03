"""Tests for VentasCoberPreventistaMarcaService."""
import pandas as pd
from unittest.mock import MagicMock, patch

from openpyxl import load_workbook

from src.core.data_loader import DataLoader
from src.services.ventas_cober_preventista_marca import (
    VentasCoberPreventistaMarcaConfig,
    VentasCoberPreventistaMarcaService,
)


def _raw():
    """Client 1 bought from FGUANTAY (LORENA) AND VCHAPUR (NAHUEL) → distinct-count test."""
    return pd.DataFrame({
        "vendedor": ["LORENA TARITOLAY", "LORENA TARITOLAY", "NAHUEL RUEDA", "DIRECTA"],
        "id_cliente": [1, 2, 1, 3],
        "bultos": [10.0, 5.0, 8.0, 3.0],
    })


def _sheet_rows(ruta):
    ws = load_workbook(ruta).active
    return [[ws.cell(r, c).value for c in range(1, 5)] for r in range(1, ws.max_row + 1)]


def _make(tmp_path, raw):
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_cobertura_por_vendedor.return_value = raw
    service = VentasCoberPreventistaMarcaService(data_loader=loader)
    config = VentasCoberPreventistaMarcaConfig(
        marca="FULL SPORT", fecha_desde="2026-07-01", fecha_hasta="2026-07-31", id_sucursal=1,
    )
    with patch("src.services.ventas_cober_preventista_marca.service.service_output_dir",
               return_value=tmp_path):
        return service.generar_reporte(config), loader


def test_composite_key_query_args(tmp_path):
    result, loader = _make(tmp_path, _raw())
    _, kwargs = loader.get_ventas_cobertura_por_vendedor.call_args
    assert kwargs["marca"] == "FULL SPORT"
    assert kwargs["id_sucursal"] == 1
    assert result.ruta_archivo.exists()


def test_supervisor_mapping_and_totals(tmp_path):
    result, _ = _make(tmp_path, _raw())
    rows = _sheet_rows(result.ruta_archivo)
    # supervisor of each vendedor row
    vend = {r[0]: r[1] for r in rows if r[0] in ("LORENA TARITOLAY", "NAHUEL RUEDA", "DIRECTA")}
    assert vend["LORENA TARITOLAY"] == "FGUANTAY"
    assert vend["NAHUEL RUEDA"] == "VCHAPUR"
    assert vend["DIRECTA"] == "SIN SUPERVISOR"
    # per-preventista total bultos
    assert result.total_bultos == 26.0


def test_cobertura_is_not_additive(tmp_path):
    """Sum of supervisor coberturas (2+1+1=4) exceeds the true total (3 distinct clients)."""
    result, _ = _make(tmp_path, _raw())
    assert result.cobertura_total == 3  # clients {1,2,3}, client 1 shared across supervisors
    rows = _sheet_rows(result.ruta_archivo)
    # supervisor-section cobertura (col 4) for FGUANTAY should be 2 (clients 1,2)
    sup_cob = {r[0]: r[3] for r in rows if r[0] in ("FGUANTAY", "VCHAPUR", "SIN SUPERVISOR")}
    assert sup_cob["FGUANTAY"] == 2
    assert sup_cob["VCHAPUR"] == 1


def test_has_two_total_general_rows(tmp_path):
    result, _ = _make(tmp_path, _raw())
    rows = _sheet_rows(result.ruta_archivo)
    totals = [r for r in rows if r[0] == "TOTAL GENERAL"]
    assert len(totals) == 2  # one per section (convención: fila de totales)


def test_empty_raw_does_not_crash(tmp_path):
    result, _ = _make(tmp_path, pd.DataFrame(columns=["vendedor", "id_cliente", "bultos"]))
    assert result.ruta_archivo.exists()
    assert result.total_bultos == 0.0
    assert result.cobertura_total == 0


# ── Dos periodos (mes anterior + mes corriente) ──────────────────────────────

def _raw_julio():
    """Julio: clientes 1 y 2 a LORENA, cliente 1 tambien a NAHUEL, 3 a DIRECTA."""
    return pd.DataFrame({
        "vendedor": ["LORENA TARITOLAY", "LORENA TARITOLAY", "NAHUEL RUEDA", "DIRECTA"],
        "id_cliente": [1, 2, 1, 3],
        "bultos": [10.0, 5.0, 8.0, 3.0],
    })


def _raw_agosto():
    """Agosto: solo LORENA vendio, al mismo cliente 1. NAHUEL y DIRECTA no aparecen."""
    return pd.DataFrame({
        "vendedor": ["LORENA TARITOLAY"],
        "id_cliente": [1],
        "bultos": [4.0],
    })


def _make_dos_periodos(tmp_path):
    loader = MagicMock(spec=DataLoader)

    def por_periodo(*, marca, fecha_desde, fecha_hasta, id_sucursal):
        return _raw_agosto() if fecha_desde.startswith("2026-08") else _raw_julio()

    loader.get_ventas_cobertura_por_vendedor.side_effect = por_periodo
    service = VentasCoberPreventistaMarcaService(data_loader=loader)
    config = VentasCoberPreventistaMarcaConfig(
        marca="FULL SPORT",
        fecha_desde="2026-08-01",
        fecha_hasta="2026-08-03",
        id_sucursal=1,
        incluir_mes_anterior=True,
    )
    with patch("src.services.ventas_cober_preventista_marca.service.service_output_dir",
               return_value=tmp_path):
        return service.generar_reporte(config), loader


def _grid(ruta, ancho=6):
    ws = load_workbook(ruta).active
    return [[ws.cell(r, c).value for c in range(1, ancho + 1)] for r in range(1, ws.max_row + 1)]


def test_dos_periodos_deriva_la_ventana_anterior(tmp_path):
    """The July window is DERIVED from fecha_desde, never read from the config."""
    _, loader = _make_dos_periodos(tmp_path)
    ventanas = {
        (c.kwargs["fecha_desde"], c.kwargs["fecha_hasta"])
        for c in loader.get_ventas_cobertura_por_vendedor.call_args_list
    }
    assert ventanas == {("2026-07-01", "2026-07-31"), ("2026-08-01", "2026-08-03")}


def test_dos_periodos_encabezado_de_dos_niveles(tmp_path):
    result, _ = _make_dos_periodos(tmp_path)
    ws = load_workbook(result.ruta_archivo).active
    # fila 5: grupo de mes (anterior primero); fila 6: medidas
    assert ws.cell(5, 3).value == "JULIO 2026"
    assert ws.cell(5, 5).value == "AGOSTO 2026"
    assert [ws.cell(6, c).value for c in range(1, 7)] == [
        "Vendedor", "Supervisor", "Bultos", "Cobertura", "Bultos", "Cobertura",
    ]


def test_dos_periodos_vendedor_sin_venta_en_agosto_queda_en_cero(tmp_path):
    result, _ = _make_dos_periodos(tmp_path)
    filas = {r[0]: r for r in _grid(result.ruta_archivo) if r[0] == "NAHUEL RUEDA"}
    assert filas["NAHUEL RUEDA"][2:6] == [8.0, 1, 0.0, 0]


def test_dos_periodos_cobertura_no_se_suma_entre_meses(tmp_path):
    """Cliente 1 compro en julio Y en agosto: cuenta 1 en cada mes, nunca 2."""
    result, _ = _make_dos_periodos(tmp_path)
    grid = _grid(result.ruta_archivo)
    lorena = next(r for r in grid if r[0] == "LORENA TARITOLAY")
    assert lorena[2:6] == [15.0, 2, 4.0, 1]   # jul: 2 clientes | ago: 1 cliente

    totales = [r for r in grid if r[0] == "TOTAL GENERAL"]
    # Julio: clientes distintos {1,2,3} = 3 (NO 2+1+1=4, que seria sumar niveles)
    assert totales[0][3] == 3
    # Agosto: solo cliente 1
    assert totales[0][5] == 1


def test_dos_periodos_totales_de_bultos_por_columna(tmp_path):
    result, _ = _make_dos_periodos(tmp_path)
    total_prev = next(r for r in _grid(result.ruta_archivo) if r[0] == "TOTAL GENERAL")
    assert total_prev[2] == 26.0   # 10 + 5 + 8 + 3 en julio
    assert total_prev[4] == 4.0    # solo LORENA en agosto


def test_un_solo_periodo_mantiene_el_layout_original(tmp_path):
    """Regression: sin el flag, el encabezado sigue en la fila 5 con 4 columnas."""
    result, loader = _make(tmp_path, _raw())
    ws = load_workbook(result.ruta_archivo).active
    assert [ws.cell(5, c).value for c in range(1, 5)] == [
        "Vendedor", "Supervisor", "Bultos", "Cobertura",
    ]
    assert loader.get_ventas_cobertura_por_vendedor.call_count == 1
