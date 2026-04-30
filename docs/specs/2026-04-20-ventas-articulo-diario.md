# Spec: Ventas Artículo Diario

> **Estado:** DRAFT
> **Fecha:** 2026-04-20
> **Autor:** nahuel

---

## 1. Objetivo

Convertir el script hard-coded `medallion-etl/scripts/reporte_schneider710_diario.py` en un servicio reutilizable `ventas-articulo` que genera un XLSX de ventas diarias para CUALQUIER artículo y sucursal mediante configuración JSON, sin cambios de código por artículo.

---

## 2. Contexto

El script original produce un reporte diario de Schneider 710ml con fechas y ID de artículo cableados en el código. El equipo necesita el mismo reporte para otros artículos (e.g. distintas presentaciones, otras marcas) sin tener que copiar/modificar scripts. La solución encaja en la arquitectura existente: un nuevo `VentasArticuloService` heredando `BaseService`, un nuevo método `DataLoader.get_ventas_diarias_articulo()`, y un subcomando CLI `ventas-articulo` que acepta la misma estructura de config nueva (`tipo` + `filtros` + `reportes[]`).

El formato visual del XLSX (filas por día, domingo rosa, dias con venta celeste, total verde) ya fue validado por el usuario con el script original; este spec lo formaliza como contrato para la implementación.

---

## 3. Requisitos Funcionales

### 3.1 Config Model

- **RF-001**: Cuando `GlobalFilters` es instanciado, el sistema debe aceptar el campo opcional `id_articulo: int | None = None` con valor por defecto `None`.

- **RF-002**: Cuando `ReportConfig` es construido con `tipo`, el sistema debe aceptar el valor literal `"ventas-articulo"` como tipo válido (agregado al `Literal` existente).

- **RF-003**: Cuando `merge_filters(global_f, report_f)` es llamado y `global_f.id_articulo` tiene un valor distinto de `None`, el sistema debe incluir `"id_articulo": global_f.id_articulo` en el dict resultante.

- **RF-004**: Cuando `merge_filters` es llamado y `global_f.id_articulo` es `None`, el sistema debe incluir `"id_articulo": None` en el dict resultante (sin excepción ni KeyError).

### 3.2 DataLoader

- **RF-010**: Cuando `DataLoader.get_ventas_diarias_articulo(id_articulo, id_sucursal, fecha_desde, fecha_hasta)` es llamado, el sistema debe retornar un `pd.DataFrame` con exactamente las columnas `["fecha_comprobante", "bultos"]`.

- **RF-011**: Cuando `get_ventas_diarias_articulo` construye la consulta SQL, el sistema debe usar `sqlalchemy.text()` con parámetros nombrados (`:id_articulo`, `:id_sucursal`, `:fecha_desde`, `:fecha_hasta`) y nunca interpolar valores directamente en el string SQL.

- **RF-012**: Cuando el rango de fechas dado no contiene ventas para el artículo/sucursal indicados, el sistema debe retornar un `pd.DataFrame` vacío con las columnas `["fecha_comprobante", "bultos"]` (no `None`, no excepción).

- **RF-013**: Cuando `get_ventas_diarias_articulo` computa `bultos`, el sistema debe utilizar `SUM(cantidades_total)` como valor float sin aplicar `int()`, `round()`, ni `astype(int)` — conforme a la REGLA PRIMARIA del proyecto de no-redondeo.

### 3.3 Service

- **RF-020**: Cuando `VentasArticuloService.generar_reporte(config)` es llamado con un config válido, el sistema debe retornar un objeto `VentasArticuloResult`.

- **RF-021**: Cuando `VentasArticuloResult` es instanciado, el sistema debe exponer los campos:
  - `ruta_archivo: Path` — path al XLSX generado
  - `registros_procesados: int` — cantidad de filas de día escritas (igual a días del mes)
  - `dias_con_venta: int` — días con `bultos > 0`
  - `total_bultos: float` — suma de bultos del mes
  - `articulo_nombre: str` — descripción del artículo

