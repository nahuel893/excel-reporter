# Spec: Resumen Mensual

> **Estado:** APROBADA
> **Fecha:** 2026-03-02
> **Autor:** nahuel

---

## 1. Objetivo

Generar un reporte Excel de resumen mensual que consolide, por cada generico, las ventas de los dos ultimos dias habiles, el total acumulado del mes, la tendencia al cierre, las ventas del mismo mes del ano anterior, y (en el futuro) el objetivo y su porcentaje de cumplimiento. El reporte permite a los supervisores leer rapidamente el estado del mes en una sola tabla compacta por generico.

---

## 2. Contexto

El reporte de ventas existente (`VentasService`) genera un desglose columna-por-dia que es muy granular para una lectura ejecutiva rapida. Los supervisores necesitan una vision de "estado del mes" que responda en una sola hoja: cuanto se vendio los ultimos dos dias, como viene el mes, y como se compara con el ano anterior. No existe hoy ninguna tabla de objetivos en la base de datos; el diseno debe dejar esa columna prevista sin bloquear el desarrollo.

---

## 3. Requisitos Funcionales

### 3.1 Generacion del archivo

- **RF-001**: Cuando el usuario invoca el reporte con `fecha_desde` y `fecha_hasta`, el sistema debe generar un unico archivo Excel en `data/output/` con el nombre `Resumen {dd-mm-yyyy}.xlsx`, donde la fecha corresponde a la ultima fecha con ventas reales en el rango; si no hay ventas, debe usar `fecha_hasta` como fallback.

- **RF-002**: Cuando el archivo es generado, el sistema debe crear una hoja por cada generico presente en los datos, nombrada exactamente con el nombre del generico (ej: `CERVEZAS`, `AGUAS DANONE`). Si no hay genericos filtrados, se incluyen todos los genericos con ventas en el periodo.

- **RF-003**: Si `genericos` es una lista no vacia en la configuracion, el sistema debe filtrar el reporte para incluir unicamente esos genericos, en el mismo orden en que aparecen en la lista.

### 3.2 Estructura de columnas por hoja

- **RF-004**: Cuando se genera una hoja de generico, el sistema debe producir una tabla con las siguientes columnas en este orden exacto:

  | # | Nombre de columna | Tipo de dato |
  |---|---|---|
  | 1 | `Sucursal` | texto |
  | 2 | `Generico` | texto |
  | 3 | `Vtas Dia N-1` | entero |
  | 4 | `Vtas Dia N-2` | entero |
  | 5 | `Total Ventas` | entero |
  | 6 | `Tendencia` | entero |
  | 7 | `Ventas Mes Anterior` | entero |
  | 8 | `Ventas Mismo Mes AA` | entero |
  | 9 | `Objetivo` | entero o vacio |
  | 10 | `Tend vs Obj (%)` | decimal o vacio |

- **RF-005**: Cuando `con_objetivo` es `False` (valor por defecto), el sistema debe escribir la columna `Objetivo` con valores `None` (celda vacia) y la columna `Tend vs Obj (%)` con valores `None` para todas las filas.

- **RF-006**: Cuando `con_objetivo` es `True` y existe una fuente de datos de objetivos, el sistema debe calcular `Tend vs Obj (%)` como `round(Tendencia / Objetivo * 100, 1)`. Si `Objetivo` es 0 o `None`, la celda debe quedar vacia.

### 3.3 Filas de la tabla

- **RF-007**: Cuando se construye la tabla, el sistema debe incluir una fila por cada combinacion `(Sucursal, Generico)` con ventas en el periodo o en el mismo mes del ano anterior. Las combinaciones sin ningun dato en ambos periodos se omiten. La union se realiza con **outer join** sobre `(sucursal, generico)` entre `df_ventas_mes` y `df_ventas_ma`; los valores ausentes se rellenan con `0` (`fillna(0)`).

- **RF-008**: Cuando se generan las filas, el sistema debe ordenarlas primero por `Sucursal` (alfabetico ascendente) y luego por `Generico` (alfabetico ascendente).

### 3.4 Calculo de cada columna

- **RF-009**: Cuando se calcula `Vtas Dia N-1`, el sistema debe identificar el ultimo dia con ventas reales dentro del rango `[fecha_desde, fecha_hasta]` y sumar `cantidades_total` de `fact_ventas` para esa `(Sucursal, Generico)` en esa fecha. Si no hay ventas ese dia para esa combinacion, el valor es `0`.

