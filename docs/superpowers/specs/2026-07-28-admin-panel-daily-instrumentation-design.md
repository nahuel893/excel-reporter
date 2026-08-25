# Diseño — Completar el panel de administración: instrumentación del daily + 3 pantallas

**Fecha:** 2026-07-28
**Estado:** aprobado por el usuario (diseño), pendiente de plan de implementación
**Alcance:** completar el panel de administración existente en `frontend/`, empezando por instrumentar la corrida diaria para que haya datos reales que observar.

---

## 1. Contexto: el panel ya existe

`frontend/` es una SPA (Vite 5.4 + React 18 + TypeScript strict + Tailwind 3.4 + TanStack Router con basepath `/app` + TanStack Query 5 + rjsf + Monaco), commiteada y limpia, servida por FastAPI desde `frontend/dist` en `/app` (`api.py:176`).

### Estado verificado por ruta (2026-07-28)

| Ruta | Archivo | Tamaño | Estado |
|---|---|---|---|
| layout | `src/routes/__root.tsx` | 5.6K | Implementado |
| `/` | `src/routes/index.tsx` | 13.3K | **Implementado** (Dashboard) |
| `/configs` | `src/routes/configs.tsx` | 6.1K | Implementado |
| `/configs/$filename` | `src/routes/configs.$filename.tsx` | 7.4K | Implementado (editor rjsf + widgets custom) |
| `/contactos` | `src/routes/contactos.tsx` | 6.4K | Implementado |
| `/runs` | `src/routes/runs.tsx` | 1.5K | **Stub** — "Disponible en Fase 3" |
| `/schedule` | `src/routes/schedule.tsx` | 1.5K | **Stub** — "Fase 4" |
| `/artifacts` | `src/routes/artifacts.tsx` | 1.5K | **Stub** — "Fase 5" |

`frontend/CLAUDE.md` está **desactualizado**: declara `index.tsx` como stub de Fase 3, pero el archivo fue reescrito el 18-Jun (13.3K). Corregirlo forma parte del trabajo.

`frontend/src/components/LiveLogStream.tsx` (7.3K) está completo pero **ningún componente lo importa**.

Backend: existen `src/api/routes/mgmt_runs.py` y `mgmt_configs.py`. **No existen** `mgmt_schedule.py` ni `mgmt_artifacts.py`.

---

## 2. Diagnóstico: por qué no hay datos que mostrar

### 2.1 La tabla `runs` no está rota — está contaminada

`data/mgmt.db` tiene 139 filas en `runs`: 75 `interrupted`, 64 `running`, **0 `success`, 0 `error`**.

**Causa raíz** (corroborada por tres refutadores adversariales independientes, 3/3, y verificada directamente):

```
sqlite3 data/mgmt.db "select count(*), sum(case when log_path like '%pytest%' then 1 else 0 end) from runs;"
→ 139|139
ls data/runs/  → vacío
```

`data/runs/` es `_DEFAULT_RUNS_DIR` (`src/api/runner.py:30`). Está vacío: **nunca hubo una sola corrida real del `RunRegistry`**. Las 139 filas son 139/139 artefactos de pytest.

Cadena causal:

1. `tests/api/test_runner.py:18,31,61,87,112` construye `RunRegistry(loop=..., runs_dir=...)` **sin `engine=`**.
2. `RunRegistry.trigger()` (`src/api/runner.py:174`) cae a `_try_get_engine()` (`runner.py:224-229`) → `get_default_engine()` (`src/api/db.py:80-84`), que apunta **incondicionalmente** a `data/mgmt.db`. No hay guard por `PYTEST_CURRENT_TEST` ni `MGMT_DB_URL`, y no existe `conftest.py` bajo `tests/`.
3. Los tests hacen `loop.close()` (líneas 49, 76, 101, 129) sin `await reg.wait_for(run_id)`. El hilo lector después llama `self._loop.call_soon_threadsafe(self._finalize_sync, ...)` (`runner.py:253-256`), **fuera** del `try/except` que solo envuelve el loop de lectura de stdout (`runner.py:238-251`). Resultado: `RuntimeError` no capturado en un daemon thread, y `_finalize_sync` (`runner.py:258-312`, el único código que escribe `success`/`error`) nunca corre.
4. En cada arranque de la API, `recover_interrupted_runs()` (`api.py:81`, `db.py:95-116`) voltea las `running` a `interrupted` en masa.

