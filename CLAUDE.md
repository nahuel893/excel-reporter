# Excel Reporter - Contexto del Proyecto

## Descripcion
Generador automatizado de reportes Excel desde Data Warehouse PostgreSQL (arquitectura Medallion - capa Gold).

## Stack Tecnologico
- Python 3.12+
- SQLAlchemy (conexion BD)
- Pandas (procesamiento)
- OpenPyXL (generacion Excel)
- pywin32 (slicers, solo Windows)
- pytest (testing)

## Estructura del Proyecto

```
├── config/
│   └── settings.py          # DB_CONFIG, FERIADOS, COLUMN_NAMES, DIAS_SEMANA
├── src/
│   ├── core/                 # Codigo compartido
│   │   ├── data_loader.py    # DataLoader (acceso BD, get_ventas_diarias)
│   │   ├── excel_writer.py   # generar_excel, SheetStyle, ColumnFormat, ColumnGroup, summary_rows, as_table
│   │   ├── excel_slicers.py  # agregar_slicers, slicers_disponibles (solo Windows)
│   │   └── base_processor.py # calcular_dias_habiles, calcular_info_dias, calcular_factor_tendencia
│   └── services/
│       ├── base_service.py   # BaseService (clase abstracta)
│       └── ventas/           # Reporte de ventas
│           ├── service.py    # VentasService, _crear_estilo_ventas, VENTAS_COLUMN_FORMATS
│           └── processor.py  # procesar_ventas_diarias, formatear_nombre_dia
├── tests/
├── main.py                   # CLI con subcomandos
└── data/output/              # Archivos generados
```

## Comandos

```bash
# Activar entorno virtual
.venv\Scripts\activate

# Generar reporte (con slicers en Windows)
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31

# Con filtro de genericos
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --genericos "CERVEZAS,AGUAS"

# Sin slicers (mas rapido, compatible con todos los OS)
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --no-slicers

# Tests
pytest -v
```

## Formato del Reporte de Ventas

```
Sucursal | Generico | Cant(Gen) | Tend(Gen) | Monto(Gen) | Marca | 01-01 Jueves | ... | Total | Tend(Marca) | Monto(Marca)
```

- **Totales de generico**: Solo aparecen en la primera fila de cada grupo sucursal-generico
- **Columnas de dias**: Formato `dd-mm DiaSemana`, valores 0 si no hay venta
- **Tendencia**: `cantidad * (dias_totales_mes / dias_transcurridos_hasta_hoy)`
- **Dias habiles**: Excluyen domingos y feriados (config/settings.py)

## Sistema de Formatos Excel

```python
# Estilos modulares en excel_writer.py
SheetStyle(
    numeric_format="#,##0",           # Formato numerico por defecto (sin decimales)
    column_formats={                   # Formatos especificos por columna
        "Monto (Generico)": ColumnFormat(number_format='$ #,##0'),
        "Monto (Marca)": ColumnFormat(number_format='$ #,##0'),
    },
    column_groups=[                    # Grupos colapsables
        ColumnGroup(start_col="01-01 Jueves", end_col="29-01 Jueves", collapsed=True)
    ],
    summary_rows={                     # Filas de resumen al inicio
        "Dias Habiles": 26,
        "Dias Transcurridos": 15,
        "Dias Faltantes": 11,
    },
    as_table=True,                     # Convertir a tabla Excel nativa
    table_style="TableStyleMedium9"    # Estilo de tabla
)
```

### Agrupacion de Columnas (Column Groups)

Las columnas de dias se agrupan automaticamente en Excel (colapsables), dejando visibles los ultimos 2 dias:

```python
# service.py - _crear_estilo_ventas()
def _crear_estilo_ventas(columnas_dias: list[str], info_dias: dict, dias_visibles: int = 2) -> SheetStyle:
    # Agrupa columnas_dias[0] hasta columnas_dias[-(dias_visibles + 1)]
    # Los ultimos 2 dias quedan fuera del grupo (siempre visibles)
```

### Filas de Resumen (Summary Rows)

Las primeras 3 filas del Excel muestran info de dias habiles:

```
| Dias Habiles        | 26 |
| Dias Transcurridos  | 15 |
| Dias Faltantes      | 11 |
|                     |    |  <- fila vacia
| Sucursal | Generico | ...   <- encabezados de tabla
```

Calculadas por `calcular_info_dias()` en base_processor.py

### Formato de Tabla Excel (as_table)

Los datos se convierten automaticamente a tabla Excel nativa:
- Filtros en cada columna
- Ordenamiento interactivo
- Filas alternadas (row stripes)
- Estilo configurable via `table_style` (ej: TableStyleMedium1-28, TableStyleLight1-21)

### Formato de Encabezados

La primera fila de la tabla tiene formato especial:
- Texto blanco (color FFFFFF)
- Negrita
- Centrado horizontal y vertical
- Texto distribuido (wrap_text)

### Formato de Columnas Numericas

Las celdas con valores numericos tienen:
- Formato numerico sin decimales (`#,##0`)
- Texto centrado horizontalmente

### Slicers (Segmentadores)

Los slicers permiten filtrar datos visualmente. Solo disponibles en Windows con Excel instalado.

```python
# excel_slicers.py
from src.core.excel_slicers import agregar_slicers, slicers_disponibles

# Verificar disponibilidad
if slicers_disponibles():
    agregar_slicers(
        archivo_excel=Path("reporte.xlsx"),
        nombre_tabla="Tabla_Ventas",
        columnas_slicer=["Sucursal", "Generico", "Marca"]
    )
```

**CLI**:
```bash
# Con slicers (por defecto en Windows)
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31

# Sin slicers
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --no-slicers
```

**Compatibilidad**:
- Windows: Slicers agregados automaticamente si Excel esta instalado
- Linux/Mac: Slicers no disponibles, el reporte se genera sin ellos

## Patrones de Diseno

- **Service Layer**: VentasService orquesta el flujo
- **Dependency Injection**: DataLoader inyectable para testing
- **Repository Pattern**: DataLoader abstrae acceso a BD
- **Template Method**: BaseService para nuevos reportes

## Agregar Nuevo Reporte

1. Crear `src/services/nuevo_reporte/`
2. Crear `processor.py` con logica especifica
3. Crear `service.py` heredando de `BaseService`
4. Agregar subcomando en `main.py`

## Base de Datos

- **Esquema**: gold (Data Warehouse - capa Gold)
- **Tablas**: fact_ventas, dim_articulo, dim_sucursal
- **Conexion**: Variables en `.env` (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)

### Metodos de DataLoader

- `get_ventas_diarias()`: Ventas agrupadas por fecha (para columnas de dias)
- `get_ventas()`: Ventas totales sin desglose diario (compatibilidad)
- `get_sucursales()`: Lista de sucursales
- `get_articulos()`: Combinaciones generico-marca

## Notas Importantes

- Los imports usan paths completos: `from src.core.data_loader import DataLoader`
- Los tests unitarios usan mocks para aislar la BD
- El archivo `.env` no se commitea (esta en .gitignore)
