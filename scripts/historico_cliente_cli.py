#!/usr/bin/env python
"""Generate the historico-cliente report from one command.

Exists so a caller — an agent, a cron job, a person in a hurry — can ask for
this report without hand-writing a JSON config. Every setting that is wrong
*silently* when composed by hand is decided here instead:

  - the CCU marca universe (get it wrong and the coverage gaps vanish),
  - the composite client key (id_cliente alone is not unique across sucursales),
  - the capture range (a stale hardcoded range crops the TOTAL GENERAL row out
    of the PNG while the xlsx stays correct and nothing raises).

Prints a JSON object on stdout so the caller can parse the result:

    {"ok": true, "cliente": "...", "id_cliente": 7255, "id_sucursal": 1,
     "xlsx": "/abs/path.xlsx", "png": "/abs/path.png",
     "rango": "A1:P47", "total_general": 75.41666667,
     "desde": "2025-09-01", "hasta": "2026-08-11", "solo_con_cargo": true}

On failure it prints {"ok": false, "error": "..."} and exits non-zero.

Usage:
    python scripts/historico_cliente_cli.py --cliente 7255 [--sucursal 1]
        [--meses 12] [--solo-con-cargo] [--sin-imagen]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.historico_cliente.service import (  # noqa: E402
    HistoricoClienteConfig,
    columnas_desbordadas,
    rango_captura,
)

# The four CCU genericos whose full marca set defines the coverage universe.
# Marcas the client never bought show as 0, which is the point of the report.
GENERICOS_UNIVERSO = ["CERVEZAS", "AGUAS DANONE", "VINOS CCU", "SIDRAS Y LICORES"]

_DPI = 300


class ClienteNoEncontrado(Exception):
    """No row in gold.dim_cliente for that id."""


class ClienteAmbiguo(Exception):
    """The id exists in more than one sucursal; the caller must pick one."""


class CapturaInvalida(Exception):
    """The sheet would render with ### in at least one column."""


# ── Ventana ──────────────────────────────────────────────────────────────────

def ventana(meses: int, hoy: date | None = None) -> tuple[str, str]:
    """Return (desde, hasta) covering the last ``meses`` months, inclusive.

    ``hasta`` is today, so the current month is included and partial. The
    subtitle of the sheet prints the exact range, so a partial last month is
    visible to whoever reads the image.
    """
    hoy = hoy or date.today()
    total = (hoy.year * 12 + hoy.month - 1) - (meses - 1)
    anio, mes = divmod(total, 12)
    return f"{anio:04d}-{mes + 1:02d}-01", hoy.isoformat()


# ── Cliente ──────────────────────────────────────────────────────────────────

def resolver_cliente(
    loader, id_cliente: int, id_sucursal: int | None = None
) -> tuple[int, int, str]:
    """Resolve (id_cliente, id_sucursal, nombre) against gold.dim_cliente.

    ``id_cliente`` is NOT unique — the same code is reused across sucursales.
    With several matches and no ``id_sucursal`` this raises instead of picking
    one, because guessing silently reports another branch's client.

    ``fantasia`` may be an empty string rather than NULL, so plain COALESCE is
    not enough to fall back to razon_social.
    """
    filas = loader.execute_query(
        """
        SELECT id_cliente, id_sucursal,
               COALESCE(
                   NULLIF(TRIM(fantasia), ''),
                   NULLIF(TRIM(razon_social), ''),
                   CAST(id_cliente AS TEXT)
               ) AS nombre
        FROM gold.dim_cliente
        WHERE id_cliente = :id_cliente
        ORDER BY id_sucursal
        """,
        {"id_cliente": id_cliente},
    )
    if filas is None or filas.empty:
        raise ClienteNoEncontrado(f"No existe el cliente {id_cliente} en dim_cliente.")

    if id_sucursal is not None:
        filas = filas[filas["id_sucursal"] == id_sucursal]
        if filas.empty:
            raise ClienteNoEncontrado(
                f"El cliente {id_cliente} no existe en la sucursal {id_sucursal}."
            )

    if len(filas) > 1:
        opciones = ", ".join(
            f"{int(r.id_sucursal)} ({r.nombre})" for r in filas.itertuples()
        )
        raise ClienteAmbiguo(
            f"El cliente {id_cliente} existe en varias sucursales: {opciones}. "
            f"Volvé a pedirlo con --sucursal."
        )

    fila = filas.iloc[0]
    return int(fila["id_cliente"]), int(fila["id_sucursal"]), str(fila["nombre"])


# ── Config ───────────────────────────────────────────────────────────────────

