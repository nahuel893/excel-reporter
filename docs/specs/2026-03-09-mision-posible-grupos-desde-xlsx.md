# Spec: Mision Posible - Definicion de Grupos desde XLSX

> **Estado:** IMPLEMENTADA
> **Fecha:** 2026-03-09
> **Autor:** nahuel

## 1. Objetivo

Permitir que los grupos del reporte Mision Posible se definan automaticamente leyendo un archivo XLSX donde cada valor unico de la columna `CATEGORIA` se convierte en un `GrupoArticulos`, filtrando la cobertura por los `id_articulo` especificos listados en ese XLSX en lugar de por marca completa.

## 2. Contexto

El sistema actual define los grupos en `config_mision_posible.json` manualmente con el campo `grupos`: cada entrada especifica `nombre`, `marcas` y opcionalmente `filtro_descripcion`. El filtro SQL resultante es `da.marca IN (...)`, que incluye todos los articulos de esas marcas en la BD.

El negocio necesita definir grupos de articulos especificos (por `id_articulo`) que no coinciden exactamente con los limites de una marca o un filtro de descripcion. Por ejemplo: "LEVITE - VILLAVICENCIO - FORMATO CHICO" incluye 29 articulos concretos de dos marcas; "CONVIVENCIA 330" incluye 13 articulos de tres marcas (HEINEKEN, IMPERIAL, MILLER) pero no todos los articulos de esas marcas.

El mecanismo propuesto es un XLSX entregado por el equipo de negocio que lista exactamente los articulos por categoria. El sistema lee ese XLSX y genera los grupos automaticamente. Este enfoque elimina la necesidad de calcular filtros de descripcion manualmente y garantiza que solo los articulos correctos entren en cada calculo de cobertura.

### Estado actual del sistema

El `GrupoArticulos` actual tiene:
```python
@dataclass
class GrupoArticulos:
    nombre: str
    marcas: list[str]
    filtro_descripcion: str | None = None
    requiere_todas_marcas: bool = False
```

El metodo `get_cobertura_custom` filtra con `da.marca IN (...)` y opcionalmente `da.des_articulo ILIKE :filtro`. Ambos usan la tabla `dim_articulo` (via JOIN ya presente en la query). El cambio propuesto reemplaza la clausula `da.marca IN (...)` por `fv.id_articulo IN (...)` cuando el grupo proviene de un XLSX.

### Decision de arquitectura: extension vs nuevo metodo

Se elige **extender `get_cobertura_custom`** agregando un parametro opcional `articulos_ids: list[int] | None = None`. Cuando se provee `articulos_ids`, se usa `fv.id_articulo IN (...)` como filtro principal en lugar de `da.marca IN (...)`. El JOIN a `dim_articulo` se conserva para la logica de `requiere_todas_marcas` (que agrupa por `da.marca`). Esta decision mantiene la coherencia del modelo: un metodo de cobertura custom con diferentes modos de filtrado, en lugar de proliferar metodos similares.

## 3. Requisitos Funcionales

### 3.1 Formato del XLSX de entrada

- **RF-001**: Cuando el sistema lee el archivo XLSX, debe esperar exactamente las columnas `CODIGO`, `ARTICULO`, `MARCA` y `CATEGORIA` (puede haber otras columnas que se ignoran). Si alguna de estas cuatro columnas esta ausente, el sistema debe lanzar `ValueError` descriptivo indicando la columna faltante y no generar el reporte.

- **RF-002**: Cuando el sistema lee la columna `CODIGO`, debe tratarla como entero (mapea a `id_articulo` en `fact_ventas` y `dim_articulo`). Si una fila tiene un `CODIGO` no convertible a entero, debe ignorarla con un warning impreso en stdout.

- **RF-003**: Cuando el sistema agrupa el XLSX por `CATEGORIA`, cada valor unico de `CATEGORIA` se convierte en un `GrupoArticulos` con:
  - `nombre` = valor de `CATEGORIA`
  - `marcas` = lista deduplicada y ordenada de valores de `MARCA` para esa categoria
  - `articulos` = diccionario `{int(CODIGO): str(MARCA)}` para esa categoria (deduplicado por `CODIGO`)
  - `requiere_todas_marcas` = valor del campo global `requiere_todas_marcas` del JSON de config

- **RF-004**: Cuando el mismo `CODIGO` aparece mas de una vez en la misma `CATEGORIA`, el sistema debe conservar solo la primera ocurrencia (la que aparece primero en el archivo XLSX). No se lanza error por duplicados.

- **RF-005**: Cuando el XLSX esta vacio o no contiene filas con datos (excluyendo encabezado), el sistema debe lanzar `ValueError` descriptivo y no generar el reporte.

### 3.2 Config JSON con `archivo_articulos`

- **RF-006**: Cuando el JSON de config contiene tanto `archivo_articulos` como `grupos`, el sistema debe combinar ambos: primero los grupos manuales del JSON y luego los grupos generados desde el XLSX. El resultado es una lista unica de `GrupoArticulos` que se procesa normalmente.

