"""
CLI para generacion de reportes CCU.

Uso:
    python main.py ventas --desde 2026-01-01 --hasta 2026-01-31
    python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --genericos "CERVEZAS,AGUAS"

Subcomandos disponibles:
    ventas    - Reporte de ventas por sucursal, generico y marca
"""
import argparse
import sys
from datetime import datetime

from src.services import VentasService
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


def cmd_ventas(args) -> int:
    """Ejecuta el comando de reporte de ventas."""
    # Validar fechas
    if not validar_fecha(args.desde) or not validar_fecha(args.hasta):
        print("Error: Las fechas deben tener formato YYYY-MM-DD")
        return 1

    # Parsear genericos
    genericos = parsear_genericos(args.genericos)

    # Crear configuracion
    config = ReporteVentasConfig(
        fecha_desde=args.desde,
        fecha_hasta=args.hasta,
        genericos=genericos,
        nombre_archivo=args.output,
        con_slicers=args.slicers
    )

    if genericos:
        print(f"Filtrando por genericos: {genericos}")

    # Ejecutar servicio
    print(f"Generando reporte de ventas desde {args.desde} hasta {args.hasta}...")

    service = VentasService()
    result = service.generar_reporte(config)

    # Mostrar resultado
    print(f"Reporte generado exitosamente:")
    print(f"  - Archivo: {result.ruta_archivo}")
    print(f"  - Hojas: {', '.join(result.hojas)}")
    print(f"  - Registros de ventas: {result.registros_ventas}")
    print(f"  - Registros procesados: {result.registros_procesados}")
    print(f"  - Sucursales: {result.sucursales}")
    print(f"  - Genericos: {len(result.genericos_incluidos)}")
    if result.slicers_agregados:
        print(f"  - Slicers: Agregados (Sucursal, Generico, Marca)")
    elif args.slicers:
        print(f"  - Slicers: No disponibles (requiere Windows + Excel)")

    return 0


def add_date_arguments(parser):
    """Agrega argumentos de fecha comunes a un parser."""
    parser.add_argument(
        "--desde",
        required=True,
        help="Fecha inicio (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--hasta",
        required=True,
        help="Fecha fin (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Nombre del archivo de salida (sin extension)"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Generador de reportes CCU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python main.py ventas --desde 2026-01-01 --hasta 2026-01-31
  python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --genericos "CERVEZAS,AGUAS"
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
        help="Reporte de ventas por sucursal, generico y marca"
    )
    add_date_arguments(ventas_parser)
    ventas_parser.add_argument(
        "--genericos",
        default=None,
        help="Genericos a incluir, separados por coma (ej: CERVEZAS,AGUAS,VINOS)"
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

    # Parsear argumentos
    args = parser.parse_args()

    # Si no se especifico comando, mostrar ayuda
    if args.comando is None:
        parser.print_help()
        return 1

    # Ejecutar el comando
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
