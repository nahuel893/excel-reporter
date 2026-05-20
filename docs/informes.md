# Informes — Guía de Negocio

Catálogo completo de los reportes automatizados del sistema. Cada informe está pensado para un destinatario y propósito específico.

---

## 1. Ventas — Reporte diario de ventas por sucursal

**Propósito**: Reporte principal del sistema. Muestra ventas diarias desglosadas por sucursal, genérico y marca, con tendencia, montos y cobertura.

**Destinatarios**: supervisores de zona (Walter Vilte, Antonio Cabrerizo, Adrián García, Hernán Yapura). Cada supervisor recibe solo sus sucursales.

**Frecuencia**: diario (corre en el daily run con datos del mes en curso).

**Formato**: 1 archivo Excel por supervisor, 2 hojas:
1. **Ventas Bultos** — cantidades por día con tendencia
2. **Ventas HTLs** — hectolitros (volumen) por día

**Columnas típicas** (hoja Ventas Bultos):
```
Sucursal | Genérico | Cant(Gen) | Tend(Gen) | Monto(Gen) | Cob(Gen)
  | Marca | 01-02 Lun | 02-02 Mar | ... | 28-02 Sáb
  | Total | Tend(Marca) | Monto(Marca) | Cob(Marca)
```

**Lógica clave**:
- **Zonas virtuales**: CASA CENTRAL se divide automáticamente en VALLE SALTA y SUB DISTRIBUIDORES según la ruta del cliente.
- **Tendencia**: proyecta ventas al mes completo: `cantidad × (días del mes / días transcurridos)`.
- **Cobertura**: cruza con tablas `cob_preventista_*` para mostrar cobertura por preventista y sucursal.
- **Slicers**: filtros visuales Excel (solo Windows).

**Config**: `configs/ventas.json`

**Contactos** que reciben este informe: Walter Vilte (email), Antonio Cabrerizo (email), Adrián García (email), Hernán Yapura (email), Gonzalo Farah (WhatsApp), Sebastian Dellamea (WhatsApp).

---

## 2. Resumen Mensual — Comparativo mensual con histórico

**Propósito**: Vista rápida de ventas del mes actual comparadas con mes anterior (MA) y mismo mes del año anterior (MMAA), más tendencia y objetivo contra cupo.

**Destinatarios**: supervisores y gerencia.

**Frecuencia**: mensual (corre en daily run).

**Formato**: 1 archivo Excel, 1 hoja por genérico (CERVEZAS, AGUAS DANONE, VINOS CCU, SIDRAS Y LICORES).

**Columnas**:
```
Sucursal | Genérico | Día N-1 | Día N | Total Ventas | Tendencia | MMAA | MA | Objetivo | Tend vs Obj (%)
```

**Filas** (por cada genérico):
1. `1 - CASA CENTRAL`
2. `VALLE SALTA` (zona virtual: rutas 81-92, 118-122)
3. `SUB DISTRIBUIDORES` (zona virtual: ruta 93)
4. `SUBTOTAL CASA CENTRAL` (fórmulas SUM)
5. Sucursales numeradas alfabéticamente
6. `SUCURSALES SIN DIRECTA`
7. `DIRECTA SUCURSALES` (ruta 100, sucursales ≠ 1)
8. `TOTAL SIN SMK`

**Lógica clave**:
- **Objetivo**: desde `gold.fact_cupos`, filtrado por período `YYYY-MM`.
- **Heatmap**: color scale rojo→amarillo→verde en `Tend vs Obj %`.
- **Colores por columna**: MMAA en rojo, MA en oliva, Objetivo en azul.
- **Bug histórico**: DIRECTA SUCURSALES debe segregarse ANTES de aplicar zonas virtuales.

**Config**: `configs/resumen_mensual.json`

**Contactos**: Gonzalo Farah, Sebastian Dellamea, Antonio Cabrerizo, Nahuel Aguirre.

---

## 3. Champions League — Cobertura multi-categoría

**Propósito**: Reporte mensual de cobertura para múltiples categorías especiales. Muestra cobertura por preventista (genérico y marca) y por sucursal (marca).

**Categorías incluidas**: SCHNEIDER 710, HEINEKEN CERO, CONVIVENCIA, LEVITE, FORMATO CHICO, VILLA DEL SUR, SAENZ BRIONES, IMAM, IMPERIAL.

**Frecuencia**: mensual.

**Formato**: Excel con 6+ hojas:
1. `INFO` — tabla resumen
2. `Cob Preventista Genérico`
3. `Cob Preventista Marca`
4. `Cob Sucursal Genérico`
5. `Cob Sucursal Marca`
6. `Cat <NOMBRE>` — una hoja por categoría con su lista de artículos

**Lógica clave**: las categorías son virtuales (se calculan desde `dim_articulo`, no existen en BD como tal).

**Config**: `configs/champions_league.json`

**Contactos**: Gonzalo Farah, Sebastian Dellamea.

---

## 4. Histórico Fratelli — Ventas históricas Fratelli Branca

