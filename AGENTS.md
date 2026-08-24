# Excel Reporter - Contexto del Proyecto

## Descripcion
Generador automatizado de reportes Excel desde Data Warehouse PostgreSQL (arquitectura Medallion - capa Gold).

## Stack Tecnologico
- Python 3.12+
- SQLAlchemy (conexion BD)
- Pandas (procesamiento)
- OpenPyXL (generacion Excel)
- pywin32 (slicers, solo Windows)
- matplotlib + python-pptx (graficos-cobertura)
- FastAPI (API REST)
- pytest (testing)

## Estructura del Proyecto

```
├── config/
│   └── settings.py          # DB_CONFIG, FERIADOS, COLUMN_NAMES, ZONAS_VIRTUALES, DIAS_SEMANA
├── src/
│   ├── core/                 # Codigo compartido
│   │   ├── data_loader.py    # DataLoader (acceso BD, get_ventas_diarias, get_ventas_diarias_con_ruta)
│   │   ├── excel_writer.py   # ExcelWriter, SheetStyle, ColumnFormat, ColumnGroup, summary_rows, as_table
│   │   ├── excel_slicers.py  # agregar_slicers, slicers_disponibles (solo Windows)
│   │   └── base_processor.py # calcular_dias_habiles, calcular_info_dias, calcular_factor_tendencia
│   ├── api/                  # API REST (FastAPI)
│   │   ├── routes/
│   │   │   ├── ventas.py     # Endpoints de ventas
│   │   │   ├── mgmt_runs.py      # Panel: disparar y seguir corridas
│   │   │   ├── mgmt_configs.py   # Panel: leer/editar los JSON de config
│   │   │   ├── mgmt_artifacts.py # Panel: navegar data/output/ (solo lectura)
│   │   │   ├── mgmt_schedule.py  # Panel: timer/journal de systemd (solo lectura)
│   │   │   └── mgmt_daily.py     # Panel: historial de corridas del daily (solo lectura)
│   │   ├── db.py             # Engine + tabla runs
│   │   ├── daily_store.py    # Tablas daily_runs / daily_run_services / run_artifacts
│   │   └── __init__.py
│   └── services/
│       ├── base_service.py   # BaseService (clase abstracta)
│       ├── ventas/           # Reporte de ventas
│       │   ├── service.py    # VentasService, _aplicar_zonas_virtuales, _expandir_sucursales
│       │   └── processor.py  # procesar_ventas_diarias, formatear_nombre_dia
│       ├── graficos_cobertura/   # Graficos cobertura (matplotlib + pptx)
│       │   ├── config.py     # GraficosCoberturaConfig (fecha_desde/hasta, con_aguas, etc.)
│       │   ├── constants.py  # ZONAS (5), GENERICOS_INCLUIDOS, RUTAS_A_SUC16, COLORES_MARCA
│       │   ├── processor.py  # reassign_rutas_suc1, get_zona_data, build_matrix_*, compute_yoy
│       │   ├── chart_generator.py  # matplotlib Agg + plot_cobertura_zona + plot_comparacion_marca
│       │   ├── excel_builder.py    # build_resumen_xlsx (sheets por generico + mensual + comparativo)
│       │   ├── pptx_builder.py     # build_decks -> Marca.pptx + Generico.pptx
│       │   └── service.py    # GraficosCoberturaService orquesta todo
│       └── avances/          # Reporte de avances (actualiza xlsx in-place)
│           └── service.py    # AvancesService — soporta tipo_plantilla: "branca" | "badie"
│                             # via PLANTILLA_SHEET_CONFIGS registry (ver RF-02)
├── tests/
├── main.py                   # CLI con subcomandos (soporta --config JSON)
├── api.py                    # FastAPI application (v2.0.0) — superficie de PRODUCCION
├── panel.py                  # Entrypoint del admin panel: api.py + routers de administracion
├── config.json               # Config de produccion (fechas, genericos, supervisores)
└── data/output/              # Archivos generados por servicio
    ├── ventas/{YYYY-MM}/     # VentasService (mensual)
    ├── resumen-mensual/{YYYY-MM}/
    ├── champions-league/{YYYY-MM}/
    ├── cartesiano/{YYYY-MM}/
    ├── historico-fratelli/{YYYY-MM}/
    ├── ventas-articulo/{YYYY-MM}/
    ├── stock-diario/{YYYY-MM-DD}/  # StockDiarioService (diario)
    ├── graficos-cobertura/{YYYY-MM}/  # sin timestamp (reemplaza ejecucion anterior)
    └── avances/              # AvancesService no escribe aqui (actualiza in-place)
```

