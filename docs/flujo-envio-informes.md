# Flujo de envío diario de informes

Documento integral del flujo completo de generación y envío automático de
informes del proyecto excel-reporter. Cubre desde el disparo por systemd hasta
la entrega efectiva por email y WhatsApp.

> Fuente: mapeo del código realizado sobre `scripts/run_daily.py`, `main.py`,
> `src/config/`, `src/delivery/`, `src/services/` y los `configs/*.json`.

---

## 1. Resumen y arquitectura general

El envío diario es un proceso `oneshot` orquestado por systemd. La cadena
completa es:

```
timer systemd (Lun..Sab 07:00 -03)
  -> service oneshot
     -> ExecStartPre: git checkout main   (drop-in pin-main.conf, producción SIEMPRE corre main)
     -> source .venv/bin/activate
     -> python scripts/run_daily.py
        -> REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_resumen_mensual  (no-fatal)
        -> loop sobre 12 servicios registrados (continue-on-fail):
             - parchea fechas según fecha_modo
             - aplica configs/daily_overrides.json (ejecutar / enviar)
             - load_report_config + validate_contacts
             - _run_reportes(report_config, contactos, test_mode)
                  -> por cada reporte: handler genera xlsx/artefactos
                  -> resolve_delivery(): nombres -> direcciones concretas
                  -> DeliveryPipeline([CaptureImageStep, SendEmailStep, SendWhatsAppStep])
                       -> CaptureImageStep: Excel -> PNG (libreoffice / playwright)
                       -> SendEmailStep: EmailSender.send (To + Cc, adjuntos)
                       -> SendWhatsAppStep: WhatsAppClient -> servicio Baileys :3001
                  -> registrar_envio() (delivery_log)
        -> resumen "X/Y OK" + exit code
```

### Piezas clave

- **Entrypoint:** `scripts/run_daily.py` (función `main()`). Orquesta los 12
  servicios registrados en la lista `SERVICIOS`.
- **Dispatch de reportes:** `main.py` con el registry `REPORT_HANDLERS`
  (`tipo` -> nombre de función handler, resuelto en runtime vía
  `globals()[handler_name]`).
- **Resolución de delivery:** `src/config/resolver.py` (`resolve_delivery`,
  `_collapse_enviar_a_for_test`, `load_contacts`).
- **Pipeline de entrega:** `src/delivery/pipeline.py` + `src/delivery/steps/`.
- **Canal WhatsApp:** servicio Baileys externo en la carpeta hermana
  `/home/nahuel/projects/work/whatsapp-service/`, puerto **3001**.

---

## 2. Diagrama de flujo (texto)

```
                       systemd user timer
            (OnCalendar=Mon..Sat *-*-* 07:00:00, Persistent=true)
                                 |
                                 v
                  excel-reporter-daily.service (oneshot)
                                 |
            ExecStartPre=- git -C "<repo>" checkout main   (pin-main.conf)
                                 |
              source .venv/bin/activate && python scripts/run_daily.py
                                 |
              _refresh_mv_resumen_mensual()  (REFRESH MV, errores silenciados)
                                 |
         +-----------------------+------------------------+
         |  loop SERVICIOS (12)  | continue-on-fail        |
         +-----------------------+------------------------+
                                 |
            por servicio: patch fechas -> overrides -> _ejecutar_servicio
                                 |
                          _run_reportes()
                                 |
           +---------------------+---------------------+
           |  handler genera artefactos (xlsx/png/...)  |
           +---------------------+---------------------+
                                 |
                resolve_delivery()  (nombres -> EmailConfig/WhatsAppConfig)
                  [test_mode? -> colapsa todo a "Nahuel Aguirre"]
                                 |
        DeliveryPipeline([CaptureImageStep, SendEmailStep, SendWhatsAppStep])
                  (fallo aislado por paso: un error no frena los demás)
                /                 |                      \
        CaptureImage         SendEmail               SendWhatsApp
        Excel -> PNG     EmailSender.send         WhatsAppClient -> :3001
                                 |
                          registrar_envio()
                                 |
                      resumen "X/Y OK" + exit
```

---

## 3. Tabla maestra de informes