- **RF-010**: Cuando se calcula `Vtas Dia N-2`, el sistema debe identificar el penultimo dia con ventas reales dentro del rango y aplicar la misma logica que RF-009. Los dias con ventas reales se detectan a partir de las fechas distintas presentes en `fact_ventas` para el **periodo actual** (no del calendario y no del ano anterior), excluyendo domingos y feriados definidos en `config/settings.py`. **Nota**: `FERIADOS` en `config/settings.py` solo contiene feriados de 2026; la deteccion de N-1/N-2 aplica unicamente al periodo actual (no a los datos del ano anterior), por lo que esta limitacion no afecta el calculo de `Ventas Mismo Mes AA`.

- **RF-011**: Cuando se calcula `Total Ventas`, el sistema debe sumar `cantidades_total` de `fact_ventas` para la `(Sucursal, Generico)` en todo el rango `[fecha_desde, fecha_hasta]`.

- **RF-012**: Cuando se calcula `Tendencia`, el sistema debe aplicar la formula `round(Total Ventas * factor_tendencia)`, donde `factor_tendencia = dias_habiles_totales_mes / dias_habiles_transcurridos_hasta_hoy`. Este calculo reutiliza `calcular_factor_tendencia(fecha_desde, fecha_hasta)` de `src/core/base_processor.py`. Si `dias_habiles_transcurridos_hasta_hoy` es 0, el factor es 1.0.

- **RF-013a**: Cuando se calcula `Ventas Mes Anterior`, el sistema debe sumar `cantidades_total` para la `(Sucursal, Generico)` en el mes calendario inmediatamente anterior al mes de `fecha_desde`. El rango es siempre el mes completo anterior: `[primer_dia_mes_anterior, ultimo_dia_mes_anterior]`. Ejemplos: si `fecha_desde = 2026-03-01`, el rango es `[2026-02-01, 2026-02-28]`; si `fecha_desde = 2026-01-01`, el rango es `[2025-12-01, 2025-12-31]`. Si no hay ventas, el valor es `0`.

- **RF-013b**: Cuando se calcula `Ventas Mismo Mes AA`, el sistema debe sumar `cantidades_total` para la `(Sucursal, Generico)` en el rango equivalente del ano anterior: si el periodo actual es `[YYYY-MM-01, YYYY-MM-DD]`, el periodo del ano anterior es `[(YYYY-1)-MM-01, (YYYY-1)-MM-DD]`. Si no hay ventas, el valor es `0`.

### 3.5 Zonas virtuales

- **RF-014**: Cuando se procesan ventas de `CASA CENTRAL`, el sistema debe aplicar la logica de zonas virtuales definida en `ZONAS_VIRTUALES` de `config/settings.py`, convirtiendo filas con `id_ruta` en `[81-93, 118-122]` a la sucursal virtual `VALLE SALTA`. Esta logica reutiliza `_aplicar_zonas_virtuales(df)` que ya existe en `src/services/ventas/service.py` y debe ser refactorizada a una ubicacion compartida (ver seccion 5.2). **Importante**: despues de aplicar `_aplicar_zonas_virtuales` a `df_ventas_mes` y `df_ventas_ma` (que solo tienen la columna `cantidad`), la funcion interna de reagrupamiento NO se activara (requiere `cantidad_htls` y `monto`). El processor debe hacer un `groupby(["sucursal", "generico"]).sum().reset_index()` explicito despues de llamar a `_aplicar_zonas_virtuales` para esos DataFrames, garantizando que las rutas renombradas queden correctamente agrupadas.

### 3.6 Filas de resumen (cabecera de hoja)

- **RF-015**: Cuando se escribe cada hoja, el sistema debe incluir las filas de resumen de dias habiles en la cabecera, reutilizando el mecanismo `summary_rows` de `SheetStyle`:

  ```
  Dias Habiles:        <valor entero>
  Dias Transcurridos:  <valor entero>
  Dias Faltantes:      <valor entero>
  ```

### 3.7 CLI

- **RF-016**: Cuando el usuario ejecuta `python main.py resumen-mensual --config config.json`, el sistema debe leer la configuracion del JSON y generar el reporte con el mismo patron de parametros que el subcomando `ventas`.

- **RF-017**: Mientras el subcomando `resumen-mensual` se ejecuta, el sistema debe aceptar los parametros individuales `--desde`, `--hasta`, `--genericos`, `--output`. Este reporte no usa slicers (no hay columnas de segmentacion), por lo que `--no-slicers` no aplica y no debe incluirse.

### 3.8 API REST

