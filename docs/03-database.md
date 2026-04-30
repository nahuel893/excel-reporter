# 03 — Base de datos

## Esquema y arquitectura

- **Motor**: PostgreSQL.
- **Esquema**: `gold` (capa Gold de la arquitectura Medallion — tablas dimensionales y de hechos ya preparadas para consumo).
- **Conexión**: variables en `.env` (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD) leídas por `config/settings.py`.
- **Driver**: SQLAlchemy 2.0 + psycopg2.

## Tablas usadas

### Tablas de hechos (fact)

| Tabla | Granularidad | Columnas clave | Usada por |
|-------|--------------|----------------|-----------|
| `gold.fact_ventas` | venta-línea | `id`, `fecha_comprobante`, `id_documento`, `id_sucursal`, `id_articulo`, `id_cliente`, `id_vendedor`, `cantidades_total`, `cantidad_total_htls`, `subtotal_neto`, `subtotal_final`, `bonificacion`, `descuentos` | ventas, resumen-mensual, historico-fratelli, ventas-articulo, reporte-general-badie, avances, etc. |
| `gold.fact_cupos` | objetivo mensual | `id`, `periodo` (varchar `'YYYY-MM'`), `proveedor`, `id_sucursal`, `sucursal`, `id_ruta`, `preventista`, `generico`, `desagregado`, `cupo` | resumen-mensual (Objetivo) |
| `gold.fact_cupos_cobertura` | objetivo cobertura | similar a fact_cupos | (no usado actualmente) |
| `gold.fact_stock` | stock al cierre | `fecha`, `id_sucursal`, `id_articulo`, `cantidad` | stock-diario |
| `gold.fact_comodatos` | comodatos | — | — |
| `gold.fact_ventas_contabilidad` | reconciliación | — | — |

`fact_ventas` **NO tiene `id_ruta`**. La ruta del cliente viene del JOIN con `dim_cliente.id_ruta_fv1`.

### Tablas dimensionales (dim)

| Tabla | Clave primaria | Columnas relevantes |
|-------|----------------|---------------------|
| `gold.dim_sucursal` | `id_sucursal` | `descripcion` (e.g. `"1 - CASA CENTRAL"`) |
| `gold.dim_articulo` | `id_articulo` | `descripcion`, `generico`, `marca` |
| `gold.dim_cliente` | (`id_cliente`, `id_sucursal`) | `descripcion`, `id_ruta_fv1`, `id_ruta_fv4`, `id_fuerza_ventas` |
| `gold.dim_vendedor` | (`id_sucursal`, `id_vendedor`) | `descripcion`, `id_ruta` |
| `gold.dim_deposito` | — | — |
| `gold.dim_tiempo` | `fecha` | `dia_semana`, `mes`, `anio` |

**Convención**: `dim_cliente` y `dim_vendedor` tienen **clave compuesta** `(id_sucursal, id_*)`. Los JOINs con `fact_ventas` deben respetar las dos claves.

### Tablas de cobertura (cob)

Pre-agregadas con conteos de clientes que cumplen criterios de cobertura.

| Tabla | Granularidad | Columnas | Usada por |
|-------|--------------|----------|-----------|
| `gold.cob_preventista_generico` | preventista × genérico | `id_sucursal`, `id_ruta`, `id_fuerza_ventas`, `generico`, `clientes_compradores`, `volumen_total` | ventas (cobertura por preventista) |
| `gold.cob_preventista_marca` | preventista × marca | similar + `marca` | ventas |
| `gold.cob_sucursal_generico` | sucursal × genérico | `id_sucursal`, `id_fuerza_ventas`, `generico`, `clientes_compradores`, ... | ventas, graficos-cobertura |
| `gold.cob_sucursal_marca` | sucursal × marca | similar + `marca` | ventas, graficos-cobertura |
| `gold.cob_preventista_articulo` | preventista × artículo | similar + `id_articulo` | champions-league |
| `gold.cob_sucursal_articulo` | sucursal × artículo | | champions-league |
| `gold.cob_sucursal_aguas` | desagregación de AGUAS | (opcional) | graficos-cobertura |
| `gold.cob_sucursal_lista_generico` | listas | — | — |
| `gold.cob_sucursal_lista_marca` | listas | — | — |

