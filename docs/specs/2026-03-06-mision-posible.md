# Spec: Mision Posible

> **Estado:** IMPLEMENTADA
> **Fecha:** 2026-03-06
> **Autor:** nahuel

## 1. Objetivo

Generar un reporte Excel de cobertura llamado "Mision Posible" que muestra, por cada marca configurada, cuantos clientes compraron (cobertura real), cuantos deberian comprar (objetivo), la diferencia (faltante) y el porcentaje de cumplimiento — tanto a nivel sucursal como a nivel vendedor.

---

## 2. Contexto

Los supervisores necesitan un informe periodico de cobertura de clientes por marca que responda rapidamente: "cuantos clientes activos tenemos vs cuantos deberiamos tener". Las tablas `cob_preventista_marca` y `cob_sucursal_marca` ya contienen los datos de cobertura pre-calculados por mes. Los objetivos no existen en la base de datos y deben configurarse manualmente en el JSON de entrada. El reporte inicial cubre tres marcas: Imperial, Levite y Villa del Sur.

---

## 3. Requisitos Funcionales

### 3.1 Generacion del archivo

- **RF-001**: Cuando el usuario invoca el reporte con `periodo` y `marcas`, el sistema debe generar un unico archivo Excel en `data/output/` con el nombre `Mision Posible {MM-YYYY}.xlsx`, donde `MM-YYYY` corresponde al mes del periodo configurado.

- **RF-002**: Cuando `nombre_archivo` es provisto en la configuracion, el sistema debe usar ese nombre en lugar del nombre generado automaticamente.

- **RF-003**: Cuando el archivo es generado, el sistema debe crear una hoja por cada marca presente en `marcas`, nombrada exactamente con el nombre de la marca (ej: `Imperial`, `Levite`). El orden de las hojas debe respetar el orden de la lista `marcas` en la configuracion.

- **RF-004**: Si `marcas` es una lista vacia o `None`, el sistema debe retornar un error descriptivo y no generar archivo.

### 3.2 Estructura de cada hoja

- **RF-005**: Cuando se genera una hoja de marca, el sistema debe producir dos tablas separadas verticalmente: primero la tabla por sucursal (Tabla Sucursal) y luego la tabla por vendedor (Tabla Vendedor), separadas por una fila vacia entre ellas.

- **RF-006**: Cuando se genera la Tabla Sucursal, el sistema debe producir las siguientes columnas en este orden exacto:

  | # | Nombre | Tipo |
  |---|--------|------|
  | 1 | `Sucursal` | texto |
  | 2 | `Cobertura` | entero |
  | 3 | `Objetivo` | entero o vacio |
  | 4 | `Faltante` | entero (puede ser negativo) |
  | 5 | `%` | decimal (porcentaje) o vacio |

- **RF-007**: Cuando se genera la Tabla Vendedor, el sistema debe producir las siguientes columnas en este orden exacto:

  | # | Nombre | Tipo |
  |---|--------|------|
  | 1 | `Vendedor` | texto |
  | 2 | `Sucursal` | texto |
  | 3 | `Cobertura` | entero |
  | 4 | `Objetivo` | entero o vacio |
  | 5 | `Faltante` | entero (puede ser negativo) |
  | 6 | `%` | decimal (porcentaje) o vacio |

### 3.3 Calculo de columnas

- **RF-008**: Cuando se calcula `Cobertura` para una sucursal, el sistema debe obtener `clientes_compradores` de la tabla `cob_preventista_marca` para el periodo y la marca dados, aplicar zonas virtuales, agrupar por sucursal y sumar `clientes_compradores`. No se debe usar `cob_sucursal_marca` directamente porque no tiene `id_ruta` y no soporta split de zonas virtuales.

- **RF-009**: Cuando se calcula `Cobertura` para un vendedor, el sistema debe obtener `clientes_compradores` de `cob_preventista_marca` para el periodo, la marca y el vendedor dados, aplicar zonas virtuales, y mostrar el valor por fila de vendedor.

