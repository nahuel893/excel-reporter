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
| `gold.dim_cliente` | Clientes | id_cliente, razon_social, fantasia, id_ruta_fv1, id_ruta_fv4, id_sucursal, id_lista_precio, anulado |
| `gold.dim_articulo` | Artículos/Productos | id_articulo, des_articulo, marca, generico, calibre, proveedor, unidad_negocio, factor_hectolitros |
| `gold.dim_deposito` | Depósitos físicos | id_deposito, descripcion, id_sucursal, des_sucursal |
| `gold.dim_lista_precio` | Listas de precios vigentes y futuras | id_lista, titulo, id_segmento_precios, des_segmento, anulada |
| `gold.dim_lista_sucursal` | Relación lista de precios ↔ sucursal | id_lista, id_sucursal |

### Tablas de Hechos

| Tabla | Descripción | Granularidad |
|-------|-------------|--------------|
| `gold.fact_ventas` | Líneas de venta | Una fila por línea de comprobante |
| `gold.fact_stock` | Stock por depósito | Una fila por artículo/depósito/fecha |
| `gold.fact_cupos` | Cupos de ventas por ruta/genérico | Una fila por preventista/genérico/período |
| `gold.fact_cupos_cobertura` | Cupos de cobertura por ruta/marca/genérico | Una fila por apertura/ruta/marca/período |
| `gold.fact_comodatos` | Equipamiento en préstamo a clientes | Una fila por artículo/cliente/comprobante |
| `gold.fact_precio_historico` | Histórico de precios por lista/vigencia | Una fila por lista/vigencia/artículo |
| `gold.fact_precio_vigente` | Precio actualmente vigente por lista/artículo | Una fila por lista/artículo |
| `gold.fact_ventas_contabilidad` | Ventas con detalle contable completo | Una fila por línea de comprobante (más campos que fact_ventas) |

### Tablas de Cobertura (Agregaciones)

| Tabla | Descripción | Granularidad |
|-------|-------------|--------------|
| `gold.cob_preventista_marca` | Cobertura por vendedor/marca | Mensual |
| `gold.cob_preventista_generico` | Cobertura por vendedor/genérico | Mensual |
| `gold.cob_preventista_articulo` | Cobertura por vendedor/grupo de artículos | Mensual |
| `gold.cob_sucursal_marca` | Cobertura por sucursal/marca | Mensual |
| `gold.cob_sucursal_generico` | Cobertura por sucursal/genérico | Mensual |
| `gold.cob_sucursal_articulo` | Cobertura por sucursal/grupo de artículos | Mensual |
| `gold.cob_sucursal_lista_generico` | Cobertura por sucursal/lista de precios/genérico | Mensual |
| `gold.cob_sucursal_lista_marca` | Cobertura por sucursal/lista de precios/marca | Mensual |
| `gold.cob_sucursal_aguas` | Cobertura de AGUAS por subdivisión (SABORIZADAS/MINERAL) | Mensual |

## Campos Importantes

### fact_ventas (Tabla principal de ventas)
```sql
- id                   -- PK interno
- fecha_comprobante    -- Fecha de la venta
- id_sucursal          -- FK a dim_sucursal
- id_vendedor          -- FK a dim_vendedor (clave compuesta con id_sucursal)
- id_cliente           -- FK a dim_cliente
- id_articulo          -- FK a dim_articulo
- id_documento         -- Identificador del comprobante (string, ej: "FACTURA-A")
- letra                -- Letra del comprobante (A, B, C, etc.)
- serie                -- Serie del comprobante (entero)
- nro_doc              -- Número del comprobante (entero)
- anulado              -- Boolean (incluir en consultas, no filtrar por defecto)
- cantidades_con_cargo -- Cantidad con cargo al cliente (unidades)
- cantidades_sin_cargo -- Cantidad sin cargo / bonificada (unidades)
- cantidades_total     -- Cantidad total vendida (con_cargo + sin_cargo)
- cantidad_total_htls  -- Equivalente en hectolitros (para análisis de volumen)
- subtotal_neto        -- Subtotal después de bonificaciones, antes de impuestos
- subtotal_final       -- Subtotal final (incluye todos los conceptos)
- bonificacion         -- Porcentaje o monto de bonificación aplicado
- descuentos           -- Descuentos adicionales aplicados
- facturacion_neta     -- Importe neto facturado
- precio_unitario_bruto -- Precio unitario bruto (sin descuentos)
- fecha_pedido         -- Fecha del pedido original (puede diferir de fecha_comprobante)
```