**Propósito**: Histórico de ventas de FRATELLI BRANCA (cervezas, fernet, etc.) con desglose mensual y total anual.

**Frecuencia**: mensual.

**Formato**: Excel con bloques de año, totales por mes, y fila adicional de **Facturas Presupuesto (PRVTA)** por bloque.

**Destinatarios**: gerencia / administración.

**Config**: `configs/historico_fratelli.json`

---

## 5. Stock Diario — Stock al cierre del día

**Propósito**: Snapshot diario del stock por SKU y sucursal.

**Frecuencia**: diaria. Output en `data/output/stock-diario/{YYYY-MM-DD}/`.

**Formato**: Excel, enviado por WhatsApp como imagen.

**Destinatarios**: logística / depósito.

**Config**: `configs/stock_diario.json`

**Nota**: depende de `gold.fact_stock`. Si no hay datos cargados para el día, no genera nada.

---

## 6. Cartesiano — Matriz sucursal × artículo

**Propósito**: Tabla cartesiana de combinaciones sucursal-artículo.

**Frecuencia**: mensual.

**Formato**: Excel sin cobertura ni tendencia — tabla plana de ventas por combinación sucursal-artículo.

**Config**: `configs/cartesiano.json`

---

## 7. Avances — Avance Branca (plantilla editable)

**Propósito**: Reporte de avance mensual que **actualiza una plantilla Excel existente** in-place. El usuario edita ese archivo manualmente entre corridas (mantiene fórmulas, formato manual, captura imágenes del avance).

**Caso especial**: NO escribe en `data/output/`. Modifica directamente `data/input/avances/AVANCE BRANCA.xlsx`.

**Formato**: actualiza 5 datasets (ventas, artículos, clientes, cobertura preventista genérico y marca) reemplazando hojas de datos, dejando intactas las hojas de fórmula.

**Capturas**: 2 imágenes por reporte (hojas `AVANCE` y `Cobertura`).

**Frecuencia**: mensual.

**Destinatarios**: grupo WhatsApp "Preventa + Vinos Bodega E" + Nahuel Aguirre.

**Config**: `configs/avances_branca.json`

---

## 8. Gráficos Cobertura — Paquete visual mensual

**Propósito**: Reporte visual completo de cobertura con gráficos, presentación PPTX y PNGs. Es el informe más pesado del sistema (~50 archivos generados).

**Frecuencia**: mensual. Output en `data/output/graficos-cobertura/{YYYY-MM}/`.

**Formato**: 1 directorio con:
1. `resumen.xlsx` — datos y comparativos por zona
2. `cobertura_todos.pptx` — presentación con gráficos por marca y genérico
3. `png/*.png` — ~50 PNGs generados con matplotlib (backend Agg)

**Zonas propias** (5 zonas):
- NOA NORTE
- SALTA CAPITAL
- INTERIOR SALTA SUR
- INTERIOR SALTA NORTE
- JUJUY INTERIOR

NO usa ZONAS_VIRTUALES de `config/settings.py`. Esquema de zonas independiente.

**Tabla opcional**: `gold.cob_sucursal_aguas` — si existe, desagrega AGUAS en SABORIZADAS/MINERAL.

**Destinatarios**: Gonzalo Farah, Sebastian Dellamea, Antonio Cabrerizo (email + WhatsApp), Nahuel Aguirre.

**Config**: `configs/graficos_cobertura.json`

---

## 9. Ventas Artículo — Tracking diario de un artículo

**Propósito**: Seguimiento diario de ventas de **un solo artículo** específico. Una sucursal por fila, cantidades por día como columnas.

**Frecuencia**: mensual (configurado como `schneider710` para el artículo SCHNEIDER 710*24 LATA 0606).

**Formato**: Excel con captura de imagen.

**Config**: `configs/schneider710.json`

---

## 10. Histórico Cliente — Histórico de un cliente individual

**Propósito**: Histórico mensual de compras de un cliente puntual.

**Frecuencia**: mensual.

**Formato**: Excel, una hoja por cliente, filas = artículos o marcas, columnas = meses.

**Config**: `configs/historico_cliente_example.json` (archivo de ejemplo).

---

## 11. Reporte General Badie — Reporte trimestral CCU

**Propósito**: Reporte trimestral con dropdown interactivo para seleccionar trimestre. Muestra ventas y cobertura CCU por sucursal con comparativas vs año anterior.

**Frecuencia**: trimestral.

**Formato**: SIEMPRE genera 2 archivos:
1. `Reporte General Badie.xlsx` — datos desde 2024
2. `Reporte General Badie EXTENDIDO.xlsx` — datos desde 2022

**Hojas**:
- `Reporte` — dropdown trimestral en celda `B2` (fórmulas SUMPRODUCT que cambian al seleccionar trimestre)
- `VentasCCU` — datos crudos por sucursal, genérico, año, trimestre, cliente
- `CoberturaCCU` — datos de cobertura

