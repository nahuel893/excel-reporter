# Spec: Mision Posible - Layout Multi-Tabla por Sucursal

> **Estado:** IMPLEMENTADA
> **Fecha:** 2026-03-07
> **Autor:** nahuel

## 1. Objetivo

Reemplazar el esquema de una hoja por marca del reporte Mision Posible por una hoja unica "Sucursales" que muestra las tablas de cobertura por sucursal de todas las marcas dispuestas en una grilla horizontal (hasta 4 por fila, continuando hacia abajo). Las tablas de cobertura por vendedor pasan a una hoja separada "Por Vendedor", manteniendo el mismo layout actual (una tabla por marca, apiladas verticalmente).

## 2. Contexto

El reporte Mision Posible actualmente genera una hoja por marca (ej: "IMPERIAL", "LEVITE", "VILLA DEL SUR"). Cada hoja contiene una tabla de sucursales encima y una tabla de vendedores abajo. Con tres o mas marcas, el usuario debe navegar entre hojas para comparar el estado de cobertura de cada sucursal entre marcas.

La necesidad es ver todas las marcas juntas para una lectura de una sola mirada: cada sucursal debe ser comparable horizontalmente entre marcas sin cambiar de hoja. La tabla por vendedor no tiene esta necesidad de comparacion cruzada, por lo que se mantiene en una hoja separada con el layout vertical existente.

El cambio principal impacta en la capa de servicio (`service.py`): la escritura de datos en posiciones arbitrarias (fila, columna) no esta soportada por `ExcelWriter`, que actualmente escribe secuencialmente desde la celda A1. Esta spec define como implementar ese mecanismo de escritura posicional directamente sobre `openpyxl` en el servicio, sin modificar `ExcelWriter`.

## 3. Requisitos Funcionales

### 3.1 Estructura del archivo

- **RF-001**: Cuando se genera el reporte Mision Posible, el sistema debe producir un archivo con exactamente dos hojas: "Sucursales" y "Por Vendedor", en ese orden.

- **RF-002**: Si `marcas` es una lista vacia o `None`, el sistema debe retornar un error descriptivo y no generar archivo. (Sin cambio respecto a la spec anterior.)

- **RF-003**: Cuando se genera el archivo, el sistema debe usar el nombre `Mision Posible {MM-YYYY}.xlsx` (o el nombre custom si esta configurado), igual que hoy.

### 3.2 Hoja "Sucursales"

- **RF-004**: Cuando se escribe la hoja "Sucursales", el sistema debe colocar la fila `Ult. Actualizacion: {fecha}` en la fila 1, columna A (etiqueta) y columna B (valor), igual que el `summary_row` actual, antes de la grilla de tablas.

- **RF-005**: Cuando se escribe la hoja "Sucursales", el sistema debe disponer las tablas de marcas en una grilla de hasta 4 columnas de tablas por fila de tablas, comenzando en la fila inmediatamente siguiente a la fila de resumen (con una fila vacia de separacion entre el resumen y la primera grilla).

- **RF-006**: Cuando el numero de marcas es mayor a 4, el sistema debe iniciar una nueva fila de tablas debajo de la primera, separada por exactamente una fila de altura reducida (altura = 6 puntos). Esta fila separadora no contiene datos.

- **RF-007**: Cuando se escribe cada tabla de marca en la grilla, el sistema debe renderizar:
  1. Una fila de titulo con el nombre de la marca (en negrita, fondo burdeo `A92C1F`, texto blanco), ocupando todas las columnas de la tabla (5 columnas: Sucursal, Cobertura, Objetivo, Faltante, %).
  2. Una fila de encabezado de columnas con el estilo de cabecera estandar (fondo burdeo, texto blanco, negrita).
  3. Una fila de datos por cada sucursal.

- **RF-008**: Cuando se disponen tablas horizontalmente, el sistema debe separar tablas adyacentes dentro de la misma fila de tablas con exactamente una columna vacia de ancho reducido (ancho = 2 unidades de Excel).

- **RF-009**: Cuando se aplica formato condicional a la columna `%` de cada tabla de la hoja "Sucursales", el sistema debe aplicar las reglas existentes con umbrales decimales: verde >= `0.80`, amarillo entre `0.40` y `0.799`, rojo < `0.40`. El valor de `%` se almacena como decimal (ej: `0.30` = 30%). El rango abarca solo las filas de datos de esa tabla (excluyendo titulo y encabezado).

