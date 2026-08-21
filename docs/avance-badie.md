# AVANCE BADIE — el reporte y su carga diaria

Reporte diario de avance de CASA CENTRAL (sucursal 1) contra los cupos del mes.
Es el informe más delicado del sistema: **no se genera desde cero, se actualiza
in-place** sobre un Excel que Nahuel mantiene a mano, y una parte de sus datos
NO sale de la base.

- Config: `configs/avances_badie.json`
- Servicio: `src/services/avances/service.py` (`tipo_plantilla: "badie"`)
- Salida: `data/output/avances/{YYYY-MM}/AVANCE BADIE - {MES} {AÑO}.xlsx`
- Tests: `tests/test_avances_badie_capture_wiring.py`, `tests/test_avances_service.py`

---

## 1. Qué escribe el servicio y qué no

El workbook tiene 22 hojas. El servicio toca **tres**; las otras diecinueve
—incluidas las de fórmulas que arma el usuario— hacen un round-trip intacto.

| Hoja | Origen | Se reescribe |
|---|---|---|
| `pivot_python` | `get_fact_ventas_pivot_badie` | sí |
| `cober_gen` | `get_cob_preventista_generico_pivot_badie` | sí |
| `cober_marca` | `get_cob_preventista_marca_pivot_badie` | sí |
| `CuposVolumen`, `CuposCoberGen`, `CuposCober` | carga manual | **no**, ver §2 |
| `Avance`, `Cober Nueva`, `Multicategoria`, `AvanceR`, … | fórmulas del usuario | no |

Las tres queries traen **todo** lo que hay en la tabla para ese periodo,
sucursal y fuerza de ventas: no filtran artículos ni genéricos. Si un genérico
falta en el informe, falta en `gold`, no lo filtró el reporte.

> **Timing del ETL.** Si el ETL carga un genérico *después* de que corrió el
> avance, ese genérico no aparece hasta la próxima recarga. Pasó con `MULTI CCU`
> el 2026-08-10. Para comprobarlo sin adivinar: agrupar por genérico y mirar
> `MIN(id)`/`MAX(id)` en `gold.cob_preventista_generico` — un bloque de ids muy
> por encima del resto significa "insertado después".

## 2. `skip_cupos` — la carga manual de cupos

Cada mes Nahuel tipea los cupos en el Excel **antes** de que entren a
`gold.fact_cupos`. Mientras están sólo en el Excel, regenerar el reporte los
pisaría. El flag `skip_cupos: true` en `filtros` hace que el servicio se saltee
toda hoja cuyo nombre empiece con `Cupos`.

```
INFO Sheet 'CuposVolumen' skipped (config.skip_cupos=True): preservando contenido previo
```

**Cuándo apagarlo**: cuando los cupos del mes ya estén cargados en `gold`. Si se
deja prendido después de eso, el informe muestra cupos viejos **sin avisar**.

**Regla de oro al recargar**: backup del xlsx primero, y verificar después
celda por celda que las tres hojas `Cupos*` quedaron idénticas.

```python
# tras la recarga, comparar contra el backup
for h in ["CuposVolumen", "CuposCoberGen", "CuposCober"]:
    difs = sum(1 for rn, rb in zip(nuevo[h].iter_rows(), backup[h].iter_rows())
                 for cn, cb in zip(rn, rb) if cn.value != cb.value)
```

## 3. Las 5 capturas

`capture_images` en el config. Todos los rangos son **fijos**; `auto:bordes`
está descartado en las tres hojas (§3.2).

| # | Hoja | Rango | Contenido |
|---|---|---|---|
| 1 | `Avance` | `A1:AR61` | avance por preventista, hoja entera |
| 2 | `Cober Nueva` | `A2:AW55` | Cervezas (bloques 1 y 2 unidos) |
| 3 | `Cober Nueva` | `AY2:BX55` | Aguas + TOTAL AGUAS DANONE |
| 4 | `Cober Nueva` | `CY2:EB55` | Sidras + Pernod + TOTAL MULTI CCU |
| 5 | `Multicategoria` | `A1:Z57` | multicategoría, hoja entera |

Render: ~9,5 min (antes eran 25 imágenes y ~40 min).

### 3.1. Por qué el corte es ése y no otro

`Cober Nueva` tiene **56 columnas ocultas**, y LibreOffice no imprime lo oculto.
El corte sigue lo *visible*, no la estructura lógica de la hoja:

| Bloque | Columnas | Ocultas | Visibles |
|---|---|---|---|
| Cervezas 1 | `A:R` | 0 | 18 |
| Cervezas 2 | `T:AW` | 22 | 8 |
| Aguas | `AY:BX` | 0 | 26 |
| Vinos CCU | `BZ:CW` | **24** | **0** |
| Multi CCU | `CY:EB` | 9 (`DA:DI`) | 21 |

