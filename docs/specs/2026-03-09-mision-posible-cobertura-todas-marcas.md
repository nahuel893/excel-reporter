# Spec: Mision Posible - Cobertura Requiere Todas las Marcas

> **Estado:** IMPLEMENTADA
> **Fecha:** 2026-03-09
> **Autor:** nahuel

## 1. Objetivo

Agregar un campo booleano `requiere_todas_marcas` al dataclass `GrupoArticulos` que, cuando es `True`, cambia el criterio de conteo de clientes compradores en `get_cobertura_custom`: un cliente solo cuenta si tiene volumen neto positivo en al menos un articulo de **cada** marca del grupo, en lugar de volumen neto positivo en cualquier articulo del grupo combinado.

## 2. Contexto

El comportamiento actual de `get_cobertura_custom` (implementado segun las specs `2026-03-09-mision-posible-grupos-articulos.md` y `2026-03-09-mision-imposible-union-marcas.md`, ambas IMPLEMENTADAS) cuenta a un cliente como comprador si su cantidad neta total sumando todos los articulos del grupo es positiva (`HAVING SUM(fv.cantidades_total) > 0`). Esto es la semantica de "compro algo del grupo".

El negocio necesita un criterio mas estricto para ciertos grupos multi-marca: un cliente debe haber comprado al menos una unidad neta de **cada una de las marcas** del grupo para ser contado. Por ejemplo, para el grupo `["LA CELIA", "GRAFFIGNIA", "O-61"]`, el cliente debe tener cantidad neta positiva en al menos un articulo de LA CELIA Y al menos uno de GRAFFIGNIA Y al menos uno de O-61. Comprar muchas unidades de LA CELIA pero cero de GRAFFIGNIA no lo califica.

Este es un criterio de cobertura de portafolio: no basta con comprar del grupo; hay que comprar de cada marca del grupo.

La flag es por grupo (no global), tiene valor por defecto `False` para preservar el comportamiento existente, y solo afecta a `get_cobertura_custom`. Los grupos simples que usan la tabla ETL pre-agregada (`_es_grupo_simple` retorna `True`) no son afectados en ningun caso.

## 3. Requisitos Funcionales

### 3.1 Configuracion del grupo

- **RF-001**: Cuando el usuario define un `GrupoArticulos`, el sistema debe aceptar un campo opcional `requiere_todas_marcas: bool` con valor por defecto `False`.

- **RF-002**: Cuando `requiere_todas_marcas` es `False` (default), el sistema debe mantener el comportamiento actual: un cliente cuenta si su cantidad neta total sumando todos los articulos del grupo es positiva.

- **RF-003**: Cuando `requiere_todas_marcas` es `True` y el grupo tiene dos o mas marcas distintas, el sistema debe contar al cliente solo si tiene cantidad neta positiva en al menos un articulo de **cada** marca del grupo.

- **RF-004**: Cuando `requiere_todas_marcas` es `True` y el grupo tiene exactamente una marca (despues de deduplicar), el sistema debe comportarse de forma identica al caso `requiere_todas_marcas = False`, ya que hay una sola marca que cumplir.

- **RF-005**: Cuando `requiere_todas_marcas` es `True`, el campo `_es_grupo_simple` debe permanecer sin cambios: un grupo con una sola marca y sin `filtro_descripcion` sigue siendo simple y sigue usando la tabla ETL. La flag `requiere_todas_marcas` solo es relevante dentro de `get_cobertura_custom`.

### 3.2 Consulta de cobertura

- **RF-006**: Cuando `get_cobertura_custom` recibe `requiere_todas_marcas=False`, el sistema debe generar el SQL actual con `HAVING SUM(fv.cantidades_total) > 0` en el CTE `vendedor_cliente`, sin agregar columna `da.marca` al GROUP BY.

