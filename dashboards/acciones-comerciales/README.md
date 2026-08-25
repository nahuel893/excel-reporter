# Acciones Comerciales — Dashboard

Tablero ejecutivo standalone del reporte **Acciones Comerciales** (BADIE S.A.).
Single-file HTML, zero build, sin servidores, sin CDNs obligatorios.

![dashboard hero](docs/screenshot.png)
_(screenshot del primer viewport)_

---

## TL;DR

```bash
python build_dashboard.py
open dashboard.html        # macOS
xdg-open dashboard.html    # Linux
```

Eso es todo. Un archivo HTML, autocontenido, pesa ~50 KB.

---

## Qué hace

Lee el BASE control xlsx generado por el servicio de `acciones-comerciales`
(`data/output/acciones-comerciales/{YYYY-MM}/BASE control ... xlsx`) y produce
un dashboard editorial con los KPIs más importantes del mes:

| Sección | Qué muestra |
|---|---|
| **Hero KPIs** | Facturación Neta · Descuentos · Ratio D/F · Universo (acciones · clientes · artículos) |
| **Estrategia CCU** | Split CCU vs No-CCU con facturación, descuentos, ratio y participación |
| **Pulse diario** | Time series dual: facturación + descuentos por día (con marcadores de fin de semana) |
| **Mix por genérico** | Barras horizontales · top 14 con share y badge CCU |
| **Top acciones** | Barras horizontales · las 12 acciones que más descuento entregaron |
| **Mix por sucursal** | Barras verticales · 13 puntos de venta con mini-indicador de ratio |
| **Ratios D/F** | Lollipop chart por genérico con línea de referencia del ratio global |
| **Top clientes** | Tabla con los 25 clientes que más descuento recibieron |

KPIs destacados que el tablero expone:

- **Facturación Neta total** del período
- **Descuentos otorgados** (suma de Campo1 / Descuentos de la hoja FACT_NET)
- **Ratio Descuento / Facturación** (presión promocional — sustainability indicator)
- **Mix CCU vs No-CCU** (los 5 genéricos CCU: CERVEZAS, AGUAS DANONE, VINOS CCU, SIDRAS Y LICORES, PERNOD RICARD)
- **Concentración de descuentos** en top acciones / top clientes / top sucursales
- **Pulse diario** (detecta anomalías, fines de semana, etc.)

---

## Estructura

```
dashboards/acciones-comerciales/
├── build_dashboard.py        # extractor + generador de HTML
├── dashboard.html            # output: un solo archivo, abrís esto
├── data/
│   └── dashboard.json        # opcional — datos extraídos (si querés consumirlos aparte)
├── package.sh                # empaqueta todo en un zip portable
└── README.md
```

---

## Uso

### 1. Regenerar el dashboard

```bash
python build_dashboard.py
```

Lee el BASE canónico (`data/output/acciones-comerciales/2026-07/BASE control ...xlsx`)
y sobrescribe `dashboard.html`. Tarda ~30s (la hoja `wapi` tiene 55k filas — se
stream-ea, no se materializa).

Para otro BASE:

```bash
python build_dashboard.py /path/al/BASE.xlsx /path/al/output.html
```

### 2. Empaquetar para compartir

```bash
bash package.sh
```

Crea `acciones-comerciales-dashboard-{YYYY-MM-DD}.zip` con `dashboard.html` +
este README + screenshot. Listo para mandar por mail.

### 3. Modo offline (sin Google Fonts)

Por defecto el HTML carga Fraunces / Manrope / JetBrains Mono desde Google Fonts.
Si necesitás que funcione offline (red aislada, demo en campo), el navegador
cae a los fallbacks del system stack (Hoefler Text / Georgia / ui-monospace)
— sigue funcionando, solo cambia la tipografía.

Para 100% offline-con-tipografías-correctas, embebé las WOFF2 en el HTML
(modificar el `<link>` por data: URIs). Por ahora el default asume internet.

---

## Decisiones técnicas

- **Single-file HTML**: nada de npm, nada de bundlers, nada de servers.
- **SVG charts hand-crafted**: cero Chart.js / D3, cero CDN. Los charts son
  funciones JS que dibujan paths/rects/circles inline.
- **JSON embebido** en `<script type="application/json">`: el HTML es realmente
  un solo archivo que podés mandar por mail o subir a Drive.
- **Estilo editorial argentino**: cream paper (#f4efe4) + tinta (#1a1612) +
  rojo Badie (#b8351c) + teal CCU (#2c4a52). Display en Fraunces variable
  (con opsz/SOFT/WONK para dar carácter). Números en JetBrains Mono.
- **Animación de reveal staggered** en la carga (CSS only).
- **Responsive**: el grid colapsa de 4 cols → 2 → 1 abajo de 1100/640 px.
- **Streamed load**: las hojas `wapi` (55k filas) y `cliente_fecha` (51k
  filas) se iteran una sola vez para computar aggregates, sin construir
  listas de dicts en memoria. Corre en ~30s en lugar de los 90s+ del
  primer intento (que se colgaba cargando todo en listas).

---

## Cómo extender

Agregar un KPI nuevo:

1. Computar el aggregate en `build_payload()` (Python).
2. Agregar el slot en el template HTML (`__JSON_DATA__` ya está disponible).
3. Renderizarlo en la sección JS correspondiente.

Cambiar la estética:

1. Modificar las CSS variables en `:root` (paleta, fonts).
2. Los charts SVG usan los mismos tokens (`--ink`, `--badie`, `--teal`, etc.).

Agregar filtros (ej. por sucursal o genérico):

1. Exponer `DATA` globalmente desde el IIFE actual.
2. Filtrar `DATA.mix_generico`, `DATA.mix_sucursal`, `DATA.top_acciones`,
   `DATA.top_clientes` antes de pasar a las funciones de render.
3. Re-renderizar charts al cambiar filtro.

---

## Cron / automatización

Para actualizar el dashboard cada vez que se regenera el BASE:

```bash
# crontab entry — corre diariamente después del ETL
30 6 * * * cd /home/nahuel/projects/work/Informes\ Badie && python dashboards/acciones-comerciales/build_dashboard.py
```

El HTML siempre va a quedar en el mismo path, así que cualquier consumer
(bookmark, link en Confluence, link en mail) lo va a encontrar actualizado.

---

## Notas de dominio

Los 5 genéricos CCU que el reporte reconoce están hardcoded en
`build_dashboard.py::CCU_GENERICOS` y reflejados en
`~/.claude/CLAUDE.md` y `memory/domain_genericos_ccu.md`:

```
CERVEZAS · AGUAS DANONE · VINOS CCU · SIDRAS Y LICORES · PERNOD RICARD
```

Cualquier otro genérico (FRATELLI B, VINOS, GASEOSAS, ENERGIZANTES, JUGOS,
ENVASES CCU, TAMBO, BOUTIQUE, VINOS FINOS) cae en el segmento **No CCU**.

---

## Licencia

Interno BADIE S.A.