**Caso de control:** `tests/api/test_runner_subprocess.py` inyecta un engine temporal y hace `run_until_complete(reg.wait_for(...))` — ahí sí obtiene `status='success', exit_code=0`. La lógica de write-back está sana.

### 2.2 `runs` nunca va a servir para el daily

`runs` modela *"un trigger manual de un `configs/*.json` vía subprocess"*. El daily de producción son **18 servicios in-process** disparados por `excel-reporter-daily.timer` → `scripts/run_daily.py`, completamente fuera de FastAPI y del `RunRegistry`.

Aunque se arregle §2.1, la pantalla Ejecuciones seguiría vacía respecto de producción. **Por eso la instrumentación va primero.**

### 2.3 El scheduler de APScheduler es decorativo

- `seed_daily_master_job()` (`src/api/scheduler.py:57`) crea el job `daily-master` con `func=_daily_master_placeholder`.
- `_daily_master_placeholder()` (`scheduler.py:68-74`) hace un `logger.info` y **nada más**.
- `daily_master_job(runner, engine, configs_dir)` (`scheduler.py:77`), que sí dispararía reportes, **nunca se liga al job persistido**.
- Verificado en el pickle de `apscheduler_jobs.job_state`: `func = "src.api.scheduler:_daily_master_placeholder"`, cron `hour=7 minute=0 day_of_week=mon-fri`, TZ Salta.

El disparo real es, y sigue siendo, el timer systemd:

```
excel-reporter-daily.timer  →  OnCalendar=Mon..Sat *-*-* 07:00:00, Persistent=true
excel-reporter-daily.service
  ExecStartPre=-/usr/bin/git -C "…/Informes Badie" checkout main
  ExecStart=/usr/bin/bash -c 'cd "…" && source .venv/bin/activate && exec python scripts/run_daily.py'
```

---

## 3. Decisiones de diseño

### D1 — systemd es el único scheduler; APScheduler no se recablea

La pantalla Programación lee systemd, no lo reemplaza.

**Descartado:** ligar `daily-master` a `daily_master_job`. Crearía un segundo disparador compitiendo con el timer: dos corridas simultáneas de 18 servicios, con picos de 2.4G RSS cada una, en un host con ~2Gi disponibles. Camino directo a OOM.

La pantalla muestra un aviso explícito de que el job `daily-master` de APScheduler es un placeholder, para que el hallazgo no se pierda.

### D2 — Tablas nuevas; `runs` queda intacta

No se extiende `runs`. Extenderla obligaría a migrar `src/api/db.py` y reescribir `mgmt_runs.py`, sin ganar nada: es otro modelo.

Se agregan tres tablas en el mismo `data/mgmt.db`, declaradas en un archivo **nuevo** `src/api/daily_store.py`, con su propio `MetaData` y un `create_all()` idempotente.

### D3 — El estado de un servicio tiene dos ejes, no uno

- `status` — qué pasó con la **generación** del artefacto.
- `delivery_status` + `delivery_gate` — qué pasó con el **envío**, y qué compuerta lo bloqueó.

Un solo campo produciría explosión combinatoria (`success_pero_sin_envio_por_ram`, `success_pero_sin_envio_por_objetivo`, …). Separados, la pantalla puede decir *"se generó, no se envió, porque el objetivo no cargó"* sin inventar estados.

### D4 — Hooks explícitos en `run_daily.py`, no monkeypatch con parseo

**Alternativa descartada:** un recorder que monkeypatchee `_ejecutar_servicio` y detecte las compuertas parseando las líneas de `print()` con emoji (`⏭️`, `📵`, `🚧`, `🧠`).

Motivo del descarte: depende de que nadie cambie un string de log. Se rompe en silencio y la pantalla pasa a mentir sin aviso. Además, el traceback de las excepciones (hoy descartado por completo) seguiría perdiéndose.

**Elegido:** 4 inserciones de una línea en `run_daily.py`, autorizadas por el usuario. Los gates quedan como dato estructurado desde el día uno.

### D5 — v1 sin escritura destructiva

