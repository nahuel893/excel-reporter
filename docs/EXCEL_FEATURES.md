# Características Excel Avanzadas

## Slicers (Segmentadores)

Los slicers son controles visuales interactivos que permiten filtrar datos en tablas Excel de forma intuitiva.

### ¿Qué son los Slicers?

Los slicers son botones visuales que aparecen en el Excel y permiten filtrar datos con un click. Son más intuitivos que los filtros tradicionales de tabla.

**Ejemplo visual:**
```
┌─────────────────┐
│   Sucursal      │
├─────────────────┤
│ ☑ SUCURSAL A    │
│ ☐ SUCURSAL B    │
│ ☑ SUCURSAL C    │
└─────────────────┘
```

### Implementación

#### Requisitos

- **Sistema Operativo**: Windows
- **Software**: Microsoft Excel instalado
- **Librería Python**: pywin32

En sistemas Linux/Mac, los slicers no están disponibles pero el reporte se genera normalmente.

#### Verificación de disponibilidad

```python
from src.core.excel_slicers import slicers_disponibles

if slicers_disponibles():
    print("Slicers disponibles")
else:
    print("Slicers no disponibles en este sistema")
```

#### Uso básico

```python
from pathlib import Path
from src.core.excel_slicers import agregar_slicers

# Agregar slicers a un archivo Excel existente
exito = agregar_slicers(
    archivo_excel=Path("reporte.xlsx"),
    nombre_tabla="Tabla_Ventas",
    columnas_slicer=["Sucursal", "Generico", "Marca"]
)

if exito:
    print("Slicers agregados exitosamente")
```

#### Configuración de posición

Por defecto, los slicers se posicionan automáticamente:
- **Posición horizontal**: Columna H en adelante (left=500px)
- **Separación**: 160px entre slicers
- **Posición vertical**: Fila 1 (top=5px)
- **Tamaño**: 144px ancho × 110px alto

Para posiciones personalizadas:

```python
# Posiciones custom: (left, top) en puntos
posiciones_custom = [
    (600, 10),   # Slicer 1
    (760, 10),   # Slicer 2
    (920, 10),   # Slicer 3
]

agregar_slicers(
    archivo_excel=Path("reporte.xlsx"),
    nombre_tabla="Tabla_Ventas",
    columnas_slicer=["Sucursal", "Generico", "Marca"],
    posiciones=posiciones_custom
)
```

### Uso en CLI

```bash
# Con slicers (default en Windows)
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31

# Sin slicers (más rápido)
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --no-slicers
```

### Uso en API

```json
{
  "fecha_desde": "2026-01-01",
  "fecha_hasta": "2026-01-31",
  "con_slicers": true
}
```

### Detalles técnicos

El módulo `excel_slicers.py` usa win32com para manipular Excel:

1. Abre el archivo Excel con `win32.gencache.EnsureDispatch("Excel.Application")`
2. Localiza la tabla por nombre
3. Crea un `SlicerCache` para cada columna
4. Agrega el `Slicer` visual a la hoja
5. Guarda y cierra el archivo

**Nota**: Excel debe estar cerrado al ejecutar el proceso.

### Compatibilidad multiplataforma

```python
import platform

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    try:
        import win32com.client as win32
        WIN32COM_AVAILABLE = True
    except ImportError:
        WIN32COM_AVAILABLE = False
else:
    WIN32COM_AVAILABLE = False
```

El código detecta automáticamente el sistema operativo y solo intenta usar win32com en Windows.

---

## Column Groups (Grupos de Columnas)

Los grupos de columnas permiten colapsar/expandir secciones de columnas en Excel, útil para reportes con muchas columnas.

### ¿Qué son los Column Groups?

Los column groups son secciones colapsables de columnas. Al hacer click en el botón `-`, las columnas se ocultan. Al hacer click en `+`, se muestran.

**Ejemplo visual:**
```
[−] Días del mes
    01-01  02-01  03-01  ...  29-01  30-01  31-01

Después de colapsar:
[+] Días del mes
                               29-01  30-01  31-01
```

### Implementación

#### Configuración básica

```python
from src.core.excel_writer import SheetStyle, ColumnGroup

style = SheetStyle(
    column_groups=[
        ColumnGroup(
            start_col="01-01 Jueves",
            end_col="29-01 Miércoles",
            collapsed=True  # Inicia colapsado
        )
    ]
)
```

#### En el reporte de ventas

El servicio de ventas agrupa automáticamente las columnas de días:

```python
def _crear_estilo_ventas(
    columnas_dias: list[str],
    info_dias: dict[str, int],
    dias_visibles: int = 2
) -> SheetStyle:
    """
    Agrupa las columnas de días, dejando visibles los últimos N días.

    Args:
        columnas_dias: Lista de columnas de días
        info_dias: Info de días hábiles
        dias_visibles: Cantidad de días al final que quedan visibles (default: 2)
    """
    groups = []

    if len(columnas_dias) > dias_visibles:
        start_col = columnas_dias[0]
        end_col = columnas_dias[-(dias_visibles + 1)]
        groups.append(
            ColumnGroup(
                start_col=start_col,
                end_col=end_col,
                collapsed=True
            )
        )

    return SheetStyle(column_groups=groups, ...)
```