- **RF-010**: Cuando se calcula `Objetivo` para una sucursal, el sistema debe:
  1. Buscar `objetivos[marca]["total"]` (objetivo empresa para esa marca).
  2. Buscar `porcentajes_sucursal[nombre_sucursal]` (porcentaje asignado a esa sucursal).
  3. Calcular `Objetivo = round(total * porcentaje / 100)`.
  4. Si `total` no existe para esa marca, o la sucursal no tiene porcentaje asignado, la celda queda vacia (`None`).

- **RF-011**: Cuando se calcula `Objetivo` para un vendedor, el sistema debe:
  1. Obtener el objetivo de la sucursal del vendedor (calculado segun RF-010).
  2. Contar la cantidad de vendedores con cobertura en esa sucursal para esa marca.
  3. Calcular `Objetivo = round(objetivo_sucursal / cantidad_vendedores)`.
  4. Si el objetivo de la sucursal es `None`, el objetivo del vendedor tambien es `None`.

- **RF-012**: Cuando se calcula `Faltante`, el sistema debe computar `Objetivo - Cobertura`. Si `Objetivo` es `None`, `Faltante` debe ser `None`.

- **RF-013**: Cuando se calcula `%`, el sistema debe computar `round(Cobertura / Objetivo * 100, 1)`. Si `Objetivo` es `None` o `0`, la celda debe quedar vacia (`None`).

- **RF-023**: Cuando se genera el archivo, el sistema debe incluir como `summary_row` (fila de resumen debajo de la tabla, via `SheetStyle.summary_rows`) el dato `Ult. Actualizacion: {fecha}` donde `{fecha}` es el `MAX(fecha_comprobante)` global de `fact_ventas` (sin filtros de marca/sucursal). Este dato sirve como control de que la base de datos se esta actualizando.

### 3.4 Filas de la tabla

- **RF-014**: Cuando se construye la Tabla Sucursal, el sistema debe incluir una fila por cada sucursal que tenga porcentaje asignado en `porcentajes_sucursal`, incluso si no tienen datos de cobertura (en ese caso `Cobertura = 0`, `Ult. Venta = None`). Las filas se ordenan alfabeticamente por nombre de sucursal.

- **RF-015**: Cuando se construye la Tabla Vendedor, el sistema debe incluir una fila por cada vendedor que tenga datos de cobertura para esa marca en el periodo. Las filas se ordenan primero por `Sucursal` (alfabetico ascendente) y luego por `Vendedor` (alfabetico ascendente dentro de cada sucursal).

### 3.5 Zonas virtuales

- **RF-016**: Cuando se procesan datos de cobertura de `CASA CENTRAL`, el sistema debe aplicar `aplicar_zonas_virtuales()` de `src/core/zonas.py` al DataFrame de `cob_preventista_marca` antes de agrupar, de modo que las filas con `id_ruta` en el rango de VALLE SALTA queden asignadas a esa zona virtual tanto en la Tabla Sucursal como en la Tabla Vendedor.

### 3.6 Filtro por supervisor

- **RF-017**: Cuando `supervisores` esta presente en la configuracion, el sistema debe generar un archivo Excel separado por cada supervisor, filtrando los datos de cobertura a las sucursales asignadas a ese supervisor (incluyendo zonas virtuales expandidas via `expandir_sucursales()`). El nombre del archivo debe ser `Mision Posible {supervisor} {MM-YYYY}.xlsx`.

- **RF-018**: Cuando se genera en modo supervisores, el sistema debe realizar una sola consulta a la base de datos y luego particionar los datos en memoria por supervisor, igual que `VentasService.generar_reporte_supervisores`.

### 3.7 CLI

- **RF-019**: Cuando el usuario ejecuta `python main.py mision-posible --config config_mision_posible.json`, el sistema debe leer la configuracion del JSON y generar el/los archivo/s correspondientes.

- **RF-020**: Mientras el subcomando `mision-posible` se ejecuta, el sistema debe aceptar los parametros individuales `--periodo` (formato `YYYY-MM-DD`, primer dia del mes), `--marcas` (separadas por coma) y `--output`.

### 3.8 API REST

