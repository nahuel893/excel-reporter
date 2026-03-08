# Contexto del Data Warehouse - Medallion ETL

## Resumen del Proyecto

Este es un Data Warehouse construido con **arquitectura Medallion** (Bronze → Silver → Gold) que extrae datos de un ERP de distribución comercial (Chess ERP) y los transforma para análisis.

## Arquitectura de Capas

```
Bronze (Raw)     →     Silver (Clean)     →     Gold (Analytics)
─────────────────────────────────────────────────────────────────
Datos crudos JSON      Datos normalizados      Modelo dimensional
Sin transformación     Tipados y limpios       Star Schema
```

## Esquema Gold (Usar para consultas)

La capa **Gold** es la recomendada para consultas analíticas. Contiene un modelo dimensional (star schema).

### Tablas de Dimensiones

| Tabla | Descripción | Campos clave |
|-------|-------------|--------------|
| `gold.dim_tiempo` | Calendario | fecha, dia, mes, anio, trimestre |
| `gold.dim_sucursal` | Sucursales/Locales | id_sucursal, descripcion |
| `gold.dim_vendedor` | Preventistas/Vendedores | id_vendedor, des_vendedor, id_fuerza_ventas, id_sucursal |
| `gold.dim_cliente` | Clientes | id_cliente, razon_social, id_ruta_fv1, id_ruta_fv4, id_sucursal |
| `gold.dim_articulo` | Artículos/Productos | id_articulo, des_articulo, marca, generico |

### Tablas de Hechos

| Tabla | Descripción | Granularidad |
|-------|-------------|--------------|
| `gold.fact_ventas` | Líneas de venta | Una fila por línea de comprobante |
| `gold.fact_stock` | Stock por depósito | Una fila por artículo/depósito/fecha |

### Tablas de Cobertura (Agregaciones)

| Tabla | Descripción | Granularidad |
|-------|-------------|--------------|
| `gold.cob_preventista_marca` | Cobertura por vendedor/marca | Mensual |
| `gold.cob_sucursal_marca` | Cobertura por sucursal/marca | Mensual |
| `gold.cob_preventista_generico` | Cobertura por vendedor/genérico | Mensual |

## Campos Importantes

### fact_ventas (Tabla principal de ventas)
```sql
- fecha_comprobante     -- Fecha de la venta
- id_sucursal          -- FK a dim_sucursal
- id_vendedor          -- FK a dim_vendedor (clave compuesta con id_sucursal)
- id_cliente           -- FK a dim_cliente
- id_articulo          -- FK a dim_articulo
- cantidades_total     -- Cantidad vendida (unidades)
- importe_total        -- Monto total de la línea
- anulado              -- Boolean (incluir en consultas, no filtrar)
```

### dim_vendedor
```sql
- id_vendedor          -- ID del vendedor (único por sucursal)
- id_sucursal          -- Sucursal a la que pertenece
- des_vendedor         -- Nombre del vendedor
- id_fuerza_ventas     -- 1=FV1 (Preventa), 4=FV4 (Autoventa)
```

### dim_cliente
```sql
- id_cliente           -- ID del cliente
- id_sucursal          -- Sucursal que lo atiende
- razon_social         -- Nombre del cliente
- id_ruta_fv1          -- Ruta asignada en Fuerza de Venta 1
- id_ruta_fv4          -- Ruta asignada en Fuerza de Venta 4
```

### dim_articulo
```sql
- id_articulo          -- ID del artículo
- des_articulo         -- Descripción completa
- marca                -- Marca del producto
- generico             -- Categoría genérica del producto
```

## Claves Compuestas (Importante)

Los IDs de vendedor, cliente y ruta **NO son únicos globalmente**. Son únicos **por sucursal**:

```sql
-- CORRECTO: JOIN con clave compuesta
JOIN gold.dim_vendedor dv
  ON fv.id_vendedor = dv.id_vendedor
  AND fv.id_sucursal = dv.id_sucursal

-- INCORRECTO: JOIN solo por ID
JOIN gold.dim_vendedor dv ON fv.id_vendedor = dv.id_vendedor
```

## Fuerzas de Venta

