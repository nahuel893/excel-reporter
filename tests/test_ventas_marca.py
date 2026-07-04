"""Tests for the ventas-marca report (quantity sold by marca for one generico).

Rows = marcas of the generico, value = quantity sold (bultos) over a date range,
with a mandatory TOTAL GENERAL row.
"""
from unittest.mock import MagicMock, patch

import pandas as pd
from openpyxl import load_workbook

from src.core.data_loader import DataLoader
from src.services.ventas_marca import VentasMarcaConfig, VentasMarcaService


# ── Loader query ─────────────────────────────────────────────────────────────

def test_loader_query_sums_by_marca_for_generico_and_dates():
    loader = DataLoader()
    cap: dict = {}

    def fake(q, params=None):
        cap["q"] = q
        cap["p"] = params
        return pd.DataFrame(columns=["marca", "bultos"])

    loader.execute_query = MagicMock(side_effect=fake)
    loader.get_ventas_por_marca(
        generico="PERNOD RICARD", fecha_desde="2026-07-03", fecha_hasta="2026-07-03",
        id_sucursal=1,
    )
    q = cap["q"].lower()
    assert "gold.fact_ventas" in q
    assert "sum(f.cantidades_total)" in q
    assert "da.marca" in q or "a.marca" in q
    assert "fecha_comprobante::date between" in q
    assert cap["p"]["generico"] == "PERNOD RICARD"
    assert cap["p"]["fecha_desde"] == "2026-07-03"
    assert cap["p"]["fecha_hasta"] == "2026-07-03"
    assert cap["p"]["id_sucursal"] == 1


# ── Service ──────────────────────────────────────────────────────────────────

def _loader_with_marcas():
    loader = MagicMock(spec=DataLoader)
    loader.get_ventas_por_marca.return_value = pd.DataFrame({
        "marca": ["CUSENIER", "ABSOLUT", None],
        "bultos": [27.04, 18.17, 1.5],
    })
    return loader


def test_builds_marca_rows_and_total(tmp_path):
    loader = _loader_with_marcas()
    service = VentasMarcaService(data_loader=loader)
    config = VentasMarcaConfig(generico="PERNOD RICARD", fecha="2026-07-03")

    with patch("src.services.ventas_marca.service.service_output_dir", return_value=tmp_path):
        result = service.generar_reporte(config)

    ws = load_workbook(result.ruta_archivo).active
    texts = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
    assert "CUSENIER" in texts
    assert "ABSOLUT" in texts
    assert "TOTAL GENERAL" in texts          # totals-row convention
    assert "(sin marca)" in texts            # NULL marca handled

    nums = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, (int, float))]
    assert any(abs(n - 46.71) < 1e-6 for n in nums)  # 27.04 + 18.17 + 1.5 total, NOT rounded


def test_single_day_uses_same_desde_hasta(tmp_path):
    loader = _loader_with_marcas()
    service = VentasMarcaService(data_loader=loader)
    config = VentasMarcaConfig(generico="PERNOD RICARD", fecha="2026-07-03")

    with patch("src.services.ventas_marca.service.service_output_dir", return_value=tmp_path):
        service.generar_reporte(config)

    _, kwargs = loader.get_ventas_por_marca.call_args
    assert kwargs["fecha_desde"] == "2026-07-03"
    assert kwargs["fecha_hasta"] == "2026-07-03"
    assert kwargs["generico"] == "PERNOD RICARD"