**Nota**: `fact_ventas` NO tiene columna `id_ruta`. La ruta se obtiene vía
`fact_ventas.id_cliente → dim_cliente.id_ruta_fv1` (o `id_ruta_fv4`).
Para análisis por ruta, usar `get_ventas_diarias_con_ruta()` del DataLoader.

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
- razon_social         -- Razón social (nombre legal del cliente)
- fantasia             -- Nombre de fantasía / nombre comercial del cliente
- des_sucursal         -- Descripción de la sucursal que atiende al cliente
- id_ruta_fv1          -- Ruta asignada en Fuerza de Venta 1
- des_personal_fv1     -- Nombre del preventista FV1 asignado
- id_ruta_fv4          -- Ruta asignada en Fuerza de Venta 4
- des_personal_fv4     -- Nombre del preventista FV4 asignado
- id_lista_precio      -- FK a dim_lista_precio (lista de precios asignada)
- des_lista_precio     -- Descripción de la lista de precios
- anulado              -- Boolean: cliente dado de baja (filtrar con WHERE anulado = false para activos)
- id_canal_mkt         -- ID de canal de marketing
- des_canal_mkt        -- Descripción del canal de marketing
- id_segmento_mkt      -- ID de segmento de marketing
- des_segmento_mkt     -- Descripción del segmento de marketing
- id_subcanal_mkt      -- ID de subcanal de marketing
- des_subcanal_mkt     -- Descripción del subcanal de marketing
- id_ramo              -- ID del ramo comercial
- des_ramo             -- Descripción del ramo comercial
- id_localidad         -- ID de localidad geográfica
- des_localidad        -- Descripción de la localidad
- id_provincia         -- ID de provincia
- des_provincia        -- Descripción de la provincia
- latitud              -- Coordenada latitud (GPS)
- longitud             -- Coordenada longitud (GPS)
- telefono_fijo        -- Teléfono fijo del cliente
- telefono_movil       -- Teléfono móvil del cliente
- id_personal_fv1      -- ID del vendedor FV1 (dim_vendedor)
- id_personal_fv4      -- ID del vendedor FV4 (dim_vendedor)
```

### dim_articulo
```sql
- id_articulo          -- ID del artículo
- des_articulo         -- Descripción completa del artículo
- marca                -- Marca del producto (ej: QUILMES, STELLA ARTOIS)
- generico             -- Categoría genérica (ej: CERVEZAS, AGUAS DANONE)
- calibre              -- Calibre / presentación (ej: 1L, 473CC, RETORNABLE)
- proveedor            -- Proveedor del producto
- unidad_negocio       -- Unidad de negocio del artículo
- factor_hectolitros   -- Factor para convertir unidades a hectolitros (análisis de volumen)
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

## Campos de Tablas Adicionales

### dim_deposito
```sql
- id_deposito          -- PK del depósito
- descripcion          -- Nombre del depósito (ej: DEP CENTRAL SALTA)
- id_sucursal          -- Sucursal a la que pertenece el depósito
- des_sucursal         -- Descripción de la sucursal
```

### dim_lista_precio
```sql
- id_lista             -- PK de la lista de precios
- titulo               -- Nombre descriptivo de la lista
- id_vigencia_actual   -- ID de la vigencia actualmente en curso
- fecha_vigencia_desde -- Fecha de inicio de la vigencia actual
- fecha_vigencia_hasta -- Fecha de fin de la vigencia actual
- id_segmento_precios  -- Segmento de precios al que aplica
- des_segmento         -- Descripción del segmento
- cantidad_clientes    -- Cantidad de clientes asignados a esta lista
- cantidad_articulos   -- Cantidad de artículos cubiertos
- anulada              -- Boolean: lista dada de baja
```

### dim_lista_sucursal
```sql
- id_lista             -- FK a dim_lista_precio
- id_sucursal          -- FK a dim_sucursal
-- Relación N:M entre listas de precios y sucursales
```

