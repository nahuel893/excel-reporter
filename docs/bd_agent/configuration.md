# BD Agent — Configuration Reference

Referencia completa de variables de entorno, archivos JSON y opciones que controlan el comportamiento del BD Agent. Si recien estas levantando el agente por primera vez, mejor empeza por [`getting-started.md`](./getting-started.md); este doc esta para consulta.

---

## Variables de entorno (`.env`)

El template vive en [`.env.example`](../../.env.example). Las variables se leen **una sola vez al iniciar FastAPI**, salvo lo indicado en *Hot-reload* mas abajo.

> [!IMPORTANT]
> Solo `bd_agent/wiring.py` lee `os.environ` para las variables del agente (RF-070). El resto del paquete recibe la config por dependency injection. Si agregas una variable nueva, modificala ahi.

### Requeridas

| Var | Descripcion | Default | Requerida |
|-----|-------------|---------|-----------|
| `GEMINI_API_KEY` | API key de Google AI Studio (Gemini 2.0 Flash Lite). Si esta vacia o ausente, el router `/agent/*` no se monta. | — | si |
| `AGENT_DB_URL` | DSN Postgres del usuario read-only. Formato: `postgresql://agent_user:<password>@<host>:<port>/<dbname>`. Crear el rol con [`scripts/sql/agent_user.sql`](../../scripts/sql/agent_user.sql). | — | si |

### Opcionales

| Var | Descripcion | Default | Requerida |
|-----|-------------|---------|-----------|
| `WHATSAPP_SERVICE_URL` | URL base del Node service. El smoke test pega contra `<URL>/status`. | `http://localhost:3000` | no |
| `BAILEYS_BASE_URL` | URL que usa el `WhatsAppMessagingGateway` para mandar texto saliente. En produccion deberia ser igual que `WHATSAPP_SERVICE_URL`. | `http://localhost:3000` | no |
| `PYTHON_AGENT_URL` | URL del webhook FastAPI vista **desde el Node service**. El Node hace `POST <URL>/agent/message`. | `http://localhost:8000` | no |
| `SANDBOX_ENABLED` | `true` activa la tool `execute_python_report`. Cualquier otro valor (incluso `1`, `yes`) lo deja apagado. | `false` | no |
| `SANDBOX_TIMEOUT_SECONDS` | Wall-clock antes de matar el container del sandbox. | `30` | no |
| `SANDBOX_IMAGE_TAG` | Tag de la imagen Docker del sandbox. Cambialo solo si retageas la imagen manualmente. | `bd-agent-sandbox:latest` | no |
| `GROQ_API_KEY` | Reservado para un futuro provider fallback. Hoy no se usa. | — | no |

### Notas sobre los puertos

- `WHATSAPP_SERVICE_URL=http://localhost:3000` — usado por **FastAPI** (smoke test + outbound).
- `PYTHON_AGENT_URL=http://localhost:8000` — usado por **Node**. Si corres FastAPI en otro puerto, ajustalo.

Si arrancas Node en otro puerto (por ejemplo 3001 cuando docker-compose ya ocupa el 3000), tenes que setear los **dos**: `WHATSAPP_SERVICE_URL` y `BAILEYS_BASE_URL`.

---

## `configs/contactos_agente.json`

Archivo que define quien puede usar el agente. Esta gitignored (PII). El template versionado es [`configs/contactos_agente.example.json`](../../configs/contactos_agente.example.json).

### Schema

```json
{
  "contacts": [
    {
      "name": "Gustavo Flores",
      "jid": "5493874067242@s.whatsapp.net",
      "cargo": "Supervisor de Ventas",
      "daily_message_limit": 100,
      "permissions": ["ventas", "clientes", "cobertura", "stock"]
    }
  ],
  "settings": {
    "active_hours_start": "07:00",
    "active_hours_end": "22:00",
    "timezone": "America/Argentina/Salta"
  }
}
```

### Campo por campo

#### `contacts[].name`
- **Tipo**: string
- **Descripcion**: nombre humano del contacto. Lo usa el agente para personalizar saludos y respuestas.

#### `contacts[].jid`
- **Tipo**: string
- **Restriccion**: debe terminar en `@s.whatsapp.net` (validado por pydantic). Numeros internacionales sin `+` ni espacios. En Argentina es `549<area><numero>` (notar el `9` antes del area code).
- **Ejemplo**: `5493874067242@s.whatsapp.net`

#### `contacts[].cargo` (opcional)
- **Tipo**: string | null
- **Descripcion**: cargo del contacto (ej. `"Gerente"`, `"Supervisor de Ventas"`). Se inyecta en el system prompt para que el LLM module el tono y el nivel de detalle.