- **RF-010**: Cuando se escribe una tabla de marca, el sistema debe usar los anchos de columna definidos en la seccion 5.3, aplicados a nivel de columna de worksheet (no por tabla individualmente, dado que multiples tablas comparten columnas de la hoja).

### 3.3 Hoja "Por Vendedor"

- **RF-011**: Cuando se escribe la hoja "Por Vendedor", el sistema debe renderizar las tablas de vendedores de todas las marcas apiladas verticalmente, en el mismo orden que `config.marcas`. Cada bloque contiene: titulo de marca, encabezado [Vendedor, Sucursal, Cobertura, Objetivo, Faltante, %], y filas de datos de `procesar_cobertura_vendedor`. NO se usa `concatenar_tablas`; se escribe directamente el DataFrame de vendedores por marca.

- **RF-012**: Cuando se escribe la hoja "Por Vendedor", el sistema debe incluir un titulo de marca antes de cada bloque de datos de vendedores (una fila con el nombre de la marca, fondo burdeo `A92C1F`, texto blanco, negrita — mismo estilo que en la hoja Sucursales).

- **RF-013**: Cuando se escribe la hoja "Por Vendedor", el sistema debe aplicar formato condicional a la columna `%` de cada bloque de vendedores con las mismas reglas decimales (verde >= `0.80`, amarillo `0.40`-`0.799`, rojo < `0.40`).

- **RF-014**: Cuando se escribe la hoja "Por Vendedor", el sistema debe incluir la fila `Ult. Actualizacion` al inicio de la hoja, antes del primer bloque de vendedores.

### 3.4 Zonas virtuales y supervisores

- **RF-015**: Cuando se procesan datos de cobertura, el sistema debe seguir aplicando `aplicar_zonas_virtuales()` al DataFrame de `cob_preventista_marca` antes de agrupar, igual que hoy. (Sin cambio.)

- **RF-016**: Cuando `supervisores` esta presente en la configuracion, el sistema debe generar un archivo por supervisor con las mismas dos hojas ("Sucursales" y "Por Vendedor"), filtrando los datos al universo de sucursales del supervisor. (Sin cambio en logica de filtrado.)

### 3.5 Resultado

- **RF-017**: Cuando se retorna `MisionPosibleResult`, el campo `hojas` debe contener `["Sucursales", "Por Vendedor"]` en lugar de la lista de marcas. (Cambio respecto al campo anterior que listo las marcas como hojas.)

## 4. Requisitos No Funcionales

- **RNF-001**: La generacion del reporte para hasta 8 marcas y todas las sucursales debe completarse en menos de 20 segundos con conexion normal a la base de datos.

- **RNF-002**: El archivo generado debe poder abrirse en Excel y LibreOffice sin errores de formato.

- **RNF-003**: Si la consulta a `cob_preventista_marca` falla, el sistema debe capturar la excepcion y generar las hojas con tablas vacias (sin propagar el error). (Sin cambio.)

- **RNF-004**: La escritura posicional en la hoja "Sucursales" debe hacerse directamente con la API de `openpyxl` (via `ws.cell(row, col, value)`), sin modificar `ExcelWriter` ni `_write_sheet`.

## 5. Diseno Tecnico

### 5.1 Modelo de Datos

Sin cambios. Las funciones del processor (`procesar_cobertura_sucursal`, `procesar_cobertura_vendedor`) siguen retornando los mismos DataFrames. La funcion `concatenar_tablas` se vuelve opcional (solo se usa en la hoja "Por Vendedor").

### 5.2 Arquitectura

Archivos afectados:

```
src/
  services/
    mision_posible/
      service.py     MODIFICADO: nueva logica de layout en generar_reporte y generar_reporte_supervisores
      processor.py   SIN CAMBIOS (las funciones de procesamiento no cambian)
tests/
  test_mision_posible.py   MODIFICADO: nuevos tests de layout, actualizacion de tests existentes
```