- Programación: **read-only**. Técnicamente el proceso (uid 1000) podría escribir un drop-in en `~/.config/systemd/user/` y hacer `daemon-reload` sin sudo, pero permitir que una SPA sin auth reescriba unidades del init es la mayor superficie de riesgo del panel. Se difiere.
- Archivos: **sin borrado**. Ver §6.3.
- Sí se mantiene lo que ya funciona: disparar una corrida de un config vía `POST /mgmt/runs`, y editar configs/contactos.

### D6 — El historial durable vive bajo `data/`, nunca en journald

Medido: journald no tiene `MaxRetentionSec`, `SystemMaxUse`, `MaxFileSec` ni `Storage` configurados (`/etc/systemd/journald.conf` todo comentado, sin drop-ins). Uso actual 1.6G sobre `/`, que está al 96%. La entrada más vieja de la unidad es del 2026-06-03 → ventana real ~8 semanas, y con `/` al 96% la regla de espacio libre de systemd puede vaciarlo en cualquier momento sin aviso.

Los logs del recorder van a `data/runs/daily/`, que está en `/home` (79%, 10G libres).

---

## 4. Modelo de datos

Archivo nuevo: `src/api/daily_store.py`.

### `daily_runs` — una fila por invocación de `run_daily.py`

| columna | tipo | notas |
|---|---|---|
| `id` | TEXT PK | `YYYYMMDD-HHMMSS-daily` |
| `started_at` / `finished_at` | TEXT ISO | |
| `status` | TEXT | `running \| success \| partial \| error \| interrupted`. `partial` = al menos un servicio falló y el resto corrió (hoy `main()` colapsa esto a exit 1, `run_daily.py:632`) |
| `exit_code` | INT | |
| `triggered_by` | TEXT | `schedule \| manual \| panel` |
| `test_mode` | BOOL | de `_resolve_test_mode` (`main.py:38-40`). Crítico: sin esto no se distingue una corrida real de una de prueba, porque el send-log guarda el destinatario ya colapsado y sin marcar |
| `hoy` | TEXT | fecha lógica resuelta por el daily (≠ `started_at` en corridas retroactivas) |
| `solo_canal` | TEXT NULL | de `--solo-canal` |
| `git_branch`, `git_sha`, `git_dirty` | TEXT/TEXT/BOOL | ver §6.4 |
| `overrides_snapshot` | TEXT JSON | copia de `configs/daily_overrides.json` tal como estaba |
| `host_mem_available_mb` | INT | MemAvailable al arranque, para correlacionar con el RAM guard |
| `log_path` | TEXT | log completo de la corrida |

### `daily_run_services` — una fila por servicio (18 por corrida)

| columna | tipo | notas |
|---|---|---|
| `id` | INTEGER PK | |
| `run_id` | TEXT FK → `daily_runs.id` | indexado |
| `orden` | INT | posición en `SERVICIOS` (`run_daily.py:181-310`); preserva el orden de ejecución en la UI |
| `servicio` | TEXT | `svc.nombre`, el slug canónico |
| `fecha_modo` | TEXT | `hoy \| mes_a_hoy \| mes_completo \| solo_hasta` |
| `fecha_desde`, `fecha_hasta` | TEXT | del `patched["filtros"]`, **capturado en memoria** antes del temp-file (`run_daily.py:537-541`), que se borra en el `finally` de la línea 549 |
| `started_at`, `finished_at`, `duration_ms` | | |
| `status` | TEXT | `skipped \| running \| success \| error \| exception` |
| `exit_code` | INT NULL | |
| `skip_reason` | TEXT NULL | el `razon` del override |
| `delivery_status` | TEXT | `sent \| none_configured \| suppressed \| partial \| test_redirect` |
| `delivery_gate` | TEXT NULL | `override_enviar \| objetivo_no_cargado \| ram_guard_whatsapp \| solo_canal` |
| `delivery_gate_detail` | TEXT NULL | razón textual (p. ej. `MemAvailable=1840MB, umbral 3000`) |
| `error_repr` | TEXT NULL | hoy solo existe como string en una lista (`run_daily.py:627`) |
| `error_traceback` | TEXT NULL | **dato nuevo**: hoy el traceback se descarta entero |
| `log_path` | TEXT NULL | log por servicio |

### `run_artifacts` — una fila por archivo producido

