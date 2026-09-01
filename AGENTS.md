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
│   │   │   └── ventas.py     # Endpoints de ventas
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
├── api.py                    # FastAPI application (v2.0.0)
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
    ├── cobertura-aguas/{YYYY-MM}/     # CoberturaAguasService (mensual)
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

# Iniciar API
uvicorn api:app --reload --port 8000
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

## Avances (badie, branca, guemes)

> ### 🚨 ANTES DE TOCAR UN AVANCE: leer `docs/avances-reglas.md`
>
> Son cuatro reglas cortas, cada una salida de un incidente real. Lo minimo:
>
> 1. **Los rangos de captura NO son estables entre meses.** El libro cambia (se
>    va un preventista, aparecen columnas ocultas). Un rango que anduvo el mes
>    pasado puede recortar mal este mes. Mapear el libro, renderizar y **MIRAR
>    el PNG** antes de darlo por bueno.
> 2. **Nunca regenerar para mandar**: `main.py --config` pisa las ediciones a
>    mano de Nahuel. Entregar el archivo que ya existe con `resolve_delivery` +
>    `DeliveryPipeline`, o `scripts/reenviar_fallidos.py`.
> 3. **Dry-run antes de cada envio** y leer los destinos. Van a grupos de
>    preventistas reales. Si pide "pasamelo a mi", mandar solo a el.
> 4. **El primer dia habil del mes es el CIERRE** y esta exento de
>    `desde_dia_del_mes`: es la unica corrida con el mes anterior completo.
>
> Vocabulario: "pararlo" = `ejecutar: false` (el servicio entero, no solo la
> entrega). "los avances" = los **tres**. "el cierre" = la corrida del primer
> dia habil.

Reporte diario de CASA CENTRAL contra los cupos del mes. Es el mas delicado del
sistema: **no se genera de cero, se actualiza in-place** sobre un Excel que
Nahuel mantiene a mano, y los cupos NO salen de la base.

**Documentacion completa: `docs/avance-badie.md`.** Leerlo ANTES de tocar el
config, las capturas o el flujo diario. Lo minimo que hay que saber:

- `skip_cupos: true` — las hojas `Cupos*` no se reescriben: Nahuel tipea los
  cupos antes de que entren a `gold.fact_cupos`. Recargar sin ese flag se los
  pisa. Backup + verificacion cell-by-cell obligatorios al recargar.
- **5 capturas de rango fijo**, no 25. `auto:bordes` esta descartado en las tres
  hojas. `Cober Nueva` tiene 56 columnas ocultas y LibreOffice no imprime lo
  oculto: el corte sigue lo VISIBLE, no la estructura logica de la hoja.
- El daily lo corre `mes_a_hoy` con dos compuertas: `desde_dia_del_mes` (no
  entrega los primeros dias del mes, mientras se cargan los objetivos) y el
  guard de RAM (si falta memoria omite las imagenes pero manda el xlsx igual).
- **El primer dia HABIL esta exento de `desde_dia_del_mes`: ese dia sale el
  CIERRE del mes anterior**, que es la unica corrida con el mes completo (la del
  31 a la manana no tiene el ultimo dia). Ese dia `mes_a_hoy` da el mes anterior
  cerrado, asi que los objetivos del mes nuevo no hacen falta. Sin esa exencion
  el cierre no salia nunca.
- Un rango correcto en el config NO garantiza una imagen correcta: renderizar y
  verificar el PNG antes de dar por buena una captura nueva.

## Cobertura por Calibre y Marca (`cobertura-levite`)

`python main.py --config configs/cobertura_levite.json`

Sale solo todos los dias por mail (Sebastian, Antonio, Gonzalo; Nahuel en copia)
y por WhatsApp como imagen. Solo CASA CENTRAL.

**El slug sigue siendo `cobertura-levite` pero el informe ya no es de Levite**:
son dos hojas, una por generico — `Aguas` y `Cervezas` — y cada una lleva el
MISMO cuadro repetido para tres periodos, de arriba hacia abajo: la ventana del
config (mes en curso, parcial), el mes anterior completo y el mismo mes del anio
anterior completo. Los dos historicos se DERIVAN de `fecha_hasta`
(`rango_mes` + `periodo_meses_atras`), nunca se escriben en el config.

- **Van como meses calendario ENTEROS** contra un mes en curso parcial. Es una
  decision de Nahuel (2026-08-21): los historicos quedan estables toda la
  corrida del mes. El encabezado de cada cuadro dice hasta que dia llega
  (`AGOSTO 2026 (01 al 21)` vs `JULIO 2026 (mes completo)`) para que la
  diferencia no se lea como una caida del negocio.
- **CERVEZAS muestra solo las cuatro principales** — SALTA, HEINEKEN, IMPERIAL,
  MILLER — sin banda de categoria ni subtotal. `SALTA CAUTIVA1` es otra marca y
  NO entra en la columna SALTA. **`TOTAL CERVEZAS` toma el generico completo**,
  incluidas las marcas sin columna.
- **AGUAS mantiene sus tres categorias** (MINERAL, SABORIZADA, ISOTONICA) y su
  total se queda en las 5 marcas comerciales: `SER` esta en el generico pero
  fuera del universo del informe.
- **Las filas siguen a las columnas**: un calibre que solo vendio una marca sin
  columna (470cc de KUNSTMAN) no genera fila, pero sus clientes cuentan igual en
  el total del generico.
