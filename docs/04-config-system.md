# 04 — Sistema de configuración

## Por qué hay un sistema de config

Los reportes son configurables: fechas, genéricos, sucursales filtradas, supervisores, cómo entregar (email/WhatsApp), a quién entregar, qué imágenes capturar. Todo eso vive en JSON validado con Pydantic.

## Archivos de config

```
configs/
├── contactos.json                     # catálogo global de contactos (compartido por todos los reportes)
├── ventas.json                        # config de reporte de ventas
├── resumen_mensual.json               # config resumen mensual
├── champions_league.json
├── historico_fratelli.json
├── stock_diario.json
├── cartesiano.json
├── avances_branca.json
├── graficos_cobertura.json
├── schneider710.json                  # config de ventas-articulo (artículo: SCHNEIDER 710)
├── historico_cliente_example.json     # ejemplo de config historico-cliente
├── reporte_general_badie.json
├── ventas_articulo_smoke.json         # smoke test
├── daily_overrides.json               # overrides para run_daily.py
└── daily_overrides.example.json       # plantilla
```

## Estructura de un config (`tipo + filtros + reportes[]`)

Definida en `src/config/models.py` (Pydantic).

```json
{
  "tipo": "ventas",
  "filtros": {
    "fecha_desde": "2026-04-01",
    "fecha_hasta": "2026-04-30",
    "genericos": ["CERVEZAS", "AGUAS DANONE", "VINOS CCU", "SIDRAS Y LICORES"],
    "con_slicers": false,
    "con_cobertura": true,
    "enviar_email": true,
    "enviar_whatsapp": true
  },
  "reportes": [
    {
      "nombre": "Walter Vilte",
      "filtros": {
        "supervisores": ["Walter Vilte"]
      },
      "capture_images": [
        {"hoja": "Ventas Bultos", "rango": "A1:N50", "renderer": "libreoffice"}
      ],
      "asunto_email": "Ventas - Walter Vilte",
      "enviar_a": {
        "Walter Vilte": {"via": ["whatsapp", "email"]},
        "Daniel Manzur": {"via": ["email_cc"]}
      }
    }
  ]
}
```

### Niveles

1. **`tipo`**: discriminator (literal). Determina qué servicio se invoca.
2. **`filtros`** (`GlobalFilters`): valores compartidos por todos los reportes en este archivo.
3. **`reportes`** (lista de `ReportEntry`): cada entrada genera un xlsx separado con sus propios overrides.

### Pydantic models (`src/config/models.py`)

```python
class GlobalFilters(BaseModel):
    fecha_desde: str
    fecha_hasta: str
    genericos: list[str] | None = None
    categorias: dict[str, Any] | None = None
    con_slicers: bool = True
    con_cobertura: bool = True
    enviar_email: bool = True
    enviar_whatsapp: bool = True
    archivo_plantilla: str | None = None
    id_sucursal: int | None = None
    id_fuerza_ventas: int | None = None
    id_articulo: int | None = None
    whatsapp_enviar_como: str = "imagen"  # "imagen" | "archivo" | "ambos"
    email_adjuntos: list[str] = ["excel"]  # ["excel"] | ["imagen"] | ["excel", "imagen"]


class ReportFilters(BaseModel):
    """Per-report overrides — None = inherit global."""
    supervisores: list[str] | None = None
    sucursales: list[str] | None = None
    genericos: list[str] | None = None
    con_slicers: bool | None = None
    con_cobertura: bool | None = None
    enviar_email: bool | None = None
    enviar_whatsapp: bool | None = None
    id_articulo: int | None = None
    id_sucursal: int | None = None
    clientes: list[dict] | None = None  # [{"id_cliente": int, "id_sucursal": int}]
    articulos: list[int] | None = None
    marcas: list[str] | None = None


class ReportEntry(BaseModel):
    nombre: str
    filtros: ReportFilters | None = None
    capture_image: CaptureImageConfig | None = None  # legacy single
    capture_images: list[CaptureImageConfig] | None = None  # N captures
    enviar_a: dict[str, DeliveryTarget] | None = None
    asunto_email: str | None = None


class ReportConfig(BaseModel):
    tipo: Literal["ventas", "resumen-mensual", "champions-league", ...]
    filtros: GlobalFilters
    reportes: list[ReportEntry]
```

### Captures

```python
class CaptureImageConfig(BaseModel):
    hoja: str            # nombre exacto de la hoja Excel
    rango: str           # "A1:N50"
    renderer: Literal["libreoffice", "html_playwright"] = "libreoffice"
```

`capture_image` (singular, legacy) y `capture_images` (lista) están ambos soportados; si se pasan los dos, `capture_image` se ignora (`@model_validator normalize_captures`).

## Catálogo de contactos (`contactos.json`)