- **RF-007**: Cuando el JSON de config contiene solo `grupos` (sin `archivo_articulos`), el sistema debe comportarse exactamente como hoy. Cuando contiene solo `archivo_articulos` (sin `grupos`), los grupos se generan exclusivamente desde el XLSX. Ambos campos son opcionales pero al menos uno debe estar presente.

- **RF-008**: Cuando `archivo_articulos` esta presente y el archivo no existe en la ruta especificada, el sistema debe lanzar `ValueError` descriptivo con la ruta intentada y no generar el reporte.

- **RF-009**: Cuando `archivo_articulos` esta presente, el campo global `requiere_todas_marcas` del JSON (booleano, default `False`) se aplica a todos los grupos generados desde el XLSX. No existe `requiere_todas_marcas` por grupo en este modo.

- **RF-010**: Cuando `archivo_articulos` genera grupos, los `objetivos` del JSON se asocian a los grupos por `nombre` (valor de `CATEGORIA`). Si una `CATEGORIA` no tiene entrada en `objetivos`, el grupo tiene objetivo `None` (comportamiento existente).

### 3.3 Nuevo campo `articulos` en `GrupoArticulos`

- **RF-011**: Cuando el dataclass `GrupoArticulos` se construye con el campo `articulos` (tipo `dict[int, str] | None`), el sistema debe aceptarlo como campo opcional con default `None`. Un grupo con `articulos != None` se llama "grupo por articulos"; un grupo con `articulos is None` es un "grupo por marcas" (comportamiento actual).

- **RF-012**: Cuando `GrupoArticulos` tiene `articulos != None` y `marcas` es una lista vacia, el sistema debe permitirlo (en grupos por articulos, `marcas` se usa solo para mostrar info y para `requiere_todas_marcas`; puede derivarse del dict de articulos). La validacion del `__post_init__` actual (`if not self.marcas: raise ValueError`) debe relajarse para grupos por articulos.

- **RF-013**: Cuando `_es_grupo_simple` evalua un grupo con `articulos != None`, debe retornar siempre `False` (los grupos por articulos siempre usan `get_cobertura_custom`).

### 3.4 Extension de `get_cobertura_custom`

- **RF-014**: Cuando `get_cobertura_custom` recibe `articulos_ids: list[int]` (lista no vacia), el sistema debe usar `fv.id_articulo IN (:art_0, :art_1, ...)` como filtro principal en lugar de `da.marca IN (...)`. El JOIN a `dim_articulo` se conserva para que `da.marca` este disponible en la logica de `requiere_todas_marcas`.

- **RF-015**: Cuando `get_cobertura_custom` recibe tanto `articulos_ids` como `requiere_todas_marcas=True`, el sistema debe aplicar el criterio de todas-las-marcas usando `UPPER(da.marca)` en el SQL (en lugar de `da.marca` sin normalizar) para el GROUP BY y COUNT(DISTINCT). Esto garantiza que las marcas en el SQL se comparen en UPPER sin importar el case en la BD. El parametro `:num_marcas` se calcula a partir de `len(marcas_upper)` donde `marcas_upper` son las marcas del caller normalizadas a UPPER. La funcion `_cargar_grupos_desde_xlsx` debe normalizar la columna `MARCA` a UPPER al construir `grupo.marcas`, asegurando coincidencia con `UPPER(da.marca)` del SQL.

- **RF-016**: Cuando `get_cobertura_custom` recibe `articulos_ids`, el parametro `filtro_descripcion` debe seguir siendo aceptado y aplicado adicionalmente (por si se combina). Si `articulos_ids` esta presente, `filtro_descripcion` es redundante pero no debe causar error.

- **RF-017**: Cuando `get_cobertura_custom` recibe `articulos_ids` vacia (`[]`), debe lanzar `ValueError` descriptivo.

- **RF-018**: Cuando `get_cobertura_custom` recibe `articulos_ids=None` (default), el comportamiento es identico al actual: filtra por `da.marca IN (...)`.

### 3.5 Orquestacion en el servicio

- **RF-019**: Cuando `_fetch_data_grupo` procesa un grupo con `articulos != None`, debe llamar a `get_cobertura_custom` pasando `articulos_ids=list(grupo.articulos.keys())` en lugar de `marcas=grupo.marcas`. El campo `marcas` del grupo sigue pasandose para que `requiere_todas_marcas` funcione correctamente.

- **RF-020**: Cuando `_fetch_data_grupo` procesa un grupo con `articulos is None`, el comportamiento es identico al actual (sin cambios).

### 3.6 Parseo en `main.py`

- **RF-021**: Cuando `cmd_mision_posible` lee un JSON con `archivo_articulos`, debe:
  1. Resolver la ruta del XLSX (relativa al directorio de trabajo del proceso).
  2. Leer el XLSX con `pandas.read_excel`.
  3. Validar columnas requeridas (`CODIGO`, `ARTICULO`, `MARCA`, `CATEGORIA`).
  4. Agrupar por `CATEGORIA` y construir una lista de `GrupoArticulos` con el campo `articulos` poblado.
  5. Asignar `requiere_todas_marcas` global a todos los grupos generados.
  6. Continuar el flujo normal con `MisionPosibleConfig(grupos=grupos_generados, ...)`.

- **RF-022**: Cuando `cmd_mision_posible` lee un JSON sin `archivo_articulos`, el comportamiento es identico al actual.