- **RF-018**: Cuando se realiza `POST /resumen-mensual/reporte`, el sistema debe generar el reporte y retornar metadata con: `ruta_archivo`, `registros_procesados`, `sucursales`, `genericos_incluidos`, `hojas`.

- **RF-019**: Cuando se realiza `POST /resumen-mensual/reporte/download`, el sistema debe retornar el archivo `.xlsx` como descarga directa con el header `Content-Disposition: attachment`.

---

## 4. Requisitos No Funcionales

- **RNF-001**: La generacion del reporte para un mes completo con todos los genericos debe completarse en menos de 30 segundos con conexion normal a la base de datos.

- **RNF-002**: El modulo `_aplicar_zonas_virtuales` y `_expandir_sucursales` deben moverse a `src/services/ventas/service.py` como funciones de modulo (ya estan ahi) o a un modulo compartido `src/core/zonas.py`. Esta spec requiere reutilizarlas; si se mueven, `VentasService` debe actualizar su import sin cambio de comportamiento.

- **RNF-003**: Si la consulta de `Ventas Mismo Mes AA` falla (por ejemplo porque no hay datos del ano anterior), el sistema debe capturar la excepcion, completar con `0` esa columna y continuar la generacion sin lanzar error al usuario.

- **RNF-004**: El archivo generado debe poder abrirse en Excel y LibreOffice sin errores de formato.

- **RNF-005**: El servicio debe aceptar `DataLoader` inyectable para permitir tests unitarios con mocks, siguiendo el patron de `VentasService`.

---

## 5. Diseno Tecnico

### 5.1 Modelo de Datos

No se crean tablas nuevas en esta iteracion. Las fuentes de datos son:

**Consulta 1 — Ventas mensuales con ruta (para Total Ventas, Tendencia y Zonas Virtuales)**

```sql
SELECT
    ds.descripcion          AS sucursal,
    da.generico,
    dc.id_ruta_fv1          AS id_ruta,
    SUM(fv.cantidades_total) AS cantidad
FROM gold.fact_ventas fv
LEFT JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal  = ds.id_sucursal
LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente
WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
  AND da.generico IS NOT NULL
  [AND da.generico IN (:gen_0, :gen_1, ...)]  -- opcional
GROUP BY ds.descripcion, da.generico, dc.id_ruta_fv1
ORDER BY ds.descripcion, da.generico
```

Nuevo metodo en `DataLoader`: `get_ventas_resumen_mensual(fecha_desde, fecha_hasta, genericos)`
Columnas retornadas: `sucursal`, `generico`, `id_ruta`, `cantidad`

---

**Consulta 2 — Ultimos N dias con ventas (para Vtas Dia N-1 y N-2)**

```sql
SELECT
    ds.descripcion           AS sucursal,
    da.generico,
    fv.fecha_comprobante     AS fecha,
    dc.id_ruta_fv1           AS id_ruta,
    SUM(fv.cantidades_total) AS cantidad
FROM gold.fact_ventas fv
LEFT JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal  = ds.id_sucursal
LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente
WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
  AND da.generico IS NOT NULL
  [AND da.generico IN (:gen_0, ...)]
GROUP BY ds.descripcion, da.generico, fv.fecha_comprobante, dc.id_ruta_fv1
ORDER BY ds.descripcion, da.generico, fv.fecha_comprobante
```

Nuevo metodo en `DataLoader`: `get_ventas_ultimos_dias_habiles(fecha_desde, fecha_hasta, genericos)`
Columnas retornadas: `sucursal`, `generico`, `fecha`, `id_ruta`, `cantidad`

Nota: esta consulta es identica en estructura a `get_ventas_diarias_con_ruta` pero sin `marca`, sin `cantidad_htls` y sin `monto`. Se puede reutilizar `get_ventas_diarias_con_ruta` filtrando columnas en el procesador si se prefiere no duplicar SQL, pero se recomienda un metodo propio para mantener la query mas liviana.

La deteccion de N-1 y N-2 se hace en Python despues del fetch:

```python
def _detectar_dias_habiles_con_ventas(df: pd.DataFrame, n: int = 2) -> list[date]:
    """
    Retorna los ultimos N dias que tienen ventas reales en el DataFrame,
    filtrando domingos y feriados.

    Args:
        df: DataFrame con columna 'fecha'
        n: Cantidad de dias a retornar
    Returns:
        Lista de dates ordenados descendente (el ultimo primero)
    """
    feriados_set = {datetime.strptime(f, "%Y-%m-%d").date() for f in FERIADOS}
    fechas_con_ventas = pd.to_datetime(df["fecha"]).dt.date.unique()
    fechas_habiles = sorted(
        [d for d in fechas_con_ventas
         if d.weekday() != 6 and d not in feriados_set],
        reverse=True
    )
    return fechas_habiles[:n]
```

