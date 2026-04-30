# 05 — Pipeline de entrega

## Concepto

Una vez que un servicio genera el xlsx, no termina ahí. El **delivery pipeline** ejecuta una secuencia de pasos opcionales:

1. **Capturar imagen** (CaptureImageStep): renderiza un rango Excel a PNG.
2. **Enviar email** (SendEmailStep): SMTP con adjuntos (excel y/o imagen).
3. **Enviar WhatsApp** (SendWhatsAppStep): postea en grupos vía microservicio Node.

Cada paso es independiente y puede fallar sin romper los demás (**fallo aislado**).

## Implementación

`src/delivery/pipeline.py` (152 líneas) define:

- **`DeliveryStep`** (ABC): cada paso implementa `execute(artifact, config, logger) -> StepResult`.
- **`DeliveryPipeline`**: ejecuta los pasos en orden, captura excepciones por paso, retorna `PipelineResult`.
- **`ReportArtifact`**: lo que produce el servicio (`ruta_excel`, `rutas_imagenes`, `metadata`).
- **`DeliveryConfig`**: config Pydantic con `capture_images`, `email`, `whatsapp`, `log_steps`.

```python
class DeliveryPipeline:
    def __init__(self, steps: list[DeliveryStep]):
        self.steps = steps

    def run(self, artifact: ReportArtifact, config: DeliveryConfig) -> PipelineResult:
        result = PipelineResult()
        for step in self.steps:
            try:
                step_result = step.execute(artifact, config, self.logger)
            except Exception as exc:
                self.logger.error("Error inesperado en %s: %s", type(step).__name__, exc)
                step_result = StepResult(status="error", step_name=type(step).__name__, message=str(exc))
            result.steps.append(step_result)
        return result
```

## Pasos disponibles

### 1. CaptureImageStep (`src/delivery/steps/capture_image.py`, 88 líneas)

**Para qué**: tomar un rango Excel (`A1:N50`) y exportarlo a PNG.

**Backends** (en `src/core/excel_renderers/`):
- `libreoffice` (default): `libreoffice --headless --convert-to pdf` + `pdftoppm` para extraer la página como PNG. Requiere LibreOffice instalado.
- `html_playwright`: convierte el rango a HTML con `xlsx2html` y lo renderiza con Playwright Chromium. Requiere Playwright + Chromium.

**Config** (Pydantic):
```python
class CaptureConfig(BaseModel):
    hoja: str
    rango: str        # "A1:H20"
    renderer: str = "libreoffice"
```

**Output**: PNG en el mismo directorio que el xlsx, con nombre `{xlsx_stem}_{rango_id}.png`. Las rutas se agregan a `artifact.rutas_imagenes`.

**Selección dinámica del backend**: `excel_renderers.get_renderer(name)` retorna la implementación. Permite agregar otros backends sin tocar el step.

### 2. SendEmailStep (`src/delivery/steps/send_email.py`, 77 líneas)

**Para qué**: enviar el reporte por SMTP.

**Config**:
```python
class EmailConfig(BaseModel):
    destinatarios: list[str]
    cc: list[str] = []
    asunto: str | None = None
    adjuntos: list[Literal["excel", "imagen"]] = ["excel"]
```

