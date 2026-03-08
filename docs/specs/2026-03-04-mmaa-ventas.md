# Spec: MMAA en Reporte de Ventas

> **Estado:** DRAFT
> **Fecha:** 2026-03-04
> **Autor:** nahuel

## 1. Objetivo

Agregar dos columnas "Ventas Mismo Mes Año Anterior (MMAA)" al reporte de ventas existente: una a nivel generico y otra a nivel marca. Ambas hojas (Bultos y HTLs) reciben ambas columnas.

## 2. Contexto

El reporte de ventas (`VentasService`) ya muestra Cantidad, Tendencia, Monto y Cobertura por generico y por marca. Los usuarios necesitan comparar las ventas actuales contra el mismo mes del año anterior para evaluar el crecimiento. El resumen mensual ya calcula MMAA a nivel sucursal+generico; el reporte de ventas necesita además el desglose por marca y los valores en HTLs.

El metodo `get_ventas_mismo_mes_anio_anterior()` ya existe en `DataLoader` pero solo retorna `sucursal, generico, id_ruta, cantidad`. Esta spec requiere un nuevo metodo que incluya tambien `marca` y `cantidad_htls`.

## 3. Requisitos Funcionales

- **RF-001**: Cuando se genera el reporte de ventas, el sistema debe incluir una columna `MMAA (Generico)` inmediatamente despues de `Cobertura (Generico)`, con el total de `cantidades_total` del mismo mes del año anterior agrupado por `(sucursal, generico)`. El valor solo aparece en la primera fila de cada grupo `(sucursal, generico)`; las demas filas del grupo tienen `None`.

- **RF-002**: Cuando se genera el reporte de ventas, el sistema debe incluir una columna `MMAA (Marca)` inmediatamente despues de `Cobertura (Marca)`, con el total de `cantidades_total` del mismo mes del año anterior agrupado por `(sucursal, generico, marca)`.

- **RF-003**: Cuando la hoja generada es "Ventas Bultos", el sistema debe usar `cantidades_total` (campo `cantidad` en el DataFrame) para poblar ambas columnas MMAA.

- **RF-004**: Cuando la hoja generada es "Ventas HTLs", el sistema debe usar `cantidad_total_htls` (campo `cantidad_htls` en el DataFrame) para poblar ambas columnas MMAA.

- **RF-005**: Cuando el rango del reporte es `[YYYY-MM-DD, YYYY-MM-DD]`, el sistema debe calcular el periodo MMAA como el mismo rango desplazado exactamente un año atras: `[(YYYY-1)-MM-DD, (YYYY-1)-MM-DD]`.

- **RF-006**: Cuando una combinacion `(sucursal, generico)` o `(sucursal, generico, marca)` no tiene ventas en el año anterior, el sistema debe mostrar `0` (no `None`) en las columnas MMAA correspondientes.

- **RF-007**: Cuando la consulta MMAA falla por cualquier razon (BD no disponible, tabla ausente, error de red), el sistema debe capturar la excepcion, rellenar ambas columnas MMAA con `0` para todas las filas y continuar la generacion del reporte sin propagar el error.

- **RF-008**: Cuando se aplican zonas virtuales (CASA CENTRAL se divide en CASA CENTRAL y VALLE SALTA segun `id_ruta`), el sistema debe aplicar `aplicar_zonas_virtuales()` al DataFrame MMAA antes de agrupar, de modo que los datos de rutas de VALLE SALTA queden correctamente asignados a esa zona virtual. **Nota:** `aplicar_zonas_virtuales` en `src/core/zonas.py` debe actualizarse para reagrupar DataFrames con columnas `(cantidad, cantidad_htls)` sin `monto` — actualmente solo reagrupa si las tres (`cantidad`, `cantidad_htls`, `monto`) estan presentes.

- **RF-009**: Cuando se genera un reporte por supervisor, el sistema debe filtrar los datos MMAA al universo de sucursales del supervisor (incluyendo las zonas virtuales expandidas), igual que con los demas DataFrames.

## 4. Requisitos No Funcionales

