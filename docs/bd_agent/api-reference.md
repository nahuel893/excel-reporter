# BD Agent — API Reference

Reference completo de los endpoints HTTP del agente. El agente esta compuesto por dos procesos que se hablan via HTTP:

- **FastAPI** (Python, port 8000) — orquestador del agente.
- **whatsapp-service** (Node, port 3000) — bridge de Baileys hacia WhatsApp.

```
WhatsApp -> Baileys (Node) -> POST /agent/message (FastAPI) -> AgentTurn
                                              |
                              FastAPI -> POST /send-text (Node) -> WhatsApp
```

Todos los endpoints son internos al deploy. **Ninguno tiene autenticacion**: poneles un firewall o exponelos solo en localhost / red privada.

---

## FastAPI (port 8000)

### POST `/agent/message`

Webhook que recibe DMs reenviados por el `whatsapp-service`. Se procesa de forma **no bloqueante** (`BackgroundTask`): la respuesta se devuelve inmediatamente y el pipeline real corre despues.

Implementado en [`bd_agent/transport/router.py`](../../bd_agent/transport/router.py).

**Request**

```http
POST /agent/message HTTP/1.1
Content-Type: application/json

{
  "from": "5493874000000@s.whatsapp.net",
  "text": "que ventas tuvimos hoy?",
  "ts": 1746662400.0
}
```

| Campo | Tipo | Descripcion |
|-------|------|-------------|
| `from` | string | JID del remitente (debe terminar en `@s.whatsapp.net`). Mapeado via alias porque `from` es palabra reservada en Python. |
| `text` | string | Cuerpo del mensaje en texto plano. |
| `ts` | float | Unix timestamp en segundos. Se usa como clave de deduplicacion. |

**Response (200 OK)**

```json
{ "ok": true }
```

**Response (202 Accepted) — duplicado**

Si la misma `(from, ts)` llega dos veces dentro de los 60 segundos:

```json
{ "status": "duplicate" }
```

**Idempotencia**: dedup interno de 60s por `(jid, ts)`. Garantiza que reintentos del Node service no disparen dos turnos del agente.

**Curl**

```bash
curl -X POST http://localhost:8000/agent/message \
  -H "Content-Type: application/json" \
  -d '{"from":"5493874000000@s.whatsapp.net","text":"hola","ts":1746662400}'
```

---

### POST `/agent/reload-contacts`

Recarga `configs/contactos_agente.json` desde disco sin reiniciar FastAPI. Util cuando agregas un contacto o cambias `daily_message_limit`.

Si el JSON es invalido se retiene el estado anterior y se loguea el error (RF-003/S2).

**Request**

```http
POST /agent/reload-contacts HTTP/1.1
```

Sin body.

**Response (200 OK)**

```json
{ "ok": true, "action": "contacts_reloaded" }
```

**Curl**

```bash
curl -X POST http://localhost:8000/agent/reload-contacts
```

---

### POST `/agent/reload-schema`

Recarga `CONTEXT_DATABASE.md` desde disco sin reiniciar. Lo siguiente que el LLM vea va a usar la version actualizada del schema doc.

**Request**

```http
POST /agent/reload-schema HTTP/1.1
```

Sin body.

**Response (200 OK)**

```json
{ "ok": true, "action": "schema_reloaded" }
```

**Curl**

```bash
curl -X POST http://localhost:8000/agent/reload-schema
```

---

### GET `/agent/metrics`

Snapshot de los counters in-memory. **Sin autenticacion** — exponer solo en red interna.

Reset al reiniciar FastAPI (no hay persistencia).

**Response (200 OK)**

```json
{
  "messages_received": 142,
  "messages_sent": 138,
  "tool_calls_by_name": {
    "get_ventas_cliente": 53,
    "get_clientes_sucursal": 12,
    "run_sql_select": 4
  },
  "errors_by_type": {
    "GeminiTimeout": 1
  },
  "errors_total": 1,
  "tokens_in_total": 284000,
  "tokens_out_total": 71500,
  "uptime_seconds": 18432.4
}
```

**Curl**

```bash
curl http://localhost:8000/agent/metrics | jq
```