`ExcelWriter` no se modifica. La hoja "Sucursales" se escribe directamente sobre el `Worksheet` de `openpyxl` via un nuevo metodo privado `_escribir_hoja_sucursales(ws, tablas, ultima_fecha)` en el servicio. La hoja "Por Vendedor" se escribe con un metodo privado `_escribir_hoja_vendedores(ws, tablas_vend, ultima_fecha)`.

**Flujo de datos actualizado:**

```
MisionPosibleService.generar_reporte(config)
    |
    +-- _fetch_data(periodo)  --> df_cob, ultima_fecha
    |
    +-- Para cada marca:
    |     procesar_cobertura_sucursal(df_cob, marca, ...)  --> df_suc
    |     procesar_cobertura_vendedor(df_cob, marca, ...)  --> df_vend
    |     tablas_suc.append((marca, df_suc))
    |     tablas_vend.append((marca, df_vend))
    |
    +-- wb = openpyxl.Workbook()
    |
    +-- ws_suc = wb.active; ws_suc.title = "Sucursales"
    |     _escribir_hoja_sucursales(ws_suc, tablas_suc, ultima_fecha)
    |
    +-- ws_vend = wb.create_sheet("Por Vendedor")
    |     _escribir_hoja_vendedores(ws_vend, tablas_vend, ultima_fecha)
    |
    +-- wb.save(ruta)
    --> MisionPosibleResult(hojas=["Sucursales", "Por Vendedor"])
```

### 5.3 Layout de la hoja "Sucursales"

**Constantes de layout:**

```python
MARCAS_POR_FILA = 4          # maximo de tablas por fila horizontal
COLS_POR_TABLA = 5           # Sucursal, Cobertura, Objetivo, Faltante, %
COL_SEPARADOR_ANCHO = 2      # ancho en unidades Excel de la columna vacia entre tablas
FILA_SEPARADOR_ALTO = 6      # altura en puntos de la fila separadora entre filas de tablas
```

**Calculo de posicion de cada tabla:**

La grilla asigna a cada marca un indice `i` (0-based). La posicion se calcula:

```
fila_grupo = i // MARCAS_POR_FILA      # 0, 0, 0, 0, 1, 1, ...
col_grupo  = i %  MARCAS_POR_FILA      # 0, 1, 2, 3, 0, 1, ...

# Columna de inicio de la tabla (1-based):
col_inicio = 1 + col_grupo * (COLS_POR_TABLA + 1)
# La +1 es la columna separadora entre tablas.
# col_grupo=0 → col=1
# col_grupo=1 → col=7  (1 + 1*6)
# col_grupo=2 → col=13 (1 + 2*6)
# col_grupo=3 → col=19 (1 + 3*6)

# Fila de inicio de la tabla (1-based), considerando:
#   fila 1:   summary row (Ult. Actualizacion)
#   fila 2:   vacia de separacion entre resumen y grilla
#   +2 filas por cada grupo anterior (titulo + encabezado)
#   +N filas de datos del grupo anterior
#   +1 fila separadora entre grupos (altura reducida)
```

Como los grupos de tablas pueden tener distinto numero de filas de datos (si diferentes marcas tienen diferente cantidad de sucursales), la fila de inicio del grupo `g` se calcula dinamicamente como:

```
# FILA_INICIO_BASE depende de si hay summary row:
FILA_INICIO_BASE = 3 si ultima_fecha is not None   # fila 1 = resumen, fila 2 = vacia, fila 3 = primera tabla
FILA_INICIO_BASE = 1 si ultima_fecha is None        # sin resumen, grilla comienza en fila 1

fila_inicio_grupo[0] = FILA_INICIO_BASE
fila_inicio_grupo[g] = fila_inicio_grupo[g-1]
                       + max_filas_en_grupo[g-1]   # titulo(1) + encabezado(1) + max(sucursales en ese grupo)
                       + 1                          # fila separadora (solo entre grupos, NO despues del ultimo)
```

`max_filas_en_grupo[g]` es el maximo de `len(df_suc)` entre las marcas del grupo `g`, mas 2 (titulo + encabezado).

**NOTA**: La fila separadora solo se inserta entre grupos consecutivos. No se inserta despues del ultimo grupo. `COLS_POR_TABLA` debe coincidir con el numero de columnas retornadas por `procesar_cobertura_sucursal`.