Orden = orden de ejecución en `run_daily.py`. Canales: `email` = To,
`email_cc` = CC, `whatsapp` = WA.

| # | Informe (config) | tipo | handler | config | fecha_modo | Salida | Destinatarios (canal) |
|---|------------------|------|---------|--------|------------|--------|------------------------|
| 1 | stock-diario | stock-diario | `_run_stock_diario_report` | `stock_diario.json` | hoy | 1 xlsx por fecha (hoja "Stock", doble banner BULTOS/HTLs) | 4 reportes por supervisor (ver detalle) |
| 2 | champions-league | champions-league | `_run_mision_report` | `champions_league.json` | mes_a_hoy | xlsx acumulativo (Cob*/Cat*/INFO) | Gonzalo Farah (WA); Nahuel Aguirre (email_cc) |
| 3 | graficos-cobertura | graficos-cobertura | `_run_graficos_cobertura_report` | `graficos_cobertura.json` | mes_a_hoy | resumen.xlsx + 2 PPTX + ~50 PNG | Gonzalo Farah, Sebastian Dellamea, Antonio Cabrerizo (email+WA); Nahuel Aguirre (WA+email_cc) |
| 4 | schneider-710 | ventas-articulo | `_run_ventas_articulo_report` | `schneider710.json` | mes_a_hoy | xlsx 1 hoja, ventas diarias de 1 artículo x 1 sucursal | Gonzalo Farah (email+WA); Nahuel Aguirre (email_cc) |
| 5 | avance-branca | avances | `_run_avances_report` | `avances_branca.json` | mes_a_hoy | xlsx in-place (plantilla branca) | Nahuel Aguirre (WA+email_cc); "Preventa + Vinos Bodega E" (WA) |
| 6 | avance-badie | avances | `_run_avances_report` | `avances_badie.json` | mes_a_hoy | xlsx in-place (plantilla badie) | Sin `enviar_a` (override: ejecuta pero NO envía) |
| 7 | ventas | ventas | `_run_ventas_report` | `ventas.json` | mes_a_hoy | 1 xlsx por supervisor (Ventas Bultos + HTLs + Cobertura) | 4 reportes por supervisor (ver detalle) |
| 8 | resumen-mensual | resumen-mensual | `_run_resumen_report` | `resumen_mensual.json` | mes_a_hoy | xlsx multi-hoja (una por genérico) | Gonzalo Farah, Sebastian Dellamea, Fabian Gallardo (WA+email); Daniel Manzur (WA); Nahuel Aguirre (WA+email_cc) |
| 9 | reporte-rebotes | reporte-rebotes | `_run_rebotes_report` | `rebotes.json` | mes_a_hoy | xlsx 4 hojas (rebotes/rechazos) | Gonzalo Farah, Sebastian Dellamea (WA); Gustavo Flores (WA+email); Veronica Chapur, Facundo Guantay (email) |
| 10 | descuentos | reporte-descuentos | `_run_descuentos_report` | `descuentos.json` | mes_a_hoy | xlsx 2 hojas (normal + lista_precio) | Sebastian Dellamea (WA+email) |
| 11 | incentivo-cobertura | reporte-incentivo-cobertura | `_run_incentivo_cobertura_report` | `incentivo_cobertura.json` | mes_a_hoy | xlsx 1 hoja (incentivo ON PREMISE) | Preventa Salta (WA) — **OFF en daily_overrides (vencido 13/06/2026)** |
| 12 | stock-suria | stock-suria | `_run_stock_suria_report` | `stock_suria.json` | hoy | xlsx 3 hojas (BD SURIA) | Juan Quintana, Fabian Gallardo (email); Nahuel Aguirre (email_cc) |

### Detalle stock-diario (4 reportes)

- **Stock CCU - WV** (Walter Vilte): Walter Vilte, M Bravo, Emiliano Gaston
  Rivera, Diego Martín Aguirre, José Alejandro Teran (email); CC: Sebastian
  Dellamea, Nahuel Aguirre, M Mirse, M Frank, G Teseira.
- **Stock Antonio Cabrerizo**: Antonio Cabrerizo (email); CC: Sebastian
  Dellamea, Nahuel Aguirre.
- **Stock Adrian Garcia**: Adrian Garcia (email); CC: Sebastian Dellamea,
  Nahuel Aguirre, Fabian Gallardo.
