# 02 — Catálogo de servicios

11 servicios registrados, cada uno en `src/services/{nombre}/` y declarado en `main.py:REPORT_HANDLERS` y en `src/config/models.py:ReportConfig.tipo` (Literal).

| # | Slug | Granularidad | Output | Config JSON |
|---|------|--------------|--------|-------------|
| 1 | `ventas` | month | xlsx (1 archivo por supervisor) | `configs/ventas.json` |
| 2 | `resumen-mensual` | month | xlsx (1 hoja por genérico) | `configs/resumen_mensual.json` |
| 3 | `champions-league` | month | xlsx multi-hoja | `configs/champions_league.json` |
| 4 | `historico-fratelli` | month | xlsx | `configs/historico_fratelli.json` |
| 5 | `stock-diario` | day | xlsx por día | `configs/stock_diario.json` |
| 6 | `cartesiano` | month | xlsx | `configs/cartesiano.json` |
| 7 | `avances` | month | actualiza plantilla in-place | `configs/avances_branca.json` |
| 8 | `graficos-cobertura` | month | xlsx + 2 pptx + ~50 PNGs | `configs/graficos_cobertura.json` |
| 9 | `ventas-articulo` | month | xlsx por artículo | `configs/schneider710.json` |
| 10 | `historico-cliente` | month | xlsx | `configs/historico_cliente_example.json` |
| 11 | `reporte-general-badie` | month | xlsx (normal + EXTENDIDO) | `configs/reporte_general_badie.json` |

---

## 1. `ventas` — Reporte de ventas por sucursal/genérico/marca

**Servicio**: `VentasService` (`src/services/ventas/service.py`, 568 líneas).

**Para qué**: reporte mensual con desglose diario, tendencia, monto y cobertura. Es el reporte "core" — uno por supervisor, donde cada supervisor recibe sólo sus sucursales.

**Hojas del Excel**:
1. `Ventas Bultos` — cantidad por día
2. `Ventas HTLs` — hectolitros (volumen) por día

**Columnas**:
```
Sucursal | Generico | Cant(Gen) | Tend(Gen) | Monto(Gen) | Cob(Gen)
       | Marca | 01-02 Lunes | 02-02 Martes | ... | 28-02 Sabado
       | Total | Tend(Marca) | Monto(Marca) | Cob(Marca)
```

**Lógica clave**:
- **Totales de genérico**: solo aparecen en la primera fila de cada grupo (sucursal+genérico).
- **Tendencia**: `cantidad * (días_totales_mes / días_transcurridos_hasta_hoy)`.
- **Días hábiles**: excluyen domingos y feriados (`config/settings.py:FERIADOS`).
- **Cobertura**: cruce con `cob_preventista_generico` / `_marca`.
- **Zonas virtuales**: CASA CENTRAL se splittea en VALLE SALTA / SUB DISTRIBUIDORES según `id_ruta`.
- **Slicers (Windows only)**: filtros visuales, omitidos en Linux.
- **Nombre archivo**: `Ventas {supervisor} - {dd-mm-yyyy}.xlsx` (fecha = última venta real).

**Config**:
```json
{
  "tipo": "ventas",
  "filtros": {
    "fecha_desde": "2026-04-01",
    "fecha_hasta": "2026-04-30",
    "genericos": ["CERVEZAS", "AGUAS DANONE"],
    "con_slicers": false,
    "con_cobertura": true
  },
  "reportes": [
    {
      "nombre": "Walter Vilte",
      "filtros": {
        "supervisores": ["Walter Vilte"]
      },
      "enviar_a": {
        "Walter Vilte": {"via": ["whatsapp", "email"]}
      }
    }
  ]
}
```

Cuando hay supervisores, genera **un xlsx por supervisor** con sus sucursales asignadas.

---

## 2. `resumen-mensual` — Resumen mensual por genérico

**Servicio**: `ResumenMensualService` (`src/services/resumen_mensual/service.py`, 576 líneas).

**Para qué**: vista mensual rápida que compara ventas actuales vs mes anterior (MA) y mismo mes año anterior (MMAA), con tendencia y objetivo.

**Hojas**: 1 por genérico (CERVEZAS, AGUAS DANONE, VINOS CCU, SIDRAS Y LICORES).

**Columnas**:
```
Sucursal | Generico | Día N-1 | Día N | Total Ventas | Tendencia
       | MMAA | MA | Objetivo | Tend vs Obj (%)
```