Las fuerzas de venta son **grupos de preventistas que venden distintos artículos**. Cada fuerza vende genéricos específicos:

| Fuerza | id_fuerza_ventas | Genéricos que vende |
|--------|------------------|---------------------|
| FV1 | 1 | CERVEZAS, AGUAS DANONE, VINOS CCU, SIDRAS Y LICORES |
| FV4 | 4 | FRATELLI B, VINOS, JUGOS, VINOS FINOS |

Un mismo cliente puede ser atendido por diferentes fuerzas de venta, cada una con su propia ruta asignada:

- `id_ruta_fv1`: Ruta asignada al cliente para Fuerza de Venta 1
- `id_ruta_fv4`: Ruta asignada al cliente para Fuerza de Venta 4

Las fuerzas de venta son independientes entre sí, pero un mismo cliente puede comprarle a múltiples fuerzas.

## Consultas de Ejemplo

### Ventas por Sucursal/Año/Mes/Genérico
```sql
SELECT
    fv.id_sucursal,
    ds.descripcion AS sucursal,
    EXTRACT(YEAR FROM fv.fecha_comprobante) AS anio,
    EXTRACT(MONTH FROM fv.fecha_comprobante) AS mes,
    da.generico,
    SUM(fv.cantidades_total) AS volumen_total,
    SUM(fv.importe_total) AS importe_total
FROM gold.fact_ventas fv
LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
GROUP BY fv.id_sucursal, ds.descripcion, anio, mes, da.generico
ORDER BY fv.id_sucursal, anio, mes, volumen_total DESC;
```

### Ventas por Vendedor/Marca
```sql
SELECT
    fv.id_sucursal,
    ds.descripcion AS sucursal,
    fv.id_vendedor,
    dv.des_vendedor,
    EXTRACT(YEAR FROM fv.fecha_comprobante) AS anio,
    EXTRACT(MONTH FROM fv.fecha_comprobante) AS mes,
    da.marca,
    SUM(fv.cantidades_total) AS volumen_total
FROM gold.fact_ventas fv
LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
LEFT JOIN gold.dim_vendedor dv ON fv.id_vendedor = dv.id_vendedor
    AND fv.id_sucursal = dv.id_sucursal
GROUP BY fv.id_sucursal, ds.descripcion, fv.id_vendedor, dv.des_vendedor, anio, mes, da.marca
ORDER BY fv.id_sucursal, fv.id_vendedor, anio, mes, volumen_total DESC;
```

### Cobertura (Clientes únicos que compraron)
```sql
SELECT
    fv.id_sucursal,
    ds.descripcion AS sucursal,
    EXTRACT(YEAR FROM fv.fecha_comprobante) AS anio,
    EXTRACT(MONTH FROM fv.fecha_comprobante) AS mes,
    da.marca,
    COUNT(DISTINCT fv.id_cliente) AS clientes_compradores,
    SUM(fv.cantidades_total) AS volumen_total
FROM gold.fact_ventas fv
LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
WHERE fv.cantidades_total > 0
GROUP BY fv.id_sucursal, ds.descripcion, anio, mes, da.marca
ORDER BY fv.id_sucursal, anio, mes, clientes_compradores DESC;
```

### Consultar tablas de cobertura pre-calculadas
```sql
-- Cobertura por preventista/marca (ya calculada)
SELECT * FROM gold.cob_preventista_marca
WHERE periodo = '2025-01-01'
ORDER BY id_sucursal, id_vendedor, volumen_total DESC;

-- Cobertura por sucursal/marca
SELECT * FROM gold.cob_sucursal_marca
WHERE periodo = '2025-01-01'
ORDER BY id_sucursal, volumen_total DESC;
```

## Notas Importantes

1. **No filtrar por anulado**: Las ventas anuladas deben incluirse en los cálculos
2. **Usar claves compuestas**: Siempre incluir `id_sucursal` en JOINs con dim_vendedor y dim_cliente
3. **Cobertura no es sumable**: La cobertura de marca A + marca B no es la cobertura total (clientes pueden comprar ambas)
4. **Periodo en cobertura**: Es el primer día del mes (ej: '2025-01-01' para enero 2025)