- **Stock Hernan Yapura**: Hernan Yapura (email); CC: Sebastian Dellamea,
  Nahuel Aguirre, Fabian Gallardo.

### Detalle ventas (4 reportes por supervisor)

- **Ventas CCU - WV**: Sebastian Dellamea (WA); Walter Vilte (email); Nahuel
  Aguirre (email_cc).
- **Ventas Antonio Cabrerizo**: Gonzalo Farah (WA); Antonio Cabrerizo (email);
  Nahuel Aguirre (email_cc).
- **Ventas Adrian Garcia**: Adrian Garcia (email); Nahuel Aguirre (email_cc).
- **Ventas Hernan Yapura**: Hernan Yapura (email); Nahuel Aguirre (email_cc).

> **Nota:** Nahuel Aguirre aparece como `email_cc` o `whatsapp` en casi todos
> los informes (rol de monitoreo). Hay múltiples configs variantes
> (`*_junio_2026_*`, `*_test`, `*_correccion`) que duplican el informe canónico
> con distintos destinatarios; el canónico es el de nombre base sin sufijo.

### Modos de fecha (`Servicio.patch`)

- **`hoy`**: `fecha_desde = fecha_hasta = today` (snapshots de un día).
- **`mes_a_hoy`**: `fecha_desde = primer día del mes`, `fecha_hasta = today`.
  **Excepción:** si hoy es el primer día hábil del mes
  (`_is_first_business_day_of_month`), envía el **mes anterior cerrado**
  (primer a último día del mes previo). Día hábil = no domingo y no feriado
  (`config/settings.FERIADOS`).
- **`solo_hasta`**: mantiene `fecha_desde` del config y solo parchea
  `fecha_hasta = today`. No usado por ningún servicio actual.

---

## 4. Detalle por servicio

Todos los servicios escriben bajo `data/output/{slug}/{periodo}/`. Granularidad
`month` salvo stock-diario y stock-suria (`day`). `GRANULARITY=month` usa
`{YYYY-MM}`, `day` usa `{YYYY-MM-DD}`.

### ventas (`VentasService`)
- **Salida:** `data/output/ventas/{YYYY-MM}/Ventas {supervisor} - {dd-mm-yyyy}.xlsx`
  (la fecha es la **última fecha con ventas reales**, no `fecha_hasta`).
- **Hojas:** Ventas Bultos, Ventas HTLs, Cobertura Generico, Cobertura Marca, y
  **SUB DISTRIBUIDORES** solo para el supervisor `Adrian Garcia` (siempre solo
  genéricos CCU, ignora el config).
- **Zonas virtuales LOCALES** (`_ZONAS_VIRTUALES_VENTAS`): VALLE SALTA = CASA
  CENTRAL filtrada por rutas `[81..93, 118-122]`, con la ruta 93 (SUB DIST)
  absorbida dentro de VALLE SALTA (difiere del global de settings).
- **BD:** `get_ventas_diarias_con_ruta`, `get_sucursales`, `get_articulos`,
  `get_cobertura_preventista_*`, `get_ventas_historico_mmaa`, `get_cupos`,
  `get_ventas_subdistribuidores_sheet`.
- Un xlsx por supervisor vía `generar_reporte_supervisores` (1 query, filtra por
  sucursales). Factor tendencia = cantidad × (días_hábiles / días_transcurridos).

### resumen-mensual (`ResumenMensualService`)
- **Salida:** `data/output/resumen-mensual/{YYYY-MM}/Resumen - {dd-mm-yyyy}.xlsx`.
  Modo **merge**: si ya existe un xlsx lo mergea; error si hay >1.
- **Hojas:** una por genérico lógico (CERVEZAS, AGUAS DANONE, VINOS CCU, SIDRAS
  Y LICORES) + hojas de Detalle Movimientos importadas (actual/MA/MMAA) +
  `dim_articulo` + `Categorias`.
- **Zonas virtuales GLOBALES** (settings): CASA CENTRAL + VALLE SALTA + SUB
  DISTRIBUIDORES. Segrega DIRECTA SUCURSALES (`id_ruta==100`) **antes** de
  aplicar zonas. 3 subtotales con fórmulas + heatmap en "Tend vs Obj (%)".
