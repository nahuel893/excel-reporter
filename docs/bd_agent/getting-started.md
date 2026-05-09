# BD Agent — Getting Started

Esta guia te lleva de **0** (repo recien clonado) a **agente respondiendo en WhatsApp**. Esta pensada para alguien que nunca levanto el agente en su maquina.

Si ya levantaste el agente alguna vez y solo necesitas operarlo, saltea esta guia y leete `AGENTS.md` (seccion *Asistente WhatsApp (BD Agent)*) o el [troubleshooting](./troubleshooting.md).

---

## Que es

El BD Agent es un asistente de WhatsApp que responde preguntas en lenguaje natural sobre el Data Warehouse. Recibe DMs, las traduce a SQL contra `gold.*` (read-only), y devuelve la respuesta al mismo chat. Internamente usa Gemini 2.0 Flash Lite para razonar y un set de tools curadas para consultar la BD.

Para arquitectura completa ver [`README.md`](./README.md). Para conocer los endpoints HTTP ver [`api-reference.md`](./api-reference.md).

---

## Pre-requisitos

| Componente | Version | Notas |
|------------|---------|-------|
| Python | 3.12+ | Lo mismo que el resto del proyecto |
| Node.js | 18+ | Solo para `whatsapp-service/` (Baileys) |
| PostgreSQL | 13+ | Acceso al DW; el script `agent_user.sql` corre como superuser |
| Docker (opcional) | 24+ | Solo si vas a habilitar el sandbox de reportes Python |
| Cuenta Google | — | Para sacar la API key gratis de Gemini |
| WhatsApp en el celular | — | Para escanear el QR de Baileys una vez |

> [!IMPORTANT]
> El agente NO funciona sin `GEMINI_API_KEY` ni sin `AGENT_DB_URL`. Si alguna falta, FastAPI arranca pero el router `/agent/*` no se monta y veras `BD Agent not started: missing env vars` en los logs.

---

## Pasos

### 1. Clonar y crear venv

```bash
git clone <repo-url>
cd "Informes Badie"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Y para el servicio de Node:

```bash
cd whatsapp-service
npm install
cd ..
```

### 2. Crear el rol `agent_user` en Postgres

Editar primero el script y reemplazar `'CHANGEME'` por una password real:

```bash
# Edita scripts/sql/agent_user.sql, busca la linea:
#   CREATE ROLE agent_user WITH LOGIN PASSWORD 'CHANGEME';
# y poneles una password fuerte.

psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/agent_user.sql
```

El script es idempotente: lo podes correr varias veces sin romper nada. Otorga `USAGE` sobre el schema `gold` y `SELECT` sobre todas las tablas existentes y futuras. Detalles completos en [`scripts/sql/agent_user.sql`](../../scripts/sql/agent_user.sql).

### 3. Conseguir API key de Gemini

1. Ir a https://aistudio.google.com/app/apikey
2. *Create API key* (free tier: 1500 requests/dia, alcanza de sobra)
3. Copiar el valor — lo vas a pegar en `.env` en el siguiente paso

### 4. Configurar `.env`

Copiar el ejemplo y editarlo:

```bash
cp .env.example .env
```

Variables minimas que tenes que setear para arrancar el agente:

```env
# Tu DW
DB_HOST=localhost
DB_PORT=5432
DB_NAME=dwh_db
DB_USER=reporter_user
DB_PASSWORD=<la password real>

# Conexion read-only que va a usar el agente
AGENT_DB_URL=postgresql://agent_user:<password-del-paso-2>@localhost:5432/dwh_db

# La API key del paso 3
GEMINI_API_KEY=<pega-la-aca>

# URLs por defecto (cambiar solo si corres en otro puerto)
WHATSAPP_SERVICE_URL=http://localhost:3000
PYTHON_AGENT_URL=http://localhost:8000

# Sandbox: dejar en false hasta que termines la guia base
SANDBOX_ENABLED=false
```

Lista completa de variables en [`configuration.md`](./configuration.md).

### 5. Editar `configs/contactos_agente.json`

Crear el archivo a partir del template:

```bash
cp configs/contactos_agente.example.json configs/contactos_agente.json
```

Editar `configs/contactos_agente.json` con tus contactos reales. El JID es el numero internacional sin `+`, sin espacios, terminado en `@s.whatsapp.net`:

```json
{
  "contacts": [
    {
      "name": "Tu Nombre",
      "jid": "5493874000000@s.whatsapp.net",
      "cargo": "Desarrollador",
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

> [!NOTE]
> El archivo `contactos_agente.json` esta en `.gitignore` (contiene PII). El template `contactos_agente.example.json` si se commitea — no edites el ejemplo.

### 6. Iniciar el `whatsapp-service` (Node + Baileys)

```bash
cd whatsapp-service
node index.js
```

**La primera vez** vas a ver un QR en la terminal. Escanealo desde *WhatsApp > Dispositivos vinculados > Vincular un dispositivo*. La sesion queda persistida en `whatsapp-service/session/` y no tenes que escanear de nuevo.

Cuando termina de conectarse vas a leer:

```
{"phone":"5493874xxxxxxx"} WhatsApp conectado
```

Dejalo corriendo en su terminal.

### 7. Iniciar FastAPI

En **otra terminal** desde la raiz del proyecto, con el venv activo:

```bash
source .venv/bin/activate
uvicorn api:app --reload --port 8000
```

Si todo esta bien, en los logs deberias ver:

```
BD Agent mounted at /agent
```

Si en cambio aparece `BD Agent not started: missing env vars`, revisa que `GEMINI_API_KEY` y `AGENT_DB_URL` esten realmente seteados en `.env` y reinicia.

### 8. Smoke test

Antes de mandar el primer mensaje, corre el smoke test:

```bash
python -m bd_agent.scripts.smoke_test
```

Salida esperada (todos `✓`):

```
=== BD Agent Smoke Test ===

  ✓ env_vars
  ✓ db_ping
  ✓ sqlglot_validator
  ✓ whatsapp_status
  ✓ docker_daemon
  ✓ sandbox_image

All checks passed.
```

Si alguno falla, leete el [troubleshooting](./troubleshooting.md) — cada chequeo del smoke test esta cubierto ahi.

### 9. Probar con un DM

Mandale un WhatsApp **al numero que escaneaste** (no a un grupo). Si tu JID esta en la allowlist y estas dentro de `active_hours`, deberias recibir respuesta en 2-30 segundos (jitter exponencial, configurable solo en codigo).

Pregunta de prueba: `que ventas tenemos hoy?`

Si no responde, revisa los logs de `uvicorn` y el [troubleshooting](./troubleshooting.md).

---

## Proximos pasos

- **Operacion diaria**: [`AGENTS.md`](../../AGENTS.md) seccion *Asistente WhatsApp (BD Agent)* tiene los comandos de hot-reload, metricas, y desactivacion.
- **Configurar todas las opciones**: [`configuration.md`](./configuration.md)
- **Activar el sandbox de reportes Python** (Excel/PDF/PNG generados por LLM): [`README.md`](./README.md) seccion 11 + [`troubleshooting.md`](./troubleshooting.md)
- **Endpoints HTTP**: [`api-reference.md`](./api-reference.md)
- **Algo no anda**: [`troubleshooting.md`](./troubleshooting.md)