---

**Consulta 3 — Ventas mes anterior (mes calendario previo)**

Identica en estructura a la Consulta 1, con el rango del mes completo anterior:

```python
from dateutil.relativedelta import relativedelta
fecha_desde_dt = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
primer_dia_mes_anterior = (fecha_desde_dt.replace(day=1) - relativedelta(months=1))
ultimo_dia_mes_anterior = fecha_desde_dt.replace(day=1) - timedelta(days=1)
```

Nuevo metodo en `DataLoader`: `get_ventas_mes_anterior(fecha_desde, genericos)`
Internamente calcula el rango del mes anterior y reutiliza la misma query que `get_ventas_resumen_mensual`.
Columnas retornadas: `sucursal`, `generico`, `id_ruta`, `cantidad`

---

**Consulta 4 — Ventas mismo mes ano anterior**

Identica en estructura a la Consulta 1, pero con el rango de fechas desplazado 1 ano atras:

```python
fecha_desde_ma = f"{int(fecha_desde[:4]) - 1}{fecha_desde[4:]}"
fecha_hasta_ma = f"{int(fecha_hasta[:4]) - 1}{fecha_hasta[4:]}"
```

Nuevo metodo en `DataLoader`: `get_ventas_mismo_mes_anio_anterior(fecha_desde_ma, fecha_hasta_ma, genericos)`
Internamente puede reutilizar la misma query que `get_ventas_resumen_mensual`.
Columnas retornadas: `sucursal`, `generico`, `id_ruta`, `cantidad`

---

### 5.2 Arquitectura

```
src/
  core/
    zonas.py                    # NUEVO: _aplicar_zonas_virtuales, _expandir_sucursales
                                # (refactorizadas desde ventas/service.py)
    data_loader.py              # MODIFICADO: +3 metodos nuevos
    base_processor.py           # SIN CAMBIOS (se reutiliza calcular_factor_tendencia)
  services/
    ventas/
      service.py                # MODIFICADO: imports desde src.core.zonas (si se refactoriza)
    resumen_mensual/            # NUEVO modulo
      __init__.py
      service.py                # ResumenMensualService, config, result
      processor.py              # procesar_resumen_mensual
  api/
    routes/
      resumen_mensual.py        # NUEVO: router FastAPI
    __init__.py                 # MODIFICADO: +resumen_mensual_router

main.py                         # MODIFICADO: +subcomando resumen-mensual
api.py                          # MODIFICADO: include_router(resumen_mensual_router)
```

**Flujo de datos:**

```
main.py/API
    |
    v
ResumenMensualService.generar_reporte(config)
    |
    +-- data_loader.get_ventas_resumen_mensual()         --> df_ventas_mes
    +-- data_loader.get_ventas_ultimos_dias_habiles()    --> df_dias
    +-- data_loader.get_ventas_mes_anterior()            --> df_ventas_ma
    +-- data_loader.get_ventas_mismo_mes_anio_anterior() --> df_ventas_aa
    |
    +--> _aplicar_zonas_virtuales(df_ventas_mes)
    +--> _aplicar_zonas_virtuales(df_dias)
    +--> _aplicar_zonas_virtuales(df_ventas_ma)
    +--> _aplicar_zonas_virtuales(df_ventas_aa)
    |
    +--> procesar_resumen_mensual(df_ventas_mes, df_dias, df_ventas_ma, df_ventas_aa, info_dias, config)
         |
         +--> _detectar_dias_habiles_con_ventas(df_dias, n=2)
         +--> calcular_factor_tendencia(fecha_desde, fecha_hasta)
         +--> construir DataFrame con 9 columnas
    |
    +--> ExcelWriter: una hoja por generico
         |
         +--> SheetStyle con summary_rows={Dias Habiles, Dias Transcurridos, Dias Faltantes}
    |
    --> ResumenMensualResult
```

### 5.3 API / Interfaz

#### Config dataclass

```python
@dataclass
class ResumenMensualConfig:
    """Standalone dataclass; NO hereda de BaseReporteConfig para evitar que
    __post_init__ sobreescriba nombre_archivo=None con un valor por defecto."""
    fecha_desde: str           # "YYYY-MM-DD", primer dia del mes
    fecha_hasta: str           # "YYYY-MM-DD", ultimo dia con ventas (o fin de mes)
    genericos: list[str] | None = None
    nombre_archivo: str | None = None
    con_objetivo: bool = False  # False hasta que exista tabla en BD
```