- **RF-007**: Cuando `get_cobertura_custom` recibe `requiere_todas_marcas=True` con N marcas distintas (N >= 2), el sistema debe generar un SQL alternativo que incluya `da.marca` en el GROUP BY del CTE, aplique `HAVING SUM(fv.cantidades_total) > 0` por cliente-marca, y luego filtre los clientes que tengan exactamente N marcas distintas con volumen positivo, donde N es `len(set(marcas_upper))`.

- **RF-008**: Cuando se genera el SQL con `requiere_todas_marcas=True`, el parametro `:num_marcas` debe derivarse del largo de la lista deduplicada de marcas (`len(marcas_upper)` despues de aplicar `dict.fromkeys`), nunca ser pasado por el caller.

- **RF-009**: Cuando `get_cobertura_custom` construye la query con `requiere_todas_marcas=True`, el sistema debe aplicar el filtro en ambas ramas del UNION ALL (FV1 y FV4) de forma simetrica.

- **RF-010**: Cuando `get_cobertura_custom` recibe `requiere_todas_marcas=True` junto con `filtro_descripcion`, el sistema debe aplicar ambos filtros: `ILIKE` sobre `des_articulo` y el criterio de todas-las-marcas. El filtro `ILIKE` reduce el universo de articulos antes de evaluar si el cliente compro de cada marca.

- **RF-011**: Cuando `get_cobertura_custom` recibe `requiere_todas_marcas=True`, el DataFrame retornado debe tener exactamente las mismas columnas que el caso `False`: `periodo, id_fuerza_ventas, id_sucursal, sucursal, vendedor, id_ruta, clientes_compradores, volumen_total`. La columna `da.marca` que aparece en el CTE intermedio no debe estar en el DataFrame final.

### 3.3 Orquestacion en el servicio

- **RF-012**: Cuando `_fetch_data_grupo` llama a `get_cobertura_custom`, debe pasar `requiere_todas_marcas=grupo.requiere_todas_marcas`.

- **RF-013**: Cuando `_es_grupo_simple` evalua un grupo con `requiere_todas_marcas=True` pero con una sola marca y sin `filtro_descripcion`, debe retornar `True` (es simple). La flag no hace que un grupo simple se trate como custom.

### 3.4 API REST

- **RF-014**: Cuando el endpoint `POST /mision-posible/reporte` recibe un body con `grupos[].requiere_todas_marcas`, el sistema debe aceptarlo como campo booleano opcional con default `False` en el schema Pydantic `GrupoArticulosSchema`. El campo debe mapearse al `GrupoArticulos` correspondiente en `_build_config`.

### 3.5 Config JSON y CLI

- **RF-015**: Cuando `main.py` lee `config_mision_posible.json` y un grupo tiene el campo `requiere_todas_marcas`, debe pasarlo al constructor de `GrupoArticulos`. Si el campo esta ausente, debe omitirse (el dataclass usa el default `False`).

## 4. Requisitos No Funcionales

- **RNF-001**: El tiempo de ejecucion de `get_cobertura_custom` con `requiere_todas_marcas=True` para un grupo de 3 marcas y todas las sucursales no debe superar 60 segundos con conexion normal a la BD. La query con el CTE adicional implica un GROUP BY mas costoso pero sigue siendo una sola query UNION ALL.

- **RNF-002**: `get_cobertura_custom` debe usar parametros SQL enlazados para `:num_marcas` (entero) igual que para las marcas. Nunca interpolar el numero directamente en el SQL.

- **RNF-003**: Si `get_cobertura_custom` falla para un grupo con `requiere_todas_marcas=True`, el servicio debe capturar la excepcion, registrar el error con `print`, generar las tablas de ese grupo vacias y continuar. Igual que hoy.

- **RNF-004**: El cambio no modifica el esquema de columnas del DataFrame retornado por `get_cobertura_custom`. Las columnas siguen siendo: `periodo, id_fuerza_ventas, id_sucursal, sucursal, vendedor, id_ruta, clientes_compradores, volumen_total`.