| columna | notas |
|---|---|
| `id`, `service_row_id` FK | |
| `path` | relativo a `data/output/` |
| `kind` | `xlsx \| xlsm \| png \| pptx \| pdf` |
| `size_bytes`, `mtime` | |
| `sent` | BOOL — si entró efectivamente en un `registrar_envio` |

Es lo que conecta la pantalla Archivos con la pantalla Ejecuciones ("qué archivos produjo *esta* corrida"), pregunta que el filesystem por sí solo no puede responder.

### Qué se reutiliza

| Elemento | Decisión |
|---|---|
| `runs` | Se reutiliza sin cambios, para triggers manuales de un config. Se purgan las 139 filas basura. |
| `apscheduler_jobs` | Se conserva, se declara no-autoritativo en la UI. |
| `data/output/_send_log/{fecha}.json` (`src/core/delivery_log.py:14,23-37`) | Se conserva como está, pero **no** es fuente para la pantalla: no tiene `run_id`, su `tipo` viene de `metadata["_tipo"]` (el `tipo` del report-config) y no está garantizado que coincida con `SERVICIOS[].nombre`. Los servicios saltados o con gate nunca aparecen ahí. |

---

## 5. Puntos de enganche en `run_daily.py`

Elegida la opción D4 (hooks explícitos), **no hace falta wrapper externo ni drop-in systemd**: `run_daily.py` importa el recorder directamente y la unidad systemd queda intacta. La superficie de cambio es la siguiente, y es más que "4 líneas" — se declara con precisión para que el plan no la subestime:

| Ubicación | Cambio | Qué captura |
|---|---|---|
| tope del archivo | `from scripts.daily_recorder import recording_run, emit` (1 línea) | — |
| `main()`, alrededor del cuerpo | `with recording_run(...) as rec:` (context manager, indenta el bloque existente) | apertura y cierre de `daily_runs`, incluido el caso de excepción |
| `604` | `emit(...)` antes del `for` | `hoy`, `test_mode`, overrides, git sha/dirty, MemAvailable |
| `506` | `emit(...)` en `_objetivo_gate_bloquea` | gate objetivo — estado interno de `_ejecutar_servicio`, hoy no se devuelve al caller |
| `528` | `emit(...)` en el RAM guard | depende de `MemAvailable` en tiempo real (`run_daily.py:108,452-464`): **no es reconstruible post-hoc** |
| `626` | `emit(..., traceback.format_exc())` en el `except Exception as exc` | único lugar donde existe el traceback |

El `with` reindenta el cuerpo de `main()`. Es el único cambio no trivial y debe hacerse en un commit propio, sin mezclar.

**Contrato de aislamiento:** `emit()` y `recording_run()` **nunca propagan excepciones**. Si la escritura a SQLite falla, se loguea a stderr y la corrida sigue. La instrumentación no puede tumbar el daily de producción — es el requisito no funcional más importante de esta unidad.

### Lo que NO necesita hook

El skip por `ejecutar=false` (`run_daily.py:611-615`) es puramente determinístico: `overrides[nombre].ejecutar is False`, y `SERVICIOS` es un registry estático importable. Se reconstruye desde afuera leyendo `configs/daily_overrides.json` + el módulo.

### Riesgos de wrapping evaluados

- **No hay** `sys.exit`, `os._exit` ni handlers de señal en `run_daily.py` ni en `_run_reportes`. Un `try/finally` global es seguro y siempre corre.
- El temp-config se borra en el `finally` de la línea 549: hay que capturar `patched` en memoria, no leer el archivo.
- No hay logging a archivo en ningún lado. `logging.basicConfig` se llama tarde y solo a stdout (`main.py:487-489`, y de nuevo en 1014 y 1265 — no-ops por la semántica de `basicConfig`). El recorder escribe su propio artefacto; no puede piggybackear.

El recorder vive en un archivo **nuevo** (`scripts/daily_recorder.py`). La unidad systemd, su drop-in `pin-main.conf` y el timer **no se tocan**: como `run_daily.py` importa el recorder, no hace falta cambiar el `ExecStart`.

---

## 6. Las tres pantallas

### 6.1 Ejecuciones (`frontend/src/routes/runs.tsx`)

**Ya existe y no está cableado:**

