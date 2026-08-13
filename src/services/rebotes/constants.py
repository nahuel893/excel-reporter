"""Constants for rebotes report."""

# Mapping de supervisor -> lista de vendedores (case-insensitive match con dim_vendedor.des_vendedor)
SUPERVISOR_VENDOR_MAP: dict[str, list[str]] = {
    "ANOGALES": ["SUB DISTRIBUIDOR"],
    "FGUANTAY": [
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
        "YAPURA GABRIEL",
    ],
    "GFARAH": ["FGUANTAY", "GFARAH", "GFLORES", "VCHAPUR", "DIRECTA"],
    "GFLORES": [
        "EZEQUIEL CACHAGUA",
        "FACUNDO CACERES",
        # "GILDA VELAZCO" ya no figura en dim_vendedor (suc 1, FV1) y no se sabe
        # quien la reemplazo. Queda anotada hasta confirmarlo; borrarla sin mas
        # esconderia el hueco.
        "GILDA VELAZCO",
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