- **RF-021**: Cuando se realiza `POST /mision-posible/reporte`, el sistema debe generar el reporte y retornar metadata con: `ruta_archivos` (lista de paths), `marcas_incluidas`, `hojas`.

- **RF-022**: Cuando se realiza `POST /mision-posible/reporte/download`, el sistema debe retornar el archivo `.xlsx` como descarga directa si hay un solo archivo, o un `.zip` si hay multiples archivos (modo supervisores).

---

## 4. Requisitos No Funcionales

- **RNF-001**: La generacion del reporte para 3 marcas y todas las sucursales debe completarse en menos de 15 segundos con conexion normal a la base de datos.

- **RNF-002**: El servicio debe aceptar `DataLoader` inyectable para permitir tests unitarios con mocks, siguiendo el patron de `VentasService`.

- **RNF-003**: Si la consulta a `cob_preventista_marca` falla por cualquier razon, el sistema debe capturar la excepcion, generar el archivo con la columna `Cobertura` en blanco para esa marca y continuar sin propagar el error.

- **RNF-004**: El archivo generado debe poder abrirse en Excel y LibreOffice sin errores de formato.

- **RNF-005**: La logica de zonas virtuales debe reutilizar `aplicar_zonas_virtuales()` y `expandir_sucursales()` de `src/core/zonas.py` sin duplicacion.

---

## 5. Diseno Tecnico

### 5.1 Modelo de Datos

No se crean tablas nuevas. Las fuentes de datos son:

**Consulta principal — Cobertura por vendedor y marca**

Metodo existente: `get_cobertura_preventista_marca(periodo_desde, periodo_hasta, periodos, sucursales)`

Columnas retornadas: `periodo`, `sucursal`, `id_vendedor`, `vendedor`, `id_ruta`, `marca`, `clientes_compradores`, `volumen_total`

Para este reporte se invoca con `periodos=[periodo]` (lista de un solo elemento, el primer dia del mes configurado). No se necesitan metodos nuevos en `DataLoader`.

**Nota:** El metodo `get_cobertura_preventista_marca` no tiene parametro `marcas` — retorna datos de TODAS las marcas del periodo. El filtrado por marca se hace en memoria en el processor (`df[df["marca"] == marca]`). Esto es intencional: la consulta es una sola para todas las marcas, y el filtrado en Python es trivial.

**Obtencion de nombre del vendedor**

La columna `vendedor` viene del JOIN con `dim_vendedor.des_vendedor` dentro del metodo existente. No se requiere consulta adicional.

**Consulta adicional — Ultima fecha de venta global**

Nuevo metodo: `get_ultima_fecha_venta()`

```sql
SELECT MAX(fv.fecha_comprobante) AS ultima_venta
FROM gold.fact_ventas fv
```

Retorna una sola fecha. Se usa como dato de control en `summary_rows`. No requiere filtros ni zonas virtuales.

**Objetivos**

Los objetivos provienen exclusivamente de la configuracion JSON. No hay tabla en base de datos. El objetivo total empresa se reparte entre sucursales via `porcentajes_sucursal`, y luego entre vendedores en partes iguales.

### 5.2 Arquitectura

```
src/
  services/
    mision_posible/          NUEVO modulo
      __init__.py
      service.py             MisionPosibleService, MisionPosibleConfig, MisionPosibleResult
      processor.py           procesar_cobertura_sucursal(), procesar_cobertura_vendedor()
  api/
    routes/
      mision_posible.py      NUEVO: router FastAPI
    __init__.py              MODIFICADO: +mision_posible_router

main.py                      MODIFICADO: +subcomando mision-posible
api.py                       MODIFICADO: include_router(mision_posible_router), version bump
config_mision_posible.json   NUEVO: config de ejemplo
tests/
  test_mision_posible.py     NUEVO: tests unitarios
```

**Flujo de datos:**

