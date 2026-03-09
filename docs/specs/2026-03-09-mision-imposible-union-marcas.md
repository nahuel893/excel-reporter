# Spec: Mision Posible - Union de Marcas

> **Estado:** IMPLEMENTADA
> **Fecha:** 2026-03-09
> **Autor:** nahuel

## 1. Objetivo

Extender el campo `marca` del dataclass `GrupoArticulos` para aceptar una lista de marcas (`marcas: list[str]`) en lugar de una sola, de modo que la cobertura de un grupo se calcule como la union de clientes que compraron cualquiera de las marcas del grupo con volumen neto positivo a traves de todas ellas combinadas.

## 2. Contexto

El sistema actual (implementado segun `2026-03-09-mision-posible-grupos-articulos.md`, estado IMPLEMENTADA) soporta `GrupoArticulos` con `marca: str`. Cada grupo dispara una query `get_cobertura_custom(periodo, marca, filtro_descripcion)` que filtra `AND da.marca = :marca` en `fact_ventas`.

El negocio necesita grupos que combinen marcas relacionadas, por ejemplo "LEVITE + VILLAVICENCIO": un cliente que compro LEVITE pero devolvio VILLAVICENCIO (o viceversa) debe contarse como comprador solo si su cantidad neta a traves de **ambas marcas combinadas** es positiva. La logica `HAVING SUM > 0` debe aplicarse sobre el total de las marcas unidas, no por separado, porque de lo contrario un cliente con compra neta positiva en una marca pero negativa en otra podria ser contado doble.

La extension es un breaking change en la firma de `GrupoArticulos` y en `get_cobertura_custom`: el campo `marca: str` pasa a `marcas: list[str]`. El filtro `filtro_descripcion` se mantiene como clausula global aplicada a todos los articulos del grupo independientemente de la marca.

## 3. Requisitos Funcionales

### 3.1 Configuracion

- **RF-001**: Cuando el usuario define un `GrupoArticulos`, el sistema debe aceptar el campo `marcas: list[str]` (lista de una o mas marcas) y rechazar el campo `marca: str` (formato anterior). El campo `filtro_descripcion: str | None` se conserva sin cambios.

- **RF-002**: Cuando `marcas` contiene exactamente un elemento, el sistema debe comportarse de forma identica al comportamiento anterior con `marca: str` unica. Los resultados numericos deben ser identicos.

- **RF-003**: Cuando `marcas` contiene dos o mas elementos, el sistema debe calcular la cobertura como la union de clientes que tienen cantidad neta positiva sumando las cantidades de todas las marcas del grupo. Un cliente con +5 unidades de LEVITE y -3 unidades de VILLAVICENCIO tiene cantidad neta total +2 y debe ser contado como comprador.

- **RF-004**: Cuando `marcas` es una lista vacia o `None`, el sistema debe lanzar un `ValueError` descriptivo y no generar archivo.

- **RF-005**: Cuando `filtro_descripcion` esta presente en un grupo multi-marca, el sistema debe aplicar el filtro `da.des_articulo ILIKE '%<filtro>%'` a todos los articulos del grupo independientemente de la marca. No existe soporte de filtros por-marca en esta iteracion.

- **RF-006**: Cuando la config JSON tiene el formato `"marcas": ["LEVITE", "VILLAVICENCIO"]`, el sistema debe aceptarlo. Cuando la config tiene el formato antiguo `"marca": "LEVITE"` (string simple), el sistema debe lanzar un error descriptivo al parsear la configuracion.

### 3.2 Consulta de cobertura

- **RF-007**: Cuando `get_cobertura_custom` recibe una lista de marcas con un solo elemento, el sistema debe generar SQL con `AND da.marca = :marca_0` (o equivalente `IN` con un elemento). Los resultados numericos deben ser identicos al comportamiento anterior.

- **RF-008**: Cuando `get_cobertura_custom` recibe una lista de marcas con dos o mas elementos, el sistema debe generar SQL con `AND da.marca IN (:marca_0, :marca_1, ...)` usando parametros enlazados, uno por marca. El numero de parametros debe coincidir exactamente con el largo de la lista.

