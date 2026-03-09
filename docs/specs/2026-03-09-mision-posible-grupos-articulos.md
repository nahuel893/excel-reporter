# Spec: Mision Posible - Grupos de Articulos

> **Estado:** IMPLEMENTADA
> **Fecha:** 2026-03-09
> **Autor:** nahuel

## 1. Objetivo

Extender el reporte Mision Posible para que, en lugar de filtrar cobertura por marca completa usando la tabla pre-agregada `cob_preventista_marca`, soporte "grupos de articulos" definidos como combinaciones de marca mas un filtro opcional por descripcion de articulo (ej: "SCHNEIDER 710" = marca SCHNEIDER + `des_articulo LIKE '%710%'`). Los grupos que no tienen filtro de descripcion se comportan identicamente al comportamiento actual.

## 2. Contexto

El reporte Mision Posible actual usa `cob_preventista_marca`, una tabla pre-agregada en la capa Gold del Data Warehouse. Esta tabla agrupa cobertura por marca completa. El negocio necesita segmentar marcas por envase o calibre; por ejemplo, "SCHNEIDER 710" (botellas de 710ml) es un grupo de gestion distinto a "SCHNEIDER" completo.

La tabla `cob_preventista_marca` no tiene granularidad de articulo, por lo que filtros como "710 ml" son imposibles sin recalcular la cobertura desde `fact_ventas + dim_articulo`. Se necesita un nuevo metodo `get_cobertura_custom()` en `DataLoader` que replique la ETL de cobertura con filtros adicionales sobre `dim_articulo.des_articulo`.

El campo `calibre` de `dim_articulo` esta previsto para el futuro pero aun no existe en la BD; por ahora el filtro se hace via `des_articulo LIKE '%<texto>%'`.

El cambio es retrocompatible en concepto: un grupo sin `filtro_descripcion` produce exactamente los mismos datos que el flujo actual. Sin embargo, la config JSON cambia de formato (de `marcas: list[str]` a `grupos: list[GrupoArticulos]`), lo que requiere migrar `config_mision_posible.json` y actualizar todos los tests existentes.

## 3. Requisitos Funcionales

### 3.1 Configuracion

- **RF-001**: Cuando el usuario provee una configuracion con el campo `grupos`, el sistema debe aceptar una lista de objetos con los campos `nombre` (string, requerido), `marca` (string, requerido) y `filtro_descripcion` (string, opcional). El campo `marcas` (formato anterior) deja de ser soportado.

- **RF-002**: Cuando `filtro_descripcion` esta presente en un grupo, el sistema debe aplicar el filtro `da.des_articulo ILIKE '%<filtro_descripcion>%'` en la consulta SQL de cobertura de ese grupo.

- **RF-003**: Cuando `filtro_descripcion` esta ausente o es `None` en un grupo, el sistema debe incluir todos los articulos de esa marca sin filtro adicional de descripcion. Nota: los resultados replican la misma logica del ETL (`cob_preventista_marca`) pero se calculan desde `fact_ventas`; pueden existir diferencias menores de timing si la tabla pre-agregada no esta actualizada.

- **RF-004**: Si `grupos` es una lista vacia o `None`, el sistema debe retornar un error descriptivo y no generar archivo.

- **RF-005**: Cuando se mapean objetivos y porcentajes de sucursal, el sistema debe usar `grupo.nombre` como clave de lookup en `config.objetivos`, reemplazando el uso anterior de `marca`.

### 3.2 Consulta de cobertura

- **RF-006**: Cuando el sistema necesita calcular cobertura para un grupo, debe invocar `DataLoader.get_cobertura_custom(periodo, marca, filtro_descripcion)` en lugar de `get_cobertura_preventista_marca`.

- **RF-007**: Cuando `get_cobertura_custom` se ejecuta, el sistema debe retornar un DataFrame con las columnas: `periodo`, `id_fuerza_ventas`, `sucursal`, `id_sucursal`, `id_vendedor`, `vendedor`, `id_ruta`, `clientes_compradores`, `volumen_total`. El esquema es identico al de `get_cobertura_preventista_marca` (incluyendo `id_fuerza_ventas` e `id_sucursal`) excepto la columna `marca` (innecesaria porque el resultado ya esta filtrado por grupo).

