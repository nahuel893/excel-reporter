# BD Agent — Troubleshooting

Problemas comunes que aparecen al levantar y operar el agente, con causa probable y fix concreto. Si tu sintoma no esta aca, revisa el [`README.md`](./README.md) seccion *Observabilidad* — los logs JSON suelen decir exactamente que pasa.

---

## El agente no responde a mis DMs

### Sintoma
Mandas un mensaje al numero del bot. No llega respuesta. El Node service ni siquiera loguea `"Mensaje entrante aceptado"`.

### Causa probable
Puede ser cualquiera de las cuatro capas de safety. Las chequeamos en orden:

#### 1. JID no esta en `contactos_agente.json`

```bash
# En los logs del Node service
{"from":"5493874...","msg":"Mensaje ignorado — JID no en allowlist"}
```

**Fix**: agregar tu JID a `configs/contactos_agente.json` y recargar:

```bash
curl -X POST http://localhost:8000/agent/reload-contacts
```

El Node service tambien recarga solo cada 5s via `fs.watchFile`.

#### 2. Fuera de `active_hours`

El `ActiveHoursGuard` silencia mensajes fuera de la ventana configurada en `settings.active_hours_*`. Default: 07:00-22:00 Salta.

**Fix**: ampliar la ventana en `configs/contactos_agente.json` o esperar al horario habil.

#### 3. Daily rate limit alcanzado

```bash
# En errors.log o en stdout de FastAPI
{"event_type":"daily_limit_reached","jid_hash":"a1b2c3d4"}
```

**Fix**: subir `daily_message_limit` para ese contacto (default 100) o esperar a las 00:00 Salta para el reset.

#### 4. Mensaje desde el numero del bot mismo (Note to Self)

El handler `messages.upsert` filtra `msg.key.fromMe` con una excepcion: si `remoteJid === botJid`, lo permite (es self-chat). Si tu sesion de Baileys reporta un `botJid` distinto al esperado, el self-chat queda mudo.

**Fix**: probar desde **otro numero** que este en la allowlist. Si necesitas usar el self-chat, verificar en los logs que `botJid` se haya resuelto bien (`{"phone":"..."} WhatsApp conectado`).

---

## WhatsApp service: connection 401 / `loggedOut`

### Sintoma

```
{"statusCode":401,"msg":"Conexion cerrada. Reconectando: false"}
```

El Node service no se reconecta solo (porque `loggedOut` desactiva el `shouldReconnect`).

### Causa
La sesion de Baileys quedo invalidada — desvinculaste el dispositivo desde el celular, o WhatsApp Web te echo por inactividad.

### Fix
Borrar la sesion y volver a escanear el QR:

```bash
cd whatsapp-service
rm -rf session/
node index.js
# Escaneas el QR nuevo desde el celular: WhatsApp > Dispositivos vinculados > Vincular
```

> [!IMPORTANT]
> Verifica primero que el archivo lock no este en un docker-compose distinto. Si tenes dos procesos de Node corriendo contra la misma `session/` se pelean por los locks y entran en bucle de reconexion.

---

## FastAPI no monta `/agent/*`

### Sintoma

Al iniciar `uvicorn api:app` ves:

```
BD Agent not started: missing env vars GEMINI_API_KEY
```

o, peor, no ves `BD Agent mounted at /agent` y los endpoints `/agent/message` devuelven 404.

### Causa
`bd_agent/wiring.py` requiere **dos** variables: `GEMINI_API_KEY` y `AGENT_DB_URL`. Si falta alguna o esta en blanco, `build_agent_runtime()` retorna `None` y `api.py` no monta el router.

### Fix

```bash
# Verifica que .env tenga las dos
grep -E "^(GEMINI_API_KEY|AGENT_DB_URL)=" .env

# Y que se hayan exportado (uvicorn lee .env via python-dotenv si lo tenes)
echo $GEMINI_API_KEY
echo $AGENT_DB_URL
```

Reinicia FastAPI. Si la variable existe pero el agente sigue sin montar, mira los logs por `BD Agent failed to initialise:` — la excepcion exacta te dice si fue la BD, el JSON de contactos, o la conexion a Gemini.

---

## Sandbox tool no se registra

### Sintoma

En los logs:

```
{"event":"sandbox.disabled","reason":"SANDBOX_ENABLED!=true"}
```

o

```
{"event":"sandbox.image_missing","image":"bd-agent-sandbox:latest"}
```

El agente arranca pero no expone `execute_python_report`.

### Causa A: la flag esta apagada

`SANDBOX_ENABLED` debe ser exactamente `"true"` (case-insensitive). `1`, `yes`, `on` **no funcionan**.

**Fix**:
```bash
# .env
SANDBOX_ENABLED=true
```
Reiniciar FastAPI.

### Causa B: la imagen Docker no esta buildeada

```bash
docker image inspect bd-agent-sandbox:latest
# si exit code != 0, la imagen no existe
```

**Fix**:
```bash
bash scripts/build_sandbox_image.sh
```

Primer build tarda 3-8 min (numpy/pandas/matplotlib). Reintentos quedan en ~5s gracias al cache.

Verifica con el smoke test:
```bash
SANDBOX_ENABLED=true python -m bd_agent.scripts.smoke_test
```

---

## Docker daemon no esta corriendo

### Sintoma

El smoke test con `SANDBOX_ENABLED=true` reporta:

```
✗ docker_daemon  [error: docker info exited 1]
```