- **RF-009**: Cuando `get_cobertura_custom` construye el CTE `vendedor_cliente`, el GROUP BY debe mantenerse como `(periodo, id_fuerza_ventas, id_vendedor, id_ruta, id_sucursal, sucursal, id_cliente)` — sin `da.marca` (que nunca estuvo). Al cambiar el filtro de `= :marca` a `IN (...)`, las cantidades de distintas marcas del mismo cliente se suman automaticamente en el mismo grupo. El `HAVING SUM(fv.cantidades_total) > 0` se evalua sobre la suma total de todas las marcas del grupo.

- **RF-010**: Cuando `get_cobertura_custom` construye ambas ramas del UNION ALL (FV1 y FV4), el sistema debe aplicar el filtro `IN (:marca_0, :marca_1, ...)` a ambas ramas de forma identica.

- **RF-011**: Cuando `get_cobertura_custom` recibe `filtro_descripcion` junto a multiples marcas, el sistema debe agregar `AND da.des_articulo ILIKE :filtro` a ambas ramas del UNION ALL ademas del filtro `IN` de marcas. Ambos filtros se combinan con AND.

- **RF-012**: Cuando `get_cobertura_custom` normaliza las marcas, el sistema debe aplicar `.upper()` a cada elemento de la lista antes de construir la query SQL.

### 3.3 Orquestacion en el servicio

- **RF-013**: Cuando el servicio llama a `_fetch_data_grupo(periodo, grupo)`, debe pasar `marcas=grupo.marcas` (lista) al metodo `get_cobertura_custom` en lugar de `marca=grupo.marca.upper()` (string). La normalizacion a mayusculas se delega al DataLoader (RF-012), el caller no aplica `.upper()`. La cantidad de llamadas a la BD no cambia: sigue siendo una llamada por grupo.

- **RF-014**: Cuando se construye `MisionPosibleResult`, el campo `marcas_incluidas` debe contener la lista de `grupo.nombre` (no `grupo.marcas`), igual que hoy.

### 3.4 API REST

- **RF-015**: Cuando el endpoint `POST /mision-posible/reporte` recibe un body con `grupos[].marcas` (lista), el sistema debe aceptarlo y construir correctamente los `GrupoArticulos`. El campo `grupos[].marca` (string) debe ser rechazado con HTTP 422.

### 3.5 Config JSON

- **RF-016**: Cuando `main.py` lee `config_mision_posible.json`, debe parsear el campo `marcas` de cada grupo como `list[str]`. Si el campo `marca` (string) esta presente en lugar de `marcas` (lista), `main.py` (funcion `cmd_mision_posible`) debe lanzar `ValueError` con un mensaje descriptivo que indique que el formato fue actualizado a `"marcas": [...]`.

## 4. Requisitos No Funcionales

- **RNF-001**: La generacion del reporte para hasta 6 grupos (incluyendo grupos multi-marca con hasta 5 marcas cada uno) y todas las sucursales debe completarse en menos de 45 segundos. La union de marcas incrementa marginalmente el costo de la query por el `IN` y el GROUP BY sin `marca`, pero no cambia el numero de queries.

- **RNF-002**: `get_cobertura_custom` debe usar parametros SQL enlazados (`:marca_0`, `:marca_1`, ...) para cada marca de la lista, nunca interpolacion de strings. Esto previene SQL injection incluso con listas de un elemento.

- **RNF-003**: Si `get_cobertura_custom` falla para un grupo (por cualquier razon), el servicio debe capturar la excepcion, registrar el error con `print`, generar las tablas de ese grupo vacias y continuar con los demas grupos. Igual que hoy.

- **RNF-004**: El cambio no debe modificar el esquema de columnas del DataFrame retornado por `get_cobertura_custom`. Las columnas siguen siendo: `periodo, id_fuerza_ventas, id_sucursal, sucursal, id_vendedor, vendedor, id_ruta, clientes_compradores, volumen_total`.

## 5. Diseno Tecnico

### 5.1 Cambios en el modelo de datos Python