- **RNF-001**: El nuevo metodo `get_ventas_mmaa(fecha_desde, fecha_hasta, genericos)` en `DataLoader` debe retornar un DataFrame con columnas `sucursal, generico, marca, id_ruta, cantidad, cantidad_htls` y no incluir la columna `fecha` (es un agregado mensual, no diario).

- **RNF-002**: La adicion de las columnas MMAA no debe aumentar el tiempo de generacion en mas de 5 segundos en condiciones normales de red.

- **RNF-003**: Si `MMAA (Generico)` o `MMAA (Marca)` no estan en `COLUMN_NAMES` en `config/settings.py`, la clave debe agregarse ahi para mantener consistencia con el resto de columnas del reporte.

## 5. Diseño Tecnico

### 5.1 Modelo de Datos

No se crean tablas nuevas. Se agrega un metodo al `DataLoader` que consulta `fact_ventas` con el rango del año anterior.

**Nuevo metodo: `get_ventas_mmaa(fecha_desde, fecha_hasta, genericos)`**

Recibe el rango del año actual y calcula internamente el rango del año anterior.

```sql
-- Rango calculado en Python: anio_desde = YYYY-1, anio_hasta = YYYY-1
SELECT
    ds.descripcion          AS sucursal,
    da.generico,
    da.marca,
    dc.id_ruta_fv1          AS id_ruta,
    SUM(fv.cantidades_total)       AS cantidad,
    SUM(fv.cantidad_total_htls)    AS cantidad_htls
FROM gold.fact_ventas fv
LEFT JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal  = ds.id_sucursal
LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente
WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta   -- rango del año anterior
  AND da.generico IS NOT NULL
  [AND da.generico IN (:gen_0, :gen_1, ...)]           -- opcional
GROUP BY ds.descripcion, da.generico, da.marca, dc.id_ruta_fv1
ORDER BY ds.descripcion, da.generico, da.marca
```

Calculo del rango del año anterior (en Python, igual al patron ya existente en `get_ventas_mismo_mes_anio_anterior`):

```python
fecha_desde_aa = f"{int(fecha_desde[:4]) - 1}{fecha_desde[4:]}"
fecha_hasta_aa = f"{int(fecha_hasta[:4]) - 1}{fecha_hasta[4:]}"
```

Columnas retornadas: `sucursal, generico, marca, id_ruta, cantidad, cantidad_htls`

### 5.2 Arquitectura

Archivos afectados:

```
src/
  core/
    data_loader.py        MODIFICADO: +get_ventas_mmaa()
  services/
    ventas/
      service.py          MODIFICADO: fetch MMAA en _fetch_data, filtro en generar_reporte_supervisores,
                                      pasar df_mmaa a _build_workbook
      processor.py        MODIFICADO: procesar_ventas_diarias acepta df_mmaa, agrega columnas MMAA
config/
  settings.py             MODIFICADO: +mmaa_generico y +mmaa_marca en COLUMN_NAMES
tests/
  test_processor.py       MODIFICADO: tests para columnas MMAA en procesar_ventas_diarias
  test_services.py        MODIFICADO: mock_loader incluye get_ventas_mmaa
```

**Flujo de datos:**

```
VentasService._fetch_data(config)
    |
    +-- data_loader.get_ventas_mmaa(fecha_desde, fecha_hasta, genericos)  --> df_mmaa_raw
    |
    +--> aplicar_zonas_virtuales(df_mmaa_raw)                             --> df_mmaa
    |
    +--> df_mmaa ya disponible en _fetch_data (retornado como 7mo elemento)

VentasService._build_workbook(...)
    |
    +--> procesar_ventas_diarias(df_ventas, ..., col_cantidad, ..., df_mmaa=df_mmaa)
         |
         +--> Construir mmaa_gen_dict:  (sucursal, generico) -> cantidad o cantidad_htls
         +--> Construir mmaa_marca_dict: (sucursal, generico, marca) -> cantidad o cantidad_htls
         |
         +--> En el loop de rows:
              row[COLUMN_NAMES["mmaa_generico"]] = mmaa_gen_dict.get((suc, gen), 0) if i == 0 else None
              row[COLUMN_NAMES["mmaa_marca"]]    = mmaa_marca_dict.get((suc, gen, marca), 0)
```