- **RF-008**: Cuando `get_cobertura_custom` construye la cobertura, el sistema debe implementar la logica de dos ramas FV1 y FV4 unidas con UNION ALL, replicando la ETL de `gold.cob_preventista_marca`:
  - Rama FV1: usa `dim_cliente.id_personal_fv1` como `id_vendedor` y `dim_cliente.id_ruta_fv1` como `id_ruta`.
  - Rama FV4: usa `dim_cliente.id_personal_fv4` como `id_vendedor` y `dim_cliente.id_ruta_fv4` como `id_ruta`.
  - Ambas ramas incluyen solo filas donde `id_personal_fvX IS NOT NULL`.
  - El JOIN con `dim_cliente` es compuesto: `fv.id_cliente = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal`.
  - El vendedor (`des_vendedor`) se obtiene via JOIN con `dim_vendedor` usando `id_vendedor` del resultado final.

- **RF-009**: Cuando `get_cobertura_custom` calcula clientes compradores, el sistema debe aplicar `HAVING SUM(cantidades_total) > 0` por cliente dentro de cada rama, de modo que un cliente con cantidad neta <= 0 no sea contado como comprador.

- **RF-010**: Cuando `get_cobertura_custom` se invoca con `filtro_descripcion`, el sistema debe agregar la condicion `da.des_articulo ILIKE :filtro` a ambas ramas del UNION ALL, donde `:filtro` es el parametro con valor `'%<filtro_descripcion>%'`.

- **RF-011**: Cuando `get_cobertura_custom` se invoca sin `filtro_descripcion` (o con `None`), el sistema no debe agregar ninguna condicion sobre `des_articulo`.

### 3.3 Orquestacion en el servicio

- **RF-012**: Cuando el servicio genera el reporte, debe invocar `get_cobertura_custom` una vez por cada grupo de la lista `config.grupos`, pasando `periodo`, `grupo.marca` y `grupo.filtro_descripcion`.

- **RF-013**: Cuando el servicio recibe el DataFrame de cobertura de un grupo, debe aplicar `aplicar_zonas_virtuales()` de `src/core/zonas.py` al resultado antes de enviarlo al processor. La logica de zonas virtuales no cambia.

- **RF-014**: Cuando el servicio itera por grupos, debe pasar al processor el DataFrame ya filtrado para ese grupo (no hay filtrado por marca en el processor). El nombre de display del grupo (`grupo.nombre`) se usa como etiqueta en los titulos de las tablas Excel.

- **RF-015**: Cuando se genera en modo supervisores, el sistema debe realizar una llamada a `get_cobertura_custom` por cada grupo por cada supervisor. A diferencia del modo actual (una sola consulta global particionada en memoria), esta estrategia es necesaria porque cada grupo puede tener un SQL diferente. Si el numero de supervisores x grupos es grande, esto puede impactar performance (ver RNF-001).

  **Alternativa aceptable**: hacer una sola llamada por grupo (sin filtro de sucursal) y luego filtrar en memoria por supervisor, como se hace hoy. Esta alternativa es preferida si el volumen de datos lo permite.

- **RF-016**: Cuando `MisionPosibleResult` se construye, el campo `marcas_incluidas` debe contener la lista de `grupo.nombre` (no `grupo.marca`), para reflejar el nombre de display.

### 3.4 Processor (sin cambios de logica)

- **RF-017**: Cuando el processor recibe el DataFrame de un grupo, las funciones `procesar_cobertura_sucursal` y `procesar_cobertura_vendedor` deben recibir el DataFrame ya filtrado (sin la columna `marca`) y un parametro `grupo_nombre: str` en lugar de `marca: str`. El parametro `grupo_nombre` se usa solo para labeling; el filtrado ya ocurrio en la consulta SQL.

- **RF-018**: Mientras el processor procesa un DataFrame de cobertura de grupo, debe agrupar por `sucursal` y `vendedor` exactamente igual que hoy, sin cambios en la logica de calculo de Objetivo, Faltante y Porcentaje.

### 3.5 Config JSON