De ahí salen dos decisiones que parecen arbitrarias y no lo son:

- **Cervezas 1 y 2 van juntas en `A2:AW55`.** Las columnas `T` y `U` —el
  Vendedor y Supervisor del bloque 2— están ocultas. Capturado por separado,
  el bloque 2 sale sin identificar de quién es cada fila. Arrancando en `A` se
  lleva las columnas `A`/`B`, que sí son visibles.
- **Vinos CCU por marca NO se captura.** Sus 24 columnas están ocultas a
  propósito (confirmado con Nahuel): capturarlo produce un PNG A4 en blanco.
  Sus totales igual aparecen en la imagen de Multi CCU.

Hay dos tests que sirven de trampa para esto: uno rechaza cualquier rango que
arranque en `BZ`, otro exige que el de Cervezas arranque en `A`.

### 3.2. `auto:bordes` está descartado

Verificado corriendo `RangeRecognizer` contra el workbook real:

- `Avance` → detecta 3 bloques y **pierde el primero** (la banda de GFLORES).
- `Cober Nueva` → 8 bloques irregulares; los bordes están fragmentados.
- `Multicategoria` → devuelve celdas sueltas (`K6:V6`, `M52:M54`…), no la tabla.

### 3.3. Verificar una captura nueva antes de darla por buena

Un rango correcto en el config **no** garantiza una imagen correcta. Siempre
renderizar y revisar el PNG:

```python
from PIL import Image
im = Image.open(png)
vacia = im.convert("L").getextrema()[0] > 250   # A4 en blanco = 2481x3508
```

## 4. La carga diaria

```
excel-reporter-daily.timer   Mon..Sat 07:00, Persistent=true
  └─ ExecStartPre: git checkout main      ← producción SIEMPRE corre main
  └─ scripts/run_daily.py
       └─ avance-badie   (fecha_modo: mes_a_hoy → 1° del mes .. hoy)
```

`Persistent=true` significa que si la máquina estaba apagada a las 07:00, el
timer dispara al encender. Por eso a veces el avance sale a las 08:20.

### 4.1. Dos compuertas antes de entregar

**Compuerta de calendario** — `configs/daily_overrides.json`:

```json
"avance-badie": { "ejecutar": true, "enviar": true, "desde_dia_del_mes": 5 }
```

`desde_dia_del_mes: 5` saltea el servicio los días 1 al 4 de cada mes: es el
margen que Nahuel necesita para cargar los objetivos. Del día 5 en adelante
corre y entrega solo. Un `ejecutar: false` explícito le gana al calendario, y un
valor inválido se ignora con warning (fail-open: un typo no debe apagar un
informe para siempre en silencio).

**Compuerta de RAM** — `RAM_MIN_MB_IMAGENES = 1000` en `run_daily.py`: si a las
07:00 hay menos memoria disponible, se omiten las imágenes, **el xlsx igual sale
por email** y Nahuel recibe un aviso por WhatsApp. Nunca falla en silencio.

**El guard apaga el render, NO toca la entrega.** Saca `capture_images` del
config y nada más. Con `enviar_como="imagen"` y sin imágenes, `SendWhatsAppStep`
no manda nada — que es lo correcto: al grupo le tiene que faltar el informe, no
llegarle otra cosa.

Esa regla salió de pisar el mismo palito dos veces, las dos con el guard
metiéndose con la entrega:

| Fecha | Qué hacía el guard | Qué pasó |
|---|---|---|
| 2026-08-19 | `enviar_whatsapp = False` | Preventa Salta y Nogales, que **solo** tienen WhatsApp, no recibieron nada y nadie se enteró |
| 2026-08-21 | `whatsapp_enviar_como = "archivo"` | al grupo de preventistas le llegó el xlsx de 8,4 MB en vez de las 5 imágenes |

Mandar **otra cosa** es peor que no mandar: parece el informe y no lo es.

### El piso se recalibra cuando cambia el costo del render

| Fecha | Disponible al arrancar | Duración | Resultado |
|---|---|---|---|
| 2026-08-19 | 3918 MB | 567 s | 5/5 |
| 2026-08-19 | 1108 MB | 736 s | 5/5 |
| 2026-08-21 | 1503 MB | ~596 s | 5/5, ~119 s por imagen |

Picos de RSS: `soffice` 1151 MB, Python 2588 MB. Con poca memoria el render
**no muere, se apoya en swap y tarda ~30% más**. Por eso el piso protege contra
un OOM-kill, no contra la lentitud — subirlo no compra seguridad, solo bloquea
envíos que iban a funcionar.