```python
# ANTES
@dataclass
class GrupoArticulos:
    nombre: str
    marca: str
    filtro_descripcion: str | None = None

# DESPUES
@dataclass
class GrupoArticulos:
    nombre: str
    marcas: list[str]
    filtro_descripcion: str | None = None
```

No se crean tablas nuevas en la BD. El cambio es exclusivamente en el SQL generado dinamicamente.

### 5.2 Nueva firma de `get_cobertura_custom`

```python
def get_cobertura_custom(
    self,
    periodo: str,
    marcas: list[str],
    filtro_descripcion: str | None = None,
) -> pd.DataFrame:
    """
    Calcula cobertura desde fact_ventas para un grupo de marcas.
    La cobertura es la union de clientes con cantidad neta positiva
    sumando todas las marcas del grupo.

    Args:
        periodo: Primer dia del mes, formato 'YYYY-MM-DD' (ej: '2026-03-01').
        marcas: Lista de nombres de marcas en dim_articulo. Se normalizan a UPPER.
                Debe tener al menos un elemento.
        filtro_descripcion: Substring para filtrar des_articulo con ILIKE.
                            Se aplica a todos los articulos del grupo.
                            Si es None, incluye todos los articulos de las marcas.

    Returns:
        DataFrame con columnas:
            periodo, id_fuerza_ventas, id_sucursal, sucursal,
            id_vendedor, vendedor, id_ruta, clientes_compradores, volumen_total
    """
```

### 5.3 SQL completo para `get_cobertura_custom` con multiples marcas

El cambio clave respecto a la implementacion actual es:
1. `AND da.marca = :marca` reemplazado por `AND da.marca IN (:marca_0, :marca_1, ...)`
2. Parametros dinamicos generados en Python con `{marca_0: "LEVITE", marca_1: "VILLAVICENCIO", ...}`

**Nota**: El GROUP BY del CTE actual ya NO incluye `da.marca` — agrupa por `(periodo, id_fuerza_ventas, id_vendedor, id_ruta, id_sucursal, sucursal, id_cliente)`. Esto significa que al cambiar `= :marca` por `IN (...)`, las cantidades de distintas marcas del mismo cliente se suman automaticamente en el mismo grupo. No hay que modificar el GROUP BY.

```sql
WITH vendedor_cliente AS (
    -- Rama FV1
    SELECT
        DATE_TRUNC('month', fv.fecha_comprobante)::date AS periodo,
        1                                               AS id_fuerza_ventas,
        dc.id_personal_fv1                              AS id_vendedor,
        dc.id_ruta_fv1                                  AS id_ruta,
        fv.id_sucursal,
        ds.descripcion                                  AS sucursal,
        fv.id_cliente,
        SUM(fv.cantidades_total)                        AS total_qty
    FROM gold.fact_ventas fv
    JOIN      gold.dim_cliente  dc ON fv.id_cliente  = dc.id_cliente
                                  AND fv.id_sucursal = dc.id_sucursal
    LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal  = ds.id_sucursal
    LEFT JOIN gold.dim_articulo da ON fv.id_articulo  = da.id_articulo
    WHERE dc.id_personal_fv1 IS NOT NULL
      AND da.marca IN (:marca_0, :marca_1, ...)     -- generado dinamicamente
      -- condicional: AND da.des_articulo ILIKE :filtro
      AND DATE_TRUNC('month', fv.fecha_comprobante) = :periodo
    GROUP BY 1, 2, 3, 4, 5, 6, fv.id_cliente
    -- GROUP BY sin cambios respecto a la version actual; da.marca nunca estuvo en el GROUP BY
    HAVING SUM(fv.cantidades_total) > 0

    UNION ALL

    -- Rama FV4
    SELECT
        DATE_TRUNC('month', fv.fecha_comprobante)::date AS periodo,
        4                                               AS id_fuerza_ventas,
        dc.id_personal_fv4                              AS id_vendedor,
        dc.id_ruta_fv4                                  AS id_ruta,
        fv.id_sucursal,
        ds.descripcion                                  AS sucursal,
        fv.id_cliente,
        SUM(fv.cantidades_total)                        AS total_qty
    FROM gold.fact_ventas fv
    JOIN      gold.dim_cliente  dc ON fv.id_cliente  = dc.id_cliente
                                  AND fv.id_sucursal = dc.id_sucursal
    LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal  = ds.id_sucursal
    LEFT JOIN gold.dim_articulo da ON fv.id_articulo  = da.id_articulo
    WHERE dc.id_personal_fv4 IS NOT NULL
      AND da.marca IN (:marca_0, :marca_1, ...)     -- mismo IN generado dinamicamente
      -- condicional: AND da.des_articulo ILIKE :filtro
      AND DATE_TRUNC('month', fv.fecha_comprobante) = :periodo
    GROUP BY 1, 2, 3, 4, 5, 6, fv.id_cliente
    HAVING SUM(fv.cantidades_total) > 0
)
SELECT
    vc.periodo,
    vc.id_fuerza_ventas,
    vc.id_sucursal,
    vc.sucursal,
    vc.id_vendedor,
    dv.des_vendedor                  AS vendedor,
    vc.id_ruta,
    COUNT(DISTINCT vc.id_cliente)    AS clientes_compradores,
    SUM(vc.total_qty)                AS volumen_total
FROM vendedor_cliente vc
LEFT JOIN gold.dim_vendedor dv ON vc.id_vendedor = dv.id_vendedor
GROUP BY vc.periodo, vc.id_fuerza_ventas, vc.id_sucursal, vc.sucursal,
         vc.id_vendedor, dv.des_vendedor, vc.id_ruta
ORDER BY vc.sucursal, dv.des_vendedor
```