- **RF-019**: Cuando el sistema lee `config_mision_posible.json`, debe aceptar el nuevo formato con `grupos` y rechazar (error descriptivo) el formato antiguo con `marcas` a nivel de campo raiz.

- **RF-020**: Cuando se usan grupos sin `filtro_descripcion`, el comportamiento del reporte generado debe replicar la logica del ETL de `cob_preventista_marca` (mismos JOINs, misma logica FV1/FV4 UNION ALL, mismo `HAVING SUM > 0`). Los resultados se calculan en tiempo real desde `fact_ventas`, por lo que reflejan datos mas frescos que la tabla pre-agregada.

- **RF-021**: Cuando `get_cobertura_custom` recibe un `filtro_descripcion` que contiene caracteres SQL wildcard (`%` o `_`), el sistema debe escaparlos antes de wrappear con `%..%` para evitar wildcards no intencionales. Ejemplo: `filtro_descripcion="710%"` produce `ILIKE '%710\%%'`. El escape es responsabilidad del `DataLoader`.

## 4. Requisitos No Funcionales

- **RNF-001**: La generacion del reporte para hasta 6 grupos (con o sin `filtro_descripcion`) y todas las sucursales debe completarse en menos de 30 segundos con conexion normal a la base de datos. Cada llamada a `get_cobertura_custom` implica una query con UNION ALL sobre `fact_ventas`; esto es mas costoso que la tabla pre-agregada.

- **RNF-002**: El servicio debe aceptar `DataLoader` inyectable para permitir tests unitarios con mocks, siguiendo el patron existente.

- **RNF-003**: Si `get_cobertura_custom` falla para un grupo, el sistema debe capturar la excepcion, registrar el error con `print`, generar las tablas de ese grupo vacias y continuar con los demas grupos sin propagar el error.

- **RNF-004**: El archivo generado debe poder abrirse en Excel y LibreOffice sin errores de formato. El cambio no modifica la capa de escritura Excel.

- **RNF-005**: `get_cobertura_custom` debe usar parametros SQL enlazados (`:param`) en lugar de interpolacion de strings para prevenir inyeccion SQL.

## 5. Diseno Tecnico

### 5.1 Modelo de Datos

No se crean tablas nuevas. La nueva fuente de datos es la consulta dinamica desde transacciones.

**Nuevo metodo: `DataLoader.get_cobertura_custom(periodo, marca, filtro_descripcion)`**

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
      AND da.marca = :marca
      -- condicional: AND da.des_articulo ILIKE :filtro  (solo si filtro_descripcion)
      AND DATE_TRUNC('month', fv.fecha_comprobante) = :periodo
    GROUP BY 1, 2, 3, 4, 5, 6, fv.id_cliente
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
      AND da.marca = :marca
      -- condicional: AND da.des_articulo ILIKE :filtro  (solo si filtro_descripcion)
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

Parametros:
- `:periodo` — primer dia del mes, ej: `'2026-03-01'`
- `:marca` — nombre de marca en mayusculas, ej: `'SCHNEIDER'`
- `:filtro` — solo si `filtro_descripcion` presente, valor `'%710%'`

**DataFrame retornado por `get_cobertura_custom`:**

| Columna | Tipo | Descripcion |
|---------|------|-------------|
| `periodo` | date | Primer dia del mes |
| `id_fuerza_ventas` | int | Fuerza de ventas (1=FV1, 4=FV4) |
| `id_sucursal` | int | ID numerico de la sucursal |
| `sucursal` | str | Descripcion de la sucursal |
| `id_vendedor` | int | ID del vendedor (de dim_cliente) |
| `vendedor` | str | Nombre del vendedor (de dim_vendedor) |
| `id_ruta` | int | ID de ruta (de dim_cliente) |
| `clientes_compradores` | int | Clientes distintos con compra neta > 0 |
| `volumen_total` | float | Suma de cantidades_total |

Nota: no incluye columna `marca` porque el DataFrame ya esta filtrado para un grupo especifico. Incluye `id_fuerza_ventas` e `id_sucursal` para mantener paridad con `cob_preventista_marca` y permitir que `aplicar_zonas_virtuales` funcione correctamente.

