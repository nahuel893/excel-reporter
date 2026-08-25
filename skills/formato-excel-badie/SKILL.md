---
name: formato-excel-badie
description: "Colores, formatos numéricos y convenciones visuales de los informes Excel de Distribuidora Badie. Define la paleta por rol semántico (encabezado, subtotal, TOTAL GENERAL, alerta, dato faltante), los number_format por tipo de medida (bultos, hectolitros, pesos, porcentajes, cobertura) — SIEMPRE sin decimales —, los bordes (OBLIGATORIOS en toda celda de la tabla), y las reglas que no se negocian: nunca redondear el dato, siempre fila de totales, el porcentaje se guarda como fracción. Usar al crear un servicio nuevo que genere Excel, al agregar hojas o columnas a uno existente, al revisar por qué un informe se ve distinto de los demás, o cuando pidan cambiar colores, formatos o el aspecto de un reporte."
version: 1.0.0
metadata:
  hermes:
    tags: [badie, excel, formato, estilo, reporting, openpyxl]
---

# Formato de los Excel — Distribuidora Badie

Los informes los lee gente que abre diez por día. Si cada uno pinta el TOTAL de
un color distinto, hay que releer la leyenda cada vez. Esta skill fija los roles.

**Antes de inventar un color, buscá el rol.** La paleta es chica a propósito.

---

## 1. Paleta por rol semántico

El color no describe una fila, describe **qué es** esa fila.

| Rol | Hex | Se ve como | Cuándo |
|---|---|---|---|
| Encabezado de columna | `2E75B6` | azul medio | fila de títulos, con fuente `FFFFFF` en negrita |
| Encabezado oscuro | `1F4E78` | azul oscuro | igual, cuando el informe ya usa azul medio para otra cosa |
| Encabezado navy | `1F3864` | navy | histórico-cliente, que además lo usa para el gran total |
| Banda de agrupación | `DDEBF7` | celeste claro | cabecera de sucursal, de zona, de bloque |
| Subtotal | `D9E1F2` / `D9E2F3` | celeste | subtotal de grupo (por sucursal, por genérico, por ruta) |
| Subtotal de bloque | `FFF2CC` | crema | el total de un bloque intermedio (ej. TOTAL AGUAS de una sucursal) |
| **TOTAL GENERAL** | `FFE08A` | **ámbar** | la fila de totales del informe. **Siempre este.** |
| Fila destacada | `FFFF00` | amarillo | agregados que no hay que sumar dos veces (apertura de rutas) |
| Alerta / error | `FFC7CE` | rosa | supuestos rotos: artículo sin factor, lista de precios vencida |
| Bien / cumple | `C6EFCE` | verde | semáforos que llegan al objetivo |
| Mal / no cumple | `F8696B` | rojo | semáforos que no llegan |
| Neutro / apagado | `F2F2F2` | gris | filas de contexto que no son dato propio |
| Dato faltante | `F4F6FA` + fuente `A3B0C4` | gris muy claro | marca que el cliente NO compró: es información, no un hueco |
| Zebra | `F7F9FC` | casi blanco | bandeado alterno en tablas largas |

**Fuente del semáforo**: SIEMPRE `000000` (negra), sobre cualquiera de los
rellenos de semáforo. El relleno ya dice si está bien o mal; teñir además la
fuente baja el contraste y se lee peor, sobre todo en las capturas de WhatsApp.
Nada de `006100` / `9C0006` / `9C5700`, que son los que pone Excel por defecto.

**Fuente sobre relleno oscuro**: `FFFFFF` en negrita.
**Fuente de subtítulo**: `546E7A` o `7F7F7F`, itálica, tamaño 10.

## 2. ⛔ Bordes — SIEMPRE en TODAS las celdas de la tabla

**Toda celda que forma parte de una tabla lleva borde, sin excepción:**
encabezados, filas de datos, subtotales, TOTAL GENERAL y bandas de agrupación.

`Side(style="thin", color="D9D9D9")` en todas las celdas. Para tablas más
densas se usa `B0B0B0` o `BFBFBF`; elegí uno y mantenelo en todo el archivo.

No dejar ninguna celda de la tabla sin `border`: una tabla con celdas sueltas
sin borde se ve rota y no es un informe Badie.

## 3. ⛔ Formatos numéricos por tipo de medida — SIEMPRE sin decimales

**Regla: ninguna celda numérica muestra decimales.** El `number_format` de
todas las medidas usa `#,##0` (o `$ #,##0` para plata). La celda guarda el
valor completo con su precisión (NUNCA se redondea el dato, ver §4.1); el
formato solo decide cómo se **muestra**, y se muestra sin decimales.

| Medida | `number_format` | Por qué |
|---|---|---|
| Bultos | `#,##0` | se leen enteros aunque el dato tenga decimales |
| Bultos con detalle | `#,##0` | **sin decimales** — la fracción de caja no se muestra |
| Hectolitros | `#,##0` | **sin decimales** |
| Kilos | `#,##0` | **sin decimales** |
| Pesos | `$ #,##0` | sin decimales: son millones, los centavos son ruido |
| Porcentaje | `0.0%` | **se guarda como fracción** (0.421), no como 42.1 |
| Cobertura / clientes | `#,##0` | son conteos enteros |
| Cupos y objetivos | `#,##0` | |
| Códigos numéricos | `0` | id_ruta, id_cliente: **nunca** formato de fecha (ver §6) |