- **BD:** `get_ventas_resumen_mensual`, `get_ventas_ultimos_dias_habiles`,
  `get_ventas_mes_anterior`, `get_ventas_mismo_mes_anio_anterior`,
  `get_cupos_resumen_mensual`, `get_dim_articulo`.
- Tiene `generar_datos()` -> dict JSON (vía `serializer.to_datos_json`); el
  frontend React fue reemplazado por Superset.

### ventas-articulo (`VentasArticuloService`)
- **Salida:** `data/output/ventas-articulo/{YYYY-MM}/{articulo} - {Mes} {anio}.xlsx`.
  1 hoja, openpyxl puro. Ventas diarias de UN artículo x UNA sucursal.
- Requiere `id_articulo` e `id_sucursal` obligatorios. Muestra todos los días
  del mes (domingo rosa, con venta azul, sin venta gris) + fila TOTAL.
- **BD:** `get_articulo_descripcion`, `get_ventas_diarias_articulo`.
- En el daily se usa como `schneider-710` (config `schneider710.json`).

### stock-diario (`StockDiarioService`)
- **Salida:** `data/output/stock-diario/{YYYY-MM-DD}/Stock {supervisor} - DD-MM-YYYY.xlsx`.
  Itera día a día; un xlsx por fecha. Si el df queda vacío, WARN y no genera.
- 1 hoja "Stock": doble banner BULTOS (azul `4472C4`) / HTLs (verde `70AD47`),
  4 columnas descriptoras + N sucursales x2. Sucursales dinámicas del df.
- **BD:** principal (override opcional vía `config.db_name`).

### stock-suria (`StockSuriaService`) — caso especial, ver sección 6
- **Salida:** `data/output/stock-suria/{YYYY-MM-DD}/Stock SURIA - DD-MM-YYYY.xlsx`.
  3 hojas: RESUMEN DEL MATCH, Stock SURIA, ARTICULOS SIN MATCH POR CODIGO.
- Apunta a la **BD `medallion_db_suria`** (env `DB_NAME_SURIA`), no la principal.

### graficos-cobertura (`GraficosCoberturaService`) — caso especial, ver sección 6
- **Salida:** `data/output/graficos-cobertura/{YYYY-MM}/` con `resumen.xlsx` +
  2 PPTX + `png/*.png` (~50). Sobreescribe la corrida anterior del mismo mes.
- Esquema PROPIO de 5 zonas (no usa ZONAS_VIRTUALES).

### avances (`AvancesService`) — caso especial, ver sección 6
- Actualiza un xlsx base **in-place** preservando fórmulas. `tipo_plantilla`
  `branca` | `badie` vía `PLANTILLA_SHEET_CONFIGS`.

### Servicios secundarios (no en el daily por subcomando dedicado)

- **champions-league** (`ChampionsLeagueService`): xlsx acumulativo; hojas
  `Cob*`/`Cat*`/`INFO`; preserva hojas manuales; categorías con fórmula CUMPLE.
  Usa ZONAS_VIRTUALES. (handler `_run_mision_report`).
- **descuentos** (`DescuentosService`): "Descuentos CCU"; 2 hojas; excluye
  ENVASES CCU; NO filtra `anulado`; CASA CENTRAL split en VALLE SALTA.
- **rebotes** (`RebotesService`): 4 hojas; semáforo verde<3%/amarillo<5%/rojo≥5%.
- **incentivo-cobertura** (`IncentivoCoberturaService`): incentivo ON PREMISE
  (lista_precio=4) en CASA CENTRAL; targets hardcoded; usa `SUPERVISOR_VENDOR_MAP`.
- **subdistribuidores** (`SubdistribuidoresService`): ventas de ruta 93 fija.
- **historico-cliente**, **historico-fratelli** (ANIOS=[2024,2025,2026]
  hardcoded), **reporte-general-badie** (2 workbooks: normal + EXTENDIDO),
  **cartesiano** (cross-join rutas×genéricos), **cobertura** (multi-período).

> No existe servicio `schneider`: "SCHNEIDER 710" es solo un nombre de
> categoría/tabla. El daily lo corre como `ventas-articulo`.

