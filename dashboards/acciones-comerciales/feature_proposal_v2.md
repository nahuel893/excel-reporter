# Acciones Comerciales — Feature Proposal v2

**Fecha**: 2026-07-25
**Trigger**: Re-análisis post-implementación con skills `pandas-pro` y `data-visualization` (recién instaladas).
**Output actual**: `dashboards/acciones-comerciales/dashboard.html` v1 (49 KB single-file).

## TL;DR

v1 cubre lo obvio (hero KPIs, mix, top-N). El EDA profundo con pandas-pro reveló **insights que v1 NO expone** y la auditoría con data-visualization encontró **2 antipatterns reales** (dual-axis chart, target sin bullet chart). Esta propuesta lista 12 features priorizadas (P0/P1/P2) para v2.

---

## Hallazgos del EDA (pandas-pro)

Datos del período `2026-07-01 → 2026-07-21` (21 días cerrados):

### Insights estructurales

| # | Hallazgo | Implicancia |
|---|---|---|
| H1 | **HHI = 0.0026** (diversificado). Top 20 clientes = 14.4% del descuento; top 100 = 26.6%; mitad del descuento va a 597 clientes. | La promo está bien atomizada — no hay un "ballena" que rompería el análisis. |
| H2 | **51% de las (sucursal × artículo) NO tienen descuento** (928/1812). Solo 876 reciben promo. | Hay margen claro para **expandir cobertura de artículos**. |
| H3 | **Solo 7 filas con descuento negativo** (devoluciones) — 0.39%. | El "ajuste por devoluciones" no es relevante al agregado. |
| H4 | **Viernes concentra 24.5% del descuento**, sábado 21.6%, lunes 19.5%. Jueves el día más flojo (8.3%). | Patrón semanal fuerte — útil para planificar inventario/cobertura. |
| H5 | **Volatilidad diaria CV = 0.746** (alta). Día pico: 2026-07-18 = $60M; día valle: 2026-07-09 = $585k. | El 9 de julio cayó al mínimo absoluto — feriado Día de la Independencia. **El dashboard no marca feriados**. |
| H6 | **Tipo "SIN CARGO" tiene ratio D/F = 28.81%** vs "Descuentos" = 10.48%. | Las promos "sin cargo" (bonificación) son **3× más concentradas en margen** que las promos con % descuento. **Insight crítico que v1 NO muestra.** |
| H7 | **38% de las filas wapi no tienen ZONA** (21,173/55,202). | Faltan datos de zona — debería salir como banner de calidad de datos. |
| H8 | **Solo 3 zonas tienen datos** (Antonio Cabrerizo, Adrian Garcia, Hernan Yapura). El resto son null. | Cobertura de zonas incompleta — no podemos hacer análisis por zona hasta cerrar ETL. |
| H9 | **Comprobantes duplicados = 43%**. Normal (1 comprobante = N líneas). | No es bug — pero debería documentarse para no asustar. |
| H10 | **Acciones top hiperconcentradas**: `P2772` YAPURA SCH 710 MUNDIAL 20% = $57.7M en **1 solo artículo** repartido en 8 sucursales. `P2773` similar ($31.5M / 1 art / 4 suc). | Estas son **promos "mundial" del Mundial de Clubes 2026**. **Tienen que tener su propia callout** — no son una acción más. |
| H11 | **CCU ratio D/F promedio = 14.51% vs No-CCU 12.82%**. CCU está más presionado. | Ya está en v1, pero falta el **ranking interno CCU** (cuáles 5 presionan más). |
| H12 | **Sucursales más presionadas** (vs global 10.36%): METAN +4.29pp, JOAQUIN V GONZALEZ +2.09pp, MAIMARA +1.16pp, PERICO +1.03pp, LIBERTADOR +0.85pp. **Más disciplinadas**: GUEMES -3.92pp, ORAN -2.85pp, CAFAYATE -2.59pp. | Esto es lo que un supervisor necesita ver: **"mi sucursal vs la red"**. v1 muestra la sucursal pero no la desvío. |
| H13 | **BOUTIQUE ratio D/F = 79.4%** — outlier extremo. SIDRAS Y LICORES 26.5%. AGUAS DANONE 20.2%. | BOUTIQUE probablemente muestra chica (volumen $2M, descuento $1.7M). Hay que **marcar outliers** para no distorsionar la vista general. |
| H14 | **Día 9 de julio = -97.12% DoD**, día 21 = -80.76% (último día parcial). | El DoD% sin contexto engaña — necesitaría marcar "día parcial" o "feriado". |