```
main.py / API
    |
    v
MisionPosibleService.generar_reporte(config)
    |
    +-- data_loader.get_cobertura_preventista_marca(periodos=[config.periodo])
    |       --> df_cob_raw
    |
    +--> aplicar_zonas_virtuales(df_cob_raw)
    |       --> df_cob
    |
    +-- Para cada marca en config.marcas:
    |     |
    |     +--> processor.procesar_cobertura_sucursal(df_cob, marca, objetivos_marca)
    |     |       --> df_sucursal  (columnas: Sucursal, Cobertura, Objetivo, Faltante, %)
    |     |
    |     +--> processor.procesar_cobertura_vendedor(df_cob, marca, objetivos_marca)
    |             --> df_vendedor  (columnas: Vendedor, Sucursal, Cobertura, Objetivo, Faltante, %)
    |
    +--> ExcelWriter: una hoja por marca
         |
         +--> SheetStyle con dos rangos de tabla (sucursal arriba, vendedor abajo)
    |
    --> MisionPosibleResult
```

**Layout de dos tablas por hoja (Decision resuelta)**: El processor concatena `df_sucursal` + fila separadora (titulo "Por Vendedor") + `df_vendedor` en un solo DataFrame. Se escribe con `as_table=False` (sin formato de tabla Excel) para evitar modificar `ExcelWriter`. Los encabezados de cada seccion se distinguen visualmente porque la fila separadora actua como subtitulo. Las columnas de la Tabla Vendedor (`Vendedor`, `Sucursal`) se mapean a las mismas posiciones que la Tabla Sucursal rellenando con las columnas correctas. Alternativa futura: extender `ExcelWriter` con `start_row` para soportar multiples tablas formateadas.

### 5.3 API / Interfaz

#### Config dataclass

```python
@dataclass
class MisionPosibleConfig:
    periodo: str                          # "YYYY-MM-DD", primer dia del mes
    marcas: list[str]                     # ["Imperial", "Levite", "Villa del Sur"]
    objetivos: dict[str, int]             # {"Imperial": 500, "Levite": 300} — objetivo empresa por marca
    porcentajes_sucursal: dict[str, float] # {"CASA CENTRAL": 30, "SUCURSAL CAFAYATE": 15} — % de cada sucursal
    nombre_archivo: str | None = None
    supervisores: dict[str, list[str]] | None = None
```

Estructura de `objetivos` (objetivo total empresa por marca):

```python
{
    "Imperial": 500,       # 500 clientes objetivo para toda la empresa
    "Levite": 300,
    "Villa del Sur": 200
}
```

Estructura de `porcentajes_sucursal` (reparto fijo entre sucursales):

```python
{
    "CASA CENTRAL": 30,         # 30% del total
    "VALLE SALTA": 15,
    "SUCURSAL CAFAYATE": 10,
    "SUCURSAL METAN": 10,
    "SUCURSAL ABRA PAMPA": 10,
    "SUCURSAL PERICO": 10,
    "SUCURSAL TARTAGAL": 15
}
```

**Calculo de objetivos:**
- Objetivo sucursal = `round(objetivos[marca] * porcentajes_sucursal[sucursal] / 100)`
- Objetivo vendedor = `round(objetivo_sucursal / cant_vendedores_con_cobertura_en_sucursal)`
- Si la marca no esta en `objetivos`, todas las celdas Objetivo quedan vacias.
- Si la sucursal no esta en `porcentajes_sucursal`, Objetivo queda vacio para esa sucursal y sus vendedores.

#### Result dataclass

```python
@dataclass
class MisionPosibleResult:
    ruta_archivos: list[Path]     # uno o mas archivos generados
    marcas_incluidas: list[str]
    hojas: list[str]              # = marcas_incluidas
    supervisor: str | None = None # poblado en modo supervisores
```

#### Schema de la hoja Excel (por marca)

```
[Titulo opcional: nombre de marca - periodo]

Tabla Sucursal:
  Encabezado: Sucursal | Cobertura | Objetivo | Faltante | %
  Datos: una fila por sucursal

[fila vacia]

Tabla Vendedor:
  Encabezado: Vendedor | Sucursal | Cobertura | Objetivo | Faltante | %
  Datos: una fila por vendedor

[fila resumen]
  Ult. Actualizacion: dd/mm/yyyy
```