#### Result dataclass

```python
@dataclass
class ResumenMensualResult:
    ruta_archivo: Path
    registros_procesados: int   # total de filas (sucursal, generico) en el archivo (suma de todas las hojas)
    sucursales: int             # cantidad de sucursales unicas en el resultado
    genericos_incluidos: list[str]
    hojas: list[str]            # nombres de hojas = nombres de genericos
```

#### Schema de la hoja Excel (por generico)

```
Filas de cabecera (summary_rows):
  Fila 1: "Dias Habiles"        | <int>
  Fila 2: "Dias Transcurridos"  | <int>
  Fila 3: "Dias Faltantes"      | <int>
  Fila 4: (vacia)

Encabezados de tabla (Fila 5):
  Sucursal | Generico | Vtas Dia N-1 | Vtas Dia N-2 | Total Ventas |
  Tendencia | Ventas Mes Anterior | Ventas Mismo Mes AA | Objetivo | Tend vs Obj (%)

Datos (Fila 6 en adelante):
  Una fila por combinacion (sucursal, generico) con ventas.
```

#### SheetStyle para Resumen Mensual

```python
SheetStyle(
    numeric_format="#,##0",
    column_formats={
        "Sucursal":            ColumnFormat(width=22),
        "Generico":            ColumnFormat(width=20),
        "Vtas Dia N-1":        ColumnFormat(number_format="#,##0", width=12, font_bold=True),
        "Vtas Dia N-2":        ColumnFormat(number_format="#,##0", width=12, font_bold=True),
        "Total Ventas":        ColumnFormat(number_format="#,##0", width=13, font_bold=True),
        "Tendencia":           ColumnFormat(number_format="#,##0", width=13, font_bold=True),
        "Ventas Mes Anterior":  ColumnFormat(number_format="#,##0", width=15, font_bold=True),
        "Ventas Mismo Mes AA":  ColumnFormat(number_format="#,##0", width=16, font_bold=True),
        "Objetivo":            ColumnFormat(number_format="#,##0", width=12, font_bold=True),
        "Tend vs Obj (%)":     ColumnFormat(number_format="#,##0.0", width=14, font_bold=True),
    },
    summary_rows=info_dias,  # dict retornado por calcular_info_dias(fecha_desde, fecha_hasta)
    as_table=True,
    table_style="TableStyleMedium9"
)
```

#### Endpoint POST /resumen-mensual/reporte

Request body:
```json
{
  "fecha_desde": "2026-02-01",
  "fecha_hasta": "2026-02-28",
  "genericos": ["CERVEZAS", "AGUAS DANONE"],
  "nombre_archivo": null,
  "con_objetivo": false
}
```

Response:
```json
{
  "ruta_archivo": "data/output/Resumen 28-02-2026.xlsx",
  "registros_procesados": 42,
  "sucursales": 7,
  "genericos_incluidos": ["CERVEZAS", "AGUAS DANONE"],
  "hojas": ["CERVEZAS", "AGUAS DANONE"]
}
```

#### Endpoint POST /resumen-mensual/reporte/download

Retorna el archivo `.xlsx` directamente:
```
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Content-Disposition: attachment; filename*=UTF-8''Resumen%2028-02-2026.xlsx
```

#### Subcomando CLI

```bash
# Con config JSON (recomendado)
python main.py resumen-mensual --config config_resumen.json

# Con args individuales
python main.py resumen-mensual --desde 2026-02-01 --hasta 2026-02-28
python main.py resumen-mensual --desde 2026-02-01 --hasta 2026-02-28 --genericos "CERVEZAS,AGUAS"
python main.py resumen-mensual --desde 2026-02-01 --hasta 2026-02-28 --no-slicers
```

Config JSON para resumen-mensual:
```json
{
  "fecha_desde": "2026-02-01",
  "fecha_hasta": "2026-02-28",
  "genericos": ["CERVEZAS", "AGUAS DANONE"],
  "nombre_archivo": null,
  "con_objetivo": false
}
```