#### `contacts[].daily_message_limit`
- **Tipo**: int >= 0
- **Descripcion**: cantidad maxima de mensajes que el `RateLimiter` acepta en un dia (reset a las 00:00 hora Salta). `0` deshabilita el contacto sin sacarlo de la allowlist.

#### `contacts[].permissions`
- **Tipo**: lista de strings, valores validos: `"ventas"`, `"clientes"`, `"cobertura"`, `"stock"` (enum `Permission` en [`bd_agent/contacts/schema.py`](../../bd_agent/contacts/schema.py)).
- **Descripcion**: que dominios de datos puede consultar el contacto. Se inyecta en el system prompt; el LLM no debe llamar tools de un dominio que el contacto no tenga.

| Permiso | Cubre |
|---------|-------|
| `ventas` | Tablas de hechos de venta (`gold.fact_ventas`, agregaciones diarias/mensuales) |
| `clientes` | Dimensiones de cliente / sucursal y combinacion sucursal-cliente |
| `cobertura` | Tablas `gold.cob_*` (cobertura por preventista, sucursal, ruta) |
| `stock` | Tablas de stock (cuando esten disponibles) |

#### `settings.active_hours_start` / `settings.active_hours_end`
- **Tipo**: string `HH:MM` (formato 24h)
- **Descripcion**: ventana horaria en la que el agente responde. Fuera de esta ventana **se silencia** (no encola, no responde). El `start` es inclusivo, el `end` es exclusivo. Implementado en [`bd_agent/safety/active_hours.py`](../../bd_agent/safety/active_hours.py).

#### `settings.timezone`
- **Tipo**: string IANA tz (ej. `"America/Argentina/Salta"`).
- **Descripcion**: tz contra la que se evalua `active_hours` y el reset diario del `RateLimiter`.

---

## `CONTEXT_DATABASE.md`

Markdown que documenta el schema `gold` para el LLM. Se inyecta en cada `system_prompt`, asi que **todo lo que esta ahi pesa tokens**. Mantenelo conciso.

### Que va

- Tablas relevantes: nombre, descripcion corta, columnas clave, JOINs comunes.
- Convenciones (`fecha_comprobante` no `fecha`; sucursales por `descripcion`, no por id).
- Casos especiales que el LLM tiene que conocer: feriados, zonas virtuales, etc.

### Que NO va

- DDL completos.
- Secrets, hosts, passwords.
- Detalles de columnas que el agente no puede ver (otros schemas).

### Como actualizar

1. Editas `CONTEXT_DATABASE.md` en disco.
2. Pegale POST a `/agent/reload-schema` (ver [api-reference.md](./api-reference.md#post-agentreload-schema)).
3. La proxima llamada al LLM ya usa la version nueva.

No hace falta reiniciar FastAPI.

---

## Permisos: el enum `Permission`

Definido en [`bd_agent/contacts/schema.py`](../../bd_agent/contacts/schema.py):

```python
Permission = Literal["ventas", "clientes", "cobertura", "stock"]
```

Si agregas un permiso nuevo, ademas de actualizar el `Literal`:

1. Documentarlo en este archivo.
2. Mencionarlo en el system prompt ([`bd_agent/conversation/system_prompt.py`](../../bd_agent/conversation/system_prompt.py)) para que el LLM sepa que existe.
3. Actualizar `configs/contactos_agente.example.json`.
4. Las tools que dependen del permiso tienen que validar el permiso del contacto que las invoca.

---

## Hot-reload: que se puede vs que no

### Se recarga sin reiniciar FastAPI

| Que | Como | Endpoint |
|-----|------|----------|
| `configs/contactos_agente.json` | Hot-reload manual | `POST /agent/reload-contacts` |
| `CONTEXT_DATABASE.md` | Hot-reload manual | `POST /agent/reload-schema` |
| Allowlist en el Node service | `fs.watchFile` cada 5s — automatico | (sin endpoint) |

Si el JSON queda invalido en un reload manual, el agente **retiene el estado anterior** y loguea el error. Tu vida no cambia hasta que arregles el archivo.

### Requiere restart

| Que | Por que |
|-----|---------|
| Cualquier variable de `.env` | Se leen una vez en `build_agent_runtime()` |
| `SANDBOX_ENABLED` | Toggle se evalua al construir el `ToolRegistry` |
| Imagen del sandbox actualizada | El runner cachea referencias a la imagen actual |
| Modelos del codigo del agente (`bd_agent/*.py`) | uvicorn `--reload` lo hace automatico en dev |

Para reiniciar el agente sin tirar abajo el resto de la API:

```bash
# Mata uvicorn y volve a levantarlo
pkill -f "uvicorn api:app"
uvicorn api:app --reload --port 8000
```

El Node service no se toca: la sesion de WhatsApp queda intacta entre restarts del Python.