### fact_cupos (Cupos de ventas por preventista)
```sql
- id                   -- PK interno
- loaded_at            -- Timestamp de carga ETL
- periodo              -- Período (string 'YYYY-MM')
- proveedor            -- Proveedor del genérico
- id_sucursal          -- FK a dim_sucursal
- sucursal             -- Nombre de la sucursal
- id_ruta              -- ID de ruta del preventista
- descripcion          -- Descripción de la ruta / preventista
- preventista          -- Nombre del preventista
- generico             -- Categoría genérica del cupo
- desagregado          -- Desglose adicional del cupo (opcional)
- cupo                 -- Valor del cupo asignado (numérico)
```

### fact_cupos_cobertura (Cupos de cobertura por apertura)
```sql
- id                   -- PK interno
- loaded_at            -- Timestamp de carga ETL
- periodo              -- Período (string 'YYYY-MM')
- tipo_apertura        -- Tipo de apertura (ej: por_marca, por_generico)
- id_sucursal          -- FK a dim_sucursal
- sucursal             -- Nombre de la sucursal
- id_ruta              -- ID de ruta del preventista
- descripcion_ruta     -- Descripción de la ruta
- preventista          -- Nombre del preventista
- marca                -- Marca del cupo (si aplica)
- generico             -- Genérico del cupo (si aplica)
- cupo                 -- Valor del cupo de cobertura
```

### fact_comodatos (Equipamiento en préstamo)
```sql
- id                   -- PK interno
- comprobante          -- Código del tipo de comprobante
- desc_comprobante     -- Descripción del comprobante (ej: COMODATO)
- id_sucursal          -- FK a dim_sucursal
- numero               -- Número del comprobante de comodato
- fecha                -- Fecha del movimiento
- linea                -- Línea del comprobante
- id_cliente           -- FK a dim_cliente
- id_articulo          -- FK a dim_articulo (equipo en préstamo)
- unidad_negocio       -- Unidad de negocio del artículo
- saldo                -- Saldo actual del comodato (positivo = entregado al cliente)
```

### fact_precio_historico (Histórico de precios por lista)
```sql
- id_lista             -- FK a dim_lista_precio
- id_vigencia          -- ID de la vigencia de precios
- id_articulo          -- FK a dim_articulo
- fecha_vigencia_desde -- Inicio de validez de este precio
- fecha_vigencia_hasta -- Fin de validez (null si es la vigencia actual)
- es_vigente_actual    -- Boolean: es el precio actualmente vigente
- precio               -- Precio base (neto)
- precio_final         -- Precio final al cliente
- precio_sugerido      -- Precio sugerido de venta
- precio_consumidor    -- Precio al consumidor final
- precio_compra        -- Precio de compra (costo)
- iva                  -- Porcentaje de IVA
- internos_fijos       -- Impuestos internos fijos
- bonificacion         -- Bonificación incluida en la lista
- contribucion_neta    -- Contribución neta (precio - costo)
- contribucion_margen  -- Margen de contribución (%)
- anulado              -- Boolean: vigencia anulada
```

### fact_precio_vigente (Precio activo por lista/artículo)
```sql
-- Mismos campos que fact_precio_historico donde es_vigente_actual = true
-- Tabla denormalizada para consultas rápidas del precio actual
- id_lista, id_articulo, id_vigencia (PK compuesta)
- fecha_vigencia_desde
- fecha_ultima_extraccion  -- Última vez que se sincronizó desde el ERP
- precio, precio_final, precio_sugerido, precio_consumidor, precio_compra
- iva, internos_fijos, bonificacion
- contribucion_neta, contribucion_margen
- anulado
```