- **RNF-005**: El cambio no modifica ninguna logica de escritura Excel, processor, ni zonas virtuales.

## 5. Diseno Tecnico

### 5.1 Modelo de Datos

Sin cambios de tablas en la BD. El cambio es exclusivamente en el SQL generado dinamicamente.

**Cambio en el dataclass Python:**

```python
# ANTES
@dataclass
class GrupoArticulos:
    nombre: str
    marcas: list[str]
    filtro_descripcion: str | None = None

# DESPUES
@dataclass
class GrupoArticulos:
    nombre: str
    marcas: list[str]
    filtro_descripcion: str | None = None
    requiere_todas_marcas: bool = False
```

### 5.2 Nueva firma de `get_cobertura_custom`

```python
def get_cobertura_custom(
    self,
    periodo: str,
    marcas: list[str],
    filtro_descripcion: str | None = None,
    requiere_todas_marcas: bool = False,
) -> pd.DataFrame:
    """
    Calcula cobertura desde fact_ventas para un grupo de marcas.

    Args:
        periodo: Primer dia del mes, formato 'YYYY-MM-DD' (ej: '2026-03-01').
        marcas: Lista de nombres de marcas en dim_articulo. Se normalizan a UPPER.
                Debe tener al menos un elemento.
        filtro_descripcion: Substring para filtrar des_articulo con ILIKE.
                            Se aplica a todos los articulos del grupo.
                            Si es None, incluye todos los articulos de las marcas.
        requiere_todas_marcas: Si True, solo cuenta clientes con cantidad neta
                               positiva en al menos un articulo de CADA marca del grupo.
                               Si False (default), usa el criterio actual: cantidad
                               neta total positiva sumando todas las marcas.

    Returns:
        DataFrame con columnas:
            periodo, id_fuerza_ventas, id_sucursal, sucursal,
            vendedor, id_ruta, clientes_compradores, volumen_total
    """
```

### 5.3 SQL: rama `requiere_todas_marcas=False` (sin cambios)

El SQL actual se conserva sin modificacion cuando `requiere_todas_marcas` es `False` o cuando hay una sola marca:

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
      AND da.marca IN (:marca_0, :marca_1, ...)
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

### 5.4 SQL: rama `requiere_todas_marcas=True` (nuevo)

Cuando `requiere_todas_marcas=True` y `len(marcas_upper) >= 2`, el SQL agrega `da.marca` al GROUP BY del CTE para poder contar marcas distintas por cliente, y luego filtra en un segundo nivel los clientes que tienen registros para todas las marcas:

```sql
WITH cliente_marca AS (
    -- Rama FV1: un registro por (cliente, marca) con volumen neto positivo
    SELECT
        DATE_TRUNC('month', fv.fecha_comprobante)::date AS periodo,
        1                                               AS id_fuerza_ventas,
        dc.des_personal_fv1                             AS vendedor,
        dc.id_ruta_fv1                                  AS id_ruta,
        fv.id_sucursal,
        ds.descripcion                                  AS sucursal,
        fv.id_cliente,
        da.marca,
        SUM(fv.cantidades_total)                        AS total_qty
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_cliente  dc ON fv.id_cliente  = dc.id_cliente
                                  AND fv.id_sucursal = dc.id_sucursal
    LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal  = ds.id_sucursal
    LEFT JOIN gold.dim_articulo da ON fv.id_articulo  = da.id_articulo
    WHERE dc.des_personal_fv1 IS NOT NULL
      AND da.marca IN (:marca_0, :marca_1, ...)
      -- condicional: AND da.des_articulo ILIKE :filtro
      AND DATE_TRUNC('month', fv.fecha_comprobante) = :periodo
    GROUP BY 1, 2, 3, 4, 5, 6, fv.id_cliente, da.marca
    HAVING SUM(fv.cantidades_total) > 0

    UNION ALL

    -- Rama FV4 (estructura identica con des_personal_fv4, id_ruta_fv4)
    SELECT
        DATE_TRUNC('month', fv.fecha_comprobante)::date AS periodo,
        4                                               AS id_fuerza_ventas,
        dc.des_personal_fv4                             AS vendedor,
        dc.id_ruta_fv4                                  AS id_ruta,
        fv.id_sucursal,
        ds.descripcion                                  AS sucursal,
        fv.id_cliente,
        da.marca,
        SUM(fv.cantidades_total)                        AS total_qty
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_cliente  dc ON fv.id_cliente  = dc.id_cliente
                                  AND fv.id_sucursal = dc.id_sucursal
    LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal  = ds.id_sucursal
    LEFT JOIN gold.dim_articulo da ON fv.id_articulo  = da.id_articulo
    WHERE dc.des_personal_fv4 IS NOT NULL
      AND da.marca IN (:marca_0, :marca_1, ...)
      -- condicional: AND da.des_articulo ILIKE :filtro
      AND DATE_TRUNC('month', fv.fecha_comprobante) = :periodo
    GROUP BY 1, 2, 3, 4, 5, 6, fv.id_cliente, da.marca
    HAVING SUM(fv.cantidades_total) > 0
),
cliente_valido AS (
    -- Solo clientes con volumen positivo en CADA marca del grupo
    -- Agrega volumen_total aqui para evitar JOIN de vuelta a cliente_marca
    SELECT
        periodo,
        id_fuerza_ventas,
        vendedor,
        id_ruta,
        id_sucursal,
        sucursal,
        id_cliente,
        SUM(total_qty) AS total_qty
    FROM cliente_marca
    GROUP BY periodo, id_fuerza_ventas, vendedor, id_ruta, id_sucursal, sucursal, id_cliente
    HAVING COUNT(DISTINCT marca) = :num_marcas
)
SELECT
    cv.periodo,
    cv.id_fuerza_ventas,
    cv.id_sucursal,
    cv.sucursal,
    cv.vendedor,
    cv.id_ruta,
    COUNT(DISTINCT cv.id_cliente) AS clientes_compradores,
    SUM(cv.total_qty)             AS volumen_total
FROM cliente_valido cv
GROUP BY cv.periodo, cv.id_fuerza_ventas, cv.id_sucursal, cv.sucursal,
         cv.vendedor, cv.id_ruta
ORDER BY cv.sucursal, cv.vendedor
```

**Construccion del parametro `:num_marcas` en Python:**

```python
marcas_upper = list(dict.fromkeys(m.upper() for m in marcas))  # dedup, preserva orden
num_marcas = len(marcas_upper)
params["num_marcas"] = num_marcas
```

El parametro `:num_marcas` nunca es provisto por el caller; siempre se deriva de `marcas_upper` dentro de `get_cobertura_custom`.

### 5.5 Logica de seleccion del SQL en Python

```python
# En get_cobertura_custom, despues de construir marcas_upper y marca_params:

usar_todas_marcas = requiere_todas_marcas and len(marcas_upper) >= 2

if usar_todas_marcas:
    params["num_marcas"] = len(marcas_upper)
    query = _build_query_todas_marcas(marca_placeholders, filtro_desc_clause)
else:
    query = _build_query_default(marca_placeholders, filtro_desc_clause)
```

La construccion del SQL puede hacerse con funciones auxiliares privadas o con f-strings condicionales; el patron exacto queda a criterio del implementador siempre que la logica sea clara y los tests pasen.

### 5.6 Arquitectura - archivos afectados