---

## 5. Pipeline de entrega

### Canales

Definidos en `DeliveryTarget.via` (`src/config/models.py:37`):
`list[Literal["email", "email_cc", "whatsapp"]]`. Un contacto puede declarar
varios. `via` no puede estar vacío (validador `via_not_empty`).

- **`email`** -> destinatario directo (To:)
- **`email_cc`** -> copia (Cc:)
- **`whatsapp`** -> grupo o teléfono individual

### Resolución de contactos (contactos.json)

`ContactInfo` (`models.py:18-31`) es un mapa `nombre -> {email?, telefono?,
whatsapp_grupo?}`. El validador `at_least_one_channel` exige al menos un canal.
`whatsapp_grupo` tiene **prioridad** sobre `telefono` al resolver WhatsApp.

- **Carga:** `load_contacts(path)` (`resolver.py:81-86`). Ruta por defecto:
  `config_path.parent / "contactos.json"` (`main.py:104-105`). Si no existe,
  `contactos = {}` y no rompe.
- **`contactos.json` es PII y está gitignored.** No contiene datos en el repo;
  no incluir emails/teléfonos reales en documentación.
- **Validación de referencias:** `ReportConfig.validate_contacts`
  (`models.py:130-139`) falla si un nombre en `enviar_a` no existe en el catálogo.

`resolve_delivery` (`resolver.py:97-203`) traduce `enviar_a: {nombre:
DeliveryTarget}` al `DeliveryConfig` concreto (EmailConfig + WhatsAppConfig +
capturas). Por cada contacto:
- Si no está en el catálogo -> `logger.warning` y skip (`resolver.py:135-138`).
- `email`/`email_cc` usan `contact.email` (warn si falta).
- `whatsapp`: prioriza `whatsapp_grupo` (`is_group=True`) sobre `telefono`
  (`is_group=False`); warn si no hay ninguno.
- Devuelve `None` si no hay `enviar_a` efectivo ni capturas.
- Los flags `enviar_email` / `enviar_whatsapp` gatean si los canales se resuelven.

### TEST MODE

Chokepoint en `resolver.py:121-124`:

```python
if test_mode and report.enviar_a:
    effective_enviar_a = _collapse_enviar_a_for_test(report.enviar_a, contactos)
```

`_collapse_enviar_a_for_test` (`resolver.py:34-78`) corre **antes** de resolver
direcciones:
1. Toma la **unión de todos los canales** de todos los destinatarios
   (`resolver.py:49-53`).
2. **Promueve `email_cc` -> `email`** (`resolver.py:52-53`) para que el contacto
   de test reciba como To:.
3. Devuelve `None` si la unión queda vacía.
4. Exige que `TEST_CONTACT_NAME = "Nahuel Aguirre"` (`resolver.py:31`) exista en
   el catálogo; si no, `ValueError`.
5. Si `whatsapp` está en los canales pero el contacto de test no tiene teléfono
   ni grupo -> warn y **dropea whatsapp** (`resolver.py:65-71`).
6. Colapsa TODO a `{Nahuel Aguirre: DeliveryTarget(via=...)}`.

Resultado: en test mode ningún contacto real es contactado; todo se redirige a
Nahuel Aguirre y los CC se vuelven To:.

`test_mode` se activa con el flag CLI `--test-mode` o el env
`INFORMES_TEST_MODE=1` (`_resolve_test_mode`, `main.py:38-40`). **No tiene efecto
en flujos legacy** (`_cmd_ventas_legacy` / `_cmd_resumen_legacy`): solo loguea un
warning.

### Pasos del pipeline

Ensamblado en `main.py:394-395`, orden fijo:

```python
DeliveryPipeline([CaptureImageStep(), SendEmailStep(), SendWhatsAppStep()])
```

`DeliveryPipeline.run` (`pipeline.py:136-164`) ejecuta en secuencia con **fallo
aislado**: si un paso lanza excepción, se captura como `StepResult(status="error")`
y los demás siguen. La captura va primero porque email y whatsapp dependen de los
PNG generados.