- `GET /mgmt/runs` (`mgmt_runs.py:104`) soporta `limit/offset/status/config`; `api.runs.list()` y `useRuns()` los aceptan. La UI no los usa.
- `GET /mgmt/runs/{id}` (`mgmt_runs.py:170`), `api.runs.get`, `useRun()` — tipados, hookeados, **nunca llamados**.
- `LiveLogStream.tsx` está completo (SSE mientras corre, fetch del log cuando terminó, auto-scroll, badges). Solo hay que montarlo.
- `GET /mgmt/runs/{id}/log` (`:208`) y `/stream` (`:237`) funcionan.

**Bugs a corregir en el camino:**

- `index.tsx:323-331`: `handleTableSelect` **hardcodea** `setSelectedRunStatus("running")` sin importar el estado real. Línea delatora: `const run = configs; // dummy reference`. Debe resolverse con `useRun(runId)`.
- El 409 de `RunBusyError` (lock por `config_filename`, no global) devuelve `{"detail": ..., "run_id": <activo>}`, pero el frontend solo hace `toast(String(err))`. Falta la UX "ya hay una corrida de este config → abrila".

**Backend nuevo** (`src/api/routes/mgmt_daily.py`, read-only):

- `GET /mgmt/daily-runs` — lista paginada, filtros por fecha/estado
- `GET /mgmt/daily-runs/{id}` — padre + 18 hijos + gates + artefactos
- `GET /mgmt/daily-runs/{id}/services/{orden}/log` — `FileResponse text/plain`, mismo patrón que `mgmt_runs.py:208-229`

**Fuera de alcance en v1:** cancelar un daily en curso. Corre bajo systemd, fuera del `RunRegistry`; requeriría `systemctl --user stop`.

### 6.2 Programación (`frontend/src/routes/schedule.tsx`)

**Backend nuevo** (`src/api/routes/mgmt_schedule.py`, read-only). Verificado sin privilegios, exit 0:

- `GET /mgmt/schedule` → `systemctl --user list-timers -o json` + `show -p NextElapseUSecRealtime -p Persistent` + `cat` de la unit
- `GET /mgmt/schedule/journal?since=&until=` → `journalctl --user -u excel-reporter-daily.service -o json` (medido: 661 líneas para la ventana de 20 min de la última corrida)

La pantalla muestra: próxima corrida, `OnCalendar`, `Persistent`, el contenido de la unit y sus drop-ins, las últimas N líneas del journal, y el aviso sobre el placeholder de APScheduler (D1).

**Diferido:** escritura de `OnCalendar`. Si se implementa, limitada a un único drop-in `override-oncalendar.conf`, con `systemd-analyze calendar <valor>` como validador previo, nunca escritura libre de unidades.

### 6.3 Archivos (`frontend/src/routes/artifacts.tsx`)

**Backend nuevo** (`src/api/routes/mgmt_artifacts.py`, read-only):

- `GET /mgmt/artifacts/tree?slug=&periodo=` → árbol de 3 niveles: servicio → período (`YYYY-MM` o `YYYY-MM-DD`, según `output_paths.service_output_dir`) → archivos, agrupados en **Principal / Imágenes / Backups**
- `GET /mgmt/artifacts/file?path=…` → `FileResponse`. **Validación obligatoria**: `Path(root / path).resolve().is_relative_to(root.resolve())`. Nunca path crudo del cliente.

**Convenciones a parsear:**

- PNG: `{stem_del_xlsx}_{NombreHoja}_{CeldaSupIzq}_{CeldaInfDer}.png` — permite mostrar "hoja X, rango Y" sin metadata extra.
- Backups, dos variantes que conviven: `{stem}_backup.xlsx` sin timestamp (`prepare_accumulative_file`, **se pisa cada corrida**, no es red de seguridad histórica) y `{stem}_backup-YYYYMMDD[-motivo].xlsx` / `.bak.YYYYMMDD-HHMM` (avances, criterio de `_is_backup_name()` en `src/services/avances/service.py`).
- Bucket **"Sin clasificar"**: 81 archivos sueltos en la raíz de `data/output/` (171 MB) + 2 `.xlsm` sueltos en `acciones-comerciales/` (143 MB entre los dos). Se muestran con advertencia.
- Marcar como anómalas, no auto-clasificar: `resumen-mensual/2026-06.contaminated` y `resumen-mensual/historico-2026-01_2026-05-cc`.