---

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|------|------------------------|
| No hay ventas en el periodo | Retornar archivo con hojas vacias (sin filas de datos, solo cabecera y summary_rows) |
| Solo hay 1 dia con ventas | `Vtas Dia N-1` = ese dia, `Vtas Dia N-2` = 0 para todas las filas |
| No hay datos del ano anterior | Columna `Ventas Mismo Mes AA` = 0 para todas las filas (sin error) |
| `fecha_hasta` es hoy (mes en curso) | `Tendencia` usa `dias_habiles_transcurridos` calculados hasta hoy; `Dias Faltantes > 0` |
| `fecha_hasta` es fin de mes pasado | `factor_tendencia` = 1.0 (mes ya cerrado); `Dias Faltantes = 0` |
| `Objetivo = 0` | `Tend vs Obj (%)` = None (celda vacia); no dividir por cero |
| `con_objetivo = False` | Columnas `Objetivo` y `Tend vs Obj (%)` presentes pero con todos los valores None |
| Generico sin ventas en mes actual pero con ventas en AA | Incluir fila con `Total Ventas = 0`, `Tendencia = 0`, `Ventas Mismo Mes AA > 0` |
| Generico sin ventas en ningun periodo | Omitir la combinacion (no crear fila de ceros) |
| `CASA CENTRAL` con rutas mezcladas | Aplicar `_aplicar_zonas_virtuales` a los 3 DataFrames antes de unirlos |
| Fecha `fecha_desde` no es primer dia del mes | El sistema acepta cualquier rango; `Tendencia` y `Ventas Mismo Mes AA` usan el mismo rango desplazado 1 ano |
| Hoja con nombre de generico mayor a 31 caracteres | OpenPyXL trunca a 31 caracteres; el sistema debe truncar antes de llamar `add_sheet` para evitar error |
| `genericos` = lista vacia `[]` | Tratar como `None` (traer todos los genericos) |

---

## 7. Plan de Testing

### Unitarios (sin BD, con mocks)

- [ ] **Test RF-001**: `test_nombre_archivo_usa_ultima_fecha_venta` — verifica que el nombre del archivo sea `Resumen {fecha_max}.xlsx` cuando hay ventas; usa `fecha_hasta` como fallback si el DataFrame esta vacio. Valida RF-001.

- [ ] **Test RF-002**: `test_hojas_por_generico` — dado un DataFrame con 2 genericos distintos, verifica que `ExcelWriter.add_sheet` es llamado 2 veces con los nombres de esos genericos. Valida RF-002.

- [ ] **Test RF-003**: `test_filtro_genericos` — verifica que `data_loader.get_ventas_resumen_mensual` es llamado con la lista de genericos correcta. Valida RF-003.

- [ ] **Test RF-004**: `test_columnas_presentes_en_tabla` — verifica que el DataFrame resultante de `procesar_resumen_mensual` tiene exactamente las 9 columnas en el orden correcto. Valida RF-004.

- [ ] **Test RF-005**: `test_objetivo_none_cuando_desactivado` — con `con_objetivo=False`, verifica que las columnas `Objetivo` y `Tend vs Obj (%)` estan presentes y tienen valor `None` en todas las filas. Valida RF-005.

- [ ] **Test RF-009 y RF-010**: `test_detectar_dias_habiles_con_ventas` — dado un DataFrame con fechas incluyendo un domingo y un feriado, verifica que `_detectar_dias_habiles_con_ventas` devuelve correctamente los ultimos 2 dias habiles con ventas, excluyendo domingo y feriado. Valida RF-009, RF-010.

- [ ] **Test RF-009 y RF-010**: `test_vtas_dia_n1_n2_valores` — dado un DataFrame con ventas en 3 fechas conocidas, verifica que `Vtas Dia N-1` corresponde a la ultima fecha y `Vtas Dia N-2` a la penultima. Valida RF-009, RF-010.

- [ ] **Test RF-011**: `test_total_ventas_suma_periodo` — verifica que `Total Ventas` es la suma correcta de cantidades del periodo para una `(Sucursal, Generico)`. Valida RF-011.

- [ ] **Test RF-012**: `test_tendencia_con_factor_correcto` — mockeando `calcular_factor_tendencia` para devolver 2.0, verifica que `Tendencia = round(Total Ventas * 2.0)`. Valida RF-012.

- [ ] **Test RF-012**: `test_factor_tendencia_uno_cuando_cero_dias` — verifica que cuando `dias_habiles_transcurridos = 0`, el factor es 1.0 y `Tendencia = Total Ventas`. Valida RF-012.

- [ ] **Test RF-013**: `test_ventas_ma_desplazamiento_un_anio` — verifica que las fechas del ano anterior se calculan correctamente: `2026-02-01` → `2025-02-01`. Valida RF-013.