- **CaptureImageStep** (`steps/capture_image.py`): captura N rangos de hojas
  Excel como PNG vía `excel_renderers.get_renderer` (default `libreoffice`,
  alternativa `html_playwright`). Puebla `artifact.rutas_imagenes` y
  `nombres_hojas`. Estados: `success`/`partial`/`error`/`skipped`.
  `capture_images` (plural) gana sobre `capture_image` (legacy singular).
- **SendEmailStep** (`steps/send_email.py`): `skipped` si `config.email is None`.
  Adjuntos según `config.email.adjuntos` (`"excel"` -> `artifact.ruta_excel`;
  `"imagen"` -> `artifact.rutas_imagenes`). Invoca `EmailSender().send(...)`.
- **SendWhatsAppStep** (`steps/send_whatsapp.py`): `skipped` si
  `config.whatsapp is None`. Por grupo/target envía según `enviar_como`:
  `"imagen"` (PNGs), `"archivo"` (xlsx), `"ambos"`. Usa `WhatsAppClient`. Pasa
  `group_name=grupo` solo si `is_group`.

`EmailSender.send` (`src/core/email_sender.py:30-90`): `To` = destinatarios,
`Cc` = cc, pero `all_recipients = destinatarios + (cc or [])` (línea 72) — el
`sendmail` envía el sobre SMTP a To **y** Cc juntos. SSL (`SMTP_SSL`) o TLS
(`starttls`) según `use_ssl`; config desde `SMTP_CONFIG`.

Tras el pipeline, `main.py:407` llama `registrar_envio(tipo, nombre, archivos,
status)` (`src/core/delivery_log`), usando `metadata["_tipo"]`.

---

## 6. Casos especiales

### stock-suria (BD separada + lista congelada)

- Apunta a la **BD `medallion_db_suria`** (`_build_suria_engine()`, env
  `DB_NAME_SURIA`, reusa `DB_HOST/PORT/USER/PASSWORD`). Es una segunda BD
  medallion separada de la principal.
- **No re-matchea en runtime:** lee la lista congelada
  `configs/stock_suria_articulos.json`. Estado actual: total_activos=187,
  matched=170, sin_match=17, por_esquema={40:141, 400:25, pelado:4}.
- Usa `MAX(date_stock)` de `gold.fact_stock` para la fecha real de stock; el
  `config.fecha` solo determina el output dir y el nombre del archivo.
- Sucursales fijas hardcodeadas: ABRA PAMPA, HUMAHUACA, JUJUY, LA QUIACA,
  MAIMARA, PERICO (zona Jujuy/Quebrada).
- **Re-match:** `scripts/rematch_stock_suria.py`, se corre **cuando el proveedor
  (Coca-Cola) manda un archivo nuevo** de activos
  (`/home/nahuel/VM shared/archivos_diarios/articulos-coca/articulos_coca.xlsx`).
  Genera 3 candidatos de `id_articulo` por código (`40+C`, `400+C`, `C` pelado),
  elige por overlap Jaccard de tokens vs descripción del proveedor (acepta
  overlap>0 o desc con "DUAL"). `verify()` self-check; `--dry-run` no sobreescribe.

### graficos-cobertura (paquete visual + 5 zonas propias)

- Genera `resumen.xlsx` + 2 PPTX (`pptx_builder.build_decks`) + ~50 PNG.
  (Nota: `constants.py` define `PPTX_GENERICO_FILENAME='cobertura_todos.pptx'`;
  CLAUDE.md menciona `Marca.pptx`/`Generico.pptx` — verificar `build_decks` si el
  nombre exacto importa.)
- Esquema **propio de 5 zonas** basado en `id_sucursal`/`id_ruta` de las tablas
  `gold.cob_*`, NO usa `ZONAS_VIRTUALES` de settings:
  - NOA NORTE (todas), SALTA CAPITAL (`[1]`), INTERIOR SALTA SUR (`[3,4,5,16]`),
    INTERIOR SALTA NORTE (`[6,7]`), JUJUY INTERIOR (`[9-15]`).
- Genéricos: CERVEZAS, AGUAS SABORIZADAS, AGUAS MINERAL, SIDRAS Y LICORES,
  VINOS CCU. AGUAS se subdivide y se omite si `con_aguas=false` (tabla opcional
  `gold.cob_sucursal_aguas`). Rutas `[85,86,87,88,118,119]` de suc 1 reasignadas
  a suc 16.

