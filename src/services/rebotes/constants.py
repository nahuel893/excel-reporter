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
        "DARIO LUPATY",
        "EZEQUIEL CACHAGUA",
        "FACUNDO CACERES",
        "GILDA VELAZCO",
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