**Construccion dinamica del clausula IN y sus parametros en Python:**

```python
marcas_upper = [m.upper() for m in marcas]
marca_params = {f"marca_{i}": m for i, m in enumerate(marcas_upper)}
marca_placeholders = ", ".join(f":marca_{i}" for i in range(len(marcas_upper)))
filtro_marca_clause = f"AND da.marca IN ({marca_placeholders})"

params: dict = {"periodo": periodo, **marca_params}
```

Para una lista `["LEVITE", "VILLAVICENCIO"]` esto produce:
- `filtro_marca_clause = "AND da.marca IN (:marca_0, :marca_1)"`
- `params = {"periodo": "2026-03-01", "marca_0": "LEVITE", "marca_1": "VILLAVICENCIO"}`

### 5.4 Arquitectura - archivos afectados

```
src/
  core/
    data_loader.py          MODIFICADO: firma get_cobertura_custom(marcas: list[str])
                                        SQL: = :marca  ->  IN (:marca_0, ...)
                                        GROUP BY: eliminar da.marca del CTE
  services/
    mision_posible/
      service.py            MODIFICADO: GrupoArticulos.marca -> marcas: list[str]
                                        _fetch_data_grupo: pasa grupo.marcas
src/
  api/
    routes/
      mision_posible.py     MODIFICADO: GrupoArticulosSchema.marca -> marcas: list[str]
                                        _build_config: pasa g.marcas
config_mision_posible.json  MODIFICADO: "marca": "X"  ->  "marcas": ["X"]
main.py                     MODIFICADO: parseo de grupos desde JSON config
                                        deteccion de formato viejo "marca" -> error descriptivo
tests/
  test_mision_posible.py    MODIFICADO: fixtures, mocks y tests nuevos
```

Archivos NO afectados: `processor.py`, `ExcelWriter`, `zonas.py`, `base_service.py`, hoja Excel.

### 5.5 Actualizacion del schema Pydantic en la API

```python
# ANTES
class GrupoArticulosSchema(BaseModel):
    nombre: str
    marca: str
    filtro_descripcion: Optional[str] = None

# DESPUES
class GrupoArticulosSchema(BaseModel):
    nombre: str
    marcas: list[str] = Field(..., min_length=1, description="Marcas en dim_articulo")
    filtro_descripcion: Optional[str] = Field(None, description="Substring ILIKE sobre des_articulo")
```