**Filas**:
1. `1 - CASA CENTRAL`
2. `VALLE SALTA` (zona virtual: rutas 81-92, 118-122)
3. `SUB DISTRIBUIDORES` (zona virtual: ruta 93)
4. `SUBTOTAL CASA CENTRAL` (suma de 1+2+3 con fórmulas SUM)
5. Sucursales numeradas alfabéticas
6. `SUCURSALES SIN DIRECTA` (suma de 5)
7. `DIRECTA SUCURSALES` (zona local: ruta 100 de sucursales != 1)
8. `TOTAL SIN SMK` (suma de 4+6+7)

**Lógica clave**:
- **Tendencia**: float, sin redondear.
- **MMAA en rojo, MA en oliva, Objetivo en azul** (font_color por columna).
- **Heatmap rojo→amarillo→verde** en `Tend vs Obj %` (ColorScaleRule).
- **Subtotales**: fórmulas `=SUM(...)` con fills diferenciados (verde / violeta / rojo).
- **Bordes thin** en todas las celdas.
- **Objetivo**: viene de `gold.fact_cupos` filtrando por periodo `YYYY-MM` y los 4 genéricos CCU.
- **DIRECTA SUCURSALES**: lógica local en el processor (no usa `ZONAS_VIRTUALES` global) — segrega ANTES de aplicar zonas virtuales.

**Bug histórico**: `aplicar_zonas_virtuales` dropea `id_ruta`, así que la segregación DIRECTA debe ir PRIMERO. Si se invierte el orden, no encuentra qué segregar y la fila no aparece.

---

## 3. `champions-league` — Reporte multi-categoría

**Servicio**: `ChampionsLeagueService` (`src/services/champions_league/service.py`, 609 líneas).

**Para qué**: reporte mensual con foco en cobertura de varias categorías (SCHNEIDER 710, HEINEKEN CERO, CONVIVENCIA, LEVITE, FORMATO CHICO, VILLA DEL SUR, SAENZ BRIONES, IMAM, IMPERIAL).

**Hojas**:
1. `INFO` — tabla resumen
2. `Cob Preventista Generico`
3. `Cob Preventista Marca`
4. `Cob Sucursal Generico`
5. `Cob Sucursal Marca`
6. `Cat <NOMBRE>` (una hoja por categoría con su lista de artículos)

**Lógica clave**: agrega categorías virtuales (no existen en BD) calculadas desde `dim_articulo`. Se renombró desde "misión imposible" a "champions league".

---

## 4. `historico-fratelli` — Histórico Fratelli Branca

**Servicio**: `HistoricoFratelliService` (`src/services/historico_fratelli/service.py`, 471 líneas).

**Para qué**: actualizar un excel histórico con todos los meses de venta de la marca FRATELLI BRANCA (cervezas, fernet, etc.), con desglose mensual y total anual por bloque de año.

**Lógica clave**:
- Bloques de año (uno por año del histórico) con totales por mes.
- Fila adicional **Facturas Presupuesto** (PRVTA) por bloque, con cantidades por mes.
- Usa `get_ventas_historico_fratelli` y `get_prvta_historico_fratelli`.

---

## 5. `stock-diario` — Stock al cierre del día

**Servicio**: `StockDiarioService` (`src/services/stock_diario/service.py`, 76 líneas).

**Granularidad**: día. Output en `data/output/stock-diario/{YYYY-MM-DD}/`.

**Para qué**: snapshot diario de stock por SKU/sucursal. Se manda por WhatsApp como imagen.

---

## 6. `cartesiano` — Tabla cartesiana sucursal × artículo

**Servicio**: `CartesianoService` (`src/services/cartesiano/service.py`, 106 líneas).

**Para qué**: matriz de combinaciones sucursal-artículo (no implementa cobertura ni tendencia).

---

## 7. `avances` — Avance Branca / Avance CCU

**Servicio**: `AvancesService` (`src/services/avances/service.py`, 163 líneas).

**Caso especial**: NO escribe en `data/output/`. **Actualiza el archivo plantilla** (`data/input/avances/AVANCE BRANCA - {MES} {YYYY}.xlsx`) in-place porque el usuario edita ese archivo entre corridas (mantiene fórmulas, formato manual, etc.).

**Lógica clave**:
- Lee 5 datasets: `fact_ventas`, `dim_articulo`, `dim_cliente`, `cob_preventista_generico`, `cob_preventista_marca`.
- Reemplaza las hojas de datos del Excel (deja las hojas de fórmula intactas).
- Captura 2 imágenes: `AVANCE` y `Cobertura`.

**Configurado en `configs/avances_branca.json`**.

---

## 8. `graficos-cobertura` — Paquete visual de cobertura

**Servicio**: `GraficosCoberturaService` (`src/services/graficos_cobertura/service.py`, 510 líneas).