Historial de pisos, cada uno demasiado alto:

- **3000 MB** — medido en julio con 25 imágenes. Al pasar a 5 quedó viejo: el
  2026-08-19 saltó con 2497 MB disponibles.
- **1500 MB** — el 2026-08-21 saltó con **1482 MB**, 18 MB de diferencia. Tres
  horas después el mismo render completó las 5 con 1503 MB.

1000 queda por debajo del mínimo probado (1108 MB) sin llegar a cero.

### 4.2. A quién le llega

| Canal | Destinatarios |
|---|---|
| Email (xlsx) | Dellamea, Farah, Chapur, Guantay, Flores, Alegucci — Nahuel en CC |
| WhatsApp (5 imágenes) | grupo **Preventa Salta** + Alejandro Nogales |

## 5. Recetas

```bash
# recargar a hoy SIN enviar nada (backup primero)
cp -n "data/output/.../AVANCE BADIE - AGOSTO 2026.xlsx" "..._backup_$(date +%Y%m%d).xlsx"
python main.py --config configs/avances_badie.json --no-delivery

# recargar y mandar SOLO por WhatsApp (no duplica el email de las 07:00)
python scripts/run_daily.py --only avance-badie --solo-canal whatsapp

# ver qué haría el daily hoy, sin ejecutar
python scripts/run_daily.py --dry-run
```

**Enviar un xlsx que Nahuel editó a mano**: NO usar `main.py --config`, que
regenera desde la base y le pisa las ediciones. Usar `resolve_delivery` +
`DeliveryPipeline` sobre el archivo existente, con dry-run previo.

**Verificar el destino real** antes de un envío (leer el flag no alcanza):

```python
d = resolve_delivery(rep, contactos,
                     enviar_email=m["enviar_email"],
                     enviar_whatsapp=m["enviar_whatsapp"])   # keywords, no posicional
```

> `resolve_delivery` tiene `enviar_email` como TERCER posicional. Pasarle el
> dict `merged` ahí da un falso "sí se envía", porque `enviar_whatsapp` toma su
> default `True`.

## 6. El PowerPoint del avance

`scripts/avance_pptx.py` arma un deck a partir del xlsx. **Solo lee**: nunca
escribe el libro.

```bash
python scripts/avance_pptx.py \
  --archivo "data/output/avances/2026-07/AVANCE BADIE - JULIO 2026.xlsx" \
  --diagnostico
```

Sin `--salida` escribe el `.pptx` al lado del xlsx, y se niega a pisar uno que ya
exista salvo `--force`.

**29 slides**: portada, después **todo el volumen** y recién después **toda la
cobertura** — nunca intercalados: son dos lecturas distintas y mezclarlas
obliga a saltar de una a otra en la reunión.

Cada sección **abre con sus totales por supervisor**, sacados de la hoja que esa
sección lee: dos slides `TOTALES POR SUPERVISOR` al empezar volumen (una de
`Avance`, otra de `Multicategoria`) y cinco al empezar cobertura, una por cada
corte de marca de `Cober Nueva`.

> Esas filas se **leen** de la banda de resumen del libro, celda por celda. No se
> suman los vendedores ni se recalcula ningún porcentaje: el número de la slide
> es el que está en el Excel. Ojo con la forma de la banda, que **no es igual en
> las tres hojas**: en `Avance` (filas 52-55) el código va en `B` con la columna
> `A` vacía, pero en `Cober Nueva` (filas 51-54) `A` trae un `0` numérico. Por eso
> la búsqueda usa `_filas_resumen(..., exigir_nombre_vacio=True)` para cobertura.
> Sin ese flag la banda no aparece y la sección sale sin su slide de totales.
>
> La fila `TOTAL <código>` al pie de cada slide de detalle es la excepción: esa
> **sí** se calcula, porque totaliza exactamente las filas que tiene encima.

Por cada bloque de supervisor (GFLORES, FGUANTAY, VCHAPUR):

| Slide | Hoja | Contenido |
|---|---|---|
| `VOLUMEN CERVEZAS` | `Avance` | 6 categorías × (Venta, % Cupo, Falta) + TOTAL CERVEZA × 5 |
| `VOLUMEN ADO / MULTI CCU` | `Multicategoria` | va **aparte**, no pegado a cervezas |
| `COBERTURA CERVEZAS 1` | `Cober Nueva` | SALTA, HEINEKEN, IMPERIAL, MILLER |
| `COBERTURA CERVEZAS 2` | `Cober Nueva` | BIECKERT…SALTA CAUTIVA1 + TOTAL CERVEZAS |
| `COBERTURA AGUAS DANONE` | `Cober Nueva` | LEVITE, VILLAVICENCIO, VILLA DEL SUR, BRIO, FULL SPORT + TOTAL |
| `COBERTURA VINOS CCU` | `Cober Nueva` | COLON…SANTA SILVIA + TOTAL |
| `COBERTURA SIDRAS Y LICORES` | `Cober Nueva` | REAL…MISTRAL + TOTAL |

