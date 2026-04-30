# Spec: Output Per Service

> **Estado:** DRAFT
> **Fecha:** 2026-04-20
> **Autor:** nahuel

---

## 1. Objetivo

Reorganizar todos los artefactos de salida bajo `data/output/{tipo-servicio}/{periodo}/` de modo que cada tipo de reporte tenga su propio subdirectorio versionado por periodo, eliminando la colision de archivos de distintos servicios en el directorio raiz.

---

## 2. Contexto

Actualmente los 8 servicios activos (ventas, resumen-mensual, mision-imposible, historico-fratelli, cartesiano, stock-diario, ventas-articulo, graficos-cobertura) vuelcan todos sus artefactos directamente en `data/output/`. El resultado es un directorio plano con archivos mezclados de distintos meses y tipos. Ademas, `CaptureImageStep` deposita PNGs en el mismo directorio raiz, desvinculados del xlsx que los origino.

El unico servicio que ya usa un subdirectorio es `graficos-cobertura`, pero con un subfolder de timestamp en lugar de periodo — inconsistente con el resto.

El servicio `avances` es una excepcion deliberada: su xlsx es un archivo de trabajo externo (`archivo_plantilla`) que se actualiza in-place; no genera un xlsx de salida propio, por lo que su ruta no cambia.

---

## 3. Requisitos Funcionales

### 3.1 Helper `service_output_dir`

- **RF-001**: Cuando se llama a `service_output_dir(service_slug, fecha_desde, granularity)`, el sistema debe retornar un `Path` con la forma `DATA_OUTPUT / service_slug / period`.

- **RF-002**: Cuando `granularity="month"` y `fecha_desde="2026-04-15"`, el sistema debe retornar un path cuyo componente de periodo sea `"2026-04"`.

- **RF-003**: Cuando `granularity="day"` y `fecha_desde="2026-04-15"`, el sistema debe retornar un path cuyo componente de periodo sea `"2026-04-15"`.

- **RF-004**: Cuando `fecha_desde=None` y `granularity="month"`, el sistema debe usar la fecha de hoy en formato `YYYY-MM` como periodo.

- **RF-005**: Cuando `fecha_desde=None` y `granularity="day"`, el sistema debe usar la fecha de hoy en formato `YYYY-MM-DD` como periodo.

- **RF-006**: Cuando se pasa un valor de `granularity` distinto de `"month"` o `"day"`, el sistema debe elevar `ValueError` con un mensaje que indique los valores validos.

- **RF-007**: La funcion `service_output_dir` NO debe crear el directorio; esa responsabilidad es del caller mediante `mkdir(parents=True, exist_ok=True)`.

### 3.2 Integracion por servicio

- **RF-010**: Cuando se ejecuta el servicio `ventas` con `fecha_desde` del rango del reporte, el sistema debe escribir el xlsx en `data/output/ventas/{YYYY-MM}/` derivado de `fecha_desde`.

- **RF-011**: Cuando se ejecuta el servicio `resumen-mensual`, el sistema debe escribir el xlsx en `data/output/resumen-mensual/{YYYY-MM}/` derivado de `fecha_desde`.

- **RF-012**: Cuando se ejecuta el servicio `mision-imposible`, el sistema debe escribir el xlsx en `data/output/mision-imposible/{YYYY-MM}/` derivado de `fecha_desde`.

- **RF-013**: Cuando se ejecuta el servicio `historico-fratelli` (sin period en config), el sistema debe escribir el xlsx en `data/output/historico-fratelli/{YYYY-MM}/` usando la fecha de ejecucion como fallback.

- **RF-014**: Cuando se ejecuta el servicio `cartesiano` (sin period en config), el sistema debe escribir el xlsx en `data/output/cartesiano/{YYYY-MM}/` usando la fecha de ejecucion como fallback.

- **RF-015**: Cuando se ejecuta el servicio `stock-diario` con `fecha_desde`, el sistema debe escribir el xlsx en `data/output/stock-diario/{YYYY-MM-DD}/` derivado de `fecha_desde`.

- **RF-016**: Cuando se ejecuta el servicio `ventas-articulo` con `fecha_desde`, el sistema debe escribir el xlsx en `data/output/ventas-articulo/{YYYY-MM}/` derivado de `fecha_desde`.

