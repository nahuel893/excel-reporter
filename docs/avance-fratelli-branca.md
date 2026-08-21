# AVANCE FRATELLI BRANCA — el PowerPoint

Deck mensual armado desde el xlsx del avance de Fratelli Branca (el que el
sistema llama "branca").

- Script: `scripts/avance_branca_pptx.py` (**solo lee** el libro)
- Libro: `data/output/avances/{YYYY-MM}/AVANCE BRANCA - {MES} {AÑO}.xlsx`
- Config del reporte: `configs/avances_branca.json`
- Tests: `tests/test_avance_branca_pptx.py`

```bash
python scripts/avance_branca_pptx.py \
  --archivo "data/output/avances/2026-07/AVANCE BRANCA - JULIO 2026.xlsx" \
  --diagnostico
```

## 1. La hoja está transpuesta

En BADIE las filas son vendedores y las columnas categorías. Acá es al revés:
**las filas son categorías/marcas y las columnas son vendedores**, tres por
vendedor (`Avance`, `%Tend`, `Faltan`). Por eso es un script aparte y no una
opción del de BADIE. El look and feel se importa de `avance_pptx`, así que los
dos decks se ven igual.

**6 diapositivas**: portada, `VOLUMEN — LINEA BRANCA`, `VOLUMEN — OTRAS LINEAS`,
`COBERTURA — LINEA BRANCA`, `COBERTURA — OTRAS LINEAS` y `RECHAZOS`. Primero
todo el volumen, después toda la cobertura.

Los nombres de vendedor se leen de la fila 5, no están escritos en el código: si
cambia un preventista, el deck lo toma solo.

Queda afuera lo que la hoja tiene oculto: `DIRECTA VINOS` (`AE:AG` en `AVANCE`,
`AI:AL` en `Cobertura`), `Factura Presupuesto` (`AV:BE`), `GABRIELA BARAKAT`
(`W:Z` en `Cobertura`) y **todas** las columnas de `%` y `Faltan` de la hoja
`Cobertura` — ahí solo queda visible el PDV por vendedor.

> `DIRECTA VINOS` está oculto pero **sí** entra en la columna `GFARAH`. Las
> columnas visibles no cierran contra ese total, y no es un error del deck: es
> la decisión de la hoja.

## 2. El libro casi nunca trae valores

`AvancesService` escribe el xlsx con openpyxl, que **descarta todos los valores
cacheados de las fórmulas**. Salvo que alguien lo haya abierto y guardado a
mano, `data_only=True` devuelve `None` en toda la hoja.

Cuando eso pasa, el script recalcula una **copia** con LibreOffice y lee esa. El
original no se toca nunca. Lo avisa por consola:

```
El libro no traia valores cacheados: se recalculo una copia con LibreOffice.
```

Si LibreOffice no está instalado, falla con un mensaje claro en vez de sacar un
deck lleno de guiones.

## 3. El total de cobertura NO se suma

Esta es la diferencia importante contra el deck de BADIE:

| | Total |
|---|---|
| Volumen (`AVANCE`) | **se calcula**: suma de las filas mostradas, `%` = Avance / (Avance + Faltan) |
| Cobertura (`Cobertura`) | **se lee de la hoja**, verbatim |

La cobertura cuenta puntos de venta, y un cliente que compra FERNET y CARPANO es
**un** PDV, no dos: no es aditiva entre marcas. En JULIO 2026 el `TOTAL LINEA` de
PABLO NAVARRO es 201 mientras que sus catorce filas de marca suman 352 — sumarlas
infla el número un 75%.

Por eso `--diagnostico` corre **solo sobre volumen**. En cobertura compararía
contra una suma que no debe cerrar y avisaría en todas las celdas.

`OTRAS LINEAS` sale **sin fila de total** a propósito: `TAMBO` se mide en KG y
el resto en bultos, y sumarlos daría un número que no significa nada. Va aclarado
en el subtítulo de la diapositiva.

## 4. La imagen de rechazos

La última diapositiva es el PNG de rebotes del mes, insertado como imagen.

Se lo busca **por carpeta, nunca por nombre**: `configs/rebotes.json` tiene el
`nombre` escrito a mano (`"Rebotes Junio 2026"`), así que todos los meses salen
con el mismo nombre de archivo. La carpeta sí es correcta —
`service_output_dir()` la deriva de `fecha_desde`.

```
data/output/reporte-rebotes/2026-07/Rebotes Junio 2026_%_Rebotes_x_Generico...png
                            ^^^^^^^ julio, aunque diga "Junio"
```

Que la carpeta `2026-07` tenga el mes de julio completo sale de
`rango_mes_a_hoy()`: **el primer día hábil del mes se manda el mes anterior
cerrado**. El daily del 1 de agosto pidió 2026-07-01..2026-07-31.

Con `--rechazos <ruta>` se le pasa otra imagen a mano.

**Pendiente**: el `nombre` fijo de `configs/rebotes.json` es el mismo bug que
tenía el asunto del mail de avance-badie. Se arregla con los placeholders
`{MES}` `{AÑO}`, que `_resolver_nombre_periodo` (main.py) ya resuelve.
