# Spec: Reporte General Badie

> **Estado:** DRAFT
> **Fecha:** 2026-04-23
> **Autor:** nahuel

---

## 1. Objetivo

Construir el servicio `reporte-general-badie` que genera un único XLSX mensual con los KPIs CCU por sucursal (mix de genericos, variación YoY, cobertura de clientes cervezas) donde el mes de análisis se selecciona desde una celda dropdown del propio Excel, sin modificar el archivo de código.

---

## 2. Contexto

El equipo de Badie necesita un reporte mensual consolidado de los 4 genericos CCU (CERVEZAS, AGUAS DANONE, VINOS CCU, SIDRAS Y LICORES) con visión de mix porcentual y variación interanual. El diseño "auditable" requiere que los datos crudos estén en hojas de raw data y que la hoja de presentación use fórmulas SUMIFS/COUNTIFS sobre esos datos, de modo que el usuario pueda cambiar el mes desde un dropdown y todas las columnas recalculen automáticamente sin re-ejecutar el script.

Los comprobantes de tipo `PRVTA` (preventista) son internas y deben excluirse de los conteos de cobertura de clientes.

---

## 3. Requisitos Funcionales

### 3.1 Módulo y slug

**RF-001**: El servicio SHALL residir en `src/services/reporte_general_badie/` y exponer `SERVICE_SLUG = "reporte-general-badie"`. El directorio de salida SHALL computarse vía `service_output_dir("reporte-general-badie", fecha_desde, "month")`, produciendo `data/output/reporte-general-badie/{YYYY-MM}/`.

### 3.2 DataLoader — ventas mensuales CCU

**RF-002**: `DataLoader.get_ventas_mensuales_ccu(fecha_desde: str, fecha_hasta: str) -> pd.DataFrame` SHALL retornar un DataFrame con exactamente las columnas:

| Columna | Tipo SQL | Descripción |
|---------|----------|-------------|
| `sucursal` | str | `dim_sucursal.descripcion` |
| `generico` | str | `dim_articulo.generico` |
| `anio` | int | `EXTRACT(YEAR FROM fv.fecha_comprobante)` |
| `mes` | int | `EXTRACT(MONTH FROM fv.fecha_comprobante)` |
| `bultos` | float | `SUM(fv.cantidades_total)` |

El método SHALL filtrar `da.generico IN ('CERVEZAS', 'AGUAS DANONE', 'VINOS CCU', 'SIDRAS Y LICORES')` de forma fija (sin parámetro de genericos). La ventana de fechas SHALL cubrir tanto el período seleccionado como el mismo período del año anterior en una sola consulta: `fecha_desde` → primer día del año anterior al año de `fecha_desde`, `fecha_hasta` → último día del mes de `fecha_hasta`. Es decir, si el config tiene `fecha_desde="2026-01-01"` y `fecha_hasta="2026-04-30"`, la query debe traer desde `2024-01-01` hasta `2026-04-30` para incluir todos los meses necesarios para el dropdown y para el YoY. El parámetro `fecha_desde` que llega al método es ya la fecha expandida; el caller (service) calcula esta expansión.

**RF-003**: La consulta de RF-002 SHALL usar `sqlalchemy.text()` con parámetros nombrados (`:desde`, `:hasta`) y NO interpolar valores directamente en el string SQL.

**RF-004**: La consulta de RF-002 SHALL incluir el filtro `AND fv.id_documento != 'PRVTA'` en el WHERE de `fact_ventas`.

### 3.3 DataLoader — cobertura de clientes cervezas

**RF-005**: `DataLoader.get_cobertura_clientes_cervezas(fecha_desde: str, fecha_hasta: str) -> pd.DataFrame` SHALL retornar un DataFrame con exactamente las columnas:

| Columna | Tipo SQL | Descripción |
|---------|----------|-------------|
| `sucursal` | str | `dim_sucursal.descripcion` |
| `anio` | int | `EXTRACT(YEAR FROM fv.fecha_comprobante)` |
| `mes` | int | `EXTRACT(MONTH FROM fv.fecha_comprobante)` |
| `id_cliente` | int | `fv.id_cliente` |
| `bultos` | float | `SUM(fv.cantidades_total)` — agrupado por cliente/mes |

El método SHALL filtrar `da.generico = 'CERVEZAS'` y `AND fv.id_documento != 'PRVTA'`. La ventana de fechas SHALL aplicar la misma expansión que RF-002 (el caller pasa las fechas ya expandidas).

**RF-006**: Cuando `get_cobertura_clientes_cervezas` recibe un rango sin datos, SHALL retornar un DataFrame vacío con las columnas `["sucursal", "anio", "mes", "id_cliente", "bultos"]`, no `None` ni levantar excepción.