#### SheetStyle para Mision Posible

```python
SheetStyle(
    numeric_format="#,##0",
    column_formats={
        "Sucursal":    ColumnFormat(width=25),
        "Vendedor":    ColumnFormat(width=25),
        "Cobertura":   ColumnFormat(number_format="#,##0", width=12),
        "Objetivo":    ColumnFormat(number_format="#,##0", width=12),
        "Faltante":    ColumnFormat(number_format="#,##0", width=12),
        "%":           ColumnFormat(number_format="#,##0.0", width=10),
    },
    as_table=True,
    table_style="TableStyleMedium9"
)
```

#### Config JSON de ejemplo (config_mision_posible.json)

```json
{
    "periodo": "2026-03-01",
    "marcas": ["Imperial", "Levite", "Villa del Sur"],
    "objetivos": {
        "Imperial": 500,
        "Levite": 300,
        "Villa del Sur": 200
    },
    "porcentajes_sucursal": {
        "CASA CENTRAL": 30,
        "VALLE SALTA": 15,
        "SUCURSAL CAFAYATE": 10,
        "SUCURSAL METAN": 10,
        "SUCURSAL ABRA PAMPA": 10,
        "SUCURSAL PERICO": 10,
        "SUCURSAL TARTAGAL": 15
    },
    "nombre_archivo": null,
    "supervisores": null
}
```

#### Endpoint POST /mision-posible/reporte

Request body:
```json
{
  "periodo": "2026-03-01",
  "marcas": ["Imperial", "Levite", "Villa del Sur"],
  "objetivos": {"Imperial": 500, "Levite": 300, "Villa del Sur": 200},
  "porcentajes_sucursal": {"CASA CENTRAL": 30, "VALLE SALTA": 15, "SUCURSAL CAFAYATE": 10},
  "nombre_archivo": null,
  "supervisores": null
}
```

Response:
```json
{
  "ruta_archivos": ["data/output/Mision Posible 03-2026.xlsx"],
  "marcas_incluidas": ["Imperial", "Levite", "Villa del Sur"],
  "hojas": ["Imperial", "Levite", "Villa del Sur"]
}
```

#### Endpoint POST /mision-posible/reporte/download

Retorna el archivo `.xlsx` directamente (o `.zip` en modo supervisores):
```
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Content-Disposition: attachment; filename*=UTF-8''Mision%20Posible%2003-2026.xlsx
```

#### Subcomando CLI

```bash
# Con config JSON (recomendado)
python main.py mision-posible --config config_mision_posible.json

# Con args individuales
python main.py mision-posible --periodo 2026-03-01 --marcas "Imperial,Levite,Villa del Sur"
python main.py mision-posible --periodo 2026-03-01 --marcas "Imperial" --output "Mi Mision"
```

---

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|------|------------------------|
| Marca sin datos en `cob_preventista_marca` | Hoja generada con todas las sucursales de `porcentajes_sucursal` mostrando `Cobertura = 0`, `Ult. Venta = None` |
| `objetivos` no contiene una marca configurada | `Objetivo`, `Faltante` y `%` quedan vacias (`None`) para todas las filas de esa marca |
| Sucursal no esta en `porcentajes_sucursal` | `Objetivo = None`, `Faltante = None`, `%` = None para esa sucursal y sus vendedores |
| Sucursal en `porcentajes_sucursal` sin vendedores | Aparece en Tabla Sucursal con `Cobertura = 0`; no aparece en Tabla Vendedor |
| Vendedor objetivo con 0 vendedores en sucursal | No puede pasar: si no hay vendedores, no hay filas en Tabla Vendedor |
| `Objetivo = 0` | `Faltante = 0 - Cobertura` (negativo o cero); `%` = `None` (no dividir por cero) |
| `Objetivo > Cobertura` | `Faltante` es positivo (normal) |
| `Objetivo < Cobertura` | `Faltante` es negativo (supero el objetivo); se muestra el valor negativo tal cual |
| `marcas = []` o `None` | Error descriptivo, no se genera archivo |
| `periodo` con dia distinto de 1 | El sistema normaliza al primer dia del mes, imprime warning y continua |
| `CASA CENTRAL` en datos de cobertura | `aplicar_zonas_virtuales` divide en CASA CENTRAL y VALLE SALTA segun `id_ruta` |
| Supervisor con `CASA CENTRAL` en su lista | `expandir_sucursales` agrega automaticamente `VALLE SALTA`; ambas aparecen en su reporte |
| Vendedor en multiples sucursales | `id_vendedor` no es unico globalmente; la combinacion `(id_vendedor, id_sucursal)` es la clave. Se muestran filas separadas por sucursal |
| Consulta a BD falla | `df_cob_raw` queda vacio; tablas de esa marca quedan vacias; no se propaga el error |
| Nombre de marca mayor a 31 caracteres | Truncar a 31 caracteres antes de crear la hoja (limite de OpenPyXL) |
| Modo supervisores sin datos para un supervisor | Genera archivo vacio pero valido para ese supervisor |