**Restricciones duras:**

- **Nada de renderizado on-demand.** El único renderer operativo es LibreOffice headless + `pdftoppm`; `xlsx2html` y `playwright` figuran en `requirements.txt` pero **no están instalados** en el venv. Además el `RangeRecognizer` del sentinel `auto:bordes` tarda 110-125 s solo en cargar el workbook. Un preview por request es inviable y competiría por RAM con el daily.
- Preview inline: **solo PNG ya generados** en disco (150-450 KB c/u). XLSX/XLSM: solo descarga.
- No todos los xlsx tienen PNG: `CaptureImageStep` se auto-omite si ningún canal de entrega consume imágenes.

**Sin borrado en v1.** Lista DO-NOT-DELETE, con motivo:

- `avances/` — `_resolve_base()` (`src/services/avances/service.py`) usa **el output del mes anterior como plantilla base** del mes siguiente, con prioridad sobre `archivo_plantilla`. Borrarlo pierde toda la personalización acumulada. Los `_backup*` están explícitamente excluidos como candidatos de base.
- `champions-league/`, `mision-imposible/` — `prepare_accumulative_file()` acumula hojas sobre el xlsx del período.
- Archivos sueltos en la raíz de `data/output/` — `prepare_accumulative_file` los busca como fuente legacy de migración.
- `~$*.xlsx` — no es basura: es un lock file de Excel. Se señaliza, no se borra.

Cuando se agregue borrado: *soft-delete* a `data/output/_trash/{fecha}/` con restore, lista DO-NOT-DELETE codificada **en el backend** (no en la UI) y doble confirmación.

---

## 7. Riesgos operativos y mitigación

### 7.1 Disco — dos filesystems distintos

```
/dev/sda6  /       49G  45G  2.3G  96%   ← journald (1.6G), sistema
/dev/sda7  /home   49G  37G   10G  79%   ← el repo, data/output (820M), mgmt.db
```

El 96% es `/`. `data/output` vive en `/home`. Mitigación: el recorder escribe bajo `data/runs/daily/` (→ `/home`) y nunca confía en journald como almacén. El panel alerta si `/home` baja de 5G o `/` de 1.5G.

### 7.2 Retención de logs

Sin política, 661 líneas/corrida × 18 servicios × 5-6 días/semana crece indefinidamente. Política desde el día uno: conservar logs por servicio **60 días o 500 MB**, lo que llegue primero; podar al arranque del recorder (barato, sin cron extra). Las filas de `daily_run_services` se conservan siempre (son chicas); solo se podan los `.log` y se marca `log_path = NULL`.

### 7.3 RAM guard vs. renderizado

El guard dispara con `MemAvailable < 3000 MB` (`run_daily.py:108,452-464`) y apaga imágenes de WhatsApp. El daily pica en 2.4G RSS (medido en journal) y el host tiene ~2Gi disponibles.

**Regla dura: el panel no invoca LibreOffice jamás.** Y "disparar corrida desde el panel" debe chequear `MemAvailable` antes y negarse con un mensaje explícito, no encolar a ciegas.

### 7.4 Working tree sucio en `main` + `ExecStartPre=-`

Estado verificado: rama `main`, ~10 archivos modificados sin commitear más 8 rutas sin trackear. El drop-in hace `git checkout main` con prefijo `-` (fallo ignorado).

Dos consecuencias distintas:

- Estando ya en `main`, `checkout main` es un no-op que **no descarta** los cambios locales → el daily corre código no commiteado. Viola el workflow documentado en `CLAUDE.md`.
- Si el tree quedara en una rama feature con conflictos, el `checkout` falla, el `-` lo ignora, y el daily corre la rama feature **en silencio**.

Mitigación en dos partes: (a) commitear o stashear — acción del usuario, no del panel; (b) **el recorder guarda `git_branch`, `git_sha`, `git_dirty` en cada `daily_runs`** y la pantalla Ejecuciones muestra un badge de advertencia en esas corridas. Es la única forma de que esto deje de ser invisible.

### 7.5 Puerto 8000 ocupado