### 3.4 PRVTA exclusion

**RF-007**: Cuando cualquier query de este servicio consulta `gold.fact_ventas`, el sistema SHALL incluir `AND fv.id_documento != 'PRVTA'` en el WHERE. Esta condición aplica a AMBOS métodos del DataLoader (`get_ventas_mensuales_ccu` y `get_cobertura_clientes_cervezas`) y a ningún otro servicio existente.

### 3.5 Hoja raw "VentasCCU"

**RF-008**: El workbook SHALL contener una hoja llamada exactamente `"VentasCCU"` con los datos crudos de ventas mensuales CCU cargados como tabla openpyxl con nombre `"TblVentasCCU"`. Las columnas SHALL aparecer en este orden:

`sucursal | generico | anio | mes | bultos`

Los tipos de celda SHALL ser: `sucursal` → string, `generico` → string, `anio` → int, `mes` → int, `bultos` → float (sin `int()`, sin `round()`).

**RF-009**: Si `get_ventas_mensuales_ccu` retorna un DataFrame vacío, la hoja `"VentasCCU"` SHALL crearse igualmente con los encabezados de columna pero sin filas de datos, y la tabla SHALL tener cero filas de datos.

### 3.6 Hoja raw "CoberturaCervezas"

**RF-010**: El workbook SHALL contener una hoja llamada exactamente `"CoberturaCervezas"` con los datos de cobertura de clientes cargados como tabla openpyxl con nombre `"TblCoberturaCervezas"`. Las columnas SHALL aparecer en este orden:

`sucursal | anio | mes | id_cliente | bultos`

Los tipos de celda SHALL ser: `sucursal` → string, `anio` → int, `mes` → int, `id_cliente` → int, `bultos` → float.

**RF-011**: Si `get_cobertura_clientes_cervezas` retorna un DataFrame vacío, la hoja `"CoberturaCervezas"` SHALL crearse igualmente con encabezados y cero filas de datos.

### 3.7 Hoja de presentación "Reporte"

**RF-012**: El workbook SHALL contener una hoja llamada exactamente `"Reporte"`. Esta hoja SHALL ser la primera hoja en el workbook (índice 0). Las hojas raw (`"VentasCCU"`, `"CoberturaCervezas"`) SHALL estar a continuación.

**RF-013**: La hoja "Reporte" SHALL tener la siguiente estructura de filas fija:

| Fila | Contenido |
|------|-----------|
| 1 | Título: texto `"Reporte General Badie"` en celda A1, fuente negrita tamaño 14 |
| 2 | Etiqueta `"Mes:"` en celda A2; dropdown de mes en celda B2 (ver RF-014) |
| 3 | Vacía (separador visual) |
| 4 | Encabezados de columna (ver RF-016) |
| 5+ | Una fila por sucursal física, con fórmulas (ver RF-017) |

**RF-014**: La celda B2 SHALL tener un `openpyxl.worksheet.datavalidation.DataValidation` de tipo `"list"` con `formula1` construida como una lista de strings de meses en formato `"AAAA-MM"` separados por coma y encerrada en comillas dobles. El rango de meses SHALL cubrir desde `2024-01` hasta el mes correspondiente a `fecha_hasta` del config (inclusive). El valor inicial de B2 SHALL ser el string del mes de `fecha_hasta` (e.g., `"2026-04"`).

Ejemplo de `formula1` con dos meses: `'"2024-01,2024-02"'`

**RF-015**: La celda B2 SHALL tener `data_validation.showDropDown = False` para que la flecha del dropdown sea visible en Excel y LibreOffice.

**RF-016**: La fila 4 SHALL tener los siguientes encabezados en columnas A–H, con fill de fondo `#1F4E79` y fuente blanca, negrita:

| Col | Encabezado |
|-----|-----------|
| A | `Sucursal` |
| B | `Total CCU` |
| C | `% Cerveza` |
| D | `% Aguas Danone` |
| E | `% Multi CCU` |
| F | `% Variación YoY` |
| G | `Cobertura Normal` |
| H | `Cobertura ≥1 Bulto` |

**RF-017**: Cada fila de sucursal (fila 5 en adelante) SHALL contener fórmulas que referencian la celda B2 para el mes seleccionado. Sea `r` el número de fila de la sucursal (5, 6, 7, …) y sea `A{r}` la celda con el nombre de la sucursal (valor string literal, NO fórmula):