**La cantidad de columnas es la de la hoja**, no una selección: si una categoría
tiene tres columnas, van las tres. CERVEZAS son 10 marcas y no entran legibles
en una diapositiva, así que se abren con el mismo corte que usa la hoja
(Cervezas 1 / Cervezas 2). Las marcas de VINOS y SIDRAS traen tres columnas
porque la hoja no les calcula `Faltan` — el TOTAL de cada genérico sí lo trae.

Formato: venta y cupo sin decimales (son bultos), porcentajes con un decimal,
objetivo de cobertura con uno (en SIDRAS anda por 9,3 y redondearlo lo deja sin
sentido). Un % por encima de 1.000% pierde el decimal: pasa cuando el objetivo
es casi cero (AMSTEL) y con el decimal la celda se parte en dos líneas.

Los bloques se detectan solos: un supervisor es un código de la columna `Super`
cuyos miembros son vendedores. `GFARAH` queda afuera porque sus miembros son
códigos, y `DIRECTA` / `SUB DISTRIBUIDOR` solo aparecen en el resumen porque son
de una fila.

Queda afuera lo que la hoja tiene oculto o roto: `SALTA CAUTIVA1` y `Y:AL` en
`Avance`, `K:V` en `Multicategoria` (además con `#REF!`), PERNOD en `Cober
Nueva`, y la columna `AR` (`Vta. Diaria p/ Cupo`), que es `#DIV/0!` en todas las
filas del libro.

### 6.1. Los totales se suman, no se leen

**Las filas de total del libro no son confiables.** El deck totaliza sumando las
filas que muestra y deriva el % igual que la hoja (`venta / cupo`, `PDV / OBJ`).
Verificado contra JULIO 2026, hay 30 celdas de total desactualizadas repartidas
en tres lugares distintos:

| Dónde | Dice | La suma de sus filas da |
|---|---|---|
| `Avance`, banda de resumen, FGUANTAY (`AM54`) | 22.594,57 | 23.340,65 |
| `Cober Nueva`, total del bloque VCHAPUR (`DS44`) | 23 PDV | 21 PDV |
| `Cober Nueva`, totales de Cervezas 1 (`C17`, `C32`, …) | 1.228 PDV | 1.535 PDV |

La forma de saber cuál gana no es elegir: **el gran total del propio libro cierra
con la suma de las filas, no con esos totales de bloque**. `Cober Nueva!C55`
(GFARAH) da 4.129 y la suma de los 31 vendedores da 4.129; la suma de las filas
de total da 3.557. Lo mismo en `Avance!AM57` = 79.720,68. Las bandas de resumen
(filas 51-54) también coinciden con la suma.

Son rangos de `SUM` que quedaron cortos: el de FGUANTAY nunca creció cuando se
agregó LORENA TARITOLAY. `--diagnostico` lista cada celda donde un total no
cierra con sus propias filas — conviene correrlo cada mes, es la forma barata de
detectar un rango que quedó viejo. Los porcentajes quedan fuera de esa
comparación: un ratio no se suma.

## 7. Historial de trampas ya pisadas

| Fecha | Qué pasó |
|---|---|
| 2026-07-24 | Cupo de cerveza daba 82.574 en las imágenes y 83.000 en el xlsx. `CuposVolumen!Código` (un `id_ruta`) se guardaba con formato de fecha; el round-trip de openpyxl reserializaba y el bug del bisiesto 1900 corría los seriales ≥60 un día, rompiendo el VLOOKUP a `AvanceR`. Fix: `numeric_columns` fuerza formato `"0"` (commit `052b6e2`). |
| 2026-08-10 | `MULTI CCU` faltaba en `cober_gen`. No era el reporte: el ETL lo cargó después de la corrida. |
| 2026-08-17 | Capturas rediseñadas por bloque visible tras descubrir las 56 columnas ocultas. |

**Bug abierto**: `cober_gen!Numero_Clientes` tiene formato de fecha heredado de
la plantilla. Hoy los valores van de 1 a 59 y no se dispara nada, pero es el
mismo mecanismo del bug de julio: al llegar a 60 el valor se corrompe en el
próximo round-trip. Fix de una línea — agregar `numeric_columns=["Numero_Clientes"]`
al `SheetConfig` de `cober_gen`.