```
src/
  core/
    data_loader.py          MODIFICADO: +parametro requiere_todas_marcas en get_cobertura_custom
                                        SQL alternativo cuando requiere_todas_marcas=True
  services/
    mision_posible/
      service.py            MODIFICADO: +campo requiere_todas_marcas en GrupoArticulos
                                        _fetch_data_grupo: pasa grupo.requiere_todas_marcas
src/
  api/
    routes/
      mision_posible.py     MODIFICADO: +campo requiere_todas_marcas en GrupoArticulosSchema
                                        _build_config: pasa g.requiere_todas_marcas
config_mision_posible.json  MODIFICADO: agregar "requiere_todas_marcas": true en grupos que lo necesiten
main.py                     MODIFICADO: parseo de requiere_todas_marcas desde JSON config
tests/
  test_mision_posible.py    MODIFICADO: tests nuevos para la flag
```

Archivos NO afectados: `processor.py`, `ExcelWriter`, `zonas.py`, `base_service.py`, hojas Excel.

### 5.7 Schema Pydantic actualizado

```python
# ANTES
class GrupoArticulosSchema(BaseModel):
    nombre: str = Field(..., description="Nombre de display del grupo")
    marcas: list[str] = Field(..., min_length=1, description="Marcas en dim_articulo")
    filtro_descripcion: Optional[str] = Field(None, description="Substring ILIKE sobre des_articulo")

# DESPUES
class GrupoArticulosSchema(BaseModel):
    nombre: str = Field(..., description="Nombre de display del grupo")
    marcas: list[str] = Field(..., min_length=1, description="Marcas en dim_articulo")
    filtro_descripcion: Optional[str] = Field(None, description="Substring ILIKE sobre des_articulo")
    requiere_todas_marcas: bool = Field(False, description="Si True, el cliente debe comprar de cada marca del grupo")
```

### 5.8 Parseo en `main.py`

```python
grupos = [
    GrupoArticulos(
        nombre=g["nombre"],
        marcas=g["marcas"],
        filtro_descripcion=g.get("filtro_descripcion"),
        requiere_todas_marcas=g.get("requiere_todas_marcas", False),  # nuevo
    )
    for g in grupos_raw
]
```

### 5.9 Ejemplo de config JSON con la nueva flag

```json
{
    "periodo": "2026-03-01",
    "grupos": [
        {"nombre": "IMPERIAL", "marcas": ["IMPERIAL"]},
        {"nombre": "LEVITE", "marcas": ["LEVITE"]},
        {
            "nombre": "LA CELIA - GRAFFIGNIA - O-61",
            "marcas": ["LA CELIA", "GRAFFIGNIA", "O-61"],
            "requiere_todas_marcas": true
        }
    ],
    "objetivos": {
        "IMPERIAL": 5245,
        "LEVITE": 5256,
        "LA CELIA - GRAFFIGNIA - O-61": 622
    },
    "porcentajes_sucursal": {
        "CASA CENTRAL": 6.67,
        "VALLE SALTA": 6.67
    },
    "nombre_archivo": null,
    "supervisores": null
}
```

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|------|------------------------|
| `requiere_todas_marcas=False` (default) | SQL actual sin cambios. Valida RF-002. |
| `requiere_todas_marcas=True` con 1 marca (ej: `["IMPERIAL"]`) | SQL actual (identico a `False`), `num_marcas=1` no hace diferencia. Valida RF-004. |
| `requiere_todas_marcas=True` con marcas duplicadas (ej: `["LA CELIA","LA CELIA"]`) | Deduplicar antes: `marcas_upper = ["LA CELIA"]`, `num_marcas=1`, usar SQL default. Valida RF-004, RF-008. |
| `requiere_todas_marcas=True` con 3 marcas; cliente compra solo 2 | Cliente tiene `COUNT(DISTINCT marca) = 2 < 3`; NO es contado. Valida RF-003. |
| `requiere_todas_marcas=True` con 3 marcas; cliente compra las 3 | Cliente tiene `COUNT(DISTINCT marca) = 3 = 3`; ES contado. Valida RF-003. |
| `requiere_todas_marcas=True` con 3 marcas; cliente compra +5 LA CELIA, -3 GRAFFIGNIA; GRAFFIGNIA neta <= 0 | GRAFFIGNIA filtrada por HAVING individual; `COUNT(DISTINCT marca) = 1 < 3`; NO contado. Valida RF-007. |
| `requiere_todas_marcas=True` con `filtro_descripcion` | Filtro ILIKE reduce articulos antes del HAVING por marca. Un cliente puede calificar para LA CELIA pero no para GRAFFIGNIA si no hay articulos de GRAFFIGNIA que pasen el filtro. Valida RF-010. |
| Grupo simple (`_es_grupo_simple=True`) con `requiere_todas_marcas=True` | `_es_grupo_simple` retorna `True`; se usa tabla ETL. `requiere_todas_marcas` no tiene efecto. Valida RF-005, RF-013. |
| `requiere_todas_marcas` ausente en JSON | Parseo usa `g.get("requiere_todas_marcas", False)`; el dataclass usa default `False`. Valida RF-015. |
| `requiere_todas_marcas=True`; `get_cobertura_custom` falla | Tablas vacias para ese grupo; reporte continua. Valida RNF-003. |