- **Columna A**: Nombre de sucursal (string literal, valor de `dim_sucursal.descripcion`)
- **Columna B (Total CCU)**: SUMIFS sobre `TblVentasCCU` sumando los 4 genericos para la sucursal y mes seleccionado. Ver RF-018.
- **Columna C (% Cerveza)**: SUMIFS solo CERVEZAS dividido B{r}. Ver RF-019.
- **Columna D (% Aguas Danone)**: SUMIFS solo AGUAS DANONE dividido B{r}. Ver RF-019.
- **Columna E (% Multi CCU)**: SUMIFS VINOS CCU + SIDRAS Y LICORES dividido B{r}. Ver RF-019.
- **Columna F (% Variación YoY)**: ver RF-020.
- **Columna G (Cobertura Normal)**: COUNTIFS clientes con bultos > 0 en CERVEZAS. Ver RF-021.
- **Columna H (Cobertura ≥1 Bulto)**: COUNTIFS clientes con bultos > 1 en CERVEZAS. Ver RF-022.

### 3.8 Fórmula SUMIFS — Total CCU

**RF-018**: La celda B{r} SHALL contener la siguiente fórmula Excel (o equivalente funcional). El mes se extrae de B2 con funciones TEXT/VALUE. La fórmula usa dos columnas auxiliares de TblVentasCCU: `anio` y `mes`.

```
=SUMPRODUCT(
    (TblVentasCCU[sucursal]=A{r})*
    (TblVentasCCU[anio]=YEAR(DATE(VALUE(LEFT($B$2,4)),VALUE(MID($B$2,6,2)),1)))*
    (TblVentasCCU[mes]=VALUE(MID($B$2,6,2)))*
    TblVentasCCU[bultos]
)
```

Nota: Se usa SUMPRODUCT en lugar de SUMIFS porque SUMIFS no soporta múltiples criterios OR sobre la misma columna (`generico`). El Total CCU suma los 4 genericos implícitamente (no filtra por generico).

**RF-019**: Las celdas C{r}, D{r} SHALL usar la misma estructura SUMPRODUCT que RF-018 pero con filtro adicional `*(TblVentasCCU[generico]="CERVEZAS")` (o "AGUAS DANONE") dividido por `B{r}`. La celda E{r} (% Multi CCU) SHALL sumar VINOS CCU + SIDRAS Y LICORES: `(SUMPRODUCT(…generico="VINOS CCU"…) + SUMPRODUCT(…generico="SIDRAS Y LICORES"…)) / B{r}`. Cuando `B{r} = 0`, las celdas de porcentaje SHALL mostrar `""` (string vacío) usando `IF(B{r}=0,"",…)`.

### 3.9 Fórmula % Variación YoY

**RF-020**: La celda F{r} SHALL calcular la variación interanual para la misma sucursal y mismo mes-del-año pero del año anterior. La fórmula SHALL:

1. Calcular `bultos_mes_actual` = Total CCU para el año y mes de B2 (idéntico a B{r}).
2. Calcular `bultos_anio_anterior` = SUMPRODUCT sobre TblVentasCCU con `anio = YEAR(B2_date) - 1` y `mes = mes de B2`.
3. Retornar `(bultos_mes_actual - bultos_anio_anterior) / bultos_anio_anterior`.
4. Cuando `bultos_anio_anterior = 0` (no hay datos del año anterior), la celda SHALL mostrar `""` (string vacío): `IF(bultos_anio_anterior=0,"",…)`.

El `number_format` de la columna F SHALL ser `"0.0%"`.

### 3.10 Fórmulas COUNTIFS — Cobertura

**RF-021**: La celda G{r} (Cobertura Normal) SHALL contar clientes distintos con `bultos > 0` en CERVEZAS para la sucursal y mes seleccionado. Dado que COUNTIFS no cuenta valores distintos, el servicio SHALL usar SUMPRODUCT con una construcción de conteo de únicos:

```
=SUMPRODUCT(
    (TblCoberturaCervezas[sucursal]=A{r})*
    (TblCoberturaCervezas[anio]=YEAR(DATE(VALUE(LEFT($B$2,4)),VALUE(MID($B$2,6,2)),1)))*
    (TblCoberturaCervezas[mes]=VALUE(MID($B$2,6,2)))*
    (TblCoberturaCervezas[bultos]>0)/
    COUNTIFS(
        TblCoberturaCervezas[sucursal],A{r},
        TblCoberturaCervezas[anio],YEAR(DATE(VALUE(LEFT($B$2,4)),VALUE(MID($B$2,6,2)),1)),
        TblCoberturaCervezas[mes],VALUE(MID($B$2,6,2)),
        TblCoberturaCervezas[id_cliente],TblCoberturaCervezas[id_cliente],
        TblCoberturaCervezas[bultos],">"&0
    )
)
```

Cuando el denominador del COUNTIFS produce 0 para alguna fila (no hay clientes con bultos>0 en esa combinación), la fórmula SHALL manejar la división por cero retornando 0 o usando IFERROR. El `number_format` SHALL ser `"#,##0"`.