### 3.7 API REST

- **RF-023**: Cuando el endpoint `POST /mision-posible/reporte` recibe un request, el campo `grupos[].articulos` debe ser aceptado en el schema Pydantic como `Optional[dict[str, str]]` (JSON no soporta claves enteras, por lo que el CODIGO llega como string clave y la marca como string valor). El sistema convierte las claves a `int` al construir `GrupoArticulos` en `_build_config`.

- **RF-024**: Cuando `grupos[].articulos` esta presente en el request de la API, `_build_config` debe construir el `GrupoArticulos` con `articulos={int(k): v for k, v in g.articulos.items()}`. Si alguna clave no es convertible a int, debe lanzar `HTTPException(400)`.

- **RF-025**: La API NO soporta `archivo_articulos` como campo de request; la lectura del XLSX es responsabilidad exclusiva del CLI. La API acepta los grupos ya parseados con el campo `articulos` por grupo.

## 4. Requisitos No Funcionales

- **RNF-001**: Cuando el numero de `articulos_ids` es mayor a 1000, el sistema debe emitir un warning en stdout indicando el numero de IDs en el IN clause, dado que queries muy largas pueden impactar el planner de PostgreSQL. No se debe cortar la lista ni fallar.

- **RNF-002**: El tiempo de ejecucion de `get_cobertura_custom` con `articulos_ids` de hasta 100 elementos y todas las sucursales no debe superar 60 segundos con conexion normal a la BD. El `IN` sobre `fv.id_articulo` es directo sobre la tabla de hechos y deberia ser mas eficiente que el JOIN a `dim_articulo` para el filtro de marca.

- **RNF-003**: El XLSX se lee una sola vez por ejecucion del CLI, al momento de parsear la config. No se relee por grupo ni por supervisor.

- **RNF-004**: La lectura del XLSX con pandas debe usar `dtype={"CODIGO": "Int64"}` para evitar que numeros enteros sean leidos como float (lo que causaria `id_articulo = 1234.0` en lugar de `1234`).

- **RNF-005**: Si `get_cobertura_custom` falla para un grupo por articulos, el servicio debe capturar la excepcion, registrar el error, generar tablas vacias y continuar. Igual que en el comportamiento actual (RNF-003 de la spec grupos-articulos).

- **RNF-006**: Los `articulos_ids` en el SQL deben usar parametros enlazados (`:art_0`, `:art_1`, ...) en lugar de interpolacion directa.

## 5. Diseno Tecnico

### 5.1 Modelo de Datos

Sin cambios en tablas de la BD. El XLSX es un archivo de entrada externo, no persistido en la BD.

**Cambio en el dataclass Python:**

```python
@dataclass
class GrupoArticulos:
    nombre: str
    marcas: list[str]
    filtro_descripcion: str | None = None
    requiere_todas_marcas: bool = False
    articulos: dict[int, str] | None = None  # {id_articulo: marca} desde XLSX

    def __post_init__(self):
        if not self.marcas and self.articulos is None:
            # Solo error si no hay ni marcas ni articulos
            raise ValueError(f"GrupoArticulos '{self.nombre}': marcas no puede estar vacia.")
```

El campo `articulos` es un diccionario que mapea `id_articulo` (int) a `marca` (str). La marca viene del XLSX (columna `MARCA`) y se usa para derivar `marcas` y para informar al caller sobre las marcas del grupo. No se usa directamente en el SQL (el SQL usa `da.marca` del JOIN a `dim_articulo`).

### 5.2 Nueva firma de `get_cobertura_custom`

```python
def get_cobertura_custom(
    self,
    periodo: str,
    marcas: list[str],
    filtro_descripcion: str | None = None,
    requiere_todas_marcas: bool = False,
    articulos_ids: list[int] | None = None,
) -> pd.DataFrame:
    """
    Calcula cobertura desde fact_ventas para un grupo de marcas o articulos especificos.

    Args:
        periodo: Primer dia del mes, formato 'YYYY-MM-DD'.
        marcas: Lista de marcas en dim_articulo. Requerido si articulos_ids es None.
                Cuando articulos_ids esta presente, marcas se usa solo para calcular
                num_marcas en la logica requiere_todas_marcas.
        filtro_descripcion: Substring ILIKE sobre des_articulo. Opcional.
        requiere_todas_marcas: Si True, cuenta solo clientes con compra en CADA marca.
        articulos_ids: Lista de id_articulo especificos. Si se provee, filtra por
                       fv.id_articulo IN (...) en lugar de da.marca IN (...).
                       Si es lista vacia, lanza ValueError.

    Returns:
        DataFrame con columnas:
            periodo, id_fuerza_ventas, id_sucursal, sucursal,
            vendedor, id_ruta, clientes_compradores, volumen_total
    """
```

### 5.3 SQL: modo `articulos_ids` (nuevo)

Cuando `articulos_ids` no es `None`, el filtro de marcas se reemplaza:

```sql
-- ANTES (modo por marcas):
AND da.marca IN (:marca_0, :marca_1, ...)

-- DESPUES (modo por articulos):
AND fv.id_articulo IN (:art_0, :art_1, ...)
```