El helper `_build_config` pasa de:
```python
GrupoArticulos(nombre=g.nombre, marca=g.marca, filtro_descripcion=g.filtro_descripcion)
```
a:
```python
GrupoArticulos(nombre=g.nombre, marcas=g.marcas, filtro_descripcion=g.filtro_descripcion)
```

### 5.6 Formato de config JSON actualizado

```json
{
    "periodo": "2026-03-01",
    "grupos": [
        {"nombre": "AGUAS", "marcas": ["LEVITE", "VILLAVICENCIO"]},
        {"nombre": "IMPERIAL", "marcas": ["IMPERIAL"]},
        {"nombre": "SCHNEIDER 710", "marcas": ["SCHNEIDER"], "filtro_descripcion": "710"},
        {"nombre": "VILLA DEL SUR", "marcas": ["VILLA DEL SUR"]}
    ],
    "objetivos": {
        "AGUAS": 8000,
        "IMPERIAL": 5245,
        "SCHNEIDER 710": 3200,
        "VILLA DEL SUR": 4475
    },
    "porcentajes_sucursal": {
        "CASA CENTRAL": 6.67,
        "VALLE SALTA": 6.67,
        "SUCURSAL CAFAYATE": 6.67,
        "SUCURSAL METAN": 6.67
    },
    "nombre_archivo": null,
    "supervisores": null
}
```

### 5.7 Actualizacion del mock en tests

El mock actual usa `side_effect` sobre el parametro `marca` (string):

```python
# ANTES
loader.get_cobertura_custom.side_effect = lambda periodo, marca, filtro_descripcion=None: {
    "IMPERIAL": _df_cob_imperial(),
    "LEVITE": _df_cob_levite(),
}.get(marca.upper(), pd.DataFrame())
```

El nuevo mock debe recibir `marcas` (lista):

```python
# DESPUES
def _side_effect_cob(periodo, marcas, filtro_descripcion=None):
    key = tuple(sorted(m.upper() for m in marcas))
    return {
        ("IMPERIAL",): _df_cob_imperial(),
        ("LEVITE",): _df_cob_levite(),
        ("LEVITE", "VILLAVICENCIO"): _df_cob_aguas(),
    }.get(key, pd.DataFrame())

loader.get_cobertura_custom.side_effect = _side_effect_cob
```

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|------|------------------------|
| `marcas = []` | `ValueError` en `GrupoArticulos.__post_init__` o en `get_cobertura_custom`. No se genera archivo. Valida RF-004. |
| `marcas = ["IMPERIAL"]` (un elemento) | Comportamiento identico al `marca = "IMPERIAL"` anterior. Genera `IN (:marca_0)`. Valida RF-002. |
| Cliente compra LEVITE +5, devuelve VILLAVICENCIO -3; grupo es ["LEVITE","VILLAVICENCIO"] | Cantidad neta total = +2 > 0; el cliente ES contado como comprador. Valida RF-003. |
| Cliente compra LEVITE +5, devuelve VILLAVICENCIO -8; grupo es ["LEVITE","VILLAVICENCIO"] | Cantidad neta total = -3 <= 0; el cliente NO es contado como comprador. Valida RF-003. |
| Cliente compra LEVITE +5; grupo es ["LEVITE","VILLAVICENCIO"] pero no tiene ventas de VILLAVICENCIO | Cantidad neta = +5 > 0; el cliente ES contado. Valida RF-003. |
| `marcas` con duplicados, ej: `["IMPERIAL", "IMPERIAL"]` | El sistema no valida unicidad; genera `IN (:marca_0, :marca_1)` con el mismo valor dos veces. Funciona correctamente en SQL (no cuenta doble). Sin embargo, normalizar duplicados (dedupliacion) es aceptable si se documenta. |
| `marcas` con strings en minusculas | `.upper()` aplicado a cada elemento antes del SQL. Valida RF-012. |
| `filtro_descripcion` con grupos multi-marca | El filtro ILIKE se aplica a todos los articulos del grupo. Un articulo de VILLAVICENCIO que contiene el texto del filtro es incluido. Valida RF-011. |
| Config JSON con `"marca": "LEVITE"` (string, formato viejo) | Error de parseo Pydantic (HTTP 422 en API) o `ValueError` en CLI. Mensaje descriptivo que indica el cambio de formato. Valida RF-006, RF-016. |
| Grupo con `marcas` de marcas sin datos en el periodo | DataFrame vacio; tablas con `Cobertura = 0`. Igual que hoy. |
| `get_cobertura_custom` falla para un grupo multi-marca | Tablas vacias para ese grupo; el reporte continua con los demas. Valida RNF-003. |
| `filtro_descripcion` con caracteres SQL wildcard (`%`, `_`) | Escape previo al wrapping `%..%`. Comportamiento existente sin cambio. |
| Modo supervisores con N grupos multi-marca | N queries (una por grupo, sin distincion mono/multi-marca), filtrado por sucursal en memoria. Sin cambio respecto al comportamiento actual. |