**Estructura de cada tabla dentro de la grilla:**

```
fila_inicio + 0: [TITULO MARCA]  <- celda mergeada columnas col_inicio..col_inicio+4
fila_inicio + 1: [Sucursal] [Cobertura] [Objetivo] [Faltante] [%]   <- encabezado
fila_inicio + 2: datos fila 1
fila_inicio + 3: datos fila 2
...
fila_inicio + 1 + len(df_suc): ultima fila de datos
```

**Escritura de la fila separadora entre grupos (solo entre grupos, NO despues del ultimo):**

```python
num_grupos = ceil(len(marcas) / MARCAS_POR_FILA)
for g in range(num_grupos - 1):   # excluye el ultimo grupo
    fila_sep = fila_inicio_grupo[g + 1] - 1
    ws.row_dimensions[fila_sep].height = FILA_SEPARADOR_ALTO
```

### 5.4 Layout de la hoja "Por Vendedor"

La hoja se escribe secuencialmente hacia abajo. Para cada marca:

```
[Ult. Actualizacion]     <- solo en la fila 1, antes del primer bloque

[TITULO MARCA]           <- negrita, fondo burdeo A92C1F, texto blanco
[Vendedor] [Sucursal] [Cobertura] [Objetivo] [Faltante] [%]   <- encabezado
[datos vendedor 1]
[datos vendedor 2]
...
[fila vacia]             <- separador entre marcas
```

El formato condicional de `%` se aplica al rango de filas de datos de cada bloque.

### 5.5 API / Interfaz

#### Firma de los metodos privados nuevos

```python
def _escribir_hoja_sucursales(
    self,
    ws,                               # openpyxl Worksheet
    tablas: list[tuple[str, pd.DataFrame]],  # [(marca, df_suc), ...]
    ultima_fecha: date | None,
) -> None:
    """Escribe la grilla de tablas de sucursales en la hoja 'Sucursales'."""

def _escribir_hoja_vendedores(
    self,
    ws,                               # openpyxl Worksheet
    tablas: list[tuple[str, pd.DataFrame]],  # [(marca, df_vend), ...]
    ultima_fecha: date | None,
) -> None:
    """Escribe los bloques de vendedores apilados en la hoja 'Por Vendedor'."""
```

#### Anchos de columna para la hoja "Sucursales"

Los anchos se aplican a nivel de columna de worksheet. Dado que cada tabla ocupa las mismas 5 columnas relativas (Sucursal, Cobertura, Objetivo, Faltante, %), los anchos se repiten por cada grupo de 6 columnas (5 de datos + 1 separadora):

```python
ANCHOS_TABLA = [25, 12, 12, 12, 10]   # Sucursal, Cobertura, Objetivo, Faltante, %

for col_grupo in range(MARCAS_POR_FILA):
    col_base = 1 + col_grupo * (COLS_POR_TABLA + 1)
    for offset, ancho in enumerate(ANCHOS_TABLA):
        ws.column_dimensions[get_column_letter(col_base + offset)].width = ancho
    # columna separadora
    ws.column_dimensions[get_column_letter(col_base + COLS_POR_TABLA)].width = COL_SEPARADOR_ANCHO
```

#### Formato condicional en hoja "Sucursales"

```python
# col_pct = col_inicio + 4  (columna E relativa = columna % de esa tabla)
col_pct_letter = get_column_letter(col_inicio + 4)
first_row = fila_inicio + 2   # primera fila de datos (despues de titulo y encabezado)
last_row  = fila_inicio + 1 + len(df_suc)
# Solo aplicar formato condicional si hay filas de datos (first_row <= last_row)
if len(df_suc) > 0:
    _aplicar_formato_condicional(ws, col_pct_letter, first_row, last_row)
```

La funcion `_aplicar_formato_condicional` ya existe en `service.py` y no cambia.

#### Formato numerico de celdas

Dado que `ExcelWriter` se bypassa, los formatos numericos deben aplicarse directamente a cada celda:

```python
# Para cada celda de datos en la columna %:
cell.number_format = "0.00%"

# Para cada celda de datos en columnas Cobertura, Objetivo, Faltante:
cell.number_format = "#,##0"
```

Esto aplica a ambas hojas ("Sucursales" y "Por Vendedor").