### 5.2 Nuevas estructuras de datos en Python

```python
@dataclass
class GrupoArticulos:
    """Define un grupo de articulos para el reporte Mision Posible."""
    nombre: str                          # nombre de display y clave en objetivos/resultados
    marca: str                           # marca en dim_articulo (case-insensitive en SQL)
    filtro_descripcion: str | None = None  # substring para ILIKE sobre des_articulo


@dataclass
class MisionPosibleConfig:
    """Configuracion para el reporte Mision Posible."""
    periodo: str                                # "YYYY-MM-DD", primer dia del mes
    grupos: list[GrupoArticulos]                # reemplaza a marcas: list[str]
    objetivos: dict[str, int] = field(default_factory=dict)        # clave = grupo.nombre
    porcentajes_sucursal: dict[str, float] = field(default_factory=dict)
    nombre_archivo: str | None = None
    supervisores: dict[str, list[str]] | None = None
```

### 5.3 Arquitectura

Archivos afectados:

```
src/
  core/
    data_loader.py          MODIFICADO: +get_cobertura_custom()
  services/
    mision_posible/
      service.py            MODIFICADO: MisionPosibleConfig.marcas -> grupos,
                                        _fetch_data_grupo(), loop por grupos
      processor.py          MODIFICADO: firma de funciones marca->grupo_nombre,
                                        eliminar filtro interno por marca
config_mision_posible.json  MODIFICADO: formato marcas -> grupos
tests/
  test_mision_posible.py    MODIFICADO: fixtures y mocks actualizados,
                                        tests nuevos para grupos con filtro_descripcion
```

`ExcelWriter`, `zonas.py`, `base_service.py` y los metodos de escritura Excel en `service.py` (`_escribir_hoja_sucursales`, `_escribir_hoja_vendedores`) no se modifican.

**Flujo de datos actualizado:**

```
MisionPosibleService.generar_reporte(config)
    |
    +-- Para cada grupo en config.grupos:
    |     |
    |     +-- data_loader.get_cobertura_custom(
    |     |       periodo=config.periodo,
    |     |       marca=grupo.marca,
    |     |       filtro_descripcion=grupo.filtro_descripcion
    |     |   )  --> df_cob_raw
    |     |
    |     +-- aplicar_zonas_virtuales(df_cob_raw)  --> df_cob
    |     |
    |     +-- procesar_cobertura_sucursal(df_cob, grupo_nombre=grupo.nombre, ...)
    |     |       --> df_suc
    |     |
    |     +-- procesar_cobertura_vendedor(df_cob, grupo_nombre=grupo.nombre, ...)
    |             --> df_vend
    |
    +-- tablas_suc: list[(grupo.nombre, df_suc)]
    +-- tablas_vend: list[(grupo.nombre, df_vend)]
    |
    +-- _escribir_hoja_sucursales(ws_suc, tablas_suc, ultima_fecha)
    +-- _escribir_hoja_vendedores(ws_vend, tablas_vend, ultima_fecha)
    |
    --> MisionPosibleResult(marcas_incluidas=[g.nombre for g in config.grupos])
```

### 5.4 API / Interfaz

#### Config JSON actualizada (`config_mision_posible.json`)

```json
{
    "periodo": "2026-03-01",
    "grupos": [
        {"nombre": "SCHNEIDER 710", "marca": "SCHNEIDER", "filtro_descripcion": "710"},
        {"nombre": "IMPERIAL", "marca": "IMPERIAL"},
        {"nombre": "LEVITE", "marca": "LEVITE"},
        {"nombre": "VILLA DEL SUR", "marca": "VILLA DEL SUR"}
    ],
    "objetivos": {
        "SCHNEIDER 710": 3200,
        "IMPERIAL": 5245,
        "LEVITE": 5256,
        "VILLA DEL SUR": 4475
    },
    "porcentajes_sucursal": {
        "CASA CENTRAL": 6.67,
        "VALLE SALTA": 6.67,
        "SUCURSAL CAFAYATE": 6.67,
        "SUCURSAL METAN": 6.67,
        "SUCURSAL ABRA PAMPA": 6.67,
        "SUCURSAL PERICO": 6.67,
        "SUCURSAL TARTAGAL": 6.67
    },
    "nombre_archivo": null,
    "supervisores": null
}
```