- [ ] **Test RF-013**: `test_ventas_ma_cero_cuando_falla_query` — mockeando `get_ventas_mismo_mes_anio_anterior` para lanzar `Exception`, verifica que la columna queda en 0 y no se propaga el error. Valida RF-013 + RNF-003.

- [ ] **Test RF-014**: `test_zonas_virtuales_aplicadas` — verifica que filas con `id_ruta=81` y sucursal `CASA CENTRAL` se renombran a `VALLE SALTA` en los 3 DataFrames. Valida RF-014.

- [ ] **Test RF-015**: `test_summary_rows_presentes` — verifica que `SheetStyle.summary_rows` contiene las 3 claves esperadas con valores enteros. Valida RF-015.

- [ ] **Test RF-007 edge case**: `test_combinacion_solo_en_ma_incluida` — si una combinacion tiene ventas solo en el ano anterior (no en el periodo actual), verifica que aparece en la tabla con `Total Ventas = 0` y `Ventas Mismo Mes AA > 0`. Valida RF-007.

- [ ] **Test RF-007 edge case**: `test_combinacion_sin_datos_omitida` — si una combinacion no tiene datos en ningun periodo, no aparece en la tabla. Valida RF-007.

- [ ] **Test edge case**: `test_nombre_hoja_truncado_31_chars` — verifica que nombres de generico mayores a 31 caracteres son truncados antes de crear la hoja. Valida constraint de OpenPyXL.

- [ ] **Test edge case**: `test_genericos_lista_vacia_trae_todos` — con `genericos=[]`, verifica que se llama a `get_ventas_resumen_mensual` con `genericos=None`. Valida edge case de configuracion.

- [ ] **Test RF-006 edge case**: `test_tend_vs_obj_none_cuando_objetivo_cero` — con `con_objetivo=True` y `Objetivo=0`, verifica que `Tend vs Obj (%)` es `None`. Valida RF-006.

- [ ] **Test RF-008**: `test_filas_ordenadas_por_sucursal_luego_generico` — dado un DataFrame desordenado, verifica que las filas resultantes estan ordenadas primero por Sucursal y luego por Generico. Valida RF-008.

### De integracion (requieren BD)

- [ ] **Test RF-001**: `test_generar_reporte_crea_archivo` — genera un reporte real y verifica que el archivo existe en `data/output/`. Valida RF-001.

- [ ] **Test RF-018**: `test_api_post_resumen_retorna_metadata` — hace POST al endpoint y verifica que la respuesta tiene las claves `ruta_archivo`, `registros_procesados`, `genericos_incluidos`, `hojas`. Valida RF-018.

---

## 8. Tareas de Implementacion

Las tareas deben implementarse en orden; cada una genera un commit atomico.

**Tarea 1 — Refactorizar zonas virtuales a modulo compartido**
- Mover `_aplicar_zonas_virtuales` y `_expandir_sucursales` de `src/services/ventas/service.py` a `src/core/zonas.py`.
- Actualizar el import en `src/services/ventas/service.py` para que use `from src.core.zonas import ...`.
- Verificar que los tests existentes de `VentasService` siguen pasando.
- Archivos: `src/core/zonas.py` (nuevo), `src/services/ventas/service.py` (modificado)

**Tarea 2 — Agregar metodos al DataLoader**
- Implementar `get_ventas_resumen_mensual(fecha_desde, fecha_hasta, genericos)`.
- Implementar `get_ventas_ultimos_dias_habiles(fecha_desde, fecha_hasta, genericos)`. Usar `fecha_hasta - 6 dias` como `fecha_desde` de la query (ventana de 7 dias calendario, suficiente para garantizar 2 dias habiles).
- Implementar `get_ventas_mes_anterior(fecha_desde, genericos)`. Calcula el rango del mes completo anterior y reutiliza la query de `get_ventas_resumen_mensual`.
- Implementar `get_ventas_mismo_mes_anio_anterior(fecha_desde_ma, fecha_hasta_ma, genericos)`. Puede reutilizar internamente `get_ventas_resumen_mensual`.
- Archivos: `src/core/data_loader.py`
- **Sin dependencias** (independiente de Tarea 1; la query SQL no requiere zonas virtuales)

**Tarea 3 — Crear processor de resumen mensual**
- Implementar `_detectar_dias_habiles_con_ventas(df, n)` en `processor.py`.
- Implementar `procesar_resumen_mensual(df_ventas_mes, df_dias, df_ventas_ma, info_dias, config)` que retorna un DataFrame con las 9 columnas de RF-004.
- Archivos: `src/services/resumen_mensual/processor.py` (nuevo)
- Depende de: Tarea 1, Tarea 2