## 7. Plan de Testing

### 7.1 Unitarios del DataLoader

- [ ] `test_cobertura_custom_requiere_todas_marcas_false_usa_sql_actual` — con `requiere_todas_marcas=False` y 2 marcas, verifica que la query contiene `HAVING SUM(fv.cantidades_total) > 0` en el CTE y NO contiene `COUNT(DISTINCT marca)`. Valida RF-006.

- [ ] `test_cobertura_custom_requiere_todas_marcas_true_multimarca_contiene_num_marcas` — con `requiere_todas_marcas=True` y `marcas=["LA CELIA","GRAFFIGNIA","O-61"]`, verifica que la query contiene `COUNT(DISTINCT marca) = :num_marcas` y que `params["num_marcas"] == 3`. Valida RF-007, RF-008.

- [ ] `test_cobertura_custom_requiere_todas_marcas_true_marca_unica_usa_sql_actual` — con `requiere_todas_marcas=True` y `marcas=["IMPERIAL"]`, verifica que la query es la del caso default (sin `COUNT(DISTINCT marca)`). Valida RF-004.

- [ ] `test_cobertura_custom_requiere_todas_marcas_true_dedup_usa_sql_actual` — con `requiere_todas_marcas=True` y `marcas=["LA CELIA","LA CELIA"]`, verifica que despues de deduplicar `num_marcas=1` y se usa el SQL actual. Valida RF-004.

- [ ] `test_cobertura_custom_requiere_todas_marcas_true_con_filtro_descripcion` — con `requiere_todas_marcas=True`, 2 marcas y `filtro_descripcion="710"`, verifica que la query contiene tanto `COUNT(DISTINCT marca) = :num_marcas` como `ILIKE :filtro`. Valida RF-010.

- [ ] `test_cobertura_custom_requiere_todas_marcas_num_marcas_derivado_internamente` — verifica que el parametro `:num_marcas` no puede ser inyectado por el caller; el metodo lo calcula siempre. Valida RF-008.

- [ ] `test_cobertura_custom_columnas_retornadas_identicas_con_flag` — con `requiere_todas_marcas=True` y un mock de `execute_query`, verifica que el DataFrame retornado tiene exactamente las columnas `[periodo, id_fuerza_ventas, id_sucursal, sucursal, vendedor, id_ruta, clientes_compradores, volumen_total]`. Valida RF-011, RNF-004.

### 7.2 Unitarios del Servicio

- [ ] `test_grupo_articulos_acepta_requiere_todas_marcas` — construye `GrupoArticulos("G", marcas=["A","B"], requiere_todas_marcas=True)` sin errores. Valida RF-001.

- [ ] `test_grupo_articulos_default_requiere_todas_marcas_es_false` — construye `GrupoArticulos("G", marcas=["A"])` y verifica que `requiere_todas_marcas == False`. Valida RF-001.