## 7. Plan de Testing

### 7.1 Unitarios de DataLoader

- [ ] `test_get_cobertura_custom_marca_unica_genera_in_clause` — con `marcas=["IMPERIAL"]`, verifica que la query contiene `IN (:marca_0)` y que `params["marca_0"] == "IMPERIAL"`. Valida RF-007.

- [ ] `test_get_cobertura_custom_multimarca_genera_in_con_todos_los_params` — con `marcas=["LEVITE", "VILLAVICENCIO"]`, verifica que la query contiene `IN (:marca_0, :marca_1)` y que `params` tiene `marca_0="LEVITE"` y `marca_1="VILLAVICENCIO"`. Valida RF-008, RF-010.

- [ ] `test_get_cobertura_custom_multimarca_group_by_sin_marca` — con `marcas=["LEVITE", "VILLAVICENCIO"]`, verifica que el GROUP BY del CTE agrupa por `(periodo, id_fuerza_ventas, id_vendedor, id_ruta, id_sucursal, sucursal, id_cliente)` sin `da.marca` (misma estructura que la version anterior). Valida RF-009.

- [ ] `test_get_cobertura_custom_having_aplica_sobre_suma_total` — verifica que `HAVING SUM(fv.cantidades_total) > 0` esta presente en ambas ramas del UNION ALL (sin condicion adicional por marca). Valida RF-009.

- [ ] `test_get_cobertura_custom_multimarca_con_filtro_descripcion` — con `marcas=["LEVITE","VILLAVICENCIO"]` y `filtro_descripcion="600"`, verifica que la query contiene tanto `IN (:marca_0, :marca_1)` como `ILIKE :filtro`. Valida RF-011.

- [ ] `test_get_cobertura_custom_normaliza_marcas_a_mayusculas` — con `marcas=["levite", "Villavicencio"]`, verifica que `params["marca_0"] == "LEVITE"` y `params["marca_1"] == "VILLAVICENCIO"`. Valida RF-012.

- [ ] `test_get_cobertura_custom_lista_vacia_lanza_error` — con `marcas=[]`, verifica que se lanza `ValueError`. Valida RF-004.

- [ ] `test_get_cobertura_custom_columnas_retornadas_no_cambian` — dado un mock de `execute_query`, verifica que el DataFrame tiene exactamente las columnas `[periodo, id_fuerza_ventas, id_sucursal, sucursal, id_vendedor, vendedor, id_ruta, clientes_compradores, volumen_total]`. Valida RNF-004.

### 7.2 Unitarios del Servicio

- [ ] `test_grupo_articulos_acepta_marcas_lista` — construye `GrupoArticulos(nombre="AGUAS", marcas=["LEVITE","VILLAVICENCIO"])` sin errores. Valida RF-001.

- [ ] `test_grupo_articulos_rechaza_lista_vacia` — construye `GrupoArticulos(nombre="X", marcas=[])` y verifica `ValueError`. Valida RF-004.

- [ ] `test_fetch_data_grupo_pasa_lista_de_marcas` — con `grupo.marcas=["LEVITE","VILLAVICENCIO"]`, verifica que `data_loader.get_cobertura_custom` se llama con `marcas=["LEVITE","VILLAVICENCIO"]` (no con `marca=...`). Valida RF-013.

