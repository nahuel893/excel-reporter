# BD Agent — Architecture Reference

Internal documentation for the WhatsApp BD Agent component. For the quick-start operational guide, see the "Asistente WhatsApp (BD Agent)" section in `AGENTS.md`.

---

## 1. What it does

The BD Agent is a natural-language query interface over the PostgreSQL Data Warehouse (`gold` schema). Users send free-text questions via WhatsApp; the agent translates them into SQL queries using Gemini 2.0 Flash Lite, runs them through a read-only DB connection, and replies with formatted results — all inside the same WhatsApp DM thread.

---

## 2. Module layout

```
bd_agent/                       # Top-level package; zero imports from src.*
  __init__.py
  agent.py                      # AgentTurn: full incoming-message turn pipeline
  contracts.py                  # All Protocols + dataclasses (DatabaseGateway, etc.)
  wiring.py                     # build_agent_runtime() — DI factory; only module that reads env vars
  contacts/
    schema.py                   # Pydantic models: Contact, ContactsFile, SettingsModel
    repo.py                     # JsonContactsRepo: hot-reload, mtime-cached
  conversation/
    history.py                  # InMemoryHistory: per-JID sliding window (10 pairs, 1h timeout)
    system_prompt.py            # build_system_prompt(): renders Gemini system prompt
  integrations/
    database.py                 # PgDatabaseGateway: SQLAlchemy, read-only, 30s timeout, 500 rows cap
    messaging.py                # WhatsAppMessagingGateway: httpx POST /send-text to Baileys
  llm/
    provider.py                 # LLMProvider Protocol + LLMMessage/LLMResponse dataclasses
    gemini.py                   # GeminiProvider: google-genai, Flash Lite, 3x exponential backoff
  observability/
    logger.py                   # BDAgentLogger: JSON formatter, jid_hash only (SHA-256), per-event helpers
    metrics.py                  # MetricsCollector: thread-safe counters, GET /agent/metrics
  safety/
    sqlglot_validator.py        # validate(query): blocks all non-SELECT SQL categories
    rate_limiter.py             # RateLimiter: per-JID daily budget, midnight-Salta reset
    active_hours.py             # ActiveHoursGuard: configurable time window
    allowlist.py                # AllowlistGuard: JID check via ContactsRepo
    guard.py                    # SafetyGuard: aggregates all four, first-denial-wins
  scheduler/
    greeting.py                 # GreetingJob: daily 08:00 Salta cron, skips recent contacts
  scripts/
    smoke_test.py               # Pre-flight checks: env, DB ping, sqlglot, WhatsApp /status
  tools/
    registry.py                 # ToolRegistry: register/invoke/gemini_function_declarations
    curated.py                  # 5 curated tools: get_ventas_cliente, get_clientes_sucursal, etc.
    sql_fallback.py             # run_sql_select: last-resort validated SQL execution

whatsapp-service/               # Node.js Baileys bridge (existing service, extended)
  index.js                      # messages.upsert handler + POST /send-text endpoint
  lib/
    allowlist.js                # AllowlistManager: reads contactos_agente.json, fs.watchFile
    dedup.js                    # MessageDeduplicator: per-JID 60s sliding window

configs/
  contactos_agente.json         # Live contacts file (gitignored — PII)
  contactos_agente.example.json # Committed template

scripts/sql/
  agent_user.sql                # Idempotent Postgres role setup (SELECT-only on gold.*)

docs/bd_agent/
  README.md                     # This file
```

---

## 3. Protocol contracts

All cross-boundary dependencies use Protocols from `bd_agent/contracts.py`. This means the agent core has no knowledge of SQLAlchemy, httpx, or Google AI — only the Protocols it calls.

```
DatabaseGateway
  execute_select(query, params, max_rows) -> list[dict]
  get_schema_doc()                        -> str
  reload_schema_doc()                     -> None   (PgDatabaseGateway extension)

MessagingGateway
  send_text(jid, text) -> None

ContactsRepo
  get(jid)     -> Contact | None
  list_all()   -> list[Contact]
  reload()     -> None

LLMProvider  (bd_agent/llm/provider.py)
  generate(messages, tools, system_prompt) -> LLMResponse

LastActivityStore  (added in scheduler)
  last_seen(jid)      -> datetime | None
  record(jid, when)   -> None
```

---

## 4. Data flow — one message turn

```
1. WhatsApp DM arrives at Baileys (whatsapp-service/index.js)
2. Baileys filters: !fromMe, DM-only (@s.whatsapp.net), text only
3. Allowlist check (Node side) — quick reject before any POST
4. Dedup check (Node side) — same (jid, ts) within 60s ignored
5. POST http://localhost:8000/agent/message {from, text, ts}
6. FastAPI router: dedup again (60s window), BackgroundTask
7. AgentTurn.handle_incoming(jid, text, ts):
     a. AllowlistGuard: JID in contactos_agente.json?
     b. ActiveHoursGuard: within 07:00–22:00 Salta?
     c. RateLimiter: daily_message_limit not exhausted?
     d. InMemoryHistory.append(user message)
     e. build_system_prompt(schema_doc, tool_specs, contact)
     f. LLM loop (max 5 iterations):
          LLMProvider.generate(messages, tools, system_prompt)
          If tool_calls: ToolRegistry.invoke() each → append results → loop
          If text: break
     g. Jitter delay (2–30s exponential)
     h. MessagingGateway.send_text(jid, reply)
     i. InMemoryHistory.append(assistant message)
     j. BDAgentLogger.log_outbound()
```

