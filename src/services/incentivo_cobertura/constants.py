"""Constants — targets del incentivo de cobertura ON PREMISE.

Cada target define una marca lógica con su criterio de matcheo SQL y
el objetivo de clientes únicos por vendedor.
"""

# Lista de precio que define ON PREMISE en gold.dim_cliente.id_lista_precio
ID_LISTA_PRECIO_ON_PREMISE = 4

# id_sucursal CASA CENTRAL
ID_SUCURSAL_CASA_CENTRAL = 1

# Targets del incentivo (vigente hasta 13/06/2026).
# Cada target tiene:
#   - label: nombre visible en el Excel
#   - sql_where: predicado SQL sobre dim_articulo (da.* alias)
#   - objetivo: cantidad de clientes únicos requerida por vendedor
INCENTIVO_TARGETS: list[dict] = [
    {
        "label": "O-61",
        "sql_where": "da.marca = 'O-61'",
        "objetivo": 10,
    },
    {
        "label": "LA CELIA",
        "sql_where": "da.marca = 'LA CELIA'",
        "objetivo": 10,
    },
    {
        "label": "COLON DULCES",
        "sql_where": "da.marca = 'COLON' AND da.des_articulo ILIKE '%DULCE%'",
        "objetivo": 5,
    },
    {
        "label": "FULL SPORT",
        "sql_where": "da.marca = 'FULL SPORT'",
        "objetivo": 10,
    },
]