#### Firma de `get_cobertura_custom`

```python
def get_cobertura_custom(
    self,
    periodo: str,
    marca: str,
    filtro_descripcion: str | None = None,
) -> pd.DataFrame:
    """
    Calcula cobertura desde fact_ventas para una marca y filtro de descripcion opcional.

    Args:
        periodo: Primer dia del mes, formato 'YYYY-MM-DD' (ej: '2026-03-01').
        marca: Nombre de marca exacto en dim_articulo (se usa UPPER para normalizar).
        filtro_descripcion: Substring para filtrar des_articulo con ILIKE.
                            Si es None, incluye todos los articulos de la marca.

    Returns:
        DataFrame con columnas:
            periodo, sucursal, id_vendedor, vendedor, id_ruta,
            clientes_compradores, volumen_total
    """
```

#### Firmas actualizadas del processor

```python
def procesar_cobertura_sucursal(
    df_cob: pd.DataFrame,
    _grupo_nombre: str,          # antes: marca: str (no se usa en el cuerpo)
    objetivo_total: int | None,
    porcentajes_sucursal: dict[str, float],
) -> pd.DataFrame:
    """
    Genera tabla de cobertura por sucursal para un grupo de articulos.
    df_cob ya esta filtrado para este grupo; no se aplica filtro interno.
    """

def procesar_cobertura_vendedor(
    df_cob: pd.DataFrame,
    _grupo_nombre: str,          # antes: marca: str (no se usa en el cuerpo)
    objetivo_total: int | None,
    porcentajes_sucursal: dict[str, float],
) -> pd.DataFrame:
    """
    Genera tabla de cobertura por vendedor para un grupo de articulos.
    df_cob ya esta filtrado para este grupo; no se aplica filtro interno.
    """
```

Nota: `_grupo_nombre` usa prefijo `_` para indicar que no se usa en el cuerpo (el filtro ya ocurrio en SQL). El parametro se mantiene en la firma para documentar el contexto del DataFrame recibido.

#### Subcomando CLI (sin cambios en la interfaz)

```bash
# El subcomando sigue siendo el mismo; solo cambia el formato del JSON:
python main.py mision-posible --config config_mision_posible.json
```

#### Endpoint API (sin cambios en la interfaz REST)

El body de `POST /mision-posible/reporte` cambia su schema:

```json
{
  "periodo": "2026-03-01",
  "grupos": [
    {"nombre": "SCHNEIDER 710", "marca": "SCHNEIDER", "filtro_descripcion": "710"},
    {"nombre": "IMPERIAL", "marca": "IMPERIAL"}
  ],
  "objetivos": {"SCHNEIDER 710": 3200, "IMPERIAL": 5245},
  "porcentajes_sucursal": {"CASA CENTRAL": 6.67},
  "nombre_archivo": null,
  "supervisores": null
}
```

## 6. Edge Cases y Constraints