**Convención `cob_preventista_*`**: requieren `WHERE id_fuerza_ventas = 1` para evitar duplicados con FV4 (canal frío).

## Métodos del DataLoader

`src/core/data_loader.py` (1701 líneas) expone ~25 métodos `get_*`. Todos retornan un `pandas.DataFrame` con columnas estables.

### Sucursales y artículos

| Método | Output | Descripción |
|--------|--------|-------------|
| `get_sucursales()` | `[descripcion]` | Lista de sucursales activas (texto). |
| `get_sucursales_full()` | `[id_sucursal, descripcion]` | Idem con ID. |
| `get_articulos()` | `[generico, marca]` | Combinaciones genérico-marca. |
| `get_articulos_filtrados(genericos)` | `[generico, marca]` | Filtrado por lista. |

### Ventas

| Método | Args | Output | Usado por |
|--------|------|--------|-----------|
| `get_ventas(fecha_desde, fecha_hasta)` | fechas | sucursal, generico, marca, cantidad, monto, htls | (legacy compat) |
| `get_ventas_diarias(fecha_desde, fecha_hasta, genericos=None)` | + genericos opcional | + fecha (sin id_ruta) | (legacy) |
| `get_ventas_diarias_con_ruta(fecha_desde, fecha_hasta, ...)` | | + `id_ruta` | ventas |
| `get_ventas_resumen_mensual(fecha_desde, fecha_hasta, genericos)` | | sucursal, generico, id_ruta, cantidad | resumen-mensual |
| `get_ventas_ultimos_dias_habiles(fecha_desde, fecha_hasta, genericos)` | | sucursal, generico, fecha, id_ruta, cantidad | resumen-mensual |
| `get_ventas_mes_anterior(fecha_desde, genericos)` | | sucursal, generico, id_ruta, cantidad | resumen-mensual |
| `get_ventas_mismo_mes_anio_anterior(fecha_desde, fecha_hasta, genericos)` | | sucursal, generico, id_ruta, cantidad | resumen-mensual |
| `get_ventas_articulo_diario(fecha_desde, fecha_hasta, id_articulo)` | | sucursal, fecha, cantidad | ventas-articulo |
| `get_ventas_historico_fratelli(fecha_desde, fecha_hasta)` | | (multi-año, multi-mes) | historico-fratelli |
| `get_prvta_historico_fratelli(fecha_desde, fecha_hasta)` | | (sólo `id_documento='PRVTA'`) | historico-fratelli |
| `get_ventas_historico_cliente(id_cliente, id_sucursal, ...)` | | histórico de un cliente | historico-cliente |
| `get_ventas_mensuales_ccu(fecha_desde, fecha_hasta)` | | sucursal, generico, anio, trimestre, bultos | reporte-general-badie |
| `get_cobertura_clientes_ccu(fecha_desde, fecha_hasta)` | | sucursal, anio, trimestre, id_cliente, bultos, bultos_sin_regalos, bultos_aguas_danone, bultos_aguas_danone_sin_regalos, meses_con_compra | reporte-general-badie |

### Cobertura

| Método | Output | Usado por |
|--------|--------|-----------|
| `get_cobertura_preventista_generico(fecha_desde, fecha_hasta)` | id_sucursal, id_ruta, id_fuerza_ventas, generico, clientes_compradores, volumen_total | ventas |
| `get_cobertura_preventista_marca(fecha_desde, fecha_hasta)` | + marca | ventas |
| `get_cobertura_sucursal_generico(fecha_desde, fecha_hasta)` | id_sucursal, id_fuerza_ventas, generico, ... | ventas, graficos-cobertura |
| `get_cobertura_sucursal_marca(fecha_desde, fecha_hasta)` | + marca | ventas |
| `get_cob_sucursal_aguas(fecha_desde, fecha_hasta)` | desagregación AGUAS (opcional, puede no existir) | graficos-cobertura |

