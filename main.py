"""
CLI para generacion de reportes CCU.

Uso basico (args individuales):
    python main.py ventas --desde 2026-01-01 --hasta 2026-01-31
    python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --genericos "CERVEZAS,AGUAS"

Uso con archivo de configuracion (recomendado):
    python main.py ventas --config config.json

Formato del JSON de configuracion:
    {
        "fecha_desde": "2026-01-01",
        "fecha_hasta": "2026-01-31",
        "genericos": ["CERVEZAS", "AGUAS"],
        "output": "mi_reporte",
        "con_slicers": true,
        "con_cobertura": true,
        "supervisores": {
            "Juan Perez": ["Sucursal Norte", "Sucursal Sur"],
            "Maria Garcia": ["Sucursal Este"]
        }
    }

Subcomandos disponibles:
    ventas           - Reporte de ventas por sucursal, generico y marca
    resumen-mensual  - Resumen mensual por generico (ultimos dias, tendencia, anio anterior)
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.services import VentasService, ResumenMensualService, ResumenMensualConfig
from src.services import MisionPosibleService, MisionPosibleConfig, GrupoArticulos
from src.services.ventas import ReporteVentasConfig


def validar_fecha(fecha_str: str) -> bool:
    """Valida que la fecha tenga formato YYYY-MM-DD."""
    try:
        datetime.strptime(fecha_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def parsear_genericos(genericos_str: str | None) -> list[str] | None:
    """Parsea string de genericos separados por coma."""
    if not genericos_str:
        return None
    return [g.strip() for g in genericos_str.split(",")]


def _cargar_config_json(ruta: str) -> dict:
    """Lee y parsea el archivo JSON de configuracion."""
    path = Path(ruta)
    if not path.exists():
        print(f"Error: archivo de configuracion no encontrado: {path}")
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_ventas(args) -> int:
    """Ejecuta el comando de reporte de ventas."""

    # Cargar configuracion desde JSON si se provee --config
    cfg = _cargar_config_json(args.config) if args.config else {}

    # Resolver parametros: JSON tiene precedencia sobre args individuales
    fecha_desde = cfg.get("fecha_desde") or args.desde
    fecha_hasta = cfg.get("fecha_hasta") or args.hasta
    genericos = cfg.get("genericos") or parsear_genericos(args.genericos)
    nombre_archivo = cfg.get("output") or args.output
    con_slicers = cfg.get("con_slicers", args.slicers)
    con_cobertura = cfg.get("con_cobertura", True)
    supervisores = cfg.get("supervisores")  # Solo disponible via JSON

    # Validar campos requeridos
    if not fecha_desde or not fecha_hasta:
        print("Error: fecha_desde y fecha_hasta son requeridos.")
        print("       Usa --desde/--hasta o definelos en --config config.json")
        return 1

    if not validar_fecha(fecha_desde) or not validar_fecha(fecha_hasta):
        print("Error: Las fechas deben tener formato YYYY-MM-DD")
        return 1

    # Crear configuracion del servicio
    config = ReporteVentasConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        genericos=genericos,
        nombre_archivo=nombre_archivo,
        con_slicers=con_slicers,
        con_cobertura=con_cobertura,
    )

    if genericos:
        print(f"Filtrando por genericos: {genericos}")

    service = VentasService()

    # Modo supervisores: genera un archivo por supervisor
    if supervisores:
        print(f"Generando reportes por supervisor: {list(supervisores.keys())}")
        results = service.generar_reporte_supervisores(config, supervisores)
        for result in results:
            print(f"\nSupervisor: {result.supervisor}")
            _imprimir_resultado(result, con_slicers)
        return 0

    # Modo normal: un archivo con todas las sucursales
    print(f"Generando reporte de ventas desde {fecha_desde} hasta {fecha_hasta}...")
    result = service.generar_reporte(config)
    _imprimir_resultado(result, con_slicers)
    return 0


def _imprimir_resultado(result, con_slicers: bool):
    """Imprime el resultado de un reporte generado."""
    print("Reporte generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Hojas: {', '.join(result.hojas)}")
    print(f"  - Registros de ventas: {result.registros_ventas}")
    print(f"  - Registros procesados: {result.registros_procesados}")
    print(f"  - Sucursales: {result.sucursales}")
    print(f"  - Genericos: {len(result.genericos_incluidos)}")
    if result.slicers_agregados:
        print("  - Slicers: Agregados (Sucursal, Generico, Marca)")
    elif con_slicers:
        print("  - Slicers: No disponibles (requiere Windows + Excel)")


def cmd_resumen_mensual(args) -> int:
    """Ejecuta el comando de resumen mensual."""

    # Cargar configuracion desde JSON si se provee --config
    cfg = _cargar_config_json(args.config) if args.config else {}

    # Resolver parametros: JSON tiene precedencia sobre args individuales
    fecha_desde = cfg.get("fecha_desde") or args.desde
    fecha_hasta = cfg.get("fecha_hasta") or args.hasta
    genericos_raw = cfg.get("genericos") or parsear_genericos(args.genericos)
    nombre_archivo = cfg.get("output") or args.output
    con_objetivo = cfg.get("con_objetivo", False)

    # Tratar lista vacia como None (trae todos los genericos)
    genericos = genericos_raw if genericos_raw else None

    # Validar campos requeridos
    if not fecha_desde or not fecha_hasta:
        print("Error: fecha_desde y fecha_hasta son requeridos.")
        print("       Usa --desde/--hasta o definelos en --config config.json")
        return 1

    if not validar_fecha(fecha_desde) or not validar_fecha(fecha_hasta):
        print("Error: Las fechas deben tener formato YYYY-MM-DD")
        return 1

    # Crear configuracion del servicio
    config = ResumenMensualConfig(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        genericos=genericos,
        nombre_archivo=nombre_archivo,
        con_objetivo=con_objetivo,
    )

    if genericos:
        print(f"Filtrando por genericos: {genericos}")

    print(f"Generando resumen mensual desde {fecha_desde} hasta {fecha_hasta}...")
    result = ResumenMensualService().generar_reporte(config)

    print("Resumen mensual generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Hojas: {', '.join(result.hojas)}")
    print(f"  - Registros procesados: {result.registros_procesados}")
    print(f"  - Sucursales: {result.sucursales}")
    print(f"  - Genericos: {len(result.genericos_incluidos)}")
    return 0


def _cargar_grupos_desde_xlsx(
    ruta_xlsx: str,
    requiere_todas_marcas: bool = False,
) -> list[GrupoArticulos]:
    """Lee el XLSX y construye GrupoArticulos por CATEGORIA."""
    path = Path(ruta_xlsx)
    if not path.exists():
        raise ValueError(f"Archivo no encontrado: {path}")

    df = pd.read_excel(path, dtype={"CODIGO": "Int64"})

    columnas_requeridas = {"CODIGO", "ARTICULO", "MARCA", "CATEGORIA"}
    faltantes = columnas_requeridas - set(df.columns)
    if faltantes:
        raise ValueError(f"Columnas faltantes en el XLSX: {faltantes}")

    if df.empty:
        raise ValueError("El XLSX no contiene filas de datos.")

    grupos = []
    for categoria, grupo_df in df.groupby("CATEGORIA", sort=False):
        grupo_df = grupo_df.drop_duplicates(subset=["CODIGO"])
        grupo_df = grupo_df.dropna(subset=["CODIGO"])
        if grupo_df.empty:
            print(f"⚠ Categoria '{categoria}' omitida: no tiene articulos validos.")
            continue

        articulos = {int(row["CODIGO"]): str(row["MARCA"]).upper() for _, row in grupo_df.iterrows()}
        marcas = list(dict.fromkeys(str(m).upper() for m in grupo_df["MARCA"]))

        grupos.append(GrupoArticulos(
            nombre=str(categoria),
            marcas=marcas,
            articulos=articulos,
            requiere_todas_marcas=requiere_todas_marcas,
        ))

    return grupos


def cmd_mision_posible(args) -> int:
    """Ejecuta el comando de reporte Mision Posible."""

    cfg = _cargar_config_json(args.config) if args.config else {}

    periodo = cfg.get("periodo") or args.periodo
    grupos_raw = cfg.get("grupos")
    archivo_articulos = cfg.get("archivo_articulos")
    nombre_archivo = cfg.get("nombre_archivo") or args.output
    objetivos = cfg.get("objetivos", {})
    porcentajes_sucursal = cfg.get("porcentajes_sucursal", {})
    supervisores = cfg.get("supervisores")

    if not periodo:
        print("Error: periodo es requerido.")
        print("       Usa --periodo o definelo en --config config.json")
        return 1

    if not grupos_raw and not archivo_articulos:
        if cfg.get("marcas"):
            print("Error: el formato 'marcas' ya no es soportado.")
            print("       Usa 'grupos' en su lugar. Ejemplo:")
            print('       "grupos": [{"nombre": "IMPERIAL", "marcas": ["IMPERIAL"]}]')
            return 1
        print("Error: grupos o archivo_articulos es requerido.")
        print("       Definelo en --config config.json")
        return 1

    # Build grupos from manual JSON entries
    grupos = []
    if grupos_raw:
        if any("marca" in g and "marcas" not in g for g in grupos_raw):
            raise ValueError(
                "El formato de grupos cambió: usar 'marcas': ['X'] en lugar de 'marca': 'X'"
            )
        grupos = [
            GrupoArticulos(
                nombre=g["nombre"],
                marcas=g["marcas"],
                filtro_descripcion=g.get("filtro_descripcion"),
                requiere_todas_marcas=g.get("requiere_todas_marcas", False),
            )
            for g in grupos_raw
        ]

    # Append grupos from XLSX if archivo_articulos is present
    if archivo_articulos:
        requiere_todas_marcas_global = cfg.get("requiere_todas_marcas", False)
        grupos_xlsx = _cargar_grupos_desde_xlsx(archivo_articulos, requiere_todas_marcas_global)
        grupos.extend(grupos_xlsx)

    config = MisionPosibleConfig(
        periodo=periodo,
        grupos=grupos,
        objetivos=objetivos,
        porcentajes_sucursal=porcentajes_sucursal,
        nombre_archivo=nombre_archivo,
    )

    print(f"Generando reporte Mision Posible para {periodo}...")
    print(f"  Grupos: {', '.join(g.nombre for g in grupos)}")

    service = MisionPosibleService()

    if supervisores:
        print(f"  Supervisores: {list(supervisores.keys())}")
        results = service.generar_reporte_supervisores(config, supervisores)
        for result in results:
            print(f"\n  Supervisor: {result.supervisor}")
            for ruta in result.ruta_archivos:
                print(f"    Archivo: {ruta}")
    else:
        result = service.generar_reporte(config)
        for ruta in result.ruta_archivos:
            print(f"  Archivo: {ruta}")
        print(f"  Hojas: {', '.join(result.hojas)}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Generador de reportes CCU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Con args individuales
  python main.py ventas --desde 2026-01-01 --hasta 2026-01-31
  python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --genericos "CERVEZAS,AGUAS"

  # Con archivo de configuracion (recomendado)
  python main.py ventas --config config.json

  # Resumen mensual
  python main.py resumen-mensual --desde 2026-02-01 --hasta 2026-02-28
  python main.py resumen-mensual --config config_resumen.json
"""
    )

    subparsers = parser.add_subparsers(
        title="comandos",
        description="Tipos de reportes disponibles",
        dest="comando"
    )

    # Subcomando: ventas
    ventas_parser = subparsers.add_parser(
        "ventas",
        help="Reporte de ventas por sucursal, generico y marca",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Grupo: configuracion via JSON (alternativa a args individuales)
    ventas_parser.add_argument(
        "--config",
        default=None,
        metavar="config.json",
        help=(
            "Archivo JSON con todos los parametros del reporte. "
            "Tiene precedencia sobre los args individuales. "
            "Soporta: fecha_desde, fecha_hasta, genericos, output, "
            "con_slicers, con_cobertura, supervisores."
        )
    )

    # Args individuales (opcionales si se usa --config)
    ventas_parser.add_argument(
        "--desde",
        default=None,
        help="Fecha inicio (YYYY-MM-DD)"
    )
    ventas_parser.add_argument(
        "--hasta",
        default=None,
        help="Fecha fin (YYYY-MM-DD)"
    )
    ventas_parser.add_argument(
        "--genericos",
        default=None,
        help="Genericos a incluir, separados por coma (ej: CERVEZAS,AGUAS,VINOS)"
    )
    ventas_parser.add_argument(
        "--output",
        default=None,
        help="Nombre del archivo de salida (sin extension)"
    )
    ventas_parser.add_argument(
        "--slicers",
        action="store_true",
        default=True,
        help="Agregar slicers/segmentadores (solo Windows con Excel)"
    )
    ventas_parser.add_argument(
        "--no-slicers",
        action="store_false",
        dest="slicers",
        help="No agregar slicers"
    )
    ventas_parser.set_defaults(func=cmd_ventas)

    # Subcomando: resumen-mensual
    resumen_parser = subparsers.add_parser(
        "resumen-mensual",
        help="Resumen mensual por generico (ultimos dias, tendencia, anio anterior)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Grupo: configuracion via JSON (alternativa a args individuales)
    resumen_parser.add_argument(
        "--config",
        default=None,
        metavar="config.json",
        help=(
            "Archivo JSON con todos los parametros del reporte. "
            "Tiene precedencia sobre los args individuales. "
            "Soporta: fecha_desde, fecha_hasta, genericos, output, con_objetivo."
        )
    )

    # Args individuales (opcionales si se usa --config)
    resumen_parser.add_argument(
        "--desde",
        default=None,
        help="Fecha inicio (YYYY-MM-DD)"
    )
    resumen_parser.add_argument(
        "--hasta",
        default=None,
        help="Fecha fin (YYYY-MM-DD)"
    )
    resumen_parser.add_argument(
        "--genericos",
        default=None,
        help="Genericos a incluir, separados por coma (ej: CERVEZAS,AGUAS,VINOS)"
    )
    resumen_parser.add_argument(
        "--output",
        default=None,
        help="Nombre del archivo de salida (sin extension)"
    )
    resumen_parser.set_defaults(func=cmd_resumen_mensual)

    # Subcomando: mision-posible
    mision_parser = subparsers.add_parser(
        "mision-posible",
        help="Reporte de cobertura Mision Posible por marca",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mision_parser.add_argument(
        "--config",
        default=None,
        metavar="config.json",
        help=(
            "Archivo JSON con todos los parametros del reporte. "
            "Soporta: periodo, marcas, objetivos, porcentajes_sucursal, "
            "nombre_archivo, supervisores."
        )
    )
    mision_parser.add_argument(
        "--periodo",
        default=None,
        help="Periodo del reporte (YYYY-MM-DD, primer dia del mes)"
    )
    mision_parser.add_argument(
        "--marcas",
        default=None,
        help="Marcas a incluir, separadas por coma (ej: Imperial,Levite)"
    )
    mision_parser.add_argument(
        "--output",
        default=None,
        help="Nombre del archivo de salida (sin extension)"
    )
    mision_parser.set_defaults(func=cmd_mision_posible)

    # Parsear argumentos
    args = parser.parse_args()

    if args.comando is None:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