- **RF-022**: Cuando `VentasArticuloService` es construido, el sistema debe aceptar `DataLoader` como argumento opcional en el constructor (`__init__(self, data_loader: DataLoader | None = None)`) — mismo patrón que `BaseService`.

- **RF-023**: Cuando el servicio necesita el nombre del artículo y el `id_articulo` existe en `gold.dim_articulo`, el sistema debe retornar la `des_articulo` correspondiente. Cuando el `id_articulo` no existe, el sistema debe retornar la cadena `f"Articulo {id_articulo}"` sin levantar excepción.

- **RF-024**: Cuando `generar_reporte` es llamado y `config` no contiene `id_articulo`, el sistema debe levantar `ValueError` con mensaje: `"id_articulo es requerido para ventas-articulo"`.

- **RF-025**: Cuando `generar_reporte` es llamado y `config` no contiene `id_sucursal`, el sistema debe levantar `ValueError` con mensaje: `"id_sucursal es requerido para ventas-articulo"`.

### 3.4 Processor / Salida Excel

- **RF-030**: Cuando el workbook es generado, el sistema debe contener exactamente 1 hoja cuyo nombre es `"{articulo_nombre} - {mes_nombre} {anio}"` truncado a 31 caracteres (límite de openpyxl).

- **RF-031**: Cuando la hoja es construida, la celda A1 debe estar combinada en el rango A1:C1 con el texto: `"{articulo_nombre} (id {id_articulo}) — Sucursal {id_sucursal} — {mes_nombre} {anio}"`.

- **RF-032**: Cuando los encabezados son escritos en la fila 3, el sistema debe colocar `["Día", "Fecha", "Bultos"]` con fill `#1F4E79`, fuente blanca, alineación centrada.

- **RF-033**: Cuando el contenido es escrito, el sistema debe generar exactamente una fila por cada día del mes (filas 4 a `4 + dias_del_mes - 1`), incluyendo días sin venta.

- **RF-034**: Cuando la columna "Día" es llenada, el sistema debe escribir el texto `"{dia} {dia_semana_abbr}"` (e.g. `"1 Mar"`, `"2 Mié"`) usando las abreviaturas en español de 3 letras.

- **RF-035**: Cuando la columna "Fecha" es llenada, el sistema debe escribir un valor de tipo `datetime.date` con `number_format = "DD/MM/YYYY"`.

- **RF-036**: Cuando un día tiene `bultos = 0`, el sistema debe escribir `None` en la celda de Bultos (celda en blanco). Cuando `bultos > 0`, el sistema debe escribir el valor numérico con `number_format = "#,##0"`.

- **RF-037**: Cuando una fila corresponde a un domingo, el sistema debe aplicar fill `#F2DCDB` (rosa) a todas sus celdas.

- **RF-038**: Cuando una fila corresponde a un día con `bultos > 0` y NO es domingo, el sistema debe aplicar fill `#D9E2F3` (celeste claro) a todas sus celdas.

- **RF-039**: Cuando una fila corresponde a un día laborable (lunes–sábado) con `bultos = 0`, el sistema debe aplicar fill `#F2F2F2` (gris) a todas sus celdas.

- **RF-040**: Cuando la fila TOTAL es escrita (última fila, inmediatamente después del último día), el sistema debe escribir:
  - Columna A: texto `"TOTAL"`
  - Columna B: texto `"{N} días con venta"` donde N = `dias_con_venta`
  - Columna C: suma numérica de todos los bultos con `number_format = "#,##0"`

- **RF-041**: Cuando la fila TOTAL es escrita, el sistema debe aplicar fill `#2D6A2E` (verde oscuro), fuente blanca y negrita a las tres celdas.

- **RF-042**: Cuando cualquier celda del cuerpo es escrita, el sistema debe aplicar borde fino (`thin`) en todos los lados con color `#B0B0B0`.

- **RF-043**: Cuando los anchos de columna son configurados, el sistema debe asignar: columna A = 12, columna B = 14, columna C = 12 (unidades de carácter de openpyxl).

### 3.5 CLI

- **RF-050**: Cuando `python main.py ventas-articulo --config <path>` es ejecutado, el sistema debe reconocerlo como subcomando válido y procesarlo.