| Caso | Comportamiento esperado |
|------|------------------------|
| `grupos = []` o `None` | Error descriptivo (`ValueError`), no se genera archivo. Valida RF-004. |
| `filtro_descripcion = ""` (string vacio) | Tratarlo como `None`; no agregar condicion ILIKE. El string vacio no es un filtro valido. |
| Grupo sin datos en `fact_ventas` para ese periodo/marca/filtro | `df_cob` vacio; tablas del grupo con `Cobertura = 0` para todas las sucursales de `porcentajes_sucursal`. Igual que hoy con marca sin datos. |
| `grupo.nombre` no esta en `config.objetivos` | `Objetivo`, `Faltante` y `%` quedan vacios (`None`) para todas las filas de ese grupo. Igual que hoy. |
| `filtro_descripcion` con caracteres especiales SQL (`%`, `_`) | El sistema debe escapar solo los caracteres `%` y `_` del input antes de wrappearlos con `%..%`, para evitar wildcards no intencionales. Ejemplo: `filtro_descripcion="710%"` → `ILIKE '%710\%%'`. |
| Dos grupos con la misma `marca` pero diferente `filtro_descripcion` | Cada grupo genera su propia consulta y sus propias tablas; no se solapan. Ejemplo: grupo "SCHNEIDER 710" y grupo "SCHNEIDER 1L" son independientes. |
| Dos grupos con el mismo `nombre` | El segundo sobreescribira al primero en el dict `objetivos`. El sistema NO debe validar unicidad de nombres (la responsabilidad es del usuario). |
| Modo supervisores con N grupos | Se hacen N llamadas a `get_cobertura_custom` (una por grupo) y luego se filtra por sucursal en memoria por supervisor. Esto es N queries por ejecucion, no N x supervisores. |
| `CASA CENTRAL` en datos | `aplicar_zonas_virtuales` sigue funcionando igual; usa `id_ruta` del DataFrame de `get_cobertura_custom`, que incluye esta columna. Sin cambios. |
| `get_cobertura_custom` falla para un grupo | El grupo genera tablas vacias; el error se loggea con `print`; el reporte se genera para el resto de los grupos. Valida RNF-003. |
| Grupo con `marca` en minusculas | La consulta SQL debe normalizar a mayusculas con `UPPER(:marca)` o el caller debe normalizar antes de pasarla. El servicio debe normalizar `grupo.marca.upper()` antes de llamar al DataLoader. |
| Periodo con dia distinto de 1 | Normalizar al primer dia del mes con warning (comportamiento existente sin cambio). |

## 7. Plan de Testing

### Unitarios del DataLoader

- [ ] `test_get_cobertura_custom_sin_filtro_descripcion` — verifica que la query generada NO contiene `des_articulo`. Valida RF-011.

- [ ] `test_get_cobertura_custom_con_filtro_descripcion` — verifica que la query generada contiene `ILIKE` con el parametro `:filtro`. Valida RF-010.

- [ ] `test_get_cobertura_custom_columnas_retornadas` — dado un mock de `execute_query`, verifica que el DataFrame retornado tiene exactamente las columnas `[periodo, sucursal, id_vendedor, vendedor, id_ruta, clientes_compradores, volumen_total]`. Valida RF-007.

- [ ] `test_get_cobertura_custom_normaliza_marca_a_mayusculas` — verifica que la marca `"imperial"` se normaliza a `"IMPERIAL"` antes del SQL. Valida edge case de marca en minusculas.

- [ ] `test_get_cobertura_custom_escapa_wildcards_en_filtro` — verifica que `filtro_descripcion="710%"` genera parametro `'%710\\%%'` (escapado). Valida RF-021.

### Unitarios del Processor

- [ ] `test_procesar_sucursal_sin_filtro_interno` — verifica que `procesar_cobertura_sucursal` con un DataFrame ya filtrado (sin columna `marca`) retorna columnas `[Sucursal, Cobertura, Objetivo, Faltante, %]` correctamente. Valida RF-017.

- [ ] `test_procesar_vendedor_sin_filtro_interno` — mismo enfoque para `procesar_cobertura_vendedor`. Valida RF-017.

- [ ] `test_grupo_nombre_aparece_en_titulo_de_tabla` — verifica que el nombre del grupo (ej: "SCHNEIDER 710") puede pasarse como `grupo_nombre` sin romper el processor. Valida RF-014.

### Unitarios del Servicio

- [ ] `test_config_acepta_grupos` — construye `MisionPosibleConfig` con `grupos=[GrupoArticulos("IMPERIAL", "IMPERIAL")]` sin errores. Valida RF-001.

- [ ] `test_error_grupos_vacio` — con `grupos=[]`, verifica que el servicio lanza `ValueError` y no llama al DataLoader. Valida RF-004.

- [ ] `test_servicio_llama_get_cobertura_custom_por_grupo` — con 2 grupos, verifica que `data_loader.get_cobertura_custom` se llama exactamente 2 veces (una por grupo). Valida RF-012.

- [ ] `test_grupo_sin_filtro_descripcion_no_pasa_filtro` — con un grupo sin `filtro_descripcion`, verifica que `get_cobertura_custom` se llama con `filtro_descripcion=None`. Valida RF-003, RF-011.