### Cupos / Objetivos

| Método | Args | Output |
|--------|------|--------|
| `get_cupos(periodo)` | `'YYYY-MM'` | sucursal, id_ruta, generico, cupo |
| `get_cupos_resumen_mensual(periodo, genericos)` | + genericos | id_sucursal, id_ruta, sucursal, generico, cupo |

### Stock

| Método | Args |
|--------|------|
| `get_stock_diario(fecha)` | `'YYYY-MM-DD'` |

### Inspección y debug

| Método | Para qué |
|--------|----------|
| `execute_query(query, params)` | escape hatch — permite SQL custom dentro de `DataLoader` |
| `get_engine_url()` | retorna la URL para debug |

## Convenciones SQL

### Placeholders nominales
Siempre `:nombre`, nunca `?` ni `%s`. Ejemplo:
```python
query = text("""
    SELECT * FROM gold.fact_ventas
    WHERE fecha_comprobante BETWEEN :desde AND :hasta
""")
df = pd.read_sql(query, engine, params={"desde": fecha_desde, "hasta": fecha_hasta})
```

### Listas como parámetros
psycopg2 NO soporta `ANY(:lista)` con tuple. Construir placeholders dinámicos:
```python
placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
query = f"WHERE generico IN ({placeholders})"
params = {f"gen_{i}": g for i, g in enumerate(genericos)}
```

### JOINs con clave compuesta
`fact_ventas → dim_cliente`:
```sql
LEFT JOIN gold.dim_cliente dc
  ON fv.id_cliente = dc.id_cliente
 AND fv.id_sucursal = dc.id_sucursal
```

### Filtro PRVTA
**`fact_ventas` incluye facturas y presupuestos**. Para excluir presupuestos en reportes de venta efectiva: `AND fv.id_documento != 'PRVTA'`. **Pero algunos reportes específicamente quieren PRVTA** (Histórico Fratelli — fila "Facturas Presupuesto"). NO aplicar el filtro globalmente.

### Filtro `id_fuerza_ventas`
Tablas `cob_preventista_*` requieren `WHERE id_fuerza_ventas = 1` para limitarse a FV1 (canal caliente, asignado a vendedores). Sin el filtro, hay duplicación con FV4.

### Bonificación 100% = regalo
Para excluir regalos del cálculo de venta real: `AND COALESCE(fv.bonificacion, 0) < 100`.

## ETL y origen de datos

Los servicios consumen el esquema `gold` directamente. **El proyecto NO contiene scripts de ETL** — la capa Gold se asume poblada por procesos externos (DBT u otra herramienta corre antes).

`fact_cupos` se carga periódicamente con los objetivos mensuales acordados con CCU/proveedores. La columna `loaded_at` indica la última carga.

## Vista rápida del catálogo

Para inspeccionar el schema gold desde Python:
```python
from src.core.data_loader import DataLoader
from sqlalchemy import text

loader = DataLoader()
with loader.engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='gold' ORDER BY table_name
    """)).fetchall()
    for r in rows:
        print(r[0])
```

Lista actual (Apr 2026):
```
cob_preventista_articulo
cob_preventista_generico
cob_preventista_marca
cob_sucursal_aguas
cob_sucursal_articulo
cob_sucursal_generico
cob_sucursal_lista_generico
cob_sucursal_lista_marca
cob_sucursal_marca
dim_articulo
dim_cliente
dim_deposito
dim_sucursal
dim_tiempo
dim_vendedor
fact_comodatos
fact_cupos
fact_cupos_cobertura
fact_stock
fact_ventas
fact_ventas_contabilidad
```