---

## whatsapp-service (port 3000)

Servicio Node basado en [`@whiskeysockets/baileys`](https://github.com/WhiskeySockets/Baileys). Implementado en [`whatsapp-service/index.js`](../../whatsapp-service/index.js).

### GET `/status`

Estado actual de la sesion de WhatsApp.

**Response (200 OK)**

```json
{
  "connected": true,
  "phone": "5493874000000"
}
```

| Campo | Tipo | Descripcion |
|-------|------|-------------|
| `connected` | bool | `true` despues de escanear QR y conectar. |
| `phone` | string \| null | Numero del bot, sin prefijo `@s.whatsapp.net`. |

**Curl**

```bash
curl http://localhost:3000/status
```

---

### POST `/send-text`

Endpoint usado **por el agente Python** para mandar la respuesta. Aceita solo DMs (`@s.whatsapp.net`); rechaza grupos (`@g.us`).

**Request**

```http
POST /send-text HTTP/1.1
Content-Type: application/json

{
  "to": "5493874000000@s.whatsapp.net",
  "text": "Hoy facturamos $1.234.567 en CERVEZAS."
}
```

**Response (200 OK)**

```json
{ "ok": true }
```

**Errores**

| Status | Body | Cuando |
|--------|------|--------|
| 400 | `{"ok": false, "error": "to es requerido (string)"}` | Falta `to` o no es string. |
| 400 | `{"ok": false, "error": "to debe terminar en @s.whatsapp.net (solo DMs)"}` | JID de grupo. |
| 503 | `{"error": "session_not_ready", ...}` | Baileys no autenticado todavia (escaneaste QR?). |

**Curl**

```bash
curl -X POST http://localhost:3000/send-text \
  -H "Content-Type: application/json" \
  -d '{"to":"5493874000000@s.whatsapp.net","text":"prueba"}'
```

---

### POST `/send-file-dm`

Manda un archivo como **documento** (no como imagen) a un DM especifico. Lo usa el sandbox del agente para mandar Excel/PDF generados por el LLM.

Implementado en [`whatsapp-service/lib/send-file-dm-router.js`](../../whatsapp-service/lib/send-file-dm-router.js).

**Request**

`multipart/form-data` con:

| Campo | Tipo | Requerido | Descripcion |
|-------|------|-----------|-------------|
| `to` | string | si | JID destino, debe terminar en `@s.whatsapp.net`. |
| `caption` | string | no | Texto que acompaña el adjunto. |
| `file` | binary | si | El archivo (xlsx, pdf, png, jpg, csv). |

**Response (200 OK)**

```json
{ "ok": true }
```

**Errores**

| Status | Body | Cuando |
|--------|------|--------|
| 400 | `{"ok": false, "error": "invalid 'to' jid: must end with @s.whatsapp.net (DMs only)"}` | JID invalido o de grupo. |
| 400 | `{"ok": false, "error": "no file uploaded"}` | Sin archivo en el form. |
| 503 | `{"ok": false, "error": "session not ready"}` | Baileys no autenticado. |
| 500 | `{"ok": false, "error": "<message>"}` | Error de Baileys al enviar. |

**Curl**

```bash
curl -X POST http://localhost:3000/send-file-dm \
  -F "to=5493874000000@s.whatsapp.net" \
  -F "caption=Resumen abril" \
  -F "file=@/tmp/resumen-abril.xlsx"
```

---

### POST `/send-image` y POST `/send-file`

> [!NOTE]
> Estos endpoints **existen previos al agente** y los siguen usando los reportes batch del proyecto principal (envios a grupos por nombre). El agente NO los invoca; usa `/send-text` y `/send-file-dm`. Documentados aca solo para que no te confundas si los ves en el codigo del Node service.

Resumen breve:

- **POST `/send-image`** — multipart `{ group_name, caption?, image }`. Resuelve `group_name` contra los grupos del bot.
- **POST `/send-file`** — multipart `{ group_name, caption?, file }`. Mismo resolver.

Ambos hacen lookup case-insensitive del nombre de grupo en `sock.groupFetchAllParticipating()`.