---

## 7. Plan de Testing

### Unitarios (sin BD, con mocks)

- [ ] `test_nombre_archivo_formato_mes_anio` — verifica que el nombre generado sea `Mision Posible 03-2026.xlsx` para `periodo="2026-03-01"`. Valida RF-001.

- [ ] `test_nombre_archivo_custom` — con `nombre_archivo="Mi Mision"`, verifica que el archivo se llama `Mi Mision.xlsx`. Valida RF-002.

- [ ] `test_hojas_por_marca_en_orden` — dado `marcas=["Imperial", "Levite"]`, verifica que `ExcelWriter.add_sheet` es llamado con esos nombres en ese orden. Valida RF-003.

- [ ] `test_error_marcas_vacio` — con `marcas=[]`, verifica que el servicio lanza `ValueError` descriptivo y no llama a `DataLoader`. Valida RF-004.

- [ ] `test_columnas_tabla_sucursal` — verifica que `procesar_cobertura_sucursal` retorna un DataFrame con exactamente las columnas `[Sucursal, Cobertura, Objetivo, Faltante, %]` en ese orden. Valida RF-006.

- [ ] `test_columnas_tabla_vendedor` — verifica que `procesar_cobertura_vendedor` retorna un DataFrame con exactamente las columnas `[Vendedor, Sucursal, Cobertura, Objetivo, Faltante, %]` en ese orden. Valida RF-007.

- [ ] `test_cobertura_sucursal_agrupa_correctamente` — dado `df_cob` con dos filas para el mismo par `(sucursal, marca)` (dos vendedores), verifica que `procesar_cobertura_sucursal` suma los `clientes_compradores`. Valida RF-008.

- [ ] `test_objetivo_sucursal_calculo_porcentaje` — con `objetivos={"Imperial": 500}` y `porcentajes_sucursal={"CASA CENTRAL": 30, "SUCURSAL CAFAYATE": 10}`, verifica que CASA CENTRAL tiene `Objetivo=150` (500*30/100) y CAFAYATE tiene `Objetivo=50` (500*10/100). Valida RF-010.

- [ ] `test_objetivo_vendedor_reparto_igualitario` — con objetivo sucursal=150 y 3 vendedores en esa sucursal, verifica que cada vendedor tiene `Objetivo=50` (150/3). Valida RF-011.

- [ ] `test_objetivo_ausente_queda_none` — con `objetivos={}` (marca no configurada), verifica que `Objetivo`, `Faltante` y `%` son `None`. Valida RF-010, RF-011, RF-012, RF-013.

- [ ] `test_sucursal_sin_porcentaje_objetivo_none` — con sucursal presente en datos pero no en `porcentajes_sucursal`, verifica `Objetivo = None`. Valida RF-010.

- [ ] `test_todas_sucursales_presentes` — con `porcentajes_sucursal` teniendo 5 sucursales pero solo 3 con datos de cobertura, verifica que las 5 aparecen (2 con `Cobertura=0`). Valida RF-014.

- [ ] `test_faltante_negativo_cuando_supera_objetivo` — con `Cobertura=70, Objetivo=50`, verifica `Faltante=-20`. Valida RF-012.