#### Estilo de celdas

Se reutilizan las constantes de color ya definidas en `service.py`:

```python
_FILL_GREEN   # C6EFCE
_FILL_YELLOW  # FFEB9C
_FILL_RED     # FFC7CE
HEADER_FILL = PatternFill(start_color="A92C1F", end_color="A92C1F", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITULO_FILL = PatternFill(start_color="A92C1F", end_color="A92C1F", fill_type="solid")
TITULO_FONT = Font(bold=True, color="FFFFFF")
DATA_FONT   = Font(bold=True)
```

La fila de titulo de marca usa `merge_cells` para cubrir las 5 columnas de la tabla:

```python
ws.merge_cells(
    start_row=fila_inicio, start_column=col_inicio,
    end_row=fila_inicio,   end_column=col_inicio + COLS_POR_TABLA - 1
)
cell_titulo = ws.cell(row=fila_inicio, column=col_inicio, value=marca)
cell_titulo.fill = TITULO_FILL
cell_titulo.font = TITULO_FONT
cell_titulo.alignment = Alignment(horizontal="center", vertical="center")
```

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|------|------------------------|
| 1 marca | Hoja "Sucursales" con una sola tabla en la posicion (fila_grupo=0, col_grupo=0) |
| 4 marcas | Una sola fila de tablas, sin fila separadora debajo |
| 5 marcas | Primera fila con 4 tablas, segunda fila con 1 tabla; fila separadora entre filas de tablas |
| 8 marcas | Dos filas de 4 tablas; una fila separadora entre ellas |
| Marcas con distinto numero de sucursales en el mismo grupo | La altura de la fila de tablas la determina la marca con mas sucursales; las tablas mas cortas dejan celdas vacias debajo |
| Marca sin datos de cobertura (BD falla) | `df_suc` vacio (0 filas de datos); se renderiza titulo + encabezado sin filas de datos; el espacio de ese grupo se calcula con 0 filas de datos para esa marca |
| Marca sin vendedores | En la hoja "Por Vendedor", el bloque de esa marca tiene titulo + encabezado pero 0 filas de datos |
| `marcas = []` | Error descriptivo, no se genera archivo (RF-002) |
| `periodo` con dia distinto de 1 | Normalizar al primer dia del mes con warning, igual que hoy |
| `CASA CENTRAL` en cobertura | `aplicar_zonas_virtuales` divide en CASA CENTRAL y VALLE SALTA; ambas aparecen como filas en las tablas |
| Nombre de marca muy largo | No hay truncado en nombres de tabla (no son hojas); el titulo usa `merge_cells` y puede mostrar el nombre completo con `wrap_text=False` |
| Mas de 8 marcas | El sistema debe soportar N marcas arbitrario; la grilla sigue el patron `ceil(N/4)` filas de tablas |
| Formato condicional en hoja "Sucursales" | Cada tabla tiene su propio rango de CF independiente; no se solapan rangos entre tablas |
| `ultima_fecha = None` (BD falla) | Se omite la fila `Ult. Actualizacion`; la grilla comienza en fila 1 |

## 7. Plan de Testing

### Unitarios (sin BD, con mocks)

- [ ] **Test RF-001**: `test_hojas_generadas_son_sucursales_y_por_vendedor` — verifica que el workbook generado tiene exactamente dos hojas con los nombres "Sucursales" y "Por Vendedor" en ese orden. Valida RF-001.

- [ ] **Test RF-003**: `test_nombre_archivo_sin_cambio` — verifica que el nombre del archivo sigue siendo `Mision Posible 03-2026.xlsx`. Valida RF-003.

- [ ] **Test RF-004**: `test_resumen_ult_actualizacion_en_fila_1` — con `ultima_fecha=date(2026, 3, 6)`, verifica que la celda A1 de la hoja "Sucursales" contiene "Ult. Actualizacion" y B1 contiene "06/03/2026". Valida RF-004.

- [ ] **Test RF-005/RF-007**: `test_primera_tabla_en_posicion_correcta` — con 1 marca, verifica que la fila de titulo de la marca esta en la fila 3 (fila 1=resumen, fila 2=vacia), columna 1. Valida RF-005, RF-007.

