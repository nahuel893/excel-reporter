#!/usr/bin/env python3
"""Build the single monthly deck: BADIE + BRANCA + RECHAZOS + VINOS DANIELITO.

Until now the month went out as two PowerPoints and two loose PNGs, which meant
opening four things in the same meeting. This joins them into one file, in the
order the meeting runs:

1. AVANCE BADIE      - cover, volume by supervisor, coverage by brand.
2. AVANCE BRANCA     - cover, volume and coverage of the Fratelli Branca lines.
3. RECHAZOS          - the month's rebotes image, for the whole company.
4. VINOS DANIELITO   - the ad-hoc monthly volume/coverage table, as an image.

Nothing is recalculated here. The two avance sections are built by the very
same code that builds each deck on its own (`avance_pptx.poblar` and
`avance_branca_pptx.poblar`), so a number on a slide of this deck is the same
number the separate deck shows. The last two sections are images already
produced by their own reports.

Why RECHAZOS sits at deck level and not inside BRANCA
-----------------------------------------------------
The BRANCA deck ends with its RECHAZOS slide, but the rebotes report covers
EVERY preventista of BADIE - CERVEZAS, AGUAS, VINOS and SIDRAS - not the
Fratelli Branca lines. Leaving it inside that section would file a company-wide
number under one supplier, and would print it twice as soon as this deck adds
its own. So `avance_branca_pptx.poblar` is called with `con_rechazos=False`.

What is found on its own
------------------------
Only the BADIE workbook is required. The BRANCA workbook is looked up next to
it by name, and the two images by their period folder - never by file name:
`configs/rebotes.json` carries a hand-written `nombre`, so every month's PNG is
called "Rebotes Junio 2026", and the Danielito PNG carries the captured range,
which moves with the number of rows. The folder is the only reliable key.

A missing piece drops its slide and says so; it never sinks the deck.

Usage
-----
    python scripts/avance_deck.py \
        --archivo "data/output/avances/2026-07/AVANCE BADIE - JULIO 2026.xlsx"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import openpyxl

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/
sys.path.insert(0, str(RAIZ))

import avance_pptx as badie  # noqa: E402
import avance_branca_pptx as branca  # noqa: E402


NOMBRE_SALIDA = "AVANCE MENSUAL - {periodo}.pptx"

TITULO_RECHAZOS = "RECHAZOS"
SUBTITULO_RECHAZOS = "{periodo}   ·   % de bultos rechazados por preventista"
TITULO_DANIELITO = "VINOS DANIELITO"
SUBTITULO_DANIELITO = "{periodo}   ·   bultos y clientes únicos por mes, dos años enfrentados"


def _periodo(archivo: Path) -> str:
    """El periodo tal como lo declara el libro de BADIE, no el nombre del archivo."""
    libro = openpyxl.load_workbook(archivo, data_only=True, read_only=True)
    try:
        return badie._periodo(libro["Avance"])
    finally:
        libro.close()


def _buscar_branca(archivo: Path) -> Path | None:
    """El libro de BRANCA del mismo mes, al lado del de BADIE.

    Los dos los deja `AvancesService` en la misma carpeta de periodo y solo se
    diferencian por la palabra del medio, asi que alcanza con cambiarla.
    """
    candidato = archivo.with_name(archivo.name.replace("BADIE", "BRANCA"))
    if candidato == archivo or not candidato.is_file():
        return None
    return candidato


def _buscar_danielito(periodo_iso: str) -> Path | None:
    """El PNG del informe de Danielito del mes, ubicado por CARPETA.

    El nombre lleva el rango capturado (`_A1_O28`), que se mueve con la
    cantidad de filas del mes; la carpeta la deriva `service_output_dir` de la
    fecha y esa si es estable. Los `backup-*` quedan afuera: son de una corrida
    vieja del mismo mes y su fecha de archivo puede ser mas nueva que la del
    PNG vigente, asi que elegir por mtime sin filtrarlos toma el equivocado.
    """
    carpeta = RAIZ / "data" / "output" / "vinos-danielito" / periodo_iso
    if not carpeta.is_dir():
        return None
    pngs = sorted((png for png in carpeta.glob("*.png") if "backup-" not in png.name),
                  key=lambda p: p.stat().st_mtime)
    return pngs[-1] if pngs else None


def _imagen(prs, titulo: str, subtitulo: str, imagen: Path | None) -> bool:
    if imagen is None or not imagen.is_file():
        print(f"AVISO: sin imagen para {titulo}, el deck sale sin esa diapositiva.")
        return False
    badie._slide_imagen(prs, titulo, subtitulo, imagen)
    return True


def construir(archivo: Path, salida: Path, archivo_branca: Path | None = None,
              rechazos: Path | None = None, danielito: Path | None = None,
              diagnostico: bool = False, con_capturas: bool = True) -> int:
    prs = badie.nuevo_deck()
    periodo = _periodo(archivo)

    badie.poblar(prs, archivo, diagnostico=diagnostico)

    if archivo_branca:
        branca.poblar(prs, archivo_branca, diagnostico=diagnostico,
                      con_capturas=con_capturas, con_rechazos=False)

    _imagen(prs, TITULO_RECHAZOS, SUBTITULO_RECHAZOS.format(periodo=periodo), rechazos)
    _imagen(prs, TITULO_DANIELITO, SUBTITULO_DANIELITO.format(periodo=periodo), danielito)

    salida.parent.mkdir(parents=True, exist_ok=True)
    prs.save(salida)
    return len(prs.slides._sldIdLst)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PowerPoint mensual unico: BADIE + BRANCA + rechazos + Danielito")
    parser.add_argument("--archivo", required=True,
                        help="xlsx del avance de BADIE (se lee, nunca se escribe)")
    parser.add_argument("--branca", help="xlsx del avance de BRANCA; por defecto, el del mismo mes")
    parser.add_argument("--sin-branca", action="store_true",
                        help="no agregar la seccion de Fratelli Branca")
    parser.add_argument("--rechazos", help="PNG de rebotes; por defecto se busca por periodo")
    parser.add_argument("--danielito", help="PNG de Vinos Danielito; por defecto, por periodo")
    parser.add_argument("--salida", help="ruta del pptx (por defecto, junto al xlsx de BADIE)")
    parser.add_argument("--force", action="store_true", help="sobrescribir el pptx si ya existe")
    parser.add_argument("--diagnostico", action="store_true",
                        help="listar las filas de total de los libros que no cierran")
    parser.add_argument("--sin-capturas", action="store_true",
                        help="no agregar las diapositivas con la imagen de las hojas de BRANCA")
    args = parser.parse_args()

    archivo = Path(args.archivo)
    if not archivo.is_file():
        print(f"ERROR: no existe {archivo}", file=sys.stderr)
        return 1

    periodo_iso = archivo.parent.name

    if args.sin_branca:
        archivo_branca = None
    elif args.branca:
        archivo_branca = Path(args.branca)
        if not archivo_branca.is_file():
            print(f"ERROR: no existe {archivo_branca}", file=sys.stderr)
            return 1
    else:
        archivo_branca = _buscar_branca(archivo)
        if archivo_branca is None:
            print("AVISO: no se encontro el libro de BRANCA del mes; el deck sale sin esa seccion.")

    rechazos = Path(args.rechazos) if args.rechazos else branca._buscar_rechazos(periodo_iso)
    danielito = Path(args.danielito) if args.danielito else _buscar_danielito(periodo_iso)

    salida = (Path(args.salida) if args.salida
              else archivo.parent / NOMBRE_SALIDA.format(periodo=_periodo(archivo)))
    if salida.exists() and not args.force:
        print(f"ERROR: {salida} ya existe. Usar --force para sobrescribir.", file=sys.stderr)
        return 1

    for etiqueta, ruta in [("BRANCA", archivo_branca), ("Rechazos", rechazos),
                           ("Danielito", danielito)]:
        if ruta:
            print(f"{etiqueta}: {ruta.name}")

    slides = construir(archivo, salida, archivo_branca, rechazos, danielito,
                       diagnostico=args.diagnostico, con_capturas=not args.sin_capturas)
    print(f"OK: {slides} slides -> {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