### 5.3 API / Interfaz

#### Firma actualizada de `procesar_ventas_diarias`

```python
def procesar_ventas_diarias(
    df: pd.DataFrame,
    fecha_desde: str,
    fecha_hasta: str,
    df_sucursales: pd.DataFrame | None = None,
    df_articulos: pd.DataFrame | None = None,
    col_cantidad: str = "cantidad",
    df_cob_generico: pd.DataFrame | None = None,
    df_cob_marca: pd.DataFrame | None = None,
    df_mmaa: pd.DataFrame | None = None,    # NUEVO parametro
) -> pd.DataFrame:
```

`df_mmaa` es el DataFrame post-zonas-virtuales con columnas `sucursal, generico, marca, cantidad, cantidad_htls`. El procesador elige `cantidad` o `cantidad_htls` segun `col_cantidad`.

#### Seleccion de campo MMAA segun unidad

```python
# En procesar_ventas_diarias, al construir los dicts de lookup:
col_mmaa = "cantidad" if col_cantidad == "cantidad" else "cantidad_htls"

mmaa_gen_dict = {}
if df_mmaa is not None and not df_mmaa.empty:
    mmaa_gen_agg = df_mmaa.groupby(["sucursal", "generico"])[col_mmaa].sum().reset_index()
    mmaa_gen_dict = {
        (r["sucursal"], r["generico"]): int(r[col_mmaa])
        for _, r in mmaa_gen_agg.iterrows()
    }

mmaa_marca_dict = {}
if df_mmaa is not None and not df_mmaa.empty:
    mmaa_marca_agg = df_mmaa.groupby(["sucursal", "generico", "marca"])[col_mmaa].sum().reset_index()
    mmaa_marca_dict = {
        (r["sucursal"], r["generico"], r["marca"]): int(r[col_mmaa])
        for _, r in mmaa_marca_agg.iterrows()
    }
```

#### Orden de columnas resultante

```
Sucursal | Generico | Cantidad (Generico) | Tendencia (Generico) | Monto (Generico) |
Cobertura (Generico) | MMAA (Generico) |
Marca | [dd-mm DiaName ...] | Total | Tendencia (Marca) | Monto (Marca) |
Cobertura (Marca) | MMAA (Marca)
```

#### Nuevas entradas en `COLUMN_NAMES` (config/settings.py)

```python
COLUMN_NAMES = {
    ...
    "cob_generico":   "Cobertura (Generico)",
    "mmaa_generico":  "MMAA (Generico)",       # NUEVO
    "marca":          "Marca",
    ...
    "cob_marca":      "Cobertura (Marca)",
    "mmaa_marca":     "MMAA (Marca)",           # NUEVO
}
```

#### Nuevas entradas en `VENTAS_COLUMN_FORMATS` (service.py)

```python
VENTAS_COLUMN_FORMATS = {
    ...
    COLUMN_NAMES["mmaa_generico"]: ColumnFormat(number_format='#,##0', width=14, font_bold=True),
    COLUMN_NAMES["mmaa_marca"]:    ColumnFormat(number_format='#,##0', width=14, font_bold=True),
}
```

#### Fetch y manejo de error en `_fetch_data`

```python
df_mmaa = pd.DataFrame()
try:
    df_mmaa_raw = self.data_loader.get_ventas_mmaa(
        config.fecha_desde,
        config.fecha_hasta,
        config.genericos
    )
    if not df_mmaa_raw.empty:
        df_mmaa = _aplicar_zonas_virtuales(df_mmaa_raw)
except Exception:
    pass  # df_mmaa queda vacio; el processor usara 0 para todas las filas

return df_ventas, df_sucursales, df_articulos, df_cob_generico, df_cob_marca, info_dias, df_mmaa
```

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|------|------------------------|
| No hay datos del año anterior | `get_ventas_mmaa` retorna DataFrame vacio; todas las filas muestran `0` en ambas columnas MMAA |
| Consulta MMAA falla con excepcion | `df_mmaa` queda como DataFrame vacio; reporte continua con `0` en columnas MMAA |
| Combinacion `(sucursal, marca)` sin ventas en año anterior | `MMAA (Marca)` = `0` |
| Primera fila del grupo `(sucursal, generico)` | `MMAA (Generico)` tiene valor; `MMAA (Marca)` tiene valor de esa marca |
| Filas siguientes del mismo grupo | `MMAA (Generico)` = `None`; `MMAA (Marca)` tiene el valor de su propia marca |
| CASA CENTRAL con rutas de VALLE SALTA | `aplicar_zonas_virtuales` aplicado antes de agrupar; cada zona tiene sus propios valores MMAA |
| Reporte por supervisor | `df_mmaa` filtrado al mismo universo de sucursales que el resto de DataFrames |
| `df_mmaa` es `None` (no pasado al processor) | El processor trata igual que DataFrame vacio; todas las filas muestran `0` |
| Hoja HTLs | `col_cantidad = "cantidad_htls"`; el processor usa `cantidad_htls` del `df_mmaa` para ambas columnas |