### Estructura de Output

Todos los servicios escriben bajo `data/output/{tipo-servicio}/{periodo}/`:
- **Granularidad mes** (la mayoria): `data/output/{slug}/{YYYY-MM}/`
- **Granularidad dia** (stock-diario): `data/output/stock-diario/{YYYY-MM-DD}/`
- **avances**: excepcion — actualiza el archivo externo in-place (no genera en data/output)
- **Capturas PNG** (CaptureImageStep): se escriben junto al xlsx (sibling directory)
- Implementado en `src/core/output_paths.py` via `service_output_dir(slug, fecha_desde, granularity)`
```

## Setup en Linux

```bash
# Clonar y crear entorno virtual
git clone <repo-url>
cd excel-reporter
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar conexion a BD
cp .env.example .env
# Editar .env con: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
```

## Comandos

```bash
# Activar entorno virtual
source .venv/bin/activate          # Linux/Mac
# .venv\Scripts\activate           # Windows

# Generar reporte con config JSON (metodo preferido)
python main.py ventas --config config.json

# Generar reporte con parametros individuales
python main.py ventas --desde 2026-02-01 --hasta 2026-02-28

# Con filtro de genericos
python main.py ventas --desde 2026-02-01 --hasta 2026-02-28 --genericos "CERVEZAS,AGUAS DANONE"

# Sin slicers (necesario en Linux, donde no hay Excel/pywin32)
python main.py ventas --desde 2026-02-01 --hasta 2026-02-28 --no-slicers

# Graficos Cobertura (XLSX + 2 PPTX + ~50 PNGs)
python main.py graficos-cobertura --config configs/graficos_cobertura.json

# Tests
pytest -v

# Iniciar API (superficie de produccion)
uvicorn api:app --reload --port 8000