### fact_ventas_contabilidad (Ventas con detalle contable)
```sql
-- Tabla con el detalle completo contable/logístico de cada línea de venta.
-- Más campos que fact_ventas; usar cuando se necesita información fiscal/contable.
- id                       -- PK interno
- processed_at             -- Timestamp de procesamiento ETL
- id_empresa               -- ID de empresa (multisociedad)
- id_documento             -- Identificador del comprobante
- letra, serie, nro_doc    -- Identificación del comprobante
- anulado                  -- Boolean
- fecha_comprobante        -- Fecha de emisión
- fecha_alta               -- Fecha de alta en sistema
- fecha_pedido             -- Fecha del pedido
- fecha_entrega            -- Fecha de entrega física
- fecha_vencimiento        -- Fecha de vencimiento (crédito)
- fecha_caja               -- Fecha de caja / cobro
- fecha_anulacion          -- Fecha de anulación (si aplica)
- fecha_pago               -- Fecha de pago
- fecha_liquidacion        -- Fecha de liquidación
- fecha_asiento_contable   -- Fecha del asiento contable
- id_sucursal, id_deposito, id_caja
- cajero                   -- Nombre del cajero
- id_centro_costo          -- Centro de costos
- id_vendedor, id_supervisor, id_gerente
- id_fuerza_ventas         -- 1=FV1, 4=FV4
- usuario_alta             -- Usuario que creó el comprobante
- id_cliente               -- FK a dim_cliente
- linea_credito            -- Línea de crédito asignada
- id_canal_mkt, id_segmento_mkt, id_subcanal_mkt
- id_fletero_carga         -- Fletero asignado
- planilla_carga           -- Planilla de carga/reparto
- id_articulo              -- FK a dim_articulo
- es_combo, id_combo       -- Si es artículo combo
- id_pedido                -- FK al pedido de origen
- id_origen, origen        -- Origen del pedido (ERP, WEB, etc.)
- acciones                 -- Acciones aplicadas al comprobante
- cantidades_con_cargo, cantidades_sin_cargo, cantidades_total, cantidades_rechazo
- precio_unitario_bruto, precio_unitario_neto
- bonificacion
- precio_compra_bruto, precio_compra_neto
- subtotal_bruto, subtotal_bonificado, subtotal_neto, subtotal_final
- facturacion_neta
- iva21, iva27, iva105, iva2  -- Impuesto IVA por alícuota
- internos                   -- Impuestos internos
- per3337, percepcion212, percepcion_iibb  -- Percepciones impositivas
- pers_iibb_d, pers_iibb_r, cod_prov_iibb -- IIBB por provincia
- cod_cuenta_contable, nro_asiento_contable, nro_plan_contable
- id_liquidacion           -- FK a liquidación de comisiones
- proveedor                -- Proveedor del artículo
- fvig_pcompra             -- Fecha de vigencia del precio de compra
- id_rechazo               -- FK al rechazo (si fue rechazado)
- informado                -- Boolean: informado a organismos fiscales
- regimen_fiscal           -- Régimen fiscal aplicable
```

### Tablas de Cobertura — Campos Comunes

Todas las tablas `cob_*` comparten esta estructura base:

```sql
- id                   -- PK interno
- periodo              -- Primer día del mes (date, ej: '2025-01-01')
- id_fuerza_ventas     -- 1=FV1, 4=FV4
- id_sucursal          -- FK a dim_sucursal
- ds_sucursal          -- Descripción de la sucursal
- clientes_compradores -- Clientes únicos que compraron en el período
- volumen_total        -- Volumen total vendido (bultos)
```

Campos adicionales según tabla:

| Tabla | Campos extra |
|-------|--------------|
| `cob_preventista_marca` / `cob_preventista_generico` | `id_vendedor`, `id_ruta`, `marca`/`generico` |
| `cob_sucursal_marca` / `cob_sucursal_generico` | `marca`/`generico` |
| `cob_sucursal_lista_marca` / `cob_sucursal_lista_generico` | `marca`/`generico`, `id_lista_precio`, `des_lista_precio` |
| `cob_sucursal_aguas` | `subdivision_aguas` (SABORIZADAS / MINERAL) |
| `cob_preventista_articulo` / `cob_sucursal_articulo` | `nombre_grupo`, `articulos_ids` (array de IDs) |

## Notas Importantes

1. **No filtrar por anulado**: Las ventas anuladas deben incluirse en los cálculos
2. **Usar claves compuestas**: Siempre incluir `id_sucursal` en JOINs con dim_vendedor y dim_cliente
3. **Cobertura no es sumable**: La cobertura de marca A + marca B no es la cobertura total (clientes pueden comprar ambas)
4. **Periodo en cobertura**: Es el primer día del mes (ej: '2025-01-01' para enero 2025)
5. **id_ruta en fact_ventas**: No existe directamente — se obtiene via `dim_cliente.id_ruta_fv1` o `id_ruta_fv4`
6. **fact_ventas vs fact_ventas_contabilidad**: Usar `fact_ventas` para análisis de ventas comerciales; usar `fact_ventas_contabilidad` cuando se necesita detalle fiscal, contable o logístico
7. **clientes activos**: Filtrar `dim_cliente.anulado = false` para excluir clientes dados de baja
8. **Cobertura de AGUAS**: `cob_sucursal_aguas` puede no existir en todos los ambientes; si no existe, se omiten las subdivisiones de aguas