Verificado: `LISTEN 0.0.0.0:8000 users:(("uvicorn",pid=708))`, del proyecto `tv-dlna`. **Bloqueante**: `frontend/vite.config.ts` hardcodea `http://localhost:8000` en 6 lugares (líneas 17, 23, 27, 31, 35, 39). Se elige el puerto **8010** y se parametriza con `process.env.VITE_API_TARGET ?? "http://localhost:8010"`.

---

## 8. Orden de trabajo

Menor riesgo primero. Cada unidad es enviable y verificable sola.

| # | Unidad | Modifica código existente | Verificación |
|---|---|---|---|
| 0 | Puerto 8010 + parametrizar el proxy de Vite | **Sí** — `frontend/vite.config.ts:17,23,27,31,35,39` | `npm run dev` levanta y `curl localhost:8010/health` responde |
| 1 | Purgar `runs`: backup de `data/mgmt.db`, `DELETE FROM runs WHERE log_path LIKE '/tmp/pytest-of-nahuel/%'` | No (solo datos) | `select count(*) from runs` → 0 |
| 2 | Aislar los tests: `engine=` en `tests/api/test_runner.py:18,31,61,87,112` + `wait_for` antes de `loop.close()`; guard anti-pytest en `get_default_engine()` (`db.py:80-84`); `try/except` + log alrededor del `call_soon_threadsafe` (`runner.py:253-256`) | **Sí** — 3 archivos | `pytest -v` verde **y** `select count(*) from runs` sigue en 0 |
| 3 | `src/api/daily_store.py` — las 3 tablas + `create_all()` idempotente | No — archivo nuevo | `.tables` muestra `daily_runs`, `daily_run_services`, `run_artifacts` |
| 4 | `scripts/daily_recorder.py` (nuevo) + enganches en `run_daily.py` (import, `with recording_run(...)` en `main()`, y `emit()` en 604/506/528/626 — ver §5) | **Sí** — `run_daily.py`, incluida una reindentación de `main()` | corrida real: 18 filas hijas incluyendo skips, gates estructurados, logs en `data/runs/daily/`. Y una corrida con el store roto a propósito debe terminar igual (contrato de aislamiento) |
| 5 | `src/api/routes/mgmt_daily.py` (nuevo, read-only) + `include_router` en `api.py` | **Sí** — 1 línea | los 3 endpoints responden 200 con datos de la corrida del día |
| 6 | Pantalla Ejecuciones: tabla paginada + filtros + detalle + `LiveLogStream`; corregir `index.tsx:323-331` y la UX del 409 | **Sí** — `runs.tsx` (stub) e `index.tsx` | `npm test -- --run && npm run lint && npm run build` |
| 7 | `src/api/routes/mgmt_artifacts.py` (nuevo, read-only, con validación de path) + `include_router` | **Sí** — 1 línea | tree y descarga OK; `../../etc/passwd` devuelve 400 |
| 8 | Pantalla Archivos: navegación 3 niveles, preview PNG inline, descarga xlsx, bucket "Sin clasificar", sin borrado | **Sí** — `artifacts.tsx` (stub) | build verde, PNG se ven, xlsx descarga |
| 9 | `src/api/routes/mgmt_schedule.py` (nuevo, read-only) + `include_router` | **Sí** — 1 línea | próxima corrida y últimas N líneas del journal |
| 10 | Pantalla Programación (read-only) + aviso del placeholder de APScheduler | **Sí** — `schedule.tsx` (stub) | build verde |
| 11 | Poda de logs (60 días / 500 MB) al arranque del recorder | No — dentro de `daily_recorder.py` | logs viejos desaparecen, filas de DB persisten |
| 12 | Actualizar `frontend/CLAUDE.md` (está desactualizado, ver §1) | **Sí** — doc | — |

**Diferido, decisión aparte:** escritura de `OnCalendar` vía drop-in + `daemon-reload`; soft-delete de artefactos.

---

## 9. Permisos otorgados por el usuario

Modificación de código existente autorizada para: `frontend/vite.config.ts`, `tests/api/test_runner.py`, `src/api/db.py`, `src/api/runner.py`, las 4 líneas de `scripts/run_daily.py`, las líneas de `include_router` en `api.py`, y los stubs de `frontend/src/routes/`.

No autorizado sin consulta adicional: cualquier otro archivo, borrado de artefactos, escritura de unidades systemd.