# Iniciar el admin panel (produccion + routers de administracion)
uvicorn panel:app --reload --port 8010
```

## Config JSON (config.json)

Metodo preferido para ejecutar reportes. Contiene todos los parametros:

```json
{
    "fecha_desde": "2026-02-01",
    "fecha_hasta": "2026-02-28",
    "genericos": ["CERVEZAS", "AGUAS DANONE", "VINOS CCU", "SIDRAS Y LICORES"],
    "nombre_archivo": null,
    "con_slicers": true,
    "con_cobertura": true,
    "supervisores": {
        "Walter Vilte": ["SUCURSAL CAFAYATE", "SUCURSAL ABRA PAMPA", "CASA CENTRAL"],
        "Antonio Cabrerizo": ["CASA CENTRAL"],
        "Adrian Garcia": ["SUCURSAL CAFAYATE", "SUCURSAL METAN"],
        "Hernan Yapura": ["SUCURSAL ABRA PAMPA", "SUCURSAL PERICO"]
    }
}
```

- `con_slicers`: Poner `false` en Linux (pywin32 no disponible)
- `supervisores`: Genera un archivo por supervisor. Las sucursales van con **descripcion** (no ID)
- Si no se especifica `supervisores`, genera un solo archivo global

## API REST

Documentacion interactiva en:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Endpoints

| Metodo | Endpoint | Descripcion |
|--------|----------|-------------|
| POST | `/ventas/reporte` | Genera reporte y retorna metadata |
| POST | `/ventas/reporte/download` | Genera reporte y lo descarga (xlsx o ZIP si hay supervisores) |
| GET | `/ventas/genericos` | Lista genericos disponibles |
| GET | `/ventas/sucursales` | Lista sucursales disponibles |
| GET | `/health` | Verifica conectividad BD |

### Endpoints del admin panel

Solo existen bajo `panel:app` (puerto 8010), no bajo `api:app`. Ver "Admin Panel".

| Metodo | Endpoint | Descripcion |
|--------|----------|-------------|
| GET | `/mgmt/artifacts/tree` | Arbol servicio -> periodo -> archivos de `data/output/` |
| GET | `/mgmt/artifacts/file` | Sirve un archivo generado (valida que no salga de la raiz) |
| GET | `/mgmt/schedule` | Estado del timer de systemd que corre el daily |
| GET | `/mgmt/schedule/journal` | Entradas del journal de `excel-reporter-daily.service` |
| GET | `/mgmt/daily-runs` | Historial de corridas del daily (paginado, mas nueva primero) |
| GET | `/mgmt/daily-runs/{id}` | Una corrida: servicios (reales + skips reconstruidos) y artefactos |
| GET | `/mgmt/daily-runs/{id}/services/{orden}/log` | Log de un servicio, `text/plain` |

**Los skips se reconstruyen en lectura, no se guardan.** Un servicio que el
daily decidio no correr no escribe fila (decision E5), asi que una respuesta
armada solo con filas mostraria 12 servicios un dia que habia 18 configurados —
y los 6 que faltan son los que mas importan. `GET /mgmt/daily-runs/{id}` cruza
el registro `SERVICIOS` contra el `overrides_snapshot` de la corrida y sintetiza
esas filas con `is_synthetic: true` y `orden: null` (no hay fila, no hay log que
direccionar).

Si el registro no se puede importar, la respuesta trae `skips_reconstructed:
false` y solo las filas reales — nunca una lista corta presentada como completa.
La `razon` del skip es best-effort: el archivo de overrides no es la unica forma
de saltear un servicio, asi que ausencia de razon significa "no quedo
registrada", nunca "sin motivo".

`/mgmt/schedule*` no acepta ningun parametro que elija la unit: `TIMER_UNIT` y
`SERVICE_UNIT` son constantes de modulo en `mgmt_schedule.py`. Todo comando
corre como lista argv explicita con `shell=False` y timeout, asi que lo que
llegue en `?since=` es un argumento literal para `journalctl`, nunca sintaxis
de shell.

### Ejemplo de Request

```bash
curl -X POST "http://localhost:8000/ventas/reporte" \
  -H "Content-Type: application/json" \
  -d '{
    "fecha_desde": "2026-02-01",
    "fecha_hasta": "2026-02-28",
    "genericos": ["CERVEZAS", "AGUAS DANONE"],
    "con_slicers": false,
    "con_cobertura": true,
    "supervisores": {
        "Walter Vilte": ["SUCURSAL CAFAYATE", "CASA CENTRAL"]
    }
  }'