- **RF-017**: Cuando se ejecuta el servicio `graficos-cobertura`, el sistema debe escribir todos los artefactos (xlsx, pptx marca, pptx generico, PNGs) en `data/output/graficos-cobertura/{YYYY-MM-DD}/` derivado de `fecha_desde`, reemplazando el subfolder de timestamp que hoy genera `_resolve_output_dir()`.

### 3.3 Capturas de pantalla

- **RF-020**: Cuando `CaptureImageStep` produce PNGs para un reporte cuyo xlsx reside en la nueva estructura de directorios, el sistema debe guardar los PNGs en `{xlsx_parent}/captures/`.

- **RF-021**: Cuando `CaptureImageStep` produce PNGs para el servicio `avances` (cuyo xlsx es externo en `archivo_plantilla`), el sistema debe guardar los PNGs en `data/output/avances/{YYYY-MM}/captures/`, donde `YYYY-MM` se deriva de `fecha_desde`.

- **RF-022**: Cuando `CaptureImageStep` produce PNGs, el sistema NO debe escribirlos en el directorio raiz `DATA_OUTPUT`.

### 3.4 Excepcion `avances`

- **RF-030**: Cuando se ejecuta el servicio `avances`, el sistema debe guardar el xlsx en la ruta `archivo_plantilla` (path externo provisto por el usuario), sin modificar la ubicacion del archivo.

- **RF-031**: Cuando se ejecuta `avances` sin capturas configuradas, el sistema NO debe crear el directorio `data/output/avances/{period}/`.

### 3.5 Creacion de directorios

- **RF-040**: Cuando un servicio va a escribir su primer artefacto de una ejecucion, el sistema debe crear el directorio de salida via `mkdir(parents=True, exist_ok=True)` antes de abrir cualquier archivo.

- **RF-041**: Cuando el directorio de salida ya existe, el sistema debe continuar sin error (comportamiento `exist_ok=True`).

- **RF-042**: Cuando se ejecuta el mismo reporte dos veces en el mismo periodo, el sistema debe sobreescribir los archivos existentes sin crear backups ni versiones alternativas.

### 3.6 Documentacion

- **RF-050**: Cuando se complete la implementacion, el sistema debe tener las secciones de `CLAUDE.md` que describen rutas de salida actualizadas para reflejar la nueva estructura `data/output/{tipo}/{periodo}/`.

---

## 4. Requisitos No Funcionales

- **RNF-001**: `service_output_dir` debe ser importable desde `src.core.output_paths` sin dependencias circulares respecto a servicios.
- **RNF-002**: El helper debe estar cubierto al 100% por tests unitarios (todas las ramas de granularity y fecha_desde=None/presente).
- **RNF-003**: Los tests existentes que usan `patch("config.settings.DATA_OUTPUT", tmp_path)` deben seguir funcionando sin modificacion de sus patches (el helper resuelve `DATA_OUTPUT` en tiempo de llamada, no en tiempo de importacion del modulo).
- **RNF-004**: No se crea ningun mecanismo de seleccion (flag/env var) entre layout flat y layout por periodo; la nueva estructura es el unico comportamiento.

---

## 5. Diseno Tecnico

### 5.1 Nuevo modulo `src/core/output_paths.py`

```python
from datetime import date
from pathlib import Path
from config.settings import DATA_OUTPUT

def service_output_dir(
    service_slug: str,
    fecha_desde: str | None,
    granularity: str = "month",
) -> Path:
    """Retorna DATA_OUTPUT / service_slug / period.

    No crea el directorio — responsabilidad del caller.
    """
    if granularity == "month":
        fmt = "%Y-%m"
    elif granularity == "day":
        fmt = "%Y-%m-%d"
    else:
        raise ValueError(f"granularity debe ser 'month' o 'day', no '{granularity}'")

    if fecha_desde is None:
        period = date.today().strftime(fmt)
    else:
        period = fecha_desde[:len(fmt.replace("%Y", "XXXX").replace("%m", "XX").replace("%d", "XX"))]
        # Extraer prefijo segun granularity: 7 chars para month, 10 para day
        period = fecha_desde[:7] if granularity == "month" else fecha_desde[:10]

    return DATA_OUTPUT / service_slug / period
```

