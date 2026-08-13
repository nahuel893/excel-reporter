# Verificacion adversarial — Acciones Comerciales
**Periodo 2026-07-01 -> 2026-07-29** · BASE 77.692 filas wapi / 2.029 articulos
**48 agentes Sonnet 5** · 18 checks · 108 formulas inventariadas · 4,1M tokens · 49 min
**16 veredictos sostenidos · 2 refutados · 3 fallas confirmadas**

---

ry": "Verificacion exhaustiva y adversarial de la logica de acciones-comerciales contra las formulas del engine Excel original",
  "agentCount": 48,
  "logs": [
    "Fase 1 — extrayendo formulas del engine y mapeando la implementacion Python",
    "Formulas/divergencias inventariadas: 108",
    "Checks a ejecutar: 18 (12 nucleo + 6 descubiertos)",
    "Veredictos: 16 sostenidos, 2 refutados"
  ],
  "result": {
    "total_checks": 18,
    "sostenidos": 16,
    "refutados": 2,
    "fallas_confirmadas": 3,
    "formulas_inventariadas": 108,
    "informe": "# Informe Ejecutivo — Verificación Adversarial Pipeline Acciones Comerciales (Julio 2026)

## 1. Veredicto general

| ID | Check | Resultado | Filas OK / FALLA | Severidad |
|---|---|---|---|---|
| DIV-01 | SUCURSAL: VLOOKUP contra mapa congelado `aexcel!BG:BH` vs lookup en vivo | FALLA | 76.104 / 1.509 | **Alta** |
| DIV-05 | ZONA/Supervisor: config `acciones_comerciales_zonas.json` incompleto (5 de 14 sucursales) | FALLA | 49.199 / 28.414 | **Alta** |
| DIV-03 | PRECIO FINAL: VLOOKUP contra snapshot congelado `aexcel!BD:BE` vs lookup en vivo | PARCIAL | 50.207 / 1.748 | Media |
| DIV-02 | CONCAT: formato de fecha (ISO vs serial Excel) | PASA | 51.955 / 0 | Baja |
| F1 | Total2 = Cantidad × PRECIO FINAL | PASA | 77.689 / 0 | Ninguna |
| F2 | Descuento = Total2×Desc%/100 + CantSinCargo×PRECIO | PASA | 77.692 / 0 | Ninguna |
| F3 | Tipo Descuento = IF(Desc%="";"SIN CARGO";"Descuentos") | PASA | 77.692 / 0 | Ninguna |
| F4 | mvb = MVB/ESC/EXTRA TASA/OTRAS | PASA | 77.692 / 0 | Ninguna |
| F5 | Descuento $ sobre PN SF = Total×Desc%/100 + CantSinCargo×Precio Neto SF | PASA | 77.692 / 0 | Ninguna |
| F6 | FACT_NET: detalle vs TOTAL GENERAL + Campo1 | PASA | 2.029 / 0 | Ninguna |
| F8 | aexcel: Facturación Neta / Descuentos | PASA | 178.052 / 0 | Ninguna |
| F9 | Regla de oro: joins por clave compuesta (id + id_sucursal) | PASA | 178.052 / 0 | Ninguna |
| F10 | Modelo de tasa (Tasa Generada, Diferencia, Compra Necesaria) | PASA | 8 / 0 | Ninguna |
| F11 | Agregaciones del informe vs BASE | PASA | 2.056 / 0 | Ninguna |
| DIV-04 | PRECIO FINAL en blanco → Total2/Descuento heredan blanco (vs IFERROR→0) | PASA | 77.692 / 0 | Ninguna |
| DIV-06 | SUM=0 → NaN (Python) vs #DIV/0! (Excel) en Campo1 | PASA | 2.030 / 0 | Ninguna |

## 2. Fórmulas del engine verificadas

| Fórmula Excel literal | Semántica | Resultado | Peor desvío |
|---|---|---|---|
| `wapi!AA3 = Tabla2[Cantidad]*Tabla2[PRECIO FINAL]` | Total2 = Cantidad × Precio Final | PASA | 3,73e-09 (ruido float) |
| `wapi!AB3 = IFERROR(AA3*O3/100+N3*X3,0)` | Descuento = Total2×Desc%/100 + SinCargo×Precio | PASA | 2,33e-10 (ruido float) |
| `wapi!AC3 = IF(Desc%="","SIN CARGO","Descuentos")` | Tipo Descuento | PASA | 0 (exacto) |
| `wapi!Y` (FIND anidado: MVB / (ESC.) / EXTRA TASA / else OTRAS) | Clasificación mvb | PASA | 0 (case-sensitive fiel, sin impacto en dataset real) |
| `wapi!P3 = M3*O3/100+N3*L3` | Descuento $ sobre PN SF | PASA | 1,82e-12 (ruido float) |
| `FACT_NET Campo1 = Descuentos/Facturación` | Ratio descuento/facturación | PASA | 2,22e-16 (epsilon float) |
| `aexcel!AV/AW = Precio*CantTot` / `Precio*Bonific*CantTot` | Facturación Neta / Descuentos | PASA | 5,00e-09 (Python usa columnas ya calculadas de gold, no recalcula — equivalente numéricamente) |
| `COMPRAS & DESC!F=C*D`, `J=(I+G+H)-B`, `E=J/D` | Tasa Generada, Diferencia, Compra Necesaria | PASA | 1,91e-06 sobre magnitudes de ~350-451M (relativo ~4e-15) |
| `wapi!V3 = VLOOKUP(D3,aexcel!$BG:$BH,2,0)` (sin IFERROR) | SUCURSAL | **FALLA** | Mapa congelado en fila 10.988 (10.987 clientes); 1.509 filas/$86,16M sin match |
| `wapi!W3 = CONCATENATE(A3,D3,U3)` | Clave de cruce | PASA (con divergencia cosmética) | Texto 100% distinto (fecha serial vs ISO) pero sin uso downstream |
| `wapi!X3 = VLOOKUP(W3,aexcel!BD:BE,2,0)` (sin IFERROR) | PRECIO FINAL | **PARCIAL** | Snapshot congelado deja 1.723 filas #N/A en el motor; Python resuelve 1.748/1.723 en vivo |
| `wapi!Z3 = VLOOKUP(SUCURSAL,suc!B:C,2,0)` | ZONA/supervisor | **FALLA** | Config Python cubre 5/14 sucursales reales; 28.414 filas quedan en blanco |

## 3. Defectos confirmados

### DIV-01 — SUCURSAL vía mapa congelado obsoleto (Severidad: Alta)
- **1.509 filas (1,94%) / 555 clientes distintos** no tienen entrada en `aexcel!BG:BH` (mapa pegado-como-valores, congelado en la fila 10.988).
- **Impacto: $86.160.831,15** (2,53% del Total general del período, $3.407.748.455,74).
- El motor Excel, tal cual está (VLOOKUP exacto **sin** IFERROR), devolvería `#N/A` para esas filas. Python (RF-04, lookup en vivo contra `dim_cliente`) resuelve correctamente.
- Peor caso: cliente 60945 (MENDEZ RUBEN), 24/07/2026, Total $24.664.016,00 → SUCURSAL correcta "7 - SUCURSAL TARTAGAL", ausente del mapa congelado.
- 0 casos de reasignación real de sucursal (el defecto es 100% de cobertura, no de dato incorrecto). Sostenido por 3 refutadores independientes, cifras reproducidas al centavo.
- Aparte (ya conocido, no es parte de este defecto): 79 filas / 13 clientes donde el lookup en vivo de Python NO resuelve pese a que el snapshot sí tenía esos clientes — ya está surfaceado en la hoja Reconciliación ("FILAS NO RESUELTAS - SUCURSAL"), impacto $1.839.482,11.

### DIV-05 — Config de supervisor/zona incompleto (Severidad: Alta)
- **28.414 filas (36,6%) / 9 sucursales reales** (TARTAGAL, ORAN, MAIMARA, LIBERTADOR, JOAQUIN V GONZALEZ, SAN PEDRO, HUMAHUACA, GUEMES, LA QUIACA) quedan con ZONA en blanco porque `configs/acciones_comerciales_zonas.json` solo tiene 5 claves, mientras el motor (`suc!B:C`) mapea 14-16 sucursales activas contra 3 supervisores (Adrian Garcia, Antonio Cabrerizo, Hernan Yapura).
- **Impacto: Total2 $2.115.858.032,00 / Total $1.690.723.312,25.**
- El propio config trae la nota `"PLACEHOLDER VALUES pending confirmation... verify before Phase-2 sign-off"` — está incompleto a propósito, en espera de confirmación de negocio, no terminado.
- Hoy no es crítico porque ZONA aún no se usa para dividir el informe por supervisor (no está referenciado en `build_informe_excel.py`), pero **si se activa el split por supervisor (Fase 2) sin corregir esto, Hernan Yapura pierde 9 sucursales y Adrian Garcia pierde 2 (JOAQUIN V GONZALEZ y GUEMES)**.
- Nota de disputa menor entre refutadores: uno de los tres encontró que además hay 79 filas con SUCURSAL vacía *desde el origen* (no relacionado al fallback de config, sino a datos que llegan sin SUCURSAL) que subirían el total a 28.493 filas / ~$2.118M. La mayoría (2 de 3 refutadores) no adoptó esa corrección y sostuvo la cifra original de 28.414 — la queda como nota a investigar, no como corrección aceptada.
- Defecto adicional latente detectado en el mismo config (no cuantificado en pesos porque hoy no tiene impacto): `"SUCURSAL ABRA PAMPA": "Walter Vilte"` no coincide con `suc!C` del motor (`"HERNAN YAPURA"`) — inocuo hoy porque esa sucursal tuvo 0 filas en julio 2026, pero es un dato incorrecto, no solo ausente.

### DIV-03 — PRECIO FINAL vía snapshot congelado (Severidad: Media, resultado PARCIAL)
- **1.748 de 51.955 filas del motor (3,37%)** tienen `PRECIO FINAL = #N/A` en el motor porque `aexcel!BD:BE` (snapshot congelado) no incluye esas 795 ternas fecha/cliente/artículo. Python las resuelve en vivo (RF-05) al 100%.
- Impacto bruto (sin netear reversas): Total2 $92.793.207,41, Descuento $11.479.165,93. Impacto neto (netea pares de reversa): Total2 -$1.431.444,08, Descuento -$5.887,30. El efecto neto agregado es chico porque 791 de 795 ternas son pares de reversa/nota de crédito que se cancelan, **pero hay al menos una terna con efecto neto real y grande**: cliente 208259, artículo 1085, 13/07/2026, cantidad neta -50, Total2 real -$1.304.261,50 (91% del impacto neto agregado).
- Confirmado por 3 refutadores independientes con reproducción exacta de todas las cifras.

### DIV-02 — CONCAT con formato de fecha divergente (Severidad: Baja)
- **100% de las 51.955 filas emparejadas** tienen texto de CONCAT distinto carácter a carácter (Python usa fecha ISO `'2026-07-18'`, Excel usa el serial crudo `46221`).
- **Impacto: $0.** La columna CONCAT se escribe una sola vez en `processor.py` y nunca se vuelve a leer en ningún punto del pipeline Python (PRECIO FINAL usa un lookup por tupla, no por string). Es un campo "muerto" para el cálculo, aunque puede confundir a un analista que compare celda a celda ambos archivos.
- No refutado por ningún revisor.

## 4. Divergencias intencionales

- **DIV-04 (RF-08, documentado en `processor.py` línea 20)**: cuando PRECIO FINAL no resuelve, Python deja Total2/Descuento en blanco en vez del `IFERROR→0` del motor. Numéricamente equivalente en cualquier suma (0 vs blanco tratado como 0), y hoy solo afecta 3 filas de un día cerrado (22/07), ya señaladas en la hoja Reconciliación como "REVISAR (día cerrado)". Impacto: $0 de distorsión.
- **DIV-06**: cuando `SUM(Facturación Neta)` de un grupo es 0, Python escribe `NaN` (celda en blanco) en vez del `#DIV/0!` literal que mostraría Excel. Es solo una divergencia de *display* en una columna auxiliar de `FACT_NET` que **no es fórmula viva** (se escribe como valor estático) y nunca se lee aguas abajo — confirmado por grep que "Campo1" no aparece fuera de `pivots.py`/`constants.py`. Impacto: $0.
- **F8 — diseño, no traducción literal**: `get_aexcel_equivalent` no recalcula Facturación Neta/Descuentos con la fórmula del motor (`Precio*CantTot`), sino que trae esas columnas ya calculadas de `gold.fact_ventas`. Es una decisión de diseño (usar el ETL de gold en vez de recomputar en Python) validada porque el ETL construyó esas columnas con exactamente la misma fórmula (incluyendo `abs()` sobre precio y `/100` sobre bonificación) — verificado con pruebas de sensibilidad que rompen el ajuste si se remueve cualquiera de esas dos transformaciones.
- **DIV-01 / DIV-03 — diseño RF-04/RF-05**: la decisión de resolver SUCURSAL y PRECIO FINAL contra una consulta *en vivo* a `dim_cliente`/gold, en vez de reusar el mapa congelado del motor viejo, es intencional y **correcta** — el motor viejo tiene fórmulas VLOOKUP exactas **sin IFERROR** contra tablas que dejaron de crecer, y por lo tanto produciría `#N/A` real para esas filas si se recalculara hoy. La magnitud de la divergencia (alta en DIV-01, media en DIV-03) no es un bug del pipeline nuevo: es el tamaño real de lo que el motor viejo ya no puede resolver. Igual amerita comunicarse porque es sustancial en pesos.

## 5. Puntos ciegos

- **F7 (lookup de PRECIO FINAL por terna multi-precio) fue descartado** por refutación mayoritaria (2 de 3). El área que abrió esa discusión quedó sin cerrar formalmente:
  - Un refutador encontró en la propia hoja Reconciliación ("COMPARACIÓN PRECIO: TERNA vs COMPROBANTE") 23 filas/19 ternas adicionales con precio discrepante hasta 24,88% en días cerrados, no contempladas en el conteo original de "3 filas fallidas".
  - Otro refutador, abriendo el motor original directamente, encontró que de 59 ternas multi-precio verificables contra el motor (ventana 01/07 al 20/07, único tramo con snapshot de referencia), **11 (18,6%) tienen un precio distinto** al que calcula el VLOOKUP real del motor — cuestionando si la regla de desempate documentada ("mayor Cantidad; empate mayor Precio; empate menor id_línea") reproduce fielmente el comportamiento real de Excel con claves duplicadas.
  - Las 38 ternas multi-precio del tramo 21/07-29/07 **no son verificables** porque no hay backup del motor para esas fechas — quedan como "no verificable", no como "correctas por extrapolación".
  - **Conclusión: no hay un número consolidado y confiable de cuántas filas de PRECIO FINAL están mal por la regla de desempate multi-precio.** Esto queda pendiente de una re-verificación específica.
- **F12 (regla anti-redondeo)** también fue descartado, pero por un motivo distinto: dos refutadores independientes detectaron que el checker original citó cifras de una **instantánea vieja de la BASE (21-jul, 55.201 filas)** en vez del archivo vigente del worktree (29-jul, 77.692 filas). La conclusión cualitativa (el código no trunca/redondea datos) se sostuvo en la revisión de código independiente, pero **no hay evidencia empírica fresca y confiable sobre el archivo actual** para ese check específico — habría que re-correrlo contra la BASE de hoy.
- **F8**: el crudo `aexcel.xlsx` no trae las columnas Facturación Neta/Descuentos (se calculan por fórmula de tabla en el motor), por lo que no se pudo contrastar el ETL de gold contra el archivo fuente original en esas dos columnas puntuales — solo contra los valores ya calculados por el motor.
- **DIV-05**: el impacto real de este defecto en el negocio (reparto incorrecto por supervisor) **todavía no se materializó** porque la funcionalidad de split por supervisor no está activa (Fase 2 pendiente) — es un riesgo latente, no un error visible hoy en ningún informe entregado.

## 6. Veredictos descartados

### F7 — PRECIO FINAL: lookup por terna y ternas multi-precio (PARCIAL → descartado)
Refutado por 2 de 3 revisores:
- Uno confirmó el veredicto original íntegramente (sin objeciones).
- Uno encontró que el propio archivo BASE, en la sección "COMPARACIÓN PRECIO: TERNA vs COMPROBANTE" de Reconciliación (filas 3647-3671, fuera del rango que el check original había recortado), documenta 23 filas/19 ternas con precio discrepante hasta $7.160,41 (24,88%) — cobertura insuficiente en el original.
- Uno abrió el motor Excel directamente (en vez de solo verificar consistencia interna de la BASE nueva) y encontró que 11 de 59 ternas verificables tienen un precio distinto al que el motor realmente calcula — cuestionando la fidelidad de la regla de desempate documentada.

Se cae por **cobertura insuficiente**: el "0 mismatches" del veredicto original solo probaba consistencia interna del pipeline nuevo consigo mismo, no fidelidad contra el resultado real del motor.

### F12 — Regla anti-redondeo (PASA → descartado)
Refutado por 2 de 3 revisores:
- Uno confirmó la revisión de código (0 ocurrencias de redondeo/truncamiento sobre datos) pero detectó que la "evidencia numérica" del punto 4 (conteos de filas con más de 2 decimales) no era reproducible: el archivo real tiene 77.692 filas, no 55.201.
- Otro confirmó exactamente lo mismo: el checker había leído una copia vieja de la BASE (2026-07-21) en vez de la vigente en el worktree (2026-07-29).
- Uno defendió el veredicto (refutado=false), sosteniendo que la conclusión cualitativa seguía siendo válida pese al error de archivo.

Se cae por **evidencia empírica sobre un archivo desactualizado**, no porque la conclusión de fondo (el código no redondea) esté mal — de hecho los tres coinciden en que el código en sí está limpio.