**Tarea 4 — Crear ResumenMensualService**
- Implementar `ResumenMensualConfig`, `ResumenMensualResult`, `ResumenMensualService`.
- El servicio orquesta los 3 fetches, aplica zonas virtuales, llama al processor, y escribe con `ExcelWriter` (una hoja por generico).
- Implementar `__init__.py` del modulo con los exports.
- Archivos: `src/services/resumen_mensual/__init__.py` (nuevo), `src/services/resumen_mensual/service.py` (nuevo)
- Depende de: Tarea 3

**Tarea 5 — Actualizar exports y CLI**
- Actualizar `src/services/__init__.py` para exportar `ResumenMensualService`, `ResumenMensualConfig`, `ResumenMensualResult`.
- Agregar subcomando `resumen-mensual` a `main.py` con la funcion `cmd_resumen_mensual` y todos sus argumentos.
- Archivos: `src/services/__init__.py` (modificado), `main.py` (modificado)
- Depende de: Tarea 4

**Tarea 6 — Crear router FastAPI y registrar en app**
- Implementar `src/api/routes/resumen_mensual.py` con endpoints `POST /resumen-mensual/reporte` y `POST /resumen-mensual/reporte/download`.
- Actualizar `src/api/routes/__init__.py` para exportar `resumen_mensual_router`.
- Registrar el router en `api.py`.
- Actualizar `api.py` version a `2.1.0` y actualizar el mensaje de descripcion.
- Archivos: `src/api/routes/resumen_mensual.py` (nuevo), `src/api/routes/__init__.py` (modificado), `api.py` (modificado)
- Depende de: Tarea 4

**Tarea 7 — Tests unitarios**
- Implementar todos los tests unitarios del Plan de Testing en `tests/test_resumen_mensual.py`.
- Archivos: `tests/test_resumen_mensual.py` (nuevo)
- Depende de: Tarea 3, Tarea 4

---

## 9. Boundaries (Lo que NO hacer)

- NO modificar la estructura del reporte `VentasService` ni sus hojas `Ventas Bultos` / `Ventas HTLs`.
- NO agregar la columna `HTLs` al resumen mensual; este reporte es unicamente en bultos.
- NO crear tabla de objetivos en la base de datos en esta iteracion; solo agregar el placeholder `con_objetivo: bool = False`.
- NO agregar cobertura de preventistas a este reporte; no es parte del alcance.
- NO mover `COLUMN_NAMES` de `config/settings.py`; el resumen mensual define sus propios nombres de columna inline en el processor (no en settings, ya que son especificos de este reporte).
- NO cambiar el formato de nombre de archivo del reporte de ventas existente.
- NO agregar el campo `supervisores` al resumen mensual en esta iteracion.

---

## 10. Decisiones Abiertas

- [ ] **Nombre del metodo de zonas**: Decidir si `_aplicar_zonas_virtuales` va a `src/core/zonas.py` (modulo nuevo) o permanece en `src/services/ventas/service.py` con re-export. La opcion de `src/core/zonas.py` es mas limpia arquitecturalmente; la de re-export evita tocar `ventas/service.py`. Se recomienda `src/core/zonas.py`.

- [ ] **Consulta SQL para ultimos dias**: La Consulta 2 trae todo el periodo diario para poder detectar los 2 ultimos dias en Python. Si el periodo es de un mes completo con muchas sucursales y genericos, el volumen puede ser grande. Alternativa: traer solo los ultimos 7 dias calendario (suficiente para siempre incluir 2 dias habiles). La implementacion debe usar `fecha_hasta - 6 dias` como `fecha_desde` en la query, no el `fecha_desde` del reporte.

- [ ] **Combinaciones con ventas solo en AA**: RF-007 dice incluir filas si hay datos en alguno de los dos periodos. Confirmar si esta es la expectativa del usuario o si solo se quieren filas con ventas en el periodo actual.

- [ ] **Orden de hojas cuando `genericos` es None**: Cuando se traen todos los genericos, el orden de las hojas seguira el orden alfabetico de los genericos en la tabla. Confirmar si se prefiere otro orden (ej: por volumen de ventas descendente).

- [ ] **Nombre del subcomando CLI**: `resumen-mensual` (con guion, convencional en CLI) vs `resumen_mensual` (con guion bajo, consistente con el nombre del modulo Python). Se recomienda `resumen-mensual` para el CLI siguiendo convencion POSIX.
