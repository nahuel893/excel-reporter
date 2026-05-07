# Smoke Test: WhatsApp Inbound → Python Agent Roundtrip (T-082)

Manual roundtrip test plan for the Baileys Node inbound hook and BD agent integration.

---

## Prerequisites

1. `contactos_agente.json` has your test JID in the `contacts` array.
2. Python API is running on port 8000 (`uvicorn api:app --reload --port 8000`).
3. `GEMINI_API_KEY` and `AGENT_DB_URL` are set in your `.env`.
4. WhatsApp service is running and the QR has been scanned.

---

## Step 1 — Start the Python API

```bash
cd /path/to/project
source .venv/bin/activate
uvicorn api:app --reload --port 8000
```

Verify the BD agent router was mounted:

```
INFO:     Application startup complete.
```

The startup log should NOT say "GEMINI_API_KEY o AGENT_DB_URL no configurados".

---

## Step 2 — Start the WhatsApp service

```bash
cd whatsapp-service
node index.js
```

Expected startup log lines:

```
{"level":30,...,"count":1,...,"msg":"Allowlist cargada"}
{"level":30,...,"port":3000,"msg":"WhatsApp service iniciado"}
```

If the session was already authenticated, you should see:

```
{"level":30,...,"phone":"549387...","msg":"WhatsApp conectado"}
```

---

## Step 3 — Verify `/send-text` endpoint

With the service running, test the endpoint directly (session must be open):

```bash
curl -X POST http://localhost:3000/send-text \
  -H "Content-Type: application/json" \
  -d '{"to": "YOUR_JID@s.whatsapp.net", "text": "Hola desde el agente"}'
```

Expected response:

```json
{"ok": true}
```

The message should appear in the WhatsApp DM of the target number.

---

## Step 4 — Send an inbound DM from an allowlisted contact

From the WhatsApp account of the allowlisted contact, send a text message to the bot number.

Expected log in `whatsapp-service`:

```
{"level":30,...,"from":"5493870...@s.whatsapp.net","ts":1234567890,"textLen":28,"msg":"Mensaje entrante aceptado — reenviando al agente BD"}
{"level":30,...,"from":"5493870...@s.whatsapp.net","ts":1234567890,"status":202,"msg":"Mensaje reenviado al agente BD"}
```

Expected log in Python API (FastAPI):

```
INFO:     POST /agent/message 202
```

---

## Step 5 — Verify the agent processes and replies

After a few seconds, the BD agent should:

1. Call the Gemini LLM with the user's message.
2. Execute any tool calls (SQL queries, curated tools).
3. Send the reply via `POST http://localhost:3000/send-text`.

Expected log in `whatsapp-service` when the reply is sent:

```
{"level":30,...,"to":"5493870...@s.whatsapp.net","textLen":120,"msg":"Texto enviado via /send-text"}
```

The reply should appear in the WhatsApp DM of the contact.

---

## Step 6 — Verify deduplication

Send the same message again within 60 seconds (or use the same `ts` value).

Expected log:

```
{"level":20,...,"from":"5493870...@s.whatsapp.net","ts":...,"msg":"Mensaje duplicado ignorado"}
```

No second POST to Python should be made.

---

## Step 7 — Verify non-allowlisted contact is ignored

Send a message from a number NOT in `contactos_agente.json`.

Expected log (debug level — may not appear unless `LOG_LEVEL=debug`):

```
{"level":20,...,"from":"5499999999999@s.whatsapp.net","msg":"Mensaje ignorado — JID no en allowlist"}
```

No POST to Python should be made.

---

## Step 8 — Verify allowlist hot-reload

1. Add a new JID to `configs/contactos_agente.json`.
2. Wait up to 5 seconds.
3. Expected log:

```
{"level":30,...,"msg":"Allowlist file changed — recargando"}
{"level":30,...,"count":2,...,"msg":"Allowlist cargada"}
```

4. Send a message from the newly added JID — it should now be forwarded.

---

## Step 9 — Verify Python unreachable (no retry loop)

1. Stop the Python API.
2. Send a DM from an allowlisted contact.

Expected log in `whatsapp-service`:

```
{"level":40,...,"err":"connect ECONNREFUSED 127.0.0.1:8000","url":"http://localhost:8000/agent/message","msg":"No se pudo reenviar mensaje al agente BD — Python no disponible"}
```

Confirm that NO retry loop occurs (the warning appears only once per message).

---

## Checklist

- [ ] `/send-text` returns `{ok: true}` and message appears in WhatsApp
- [ ] Inbound DM from allowlisted contact is forwarded to Python (`/agent/message`)
- [ ] Python processes message and sends reply via Baileys
- [ ] Duplicate message within 60s is silently dropped
- [ ] Non-allowlisted contact is ignored
- [ ] Allowlist hot-reload works within ~5 seconds
- [ ] Python unreachable → single warning log, no retry loop
- [ ] Existing `/send-image` and `/send-file` endpoints still work

---

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| Allowlist always empty | Check `configs/contactos_agente.json` path; the service reads from `../configs/contactos_agente.json` relative to `whatsapp-service/` |
| No reply from agent | Check `GEMINI_API_KEY` is set and valid; check Python logs for LLM errors |
| `session_not_ready` on `/send-text` | WhatsApp is not connected; scan QR or wait for reconnect |
| Messages from groups forwarded | Should NOT happen — handler filters `@g.us` JIDs; check Baileys version |
