# 01 — Arquitectura

## Visión general

Excel Reporter es un sistema en capas donde el flujo va: **petición → DataLoader (BD) → procesamiento (pandas) → ExcelWriter (xlsx) → DeliveryPipeline (imagen + email + WhatsApp)**.

```
┌─────────────────────────────────────────────────────────────────┐
│                          Entry points                            │
│  CLI (main.py)        API REST (api.py)        run_daily.py     │
└────────────────┬────────────────┬──────────────────┬────────────┘
                 │                │                  │
                 └────────────────┼──────────────────┘
                                  │
                          ┌───────▼────────┐
                          │  Service Layer │  src/services/{slug}/service.py
                          │  (BaseService) │  Orquesta el flujo del reporte
                          └───────┬────────┘
                                  │
              ┌───────────────────┼───────────────────┬─────────────┐
              │                   │                   │             │
       ┌──────▼──────┐    ┌──────▼──────┐    ┌──────▼──────┐  ┌────▼─────┐
       │ DataLoader  │    │  Processor  │    │ ExcelWriter │  │ Delivery │
       │ (gold.*)    │    │  (pandas)   │    │ (openpyxl)  │  │ Pipeline │
       └──────┬──────┘    └─────────────┘    └─────────────┘  └────┬─────┘
              │                                                     │
       ┌──────▼──────┐                                       ┌──────▼─────┐
       │ PostgreSQL  │                                       │ Steps:     │
       │ (Gold layer)│                                       │ Capture    │
       └─────────────┘                                       │ Email      │
                                                             │ WhatsApp   │
                                                             └────────────┘
```

## Capas

### 1. Entry points (interfaces de usuario)

| Componente | Archivo | Rol |
|------------|---------|-----|
| **CLI** | `main.py` (1146 líneas) | Subcomandos por servicio. Despacha vía `REPORT_HANDLERS` dict. |
| **API REST** | `api.py` (89 líneas) + `src/api/routes/` | FastAPI con routers por servicio. |
| **Scheduler** | `scripts/run_daily.py` (243 líneas) | Patchea fechas a hoy, corre subset de servicios registrados. |

Los tres usan el mismo `_run_reportes()` de `main.py` por debajo, así que cualquier servicio registrado funciona desde cualquier entry point.

### 2. Service Layer

Cada reporte vive en `src/services/{nombre}/`:

```
src/services/{nombre}/
├── service.py       # {Nombre}Service(BaseService) — orquesta
├── processor.py     # (opcional) lógica pura sobre DataFrames
└── __init__.py      # exporta Service + Config + Result
```

**`BaseService`** (`src/services/base_service.py`) define:
- `SERVICE_SLUG: ClassVar[str]` — usado para el directorio de output
- `GRANULARITY: ClassVar[Granularity]` — `"month"` o `"day"` (afecta ruta de output)
- `data_loader` property con lazy init de `DataLoader`
- `_output_dir(fecha_desde) -> Path` — calcula `data/output/{slug}/{periodo}/`
- `generar_reporte(config) -> Result` — método abstracto

Cada servicio define su propio `Config` y `Result` (dataclasses), así no hay tipado mágico.

### 3. Repository Pattern — `DataLoader`

`src/core/data_loader.py` (1701 líneas, ~25 métodos `get_*`) abstrae el acceso a `gold.*`. Cada método retorna un `DataFrame` de Pandas con columnas estables.

**Conexión**: SQLAlchemy + psycopg2. Engine reutilizable, queries con `text()` y placeholders nominales `:desde`, `:hasta`, `:gen_0`, etc.

**Inyectable**: el constructor de cualquier servicio acepta un `DataLoader` opcional. Los tests pasan un `MagicMock(spec=DataLoader)`.

Ver detalles en [03-database.md](03-database.md).

### 4. Processor (lógica pura)

Algunos servicios separan la transformación de DataFrames en `processor.py` para testabilidad:

- `resumen_mensual/processor.py` — calcula tendencia, MMAA, MA, formatea fechas
- `ventas/processor.py` — pivot diario, días hábiles, totales por marca
- `reporte_general_badie/processor.py` — construye fórmulas SUMPRODUCT
- `graficos_cobertura/processor.py` — agregaciones por zona/genérico
- `stock_diario/processor.py` — formato y agregación
- `ventas_articulo/processor.py` — desglose diario por artículo

Servicios sin `processor.py` (Avances, Cartesiano, Champions League, Cobertura, Histórico Cliente, Histórico Fratelli) tienen toda la lógica en `service.py`.

### 5. ExcelWriter

`src/core/excel_writer.py` (396 líneas) es el wrapper sobre `openpyxl` con tres clases clave:

- **`SheetStyle`** — estilo declarativo: `numeric_format`, `column_formats`, `column_groups`, `summary_rows`, `as_table`, `table_style`
- **`ColumnFormat`** — `width`, `number_format`, `font_bold`, `font_color` (post-write, solo data cells)
- **`ColumnGroup`** — agrupa columnas colapsables Excel

El método `add_sheet(df, sheet_name, style)` retorna el `Worksheet` openpyxl para que el servicio aplique formato condicional, fórmulas o estilos custom post-write.

### 6. Delivery Pipeline

`src/delivery/pipeline.py` ejecuta una secuencia de `DeliveryStep` con **fallo aislado** (un paso que falla no detiene los siguientes).