**17 columnas**: Sucursal, Total CCU, Total CCU AA, AA vs MMAA, %CERVEZAS, %AGUAS, %MULTI, Cob ≥3 Bultos, Cob Promedio, Cob s/regalos ≥3, Cob s/regalos prom, Cob ≥1 c/regalos, Cob <1 Bulto s/regalos, Cob <1 Bulto c/regalos, AGUAS DANONE ≥3, AGUAS DANONE ≥3 (s/regalos).

**Config**: `configs/reporte_general_badie.json`

---

## 12. Cobertura — Reporte de cobertura por preventista

**Propósito**: Reporte de cobertura que compara períodos. Muestra cobertura por preventista, ruta, genérico y marca.

**Frecuencia**: bajo demanda (no corre en daily).

**Formato**: Excel con slicers (Windows) o tabla plana. Soporta 3 tipos:
- `preventista_generico` — Cobertura por vendedor, ruta y genérico
- `preventista_marca` — Cobertura por vendedor, ruta y marca
- `sucursal_marca` — Cobertura por sucursal y marca

**Slicers**: filtros interactivos (solo Windows con Excel instalado).

**Config**: no tiene config en `configs/` — es invocado directamente.

---

## 13. Rebotes — Rechazos por vendedor y cliente

**Propósito**: Reporte de bounces/rechazos (devoluciones) de mercadería. Identifica vendedores y clientes con alto porcentaje de rechazo.

**Frecuencia**: mensual (corre en daily run).

**Formato**: Excel con 4 hojas:

1. **Rebotes** — vendedores con bultos vendidos, bultos rechazados y % rechazo, agrupados por supervisor. Fila TOTALES y filas de supervisor con subtotales. Semáforo: verde < 3%, amarillo 3-5%, rojo > 5%. GFARAH = total general de todos los vendedores de sucursal 1.

2. **Ventas por Cliente** — por cliente y genérico: bultos vendidos, bultos rechazados y % rechazo con semáforo.

3. **Rechazos por Cliente** — solo bultos rechazados por cliente y genérico.

4. **% Rebotes x Genérico** — pivot por vendedor y supervisor con columnas intercaladas: `Bultos | Rechazados | %` para cada grupo genérico (CERVEZAS, AGUAS DANONE, MULTICCU).

**Lógica clave**:
- **Rebote = bultos rechazados / bultos vendidos** (puede dar >100% si hay más rechazos que ventas).
- **Rechazos = cantidades_total < 0** en `fact_ventas` (devoluciones con signo negativo).
- **MULTICCU = VINOS CCU + SIDRAS Y LICORES** combinados, con % recalculado.
- **DIRECTA** oculta visualmente pero suma en totales.
- **Supervisores**: ANOGALES, FGUANTAY, GFARAH (total), GFLORES, VCHAPUR.

**Destinatarios**: Gonzalo Farah, Sebastian Dellamea (WhatsApp).

**Config**: `configs/rebotes.json`

---

## 14. BD Agent — Asistente WhatsApp con IA (no genera informe)

**Propósito**: Agente conversacional que responde preguntas sobre datos del Data Warehouse vía WhatsApp. NO es un reporte — es un canal de consulta en lenguaje natural.

**Arquitectura**:
- WhatsApp (Baileys) → FastAPI → Gemini Flash Lite → SQL → respuesta
- Filtra por contactos autorizados, horario activo (08:00-20:00) y rate limit (50 msg/día).
- Puede generar reportes bajo demanda via sandbox Docker (Python).

**Costo estimado**: ~$0.47/mes por usuario activo (modelo Gemini 2.0 Flash Lite).

**Config**: `configs/contactos_agente.json` (lista blanca de contactos).

## Resumen de entregas

| Informe | A quién llega | Canal principal | Frecuencia |
|---------|---------------|-----------------|------------|
| Ventas | Supervisores (4) + GF | WhatsApp (GF/SD) / Email (supervisores) | Diaria |
| Resumen Mensual | GF, SD, AC, NA | Email + WhatsApp | Mensual |
| Champions League | GF, SD | Email | Mensual |
| Histórico Fratelli | Administración | Email | Mensual |
| Stock Diario | Logística | WhatsApp (imagen) | Diaria |
| Cartesiano | (bajo demanda) | — | Mensual |
| Avances Branca | Grupo "Preventa + Vinos Bodega E" | WhatsApp (imagen) | Mensual |
| Gráficos Cobertura | GF, SD, AC, NA | Email + WhatsApp | Mensual |
| Ventas Artículo (Schneider) | (bajo demanda) | Email | Mensual |
| Histórico Cliente | (bajo demanda) | — | Mensual |
| Reporte General Badie | Gerencia | Email | Trimestral |
| Cobertura | (bajo demanda) | — | Bajo demanda |
| Rebotes | GF, SD | WhatsApp (imagen + Excel) | Mensual |
| BD Agent | Contactos autorizados | WhatsApp (chat) | Diario / bajo demanda |

> GF = Gonzalo Farah, SD = Sebastian Dellamea, AC = Antonio Cabrerizo, NA = Nahuel Aguirre (test/backup)