**RF-022**: La celda H{r} (Cobertura ≥1 Bulto) SHALL usar la misma estructura que RF-021 pero con `bultos > 1` en lugar de `bultos > 0`. La lógica de deduplicación de clientes aplica igualmente.

### 3.11 Formatos numéricos de la hoja Reporte

**RF-023**: Los `number_format` de las celdas de la hoja "Reporte" SHALL ser:

| Columna | `number_format` |
|---------|----------------|
| B (Total CCU) | `"#,##0"` |
| C, D, E (%) | `"0.0%"` |
| F (YoY) | `"0.0%"` |
| G, H (Cobertura) | `"#,##0"` |

Los valores numéricos NO deben pasar por `int()`, `round()`, ni `astype(int)` en ninguna parte del pipeline (regla primaria del proyecto).

### 3.12 Sucursales físicas

**RF-024**: La lista de sucursales en la columna A de la hoja "Reporte" SHALL obtenerse de `DataLoader.get_sucursales()` (método existente), que retorna `dim_sucursal.descripcion` ordenadas. No se aplican zonas virtuales. La columna A contendrá exactamente los valores presentes en `dim_sucursal` sin filtros adicionales, ordenadas alfabéticamente.

### 3.13 Archivo de salida

**RF-025**: El archivo generado SHALL escribirse en:
```
data/output/reporte-general-badie/{YYYY-MM}/Reporte General Badie.xlsx
```
donde `{YYYY-MM}` se deriva de `fecha_desde`. El directorio SHALL crearse si no existe (`mkdir(parents=True, exist_ok=True)`). Si el archivo ya existe, SHALL sobrescribirse.

### 3.14 Resultado del servicio

**RF-026**: `ReporteGeneralBadieService.generar_reporte(config)` SHALL retornar un dataclass `ReporteGeneralBadieResult` con los campos:

```python
@dataclass
class ReporteGeneralBadieResult:
    ruta_archivo: Path
    registros_ventas: int      # filas en TblVentasCCU
    registros_cobertura: int   # filas en TblCoberturaCervezas
    sucursales: int            # cantidad de sucursales en columna A
    meses_en_dropdown: int     # cantidad de meses en el DataValidation
```

### 3.15 Integración CLI

**RF-027**: Cuando `python main.py reporte-general-badie --config <path>` es ejecutado, el sistema SHALL reconocerlo como subcomando válido y procesarlo. El subcomando SHALL requerir `--config` obligatoriamente (no acepta args individuales `--desde`/`--hasta`).

**RF-028**: `main.py` SHALL registrar el handler `"reporte-general-badie": "_run_reporte_general_badie_report"` en `REPORT_HANDLERS` y la función `_run_reporte_general_badie_report(report, merged) -> list[tuple[Path, dict]]` que construye la config y llama al servicio.

### 3.16 Config models

**RF-029**: `src/config/models.py` SHALL agregar `"reporte-general-badie"` al `Literal` del campo `tipo` de `ReportConfig`. No se requiere ningún campo nuevo en `GlobalFilters` ni `ReportFilters` — el servicio solo usa `fecha_desde` y `fecha_hasta`.

---

## 4. Requisitos No Funcionales

- **RNF-001**: `get_ventas_mensuales_ccu` y `get_cobertura_clientes_cervezas` deben ejecutarse en menos de 15 segundos cada uno en producción para un rango de ~28 meses (2024-01 al mes actual).
- **RNF-002**: El XLSX generado debe abrirse sin errores ni advertencias en LibreOffice Calc 7.x y Microsoft Excel 2016+.
- **RNF-003**: `ReporteGeneralBadieService` debe ser unit-testable inyectando un `DataLoader` mock; ningún test debe requerir conexión a la base de datos.
- **RNF-004**: El dropdown de mes debe funcionar correctamente en LibreOffice Calc (el atributo `showDropDown = False` es obligatorio para compatibilidad).
- **RNF-005**: Los imports deben seguir el patrón del proyecto: `from src.services.reporte_general_badie.service import ReporteGeneralBadieService`.

---

## 5. Diseño Técnico

### 5.1 Modelo de Datos

#### Cambio en `src/config/models.py`

```python
class ReportConfig(BaseModel):
    tipo: Literal[
        "ventas", "resumen-mensual", "champions-league",
        "historico-fratelli", "stock-diario", "cartesiano",
        "avances", "graficos-cobertura", "ventas-articulo",
        "historico-cliente",
        "reporte-general-badie",   # NUEVO
    ]
```

#### Nuevo dataclass de config

