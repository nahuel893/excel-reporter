"""Constants for rebotes report."""

# Mapping de supervisor -> lista de vendedores (case-insensitive match con dim_vendedor.des_vendedor)
#
# Fuente: mapeo oficial que pasa el negocio, ultima version 2026-08-14.
# NO se deriva de dim_vendedor.supervisor: esa columna difiere a proposito
# (ver las notas de ANOGALES y RUBEN TORRES mas abajo). Ante una diferencia,
# manda el mapeo oficial.
SUPERVISOR_VENDOR_MAP: dict[str, list[str]] = {
    # El oficial confirma SUB DISTRIBUIDOR bajo ANOGALES. dim_vendedor.supervisor
    # se lo asigna a FACUNDO GUANTAY; esa fila de la base esta desactualizada.
    "ANOGALES": ["SUB DISTRIBUIDOR"],
    "FGUANTAY": [
        # Baja 2026-08-14: "YAPURA GABRIEL" salio del equipo y el oficial no lo
        # reasigna a ningun supervisor. Sigue en dim_vendedor bajo GUANTAY.
        # Idem "RUBEN TORRES" (id 16), que la base pone aca y el oficial no lista:
        # nunca estuvo en este mapa, asi que hoy queda sin supervisor en el informe.
        "AGUIRRE ETHEL",
        "GONZALEZ INES",
        "LORENA TARITOLAY",
        "PABLO GUAYMAS",
        "RAMIREZ RUBEN",
        "RICARDO GUTIERREZ",
        "ROBLEDO JUAN",
        "ROBLES ORLANDO",
        "SEBASTIAN PIZARRO",
        "SUSANA GONZALEZ",
    ],
    "GFARAH": ["FGUANTAY", "GFARAH", "GFLORES", "VCHAPUR", "DIRECTA"],
    "GFLORES": [
        # Baja 2026-08-14: "GILDA VELAZCO" salio del equipo. Tampoco figuraba ya
        # en dim_vendedor. El oficial NO la reemplaza por nadie — en particular,
        # no por "RUIZ MARCELO" (id 21), que la base pone en este equipo pero el
        # mapeo oficial no lista.
        "EZEQUIEL CACHAGUA",
        "FACUNDO CACERES",
        # Era "DARIO LUPATY": mismo id_vendedor (11), le cambiaron el nombre en
        # el maestro. El match de este mapa es por TEXTO contra
        # dim_vendedor.des_vendedor, asi que con el nombre viejo el preventista
        # quedaba sin supervisor y su fila salia vacia.
        "LUCIANO GUZMAN",
        "MARTIN SUAREZ",
        "MATIAS AGUIRRE",
        "NORMA CACHARI",
        "PATRICIA CARRIZO",
        "PEREIRA ARMANDO",
        "ROXANA CASIMIRO",
        "SANTIAGO ORQUERA",
    ],
    "VCHAPUR": [
        "CRUZ IGNACIO",
        "DELGADO VILTE",
        "GUANCA LUIS",
        "JUAN JOSE BARRIOS",
        "MARCELA ASTORGA",
        "MAXIMILIANO JORQUERA",
        "NAHUEL RUEDA",
        "NESTOR ROSSI",
    ],
}