- [ ] `test_grupo_con_filtro_descripcion_pasa_filtro` — con `GrupoArticulos("SCHNEIDER 710", "SCHNEIDER", "710")`, verifica que `get_cobertura_custom` se llama con `filtro_descripcion="710"`. Valida RF-002, RF-010.

- [ ] `test_zonas_virtuales_se_aplican_por_grupo` — verifica que `aplicar_zonas_virtuales` se invoca para cada DataFrame retornado por `get_cobertura_custom`. Valida RF-013.

- [ ] `test_objetivos_usan_nombre_del_grupo` — con `objetivos={"SCHNEIDER 710": 3200}` y un grupo con `nombre="SCHNEIDER 710"`, verifica que la tabla de sucursales tiene `Objetivo != None`. Valida RF-005.

- [ ] `test_result_marcas_incluidas_son_nombres_de_grupos` — verifica que `MisionPosibleResult.marcas_incluidas` contiene `["SCHNEIDER 710", "IMPERIAL"]` (nombres de grupos, no marcas). Valida RF-016.

- [ ] `test_fallo_en_un_grupo_no_cancela_otros` — mockea `get_cobertura_custom` para que falle en el primer grupo y tenga exito en el segundo; verifica que el archivo se genera con la tabla del segundo grupo y la primera queda vacia. Valida RNF-003.

- [ ] `test_modo_supervisores_una_consulta_por_grupo` — con 2 supervisores y 2 grupos, verifica que `get_cobertura_custom` se llama exactamente 2 veces (una por grupo, filtrando por sucursal en memoria). Valida RF-015.

- [ ] `test_modo_supervisores_genera_archivo_por_supervisor` — con 2 supervisores, verifica que se generan 2 archivos con las hojas "Sucursales" y "Por Vendedor". Comportamiento existente, no debe romperse. Valida RF-015.

- [ ] `test_titulo_de_tabla_usa_nombre_del_grupo` — genera el workbook con un grupo `nombre="SCHNEIDER 710"` y verifica que el titulo de la tabla en la hoja "Sucursales" es "SCHNEIDER 710". Valida RF-014.

### Tests existentes a actualizar

Los tests existentes en `test_mision_posible.py` usan `marcas=["IMPERIAL", "LEVITE"]` y mockean `get_cobertura_preventista_marca`. Todos deben migrarse:

- Reemplazar `marcas=["IMPERIAL", "LEVITE"]` por `grupos=[GrupoArticulos("IMPERIAL", "IMPERIAL"), GrupoArticulos("LEVITE", "LEVITE")]` en `_config()`.
- Reemplazar `loader.get_cobertura_preventista_marca.return_value = ...` por `loader.get_cobertura_custom.return_value = ...` en `_mock_loader()`.
- Eliminar la columna `marca` del DataFrame de fixture `_df_cob()` (ya no forma parte del output de `get_cobertura_custom`).
- Actualizar `test_modo_supervisores_una_sola_consulta` para verificar que `get_cobertura_custom` se llama N veces (una por grupo), no `get_cobertura_preventista_marca`.

## 8. Tareas de Implementacion

**Tarea 1 — Agregar `GrupoArticulos` y actualizar `MisionPosibleConfig`**

Agregar el dataclass `GrupoArticulos` en `service.py`. Reemplazar el campo `marcas: list[str]` por `grupos: list[GrupoArticulos]` en `MisionPosibleConfig`. Actualizar la validacion de la guarda (`if not config.grupos`). Actualizar `_nombre_reporte` y `MisionPosibleResult` si referencias a `marcas` existen.

- Archivos: `src/services/mision_posible/service.py`
- Sin dependencias externas nuevas

**Tarea 2 — Implementar `get_cobertura_custom` en DataLoader**

Implementar el nuevo metodo con la query UNION ALL descrita en la seccion 5.1. Usar `text()` de SQLAlchemy con parametros enlazados. El filtro `ILIKE` se agrega condicionalmente al string SQL antes de compilar si `filtro_descripcion` no es `None`. El string vacio debe tratarse como `None`.