El JOIN a `dim_articulo` se conserva para ambos modos porque:
- `requiere_todas_marcas=True` necesita `da.marca` para el GROUP BY del CTE `cliente_marca`.
- `filtro_descripcion` necesita `da.des_articulo`.

Estructura completa del CTE para el modo `articulos_ids` con `requiere_todas_marcas=False`:

```sql
WITH vendedor_cliente AS (
    -- Rama FV1
    SELECT
        DATE_TRUNC('month', fv.fecha_comprobante)::date AS periodo,
        1                                               AS id_fuerza_ventas,
        dc.des_personal_fv1                             AS vendedor,
        dc.id_ruta_fv1                                  AS id_ruta,
        fv.id_sucursal,
        ds.descripcion                                  AS sucursal,
        fv.id_cliente,
        SUM(fv.cantidades_total)                        AS total_qty
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_cliente  dc ON fv.id_cliente  = dc.id_cliente
                                  AND fv.id_sucursal = dc.id_sucursal
    LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal  = ds.id_sucursal
    LEFT JOIN gold.dim_articulo da ON fv.id_articulo  = da.id_articulo
    WHERE dc.des_personal_fv1 IS NOT NULL
      AND fv.id_articulo IN (:art_0, :art_1, ...)       -- CAMBIO: filtro por id_articulo
      -- condicional: AND da.des_articulo ILIKE :filtro
      AND DATE_TRUNC('month', fv.fecha_comprobante) = :periodo
    GROUP BY 1, 2, 3, 4, 5, 6, fv.id_cliente
    HAVING SUM(fv.cantidades_total) > 0

    UNION ALL

    -- Rama FV4 (estructura identica)
    ...
)
SELECT
    vc.periodo,
    vc.id_fuerza_ventas,
    vc.id_sucursal,
    vc.sucursal,
    vc.vendedor,
    vc.id_ruta,
    COUNT(DISTINCT vc.id_cliente) AS clientes_compradores,
    SUM(vc.total_qty)             AS volumen_total
FROM vendedor_cliente vc
GROUP BY vc.periodo, vc.id_fuerza_ventas, vc.id_sucursal, vc.sucursal,
         vc.vendedor, vc.id_ruta
ORDER BY vc.sucursal, vc.vendedor
```

Para el modo `articulos_ids` con `requiere_todas_marcas=True`, la estructura `cliente_marca` usa el mismo filtro `fv.id_articulo IN (...)` pero agrega `da.marca` al GROUP BY (identico al modo por marcas salvo por la clausula de filtro):

```sql
WITH cliente_marca AS (
    SELECT
        ...,
        UPPER(da.marca) AS marca,
        SUM(fv.cantidades_total) AS total_qty
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
    ...
    WHERE ...
      AND fv.id_articulo IN (:art_0, ...)    -- filtro por articulos
      ...
    GROUP BY ..., UPPER(da.marca)
    HAVING SUM(fv.cantidades_total) > 0
    ...
),
cliente_valido AS (
    ...
    HAVING COUNT(DISTINCT marca) = :num_marcas
)
SELECT ...
```

### 5.4 Logica de seleccion del filtro en Python

```python
# En get_cobertura_custom, validaciones iniciales:
# La validacion 'if not marcas: raise ValueError' se relaja:
# solo aplica cuando articulos_ids es None (modo por marcas)
if not marcas and articulos_ids is None:
    raise ValueError("marcas no puede estar vacia.")

if articulos_ids is not None:
    if not articulos_ids:
        raise ValueError("articulos_ids no puede estar vacia.")
    art_params = {f"art_{i}": aid for i, aid in enumerate(articulos_ids)}
    art_placeholders = ", ".join(f":art_{i}" for i in range(len(articulos_ids)))
    filtro_principal_clause = f"AND fv.id_articulo IN ({art_placeholders})"
    params.update(art_params)
else:
    # modo existente: filtro por marca
    marcas_upper = [m.upper() for m in marcas]
    marcas_upper = list(dict.fromkeys(marcas_upper))
    marca_params = {f"marca_{i}": m for i, m in enumerate(marcas_upper)}
    marca_placeholders = ", ".join(f":marca_{i}" for i in range(len(marcas_upper)))
    filtro_principal_clause = f"AND da.marca IN ({marca_placeholders})"
    params.update(marca_params)
```

La variable `filtro_principal_clause` reemplaza `filtro_marca_clause` en los templates de query `_build_query_default` y `_build_query_todas_marcas`.

### 5.5 Parseo del XLSX en `main.py`