```python
@dataclass
class ReporteGeneralBadieConfig:
    fecha_desde: str    # "YYYY-MM-DD", primer día del mes a reportar
    fecha_hasta: str    # "YYYY-MM-DD", último día del mes a reportar
    nombre_archivo: str | None = None
```

#### Nuevo dataclass de resultado

```python
@dataclass
class ReporteGeneralBadieResult:
    ruta_archivo: Path
    registros_ventas: int
    registros_cobertura: int
    sucursales: int
    meses_en_dropdown: int
```

#### Query SQL — `get_ventas_mensuales_ccu`

```sql
SELECT
    ds.descripcion                    AS sucursal,
    da.generico,
    EXTRACT(YEAR FROM fv.fecha_comprobante)::int   AS anio,
    EXTRACT(MONTH FROM fv.fecha_comprobante)::int  AS mes,
    SUM(fv.cantidades_total)          AS bultos
FROM gold.fact_ventas fv
LEFT JOIN gold.dim_articulo  da ON fv.id_articulo = da.id_articulo
LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal = ds.id_sucursal
WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
  AND fv.id_documento != 'PRVTA'
  AND da.generico IN ('CERVEZAS', 'AGUAS DANONE', 'VINOS CCU', 'SIDRAS Y LICORES')
GROUP BY ds.descripcion, da.generico,
         EXTRACT(YEAR FROM fv.fecha_comprobante),
         EXTRACT(MONTH FROM fv.fecha_comprobante)
ORDER BY ds.descripcion, da.generico, anio, mes
```

El caller (service) computa `desde` como `{año(fecha_desde) - 1}-01-01` para incluir el año anterior completo.

#### Query SQL — `get_cobertura_clientes_cervezas`

```sql
SELECT
    ds.descripcion                    AS sucursal,
    EXTRACT(YEAR FROM fv.fecha_comprobante)::int   AS anio,
    EXTRACT(MONTH FROM fv.fecha_comprobante)::int  AS mes,
    fv.id_cliente,
    SUM(fv.cantidades_total)          AS bultos
FROM gold.fact_ventas fv
LEFT JOIN gold.dim_articulo  da ON fv.id_articulo = da.id_articulo
LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal = ds.id_sucursal
WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
  AND fv.id_documento != 'PRVTA'
  AND da.generico = 'CERVEZAS'
GROUP BY ds.descripcion,
         EXTRACT(YEAR FROM fv.fecha_comprobante),
         EXTRACT(MONTH FROM fv.fecha_comprobante),
         fv.id_cliente
ORDER BY ds.descripcion, anio, mes, fv.id_cliente
```

### 5.2 Arquitectura

```
main.py
  reporte-general-badie subcommand
    └─ _run_reporte_general_badie_report(report, merged)
         └─ ReporteGeneralBadieService.generar_reporte(config)
              ├─ DataLoader.get_sucursales()                          [existente]
              ├─ DataLoader.get_ventas_mensuales_ccu(desde_exp, hasta)  [NUEVO]
              ├─ DataLoader.get_cobertura_clientes_cervezas(desde_exp, hasta) [NUEVO]
              └─ _build_workbook(sucursales, ventas_df, cobertura_df, config)
                   ├─ _build_sheet_ventas_ccu(wb, ventas_df)          → hoja "VentasCCU"
                   ├─ _build_sheet_cobertura(wb, cobertura_df)        → hoja "CoberturaCervezas"
                   └─ _build_sheet_reporte(wb, sucursales, config)    → hoja "Reporte"
```

Árbol de archivos nuevos:

```
src/services/reporte_general_badie/
    __init__.py         ← expone ReporteGeneralBadieService, Config, Result
    service.py          ← ReporteGeneralBadieService, Config, Result
    processor.py        ← _build_workbook, _build_sheet_*, helpers de fórmulas
```

El servicio hereda de `BaseService` con:
```python
SERVICE_SLUG = "reporte-general-badie"
GRANULARITY: ClassVar[Granularity] = "month"
```

### 5.3 API / Interfaz

#### `ReporteGeneralBadieService.generar_reporte(config) -> ReporteGeneralBadieResult`

Input:
```python
ReporteGeneralBadieConfig(
    fecha_desde="2026-04-01",
    fecha_hasta="2026-04-30",
    nombre_archivo=None,   # usa "Reporte General Badie"
)
```

Output:
```python
ReporteGeneralBadieResult(
    ruta_archivo=Path("data/output/reporte-general-badie/2026-04/Reporte General Badie.xlsx"),
    registros_ventas=480,      # ejemplo: ~5 suc × 4 genericos × 28 meses
    registros_cobertura=12500, # ejemplo: clientes × meses
    sucursales=5,
    meses_en_dropdown=28,
)
```

#### Config JSON de ejemplo

