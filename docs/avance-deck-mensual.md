# El deck mensual único — `scripts/avance_deck.py`

Un solo PowerPoint por mes con las cuatro cosas que antes salían por separado:
dos pptx y dos PNG sueltos, cuatro archivos para abrir en la misma reunión.

- Script: `scripts/avance_deck.py` (**solo lee**; no toca ningún xlsx)
- Tests: `tests/test_avance_deck.py`
- Salida por defecto: `data/output/avances/{YYYY-MM}/AVANCE MENSUAL - {MES} {AÑO}.pptx`

```bash
python scripts/avance_deck.py \
  --archivo "data/output/avances/2026-07/AVANCE BADIE - JULIO 2026.xlsx" --force
```

## 1. Qué lleva y en qué orden

| # | Sección | De dónde sale |
|---|---|---|
| 1 | AVANCE BADIE | `avance_pptx.poblar` sobre el libro de BADIE |
| 2 | AVANCE FRATELLI BRANCA | `avance_branca_pptx.poblar` sobre el libro de BRANCA |
| 3 | RECHAZOS | PNG de `data/output/reporte-rebotes/{YYYY-MM}/` |
| 4 | VINOS DANIELITO | PNG de `data/output/vinos-danielito/{YYYY-MM}/` |

Cada avance abre con su portada, que hace de separador de sección.

**Los números no se recalculan acá.** Las dos secciones de avance las arma el
mismo código que arma cada deck por separado, así que una cifra de este deck es
idéntica a la del deck suelto. Las dos últimas son imágenes que ya produjo su
propio informe.

## 2. RECHAZOS va a nivel de deck, no adentro de BRANCA

El deck de BRANCA termina con su propia slide de RECHAZOS, pero el informe de
rebotes es de **todos los preventistas de BADIE** — cervezas, aguas, vinos y
sidras —, no de las líneas de Fratelli Branca. Dejarla ahí archivaría un número
de toda la empresa bajo un proveedor, y saldría repetida en cuanto el deck
agregue la suya.

Por eso `avance_branca_pptx.poblar` se llama con `con_rechazos=False`. El deck
suelto de BRANCA sigue trayéndola: ese flag solo lo baja el deck unificado.

## 3. Todo se busca por CARPETA, nunca por nombre de archivo

Ni el PNG de rebotes ni el de Danielito se pueden elegir por nombre:

- `configs/rebotes.json` tiene el `nombre` escrito a mano, así que **todos** los
  meses salen como "Rebotes Junio 2026".
- El PNG de Danielito lleva el rango capturado (`_A1_O28`), que se mueve con la
  cantidad de filas del mes.

La carpeta de periodo sí es correcta: la deriva `service_output_dir` de la fecha.
Los `backup-*` quedan afuera en los dos casos — son de una corrida vieja del
mismo mes y su fecha de archivo puede ser más nueva que la del PNG vigente.

El libro de BRANCA se busca al lado del de BADIE cambiando la palabra del medio.

Si falta una pieza, se pierde **esa** diapositiva y se avisa por consola; el deck
sale igual.

## 4. Danielito va con `--hasta`

El informe de Danielito no tiene tope superior: llega hasta el último dato
cargado en la base. Para un deck de un mes ya cerrado eso mete el mes siguiente
a medio andar, y un JULIO con tres días de AGOSTO se lee como una caída de la
venta. Antes de armar el deck de un mes cerrado:

```bash
python scripts/vinos_danielito.py --periodo 2026-07 --hasta 2026-07-31 --force
```

El tope va a las **tres** consultas de ventas (volumen, cobertura mensual y
cobertura anual) o a ninguna: topar solo el volumen dejaría un cliente contado
en un mes cuyos bultos no están en el mismo cuadro.

## 5. La primera corrida del mes tarda

`AvancesService` escribe los libros con openpyxl, que descarta los valores
cacheados de las fórmulas. Cuando el libro de BRANCA no los trae, el script
recalcula una **copia** con LibreOffice (el original no se toca) y eso son varios
minutos con un xlsx de 7 MB. Lo avisa por consola.

## 6. Verificar un cambio

Los tests no alcanzan: el deck puede pasar en verde y salir con las columnas
corridas. Generar y **mirar**:

```bash
./venv/bin/python -m pytest tests/test_avance_deck.py tests/test_avance_pptx.py \
    tests/test_avance_branca_pptx.py -q

./venv/bin/python scripts/avance_deck.py \
  --archivo 'data/output/avances/2026-07/AVANCE BADIE - JULIO 2026.xlsx' \
  --salida /tmp/julio.pptx --force

soffice --headless --convert-to pdf --outdir /tmp /tmp/julio.pptx
pdftoppm -r 110 -png /tmp/julio.pdf /tmp/slide
```