- [ ] `test_porcentaje_none_cuando_objetivo_cero` — con `Objetivo=0`, verifica `%=None`. Valida RF-013.

- [ ] `test_porcentaje_calculado_correctamente` — con `Cobertura=45, Objetivo=60`, verifica `%=75.0`. Valida RF-013.

- [ ] `test_orden_filas_sucursal` — dado DataFrame desordenado, verifica filas de Tabla Sucursal ordenadas alfabeticamente por Sucursal. Valida RF-014.

- [ ] `test_orden_filas_vendedor` — dado DataFrame desordenado, verifica filas de Tabla Vendedor ordenadas por Sucursal luego por Vendedor. Valida RF-015.

- [ ] `test_zonas_virtuales_aplicadas_a_cobertura` — dado `df_cob_raw` con `id_ruta=81` y `sucursal="CASA CENTRAL"`, verifica que despues de `aplicar_zonas_virtuales` la fila tiene `sucursal="VALLE SALTA"`. Valida RF-016.

- [ ] `test_modo_supervisores_genera_un_archivo_por_supervisor` — con `supervisores={"Ana": ["CASA CENTRAL"], "Luis": ["SUCURSAL CAFAYATE"]}`, verifica que el servicio retorna dos `MisionPosibleResult` con paths distintos. Valida RF-017.

- [ ] `test_modo_supervisores_una_sola_consulta` — verifica que `data_loader.get_cobertura_preventista_marca` se llama exactamente una vez aunque haya multiples supervisores. Valida RF-018.

- [ ] `test_periodo_normalizado_al_primer_dia` — con `periodo="2026-03-15"`, verifica que la consulta usa `periodos=["2026-03-01"]`. Valida RF-019 + constraint de periodo.

- [ ] `test_consulta_bd_falla_genera_hojas_vacias` — mock de `get_cobertura_preventista_marca` que lanza `Exception`; verifica que el servicio genera el archivo sin error con tablas vacias. Valida RNF-003.

- [ ] `test_nombre_hoja_truncado_31_chars` — con nombre de marca de 35 caracteres, verifica truncado a 31 antes de crear hoja. Valida constraint de OpenPyXL.

- [ ] `test_ultima_actualizacion_en_summary_rows` — verifica que `SheetStyle.summary_rows` incluye `Ult. Actualizacion` con la fecha retornada por `get_ultima_fecha_venta`. Valida RF-023.

### De integracion (requieren BD)

- [ ] `test_generar_reporte_crea_archivo` — genera un reporte real y verifica que el archivo existe en `data/output/`. Valida RF-001.

- [ ] `test_api_post_mision_posible_retorna_metadata` — hace `POST /mision-posible/reporte` y verifica que la respuesta tiene `ruta_archivos`, `marcas_incluidas`, `hojas`. Valida RF-021.

---

## 8. Tareas de Implementacion

**Tarea 0 — Agregar `get_ultima_fecha_venta` al DataLoader**

Nuevo metodo simple: `SELECT MAX(fecha_comprobante) FROM gold.fact_ventas`. Retorna una fecha (`date`) o `None`. Se usa como dato de control en el reporte.

- Archivos: `src/core/data_loader.py` (modificado)
- Sin dependencias

**Tarea 1 — Crear processor**

Implementar `procesar_cobertura_sucursal(df_cob, marca, objetivo_total, porcentajes_sucursal, df_ult_venta)` y `procesar_cobertura_vendedor(df_cob, marca, objetivo_sucursales, df_ult_venta)` en `processor.py`. Cada funcion filtra por marca, agrupa, calcula Objetivo (via porcentaje para sucursal, reparto igualitario para vendedor), Faltante, Porcentaje, y agrega `Ult. Venta`. Implementar tambien `concatenar_tablas(df_sucursal, df_vendedor)` para el layout de una hoja.

- Archivos: `src/services/mision_posible/__init__.py` (nuevo, vacio), `src/services/mision_posible/processor.py` (nuevo)
- Depende de: Tarea 0

**Tarea 2 — Crear MisionPosibleService**