### avances (actualización in-place, branca | badie)

- Actualiza un workbook base **in-place** preservando fórmulas y hojas que el
  usuario agrega (`replace_sheet_data` de `src/core/excel_updater.py`).
- **Resolución de base** (`_resolve_base`, primer match gana): 1) output del mes
  anterior (arrastra customizaciones, filtra por prefijo antes del " - " para no
  mezclar Branca vs Badie); 2) `archivo_plantilla` del config. Si no hay ninguno
  -> `FileNotFoundError`.
- **Dos plantillas** vía `PLANTILLA_SHEET_CONFIGS`, `tipo_plantilla` (default
  branca):
  - **branca**: hojas `gold fact_ventas`, `gold dim_articulo`, `gold dim_cliente`,
    `gold cob_preventista_generico/marca`.
  - **badie**: hojas `pivot_python`, `cober_gen`, `cober_marca`, `CuposVolumen`,
    `CuposCoberGen`, `CuposCober`.
- Gotcha: nombres de columna de cupos con **espacio final** intencional
  (`"Cupo "`, `"CUPO "`) para matchear el header Excel exacto.

---

## 7. Canal WhatsApp

El canal tiene dos piezas en carpetas distintas:

1. **`/home/nahuel/projects/work/whatsapp-service/`** (carpeta HERMANA, no la del
   proyecto) — servicio Baileys que efectivamente corre. Puerto **3001**. API
   HTTP pura (Express) en `lib/api.js`: **sin lógica de agente, sin allowlist,
   sin dedup**. Toda la inteligencia/seguridad vive en `bd_agent`.
2. **`Informes Badie/bd_agent/integrations/messaging.py`** — cliente Python que
   consume el servicio.

### Endpoints del servicio Baileys

Todos los envíos pasan por `requireSession` (HTTP **503** `session_not_ready`
si WhatsApp no está autenticado), se **encolan** (`messageQueue.enqueue`,
respuesta con `job_id`), y hay un warmup tras la conexión. `resolveJid` acepta
`to` (preferido) o `group_name` (compat).

| Método | Ruta | Body | Qué hace |
|--------|------|------|----------|
| GET | `/status` | — | `getStatus()` (incluye `connected`) |
| GET | `/queue/status` | — | estado de la cola |
| GET | `/groups` | — | lista grupos `{id, subject, size}` |
| POST | `/send-text` | JSON `{to, text}` | texto plano, **solo DMs** (`to` debe terminar en `@s.whatsapp.net`, rechaza grupos con 400) |
| POST | `/send-image` | multipart `to`/`group_name`, `caption`, `image` | **FOTO con preview** (default `image/png`) |
| POST | `/send-file` | multipart `to`/`group_name`, `caption`, `file` | **DOCUMENTO** (default mimetype xlsx) |
| POST | `/send-file-dm` | multipart `to`, `caption`, `file` | **alias de `/send-file`** por compat con bd_agent |

Diferencia clave: `/send-image` envía imagen con preview embebido; `/send-file`
y `/send-file-dm` envían como adjunto-documento.

### Cómo lo usa el proyecto

`WhatsAppMessagingGateway` (`bd_agent/integrations/messaging.py`) usa **solo dos
endpoints**: `/send-text` y `/send-file-dm` (no usa `/send-image` ni
`/send-file`). `base_url` típico `http://localhost:3001`, `httpx.Client`
inyectable (timeout 30s), zero imports de `src.*`. Si la respuesta no es 2xx
lanza `RuntimeError`.

`SendWhatsAppStep` del pipeline de informes despacha el reporte generado por este
canal (xlsx como documento DM y/o texto). Para enviar imágenes con preview se
usaría `/send-image`, pero el `WhatsAppMessagingGateway` actual entrega como
documento DM.

### bd_agent (asistente NL, separado del envío de informes)

Agente de lenguaje natural que responde preguntas por WhatsApp consultando el DW
(esquema `gold`, solo lectura). Allowlist en `configs/contactos_agente.json`
(PII, gitignored); contactos no autorizados se ignoran silenciosamente. Flujo:
Baileys -> FastAPI `POST /agent/message` -> `AgentTurn` -> `SafetyGuard`
(allowlist + horario + rate-limit) -> Gemini flash-lite -> `ToolRegistry` /
`PgDatabaseGateway` -> respuesta. Se deshabilita con `GEMINI_API_KEY=""`.