---

## 5. Security layers

SQL injection is prevented by three independent layers:

1. **sqlglot validator** — `bd_agent/safety/sqlglot_validator.py` blocks any non-SELECT statement before it reaches the DB. Rejects: DDL (CREATE/DROP/ALTER), DML (INSERT/UPDATE/DELETE/MERGE), CTE-with-DML, multi-statement, transactional control (BEGIN/COMMIT/ROLLBACK), CALL/EXECUTE.

2. **Postgres role** — `agent_user` has SELECT-only grants on `gold.*` (see `scripts/sql/agent_user.sql`). Even if a query bypasses layer 1, the DB role blocks writes.

3. **Connection settings** — `PgDatabaseGateway` sets `default_transaction_read_only = on` and `statement_timeout = 30s` at the connection level.

---

## 6. Observability

### Structured logs

Every event is logged as a single-line JSON entry. The `bd_agent.observability.logger` module provides `BDAgentLogger` with three typed helpers:

| Method | `event_type` | Extra fields |
|--------|-------------|--------------|
| `log_inbound(jid, text_len)` | `inbound_message` | `jid_hash`, `text_len` |
| `log_tool_call(jid, tool_name, duration_ms, is_error)` | `tool_call` | `jid_hash`, `tool_name`, `duration_ms`, `is_error` |
| `log_outbound(jid, tokens_in, tokens_out, duration_ms)` | `outbound_message` | `jid_hash`, `tokens_in`, `tokens_out`, `duration_ms` |

**JID privacy**: raw JIDs are NEVER logged. The `jid_hash` field is SHA-256 truncated to 8 hex chars.

### Error log rotation

Errors write to `bd_agent/errors.log` via `RotatingFileHandler` (10 MB per file, 3 backup files). Configure via the standard `logging` config.

### In-memory metrics

`MetricsCollector` (singleton via `get_metrics()`) tracks:

```
messages_received     int
messages_sent         int
tool_calls_by_name    dict[str, int]
errors_by_type        dict[str, int]
errors_total          int
tokens_in_total       int
tokens_out_total      int
uptime_seconds        float
```

Exposed at `GET /agent/metrics`. No authentication — deploy behind internal network only.

---

## 7. Testing approach

All unit tests live under `tests/bd_agent/` mirroring the module tree.

**Fakes** (in `tests/bd_agent/fakes/`):
- `InMemoryDatabaseGateway` — returns canned rows
- `RecordingMessagingGateway` — captures `send_text` calls
- `StaticContactsRepo` — fixed allowlist
- `ScriptedLLMProvider` — scripted response sequence

Integration tests are marked `@pytest.mark.integration` and require:
- `AGENT_TEST_DB_URL` env var (separate test DB)
- Running whatsapp-service stub

Run unit tests only:
```bash
pytest tests/bd_agent -x -q
```

Run with coverage:
```bash
pytest tests/bd_agent --cov=bd_agent --cov-report=term-missing
```

---

## 8. Pre-flight smoke test

Before starting the agent in a new environment:

```bash
python -m bd_agent.scripts.smoke_test
```

Checks:
- `✓` All required env vars set (`AGENT_DB_URL`, `GEMINI_API_KEY`, `WHATSAPP_SERVICE_URL`)
- `✓` DB responds to `SELECT 1` (read-only connection)
- `✓` sqlglot validator rejects DROP, accepts SELECT
- `✓` WhatsApp service `/status` returns `connected`

Exit code 0 = all pass, 1 = one or more failures.

---

## 9. Extracting bd_agent to a standalone project

The agent was designed with extraction in mind (RF-070: zero imports from `src.*`). To move it to its own repo:

1. Copy `bd_agent/`, `tests/bd_agent/`, `configs/contactos_agente.example.json`, `scripts/sql/agent_user.sql`, `CONTEXT_DATABASE.md`.
2. Create a minimal `requirements.txt`: `sqlalchemy`, `psycopg2-binary`, `httpx`, `fastapi`, `uvicorn`, `pydantic`, `google-genai`, `sqlglot`, `apscheduler`.
3. Create a minimal `api.py` that mounts `make_router(...)` from `bd_agent.transport.router`.
4. The only glue code needed is `wiring.py` (already self-contained).
5. No other project files are needed.

---

## 10. Known limitations (v1)

- **In-memory state**: conversation history, rate-limit counters, and last-activity store reset on process restart. A future v2 can use SQLite for persistence.
- **Holiday calendar**: the greeting cron runs Mon–Fri only. Argentine public holidays are NOT excluded. Deferred to v2.
- **No circuit-breaker**: `GeminiProvider` retries 429/5xx up to 3 times with exponential backoff (1s base). No circuit-breaker for sustained Gemini outages.
- **Metrics endpoint**: no authentication. Only expose internally.
- **Greeting history**: `InMemoryLastActivityStore` is separate from `InMemoryHistory`. On restart, the agent may re-greet contacts it already greeted that morning.

---

## 11. Cost reference

Model: `gemini-2.0-flash-lite`
- Input: $0.075 / 1M tokens
- Output: $0.30 / 1M tokens
- Typical per-message: ~2,000 tokens in + ~500 tokens out ≈ $0.00031 per interaction
- 50 messages/day × 30 days ≈ $0.47/month per active user