```python
import pandas as pd

def _cargar_grupos_desde_xlsx(
    ruta_xlsx: str,
    requiere_todas_marcas: bool = False,
) -> list[GrupoArticulos]:
    """Lee el XLSX y construye GrupoArticulos por CATEGORIA."""
    path = Path(ruta_xlsx)
    if not path.exists():
        raise ValueError(f"Archivo no encontrado: {path}")

    df = pd.read_excel(path, dtype={"CODIGO": "Int64"})

    columnas_requeridas = {"CODIGO", "ARTICULO", "MARCA", "CATEGORIA"}
    faltantes = columnas_requeridas - set(df.columns)
    if faltantes:
        raise ValueError(f"Columnas faltantes en el XLSX: {faltantes}")

    if df.empty:
        raise ValueError("El XLSX no contiene filas de datos.")

    grupos = []
    for categoria, grupo_df in df.groupby("CATEGORIA", sort=False):
        # Deduplicar por CODIGO, conservar primera ocurrencia
        grupo_df = grupo_df.drop_duplicates(subset=["CODIGO"])
        # Filtrar filas con CODIGO invalido
        grupo_df = grupo_df.dropna(subset=["CODIGO"])
        if grupo_df.empty:
            print(f"⚠ Categoria '{categoria}' omitida: no tiene articulos validos.")
            continue

        articulos = {int(row["CODIGO"]): str(row["MARCA"]).upper() for _, row in grupo_df.iterrows()}
        marcas = list(dict.fromkeys(str(m).upper() for m in grupo_df["MARCA"]))  # dedup, UPPER, orden

        grupos.append(GrupoArticulos(
            nombre=str(categoria),
            marcas=marcas,
            articulos=articulos,
            requiere_todas_marcas=requiere_todas_marcas,
        ))

    return grupos
```

Esta funcion se llama desde `cmd_mision_posible` cuando `cfg.get("archivo_articulos")` no es `None`.

### 5.6 Arquitectura - archivos afectados

```
src/
  core/
    data_loader.py          MODIFICADO: +parametro articulos_ids en get_cobertura_custom
                                        logica de seleccion de filtro principal
  services/
    mision_posible/
      service.py            MODIFICADO: +campo articulos en GrupoArticulos
                                        __post_init__ relajado para grupos por articulos
                                        _es_grupo_simple: retorna False si articulos != None
                                        _fetch_data_grupo: pasa articulos_ids si corresponde
src/
  api/
    routes/
      mision_posible.py     MODIFICADO: +campo articulos en GrupoArticulosSchema
                                        _build_config: convierte claves string a int
main.py                     MODIFICADO: _cargar_grupos_desde_xlsx() nueva funcion
                                        cmd_mision_posible: rama archivo_articulos
tests/
  test_mision_posible.py    MODIFICADO: tests nuevos para grupos por articulos
```

Archivos NO afectados: `processor.py`, `ExcelWriter`, `zonas.py`, `base_service.py`, hojas Excel, `config_mision_posible.json` (el archivo existente sigue funcionando).

### 5.7 Config JSON actualizada (ejemplo)

```json
{
    "periodo": "2026-03-01",
    "grupos": [
        {"nombre": "IMPERIAL", "marcas": ["IMPERIAL"]},
        {"nombre": "LEVITE", "marcas": ["LEVITE"]}
    ],
    "archivo_articulos": "data/input/articulos-mision-posible.xlsx",
    "requiere_todas_marcas": true,
    "objetivos": {
        "IMPERIAL": 5245,
        "LEVITE": 5256,
        "LEVITE - VILLAVICENCIO - FORMATO CHICO": 5000,
        "HEINEKEN SIN ALCOHOL": 1000,
        "CONVIVENCIA 330": 2000
    },
    "porcentajes_sucursal": {
        "CASA CENTRAL": 6.67,
        "VALLE SALTA": 6.67,
        "SUCURSAL CAFAYATE": 6.67,
        "SUCURSAL ABRA PAMPA": 6.67,
        "SUCURSAL PERICO": 6.67
    },
    "nombre_archivo": null,
    "supervisores": null
}
```

Cuando ambos `archivo_articulos` y `grupos` estan presentes, se combinan: primero los grupos manuales del JSON, luego los generados desde el XLSX. Si solo hay uno de los dos, se usa ese.

### 5.8 Schema Pydantic actualizado

```python
class GrupoArticulosSchema(BaseModel):
    nombre: str = Field(..., description="Nombre de display del grupo")
    marcas: list[str] = Field(default_factory=list, description="Marcas en dim_articulo. Requerido si articulos es None.")
    filtro_descripcion: Optional[str] = Field(None, description="Substring ILIKE sobre des_articulo")
    requiere_todas_marcas: bool = Field(False, description="Si True, el cliente debe comprar de cada marca del grupo")
    articulos: Optional[dict[str, str]] = Field(
        None,
        description="Mapa {str(id_articulo): marca} para filtrar por articulos especificos. "
                    "Las claves son strings porque JSON no soporta claves enteras."
    )
```