---

## Auditoría de chart-types (data-visualization)

| Sección v1 | Chart actual | Veredicto | Acción recomendada |
|---|---|---|---|
| Pulse diario | Line chart con **dual y-axis** (fact + descuentos) | ⚠️ **Antipatrón**: la skill avisa "Dual-axis charts pueden engañar al implicar correlación" | Reemplazar por **small multiples** (2 paneles apilados, mismo eje X) |
| Mix por genérico | Horizontal bars | ✅ Correcto | Mantener. Agregar share % (ya está). |
| Top acciones | Horizontal bars | ✅ Correcto | **P0**: Color por "single-art" vs "broad" — las mega-promos del Mundial son visualmente distintas. |
| Mix por sucursal | Vertical bars | ✅ Correcto, pero pierde el desvío vs global | **P0**: Bullet chart — cada barra muestra fact + posición del ratio sobre el target (global 10.36%). |
| Ratios D/F | Lollipop | ✅ Correcto para ranking | **P1**: Bullet chart con zonas de color (verde si <8%, amarillo 8-12%, rojo >12%) en lugar de solo línea de referencia. |
| Top clientes | Tabla | ✅ Tabla es correcta para muchos campos | Mantener. |

### Antipatterns detectados en v1

1. **Dual-axis chart** (Pulse diario) — la skill lo marca explícitamente como "use cautiously, can mislead".
2. **Target sin bullet chart** — la Sucursal vs global es literal un caso de "performance vs. target". Estoy usando bars simples.
3. **Title describe el dato, no el insight** — "Mix por genérico" en vez de "CERVEZAS domina 66% del descuento".

---

## Features propuestas (priorizadas)

### 🔴 P0 — crítico, alto impacto

#### F1. Bullet chart de sucursales (vs global ratio)
- Reemplaza la sección "Mix por sucursal".
- Cada barra = facturación de la sucursal + posición del ratio sobre el target (global 10.36%).
- Verde si <8%, amarillo 8-12%, rojo >12%.
- Responde: *"¿Dónde está mi sucursal vs la red?"*

#### F2. Callout de "mega-acciones" (Schneider 710 Mundial)
- Slot dedicado arriba del Top Acciones.
- Cualquier acción con `desc_per_art > $5M` (concentración un-art-muchos-suc) se separa del top regular.
- Etiqueta visible: tipo "EVENTO MUNDIAL" con icono de pelota o similar.

#### F3. Split de tipo de descuento (SIN CARGO vs Descuentos)
- Mini-comparativa con los dos tipos.
- Hace explícito el insight H6: SIN CARGO = 28.81% D/F vs Descuentos = 10.48%.
- Posicionado cerca del hero, donde un manager comercial lo ve primero.

#### F4. Small multiples para Pulse diario (en lugar de dual-axis)
- Reemplaza el chart actual.
- Dos paneles apilados:
  - Panel A: Facturación diaria (area chart sutil + línea)
  - Panel B: Descuentos diarios (bar chart)
- Mismo eje X compartido, mismo width, sin dual-y.
- Marca feriados/fin-de-año con banda gris.

### 🟡 P1 — útil, agrega profundidad

#### F5. Ranking interno CCU
- Sección propia con los 5 genéricos CCU ordenados por ratio D/F.
- Hoy están mezclados con los No-CCU en el chart de Ratios.
- Formato: tabla + mini-barras. Responde: *"De los CCU, ¿cuáles están más presionados?"*

#### F6. Heatmap sucursal × genérico (top 6×6)
- Pivot de descuentos.
- Celdas con color secuencial (claro a oscuro).
- Inmediatamente identificable: ¿dónde se cruza promo con producto?
- 6×6 mantiene legibilidad (no 13×14 que sería ruido).