⚠️ Si un número necesita decimales para que el negocio lo entienda (ej. un
precio unitario chico), se declara la excepción en el subtítulo del informe —
pero la regla general es sin decimales.

## 4. Las tres reglas que no se negocian

### 4.1 Nunca redondear el dato

`int()`, `round()` y `astype(int)` están prohibidos sobre valores del informe.
La celda guarda `1349.587090` y el `number_format` la muestra como `1.350`.

Si redondeás en Python o con `ROUND()` en SQL, la suma de las filas deja de
cerrar con el total y alguien va a pasar media hora buscando el error.

Excepción: `Decimal(...).quantize(..., rounding=ROUND_HALF_UP)` cuando el
negocio pide un entero redondeado (un objetivo, un cupo). Ojo que el `round()`
de Python es bancario: `round(2.5)` da **2**, y Excel da 3.

### 4.2 Todo informe lleva fila de totales

Etiqueta `TOTAL GENERAL`, relleno `FFE08A`, negrita.

Pero **cuidado con qué se suma**:

- Bultos, hectolitros, kilos y pesos: se suman.
- **Cobertura NO se suma** entre marcas, genéricos, calibres ni meses. El total
  es el conteo de clientes distintos sobre el corte completo. Sí se suma entre
  rutas, preventistas y sucursales.

Nunca imprimas una suma de coberturas "con una aclaración al lado": el número
se recorta de la imagen y la aclaración queda atrás.

### 4.3 El porcentaje se guarda como fracción

`ws.cell(r, c, 0.4218).number_format = "0.0%"` → se ve `42,2%`.

Guardar `42.18` con formato `0.0%` muestra `4218,0%`.

## 5. Estructura de la hoja

```
A1  Título del informe            negrita, tamaño 14
A2  Subtítulo con el CRITERIO     itálica, 10, color 546E7A
A4  Encabezados de columna        relleno azul, fuente blanca
A5+ Datos
    TOTAL GENERAL                 relleno ámbar
```

El **subtítulo es obligatorio** y tiene que decir cómo se calculó lo que se
muestra: el corte, el umbral, la ventana. Ejemplo real:

> `Cobertura = clientes distintos con compra neta > 0 en el corte | Corte al
> 2026-08-10 | Padron = dim_cliente no anulados | Los grupos son la UNION de
> sus marcas, no la suma`

Sin eso, cada lectura del informe genera una pregunta.

Ancho de columnas: la de etiquetas entre 24 y 44, las numéricas entre 11 y 15.
`ws.freeze_panes` en la primera fila de datos y `ws.auto_filter` sobre el rango.

## 6. Gotchas que ya nos mordieron

**Clave numérica con formato de fecha.** Una columna de join (`id_ruta`) guardada
con `number_format` de fecha se corrompe en el round-trip de openpyxl por el bug
del año bisiesto 1900: los seriales ≥ 60 se corren un día y el VLOOKUP falla
**solo en las imágenes**, no en el xlsx crudo. Forzá `"0"` en las claves.

**Celdas combinadas que recortan texto.** LibreOffice corta el texto que no entra
en un `merge_cells`; una celda suelta lo desborda sobre las vecinas vacías. Para
notas al pie, no combines.

**Etiquetas de datos en gráficos.** Si no apagás `showSerName` y `showCatName`
explícitamente, LibreOffice imprime `Ene; STA; 519` en vez de `519`.

**Ejes con escalas distintas.** En un combinado de barras y líneas, fijá el mismo
`scaling.min`, `scaling.max` y `majorUnit` en los dos ejes. Si cada uno se
autoescala, una barra y una línea a la misma altura valen números distintos y el
gráfico miente a simple vista.

**Aritmética de posiciones para decidir formatos.** No hagas
`if j in (col_acum + 1, n_cols)`. Declará cada columna con su formato al lado del
nombre; meter una columna al medio corre los porcentajes en silencio.

**Ancho de página en las capturas.** Si el informe se fotografía, poné
`page_setup.orientation = "landscape"` y `fitToWidth = 1`, o el render corta las
últimas columnas.

## 7. El helper compartido

`src/core/excel_writer.py` tiene `ExcelWriter` + `SheetStyle` para las tablas
simples: `numeric_format`, `column_formats`, `column_groups` colapsables,
`summary_rows` y tabla nativa de Excel (`as_table`, `TableStyleMedium9`).

Los informes con bloques, subtotales por grupo o layout de matriz se escriben
con openpyxl directo. En ese caso definí los colores como constantes con nombre
arriba del módulo, con un comentario de qué rol cumple cada una:

```python
HEADER_FILL = "2E75B6"
SUC_FILL = "DDEBF7"      # cabecera de cada sucursal
GRUPO_FILL = "F2F2F2"    # AGUA MINERAL / AGUA SABORIZADA
TOTAL_GRAL_FILL = "FFE08A"  # TOTAL GENERAL
```

Nunca un hex suelto en medio del código: en seis meses nadie sabe si `D9E1F2`
era un subtotal o una banda.
