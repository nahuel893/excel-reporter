---
name: historico-cliente-badie
description: "Genera el histórico de compras por marca de uno o varios clientes de Distribuidora Badie: bultos mes a mes abiertos por genérico y marca, una hoja por cliente, con las marcas del universo CCU que el cliente NO compró marcadas en gris y un total por año cuando la ventana cruza más de un año. El rango es parametrizable (últimos N meses, años calendario, o fechas explícitas). Entrega un Excel y, para ventanas cortas, una imagen PNG lista para mandar por WhatsApp. Usar cuando pidan las ventas, las compras o el histórico de un cliente o de una lista de clientes, identificados por código o por nombre — por ejemplo 'las ventas del cliente 7255', 'qué compró El Encuentro', 'histórico de Jorgito', 'el histórico 2024 2025 2026 de estos tres códigos', 'cuánta cerveza lleva este mes tal cliente'."
version: 1.0.0
metadata:
  hermes:
    tags: [badie, ventas, clientes, excel, whatsapp, reporting]
---

# Histórico de compras por cliente — Distribuidora Badie

Un comando genera el informe completo. **No armes un JSON de configuración a
mano ni invoques `main.py` directamente**: el wrapper decide el universo de
marcas, la clave del cliente y el rango de captura, que son justamente las
tres cosas que salen mal en silencio cuando se componen a mano.

## Comando

```bash
cd "/home/nahuel/projects/work/Informes Badie"
.venv/bin/python scripts/historico_cliente_cli.py --cliente <ID> [más IDs] [opciones]
```

| Opción | Qué hace |
|---|---|
| `--cliente ID [ID...]` | **Obligatorio.** Uno o más códigos: **una hoja por código**, en ese orden. Sufijo `ID:SUC` fija la sucursal de ese código. |
| `--meses N` | Meses hacia atrás, incluido el actual. Default 12. |
| `--anios AAAA [AAAA...]` | Años calendario completos. `--anios 2024 2025 2026` arranca el 1/1/2024. Nunca proyecta al futuro: un año en curso corta hoy. |
| `--desde` / `--hasta` | Fechas explícitas `YYYY-MM-DD`. Ganan sobre `--anios` y `--meses`. |
| `--solo-con-cargo` | Cuenta solo unidades facturadas; excluye las bonificadas al 100%. |
| `--sin-imagen` | Omite los PNG. Útil si solo necesitás los números: ahorra 30-60s por hoja. |
| `--nombre` | Nombre del archivo de salida. |

Varios clientes van a **un solo Excel con una hoja cada uno**, no a un archivo
por cliente: así el lote viaja como un adjunto y las hojas se comparan entre sí.

Devuelve un JSON en stdout:

```json
{"ok": true,
 "xlsx": "/ruta/archivo.xlsx",
 "hojas": [{"hoja": "EL ENCUENTRO", "rango": "A1:O51",
            "png": "/ruta/imagen.png", "total_general": 625.58360004}],
 "sin_datos": [],
 "clientes": [{"id_cliente": 7255, "id_sucursal": 1, "nombre": "EL ENCUENTRO"}],
 "desde": "2025-09-01", "hasta": "2026-08-11", "solo_con_cargo": true}
```

`sin_datos` lista los clientes pedidos que no tuvieron ventas en la ventana y
por lo tanto no generaron hoja. **Revisalo siempre** y mencionalos: en un lote
grande, una hoja faltante pasa desapercibida.

Ante un error devuelve `{"ok": false, "error": "..."}` y sale con código 1.
Parseá el JSON; no interpretes el texto suelto.

## Si te dan un nombre en vez de un código

El comando toma códigos. Para resolver un nombre, consultá primero:

```sql
SELECT id_cliente, id_sucursal,
       COALESCE(NULLIF(TRIM(fantasia), ''), NULLIF(TRIM(razon_social), '')) AS nombre
FROM gold.dim_cliente
WHERE fantasia ILIKE '%texto%' OR razon_social ILIKE '%texto%'
ORDER BY id_cliente;
```

`fantasia` a veces es string vacío en vez de NULL — por eso el `NULLIF(TRIM(...))`.

**Si hay más de un resultado, preguntá cuál.** Nunca elijas por tu cuenta.

## Reglas que no se negocian

**El código de cliente NO es único.** El mismo `id_cliente` se reusa entre
sucursales. La clave real es el par `(id_cliente, id_sucursal)`. Si el comando
responde que es ambiguo, listale las sucursales al usuario y que elija; no
adivines.

**Nunca redondees los números.** Los bultos vienen con decimales reales
(medio bulto es 0.5, un doceavo es 0.083). Reportá lo que devuelve el JSON.

**Por default se suma TODO: con cargo más sin cargo. No agregues
`--solo-con-cargo` por tu cuenta.**

Solo usalo cuando el pedido lo diga explícitamente: "sin los sin cargo",
"solo lo facturado", "solo lo que pagó" o equivalente. Un pedido puntual de
alguien no convierte el filtro en la norma para los siguientes.

La diferencia es real —del orden del 6-7% del total, y puede superar el 15% en
un mes suelto—, así que al informar decí sobre qué base está el número. Cuando
el filtro está activo, el subtítulo de la hoja lo declara; cuando suma todo, no
dice nada porque no hay nada que aclarar.

## Qué entregar

Con **un cliente y hasta ~12 meses**: mandá la imagen PNG. Es el cuadro
formateado, listo para leer en el teléfono.

Con **varios clientes o ventanas largas** (2-3 años son 24-36 columnas de mes):
mandá el **xlsx**. Esa imagen entra en el teléfono tan achicada que no se lee.

La imagen ya trae adentro el nombre del cliente, el período y la base de
cálculo, así que se entiende sola aunque la reenvíen fuera de la conversación.

## Cómo leer el cuadro

- Una fila por marca, agrupadas por genérico. Columnas: un mes cada una, más `Total`.
- Si la ventana cruza más de un año calendario, aparece una columna
  `Total AAAA` **al final de los meses de cada año**, con un tinte propio.
  Dentro de un solo año no se agrega: el `Total` ya es el total del año.
- **Filas en gris**: marcas del universo CCU que el cliente **no compró** en
  el período. Son los huecos de venta — suelen ser lo más accionable del informe.
- Fila azul por genérico: subtotal. Fila navy al pie: `TOTAL GENERAL`.
- Si el último mes es parcial (mes en curso), el subtítulo lo aclara con las
  fechas exactas. No lo compares contra meses completos sin avisarlo.

## Cuándo NO usar esta skill

- Ventas por sucursal, por vendedor, por ruta o por artículo: no es este informe.
- Cobertura (conteo de clientes distintos): es otro cálculo, no es aditivo
  entre períodos ni entre marcas.
- Stock, cupos, objetivos: otros servicios.

En esos casos decilo, no fuerces este informe.

## Errores frecuentes

| Mensaje | Qué hacer |
|---|---|
| `No existe el cliente N en dim_cliente` | Código equivocado. Buscá por nombre. |
| `existe en varias sucursales` | Mostrale las opciones y repreguntá. |
| `no tiene ventas entre X e Y` | Sin movimientos en la ventana. Probá `--meses` más grande. |
| `LibreOffice las renderiza como ###` | Bug de layout. **No mandes la imagen**, avisá. |

El comando tarda 30-60s con imagen — casi todo es el renderizado. Avisale al
usuario que lo estás generando en vez de dejarlo esperando en silencio.