- [ ] `test_fetch_data_grupo_marca_unica_pasa_lista` — con `grupo.marcas=["IMPERIAL"]`, verifica que `get_cobertura_custom` se llama con `marcas=["IMPERIAL"]`. Valida RF-002, RF-013.

- [ ] `test_grupo_multimarca_resultado_marcas_incluidas_usa_nombre` — `MisionPosibleResult.marcas_incluidas` contiene `"AGUAS"` (nombre del grupo), no `"LEVITE"` ni `"VILLAVICENCIO"`. Valida RF-014.

- [ ] `test_error_grupos_vacio_no_llama_data_loader` — con `grupos=[]`, verifica `ValueError` sin llamadas al DataLoader. Valida RF-004.

- [ ] `test_fallo_en_grupo_multimarca_no_cancela_otros` — mockea `get_cobertura_custom` para que falle cuando `marcas=["LEVITE","VILLAVICENCIO"]` y tenga exito cuando `marcas=["IMPERIAL"]`; verifica que el archivo se genera con la tabla de IMPERIAL con datos y la de AGUAS vacia (error capturado). Valida RNF-003.

### 7.3 Unitarios de la API

- [ ] `test_schema_acepta_marcas_lista` — construye `GrupoArticulosSchema(nombre="X", marcas=["IMPERIAL"])` sin errores. Valida RF-015.

- [ ] `test_schema_rechaza_campo_marca_string` — construye `GrupoArticulosSchema(nombre="X", marca="IMPERIAL")` y verifica `ValidationError` de Pydantic (campo `marca` no existe). Valida RF-015, RF-006.

- [ ] `test_schema_rechaza_marcas_lista_vacia` — construye `GrupoArticulosSchema(nombre="X", marcas=[])` y verifica `ValidationError` (min_length=1). Valida RF-004.

- [ ] `test_build_config_pasa_marcas_al_grupo` — con un request que tiene `marcas=["LEVITE","VILLAVICENCIO"]`, verifica que `_build_config` retorna un `MisionPosibleConfig` donde `grupos[0].marcas == ["LEVITE","VILLAVICENCIO"]`. Valida RF-015.

### 7.4 Tests existentes a actualizar

Los tests que actualmente usan `GrupoArticulos("IMPERIAL", "IMPERIAL")` deben migrarse a `GrupoArticulos("IMPERIAL", marcas=["IMPERIAL"])`. El mock `_mock_loader` debe actualizarse para que `side_effect` reciba `marcas` (lista) en lugar de `marca` (string). Ver seccion 5.7 para el patron del nuevo mock.

Checklist de migracion:
- [ ] `_mock_loader`: reemplazar `lambda periodo, marca, ...` por `lambda periodo, marcas, ...` con lookup por tuple.
- [ ] Todos los fixtures `GrupoArticulos(nombre, marca)` reemplazados por `GrupoArticulos(nombre, marcas=[marca])`.
- [ ] Tests que verifican llamada con `marca=...` deben verificar `marcas=[...]`.
- [ ] Inline `side_effect` lambdas que usan `marca` como parametro posicional (ej: `lambda periodo, marca, filtro_descripcion=None`) deben cambiar a `marcas`.
- [ ] `assert_called_once_with(periodo=..., marca="X", ...)` deben cambiar a `marcas=["X"]`.
- [ ] Test `test_fallo_en_un_grupo_no_cancela_otros`: su `side_effect` usa `marca` como arg — cambiar a `marcas`.
- [ ] Test `test_calculo_fila_inicio_con_marcas_de_distintos_tamanos`: su lambda usa `marca` — cambiar a `marcas`.

## 8. Tareas de Implementacion

**Tarea 1 — Actualizar `GrupoArticulos`: `marca` -> `marcas: list[str]`**

Cambiar el campo `marca: str` a `marcas: list[str]` en el dataclass `GrupoArticulos`. Agregar validacion en `__post_init__` que lance `ValueError` si `marcas` es vacia. Actualizar `_fetch_data_grupo` para pasar `grupo.marcas` al DataLoader.

- Archivos: `src/services/mision_posible/service.py`
- Sin dependencias

**Tarea 2 — Actualizar `get_cobertura_custom`: firma y SQL**