def construir_config(
    *, id_cliente: int, id_sucursal: int, desde: str, hasta: str,
    solo_con_cargo: bool, nombre: str,
) -> HistoricoClienteConfig:
    """Build the config with the settings this report only works with."""
    return HistoricoClienteConfig(
        fecha_desde=desde,
        fecha_hasta=hasta,
        clientes=[{"id_cliente": id_cliente, "id_sucursal": id_sucursal}],
        agrupar_por_generico=True,
        marcas_completas=True,
        genericos_universo=list(GENERICOS_UNIVERSO),
        solo_con_cargo=solo_con_cargo,
        nombre_archivo=nombre,
    )


# ── Captura ──────────────────────────────────────────────────────────────────

def rango_de(ws) -> str:
    """Capture range for ``ws``, always derived from the sheet."""
    return rango_captura(ws)


def validar_captura(ws) -> None:
    """Abort if any column would render as ### instead of its number."""
    fuera = columnas_desbordadas(ws)
    if fuera:
        raise CapturaInvalida(
            "Estas columnas no entran y LibreOffice las renderiza como ###: "
            + ", ".join(fuera)
        )


# ── Orquestación ─────────────────────────────────────────────────────────────

def _total_general(ws) -> float | None:
    """Value of the Total column on the TOTAL GENERAL row, if present."""
    for r in range(ws.max_row, 1, -1):
        if ws.cell(row=r, column=2).value == "TOTAL GENERAL":
            return ws.cell(row=r, column=ws.max_column).value
    return None


def generar(
    *, id_cliente: int, id_sucursal: int | None, meses: int,
    solo_con_cargo: bool, con_imagen: bool, hoy: date | None = None,
) -> dict:
    """Resolve, generate, validate and (optionally) render. Returns the result dict."""
    from openpyxl import load_workbook

    from src.core.data_loader import DataLoader
    from src.services.historico_cliente.service import HistoricoClienteService

    loader = DataLoader()
    id_cliente, id_sucursal, nombre = resolver_cliente(loader, id_cliente, id_sucursal)

    desde, hasta = ventana(meses, hoy=hoy)
    sufijo = " (con cargo)" if solo_con_cargo else ""
    config = construir_config(
        id_cliente=id_cliente, id_sucursal=id_sucursal, desde=desde, hasta=hasta,
        solo_con_cargo=solo_con_cargo,
        nombre=f"Historico Ventas - {nombre} {id_cliente}{sufijo}",
    )

    resultado = HistoricoClienteService(data_loader=loader).generar_reporte(config)
    if not resultado.sheets_generated:
        raise ClienteNoEncontrado(
            f"{nombre} ({id_cliente}) no tiene ventas entre {desde} y {hasta}."
        )

    ws = load_workbook(resultado.ruta_archivo)[resultado.sheets_generated[0]]
    validar_captura(ws)
    rango = rango_de(ws)

    png = None
    if con_imagen:
        from src.core.excel_renderers import get_renderer

        png = get_renderer("libreoffice").render(
            resultado.ruta_archivo, ws.title, rango,
            resultado.ruta_archivo.parent, dpi=_DPI, crop=True,
        )

    return {
        "ok": True,
        "cliente": nombre,
        "id_cliente": id_cliente,
        "id_sucursal": id_sucursal,
        "xlsx": str(resultado.ruta_archivo),
        "png": str(png) if png else None,
        "hoja": ws.title,
        "rango": rango,
        "total_general": _total_general(ws),
        "desde": desde,
        "hasta": hasta,
        "solo_con_cargo": solo_con_cargo,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Genera el histórico de compras por marca de un cliente."
    )
    parser.add_argument("--cliente", type=int, required=True, help="id_cliente")
    parser.add_argument(
        "--sucursal", type=int, default=None,
        help="id_sucursal. Obligatorio si el código existe en más de una.",
    )
    parser.add_argument("--meses", type=int, default=12, help="Meses hacia atrás (default 12)")
    parser.add_argument(
        "--solo-con-cargo", action="store_true",
        help="Contar solo unidades facturadas; excluye bonificación 100%%.",
    )
    parser.add_argument(
        "--sin-imagen", action="store_true",
        help="No renderizar el PNG (más rápido; el render tarda 30-60s).",
    )
    args = parser.parse_args(argv)

    try:
        salida = generar(
            id_cliente=args.cliente,
            id_sucursal=args.sucursal,
            meses=args.meses,
            solo_con_cargo=args.solo_con_cargo,
            con_imagen=not args.sin_imagen,
        )
    except (ClienteNoEncontrado, ClienteAmbiguo, CapturaInvalida) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1

    print(json.dumps(salida, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