Nota: en el schema Pydantic las claves son `str` (limitacion de JSON); `_build_config` las convierte a `int`.

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|------|------------------------|
| `archivo_articulos` apunta a archivo inexistente | `ValueError` descriptivo con ruta. Valida RF-008. |
| XLSX sin columna `CODIGO` | `ValueError` descriptivo con nombre de columna faltante. Valida RF-001. |
| XLSX vacio (solo cabecera) | `ValueError` descriptivo "no contiene filas de datos". Valida RF-005. |
| `CODIGO` con valor no entero (ej: "ABC") | Esa fila se omite con warning. El grupo se construye con los CODIGOs validos restantes. Valida RF-002. |
| `CODIGO` duplicado en la misma `CATEGORIA` | Se conserva la primera ocurrencia, la segunda se descarta sin error. Valida RF-004. |
| `CODIGO` duplicado en distintas `CATEGORIA` | Es valido; el mismo articulo puede pertenecer a dos grupos. Cada grupo lo procesa independientemente. |
| Una `CATEGORIA` con todos los CODIGOs invalidos | Se omite con warning "Categoria 'X' omitida: no tiene articulos validos". No se crea GrupoArticulos para esa categoria. |
| Una `CATEGORIA` con un solo articulo y una sola marca | `_es_grupo_simple` retorna `False` (grupos por articulos siempre son custom). Valida RF-013. |
| `requiere_todas_marcas=True` con categoria de una sola marca | Se aplica la logica existente: `len(marcas_upper) == 1` => SQL default. Valida logica existente de `get_cobertura_custom`. |
| `archivo_articulos` y `grupos` ambos presentes en el JSON | Se combinan: primero grupos manuales del JSON, luego los del XLSX. Los objetivos se indexan por `nombre` de grupo (sin importar el origen). Valida RF-006. |
| Ni `archivo_articulos` ni `grupos` presentes | Error descriptivo: al menos uno debe estar presente. Valida RF-007. |
| `archivo_articulos` presente pero `objetivos` vacio | Los grupos se generan sin objetivo; `Objetivo`, `Faltante` y `%` quedan en blanco. Comportamiento existente. |
| `articulos_ids` con 1000+ elementos | Warning en stdout; la query se ejecuta igual. Valida RNF-001. |
| `articulos_ids=[]` en `get_cobertura_custom` | `ValueError` descriptivo. Valida RF-017. |
| API recibe `articulos` con clave no convertible a int (ej: `{"abc": "HEINEKEN"}`) | `HTTPException(400)` con mensaje descriptivo. Valida RF-024. |
| Modo supervisores con grupos por articulos | N queries (una por grupo), filtrado por sucursal en memoria. Igual que hoy para grupos por marcas. |
| `CASA CENTRAL` en datos | `aplicar_zonas_virtuales` funciona igual; el DataFrame de `get_cobertura_custom` tiene `id_ruta` en ambos modos. |
| `get_cobertura_custom` falla para un grupo por articulos | Tablas vacias; el reporte continua. Valida RNF-005. |

## 7. Plan de Testing

### 7.1 Unitarios de parseo del XLSX

- [ ] `test_cargar_grupos_desde_xlsx_basico` — dado un DataFrame con 3 CATEGORIAs, verifica que se generan 3 `GrupoArticulos` con los `articulos` correctos. Valida RF-003, RF-021.

- [ ] `test_cargar_grupos_desde_xlsx_deduplica_codigo` — dado un XLSX con `CODIGO` duplicado en la misma categoria, verifica que el articulo aparece una sola vez en `grupo.articulos`. Valida RF-004.

- [ ] `test_cargar_grupos_desde_xlsx_columna_faltante` — dado un XLSX sin columna `MARCA`, verifica que se lanza error descriptivo mencionando `MARCA`. Valida RF-001.

- [ ] `test_cargar_grupos_desde_xlsx_vacio` — dado un XLSX con solo encabezado, verifica error descriptivo. Valida RF-005.

- [ ] `test_cargar_grupos_desde_xlsx_codigo_invalido_omitido` — dado un XLSX con una fila con `CODIGO = "ABC"`, verifica que esa fila se omite y el grupo se construye con las filas restantes. Valida RF-002.

- [ ] `test_cargar_grupos_desde_xlsx_marcas_deduplicadas` — dado un XLSX donde la misma marca aparece en multiples filas de la misma categoria, verifica que `grupo.marcas` contiene cada marca exactamente una vez. Valida RF-003.

- [ ] `test_cargar_grupos_desde_xlsx_categoria_sin_codigos_validos` — dado un XLSX con una categoria donde todos los CODIGOs son invalidos/NaN, verifica que esa categoria se omite y no genera GrupoArticulos.

- [ ] `test_cargar_grupos_requiere_todas_marcas_global` — verifica que el valor de `requiere_todas_marcas` global se aplica a todos los grupos generados. Valida RF-009.

### 7.2 Unitarios de `get_cobertura_custom` con `articulos_ids`

- [ ] `test_get_cobertura_custom_articulos_ids_usa_id_articulo_in` — con `articulos_ids=[1,2,3]`, verifica que la query contiene `fv.id_articulo IN (:art_0, :art_1, :art_2)` y NO contiene `da.marca IN`. Valida RF-014.

- [ ] `test_get_cobertura_custom_articulos_ids_none_usa_marca_in` — con `articulos_ids=None`, verifica que la query contiene `da.marca IN (...)` (comportamiento actual). Valida RF-018.

- [ ] `test_get_cobertura_custom_articulos_ids_vacia_lanza_error` — con `articulos_ids=[]`, verifica que se lanza `ValueError`. Valida RF-017.

- [ ] `test_get_cobertura_custom_articulos_ids_con_requiere_todas_marcas` — con `articulos_ids=[1,2]`, `marcas=["HEINEKEN","IMPERIAL"]` y `requiere_todas_marcas=True`, verifica que la query contiene tanto `fv.id_articulo IN (...)` como `COUNT(DISTINCT marca) = :num_marcas` con `num_marcas=2`. Valida RF-015.