```

## Admin Panel

SPA de administracion (React, `frontend/`) servida en `/app`. Permite ver los
archivos generados, editar los JSON de config y observar las corridas.

### Por que hay dos entrypoints

| Archivo | Que sirve | Quien lo corre |
|---------|-----------|----------------|
| `api.py` | Superficie de produccion: `/ventas/*`, `/health`, agente WhatsApp | systemd, el daily |
| `panel.py` | Todo lo de `api.py` + los routers `/mgmt/*` del panel | a mano, puerto 8010 |

`panel.py` importa la app de `api.py` y le agrega routers; no edita el archivo.
La separacion existe para que el panel no pueda romper lo que sale todos los
dias a las 07:00.

**El aislamiento es por PROCESO, no por objeto app.** `panel.py` muta el mismo
`app` que construye `api.py`. Correr `uvicorn api:app` da un proceso sin estas
rutas; cualquier cosa que importe `panel` las agrega tambien a `api.app` en ese
proceso. Alcanza para el objetivo (produccion nunca importa `panel`), pero no
es un sandbox.

Los routers del panel son de solo lectura (`GET`, sin `DELETE` — RF-17).

Nota historica: `mgmt_runs` y `mgmt_configs` ya estaban montados dentro de
`api.py` de antes; `panel.py` agrega unicamente lo nuevo.

### Seguridad

Las rutas `/mgmt/*` no tienen autenticacion (un solo usuario, red privada).
Bindear a una IP de Tailscale o a loopback, **nunca a `0.0.0.0`**:
`ADMIN_PANEL_ARTIFACTS_ROOT` puede apuntar a cualquier directorio del disco, asi
que un bind publico lo convierte en lectura anonima de todo ese subarbol.

### Levantarlo

```bash
uvicorn panel:app --reload --port 8010
```

El puerto 8000 suele estar ocupado por otro servicio en la maquina de
desarrollo, por eso el panel usa 8010. El proxy de Vite apunta ahi
(`VITE_API_TARGET` lo sobreescribe).

### Variables de entorno

| Variable | Default | Para que sirve |
|----------|---------|----------------|
| `ADMIN_PANEL_ARTIFACTS_ROOT` | `config.settings.DATA_OUTPUT` | Raiz de `data/output/` que lee la pantalla Archivos. Permite revisar el arbol de produccion desde un worktree sin tocar `config/settings.py`. Solo lectura. |
| `VITE_API_TARGET` | `http://localhost:8010` | Backend al que apunta el proxy de Vite en `npm run dev`. |

### Instrumentacion del daily (`scripts/daily_recorder.py`)

Modulo que registra cada corrida del daily en `data/mgmt.db` (tablas de
`src/api/daily_store.py`).

> **Todavia NO esta enganchado.** `scripts/run_daily.py` no lo importa: los
> hooks implican editar el script que systemd corre a las 07:00, y eso es una
> unidad de trabajo aparte. Hasta que entre, nada de esto se ejecuta fuera de
> los tests y `run_artifacts` queda vacia (el descubrimiento de archivos vive
> en el hook `service_done`).

La regla que gobierna todo el diseno: **la
instrumentacion nunca puede ser la razon de que un informe falle.** El
try/except del contrato vive en un solo lugar (`RunRecorder.emit()`), y un
store que no se puede abrir degrada a `NullRecorder` en vez de lanzar. Los call
sites en `run_daily.py` quedan de una linea y sin manejo de error propio.

Lo unico que **no** se traga es la falla del propio daily: una excepcion dentro
de `with recording_run(...)` se re-lanza intacta.

Dos ejes que no se colapsan (RF-04):

| Columna | Que responde |
|---------|--------------|
| `status` | Que le paso a la GENERACION |
| `delivery_status` + `delivery_gate` | Que le paso a la ENTREGA, y que compuerta la bloqueo |

Un avance generado bien y frenado despues por el guard de RAM es un exito
suprimido, no una falla.

**Tres lugares se niegan a adivinar**: un servicio que sigue en `running` al
cerrar (nunca reporto) cierra la corrida en `partial`/`interrupted` en vez de
contarlo como exito; un `service_done` sin exit code deja la fila en `running`;
git que no se pudo leer guarda NULL, no `False`.

#### Retencion de logs

`_prune_logs()` corre al abrir cada corrida. Borra **archivos**, nunca filas: el
resultado de una corrida sirve por meses, su stdout por una semana.

| Umbral | Valor |
|--------|-------|
| Antiguedad | 60 dias |
| Tamano total | 500 MB (borra del mas viejo al mas nuevo) |

**Los logs del daily van en `data/runs/daily/`, no en `data/runs/`.** Ese
directorio es de `src/api/runner.py`, que escribe ahi los logs de las corridas
manuales del panel y guarda la ruta en `runs.log_path`, columna NOT NULL: un
log borrado por debajo deja un puntero que ningun barrido puede reparar.

Y los nombres **no se pueden distinguir**: `runner` arma su id como
`{timestamp}-{slug}` donde el slug sale del campo `tipo` de un config JSON,
editable desde `/mgmt/configs`. Un config con `"tipo": "daily"` produce
exactamente el mismo formato que este modulo. Por eso la separacion es un
directorio y no un patron de nombre.

El barrido de punteros colgados verifica existencia del archivo en vez de
repetir lo que la poda acaba de borrar: un log que se llevo logrotate, tmpfiles
o una persona deja exactamente el mismo puntero roto y merece el mismo arreglo.

## Formato del Reporte de Ventas

Dos hojas por archivo: **Ventas Bultos** y **Ventas HTLs**.

```
Sucursal | Generico | Cant(Gen) | Tend(Gen) | Monto(Gen) | Cob(Gen) | Marca | 01-02 Lunes | ... | Total | Tend(Marca) | Monto(Marca) | Cob(Marca)
```

- **Totales de generico**: Solo aparecen en la primera fila de cada grupo sucursal-generico
- **Cobertura (Generico/Marca)**: Cruce con tablas cob_preventista_generico/marca
- **Columnas de dias**: Formato `dd-mm DiaSemana`, valores 0 si no hay venta, ancho 9.3
- **Tendencia**: `cantidad * (dias_totales_mes / dias_transcurridos_hasta_hoy)`
- **Dias habiles**: Excluyen domingos y feriados (config/settings.py)
- **Nombre archivo**: `Ventas {supervisor} - {dd-mm-yyyy}.xlsx` (fecha = ultima venta real)

## Graficos Cobertura

Servicio separado que genera un paquete visual mensual:
- `data/output/graficos-cobertura/{YYYY-MM}/resumen.xlsx`
- `data/output/graficos-cobertura/{YYYY-MM}/Marca.pptx` (CERVEZAS + AGUAS)
- `data/output/graficos-cobertura/{YYYY-MM}/Generico.pptx` (los 5 genericos)
- `data/output/graficos-cobertura/{YYYY-MM}/png/*.png` (~50 PNGs)

Nota: Ya no usa subdirectorio con timestamp. Cada ejecucion del mismo mes sobreescribe la anterior.

**IMPORTANTE**: Este servicio usa su propio esquema de zonas (5 zonas: NOA NORTE,
SALTA CAPITAL, INTERIOR SALTA SUR, INTERIOR SALTA NORTE, JUJUY INTERIOR) basado
en id_sucursal / id_ruta de tablas `gold.cob_*`. NO usa `ZONAS_VIRTUALES` de
`config/settings.py` (que splitea CASA CENTRAL en `fact_ventas`). Son esquemas
distintos que coexisten.

Tabla opcional: `gold.cob_sucursal_aguas` — si no existe en el ambiente se
loguea WARN y las subdivisiones de AGUAS (SABORIZADAS/MINERAL) se omiten.
Controlable tambien via `con_aguas: false` en el config.

## Zonas Virtuales (CASA CENTRAL / VALLE SALTA)

CASA CENTRAL se divide automaticamente en dos zonas segun `id_ruta` de `fact_ventas`:

```python
# config/settings.py
ZONAS_VIRTUALES = {
    "VALLE SALTA": {
        "sucursal_real": "CASA CENTRAL",
        "rutas": [81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 118, 119, 120, 122],
    }
}
```

- Los supervisores que tienen "CASA CENTRAL" reciben **ambas zonas** automaticamente
- No hace falta poner "VALLE SALTA" en el JSON; se expande solo
- La cobertura tambien se divide por ruta (usa tablas `cob_preventista_*` que tienen `id_ruta`)
- `_aplicar_zonas_virtuales()` renombra sucursal segun ruta y reagrupa
- `_expandir_sucursales()` agrega zonas virtuales a la lista del supervisor

## Sistema de Formatos Excel

```python
SheetStyle(
    numeric_format="#,##0",
    column_formats={
        "Monto (Generico)": ColumnFormat(number_format='$ #,##0'),
        "Cobertura (Generico)": ColumnFormat(number_format='#,##0', width=13),
    },
    column_groups=[ColumnGroup(start_col="01-02 Lunes", end_col="25-02 Miercoles", collapsed=True)],
    summary_rows={"Dias Habiles": 20, "Dias Transcurridos": 15, "Dias Faltantes": 5},
    as_table=True,
    table_style="TableStyleMedium9"
)
```

### Slicers (Segmentadores)

Solo disponibles en Windows con Excel instalado. En Linux se omiten silenciosamente.

```bash
# Con slicers (Windows)
python main.py ventas --config config.json

# Sin slicers (Linux o mas rapido)
# Poner "con_slicers": false en config.json
```

## Patrones de Diseno

- **Service Layer**: VentasService orquesta el flujo
- **Dependency Injection**: DataLoader inyectable para testing
- **Repository Pattern**: DataLoader abstrae acceso a BD
- **Template Method**: BaseService para nuevos reportes

## Agregar Nuevo Reporte

1. Crear `src/services/nuevo_reporte/`
2. Crear `processor.py` con logica especifica
3. Crear `service.py` heredando de `BaseService`
4. Agregar subcomando en `main.py`

## Base de Datos

- **Esquema**: gold (Data Warehouse - capa Gold)
- **Tablas principales**: fact_ventas, dim_articulo, dim_sucursal, dim_vendedor
- **Tablas cobertura**: cob_preventista_generico, cob_preventista_marca, cob_sucursal_generico, cob_sucursal_marca
- **Conexion**: Variables en `.env` (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)

### ⚠️ REGLA DE ORO — clave compuesta (id + id_sucursal)

`id_vendedor` e `id_ruta` **NO son unicos globalmente**: se REUSAN en varias sucursales.
La clave real es **compuesta**: `(id_vendedor, id_sucursal)` y `(id_ruta, id_sucursal)`.

Al joinear un fact con `dim_vendedor` (o cualquier cosa keyed por `id_ruta`) hay que
cruzar por **ambas** columnas, nunca solo por el id:

```sql
JOIN gold.dim_vendedor dv
  ON fv.id_vendedor = dv.id_vendedor
 AND fv.id_sucursal = dv.id_sucursal   -- OBLIGATORIO
```

Joinear solo por `id_vendedor` produce un **fan-out**: la misma venta matchea las filas
de dim de TODAS las sucursales que reusan ese id → duplica ventas y mete nombres/rutas de
otras sucursales en un informe de una sola sucursal. (Ej. real: FULL SPORT sucursal 1 dio
486,5 bultos mal vs 450,5 correcto; dim_vendedor.id_vendedor=100 existe en 5 sucursales.)
Mismo criterio para filtros/joins por `id_ruta`: siempre acotar por `(id_ruta, id_sucursal)`.

### Metodos de DataLoader

- `get_ventas_diarias()`: Ventas agrupadas por fecha (para columnas de dias)
- `get_ventas_diarias_con_ruta()`: Igual pero con `id_ruta` para split de zonas virtuales
- `get_ventas()`: Ventas totales sin desglose diario (compatibilidad)
- `get_sucursales()`: Lista de sucursales (usa `descripcion`, no ID)
- `get_articulos()`: Combinaciones generico-marca
- `get_cobertura_preventista_generico()`: Cobertura por preventista y generico (tiene `id_ruta`)
- `get_cobertura_preventista_marca()`: Cobertura por preventista y marca (tiene `id_ruta`)
- `get_cobertura_sucursal_generico()`: Cobertura agregada por sucursal y generico
- `get_cobertura_sucursal_marca()`: Cobertura agregada por sucursal y marca

## Notas Importantes

- Los imports usan paths completos: `from src.core.data_loader import DataLoader`
- Los tests unitarios usan mocks para aislar la BD (mockean `ExcelWriter`, no `generar_excel`)
- El archivo `.env` no se commitea (esta en .gitignore)
- Sucursales van con **descripcion** (texto), no con ID numerico
- Cobertura se fetchea con try/except: si falla, las columnas quedan en blanco (no rompe el reporte)
- En Linux: poner `con_slicers: false` en config.json (pywin32 no disponible)

## Asistente WhatsApp (BD Agent)

Agente de lenguaje natural que recibe preguntas via WhatsApp y las responde consultando el Data Warehouse. Solo accede al esquema `gold` con permisos de solo lectura.

**Quien puede usarlo**: contactos autorizados en `configs/contactos_agente.json` (JIDs de WhatsApp). El agente ignora silenciosamente cualquier mensaje de un numero no incluido en esa lista.

### Setup inicial

1. **Crear el usuario de BD** — sustituir la password antes de ejecutar:
   ```bash
   psql -h <host> -U <superuser> -d <dbname> -f scripts/sql/agent_user.sql
   # Editar el script primero: reemplazar 'CHANGEME' con una password real
   ```

2. **Obtener API key de Gemini** — gratis en https://aistudio.google.com/app/apikey
   Pegar el valor en `.env` como `GEMINI_API_KEY=<key>`

3. **Configurar contactos autorizados** — editar `configs/contactos_agente.json`
   (NO editar el ejemplo `configs/contactos_agente.example.json`)
   ```json
   {
     "contacts": [
       { "jid": "5493874000000@s.whatsapp.net", "name": "Walter Vilte", "permissions": ["ventas", "cobertura"] }
     ],
     "active_hours": { "start": "08:00", "end": "20:00", "timezone": "America/Argentina/Salta" },
     "rate_limit": { "max_requests_per_day": 50 }
   }
   ```

4. **Reiniciar servicios**:
   ```bash
   # Reiniciar Node (whatsapp-service)
   cd whatsapp-service && node index.js

   # Reiniciar FastAPI (en otro terminal)
   uvicorn api:app --reload --port 8000
   ```

5. **Verificar el flujo completo** — seguir la guia en `whatsapp-service/test-roundtrip.md`

### Arquitectura

```
WhatsApp (usuario)
  -> Baileys (whatsapp-service/index.js)  # recibe DMs, filtra, reenvía
  -> FastAPI POST /agent/message           # bd_agent/transport/router.py
  -> AgentTurn                             # bd_agent/agent.py -- orquesta pipeline
  -> SafetyGuard                           # bd_agent/safety/guard.py -- allowlist + horario + rate-limit
  -> GeminiProvider (Flash Lite)           # bd_agent/llm/gemini.py -- razonamiento
  -> ToolRegistry / PgDatabaseGateway      # bd_agent/tools/ + bd_agent/integrations/database.py
  -> WhatsAppMessagingGateway              # bd_agent/integrations/messaging.py -- responde al usuario
```

Archivos clave:
- `bd_agent/` — paquete Python completo del agente
- `whatsapp-service/index.js` — servicio Node con Baileys
- `configs/contactos_agente.json` — lista de contactos autorizados (gitignored — PII)
- `configs/contactos_agente.example.json` — plantilla versionada

### Operacion

**Deshabilitar el agente** sin cambiar codigo: poner `GEMINI_API_KEY=""` en `.env` y reiniciar.
El `build_agent_runtime()` en `bd_agent/wiring.py` detecta la ausencia de la key y no monta el router `/agent`.

**Recargar contactos sin reiniciar**:
```bash
curl -X POST http://localhost:8000/agent/reload-contacts
```

**Recargar schema doc**:
```bash
curl -X POST http://localhost:8000/agent/reload-schema
```

**Ver metricas en tiempo real**:
```bash
curl http://localhost:8000/agent/metrics
```
Devuelve un JSON con `messages_received`, `messages_sent`, `tool_calls_by_name`, `tokens_in_total`, `tokens_out_total`, `uptime_seconds` y mas.

**Verificar entorno antes de iniciar** (smoke test):
```bash
python -m bd_agent.scripts.smoke_test
```
Verifica env vars, ping a la BD, validador sqlglot, y estado de `whatsapp-service`. Sale con codigo 0 si todo pasa.

**Ver uso de rate-limit**: revisar logs de la aplicacion buscando `event_type: "daily_limit_reached"`. Los logs son JSON estructurado — filtrar por `jid_hash` para seguir a un contacto sin exponer el JID real.

**Saludo diario automatico**: el agente envia un saludo a contactos activos (ultima interaccion < 1h) de lunes a viernes a las 08:00 hora Salta, via APScheduler montado en `api.py`.

### Observabilidad

Cada evento del agente se registra como JSON de una sola linea:
- `inbound_message` — mensaje recibido (con `jid_hash`, `text_len`)
- `tool_call` — herramienta invocada (con `tool_name`, `duration_ms`, `is_error`)
- `outbound_message` — respuesta enviada (con `tokens_in`, `tokens_out`, `duration_ms`)

Los JIDs **nunca** aparecen en los logs: solo el `jid_hash` (SHA-256 de 8 chars) para privacidad.

### Sandbox Python Reports (generacion de archivos)

El agente puede generar reportes Excel, PNG o PDF via la tool `execute_python_report`.
El codigo corre en un container Docker aislado (sin red, solo lectura del filesystem del host).

**Activar**:
1. `bash scripts/build_sandbox_image.sh` — build de la imagen (~5 min primera vez)
2. `SANDBOX_ENABLED=true` en `.env`
3. Reiniciar el servidor FastAPI

Ver seccion "Sandbox Python Reports" en `docs/bd_agent/README.md` para:
- Modelo de seguridad (defense-in-depth)
- Troubleshooting (imagen faltante, daemon caido, timeout)
- Limitaciones (1 archivo de salida, cap 16 MB, sin red)

### Documentacion tecnica

Ver `docs/bd_agent/README.md` para:
- Layout completo del modulo
- Contratos de los Protocolos (DatabaseGateway, MessagingGateway, etc.)
- Flujo de datos completo de un turno
- Capas de seguridad SQL (triple defensa)
- Estrategia de testing + fakes disponibles
- Receta para extraer bd_agent como proyecto independiente
- Sandbox Python Reports (seccion 11)
- Limitaciones conocidas

### Costo estimado

Modelo: `gemini-2.0-flash-lite`
- Input: $0.075 / 1M tokens
- Output: $0.30 / 1M tokens
- Uso tipico por mensaje: ~2.000 tokens in + ~500 tokens out ~= $0.00031 por interaccion
- 50 mensajes/dia por 30 dias ~= $0.47/mes por usuario activo

## Workflow de ramas y deployment (IMPORTANTE)

- **`main` = produccion.** El timer del daily (`excel-reporter-daily.service`) tiene
  un drop-in (`pin-main.conf`) que hace `git checkout main` ANTES de correr, asi que
  produccion siempre ejecuta `main`. NO se corre produccion desde una rama feature.
- **Features en ramas → merge a `main`** cuando estan listas y revisadas. Nunca
  dejar el working tree en una rama feature "porque el daily la levanta".
- **Commitear antes de que algo salga en vivo.** No depender de cambios sin commitear
  en el working tree (se pierden ante cualquier checkout/reset).
- `data/` (outputs) y `resumen-web/node_modules,dist` estan gitignored — no commitear.
- Backups de ramas archivadas: tags `backup/<rama>-<fecha>` (en origin). Para recuperar
  una rama archivada: `git checkout -b <rama> backup/<rama>-<fecha>`.