```json
{
    "tipo": "reporte-general-badie",
    "filtros": {
        "fecha_desde": "2026-04-01",
        "fecha_hasta": "2026-04-30"
    },
    "reportes": [
        {
            "nombre": "Reporte General Badie"
        }
    ]
}
```

#### Cálculo de la fecha expandida (en el service, no en DataLoader)

```python
from dateutil.relativedelta import relativedelta

fecha_desde_dt = datetime.strptime(config.fecha_desde, "%Y-%m-%d")
desde_expandido = fecha_desde_dt.replace(year=fecha_desde_dt.year - 1, month=1, day=1).strftime("%Y-%m-%d")
# Si fecha_desde="2026-04-01", desde_expandido="2025-01-01"
```

#### Construcción del dropdown de meses

```python
from datetime import date
import calendar

def _generar_meses(desde: str, hasta: str) -> list[str]:
    """Genera lista ["YYYY-MM", ...] desde 2024-01 hasta el mes de `hasta`."""
    inicio = date(2024, 1, 1)
    fin_dt = datetime.strptime(hasta, "%Y-%m-%d").date()
    fin = date(fin_dt.year, fin_dt.month, 1)
    meses = []
    cur = inicio
    while cur <= fin:
        meses.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return meses
```

El `formula1` del DataValidation SHALL ser el string `'"' + ",".join(meses) + '"'`.

---

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|------|------------------------|
| `get_ventas_mensuales_ccu` retorna DataFrame vacío | Hoja "VentasCCU" con encabezados y 0 filas; hoja "Reporte" con fórmulas que retornan 0 o ""; archivo generado normalmente |
| `get_cobertura_clientes_cervezas` retorna DataFrame vacío | Hoja "CoberturaCervezas" con encabezados y 0 filas; columnas G y H retornan 0 |
| Año anterior sin datos (YoY) | Celda F{r} muestra `""` (IF protege la división por cero con bultos_año_anterior=0) |
| Total CCU = 0 para una sucursal en el mes seleccionado | Columnas C, D, E muestran `""` (IF(B{r}=0,"",…)); G y H muestran 0 |
| Sucursal con clientes en CERVEZAS pero todos con bultos=0 después del filtro PRVTA | G=0, H=0; no genera error en la fórmula SUMPRODUCT/COUNTIFS |
| `fecha_hasta` en diciembre (mes 12) | La generación del dropdown llega hasta "YYYY-12" correctamente; no hay overflow de mes |
| `fecha_desde` y `fecha_hasta` en el mismo mes | Archivo válido; dropdown muestra desde "2024-01" hasta ese único mes |
| Nombre de archivo con `nombre_archivo=None` | Usa literalmente `"Reporte General Badie.xlsx"` |
| Directorio de salida no existe | Se crea con `mkdir(parents=True, exist_ok=True)` |
| Archivo ya existe en el mismo período | Se sobreescribe sin error |
| `bultos` con decimales en raw data | Valor float preservado en TblVentasCCU; `#,##0` en la columna B del Reporte muestra redondeado visualmente, sin modificar el dato |
| DataValidation con lista de meses > 255 caracteres | openpyxl acepta strings largos en `formula1`; no hay límite aplicado aquí (Excel sí tiene límite de 255 chars para validación de lista inline — si la lista de meses supera ese límite, se debe usar un named range en una hoja auxiliar. Ver decisión abierta DA-001) |

---

## 7. Plan de Testing

### Unitarios — `tests/test_reporte_general_badie_service.py`

- [ ] **Test-U01**: `generar_reporte` con DataLoader mock (ventas y cobertura no vacíos) → `ruta_archivo` existe, `sucursales > 0`, `meses_en_dropdown >= 1` → valida RF-025, RF-026
- [ ] **Test-U02**: `generar_reporte` con DataLoader mock retornando DataFrames vacíos → archivo generado, `registros_ventas=0`, `registros_cobertura=0` → valida RF-009, RF-011
- [ ] **Test-U03**: Service hereda `BaseService`, tiene `SERVICE_SLUG="reporte-general-badie"` y `GRANULARITY="month"` → valida RF-001
- [ ] **Test-U04**: Output dir es `data/output/reporte-general-badie/2026-04/` cuando `fecha_desde="2026-04-01"` → valida RF-001, RF-025

### Unitarios — `tests/test_reporte_general_badie_processor.py`