- Archivos: `src/core/data_loader.py`
- Sin dependencias externas nuevas
- Depende de: ninguna tarea (puede implementarse en paralelo con Tarea 1)

**Tarea 3 — Actualizar el processor**

Renombrar el parametro `marca` a `grupo_nombre` en `procesar_cobertura_sucursal` y `procesar_cobertura_vendedor`. Eliminar la linea de filtrado interno `df_cob[df_cob["marca"] == marca]`. Verificar que el resto de la logica funciona con un DataFrame sin columna `marca`.

- Archivos: `src/services/mision_posible/processor.py`
- Depende de: Tarea 1 (para entender la nueva semantica)

**Tarea 4 — Actualizar el servicio: loop por grupos y llamadas a `get_cobertura_custom`**

Reemplazar `_fetch_data(periodo)` (que llama `get_cobertura_preventista_marca` una vez) por `_fetch_data_grupo(periodo, grupo)` que llama `get_cobertura_custom` por grupo. Actualizar `generar_reporte` y `generar_reporte_supervisores` para iterar por `config.grupos` y llamar al nuevo metodo. Pasar `grupo.nombre` al processor en lugar de `marca`. Actualizar `MisionPosibleResult.marcas_incluidas`.

- Archivos: `src/services/mision_posible/service.py`
- Depende de: Tarea 1, Tarea 2, Tarea 3

**Tarea 5 — Actualizar `config_mision_posible.json`**

Migrar el archivo de configuracion de produccion al nuevo formato con `grupos`. Conservar los objetivos y porcentajes existentes.

- Archivos: `config_mision_posible.json`
- Depende de: Tarea 1 (para conocer el nuevo formato)

**Tarea 6 — Actualizar el schema de la API REST**

Si el endpoint `POST /mision-posible/reporte` usa un Pydantic model, actualizar el model para reflejar `grupos: list[GrupoArticulosSchema]` en lugar de `marcas: list[str]`. Actualizar la documentacion del endpoint.

- Archivos: `src/api/routes/mision_posible.py`
- Depende de: Tarea 1

**Tarea 7 — Actualizar tests**

Migrar todos los tests existentes (ver seccion 7, subseccion "Tests existentes a actualizar"). Agregar todos los tests nuevos listados en la seccion 7.

- Archivos: `tests/test_mision_posible.py`
- Depende de: Tarea 3, Tarea 4

## 9. Boundaries (Lo que NO hacer)

- NO modificar `ExcelWriter`, `_escribir_hoja_sucursales`, `_escribir_hoja_vendedores` ni ninguna logica de formato Excel; este cambio es exclusivamente de datos y configuracion.
- NO agregar soporte para filtrar por `calibre` de `dim_articulo`; esa columna no existe aun en la BD. El filtro de `des_articulo ILIKE` es la solucion temporal hasta que el ETL agregue `calibre`.
- NO mantener compatibilidad con el formato antiguo `marcas: list[str]` en la config JSON. El cambio de formato es un breaking change intencional y documentado.
- NO recalcular cobertura global (todas las marcas de una vez) y luego filtrar en Python; cada grupo tiene su propia query SQL para garantizar resultados correctos con `HAVING SUM > 0` por cliente.
- NO agregar la columna `marca` al DataFrame retornado por `get_cobertura_custom`; el DataFrame ya esta en el contexto de un grupo especifico.
- NO cambiar el layout Excel ni los nombres de hojas ("Sucursales", "Por Vendedor"); el formato visual no cambia.
- NO soportar multiples periodos en esta iteracion.

## 10. Decisiones Resueltas

- [x] **Decision A — Modo supervisores**: N queries (una por grupo) con filtrado en memoria por supervisor. Es la misma estrategia que hoy con marcas y el volumen de `fact_ventas` mensual es manejable.

- [x] **Decision B — Escape de caracteres en `filtro_descripcion`**: Responsabilidad del `DataLoader` (ver RF-021). Es el unico punto de contacto con SQL.

- [x] **Decision C — Nombre del parametro en el processor**: Se renombra `marca` a `_grupo_nombre` (con prefijo `_` para indicar que no se usa en el cuerpo). El processor solo es llamado desde `service.py`; no hay otros callers.