- [ ] `test_fetch_data_grupo_pasa_requiere_todas_marcas_al_loader` — con `grupo.requiere_todas_marcas=True`, verifica que `data_loader.get_cobertura_custom` se llama con `requiere_todas_marcas=True`. Valida RF-012.

- [ ] `test_fetch_data_grupo_false_no_pasa_flag_diferente` — con `grupo.requiere_todas_marcas=False`, verifica que `get_cobertura_custom` se llama con `requiere_todas_marcas=False`. Valida RF-002, RF-012.

- [ ] `test_es_grupo_simple_no_afectado_por_flag` — con `GrupoArticulos("G", marcas=["IMPERIAL"], requiere_todas_marcas=True)`, verifica que `_es_grupo_simple` retorna `True` (usa ETL, no custom). Valida RF-005, RF-013.

- [ ] `test_grupo_simple_con_flag_true_usa_etl_no_custom` — genera reporte con `GrupoArticulos("IMPERIAL", marcas=["IMPERIAL"], requiere_todas_marcas=True)` y verifica que `data_loader.get_cobertura_custom` no es llamado; se usa `get_cobertura_preventista_marca`. Valida RF-005, RF-013.

- [ ] `test_fallo_grupo_con_flag_no_cancela_otros` — mockea `get_cobertura_custom` para que falle cuando `requiere_todas_marcas=True` y tenga exito en otro grupo; verifica que el archivo se genera. Valida RNF-003.

### 7.3 Unitarios de la API

- [ ] `test_schema_acepta_requiere_todas_marcas_true` — construye `GrupoArticulosSchema(nombre="G", marcas=["A","B"], requiere_todas_marcas=True)` sin errores. Valida RF-014.

- [ ] `test_schema_default_requiere_todas_marcas_es_false` — construye `GrupoArticulosSchema(nombre="G", marcas=["A"])` y verifica `requiere_todas_marcas == False`. Valida RF-014.

- [ ] `test_build_config_pasa_requiere_todas_marcas` — con `requiere_todas_marcas=True` en el request, verifica que `_build_config` genera `GrupoArticulos` con `requiere_todas_marcas=True`. Valida RF-014.

### 7.4 Parseo CLI

- [ ] `test_main_parsea_requiere_todas_marcas_desde_json` — carga un JSON con `"requiere_todas_marcas": true` en un grupo y verifica que el `GrupoArticulos` resultante tiene `requiere_todas_marcas=True`. Valida RF-015.

- [ ] `test_main_omite_requiere_todas_marcas_usa_default` — carga un JSON sin el campo y verifica que `requiere_todas_marcas=False`. Valida RF-015.

## 8. Tareas de Implementacion

**Tarea 1 — Agregar `requiere_todas_marcas` al dataclass `GrupoArticulos`**

Agregar el campo `requiere_todas_marcas: bool = False` al dataclass. No se necesitan cambios en `__post_init__` ni en `_es_grupo_simple`. Actualizar `_fetch_data_grupo` para pasar `grupo.requiere_todas_marcas` a `get_cobertura_custom`.

- Archivos: `src/services/mision_posible/service.py`
- Sin dependencias

**Tarea 2 — Implementar la rama alternativa en `get_cobertura_custom`**

Agregar el parametro `requiere_todas_marcas: bool = False` a la firma. Implementar la logica de seleccion de SQL: si `requiere_todas_marcas and len(marcas_upper) >= 2`, usar el SQL con CTE `cliente_marca` + `cliente_valido` (sin JOIN de vuelta; `SUM(total_qty)` se calcula en `cliente_valido`); de lo contrario, usar el SQL actual. Derivar `num_marcas` internamente. Agregar `params["num_marcas"] = num_marcas` solo en la rama alternativa. Conservar toda la logica existente (dedup, escape wildcard, UNION ALL FV1/FV4).

