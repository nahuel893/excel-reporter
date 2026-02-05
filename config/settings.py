import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Rutas del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_INPUT = BASE_DIR / "data" / "input"
DATA_OUTPUT = BASE_DIR / "data" / "output"

# Configuración de base de datos
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

# Feriados Argentina 2026 (formato: "YYYY-MM-DD")
FERIADOS = [
    "2026-01-01",  # Año Nuevo
    "2026-02-16",  # Carnaval
    "2026-02-17",  # Carnaval
    "2026-03-24",  # Día de la Memoria
    "2026-04-02",  # Día del Veterano
    "2026-04-03",  # Viernes Santo
    "2026-05-01",  # Día del Trabajador
    "2026-05-25",  # Día de la Revolución de Mayo
    "2026-06-15",  # Paso a la Inmortalidad Güemes
    "2026-06-20",  # Día de la Bandera
    "2026-07-09",  # Día de la Independencia
    "2026-08-17",  # Paso a la Inmortalidad San Martín
    "2026-10-12",  # Día del Respeto a la Diversidad Cultural
    "2026-11-23",  # Día de la Soberanía Nacional
    "2026-12-08",  # Inmaculada Concepción
    "2026-12-25",  # Navidad
]

# Nombres de columnas para el reporte
COLUMN_NAMES = {
    "sucursal": "Sucursal",
    "generico": "Generico",
    "cant_generico": "Cantidad (Generico)",
    "tend_generico": "Tendencia (Generico)",
    "monto_generico": "Monto (Generico)",
    "marca": "Marca",
    # Columnas dinamicas de dias van aqui (generadas en processor)
    "total_marca": "Total",
    "tend_marca": "Tendencia (Marca)",
    "monto_marca": "Monto (Marca)",
}

# Nombres de dias en espanol
DIAS_SEMANA = {
    0: "Lunes",
    1: "Martes",
    2: "Miercoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sabado",
    6: "Domingo",
}
