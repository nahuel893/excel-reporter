"""
Pydantic models for the new config format.

Config structure:
    configs/
    ├── contactos.json       ← global contact catalog
    ├── ventas.json          ← tipo + filtros + reportes[]
    └── resumen_mensual.json ← tipo + filtros + reportes[]
"""
from typing import Any, Literal

from pydantic import BaseModel, model_validator


class ContactInfo(BaseModel):
    """A named contact. At least one channel must be present."""

    email: str | None = None
    telefono: str | None = None
    whatsapp_grupo: str | None = None

    @model_validator(mode="after")
    def at_least_one_channel(self):
        if not any([self.email, self.telefono, self.whatsapp_grupo]):
            raise ValueError(
                "contact must have at least one of: email, telefono, whatsapp_grupo"
            )
        return self


class DeliveryTarget(BaseModel):
    """How a specific contact receives a specific report."""

    via: list[Literal["email", "email_cc", "whatsapp"]]

    @model_validator(mode="after")
    def via_not_empty(self):
        if not self.via:
            raise ValueError("via must have at least one channel")
        return self


class CaptureImageConfig(BaseModel):
    """Config for Excel range screenshot."""

    hoja: str
    rango: str
    renderer: Literal["libreoffice", "html_playwright"] = "libreoffice"


class GlobalFilters(BaseModel):
    """Filters shared across all reports in a config file."""

    fecha_desde: str
    fecha_hasta: str
    genericos: list[str] | None = None
    categorias: dict[str, Any] | None = None
    con_slicers: bool = True
    con_cobertura: bool = True
    enviar_email: bool = True
    enviar_whatsapp: bool = True
    archivo_plantilla: str | None = None
    id_sucursal: int | None = None
    id_fuerza_ventas: int | None = None


class ReportFilters(BaseModel):
    """Per-report filter overrides. All fields optional — None means inherit global."""

    supervisores: list[str] | None = None
    sucursales: list[str] | None = None
    genericos: list[str] | None = None
    con_slicers: bool | None = None
    con_cobertura: bool | None = None
    enviar_email: bool | None = None
    enviar_whatsapp: bool | None = None


class ReportEntry(BaseModel):
    """One report to generate, with its own filters and delivery mapping."""

    nombre: str
    filtros: ReportFilters | None = None
    capture_image: CaptureImageConfig | None = None  # legacy, single
    capture_images: list[CaptureImageConfig] | None = None  # N captures per report
    enviar_a: dict[str, DeliveryTarget] | None = None
    asunto_email: str | None = None

    @model_validator(mode="after")
    def normalize_captures(self):
        # If both provided, plural wins and singular is cleared to avoid confusion.
        if self.capture_images and self.capture_image is not None:
            self.capture_image = None
        return self


class ReportConfig(BaseModel):
    """Top-level structure of a report config file (e.g. ventas.json)."""

    tipo: Literal["ventas", "resumen-mensual", "mision-imposible", "historico-fratelli", "stock-diario", "cartesiano", "avances", "graficos-cobertura"]
    filtros: GlobalFilters
    reportes: list[ReportEntry]

    def validate_contacts(self, contactos: dict[str, ContactInfo]) -> None:
        """Validate that all referenced contacts exist in the catalog."""
        for report in self.reportes:
            if report.enviar_a:
                for contact_name in report.enviar_a:
                    if contact_name not in contactos:
                        raise ValueError(
                            f"report '{report.nombre}' references unknown contact "
                            f"'{contact_name}'. Available: {list(contactos.keys())}"
                        )