- [ ] `test_get_cobertura_custom_articulos_ids_columnas_retornadas` — con un mock de `execute_query`, verifica que el DataFrame tiene exactamente las columnas `[periodo, id_fuerza_ventas, id_sucursal, sucursal, vendedor, id_ruta, clientes_compradores, volumen_total]`. Valida RF-014, RNF-004 implicito.

- [ ] `test_get_cobertura_custom_articulos_ids_usa_parametros_enlazados` — verifica que los IDs no se interpolan directamente en el SQL sino que se usan como parametros. Valida RNF-006.

### 7.3 Unitarios del Servicio

- [ ] `test_grupo_articulos_acepta_campo_articulos` — construye `GrupoArticulos("G", marcas=["A"], articulos={123: "A"})` sin errores. Valida RF-011.

- [ ] `test_grupo_articulos_sin_marcas_con_articulos_no_lanza_error` — construye `GrupoArticulos("G", marcas=[], articulos={123: "A"})` sin error (el `__post_init__` no debe fallar cuando `articulos` no es `None`). Valida RF-012.

- [ ] `test_grupo_articulos_sin_marcas_sin_articulos_lanza_error` — construye `GrupoArticulos("G", marcas=[])` (sin `articulos`) y verifica `ValueError`. Valida RF-012.

- [ ] `test_es_grupo_simple_false_para_grupo_con_articulos` — con `GrupoArticulos("G", marcas=["A"], articulos={1: "A"})`, verifica que `_es_grupo_simple` retorna `False`. Valida RF-013.

- [ ] `test_fetch_data_grupo_pasa_articulos_ids_al_loader` — con `grupo.articulos={1: "HEINEKEN", 2: "HEINEKEN"}`, verifica que `data_loader.get_cobertura_custom` se llama con `articulos_ids=[1, 2]`. Valida RF-019.

- [ ] `test_fetch_data_grupo_sin_articulos_no_pasa_articulos_ids` — con `grupo.articulos=None`, verifica que `get_cobertura_custom` se llama con `articulos_ids=None` (o sin el kwarg). Valida RF-020.

- [ ] `test_generar_reporte_con_grupos_por_articulos` — genera un reporte con un grupo que tiene `articulos` poblado, verifica que el archivo XLSX se crea y tiene las hojas "Sucursales" y "Por Vendedor". Valida el flujo completo end-to-end (con mocks).

### 7.4 Parseo CLI (integracion)

- [ ] `test_cmd_mision_posible_con_archivo_articulos` — simula `cmd_mision_posible` con un JSON que tiene `archivo_articulos` apuntando a un XLSX de prueba, verifica que se construyen los grupos correctamente y el servicio es llamado con ellos. Valida RF-021.

- [ ] `test_cmd_mision_posible_sin_archivo_articulos_usa_grupos` — con JSON sin `archivo_articulos` y con `grupos`, verifica que se usa el flujo existente. Valida RF-022.

- [ ] `test_cmd_mision_posible_archivo_inexistente` — con `archivo_articulos` apuntando a un archivo inexistente, verifica que termina con error sin llamar al servicio. Valida RF-008.

### 7.5 Unitarios de la API

- [ ] `test_schema_acepta_articulos` — construye `GrupoArticulosSchema(nombre="G", marcas=["A"], articulos={"123": "A"})` sin errores. Valida RF-023.

- [ ] `test_build_config_convierte_claves_a_int` — con `g.articulos={"123": "HEINEKEN"}`, verifica que el `GrupoArticulos` resultante tiene `articulos={123: "HEINEKEN"}` (clave int). Valida RF-024.

- [ ] `test_build_config_clave_no_entero_lanza_400` — con `g.articulos={"abc": "HEINEKEN"}`, verifica que se lanza `HTTPException(400)`. Valida RF-024.

## 8. Tareas de Implementacion

**Tarea 1 — Agregar `articulos` al dataclass `GrupoArticulos`**

Agregar el campo `articulos: dict[int, str] | None = None` al dataclass. Relajar el `__post_init__` para que solo lance `ValueError` cuando `marcas` esta vacia Y `articulos` es `None`. Actualizar `_es_grupo_simple` para retornar `False` cuando `articulos != None`.

- Archivos: `src/services/mision_posible/service.py`
- Sin dependencias externas

**Tarea 2 — Extender `get_cobertura_custom` con `articulos_ids`**

Agregar el parametro `articulos_ids: list[int] | None = None` a la firma. Implementar la logica de seleccion del filtro principal: si `articulos_ids` no es `None`, usar `fv.id_articulo IN (...)` con parametros enlazados; si es `None`, usar el comportamiento actual con `da.marca IN (...)`. Renombrar la variable interna `filtro_marca_clause` a `filtro_principal_clause` para reflejar que puede ser de cualquier tipo. Actualizar los metodos `_build_query_default` y `_build_query_todas_marcas` para aceptar este parametro renombrado (actualmente reciben `filtro_marca_clause` como argumento posicional). Agregar validacion para `articulos_ids=[]`.

- Archivos: `src/core/data_loader.py`
- Depende de: Tarea 1 (para conocer la firma del caller)

**Tarea 3 — Actualizar `_fetch_data_grupo` en el servicio**