**Output**: 1 directorio con 4 cosas:
1. `resumen.xlsx` — datos y comparativos
2. `cobertura_todos.pptx` — presentación con todos los gráficos (renombrado desde `Marca.pptx`+`Generico.pptx` a un solo PPTX en una iteración previa)
3. `png/*.png` — ~50 PNGs (matplotlib backend `Agg`)

**Esquema de zonas propio**: 5 zonas (NOA NORTE, SALTA CAPITAL, INTERIOR SALTA SUR, INTERIOR SALTA NORTE, JUJUY INTERIOR) basado en `id_sucursal`/`id_ruta` de tablas `cob_*`. **NO usa `ZONAS_VIRTUALES`** de `config/settings.py` (que esa splitea CASA CENTRAL en `fact_ventas`). Son esquemas distintos que coexisten.

**Tabla opcional**: `gold.cob_sucursal_aguas` — si no existe en el ambiente se loguea WARN y las subdivisiones de AGUAS (SABORIZADAS/MINERAL) se omiten. Controlable via `con_aguas: false`.

---

## 9. `ventas-articulo` — Ventas diarias de un artículo específico

**Servicio**: `VentasArticuloService` (`src/services/ventas_articulo/service.py`, 135 líneas).

**Para qué**: tracking diario de un solo artículo (e.g. `SCHNEIDER 710*24 LATA 0606`). Una sucursal por fila, cantidades por día como columnas.

**Configurado en**: `configs/schneider710.json` (id_articulo + capture imagen + envío email).

---

## 10. `historico-cliente` — Histórico de un cliente individual

**Servicio**: `HistoricoClienteService` (`src/services/historico_cliente/service.py`, 134 líneas).

**Para qué**: histórico mensual de las compras de un cliente puntual (id_cliente + id_sucursal).

**Config example**: `configs/historico_cliente_example.json`.

---

## 11. `reporte-general-badie` — Reporte trimestral CCU con dropdown

**Servicio**: `ReporteGeneralBadieService` (`src/services/reporte_general_badie/service.py`, 140 líneas).

**Output**: SIEMPRE 2 archivos por ejecución:
1. `Reporte General Badie.xlsx` (datos desde 2024)
2. `Reporte General Badie EXTENDIDO.xlsx` (datos desde 2022)

**Lógica clave**:
- Hoja `Reporte` con dropdown trimestral (`YYYY-Q1`..`YYYY-Q4`) en celda `B2`.
- Hojas `VentasCCU` y `CoberturaCCU` con datos crudos por (sucursal, generico, anio, trimestre, id_cliente).
- Fórmulas con `SUMPRODUCT` para que el reporte cambie automáticamente al elegir trimestre del dropdown.
- 17 columnas: Sucursal | Total CCU | Total CCU AA | AA vs MMAA | %CERVEZAS | %AGUAS | %MULTI | Cob ≥3 Bultos | Cob Promedio | Cob s/regalos ≥3 | Cob s/regalos prom | Cob ≥1 c/regalos | Cob <1 Bulto s/regalos | Cob <1 Bulto c/regalos | AGUAS DANONE ≥3 | AGUAS DANONE ≥3 (s/regalos).
- Heatmap rojo→verde en columnas de cobertura (verde→rojo invertido en columnas de auditoría).
- Bordes gruesos entre grupos visuales.

---

## Tabla de archivos y métodos del DataLoader por servicio

| Servicio | Métodos DataLoader principales |
|----------|--------------------------------|
| ventas | `get_sucursales`, `get_articulos`, `get_ventas_diarias_con_ruta`, `get_cobertura_preventista_*`, `get_cobertura_sucursal_*` |
| resumen-mensual | `get_ventas_resumen_mensual`, `get_ventas_ultimos_dias_habiles`, `get_ventas_mes_anterior`, `get_ventas_mismo_mes_anio_anterior`, `get_cupos_resumen_mensual` |
| graficos-cobertura | `get_cobertura_*`, `get_cob_sucursal_aguas` (opcional) |
| reporte-general-badie | `get_sucursales`, `get_ventas_mensuales_ccu`, `get_cobertura_clientes_ccu` |
| historico-fratelli | `get_ventas_historico_fratelli`, `get_prvta_historico_fratelli` |
| ventas-articulo | `get_ventas_articulo_diario` |
| stock-diario | `get_stock_diario` |
| champions-league | `get_articulos_categoria`, `get_cobertura_*` |
| avances | `get_ventas`, `get_articulos`, `get_clientes`, `get_cobertura_preventista_*` |
| historico-cliente | `get_ventas_historico_cliente` |

Ver método-por-método en [03-database.md](03-database.md).