- **RF-051**: Cuando el subcomando `ventas-articulo` es invocado sin `--config`, el sistema debe retornar con código de salida != 0 y emitir un mensaje de error indicando que `--config` es requerido.

- **RF-052**: Cuando `--config` apunta a un archivo con formato legacy (sin campos `tipo`, `reportes`, `filtros`), el sistema debe rechazarlo con un error descriptivo (solo acepta la estructura nueva).

- **RF-053**: Cuando `_run_reportes()` evalúa `report_config.tipo == "ventas-articulo"`, el sistema debe despachar la ejecución a `_run_ventas_articulo_report(report, merged)`.

- **RF-054**: Cuando `nombre_archivo` está presente en `ReportEntry.nombre`, el sistema debe guardar el archivo en `data/output/{nombre_archivo}.xlsx`. Cuando no está especificado (nombre vacío o no proporcionado), el sistema debe usar `data/output/{articulo_nombre} - {mes_nombre} {anio}.xlsx`.

### 3.6 Integridad de Datos (REGLA PRIMARIA)

- **RF-060**: Cuando `bultos` es almacenado, computado o escrito, el sistema NO debe aplicar `int()`, `round()`, ni `.astype(int)` en ningún punto del pipeline (DataLoader → Service → Processor → Excel). El redondeo visual es responsabilidad exclusiva del `number_format` de la celda openpyxl.

---

## 4. Requisitos No Funcionales

- **RNF-001**: `get_ventas_diarias_articulo` debe ejecutarse en menos de 5 segundos para un mes completo en la base de datos de producción (índice esperado en `id_articulo` + `id_sucursal` + `fecha_comprobante`).

- **RNF-002**: El XLSX generado debe ser abridor con LibreOffice Calc y Microsoft Excel sin advertencias de formato corrompido.

- **RNF-003**: `VentasArticuloService` debe ser unit-testable inyectando un `DataLoader` con engine mock; ningún test debe requerir conexión a la base de datos.

- **RNF-004**: El código nuevo debe seguir los paths de import del proyecto: `from src.services.ventas_articulo.service import VentasArticuloService`.

---

## 5. Diseño Técnico

### 5.1 Modelo de Datos

#### Cambio en `src/config/models.py`

```python
class GlobalFilters(BaseModel):
    # ... campos existentes ...
    id_articulo: int | None = None   # NUEVO
```

```python
class ReportConfig(BaseModel):
    tipo: Literal[
        "ventas", "resumen-mensual", "mision-imposible",
        "historico-fratelli", "stock-diario", "cartesiano",
        "avances", "graficos-cobertura",
        "ventas-articulo",   # NUEVO
    ]
```

#### Nuevo dataclass de resultado

```python
@dataclass
class VentasArticuloResult:
    ruta_archivo: Path
    registros_procesados: int   # días del mes escritos
    dias_con_venta: int
    total_bultos: float
    articulo_nombre: str
```

#### Query SQL (`get_ventas_diarias_articulo`)

```sql
SELECT
    fecha_comprobante,
    SUM(cantidades_total) AS bultos
FROM gold.fact_ventas
WHERE id_articulo     = :id_articulo
  AND id_sucursal     = :id_sucursal
  AND fecha_comprobante >= :fecha_desde
  AND fecha_comprobante <= :fecha_hasta
GROUP BY fecha_comprobante
ORDER BY fecha_comprobante
```

#### Query SQL (nombre artículo, helper privado)

```sql
SELECT des_articulo
FROM gold.dim_articulo
WHERE id_articulo = :id_articulo
LIMIT 1
```

### 5.2 Arquitectura

El servicio nuevo se integra en la cadena estándar del proyecto:

```
main.py
  ventas-articulo subcommand
    └─ _run_reportes()
         └─ _run_ventas_articulo_report(report, merged)
              └─ VentasArticuloService.generar_reporte(config)
                   ├─ DataLoader.get_ventas_diarias_articulo(...)
                   ├─ DataLoader._get_articulo_nombre(id_articulo)   [privado]
                   └─ _build_workbook(articulo_nombre, ventas_df, config)
                        └─ openpyxl directo (sin ExcelWriter wrapper)
```