Nota: la implementacion real simplifica la extraccion del prefijo con un slice directo (`fecha_desde[:7]` para month, `fecha_desde[:10]` para day).

### 5.2 Granularidad por servicio

| Servicio | `service_slug` | `granularity` | Fuente de `fecha_desde` |
|---|---|---|---|
| ventas | `"ventas"` | `"month"` | `GlobalFilters.fecha_desde` |
| resumen-mensual | `"resumen-mensual"` | `"month"` | `GlobalFilters.fecha_desde` |
| mision-imposible | `"mision-imposible"` | `"month"` | `MisionImposibleConfig.fecha_desde` |
| historico-fratelli | `"historico-fratelli"` | `"month"` | `None` (fallback hoy) |
| cartesiano | `"cartesiano"` | `"month"` | `None` (fallback hoy) |
| stock-diario | `"stock-diario"` | `"day"` | `StockDiarioConfig.fecha_desde` |
| ventas-articulo | `"ventas-articulo"` | `"month"` | config `fecha_desde` |
| graficos-cobertura | `"graficos-cobertura"` | `"day"` | `GraficosCoberturaConfig.fecha_desde` |

Los slugs coinciden exactamente con el Literal definido en `ReportConfig.tipo` (linea 103 de `src/config/models.py`).

### 5.3 Puntos de inyeccion por tipo de servicio

**Servicios ExcelWriter-based** (ventas, resumen-mensual, cartesiano): `ExcelWriter` ya acepta `output_dir=` en su constructor (`src/core/excel_writer.py` linea 363). Se computa `output_dir` con el helper y se pasa al constructor. El mkdir se hace antes.

**Servicios con ruta hardcodeada** (mision-imposible, historico-fratelli): reemplazar `output_dir = DATA_OUTPUT` / `ruta = DATA_OUTPUT / f"{nombre}.xlsx"` con llamada al helper + mkdir.

**Servicios con `build_excel(output_dir=)`** (stock-diario, ventas-articulo): el param `output_dir` ya existe en sus processors (`src/services/stock_diario/processor.py` linea 56, `src/services/ventas_articulo/processor.py` linea 93). Se computa en la capa service y se pasa.

**graficos-cobertura**: reemplazar `_resolve_output_dir()` en `GraficosCoberturaService` — hoy genera `DATA_OUTPUT / "graficos-cobertura" / ts`. Pasa a usar `service_output_dir("graficos-cobertura", config.fecha_desde, "day")`. El subfolder `png/` se crea como `run_dir / PNG_SUBDIR`.

### 5.4 `CaptureImageStep`

Cambio en `src/delivery/steps/capture_image.py`:

```python
# Antes
output_dir=DATA_OUTPUT,

# Despues
output_dir=artifact.ruta_excel.parent / "captures",
```

Para el caso `avances` (donde `artifact.ruta_excel` es el path externo del plantilla), se necesita pasar `fecha_desde` al step o derivarlo desde el `DeliveryConfig`. Se opta por agregar un campo opcional `output_dir_override: Path | None = None` al `ReportArtifact`, que el servicio `avances` setea a `service_output_dir("avances", config.fecha_desde, "month") / "captures"` al construir el artifact.

Si `output_dir_override` esta seteado, `CaptureImageStep` lo usa en lugar de `artifact.ruta_excel.parent / "captures"`.

### 5.5 Modelo de datos / config

No se requieren cambios de schema ni DDL. El helper es puro Python. `ReportConfig.tipo` ya contiene los slugs validos.