- [ ] **Test RF-005/RF-007**: `test_segunda_tabla_en_columna_correcta` — con 2 marcas, verifica que el titulo de la segunda tabla esta en fila 3, columna 7 (1 + 1*6). Valida RF-005, RF-007.

- [ ] **Test RF-006**: `test_quinta_marca_inicia_nueva_fila_de_tablas` — con 5 marcas, verifica que el titulo de la quinta tabla esta en una fila mayor a la de las primeras 4 tablas (nueva fila de tablas). Valida RF-006.

- [ ] **Test RF-006**: `test_fila_separadora_tiene_altura_reducida` — con 5 marcas, verifica que la fila entre el primer y segundo grupo de tablas tiene `height = 6`. Valida RF-006.

- [ ] **Test RF-007**: `test_titulo_marca_mergeado` — verifica que la celda de titulo tiene `merge_cells` cubriendo las 5 columnas de la tabla. Valida RF-007.

- [ ] **Test RF-008**: `test_columna_separadora_tiene_ancho_reducido` — verifica que la columna 6 (primera columna separadora) tiene ancho = 2. Valida RF-008.

- [ ] **Test RF-009**: `test_formato_condicional_en_columna_pct` — con 2 marcas y datos de sucursales, verifica que el worksheet tiene reglas de formato condicional tanto en columna E (primera tabla) como en columna K (segunda tabla, col_inicio=7+4=11) para los rangos correctos de filas de datos. Valida RF-009.

- [ ] **Test RF-011/RF-012**: `test_hoja_por_vendedor_contiene_bloques_por_marca` — con 2 marcas y datos de vendedores, verifica que la hoja "Por Vendedor" tiene los nombres de ambas marcas como titulos, con filas de datos de vendedores debajo de cada uno. Valida RF-011, RF-012.

- [ ] **Test RF-013**: `test_formato_condicional_en_por_vendedor` — verifica que la hoja "Por Vendedor" tiene reglas de CF en la columna `%` para el rango de datos de cada bloque de vendedores. Valida RF-013.

- [ ] **Test RF-017**: `test_result_hojas_son_sucursales_y_por_vendedor` — verifica que `MisionPosibleResult.hojas == ["Sucursales", "Por Vendedor"]`. Valida RF-017.

- [ ] **Test RF-014**: `test_ult_actualizacion_en_hoja_por_vendedor` — verifica que la celda A1 de la hoja "Por Vendedor" contiene "Ult. Actualizacion" y B1 contiene la fecha. Valida RF-014.

- [ ] **Test RF-016**: `test_modo_supervisores_genera_dos_hojas_por_archivo` — con 2 supervisores, verifica que cada archivo generado tiene las hojas "Sucursales" y "Por Vendedor". Valida RF-016.

- [ ] **Test borde**: `test_marca_sin_datos_renderiza_encabezado_sin_filas` — con `df_suc` vacio para una marca, verifica que el titulo y encabezado se escriben pero no hay filas de datos. Valida edge case de marca sin cobertura.

- [ ] **Test borde**: `test_calculo_fila_inicio_con_marcas_de_distintos_tamaños` — con 5 marcas donde la primera tiene mas sucursales que las otras, verifica que la segunda fila de tablas empieza en la fila correcta (determinada por la marca con mas sucursales del grupo 1). Valida RF-006.

## 8. Tareas de Implementacion

**Tarea 1 — Implementar `_escribir_hoja_sucursales` en `service.py`**

Implementar el metodo privado que escribe la grilla de tablas de sucursales directamente con `openpyxl`. Incluye: calculo de posiciones (fila/columna de inicio por tabla), escritura de fila resumen, escritura de titulo de marca con `merge_cells`, escritura de encabezado y filas de datos, aplicacion de formato condicional por tabla, configuracion de anchos de columna y alturas de fila separadora.

- Archivos: `src/services/mision_posible/service.py`
- Sin dependencias externas nuevas

**Tarea 2 — Implementar `_escribir_hoja_vendedores` en `service.py`**

Implementar el metodo privado que escribe los bloques de vendedores apilados verticalmente. Incluye: escritura de `Ult. Actualizacion` en fila 1, escritura de titulo por marca, escritura de encabezado y filas de datos, fila vacia separadora entre marcas, formato condicional en columna `%` de cada bloque.