Árbol de archivos nuevos:

```
src/services/ventas_articulo/
    __init__.py
    service.py        ← VentasArticuloService, VentasArticuloConfig, VentasArticuloResult
    processor.py      ← _build_workbook(), helpers de formato
```

`VentasArticuloConfig` es un dataclass simple (no Pydantic) equivalente a los otros configs de servicio:

```python
@dataclass
class VentasArticuloConfig:
    id_articulo: int
    id_sucursal: int
    fecha_desde: str
    fecha_hasta: str
    nombre_archivo: str | None = None
```

### 5.3 API / Interfaz

#### `VentasArticuloService.generar_reporte(config: VentasArticuloConfig) -> VentasArticuloResult`

Input:

```python
VentasArticuloConfig(
    id_articulo=23179,
    id_sucursal=1,
    fecha_desde="2026-04-01",
    fecha_hasta="2026-04-30",
    nombre_archivo=None,   # usa nombre automático
)
```

Output:

```python
VentasArticuloResult(
    ruta_archivo=Path("data/output/Schneider 710ml - Abril 2026.xlsx"),
    registros_procesados=30,
    dias_con_venta=17,
    total_bultos=1234.5,
    articulo_nombre="Schneider 710ml",
)
```

#### Config JSON de ejemplo

```json
{
    "tipo": "ventas-articulo",
    "filtros": {
        "fecha_desde": "2026-04-01",
        "fecha_hasta": "2026-04-30",
        "id_articulo": 23179,
        "id_sucursal": 1
    },
    "reportes": [
        {
            "nombre": "Schneider 710 - Abril 2026"
        }
    ]
}
```

#### `_run_ventas_articulo_report(report, merged) -> list[tuple[Path, dict]]`

Construye `VentasArticuloConfig` desde `merged`, llama `VentasArticuloService().generar_reporte(config)`, retorna `[(Path(result.ruta_archivo), {"nombre": report.nombre, "fecha": merged["fecha_hasta"]})]`.

---

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|------|------------------------|
| Mes sin ventas (bultos = 0 todos los días) | XLSX generado con 30/28/31 filas, columna Bultos toda en blanco, TOTAL = "0 días con venta" / 0 |
| `id_articulo` no existe en `dim_articulo` | `articulo_nombre = f"Articulo {id_articulo}"`, XLSX generado normalmente |
| `id_articulo` ausente en config | `ValueError: "id_articulo es requerido para ventas-articulo"` |
| `id_sucursal` ausente en config | `ValueError: "id_sucursal es requerido para ventas-articulo"` |
| Febrero no bisiesto (28 días) | 28 filas de día + fila TOTAL = 29 filas de contenido (fila 3 headers + fila 1 título = 31 total) |
| Febrero bisiesto (29 días) | 29 filas de día + fila TOTAL |
| Nombre de hoja > 31 chars | Truncado silenciosamente a 31 chars |
| `bultos` con decimales (e.g. 1234.5) | Valor float preservado; `#,##0` en openpyxl muestra redondeado visualmente pero no modifica el dato |
| `nombre_archivo` vacío string `""` | Usar nombre automático (tratado igual que `None`) |
| Config formato legacy (sin `tipo`/`reportes`) | Error descriptivo con instrucción de usar formato nuevo |

---

## 7. Plan de Testing

### Unitarios — `tests/test_ventas_articulo_service.py`

- [ ] **Test-U01**: `generar_reporte` con mes normal y ventas → `dias_con_venta > 0`, `total_bultos > 0.0`, archivo creado → valida RF-020, RF-021
- [ ] **Test-U02**: `generar_reporte` con DataFrame vacío → XLSX generado, `dias_con_venta = 0`, `total_bultos = 0.0` → valida RF-012, RF-040
- [ ] **Test-U03**: `generar_reporte` sin `id_articulo` → `ValueError` con mensaje correcto → valida RF-024
- [ ] **Test-U04**: `generar_reporte` sin `id_sucursal` → `ValueError` con mensaje correcto → valida RF-025
- [ ] **Test-U05**: `_get_articulo_nombre` con ID inexistente → retorna `"Articulo 99999999"` → valida RF-023

