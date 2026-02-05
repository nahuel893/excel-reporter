# Excel Reporter

Sistema modular para generacion automatizada de reportes Excel desde Data Warehouse PostgreSQL.

Disenado con arquitectura limpia y extensible para soportar multiples tipos de reportes con minimo codigo nuevo.

## Stack Tecnologico

| Tecnologia | Proposito |
|------------|-----------|
| Python 3.12+ | Runtime |
| SQLAlchemy | Conexion PostgreSQL |
| Pandas | Procesamiento de datos |
| OpenPyXL | Generacion Excel |
| pytest | Testing con mocks |

## Arquitectura

```
excel-reporter/
├── config/
│   └── settings.py              # Configuracion centralizada
├── src/
│   ├── core/                    # Componentes reutilizables
│   │   ├── data_loader.py       # Acceso a BD (Repository Pattern)
│   │   ├── excel_writer.py      # Sistema modular de Excel
│   │   └── base_processor.py    # Utilidades compartidas
│   └── services/                # Capa de negocio
│       ├── base_service.py      # Clase abstracta
│       └── ventas/              # Reporte de ventas
│           ├── service.py       # Orquestador
│           └── processor.py     # Logica especifica
├── tests/
├── main.py                      # CLI
└── data/output/                 # Reportes generados
```

### Patrones de Diseno

- **Service Layer**: Cada reporte es un servicio independiente que orquesta el flujo
- **Dependency Injection**: `DataLoader` inyectable permite testing sin BD real
- **Repository Pattern**: Abstraccion del acceso a datos en `DataLoader`
- **Template Method**: `BaseService` define estructura comun para reportes

### Flujo de Datos

```
BD PostgreSQL → DataLoader → Processor → ExcelWriter → .xlsx
     ↓              ↓            ↓            ↓
  [Queries]    [DataFrames]  [Logica]    [Formato]
```

## Sistema de Estilos Excel

El sistema modular permite configurar formato, agrupaciones y resumen sin modificar el generador base.

### Componentes

```python
from src.core.excel_writer import SheetStyle, ColumnFormat, ColumnGroup

# Formato por columna
ColumnFormat(
    number_format='$ #,##0',    # Formato numerico
    alignment='center',          # Alineacion
    font_bold=True,              # Negrita
    width=15                     # Ancho fijo
)

# Grupo colapsable
ColumnGroup(
    start_col='01-01 Lunes',     # Columna inicio
    end_col='29-01 Jueves',      # Columna fin
    collapsed=True               # Inicia colapsado
)

# Estilo completo
SheetStyle(
    numeric_format='#,##0',                    # Formato numerico por defecto
    column_formats={'Monto': fmt},             # Formatos especificos
    column_groups=[group],                     # Agrupaciones
    summary_rows={'Dias Habiles': 26}          # Filas de resumen al inicio
)
```

### Ejemplo de Output

```
| A                   | B  |
|---------------------|----|
| Dias Habiles        | 26 |
| Dias Transcurridos  | 15 |
| Dias Faltantes      | 11 |
|                     |    |
| Sucursal | Generico | Marca | 01-01 Lun | ... | Total |
|----------|----------|-------|-----------|-----|-------|
| SUC001   | CERVEZA  | MARCA1| 10        | ... | 150   |
```

## Uso

### Instalacion

```bash
# Clonar repositorio
git clone https://github.com/tu-usuario/excel-reporter.git
cd excel-reporter

# Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con credenciales de BD
```

### Generar Reportes

```bash
# Reporte de ventas completo
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31

# Filtrar por genericos
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --genericos "CERVEZAS,AGUAS"

# Nombre de archivo personalizado
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --output "reporte_enero"
```

### Configuracion

Variables de entorno en `.env`:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=datawarehouse
DB_USER=usuario
DB_PASSWORD=password
```

## Crear Nuevo Reporte

### 1. Crear estructura de carpetas

```bash
mkdir -p src/services/inventario
touch src/services/inventario/__init__.py
touch src/services/inventario/service.py
touch src/services/inventario/processor.py
```

### 2. Implementar el procesador

```python
# src/services/inventario/processor.py
import pandas as pd

def procesar_inventario(df: pd.DataFrame) -> pd.DataFrame:
    """Logica especifica de procesamiento."""
    # Transformaciones, calculos, pivots...
    return df_procesado
```

### 3. Implementar el servicio

```python
# src/services/inventario/service.py
from dataclasses import dataclass
from src.services.base_service import BaseService
from src.core.excel_writer import generar_excel, SheetStyle, ColumnFormat
from .processor import procesar_inventario

@dataclass
class ReporteInventarioConfig:
    fecha: str
    bodega: str | None = None

@dataclass
class ReporteInventarioResult:
    ruta_archivo: Path
    items_procesados: int

class InventarioService(BaseService):
    def generar_reporte(self, config: ReporteInventarioConfig) -> ReporteInventarioResult:
        # 1. Extraer datos
        df = self.data_loader.execute_query("""
            SELECT bodega, producto, stock, costo
            FROM gold.fact_inventario
            WHERE fecha = :fecha
        """, {"fecha": config.fecha})

        # 2. Procesar
        df_procesado = procesar_inventario(df)

        # 3. Configurar estilo
        style = SheetStyle(
            column_formats={
                'Costo': ColumnFormat(number_format='$ #,##0'),
            }
        )

        # 4. Generar Excel
        ruta = generar_excel(df_procesado, f"inventario_{config.fecha}", style=style)

        return ReporteInventarioResult(
            ruta_archivo=ruta,
            items_procesados=len(df_procesado)
        )
```

### 4. Exportar en __init__.py

```python
# src/services/inventario/__init__.py
from .service import InventarioService, ReporteInventarioConfig, ReporteInventarioResult
```

### 5. Agregar subcomando en main.py

```python
@app.command()
def inventario(fecha: str, bodega: str = None):
    """Genera reporte de inventario."""
    service = InventarioService()
    config = ReporteInventarioConfig(fecha=fecha, bodega=bodega)
    result = service.generar_reporte(config)
    print(f"Reporte generado: {result.ruta_archivo}")
```

## Testing

```bash
# Todos los tests
pytest -v

# Solo unitarios (sin BD)
pytest tests/test_processor.py -v

# Solo integracion (requiere BD)
pytest tests/test_services.py -v

# Con cobertura
pytest --cov=src --cov-report=html
```

### Ejemplo de Test con Mock

```python
from unittest.mock import Mock
from src.services.ventas import VentasService

def test_generar_reporte():
    # Mock del DataLoader
    mock_loader = Mock()
    mock_loader.get_ventas_diarias.return_value = pd.DataFrame({
        'sucursal': ['SUC1'],
        'generico': ['CERVEZA'],
        'marca': ['MARCA1'],
        'fecha': ['2026-01-01'],
        'cantidad': [10],
        'monto': [1000]
    })

    service = VentasService(data_loader=mock_loader)
    # ... assertions
```

## Estructura de la Base de Datos

El sistema espera un Data Warehouse con arquitectura Medallion (capa Gold):

```sql
-- Dimensiones
gold.dim_sucursal (id_sucursal, descripcion)
gold.dim_articulo (id_articulo, generico, marca)

-- Hechos
gold.fact_ventas (id_sucursal, id_articulo, fecha_comprobante, cantidades_total, subtotal_neto)
```

## Licencia

MIT
