# Avances — reglas para cualquier sesión

**Leer esto ANTES de tocar un avance.** Los tres avances (badie, branca, guemes)
son el informe más delicado del sistema y ya se rompieron de las mismas cuatro
formas varias veces. Cada regla de acá salió de un incidente real.

Detalle por informe: `docs/avance-badie.md`, `docs/avance-fratelli-branca.md`.

---

## 1. Los rangos de captura NO son estables entre meses

**El error más caro y el más repetido.** Un rango que funcionó el mes pasado
puede salir mal este mes, porque el libro cambia: se va un preventista, se
agrega una columna, se ocultan otras.

| Fecha | Qué pasó |
|---|---|
| 2026-08-17 | `Cober Nueva` de badie tenía 56 columnas ocultas: dos de las siete capturas salían en blanco o sin identificar |
| 2026-09-01 | branca perdió a GONZALO LOPEZ y LUCIANO GUZMAN. El rango `B2:AX35` quedó viejo: arrancaba en `B` y perdía la columna de categorías, y llegaba hasta `AX` arrastrando una columna de basura (`AU14:AU22`) |

Dos reglas que se derivan:

- **El rango arranca en la columna de la ETIQUETA**, no en la primera con
  números. Sin la etiqueta la imagen es una grilla de números y nadie sabe qué
  fila es cuál. En branca es `A` (Categoria); en badie `A` (Vendedor).
- **El rango termina en la última columna VISIBLE con datos.** Ni antes (se
  pierde un total) ni después (entra basura o franjas vacías).

**LibreOffice no imprime lo oculto.** Por eso el corte sigue lo *visible*, no la
estructura lógica de la hoja. Un bloque entero de columnas ocultas produce un
PNG en blanco tamaño A4 (2481x3508).

### Cómo verificar un rango antes de darlo por bueno

Un rango correcto en el config **no** garantiza una imagen correcta. Siempre,
sin excepción:

```python
# 1. mapear el libro: donde estan las etiquetas y hasta donde llegan los datos
import openpyxl
from openpyxl.utils import get_column_letter as gcl, column_index_from_string as cidx
ws = openpyxl.load_workbook(ruta, data_only=True)["AVANCE"]
ocultas = {gcl(i) for k, d in ws.column_dimensions.items() if d.hidden
           for i in range(d.min, d.max + 1)}

# 2. renderizar
# 3. MIRAR el PNG, no solo comprobar que exista
from PIL import Image
im = Image.open(png)
vacia = im.convert("L").getextrema()[0] > 250
```

El paso 3 es leer la imagen de verdad. "El render terminó sin error" no dice
nada sobre si el recorte está bien.

## 2. Nunca regenerar para mandar

Los libros de avance los mantiene Nahuel a mano y el servicio los actualiza
**in-place**. `main.py <tipo> --config` los regenera desde la base y **pisa sus
ediciones**.

Si el archivo ya existe y solo hay que entregarlo:

```python
resolve_delivery(report, contactos,
                 enviar_email=False,      # keywords SIEMPRE
                 enviar_whatsapp=True)
DeliveryPipeline([SendWhatsAppStep()]).run(artifact, delivery)
```

> `resolve_delivery` tiene `enviar_email` como TERCER posicional. Pasarle el
> dict `merged` ahí da un falso "sí se envía", porque `enviar_whatsapp` toma su
> default `True`.

Para reenviar en masa lo que falló: `scripts/reenviar_fallidos.py` (dry-run por
defecto). Toma los archivos que ya están en disco y no regenera nada.

Y si hay que recargar de verdad: **backup primero**, y después comparar celda
por celda las hojas `Cupos*` contra el backup (§2 de `docs/avance-badie.md`).

## 3. Dry-run antes de cada envío, y mirar los destinos

El envío va a grupos de preventistas reales. Antes de mandar, imprimir y leer:

- cuántas imágenes y cuáles
- `email: SI/no`
- los destinos de WhatsApp, resueltos

Si Nahuel pide "pasámelo a mí", **mandar solo a él** — no al grupo. El config
lista los dos; hay que filtrar `enviar_a`.

Un envío hecho a mano **no** queda registrado en el log de envíos, así que sigue
figurando en `error`. Por eso `reenviar_fallidos.py` tiene `--excluir`: sin eso
se duplica al grupo.

## 4. El primer día hábil del mes es el CIERRE

`rango_mes_a_hoy()` devuelve **el mes anterior cerrado** exactamente el primer
día hábil, y el mes en curso cualquier otro día. Es la única corrida que tiene
el mes completo: la del 31 a la mañana todavía no tiene el último día.

Por eso la compuerta `desde_dia_del_mes` **exceptúa el primer día hábil**. Sin
esa excepción el cierre no existe: el 2026-09-01 los tres avances se saltearon
con `dia 1 < 5` y para el día 5 la ventana ya era el mes nuevo.

Al tocar esa compuerta, no atarla al día 1 del calendario: un mes que arranca
domingo no correría nunca.

## 5. Vocabulario de Nahuel

Interpretarlo mal ya costó dos incidentes:

| Dice | Significa |
|---|---|
| "pararlo" | `ejecutar: false` — el servicio entero, no solo la entrega |
| "los avances" | los **tres**: badie, branca y guemes |
| "el cierre" | la corrida del primer día hábil, con el mes anterior completo |

## 6. Antes de decir que algo salió

Que el pipeline diga `success` no alcanza. Verificar en este orden:

1. `curl -s localhost:3001/status` — si `connected:false` con el proceso vivo,
   la sesión de WhatsApp murió y **todo envío va a fallar con 503**.
2. El PNG: abrirlo y mirarlo.
3. `python main.py check-delivery` — estado real de los envíos del día.

El 2026-08-22 la corrida generó todo bien y 132 errores 503 dejaron 15 envíos
sin salir. El 2026-08-21 el grupo recibió el xlsx en vez de las imágenes y el
log decía `success`.