**Lógica**:
- Lee credenciales SMTP de `config/settings.py` (variables: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`).
- Si `adjuntos` incluye `"excel"`: adjunta `artifact.ruta_excel`.
- Si `adjuntos` incluye `"imagen"`: adjunta cada PNG en `artifact.rutas_imagenes`.
- Asunto: `config.email.asunto` o por default `f"{artifact.metadata.nombre}"`.
- Body: HTML simple con el nombre del reporte y la fecha.

**Implementación SMTP**: `src/core/email_sender.py` (90 líneas). Usa `smtplib` + `email.mime`.

**Falla común**: credenciales mal configuradas → `SMTPAuthenticationError`. El step retorna `StepResult(status="error", message=str(exc))`.

### 3. SendWhatsAppStep (`src/delivery/steps/send_whatsapp.py`, 64 líneas)

**Para qué**: postear el reporte en grupos/contactos de WhatsApp.

**Config**:
```python
class WhatsAppConfig(BaseModel):
    grupos: list[str]                              # IDs de grupos o teléfonos
    enviar_como: Literal["imagen", "archivo", "ambos"] = "imagen"
```

**Lógica**:
- Cliente HTTP en `src/core/whatsapp_client.py` (178 líneas).
- Endpoint: `WHATSAPP_SERVICE_URL` (default `http://localhost:3001`).
- Por cada grupo:
  - `enviar_como=imagen`: POST `/send-image` con cada PNG en `rutas_imagenes`.
  - `enviar_como=archivo`: POST `/send-file` con el xlsx.
  - `enviar_como=ambos`: ambos.
- Caption: `artifact.metadata.nombre` o `xlsx_stem`.

**Errores típicos**:
- HTTP 503 → microservicio caído o sesión WhatsApp expirada (`{"statusCode":401}` en logs del servicio).
- HTTP 404 → grupo/contacto no existe.
- Connection refused → servicio Node no está corriendo.

Cuando uno o varios grupos fallan, el step retorna `status="error"` con detalle por grupo: `"Errores en N grupo(s): grupo: error; ..."`. Los grupos exitosos quedan registrados igual.

## Cómo se arma el pipeline

Cada handler en `main.py` construye el pipeline para el reporte:

```python
def _run_ventas_report(report_config, contactos, test_mode):
    # 1. Generar el xlsx
    service = VentasService()
    result = service.generar_reporte(config)
    
    # 2. Construir ReportArtifact
    artifact = ReportArtifact(
        ruta_excel=result.ruta_archivo,
        rutas_imagenes=[],
        metadata={"nombre": report_entry.nombre},
    )
    
    # 3. Resolver config de entrega
    delivery_config = build_delivery_config(report_entry, contactos, test_mode)
    
    # 4. Ejecutar pipeline
    pipeline = DeliveryPipeline(steps=[
        CaptureImageStep(),
        SendEmailStep(),
        SendWhatsAppStep(),
    ])
    pipeline_result = pipeline.run(artifact, delivery_config)
    
    # 5. Loguear resultado por step
    for step_result in pipeline_result.steps:
        marker = {"success": "✓", "skipped": "-", "error": "✗", "partial": "⚠"}[step_result.status]
        print(f"  [{marker}] {step_result.step_name}: {step_result.message}")
```

## Estructura de `ReportArtifact`

```python
@dataclass
class ReportArtifact:
    ruta_excel: Path
    rutas_imagenes: list[Path] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    
    # Backwards-compat: legacy single-image accessor
    @property
    def ruta_imagen(self) -> Path | None:
        return self.rutas_imagenes[0] if self.rutas_imagenes else None
```

`metadata` se usa libremente — comúnmente trae `nombre` (para el caption / asunto).

## Estructura de `PipelineResult`

```python
@dataclass
class StepResult:
    status: Literal["success", "skipped", "error", "partial"]
    step_name: str
    message: str = ""
    artifact_path: Path | None = None

@dataclass
class PipelineResult:
    steps: list[StepResult] = field(default_factory=list)
    
    @property
    def success(self) -> bool:
        return all(s.status not in ("error", "partial") for s in self.steps)
```

## Logging del pipeline

```
Pipeline de entrega:
  [✓] CaptureImageStep: Imagenes generadas: REPORTE[libreoffice]:Champions League_REPORTE_C3_X70.png
  [✓] SendEmailStep: Email enviado a ['gfarah@danielmanzur.com']
  [✗] SendWhatsAppStep: Errores en 1 grupo(s): 5493874067769: Server error '503 Service Unavailable'
  Advertencia: algunos pasos fallaron (ver logs).
```

`log_steps: true` (default) imprime info al inicio y fin de cada step. El orquestador resume con `[marker] StepName: message`.

## WhatsApp client (`src/core/whatsapp_client.py`)

Wrapper sobre `requests` que mapea los métodos del microservicio Node:

| Método | Endpoint del servicio | Body |
|--------|----------------------|------|
| `client.send_text(grupo, texto)` | `POST /send-text` | `{to, text}` |
| `client.send_image(grupo, png_path, caption)` | `POST /send-image` | multipart con `image` + `caption` + `to` |
| `client.send_file(grupo, file_path, caption)` | `POST /send-file` | multipart con `file` + `caption` + `to` |
| `client.is_ready()` | `GET /health` | retorna `{ready: bool}` |

**Reintentos**: NO. Si falla, falla. La lógica de retry queda para otra capa (no implementada).

**Timeout**: 60s por request (subir si los archivos son grandes).

## Email sender (`src/core/email_sender.py`)

Función única `send_email(to, subject, html_body, attachments, cc, bcc)`. Levanta `EmailSenderError` si el servidor SMTP rechaza.

## Captura: detalles del backend LibreOffice

`src/core/excel_renderers/libreoffice.py`:

1. Abre el xlsx con `libreoffice --headless --convert-to pdf` (limita a la hoja indicada).
2. Convierte el PDF a PNG con `pdftoppm -r 150 -f 1 -l 1`.
3. Recorta el PNG al rango deseado (calculado a partir de las dimensiones de la página y el rango Excel pedido).

**Limitación**: el corte exacto del rango depende de cómo LibreOffice interprete el zoom y el page break. En la práctica funciona bien para rangos pequeños (e.g. `A1:H30`).

**Alternativa**: `html_playwright` produce render más fiel pero es más lento (Playwright Chromium pesa).