- **El calibre sale de `des_articulo`, no de `dim_articulo.calibre`.** El
  multiplicador va indistinto con `*` o con `X`. El barril (`* 30 LITROS`) queda
  en `OTRO`: no tiene fila, pero suma al total.
- **La captura usa `auto:hoja`, no un rango fijo.** El alto de la hoja depende de
  los calibres que se vendieron en las tres ventanas; un rango escrito a mano
  recorta filas unos meses y deja franjas vacias otros.
- Los ejes (columnas y filas) se calculan sobre la UNION de los tres periodos y
  se fuerzan en los tres cuadros. Sin eso se desalinean y no se pueden comparar.

## Cobertura Aguas

`python main.py --config configs/cobertura_aguas.json`

Cobertura de AGUAS DANONE de los ultimos 2 meses, abierta por **sucursal y
marca**. Tres hojas: `Resumen` (una fila por sucursal + consolidado por marca —
es la que se captura como imagen), `Detalle` (sucursal x concepto) y `Criterio`
(como se conto, para poder auditarlo sin preguntar).

**Las 5 marcas del generico**: VILLA DEL SUR, VILLAVICENCIO, LEVITE, BRIO,
FULL SPORT. Los grupos son `AGUA MINERAL` (VDS + VV) y `AGUA SABORIZADA`
(LEVITE + BRIO). **FULL SPORT entra en TOTAL AGUAS pero en ningun grupo**: es
isotonica, no agua saborizada.

**El acumulado NO se lee de `gold.cob_*`.** Esas tablas son mensuales y la
cobertura no es aditiva entre periodos, asi que el acumulado de dos meses no
existe en ninguna y hay que calcularlo desde `fact_ventas`. Para que el calculo
no invente un criterio propio, `get_ventas_cliente_marca_mes` joinea
`dim_vendedor` por la clave compuesta y filtra `id_fuerza_ventas = 1`: con ese
filtro reproduce `cob_sucursal_marca` EXACTO (julio-2026, aguas: 23.748 contra
23.748, 0 filas de 65 con diferencia). Sin el se cuelan movimientos con
`id_vendedor = 0`, un vendedor placeholder sin ficha en `dim_vendedor`.

El acumulado **totaliza el neto sobre la ventana completa y recien ahi filtra**;
no es la union de los conjuntos mensuales. Quien compra 5 en julio y devuelve 5
en agosto queda cubierto en julio y fuera del acumulado. El corte manda.

**Padron** = `gold.dim_cliente` con `anulado = false`. Es SCD tipo 1: foto de
HOY, no del mes medido.

Los meses se DERIVAN de `fecha_hasta` (ver `src/core/periodos.py`), nunca se
escriben en el config.

## Variable Mensual (INCENTIVO HERNAN)

```bash
python main.py variable-mensual \
  --archivo 'data/output/variable_mensual/INCENTIVO HERNAN 2025.xlsm' \
  --desde 2026-07-01 --hasta 2026-07-31
```

Recarga las hojas base del libro del 4% mensual. **No genera el libro**: las
hojas de informe (`ramal`, `qbrd`, `inte`, `salta`, `ORIGINAL`, `suc`) son de
Nahuel y no se tocan. Solo se reescribe lo que esta debajo.

**Documentacion completa: `docs/variable-mensual.md`.** Lo minimo:

- **El color de pestana es el contrato**: las hojas AZULES son datos base y las
  carga Python (`AX`, `cober_marca`, `cober_gen`, `villav y villa sur`). Las
  rojas/amarillas son informe y no se tocan.
- **AX usa 11 columnas de 31.** Las otras 20 se escriben vacias: se conservan los
  encabezados y la tabla `aexcel` para que ninguna formula se rompa. El `ref` de
  la tabla se estira a la ultima fila en cada corrida — eso es lo que hace que
  las formulas AD (zona) y AE (COLON DULCE) lleguen hasta el pie.
- **`marcas_x_pdv` ya no es tabla dinamica.** A:F, J:L y N:P los calcula Python
  y se pegan como valores; el bloque R:V (promedios por zona y sucursal) sigue
  siendo formulas porque es lo que leen ramal/qbrd/inte. `pivotTable1` se elimina
  del paquete: un pivot y valores pegados no pueden compartir el mismo rango.
- **El nombre de la lista de precios esta fijado en `constants.py`**:
  `gold.dim_lista_precio` esta vacia y `dim_cliente.des_lista_precio` esta en
  blanco para los 28.392 clientes. Si aparece una lista nueva, agregarla ahi.
- Las zonas son las de `suc!Q:R` (4 zonas), **no** las de `ZONAS_VIRTUALES`: este
  libro deja la ruta 93 dentro de CASA CENTRAL.
- **`referencia ma` tambien la carga Python** (5 bloques: cobertura, volumen,
  cobertura por marca, COLON DULCE y mayorista). Son 13 sucursales fijas SIN
  casa central ni valle salta: la hoja solo alimenta ramal/qbrd/inte. El volumen
  va en BULTOS, no en htls. `SUB DISTRIBUIDORES` no cuenta como mayorista.
  Estaba congelada desde MAYO 2026 y sus bloques venian de momentos distintos.
- **El servicio repara las formulas `#REF!` que el libro ya traia** (156 de 162):
  eran SUMIFS a los que un cambio viejo les borro los rangos, y tenian todos los
  cuadros de mix mayorista de `suc` en blanco. La reparacion es idempotente.
  Quedan 6 en `inte` que apuntan a una tabla que ya no existe.

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