- [ ] **Test-U05**: `_build_sheet_ventas_ccu` con DataFrame de 3 filas → hoja "VentasCCU" con 3 filas de datos + encabezados, tabla "TblVentasCCU" presente → valida RF-008
- [ ] **Test-U06**: `_build_sheet_ventas_ccu` con DataFrame vacío → hoja "VentasCCU" con encabezados y 0 filas de datos → valida RF-009
- [ ] **Test-U07**: `_build_sheet_cobertura` con DataFrame de 5 filas → hoja "CoberturaCervezas" con 5 filas, tabla "TblCoberturaCervezas" → valida RF-010
- [ ] **Test-U08**: `_build_sheet_reporte` → hoja "Reporte" en posición 0, fila 1 tiene "Reporte General Badie", fila 2 tiene "Mes:" en A2 → valida RF-012, RF-013
- [ ] **Test-U09**: Celda B2 tiene DataValidation de tipo "list", `showDropDown=False`, `formula1` comienza con `'"2024-01` → valida RF-014, RF-015
- [ ] **Test-U10**: Encabezados fila 4 (A4="Sucursal", B4="Total CCU", …, H4="Cobertura ≥1 Bulto"), fill `#1F4E79`, fuente blanca → valida RF-016
- [ ] **Test-U11**: Celda B5 (primera sucursal) contiene fórmula con "SUMPRODUCT" y referencia "TblVentasCCU[bultos]" → valida RF-018
- [ ] **Test-U12**: Celda C5 contiene "CERVEZAS" en la fórmula; celda D5 contiene "AGUAS DANONE"; celda E5 contiene "VINOS CCU" y "SIDRAS Y LICORES" → valida RF-019
- [ ] **Test-U13**: Celda F5 contiene fórmula con `"-1"` o `"- 1"` (resta de año para YoY) y contiene `IF` → valida RF-020
- [ ] **Test-U14**: Celda G5 contiene fórmula SUMPRODUCT con "TblCoberturaCervezas" y `">"&0` → valida RF-021
- [ ] **Test-U15**: Celda H5 contiene fórmula con `">"&1` → valida RF-022
- [ ] **Test-U16**: `number_format` de B5 = `"#,##0"`, C5 = `"0.0%"`, F5 = `"0.0%"`, G5 = `"#,##0"` → valida RF-023
- [ ] **Test-U17**: Columna A desde fila 5 contiene nombres de sucursales literales (strings), no fórmulas → valida RF-024
- [ ] **Test-U18**: `bultos` en DataFrame de ventas nunca pasa por `int()` (verificar código del processor: ausencia de cast entero) → valida RF-023 (regla primaria)

### Unitarios — `tests/test_reporte_general_badie_data_loader.py`

- [ ] **Test-U19**: `get_ventas_mensuales_ccu` con engine mock → SQL incluye `id_documento != 'PRVTA'`, usa parámetros nombrados, retorna columnas `["sucursal","generico","anio","mes","bultos"]` → valida RF-003, RF-004, RF-007
- [ ] **Test-U20**: `get_ventas_mensuales_ccu` con resultado vacío → DataFrame vacío con columnas correctas, no None → valida RF-003
- [ ] **Test-U21**: `get_cobertura_clientes_cervezas` con engine mock → SQL incluye `generico = 'CERVEZAS'`, `id_documento != 'PRVTA'`, retorna columnas `["sucursal","anio","mes","id_cliente","bultos"]` → valida RF-005, RF-007
- [ ] **Test-U22**: `get_cobertura_clientes_cervezas` con resultado vacío → DataFrame vacío con columnas correctas → valida RF-006

### Unitarios — `tests/test_reporte_general_badie_config.py`

- [ ] **Test-U23**: `ReportConfig` con `tipo="reporte-general-badie"` → válido sin error Pydantic → valida RF-029
- [ ] **Test-U24**: `ReportConfig` con tipo no reconocido → ValidationError → valida RF-029 (negativo)

### Escenarios de aceptación — `tests/test_reporte_general_badie_scenarios.py`

- [ ] **S-01 (Happy path)**: Mock con 5 sucursales, datos de 4 genericos por 16 meses → XLSX generado, hoja "Reporte" en pos 0, B2 con dropdown, fila 5 con fórmulas en columnas B-H, `meses_en_dropdown=16` → valida RF-012–RF-022
- [ ] **S-02 (Empty data)**: Mock retorna DataFrames vacíos → XLSX generado, hojas raw con solo encabezados, hoja "Reporte" con fórmulas (retornan 0/"") → valida RF-009, RF-011
- [ ] **S-03 (Missing YoY)**: DataFrame de ventas solo contiene datos del año actual (sin año anterior) → celda F contiene IF que retornaría "" al evaluar; fórmula presente sin error de generación → valida RF-020
- [ ] **S-04 (Month selection)**: Verificar que la fórmula de B5 referencia `$B$2` con referencia absoluta, de modo que copiar la fórmula a B6, B7, etc. mantiene la referencia al dropdown → valida RF-017, RF-018
- [ ] **S-05 (PRVTA excluded)**: DataFrame de ventas mock construido con `id_documento='PRVTA'` excluido (la query lo filtra en BD; en el test se verifica que el SQL generado contiene `id_documento != 'PRVTA'`) → valida RF-007