### Unitarios — `tests/test_ventas_articulo_processor.py`

- [ ] **Test-U06**: Febrero 2026 (28 días) → hoja con 28 filas de día + fila TOTAL (29 filas de contenido) → valida RF-033
- [ ] **Test-U07**: Domingo en rango → fill `#F2DCDB` en toda la fila → valida RF-037
- [ ] **Test-U08**: Día con bultos > 0 (no domingo) → fill `#D9E2F3` → valida RF-038
- [ ] **Test-U09**: Día con bultos = 0 (lunes) → fill `#F2F2F2` y celda Bultos = None → valida RF-036, RF-039
- [ ] **Test-U10**: Fila TOTAL → fill `#2D6A2E`, fuente blanca negrita, col B = `"{N} días con venta"` → valida RF-040, RF-041
- [ ] **Test-U11**: Nombre de hoja con > 31 chars → nombre truncado a 31 → valida RF-030
- [ ] **Test-U12**: Título en A1:C1 con texto correcto → valida RF-031
- [ ] **Test-U13**: Encabezados fila 3 con fill `#1F4E79` → valida RF-032
- [ ] **Test-U14**: Columna widths A=12, B=14, C=12 → valida RF-043
- [ ] **Test-U15**: `bultos` nunca pasa por `int()`/`round()`/`astype(int)` (verificar código + valor float en df) → valida RF-060

### Unitarios — `tests/test_data_loader_articulo.py`

- [ ] **Test-U16**: `get_ventas_diarias_articulo` con engine mock → SQL usa parámetros nombrados (`:id_articulo`) → valida RF-011
- [ ] **Test-U17**: Resultado vacío → DataFrame con columnas `["fecha_comprobante", "bultos"]` no None → valida RF-012
- [ ] **Test-U18**: Columna `bultos` es dtype float64 → valida RF-013

### Unitarios — `tests/test_config_models_articulo.py`

- [ ] **Test-U19**: `GlobalFilters` con `id_articulo=23179` → campo accesible → valida RF-001
- [ ] **Test-U20**: `GlobalFilters` sin `id_articulo` → valor `None` por defecto → valida RF-001
- [ ] **Test-U21**: `ReportConfig` con `tipo="ventas-articulo"` → válido sin error Pydantic → valida RF-002
- [ ] **Test-U22**: `merge_filters` con `id_articulo=23179` en global → `merged["id_articulo"] == 23179` → valida RF-003
- [ ] **Test-U23**: `merge_filters` sin `id_articulo` → `merged["id_articulo"] is None` sin KeyError → valida RF-004

### Escenarios de aceptación

- [ ] **Escenario-1 (Happy path — mes con ventas)**: Config `id_articulo=23179, id_sucursal=1, fecha_desde="2026-04-01", fecha_hasta="2026-04-30"` → XLSX con 30 filas de día + título + encabezados + total, 15-20 días con fill celeste, domingos (5, 12, 19, 26 de abril) con fill rosa, fila TOTAL verde con `N días con venta` correcto → valida RF-030–RF-043
- [ ] **Escenario-2 (Mes vacío)**: Artículo sin ventas en el rango → XLSX con 30 filas, todas en gris, columna Bultos toda en blanco, fila TOTAL = "0 días con venta" / celda C = 0 → valida RF-012, RF-036, RF-040
- [ ] **Escenario-3 (Artículo desconocido)**: `id_articulo=99999999` → XLSX generado con título "Articulo 99999999 (...)", sin excepción → valida RF-023
- [ ] **Escenario-4 (Falta id_articulo)**: Config sin `id_articulo` → `ValueError` con mensaje `"id_articulo es requerido para ventas-articulo"` → valida RF-024
- [ ] **Escenario-5 (Febrero 28 días)**: `fecha_desde="2026-02-01", fecha_hasta="2026-02-28"` → XLSX con exactamente 28 filas de día + 1 fila TOTAL en posición 32 (con header en fila 3, título en fila 1, fila 2 vacía) → valida RF-033