---

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|---|---|
| `fecha_desde="2026-04-15T00:00:00"` (datetime string) con `granularity="month"` | El slice `[:7]` retorna `"2026-04"` correctamente; sin parseo de datetime |
| `fecha_desde="2026-4-1"` (sin cero) | El slice `[:7]` retorna `"2026-4-"` — INCORRECTO. La funcion asume formato ISO `YYYY-MM-DD`; todos los callers usan Pydantic con `str` sin validacion de formato, pero en la practica siempre es ISO. Documentar el prerequisito. |
| `service_slug` con slash o path-separator | El helper no sanitiza el slug. Los slugs validos vienen del Literal de `ReportConfig.tipo` que no contiene slashes. |
| Dos servicios distintos corriendo concurrentemente con `fecha_desde` igual | Directorios distintos (`ventas/2026-04/` vs `stock-diario/2026-04-20/`); sin conflicto. |
| Mismo servicio corriendo dos veces el mismo dia | Mismo directorio; `mkdir(exist_ok=True)` no falla; archivos sobreescritos. |
| `graficos-cobertura` con `fecha_desde` ausente en config | `GraficosCoberturaConfig` tiene `fecha_desde` — verificar que sea campo obligatorio; si no lo es, fallback a `None` → hoy. |
| `avances` sin `capture_images` configurado | RF-031: el directorio `data/output/avances/{period}/` no se crea. El `output_dir_override` del artifact no se setea; `CaptureImageStep` retorna `skipped`. |
| Tests con `patch("config.settings.DATA_OUTPUT", tmp_path)` | El helper importa `DATA_OUTPUT` en el cuerpo de la funcion (o via `from config.settings import DATA_OUTPUT` al nivel de modulo). Si el patch reemplaza el atributo del modulo `config.settings`, el helper necesita referenciar `config.settings.DATA_OUTPUT` en tiempo de llamada, no capturar el valor al momento del import. Disenar el helper para leer `DATA_OUTPUT` del modulo en cada llamada (o recibir `base_dir` opcional en tests). |

---

## 7. Plan de Testing

- [ ] Test: `service_output_dir("ventas", "2026-04-01", "month")` retorna `DATA_OUTPUT / "ventas" / "2026-04"` → valida RF-001, RF-002
- [ ] Test: `service_output_dir("stock-diario", "2026-04-20", "day")` retorna `DATA_OUTPUT / "stock-diario" / "2026-04-20"` → valida RF-001, RF-003
- [ ] Test: `service_output_dir("historico-fratelli", None, "month")` retorna `DATA_OUTPUT / "historico-fratelli" / date.today().strftime("%Y-%m")` → valida RF-004
- [ ] Test: `service_output_dir("x", None, "day")` retorna path con `date.today().strftime("%Y-%m-%d")` → valida RF-005
- [ ] Test: `service_output_dir("x", "2026-04-01", "week")` eleva `ValueError` → valida RF-006
- [ ] Test: llamar `service_output_dir` no crea ningun directorio en el filesystem → valida RF-007
- [ ] Test: `service_output_dir` con `DATA_OUTPUT` patched a `tmp_path` retorna path bajo `tmp_path` → valida RNF-003
- [ ] Test de integracion (ventas): patch `DATA_OUTPUT`, ejecutar servicio, verificar que el xlsx existe en `tmp_path / "ventas" / "2026-04" / "Ventas...xlsx"` → valida RF-010
- [ ] Test de integracion (stock-diario): mismo patron, verifica `tmp_path / "stock-diario" / "2026-04-20" / "Stock Diario...xlsx"` → valida RF-015
- [ ] Test de integracion (graficos-cobertura): verifica `ruta_directorio` en el result NO contiene timestamp (formato `\d{4}-\d{2}-\d{2}_\d{6}`) → valida RF-017
- [ ] Test de captura (servicio regular): tras `CaptureImageStep`, `artifact.rutas_imagenes[0].parent.name == "captures"` y el parent de captures es `xlsx_parent` → valida RF-020
- [ ] Test de captura (avances): con `output_dir_override` seteado, PNG queda bajo `data/output/avances/2026-04/captures/` → valida RF-021
- [ ] Test de doble ejecucion: correr el mismo servicio dos veces, verificar que el segundo run no falla y el directorio contiene el archivo del segundo run → valida RF-042

---

## 8. Tareas de Implementacion

1. **Crear helper** — Archivos: `src/core/output_paths.py` (nuevo)
   - Funcion `service_output_dir` con las 3 ramas (month/day/invalido) y fallback `None`.
   - Tests unitarios en `tests/test_output_paths.py` (nuevo).