o `[error: docker binary not found]`.

### Fix

```bash
# Arrancar el daemon
sudo systemctl start docker

# Verificar
docker info | head -5
```

Si tu usuario no esta en el grupo `docker`, agregalo y re-logueate:

```bash
sudo usermod -aG docker $USER
# cerrar sesion y volver a entrar (newgrp docker tambien anda en el shell actual)
```

---

## "No se pudo conectar al microservicio WhatsApp"

### Sintoma

Logs de FastAPI:

```
httpx.ConnectError: All connection attempts failed
... while sending POST http://localhost:3000/send-text
```

El usuario manda un DM, el agente lo procesa, pero la respuesta nunca llega.

### Causa
El Node service no esta corriendo, esta en otro puerto, o `WHATSAPP_SERVICE_URL` / `BAILEYS_BASE_URL` apuntan a un puerto distinto al real.

### Fix

```bash
# Confirmar que Node esta arriba
curl http://localhost:3000/status
# {"connected":true,"phone":"..."}

# Si no responde, levantarlo
cd whatsapp-service && node index.js
```

Si Node corre en otro puerto (por ejemplo 3001), setear **las dos** variables en `.env`:

```env
WHATSAPP_SERVICE_URL=http://localhost:3001
BAILEYS_BASE_URL=http://localhost:3001
```

Y reiniciar FastAPI.

---

## Two Node processes fighting (statusCode 440 reconnect loop)

### Sintoma

```
{"statusCode":440,"msg":"Conexion cerrada. Reconectando: true"}
```

en bucle, cada pocos segundos.

### Causa
Hay **dos procesos** de `whatsapp-service/index.js` apuntando a la **misma** carpeta `session/`. WhatsApp solo permite una sesion activa por dispositivo vinculado, asi que se patean entre si.

### Fix

```bash
# Encontrar los procesos
pgrep -af "node.*whatsapp-service"

# Matar todos menos uno (o todos y volver a levantar uno solo)
pkill -f "node.*whatsapp-service"

cd whatsapp-service && node index.js
```

Si usas docker-compose **y** corres Node manualmente, elegis uno solo: o `docker-compose up whatsapp-service` o `node index.js`. Nunca los dos a la vez contra la misma `session/`.

---

## Tests fallan con `from src.services` import

### Sintoma

```
ImportError: cannot import name 'X' from 'src.services...'
```

corriendo tests del agente.

### Causa
Por diseño, **`bd_agent/` no debe importar de `src/`** (RF-070, ver [README seccion 9](./README.md#9-extracting-bd_agent-to-a-standalone-project)). El requisito es que el paquete sea extraible a su propio repo. Si ves un import asi, alguien rompio la regla.

### Fix

```bash
# Buscar todos los imports prohibidos
rg -n "from src\." bd_agent/
rg -n "import src\." bd_agent/

# Verificar tambien los tests del agente (deberian usar fakes locales)
rg -n "from src\." tests/bd_agent/
```

Cualquier match es un bug. Reemplazar por una abstraccion local (Protocol en `contracts.py`) y mover la implementacion concreta a `bd_agent/integrations/` o `bd_agent/conversation/`.

---

## LibreOffice lockfile bloquea reportes (no es bd_agent)

### Sintoma

Reportes batch (resumen-mensual, ventas) fallan con:

```
PermissionError: [Errno 13] Permission denied: '.~lock.<archivo>.xlsx#'
```

### Causa

> [!NOTE]
> **Esto NO es un problema del bd_agent**, pero se confunde porque ambos escriben en `data/output/`. Lo dejamos documentado aca porque es la confusion mas comun.

Tenes el archivo abierto en LibreOffice/Excel, que crea un lockfile (`~lock.archivo.xlsx#`).

### Fix

Cerrar LibreOffice/Excel. Si quedo huerfano:

```bash
fd -H "~lock\." data/output/ -x rm {}
```

El bd_agent **no escribe** en `data/output/` — solo el sandbox genera archivos, y los entrega via stream HTTP a Baileys. No deja archivos en disco visibles para el usuario.

---

## Como debuggear paso a paso

Si nada de lo anterior aplica, podes seguir el flujo de un mensaje desde la entrada hasta la salida:

1. **Llega al Node?** Logs de `whatsapp-service` deben mostrar `Mensaje entrante aceptado — reenviando al agente BD`. Si no, el problema es la conexion de WhatsApp / allowlist en Node.

2. **Llega a FastAPI?** En FastAPI deberias ver el log de `inbound_message` con `jid_hash`. Si no, mira el error en el Node (`No se pudo reenviar mensaje al agente BD`) — usualmente FastAPI no esta arriba o `PYTHON_AGENT_URL` apunta mal.

3. **El SafetyGuard lo deja pasar?** Buscar logs de `denied_by:` en stdout. Te dice cual de los cuatro guards bloqueo.

4. **El LLM responde?** El log `outbound_message` con `tokens_in`/`tokens_out` confirma que Gemini contesto. Si no, mira `errors_by_type` en `/agent/metrics` — `GeminiTimeout`, `GeminiQuota`, etc.

5. **Se manda al usuario?** Si no aparece en WhatsApp pero `outbound_message` se logueo, el problema es la conexion FastAPI -> Node `/send-text`.

Y si el rastro se pierde en algun punto, encende un log de debug temporal:

```bash
LOGLEVEL=DEBUG uvicorn api:app --port 8000
```