---

## 8. Tareas de Implementación

1. **Agregar `id_articulo` a `GlobalFilters` y `"ventas-articulo"` al `Literal` de `ReportConfig.tipo`** — Archivos: `src/config/models.py`

2. **Propagar `id_articulo` en `merge_filters`** — Archivos: `src/config/resolver.py` — Depende de: Tarea 1

3. **Agregar `get_ventas_diarias_articulo()` y helper `_get_articulo_nombre()` a `DataLoader`** — Archivos: `src/core/data_loader.py`

4. **Crear `src/services/ventas_articulo/` con `__init__.py`, `service.py` (`VentasArticuloService`, `VentasArticuloConfig`, `VentasArticuloResult`), `processor.py` (`_build_workbook`)** — Archivos: `src/services/ventas_articulo/__init__.py`, `src/services/ventas_articulo/service.py`, `src/services/ventas_articulo/processor.py` — Depende de: Tareas 1, 2, 3

5. **Agregar subcomando `ventas-articulo` al CLI y función `_run_ventas_articulo_report`** — Archivos: `main.py` — Depende de: Tarea 4

6. **Agregar despacho `tipo == "ventas-articulo"` en `_run_reportes()`** — Archivos: `main.py` — Depende de: Tarea 5

7. **Tests unitarios de modelos y resolver** — Archivos: `tests/test_config_models_articulo.py` — Depende de: Tareas 1, 2

8. **Tests unitarios de DataLoader** — Archivos: `tests/test_data_loader_articulo.py` — Depende de: Tarea 3

9. **Tests unitarios de processor** — Archivos: `tests/test_ventas_articulo_processor.py` — Depende de: Tarea 4

10. **Tests unitarios de service** — Archivos: `tests/test_ventas_articulo_service.py` — Depende de: Tarea 4

---

## 9. Boundaries (Lo que NO hacer)

- NO modificar la lógica de `VentasService` ni sus tests existentes.
- NO usar `ExcelWriter` ni `SheetStyle` del core — este reporte usa openpyxl directamente por su layout atípico (celda-a-celda con colores condicionales por fila).
- NO agregar slicers ni cobertura (`con_slicers`, `con_cobertura` no aplican a este reporte).
- NO soportar múltiples artículos por config (1 config = 1 artículo = 1 XLSX).
- NO modificar el script `medallion-etl/scripts/reporte_schneider710_diario.py` original.
- NO agregar entrega (email/WhatsApp) como parte de esta feature: el pipeline de delivery existente cubre eso automáticamente si `enviar_a` está configurado en el `ReportEntry`.
- NO tocar `src/services/__init__.py` si no es necesario para el import público.
- NO agregar campo `id_articulo` a `ReportFilters` (solo en `GlobalFilters` por ahora, un artículo por config).

---

## 10. Decisiones Abiertas

- [ ] **Fila 2 vacía**: El script original tiene una fila vacía entre el título (fila 1) y los encabezados (fila 3). Confirmar si esta fila es intencional o es un artifact del script. La spec la preserva por fidelidad visual, pero podría eliminarse.

- [ ] **Abreviaturas de días en español**: El script usa `["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]`. Confirmar si se usan estas abreviaturas exactas o las del locale del sistema. La spec asume las abreviaturas hard-coded para consistencia cross-platform.

- [ ] **`nombre_archivo` en config**: El campo `ReportEntry.nombre` se usa como nombre de archivo. Si el usuario quiere un nombre de archivo diferente al nombre del reporte en la UI, se necesitaría un campo `nombre_archivo` en `ReportEntry`. Por ahora se asume que `nombre` sirve como ambos.

- [ ] **Zona horaria de `fecha_comprobante`**: Verificar si `gold.fact_ventas.fecha_comprobante` es `DATE` o `TIMESTAMP`. Si es `TIMESTAMP`, el GROUP BY debe truncar a fecha para no generar múltiples filas por día.