#### F7. Day-of-week patrón
- Bar chart de descuentos por día de la semana (Lun-Dom).
- Color weekend más tenue.
- Responde: *"¿Cuándo conviene lanzar promo?"*

#### F8. Pareto de clientes (HHI visual)
- Bar chart con línea cumulativa encima.
- Top 50 clientes en barras + línea de Pareto.
- Marca visual del HHI (0.0026 = línea casi horizontal).
- Responde: *"¿Cuántos clientes se llevan la mitad del descuento?"*

#### F9. Marcar outliers + calidad de datos
- Banner top: "X% de filas sin ZONA, Y% sin cobertura. Última actualización Z."
- Outliers (BOUTIQUE 79%) marcados con asterisco en mix genérico.
- Aumenta la confianza del consumidor del dashboard en los números.

### 🟢 P2 — nice-to-have, deferrable

#### F10. Drill-down por sucursal (cliente-side)
- Click en una sucursal del bullet chart → filtra el resto del dashboard.
- Requiere exponer `DATA` globalmente + re-render.
- Mejora navegabilidad, no insights nuevos.

#### F11. Comparación con mes anterior
- Si tenemos BASE de Junio, mostrar arrows lado-a-lado (JUL fact $4.88B vs JUN fact $X).
- Requiere cargar 2 BASEs. Diferido hasta validar.

#### F12. Alertas / semáforo
- Reglas tipo: "si una acción tiene `desc_per_art > $10M`, marcarla como ALERTA".
- "Si una sucursal supera +3pp sobre global, marcarla amarilla".
- Visualizado con íconos sutiles (no chillones).

---

## Cambios de chart-type en v2 (resumen)

| v1 | v2 | Razón |
|---|---|---|
| Pulse diario — dual-axis line | Pulse diario — small multiples (2 paneles) | Antipattern dual-axis |
| Mix sucursal — vertical bars | Bullet chart (fact bar + ratio target) | Performance vs target |
| Ratios D/F — lollipop simple | Bullet chart con zonas de color | Visual encoding más rico |
| Top acciones — flat bars | Bars con callout para "mega-single-art" | Destacar H10 |
| (nuevo) | Split tipo descuento | Insight H6 |
| (nuevo) | Heatmap sucursal × genérico | Cross-cut no explorado |
| (nuevo) | Day-of-week bar | Patrón temporal semanal |
| (nuevo) | Pareto cliente con HHI | Insight H1 |
| (nuevo) | Banner de calidad de datos | Trust indicator |

---

## Plan de implementación

### v2.0 (esta semana)
1. F1, F2, F3, F4 — los 4 P0.
2. Rebuild del extractor `build_dashboard.py` para emitir los nuevos aggregates (CCU split, day-of-week, tipo descuento, mega-acciones, calidad de datos).
3. Rebuild del template HTML.

### v2.1 (próxima semana)
4. F5, F6, F7, F8, F9 — los 5 P1.

### v3.0 (futuro)
5. F10, F11, F12 — drill-down, multi-mes, alertas.

---

## Métricas de éxito

Para validar que v2 mejora v1:

- **Coverage**: el dashboard expone el HHI (H1), los outliers (H13), los mega-single-art (H10), el split tipo (H6), y los desvíos de sucursal (H12).
- **Compliance**: cero dual-axis charts, cero pies, todos los targets con bullet chart.
- **Accessibility**: contraste WCAG AA en todos los textos, todos los charts interpretables sin color.
- **Insight-first titles**: cada sección titula un hallazgo, no un dato.

---

## Notas

- El re-análisis confirma que la **calidad del extractor streaming es fundamental** — cargar wapi/cliente_fecha con pandas en memoria (no streaming) tarda ~2min pero permite estos análisis. Para v2.1+ podemos paralelizar: extractor streaming para el dashboard live, extractor full-load para el EDA offline.
- El skill `sql-optimization-patterns` también aplicaría si moviéramos los aggregates a SQL (vía `gold.*` views). Pero el BASE xlsx es post-procesamiento — los aggregates se hacen sobre los datos ya materializados. Deferrable.
- Sugerencia: correr `/tmp/eda_acciones.py` antes de cada release v2 para validar que no introducimos regresiones en los insights cubiertos.