---

## 8. Tareas de Implementación

1. **Agregar `"reporte-general-badie"` al Literal de `ReportConfig.tipo`** — Archivos: `src/config/models.py`

2. **Agregar `get_ventas_mensuales_ccu` y `get_cobertura_clientes_cervezas` a `DataLoader`** — Archivos: `src/core/data_loader.py` — Sin dependencias

3. **Crear `src/services/reporte_general_badie/`** con:
   - `__init__.py` — expone `ReporteGeneralBadieService`, `ReporteGeneralBadieConfig`, `ReporteGeneralBadieResult`
   - `service.py` — `ReporteGeneralBadieService(BaseService)`, `ReporteGeneralBadieConfig`, `ReporteGeneralBadieResult`
   - `processor.py` — `_build_workbook`, `_build_sheet_ventas_ccu`, `_build_sheet_cobertura`, `_build_sheet_reporte`, `_generar_meses`, helpers de fórmulas
   
   Depende de: Tareas 1 y 2

4. **Agregar subcomando `reporte-general-badie` al CLI** — `REPORT_HANDLERS`, `cmd_reporte_general_badie`, `_run_reporte_general_badie_report` — Archivos: `main.py` — Depende de: Tarea 3

5. **Tests del DataLoader** — Archivos: `tests/test_reporte_general_badie_data_loader.py` — Depende de: Tarea 2

6. **Tests del processor** — Archivos: `tests/test_reporte_general_badie_processor.py` — Depende de: Tarea 3

7. **Tests del service** — Archivos: `tests/test_reporte_general_badie_service.py` — Depende de: Tarea 3

8. **Tests de config models** — Archivos: `tests/test_reporte_general_badie_config.py` — Depende de: Tarea 1

9. **Tests de escenarios de aceptación** — Archivos: `tests/test_reporte_general_badie_scenarios.py` — Depende de: Tareas 3, 4

---

## 9. Boundaries (Lo que NO hacer)

- NO modificar la lógica de ningún servicio existente (`VentasService`, `ResumenMensualService`, etc.).
- NO agregar zonas virtuales (CASA CENTRAL no se splitea en este servicio).
- NO agregar slicers (`con_slicers` no aplica; este reporte usa dropdown nativo de openpyxl DataValidation).
- NO agregar entrega por email/WhatsApp como parte de este feature (el pipeline de delivery existente lo cubre si `enviar_a` está en el config).
- NO agregar endpoint API como parte de esta feature.
- NO tocar `get_ventas_diarias`, `get_ventas`, ni ningún método DataLoader existente.
- NO aplicar `int()`, `round()`, ni `astype(int)` a ningún valor numérico en todo el pipeline (regla primaria del proyecto).
- NO usar `ExcelWriter` ni `SheetStyle` — este reporte escribe openpyxl directamente por su layout de hoja-fórmula.
- NO agregar campo nuevo a `GlobalFilters` ni `ReportFilters` (solo `fecha_desde`/`fecha_hasta` son necesarios).

---

## 10. Decisiones Abiertas

- [ ] **DA-001 — Límite de 255 chars en DataValidation lista inline**: Excel limita las listas inline de DataValidation a 255 caracteres. Con meses desde 2024-01 hasta el mes actual (abril 2026 = 28 meses × 8 chars = 224 chars + separadores = ~250 chars), estamos cerca del límite. A medida que pase el tiempo superará el límite. Opciones: (a) usar una hoja auxiliar oculta con los meses y referenciarla vía named range en `formula1`; (b) truncar los meses más viejos en el dropdown (solo los últimos N meses). Decisión pendiente antes de implementación.

- [ ] **DA-002 — Fórmula de conteo de clientes únicos con SUMPRODUCT/COUNTIFS**: La fórmula de RF-021 y RF-022 es correcta conceptualmente pero puede ser lenta o generar `#DIV/0!` si hay combinaciones vacías dentro del rango. Evaluar si usar `IFERROR(…, 0)` alrededor del SUMPRODUCT completo o manejar el cero en el COUNTIFS del denominador con `MAX(COUNTIFS(…),1)`.

- [ ] **DA-003 — Sucursales en el Reporte vs sucursales en los datos**: Si `get_sucursales()` retorna sucursales que no tienen ventas CCU en ningún mes, sus filas en el Reporte mostrarán todo en 0 o "". Confirmar si esto es el comportamiento deseado o si se debe filtrar solo sucursales con datos en `TblVentasCCU`.