- Archivos: `src/core/data_loader.py`
- Depende de: Tarea 1 (para conocer la firma del caller)
- Puede desarrollarse en paralelo si se acuerda la firma primero

**Tarea 3 — Actualizar el schema Pydantic y `_build_config`**

Agregar `requiere_todas_marcas: bool = Field(False, ...)` a `GrupoArticulosSchema`. Actualizar `_build_config` para pasar `g.requiere_todas_marcas` al construir `GrupoArticulos`.

- Archivos: `src/api/routes/mision_posible.py`
- Depende de: Tarea 1

**Tarea 4 — Actualizar `main.py` y `config_mision_posible.json`**

Agregar `requiere_todas_marcas=g.get("requiere_todas_marcas", False)` en el parseo de grupos dentro de `cmd_mision_posible`. Actualizar `config_mision_posible.json` para agregar `"requiere_todas_marcas": true` en los grupos que lo requieran (ej: `"LA CELIA - GRAFFIGNIA - O-61"`).

- Archivos: `main.py`, `config_mision_posible.json`
- Depende de: Tarea 1

**Tarea 5 — Agregar tests**

Agregar todos los tests nuevos listados en la seccion 7. No se requiere modificar tests existentes ya que el cambio es backward-compatible (nuevo campo con default `False`). **OBLIGATORIO**: Actualizar la firma de `_mock_loader._side_effect_cob` para que acepte el nuevo keyword arg `requiere_todas_marcas=False`. La firma actual es `_side_effect_cob(periodo, marcas, filtro_descripcion=None)` y debe cambiar a `_side_effect_cob(periodo, marcas, filtro_descripcion=None, requiere_todas_marcas=False)`. Sin este cambio, los tests existentes que llaman a `get_cobertura_custom` con el nuevo kwarg fallan con `TypeError`.

- Archivos: `tests/test_mision_posible.py`
- Depende de: Tarea 1, Tarea 2, Tarea 3

## 9. Boundaries (Lo que NO hacer)

- NO modificar `processor.py`, `_escribir_hoja_sucursales`, `_escribir_hoja_vendedores`, `zonas.py` ni ninguna logica de formato Excel. El cambio es exclusivamente en la capa de datos.
- NO agregar `requiere_todas_marcas` como parametro global en `MisionPosibleConfig`; la flag es por grupo.
- NO exponer `num_marcas` como parametro de la API ni del JSON de config; siempre se deriva internamente de la lista `marcas`.
- NO cambiar el comportamiento de grupos simples (`_es_grupo_simple=True`); esos grupos siempre usan la tabla ETL independientemente del valor de la flag.
- NO modificar la logica del `HAVING SUM > 0` en la rama `requiere_todas_marcas=False`; ese es el comportamiento actual que debe preservarse.
- NO implementar filtros `requiere_todas_marcas` por-marca dentro de un mismo grupo (ej: requerir solo algunas marcas del grupo pero no todas). Si el negocio lo necesita, es una spec separada.
- NO cambiar el numero de queries por ejecucion; sigue siendo una query por grupo.
- NO agregar `da.marca` al DataFrame final retornado por `get_cobertura_custom`; la columna `marca` aparece solo en el CTE intermedio.

## 10. Decisiones Abiertas

- [ ] **Decision A — Nombre del parametro SQL para el conteo**: La spec usa `:num_marcas`. Verificar que SQLAlchemy `text()` acepta parametros enteros sin casteo explicito en PostgreSQL. Si hay problemas de tipo, usar `CAST(:num_marcas AS INTEGER)` en el SQL.

- [x] **Decision B — Implementacion del SELECT final**: Resuelta. Se usa `SUM(total_qty)` directamente en el CTE `cliente_valido` y el SELECT final lee solo de `cliente_valido`, sin JOIN de vuelta a `cliente_marca`. Esto evita la inflacion de `volumen_total` que ocurria con el JOIN (cada cliente-marca generaba N filas multiplicadas).