Cambiar la firma de `(periodo, marca: str, ...)` a `(periodo, marcas: list[str], ...)`. Agregar validacion de lista no vacia. Construir la clausula `IN` dinamicamente con parametros enlazados enumerados (`marca_0`, `marca_1`, ...). Eliminar `da.marca` del GROUP BY del CTE. Conservar toda la logica restante (UNION ALL, FV1/FV4, HAVING, filtro_descripcion).

- Archivos: `src/core/data_loader.py`
- Sin dependencias (puede desarrollarse en paralelo con Tarea 1)

**Tarea 3 — Actualizar el schema Pydantic y el helper `_build_config`**

Cambiar `GrupoArticulosSchema.marca: str` a `marcas: list[str]` con `min_length=1`. Actualizar `_build_config` para pasar `g.marcas` al construir `GrupoArticulos`.

- Archivos: `src/api/routes/mision_posible.py`
- Depende de: Tarea 1

**Tarea 4 — Actualizar `config_mision_posible.json` y `main.py`**

Migrar todos los grupos de `"marca": "X"` a `"marcas": ["X"]` en el config. Actualizar `main.py` (`cmd_mision_posible`) para parsear `marcas` como lista y detectar formato viejo `marca` con error descriptivo.

- Archivos: `config_mision_posible.json`, `main.py`
- Depende de: Tarea 1

**Tarea 5 — Actualizar tests**

Migrar `_mock_loader` para que el `side_effect` reciba `marcas: list[str]`. Actualizar todos los `GrupoArticulos(nombre, marca)` a `GrupoArticulos(nombre, marcas=[marca])`. Agregar todos los tests nuevos listados en la seccion 7.

- Archivos: `tests/test_mision_posible.py`
- Depende de: Tarea 1, Tarea 2, Tarea 3

## 9. Boundaries (Lo que NO hacer)

- NO modificar `processor.py`, `ExcelWriter`, `_escribir_hoja_sucursales`, `_escribir_hoja_vendedores`, `zonas.py` ni ninguna logica de formato Excel. El cambio es exclusivamente en la capa de datos y configuracion.
- NO implementar filtros `filtro_descripcion` por-marca (distintos filtros para distintas marcas del mismo grupo). Si el negocio lo necesita en el futuro, es una spec separada.
- NO mantener compatibilidad con `marca: str` en `GrupoArticulos` ni en `GrupoArticulosSchema`. El cambio es un breaking change intencional; no hay periodo de transicion con ambos campos.
- NO cambiar la logica de `procesar_cobertura_sucursal` ni `procesar_cobertura_vendedor`; reciben el DataFrame ya calculado y no necesitan conocer cuantas marcas componen el grupo.
- NO cambiar el numero de queries por ejecucion (sigue siendo una query por grupo). No hacer N queries por marca y unir en Python; la semantica del `HAVING SUM > 0` cross-marca requiere que sea una sola query SQL.
- NO agregar la columna `marcas` al DataFrame retornado por `get_cobertura_custom`; el DataFrame ya esta en el contexto de un grupo especifico.
- NO soportar listas de marcas en la tabla pre-agregada `cob_preventista_marca`; esa tabla no es usada por Mision Posible desde la spec anterior.

## 10. Decisiones Resueltas

- [x] **Decision A — Deduplicar marcas en la lista**: Si, deduplicar silenciosamente en `get_cobertura_custom` antes de construir los params, con `list(dict.fromkeys(marcas_upper))` para preservar orden. `marcas=["IMPERIAL","IMPERIAL"]` se trata como `["IMPERIAL"]`.

- [x] **Decision B — Validacion de marcas en `GrupoArticulos.__post_init__`**: Validar en ambos puntos. `GrupoArticulos.__post_init__` lanza `ValueError` si `marcas` es vacia (fail-fast). `get_cobertura_custom` tambien valida defensivamente.

- [x] **Decision C — Normalizacion a mayusculas**: Se hace en `get_cobertura_custom` (RF-012). El caller (`_fetch_data_grupo`) pasa `grupo.marcas` sin transformar.