## 7. Plan de Testing

### Unitarios (sin BD, con mocks)

- [ ] **Test RF-001**: `test_mmaa_generico_solo_primera_fila` — dado `df_mmaa` con datos para `(SUC1, CERVEZAS)`, verifica que `MMAA (Generico)` tiene valor en la primera fila del grupo y `None` en las siguientes. Valida RF-001.

- [ ] **Test RF-002**: `test_mmaa_marca_en_todas_las_filas` — dado `df_mmaa` con datos para `(SUC1, CERVEZAS, CORONA)` y `(SUC1, CERVEZAS, HEINEKEN)`, verifica que `MMAA (Marca)` tiene el valor correcto en cada fila. Valida RF-002.

- [ ] **Test RF-003 y RF-004**: `test_mmaa_usa_col_cantidad_correcta` — llama a `procesar_ventas_diarias` con `col_cantidad="cantidad"` y con `"cantidad_htls"`, y verifica que los valores en las columnas MMAA corresponden a los campos correctos del `df_mmaa`. Valida RF-003 y RF-004.

- [ ] **Test RF-005**: `test_get_ventas_mmaa_calcula_anio_anterior` — verifica que `get_ventas_mmaa("2026-02-01", "2026-02-28", None)` llama a la query con `desde="2025-02-01"` y `hasta="2025-02-28"`. Valida RF-005.

- [ ] **Test RF-006**: `test_mmaa_cero_cuando_sin_datos` — dado `df_mmaa` vacio, verifica que todas las filas muestran `0` en `MMAA (Marca)` y `0` en `MMAA (Generico)` (primera fila). Valida RF-006.

- [ ] **Test RF-007**: `test_mmaa_cero_cuando_query_falla` — mock de `data_loader.get_ventas_mmaa` que lanza `Exception`; verifica que el reporte se genera sin error, `MMAA (Generico)` es `0` en la primera fila de cada grupo y `None` en las siguientes, y `MMAA (Marca)` es `0` en todas las filas. Valida RF-007.

- [ ] **Test RF-008**: `test_mmaa_aplica_zonas_virtuales` — dado `df_mmaa_raw` con `id_ruta=81` y `sucursal="CASA CENTRAL"`, verifica que despues de `aplicar_zonas_virtuales` la fila tiene `sucursal="VALLE SALTA"`. Valida RF-008.

- [ ] **Test RF-009**: `test_mmaa_filtrado_por_supervisor` — verifica que en `generar_reporte_supervisores`, `df_mmaa` se filtra con las sucursales expandidas del supervisor antes de pasarlo al processor. Valida RF-009.

- [ ] **Test columnas en orden**: `test_orden_columnas_mmaa` — verifica que en el DataFrame resultado de `procesar_ventas_diarias`, `MMAA (Generico)` esta despues de `Cobertura (Generico)` y `MMAA (Marca)` esta despues de `Cobertura (Marca)`. Valida RF-001 y RF-002.

- [ ] **Test mock_loader en test_services**: `test_generar_reporte_llama_get_ventas_mmaa` — verifica que `VentasService.generar_reporte` llama a `data_loader.get_ventas_mmaa` con los parametros correctos. Valida integracion del servicio.

## 8. Tareas de Implementacion