2. **Actualizar `CaptureImageStep`** — Archivos: `src/delivery/steps/capture_image.py`, `src/delivery/pipeline.py`
   - Agregar campo `output_dir_override: Path | None = None` a `ReportArtifact`.
   - Cambiar `output_dir=DATA_OUTPUT` a `output_dir=artifact.output_dir_override or (artifact.ruta_excel.parent / "captures")`.
   - Depende de: Tarea 1

3. **Migrar servicios ExcelWriter-based** (ventas, resumen-mensual, cartesiano) — Archivos: `src/services/ventas/service.py`, `src/services/resumen_mensual/service.py`, `src/services/cartesiano/service.py`
   - Importar helper, computar `output_dir`, `mkdir`, pasar a `ExcelWriter`.
   - Depende de: Tarea 1

4. **Migrar servicios con ruta hardcodeada** (mision-imposible, historico-fratelli) — Archivos: `src/services/mision_imposible/service.py`, `src/services/historico_fratelli/service.py`
   - Reemplazar `output_dir = DATA_OUTPUT` / `ruta = DATA_OUTPUT / f"..."` con helper + mkdir.
   - Depende de: Tarea 1

5. **Migrar servicios con `build_excel(output_dir=)`** (stock-diario, ventas-articulo) — Archivos: `src/services/stock_diario/service.py`, `src/services/ventas_articulo/service.py`
   - Computar `output_dir` con helper en la capa service y pasarlo a `build_excel`.
   - Depende de: Tarea 1

6. **Migrar graficos-cobertura** — Archivos: `src/services/graficos_cobertura/service.py`
   - Reemplazar `_resolve_output_dir()` — eliminar el timestamp, usar helper con `granularity="day"` y `config.fecha_desde`.
   - Agregar `fecha_desde` a `GraficosCoberturaConfig` si no existe como campo obligatorio.
   - Depende de: Tarea 1

7. **Agregar soporte avances captures** — Archivos: `src/services/avances/service.py`, `src/delivery/pipeline.py`
   - Al construir el `ReportArtifact` para avances, setear `output_dir_override` al path de captures derivado del helper.
   - Solo cuando `capture_images` esta configurado (RF-031).
   - Depende de: Tarea 2

8. **Actualizar documentacion** — Archivos: `CLAUDE.md`
   - Reemplazar secciones que mencionan `data/output/*.xlsx` con la nueva estructura.
   - Sin dependencias de codigo; puede hacerse en paralelo con Tareas 3-7.

---

## 9. Boundaries (Lo que NO hacer)

- NO modificar `config/settings.py` — `DATA_OUTPUT` permanece como esta; el helper lo usa, no lo reemplaza.
- NO agregar migracion de archivos existentes en `data/output/` plano — limpieza manual por el usuario.
- NO agregar versioning, timestamps ni backups en el nuevo layout.
- NO crear un mecanismo de toggle (flag/env var) para elegir entre layout plano y nuevo.
- NO modificar el path de `archivo_plantilla` en `avances` — es un archivo externo del usuario.
- NO tocar la funcion legacy `generar_excel()` en `excel_writer.py` (usada solo por el servicio `cobertura` legacy, fuera de scope).
- NO modificar como se pasan los configs — la lectura de `fecha_desde` viene de los dataclass/Pydantic existentes, sin nuevos parametros CLI.

---

## 10. Decisiones Abiertas

- [ ] **`GraficosCoberturaConfig.fecha_desde`**: verificar si el campo ya existe y si es obligatorio. Si no existe, hay que agregarlo a la config y a todos los configs JSON de produccion existentes. Resolver antes de Tarea 6.
- [ ] **Patch strategy para tests**: decidir si `service_output_dir` referencia `DATA_OUTPUT` via `import config.settings as _settings; return _settings.DATA_OUTPUT / ...` (patch-friendly) o via `from config.settings import DATA_OUTPUT` (requiere patch del modulo `src.core.output_paths`). Impacta como se parchean los tests existentes.
- [ ] **`fecha_desde` en `HistoricoFratelliService` y `CartesianoService`**: ambos no tienen periodo en config. Confirmar que el fallback a `date.today()` es aceptable o si hay un campo de fecha implicito que podria usarse.