### Comportamiento

#### collapsed=True

Las columnas inician **ocultas** cuando se abre el Excel:
- Grupo aparece con botón `[+]`
- Columnas dentro del grupo no son visibles
- Click en `[+]` expande el grupo

#### collapsed=False

Las columnas inician **visibles** cuando se abre el Excel:
- Grupo aparece con botón `[−]`
- Columnas dentro del grupo son visibles
- Click en `[−]` colapsa el grupo

### Detalles técnicos

En openpyxl, para que un grupo inicie colapsado, las columnas deben estar **ocultas**:

```python
# En excel_writer.py
for group in style.column_groups:
    start_idx = col_to_idx.get(group.start_col)
    end_idx = col_to_idx.get(group.end_col)

    if start_idx and end_idx and start_idx <= end_idx:
        # Si collapsed=True, ocultar columnas
        should_hide = group.collapsed or group.hidden
        ws.column_dimensions.group(
            get_column_letter(start_idx),
            get_column_letter(end_idx),
            hidden=should_hide
        )

# Botón de grupo arriba (no a la derecha)
ws.sheet_properties.outlinePr.summaryRight = False
```

### Múltiples grupos

Puedes crear múltiples grupos independientes:

```python
style = SheetStyle(
    column_groups=[
        ColumnGroup("A", "E", collapsed=True),   # Grupo 1
        ColumnGroup("H", "Z", collapsed=False),  # Grupo 2
    ]
)
```

### Grupos anidados

Excel soporta grupos anidados (niveles de outline):

```python
# Grupo externo
ColumnGroup("A", "Z", collapsed=False)

# Grupo interno (dentro del anterior)
ColumnGroup("B", "Y", collapsed=True)
```

**Nota**: openpyxl tiene soporte limitado para grupos anidados. Para casos complejos, considerar usar win32com.

---

## Combinación de Características

### Slicers + Column Groups

Ambas características funcionan perfectamente juntas:

```python
from src.services.ventas import VentasService, ReporteVentasConfig

config = ReporteVentasConfig(
    fecha_desde="2026-01-01",
    fecha_hasta="2026-01-31",
    con_slicers=True  # Slicers habilitados
)

service = VentasService()
result = service.generar_reporte(config)

# El Excel tendrá:
# - Columnas de días colapsadas (últimos 2 visibles)
# - Slicers para Sucursal, Generico, Marca
```

### Ejemplo completo

```python
from pathlib import Path
from src.core.excel_writer import generar_excel, SheetStyle, ColumnGroup
from src.core.excel_slicers import agregar_slicers, slicers_disponibles
import pandas as pd

# 1. Crear DataFrame
df = pd.DataFrame({
    'Sucursal': ['A', 'B', 'C'],
    'Producto': ['X', 'Y', 'Z'],
    'Enero': [100, 200, 300],
    'Febrero': [150, 250, 350],
    'Marzo': [120, 220, 320],
})

# 2. Configurar estilo con grupos
style = SheetStyle(
    column_groups=[
        ColumnGroup('Enero', 'Febrero', collapsed=True)
    ],
    as_table=True,
    table_style="TableStyleMedium9"
)

# 3. Generar Excel
ruta = generar_excel(
    df,
    nombre_archivo="reporte_ejemplo",
    sheet_name="Ventas",
    style=style
)

# 4. Agregar slicers (solo Windows)
if slicers_disponibles():
    agregar_slicers(
        archivo_excel=ruta,
        nombre_tabla="Tabla_Ventas",
        columnas_slicer=["Sucursal", "Producto"]
    )
```

---

## Troubleshooting

### Slicers no aparecen

**Problema**: Los slicers no son visibles en el Excel.

**Soluciones**:
1. Verificar que estás en Windows con Excel instalado
2. Cerrar el archivo Excel antes de ejecutar el script
3. Revisar la posición de los slicers (pueden estar fuera del área visible)
4. Verificar que pywin32 esté instalado: `pip install pywin32`

### Grupos no inician colapsados

**Problema**: Las columnas aparecen expandidas al abrir el Excel.

**Solución**: Asegurarse de usar `collapsed=True` en el ColumnGroup:

```python
ColumnGroup(start_col="A", end_col="Z", collapsed=True)
```

### Error de permisos al generar Excel

**Problema**: `PermissionError: [Errno 13]`

**Solución**: Cerrar el archivo Excel si está abierto.

---

## Referencias

- [OpenPyXL Documentation](https://openpyxl.readthedocs.io/)
- [pywin32 Documentation](https://github.com/mhammond/pywin32)
- [Excel VBA SlicerCache](https://docs.microsoft.com/en-us/office/vba/api/excel.slicercache)