**Tarea 1 — Agregar `get_ventas_mmaa` al DataLoader y actualizar `aplicar_zonas_virtuales`**

Implementar el metodo que calcula el rango del año anterior y ejecuta la query SQL que retorna `sucursal, generico, marca, id_ruta, cantidad, cantidad_htls`. Ademas, actualizar `aplicar_zonas_virtuales()` en `src/core/zonas.py` para reagrupar DataFrames con columnas `(cantidad, cantidad_htls)` sin `monto` (agregar branch `elif all(c in df.columns for c in ("cantidad", "cantidad_htls"))`).

- Archivos: `src/core/data_loader.py`, `src/core/zonas.py`
- Sin dependencias

**Tarea 2 — Actualizar `COLUMN_NAMES` y formatos**

Agregar `"mmaa_generico"` y `"mmaa_marca"` a `COLUMN_NAMES` en `config/settings.py`. Agregar las entradas correspondientes en `VENTAS_COLUMN_FORMATS` en `src/services/ventas/service.py`.

- Archivos: `config/settings.py`, `src/services/ventas/service.py`
- Sin dependencias

**Tarea 3 — Actualizar `procesar_ventas_diarias` en el processor**

Agregar parametro `df_mmaa` (opcional, default `None`). Construir `mmaa_gen_dict` y `mmaa_marca_dict` a partir de `df_mmaa` usando `col_mmaa` derivado de `col_cantidad`. Insertar las dos columnas MMAA en el dict `row` en el orden correcto (despues de cobertura).

- Archivos: `src/services/ventas/processor.py`
- Depende de: Tarea 2

**Tarea 4 — Actualizar `VentasService` para fetch y propagacion de MMAA**

En `_fetch_data`: llamar a `get_ventas_mmaa`, aplicar `aplicar_zonas_virtuales`, capturar excepcion. Actualizar firma de retorno de `_fetch_data` (7 elementos). **IMPORTANTE:** Actualizar el tuple-unpack en AMBOS call sites: `generar_reporte` (linea ~297) y `generar_reporte_supervisores` (linea ~347), ambos actualmente desempaquetan 6 elementos. En `_build_workbook`: recibir y pasar `df_mmaa` al processor. En `generar_reporte_supervisores`: filtrar `df_mmaa` por sucursales del supervisor antes de pasarlo al processor.

- Archivos: `src/services/ventas/service.py`
- Depende de: Tarea 1, Tarea 3

**Tarea 5 — Actualizar tests**

Actualizar `mock_loader` en `tests/test_services.py` para incluir `get_ventas_mmaa`. Agregar tests de columnas MMAA en `tests/test_processor.py`. Agregar test de llamada a `get_ventas_mmaa` en `tests/test_services.py`.

- Archivos: `tests/test_services.py`, `tests/test_processor.py`
- Depende de: Tarea 3, Tarea 4

## 9. Boundaries (Lo que NO hacer)

- NO modificar el resumen mensual (`src/services/resumen_mensual/`) — ya tiene su propio MMAA a nivel sucursal+generico.
- NO agregar columna MMAA de Monto; solo cantidad (bultos o htls segun la hoja).
- NO cambiar el nombre ni la ubicacion del metodo `get_ventas_mismo_mes_anio_anterior` existente; el nuevo metodo `get_ventas_mmaa` es independiente (diferente granularidad: incluye marca y htls).
- NO agregar nuevos endpoints a la API REST ni cambios al CLI; el reporte de ventas ya expone sus endpoints existentes y el nuevo dato fluye de manera transparente.
- NO modificar `SheetStyle` ni `ExcelWriter`; las nuevas columnas usan los mecanismos de formato ya existentes.

## 10. Decisiones Tomadas

- **Valor MMAA (Generico) para primera fila sin datos AA**: `0`. Usa `mmaa_gen_dict.get((suc, gen), 0)` como default.
- **Valor MMAA (Generico) para filas no-primera**: `None` (supresion visual, igual que las demas columnas de generico).
- **MMAA siempre se fetchea**: No depende de `con_cobertura` ni ningun otro flag — siempre se consulta.
- **Ancho de columna**: `width=14` para ambas columnas MMAA.