- Archivos: `src/services/mision_posible/service.py`
- Sin dependencias externas nuevas

**Tarea 3 — Actualizar `generar_reporte` y `generar_reporte_supervisores` en `service.py`**

Reemplazar el loop actual `for marca in config.marcas: writer.add_sheet(...)` por:

1. Construir listas `tablas_suc: list[tuple[str, DataFrame]]` y `tablas_vend: list[tuple[str, DataFrame]]` iterando por marca.
2. Crear `wb = Workbook()` directamente (sin `ExcelWriter`).
3. Llamar a `_escribir_hoja_sucursales(wb.active, tablas_suc, ultima_fecha)`.
4. Llamar a `_escribir_hoja_vendedores(wb.create_sheet("Por Vendedor"), tablas_vend, ultima_fecha)`.
5. Guardar el workbook en `DATA_OUTPUT`.
6. Actualizar `MisionPosibleResult.hojas = ["Sucursales", "Por Vendedor"]`.

Aplicar el mismo patron en `generar_reporte_supervisores`.

- Archivos: `src/services/mision_posible/service.py`
- Depende de: Tarea 1, Tarea 2

**Tarea 4 — Actualizar tests**

Actualizar `tests/test_mision_posible.py`:

Tests existentes a **eliminar** (ya no aplican porque el servicio no usa `ExcelWriter`):
- `test_nombre_hoja_truncado_31_chars` — ya no hay hojas por marca, las hojas tienen nombres fijos
- `test_hojas_por_marca_en_orden` — reemplazado por `test_hojas_generadas_son_sucursales_y_por_vendedor`
- `test_ultima_actualizacion_en_summary_rows` — reemplazado por `test_resumen_ult_actualizacion_en_fila_1`

Tests existentes a **adaptar** (dejar de mockear `ExcelWriter`, usar `Workbook` real en memoria):
- `test_nombre_archivo_formato_mes_anio` — verificar nombre del archivo guardado
- `test_nombre_archivo_custom` — verificar nombre custom
- `test_zonas_virtuales_aplicadas_a_cobertura` — verificar que datos post-zonas aparecen en las celdas
- `test_modo_supervisores_genera_un_archivo_por_supervisor` — verificar que genera N archivos
- `test_modo_supervisores_una_sola_consulta` — verificar una sola llamada a BD
- `test_consulta_bd_falla_genera_hojas_vacias` — verificar que no crashea

Agregar todos los tests nuevos del Plan de Testing (seccion 7). Los tests del servicio deben usar un `Workbook` real en memoria (patching `wb.save` para evitar I/O) en lugar de mockear `ExcelWriter`.

- Archivos: `tests/test_mision_posible.py`
- Depende de: Tarea 3

## 9. Boundaries (Lo que NO hacer)

- NO modificar `ExcelWriter`, `_write_sheet`, `SheetStyle` ni ninguna clase de `src/core/excel_writer.py`.
- NO modificar `processor.py`; las funciones `procesar_cobertura_sucursal`, `procesar_cobertura_vendedor` y `concatenar_tablas` no cambian.
- NO agregar una tercera hoja ni mas hojas al archivo.
- NO cambiar la logica de calculo de cobertura, objetivos, faltantes o porcentajes.
- NO cambiar el nombre del archivo ni la logica de `_nombre_reporte`.
- NO cambiar el subcomando CLI ni los endpoints de la API (solo cambia lo que generan internamente).
- NO soportar un numero de columnas por fila distinto de 4 como constante hardcodeada; si en el futuro se quiere configurable, sera otra spec.
- NO poner tablas de vendedores en la hoja "Sucursales".

## 10. Decisiones Resueltas

- [x] **Decision A**: Hoja "Por Vendedor" contiene **solo vendedores** (sin tabla de sucursales). No se usa `concatenar_tablas`. Se escribe directamente `procesar_cobertura_vendedor` por marca.

- [x] **Decision B**: Titulo de marca en la grilla de "Sucursales" usa **burdeo `A92C1F`** con texto blanco (mismo estilo que encabezados de columna).

- [x] **Decision C**: Titulo de marca en "Por Vendedor" usa **el mismo estilo burdeo** que en la hoja Sucursales (consistencia visual).