Cuando `grupo.articulos is not None`, llamar a `get_cobertura_custom` con `articulos_ids=list(grupo.articulos.keys())`. Cuando `grupo.articulos is None`, comportamiento actual. No hay cambios en `generar_reporte` ni en `generar_reporte_supervisores`.

- Archivos: `src/services/mision_posible/service.py`
- Depende de: Tarea 1, Tarea 2

**Tarea 4 — Implementar `_cargar_grupos_desde_xlsx` y actualizacion de `cmd_mision_posible`**

Agregar la funcion `_cargar_grupos_desde_xlsx(ruta_xlsx, requiere_todas_marcas)` en `main.py`. Actualizar `cmd_mision_posible` para detectar `cfg.get("archivo_articulos")` y derivar los grupos desde la funcion nueva en lugar del campo `grupos_raw`. Agregar warning si tanto `archivo_articulos` como `grupos` estan presentes.

- Archivos: `main.py`
- Depende de: Tarea 1

**Tarea 5 — Actualizar el schema Pydantic y `_build_config` en la API**

Agregar `articulos: Optional[dict[str, int]] = Field(None, ...)` a `GrupoArticulosSchema`. Actualizar `_build_config` para convertir las claves string a int y lanzar `HTTPException(400)` si la conversion falla.

- Archivos: `src/api/routes/mision_posible.py`
- Depende de: Tarea 1

**Tarea 6 — Agregar tests**

Agregar todos los tests listados en la seccion 7. Crear un fixture de XLSX de prueba como DataFrame en memoria (no requiere archivo real en disco; usar `BytesIO` con `pd.ExcelWriter(engine="openpyxl")` o mockear `pd.read_excel`). **OBLIGATORIO**: Actualizar la firma de `_mock_loader._side_effect_cob` para que acepte el nuevo keyword arg `articulos_ids=None`. La firma actual es `_side_effect_cob(periodo, marcas, filtro_descripcion=None, requiere_todas_marcas=False)` y debe cambiar a `_side_effect_cob(periodo, marcas, filtro_descripcion=None, requiere_todas_marcas=False, articulos_ids=None)`. Tambien actualizar cualquier otra lambda o side_effect que use la firma vieja de `get_cobertura_custom` en el archivo de tests.

- Archivos: `tests/test_mision_posible.py`
- Depende de: Tareas 1, 2, 3, 4, 5

## 9. Boundaries (Lo que NO hacer)

- NO modificar `processor.py`, las funciones de escritura Excel (`_escribir_hoja_sucursales`, `_escribir_hoja_vendedores`), `zonas.py` ni `base_service.py`. El cambio es exclusivamente en la capa de datos y de configuracion.
- NO cambiar el formato de salida Excel; el layout del reporte no varia.
- NO persistir el XLSX ni su contenido en la BD; el archivo se lee una vez por ejecucion y los grupos viven solo en memoria durante la ejecucion.
- NO romper la retrocompatibilidad del formato `grupos` en el JSON. Si `archivo_articulos` no esta presente, el sistema debe funcionar exactamente como antes.
- NO agregar soporte para `archivo_articulos` en la API REST; esa funcionalidad es exclusiva del CLI. La API acepta grupos ya parseados con el campo `articulos`.
- NO implementar `_es_grupo_simple=True` para grupos con `articulos` de un solo elemento. Grupos por articulos siempre son custom independientemente del numero de articulos.
- NO cambiar el numero de queries por ejecucion; sigue siendo una query por grupo (con o sin modo supervisores).
- NO eliminar ni deprecar el campo `filtro_descripcion` del dataclass; sigue siendo valido para grupos por marcas.
- NO requerir `openpyxl` como dependencia nueva; ya es una dependencia del proyecto (se usa para generar el Excel de salida).

## 10. Decisiones Abiertas

- [ ] **Decision A — Orden de grupos desde XLSX**: El XLSX se agrupa por `CATEGORIA` usando `groupby(..., sort=False)` para preservar el orden de primera aparicion en el archivo. Confirmar si el negocio necesita un orden especifico (ej: alfabetico) o si el orden del archivo es suficiente.

- [x] **Decision B — `marcas` en grupos por articulos**: Resuelta. Ambos lados se normalizan a UPPER: `_cargar_grupos_desde_xlsx` normaliza las marcas del XLSX a UPPER, y el SQL del modo `articulos_ids` con `requiere_todas_marcas=True` usa `UPPER(da.marca)` en el GROUP BY y SELECT. Esto garantiza coincidencia sin importar el case en la BD o el XLSX.

- [ ] **Decision C — Warning por `articulos_ids` largo**: RNF-001 especifica emitir warning cuando `len(articulos_ids) > 1000`. Confirmar el umbral o si el warning no es necesario dado que el XLSX de ejemplo tiene 45 filas.

- [x] **Decision D — Comportamiento cuando `archivo_articulos` y `grupos` coexisten**: Resuelta. Se combinan: primero los grupos manuales del JSON, luego los generados desde el XLSX. El campo `requiere_todas_marcas` global aplica solo a los grupos del XLSX; los grupos manuales mantienen su propio `requiere_todas_marcas` por grupo.