```json
{
  "Walter Vilte": {
    "email": "wvilte@danielmanzur.com",
    "whatsapp_grupo": "5493874067769"
  },
  "Daniel Manzur": {
    "email": "dmanzur@danielmanzur.com"
  },
  "Nahuel Aguirre": {
    "email": "naguirre@danielmanzur.com",
    "whatsapp_grupo": "5493885099320"
  }
}
```

**Reglas** (`ContactInfo`):
- Cada contacto debe tener al menos uno: `email`, `telefono`, `whatsapp_grupo`.
- Los reportes referencian al contacto por nombre (clave del dict). Si un report referencia un nombre que no existe → `ValidationError` al cargar.
- `whatsapp_grupo` puede ser un teléfono individual (ARS: `5493xxxxxxxxx`) o un ID de grupo de WhatsApp (formato Baileys).

## Resolución contacto → entrega

`src/config/resolver.py` (228 líneas) toma:
- el `ReportEntry.enviar_a` (dict `{"Walter Vilte": {"via": ["whatsapp", "email"]}}`)
- el catálogo de contactos
- los flags `enviar_email` / `enviar_whatsapp`

y produce el `DeliveryConfig` que consume el pipeline:

```python
class DeliveryConfig(BaseModel):
    capture_image: CaptureConfig | None
    capture_images: list[CaptureConfig]
    email: EmailConfig | None       # destinatarios + cc + asunto + adjuntos
    whatsapp: WhatsAppConfig | None  # grupos + enviar_como
    log_steps: bool = True
```

### Mapeo `via` → canal

| `via` | resuelve a |
|-------|------------|
| `email` | agrega el contacto a `email.destinatarios` |
| `email_cc` | agrega el contacto a `email.cc` |
| `whatsapp` | agrega `whatsapp_grupo` del contacto a `whatsapp.grupos` |

Si el contacto no tiene `email` pero el `via` dice `email`, se ignora silenciosamente con un log warn.

## Test mode (`--test-mode`)

Activable via:
- CLI: `python main.py ventas --config X.json --test-mode`
- Daily: `python scripts/run_daily.py --test-mode`
- Env var: `INFORMES_TEST_MODE=1 python main.py ...`

Cuando está activo, **toda la entrega se redirige a "Nahuel Aguirre"** (o el contacto que esté hardcoded como test fallback en el resolver). Útil para probar antes de un blast.

Implementado en `src/config/resolver.py:apply_test_mode_redirect()`.

## Daily overrides (`configs/daily_overrides.json`)

Archivo opcional para suprimir o silenciar servicios en el daily sin tocar los configs base.

```json
{
  "stock-diario": {
    "ejecutar": false,
    "razon": "feriado: no abre el depósito"
  },
  "champions-league": {
    "ejecutar": true,
    "enviar": false,
    "razon": "QA — generar pero no enviar hasta validar"
  }
}
```

Reglas:
- Sin archivo → todos los servicios ejecutan y entregan normal.
- `ejecutar: false` → el servicio NO se ejecuta (ni siquiera genera).
- `ejecutar: true, enviar: false` → genera el archivo pero LIMPIA el `enviar_a` de cada reporte (no manda nada).
- `razon` se loguea para auditar.

`daily_overrides.example.json` es la plantilla de referencia.

## Cómo agregar un servicio nuevo

1. **Modelo**: agregar el slug al `Literal` de `ReportConfig.tipo` en `src/config/models.py`.
2. **Servicio**: crear `src/services/{slug}/service.py` con su `{Slug}Service(BaseService)`, `{Slug}Config`, `{Slug}Result`.
3. **Handler**: agregar `_run_{slug}_report(report_config, contactos, test_mode)` en `main.py` (mismo patrón que los otros `_run_*`).
4. **Registry**: registrar el handler en `REPORT_HANDLERS = {"slug": "_run_{slug}_report"}`.
5. **Subparser** (opcional): si querés invocarlo sin config JSON, agregar `cmd_{slug}` y subparser en `main.py`.
6. **API route** (opcional): agregar `src/api/routes/{slug}.py` y registrarlo en `src/api/routes/__init__.py`.
7. **Daily** (opcional): agregar `Servicio(...)` en `scripts/run_daily.py:SERVICIOS`.
8. **Config ejemplo**: crear `configs/{slug}.json` o `{slug}_example.json`.

## Validación

`load_report_config(path)` y `load_contacts(path)` están en `src/config/resolver.py`. Devuelven los modelos Pydantic ya validados o lanzan `ValidationError` con detalle del campo que falló.

```python
from src.config.resolver import load_report_config, load_contacts

config = load_report_config(Path("configs/ventas.json"))
contactos = load_contacts(Path("configs/contactos.json"))
config.validate_contacts(contactos)  # lanza si referencia un contacto que no existe
```
