"""Chart-domain constants for graficos-cobertura.

IMPORTANT: This service uses its OWN zone scheme (5 zones based on sucursal-id
lists and preventista-ruta reassignment). It does NOT use
config/settings.py::ZONAS_VIRTUALES (which splits CASA CENTRAL by fact_ventas
id_ruta — different semantics, different data source).
"""
from __future__ import annotations

MESES: list[str] = [
    "Ene", "Feb", "Mar", "Abr", "May", "Jun",
    "Jul", "Ago", "Sept", "Oct", "Nov", "Dic",
]

MAX_MARCAS: int = 10

GENERICOS_INCLUIDOS: list[str] = [
    "CERVEZAS",
    "AGUAS SABORIZADAS",
    "AGUAS MINERAL",
    "SIDRAS Y LICORES",
    "VINOS CCU",
]

MARCAS_POR_GENERICO: dict[str, list[str]] = {
    "CERVEZAS": ["SALTA", "HEINEKEN", "IMPERIAL", "SCHNEIDER", "AMSTEL"],
}

# Subdivision of AGUAS DANONE: pseudo-generico -> marca list
SUBDIVISION_AGUAS: dict[str, list[str]] = {
    "AGUAS SABORIZADAS": ["LEVITE", "SER", "BRIO", "FULL SPORT"],
    "AGUAS MINERAL": ["VILLA DEL SUR", "VILLAVICENCIO"],
}

# Sucursales per zone (for filtering cob_sucursal_aguas)
ZONA_SUCS_AGUAS: dict[str, list[int] | None] = {
    "NOA NORTE": None,
    "SALTA CAPITAL": [1],
    "INTERIOR SALTA SUR": [3, 4, 5, 16],
    "INTERIOR SALTA NORTE": [6, 7],
    "JUJUY INTERIOR": [9, 10, 11, 12, 13, 14, 15],
}

# Rutas reassigned from suc 1 (Valle Salta) into suc 16
RUTAS_A_SUC16: list[int] = [85, 86, 87, 88, 118, 119]

SUCS_INTERIOR: list[int] = [3, 4, 5, 16]
SUCS_SALTA_NORTE: list[int] = [6, 7]
SUCS_JUJUY: list[int] = [9, 10, 11, 12, 13, 14, 15]

ZONAS: list[str] = [
    "NOA NORTE",
    "SALTA CAPITAL",
    "INTERIOR SALTA SUR",
    "INTERIOR SALTA NORTE",
    "JUJUY INTERIOR",
]

ZONA_SLUGS: dict[str, str] = {
    "NOA NORTE": "noa_norte",
    "SALTA CAPITAL": "salta_capital",
    "INTERIOR SALTA SUR": "interior_salta_sur",
    "INTERIOR SALTA NORTE": "interior_salta_norte",
    "JUJUY INTERIOR": "jujuy_interior",
}

COLORES_MARCA: dict[str, str] = {
    "SALTA": "#1565C0",
    "SCHNEIDER": "#F5A623",
    "HEINEKEN": "#4CAF50",
    "IMPERIAL": "#F8E71C",
    "AMSTEL": "#D0421B",
    "VILLA DEL SUR": "#B0B0B0",
    "VILLAVICENCIO": "#F5A623",
    "BRIO": "#4CAF50",
    "LEVITE": "#D0421B",
    "FULL SPORT": "#F8E71C",
    "SER": "#4A90D2",
    "SAENZ BRIONES": "#B0B0B0",
    "LA VICTORIA": "#F5A623",
    "REAL": "#D0421B",
    "EL ABUELO": "#4CAF50",
    "PEHUENIA": "#F8E71C",
    "MISTRAL": "#4A90D2",
    "CONTROL C": "#BD10E0",
    "COLON": "#B0B0B0",
    "LA CELIA": "#F5A623",
    "EUGENIO BUSTOS": "#D0421B",
    "GRAFFIGNA": "#4CAF50",
    "SANTA SILVIA": "#F8E71C",
    "O-61": "#4A90D2",
}

FALLBACK_COLORS: list[str] = [
    "#B0B0B0", "#F5A623", "#D0421B", "#4CAF50", "#F8E71C",
    "#4A90D2", "#BD10E0", "#50E3C2", "#B8E986", "#8B572A",
]

COLORES_LINEAS: dict[int, str] = {
    2024: "#7B1FA2",
    2025: "#E65100",
    2026: "#2E7D32",
}

MARCADORES_LINEAS: dict[int, str] = {
    2024: "D",
    2025: "o",
    2026: "s",
}

# PPTX layout
PPTX_FONT_NAME: str = "Calibri"
PPTX_TITLE_COLOR: tuple[int, int, int] = (0x2E, 0x7D, 0x32)
PPTX_SLIDE_WIDTH_IN: float = 13.333
PPTX_SLIDE_HEIGHT_IN: float = 7.5

# File naming
PPTX_GENERICO_FILENAME: str = "cobertura_todos.pptx"
XLSX_FILENAME: str = "resumen.xlsx"
PNG_SUBDIR: str = "png"