Pasos disponibles (`src/delivery/steps/`):
- `CaptureImageStep` — renderiza un rango Excel a PNG (LibreOffice o Playwright)
- `SendEmailStep` — adjunta excel/imagen y manda por SMTP
- `SendWhatsAppStep` — postea en grupos vía microservicio Node

Ver [05-delivery.md](05-delivery.md).

## Patrones de diseño aplicados

### Service Layer Pattern
Cada operación de negocio (un reporte) es un servicio con una superficie pública mínima (`generar_reporte`). Encapsula query → transform → write → deliver.

### Repository Pattern
`DataLoader` aísla la BD. El test de cualquier servicio mockea `DataLoader` y nunca toca la BD real.

### Template Method
`BaseService` define la forma del servicio (`SERVICE_SLUG`, `data_loader`, `_output_dir`, `generar_reporte`); cada subclase rellena la lógica específica.

### Dependency Injection
`DataLoader` se inyecta opcionalmente. Si no, se crea uno con la conexión por default. Esto permite testing sin BD real y override en tests integration.

### Pipeline Pattern
`DeliveryPipeline.run(artifact, config)` ejecuta los `DeliveryStep` en secuencia, capturando excepciones por paso y devolviendo un `PipelineResult` con el detalle de cada uno.

### Strategy (excel_renderers)
`src/core/excel_renderers/` tiene dos backends para capturar imágenes: `libreoffice` (default) y `html_playwright`. Se selecciona por nombre en el config.

## Flujo de un reporte (caso `ventas`)

```
1. Usuario:  python main.py ventas --config configs/ventas.json
2. CLI:      lee JSON → ReportConfig (Pydantic)
3. CLI:      _run_ventas_report(report_config, contactos, test_mode)
4. Service:  VentasService(data_loader=DataLoader())
             ↓
             config = ReporteVentasConfig(fecha_desde, fecha_hasta, genericos, ...)
             ↓
             result = service.generar_reporte(config)
                  ↓
                  loader.get_sucursales()
                  loader.get_articulos()
                  loader.get_ventas_diarias_con_ruta()
                  loader.get_cobertura_*()
                  ↓
                  procesar_ventas_diarias(...)
                  ↓
                  ExcelWriter.add_sheet(df_bultos)
                  ExcelWriter.add_sheet(df_htls)
                  ExcelWriter.save()
                  ↓
                  return ReporteVentasResult(ruta_archivo, ...)
5. CLI:      DeliveryPipeline.run(ReportArtifact(...), DeliveryConfig)
6. Pipeline: CaptureImageStep → PNG en disco
             SendEmailStep    → SMTP envío
             SendWhatsAppStep → POST localhost:3001/send-image
```

## Decisiones arquitectónicas clave

### ¿Por qué un dict `REPORT_HANDLERS` en vez de polimorfismo?
Permite que `unittest.mock.patch.object(main, "_run_X_report", fake)` intercepte el dispatch sin tocar el registry. Resuelto con `globals()` en runtime.

### ¿Por qué Pydantic para configs y dataclasses para Service config?
- **Pydantic** valida JSON (entrada del usuario) — errores claros si el JSON es inválido.
- **dataclasses** describen el contrato interno entre CLI/Service — sin overhead de validación, son tipos de transición.

### ¿Por qué `DeliveryPipeline` con fallo aislado?
Si la entrega WhatsApp falla (servidor caído), el email igual sale. Si la captura de imagen falla (LibreOffice colgado), el excel queda generado y se puede mandar adjunto.

### ¿Por qué un dispatch en `main.py` y no servicios autodescubiertos?
Explicit > implicit. Los handlers son funciones simples que crean el config y llaman al servicio — fáciles de seguir y testear.

### ¿Por qué `data/output/{slug}/{periodo}/`?
- Output por servicio aísla los archivos de cada reporte.
- Particionamiento por período (`YYYY-MM` o `YYYY-MM-DD`) hace que regenerar un mes pasado sobreescriba sólo ese período.
- `avances` es la única excepción: actualiza un Excel plantilla in-place porque el usuario edita el archivo manualmente entre corridas.

## Capas vs servicios actuales

| Servicio | tiene `processor.py` | usa zonas virtuales | usa cobertura | salida típica |
|----------|----------------------|---------------------|---------------|---------------|
| ventas | ✓ | ✓ | ✓ | xlsx (1 file por supervisor) |
| resumen-mensual | ✓ | ✓ + DIRECTA SUCURSALES | — | xlsx (1 hoja por genérico) |
| graficos-cobertura | ✓ | propio (5 zonas) | ✓ | xlsx + 2 pptx + ~50 PNGs |
| reporte-general-badie | ✓ | — | ✓ (vía SUMPRODUCT) | xlsx (normal + EXTENDIDO) |
| historico-fratelli | — | — | — | xlsx (1 hoja con histórico) |
| ventas-articulo | ✓ | — | — | xlsx por artículo |
| stock-diario | ✓ | — | — | xlsx diario |
| champions-league | — | — | ✓ | xlsx (varias hojas categoría) |
| cartesiano | — | — | — | xlsx |
| avances | — | — | ✓ | actualiza Excel plantilla in-place |
| historico-cliente | — | — | — | xlsx |
| reporte-general-badie | ✓ | — | — | xlsx |
| cobertura | ✓ | — | ✓ | xlsx |
| reporte-rebotes | ✓ | — | — | xlsx (4 hojas + PNG) |

Ver detalles de cada servicio en [02-services.md](02-services.md).