---

## 8. Operación

### Correr el daily manualmente

```bash
cd "/home/nahuel/projects/work/Informes Badie"
source .venv/bin/activate
python scripts/run_daily.py
```

Flags útiles de `run_daily.py`:
- `--date YYYY-MM-DD` — override de "hoy" (testing).
- `--dry-run` — imprime las fechas parcheadas sin ejecutar.
- `--only SERVICIO...` — corre un subconjunto por nombre.
- `--test-mode` — redirige TODA la entrega a Nahuel Aguirre.
- `--solo-canal {whatsapp,email}` — filtra cada `enviar_a` a un solo canal.

### Test mode (un solo informe)

```bash
# Vía run_daily (todo el daily en modo test)
python scripts/run_daily.py --test-mode --only ventas

# Vía main.py con un config concreto
python main.py --test-mode --config configs/ventas.json
# o con env var
INFORMES_TEST_MODE=1 python main.py --config configs/ventas.json
```

`--config` y `--config-dir` son opciones **globales** de `main.py`: si se pasan,
`main()` llama directo a `_run_report_config`/`_run_config_dir` sin pasar por los
subcomandos. Recordar que test mode no afecta los flujos legacy.

### Verificar envíos

```bash
python main.py check-delivery   # imprime el resumen del delivery_log
```

### Schedule (systemd user units)

- **Timer** `~/.config/systemd/user/excel-reporter-daily.timer`:
  `OnCalendar=Mon..Sat *-*-* 07:00:00` (Lun a Sáb 07:00, **no domingo**),
  `Persistent=true` (catch-up si la máquina estaba apagada), timezone local
  (Salta, -03).
- **Service** `excel-reporter-daily.service`: `Type=oneshot`, `cd` al repo +
  `source .venv` + `python scripts/run_daily.py`, salida al journal.
- **Drop-in** `...service.d/pin-main.conf`:
  `ExecStartPre=-/usr/bin/git -C "<repo>" checkout main`. Producción SIEMPRE
  corre `main`; el prefijo `-` evita abortar el servicio si el checkout falla
  (ej. working tree sucio).

```bash
# Ver estado / logs
systemctl --user status excel-reporter-daily.timer
journalctl --user -u excel-reporter-daily.service -n 100
```

### Gotchas conocidos

- **Refresh de MV remoto:** antes de los reportes, `run_daily` ejecuta
  `REFRESH MATERIALIZED VIEW CONCURRENTLY gold.mv_resumen_mensual`. Los errores
  se loguean y **silencian** (no-fatal): un MV stale es aceptable, crashear el
  daily no.
- **Continue-on-fail:** cada servicio va en try/except; un exit != 0 o excepción
  se agrega a la lista `errores` y se sigue con el próximo. El resumen final es
  `Todos los servicios OK (N/N)` (exit 0) o `Completado con errores: [...]`
  (exit 1). El N/N siempre muestra el total corrido, no descuenta fallidos.
- **Overrides:** `configs/daily_overrides.json` por servicio: `ejecutar`
  (default true; false = skip total) / `enviar` (default true; false = genera sin
  entregar, `_strip_delivery` limpia `enviar_a`) / `razon`. Actualmente:
  `incentivo-cobertura` OFF (vencido 13/06/2026); `avance-badie` ejecuta pero NO
  envía (pendiente verificar primer output).
- **No redondear datos** (PRIMARY RULE del proyecto): nunca `int()`/`round()`/
  `astype(int)`; formatear solo vía Excel `number_format`. Atención:
  `stock_diario.processor` usa `int()` sobre `cant_bultos`/`cant_htls` (stock es
  entero por naturaleza, pero revisar si se reusa).
- **No sobreescribir archivos del usuario** sin confirmación explícita
  (xlsx/pdf/plantillas pueden tener ediciones manuales no commiteadas).
- **`historico-fratelli`:** `ANIOS = [2024, 2025, 2026]` hardcoded — extender en
  años futuros.
```