Implementar `MisionPosibleConfig`, `MisionPosibleResult` y `MisionPosibleService` (hereda de `BaseService`). El servicio orquesta el fetch, aplica zonas virtuales, itera por marca llamando al processor, concatena las tablas con `concatenar_tablas()`, y escribe el Excel con `as_table=False`. Implementar `generar_reporte` y `generar_reporte_supervisores` con el patron de una sola consulta y particion en memoria. El `generar_reporte` retorna un unico `MisionPosibleResult`; `generar_reporte_supervisores` retorna una lista de `MisionPosibleResult`.

- Archivos: `src/services/mision_posible/service.py` (nuevo)
- Depende de: Tarea 1

**Tarea 3 — Actualizar exports y CLI**

Actualizar `src/services/__init__.py` para exportar `MisionPosibleService`, `MisionPosibleConfig`, `MisionPosibleResult`. Agregar subcomando `mision-posible` a `main.py` con funcion `cmd_mision_posible` y todos sus argumentos. Crear `config_mision_posible.json` como ejemplo.

- Archivos: `src/services/mision_posible/__init__.py` (modificado), `src/services/__init__.py` (modificado), `main.py` (modificado), `config_mision_posible.json` (nuevo)
- Depende de: Tarea 2

**Tarea 4 — Crear router FastAPI y registrar en app**

Implementar `src/api/routes/mision_posible.py` con endpoints `POST /mision-posible/reporte` y `POST /mision-posible/reporte/download`. Actualizar `src/api/routes/__init__.py` para exportar `mision_posible_router`. Registrar el router en `api.py` y hacer version bump a `2.2.0`.

- Archivos: `src/api/routes/mision_posible.py` (nuevo), `src/api/routes/__init__.py` (modificado), `api.py` (modificado)
- Depende de: Tarea 2

**Tarea 5 — Tests unitarios**

Implementar todos los tests unitarios del Plan de Testing en `tests/test_mision_posible.py`.

- Archivos: `tests/test_mision_posible.py` (nuevo)
- Depende de: Tarea 1, Tarea 2

---

## 9. Boundaries (Lo que NO hacer)

- NO crear tabla de objetivos en la base de datos; los objetivos vienen exclusivamente del JSON de configuracion.
- NO sumar coberturas de distintas marcas para calcular un "total general"; la cobertura no es sumable entre marcas.
- NO modificar `VentasService`, `ResumenMensualService` ni sus processors.
- NO agregar columnas de volumen (`volumen_total`) al reporte; el foco es exclusivamente en clientes compradores.
- NO agregar slicers a este reporte; las tablas son simples y no lo requieren.
- NO soportar multiples periodos (rango de meses) en esta iteracion; el reporte es de un unico mes.
- NO agregar cobertura por generico en esta iteracion; comenzar solo con marcas.

---

## 10. Decisiones

### Resueltas

- [x] **Decision 1 — Layout de dos tablas por hoja**: Se usa **Opcion B** (concatenar DataFrames con fila separadora) con `as_table=False`. Es la opcion mas simple, no requiere modificar `ExcelWriter`, y el formato visual es suficiente. Futura mejora: extender `ExcelWriter` con `start_row` si se necesita formato de tabla Excel en ambas secciones.

- [x] **Decision 2 — Objetivo por vendedor**: No se configura por vendedor. El objetivo del vendedor se calcula automaticamente: `objetivo_sucursal / cantidad_vendedores` (reparto igualitario). Los vendedores se identifican por clave compuesta `(vendedor, sucursal)` en la vista.

- [x] **Decision 3 — Sucursales sin datos**: Se muestran TODAS las sucursales que estan en `porcentajes_sucursal`, con `Cobertura = 0` si no tienen datos.

- [x] **Decision 4 — Manejo de periodo no primer-dia-del-mes**: Se normaliza al primer dia del mes pero se imprime un warning al usuario (`print("⚠ Periodo normalizado de {original} a {normalizado}")`). No se interrumpe la ejecucion. Esto deja la puerta abierta a soportar rangos abiertos en el futuro.
