"""
Pydantic models for the new config format.

Config structure:
    configs/
    ├── contactos.json       ← global contact catalog
    ├── ventas.json          ← tipo + filtros + reportes[]
    └── resumen_mensual.json ← tipo + filtros + reportes[]
"""
from typing import Any, Literal


WhatsAppEnviarComo = Literal["imagen", "archivo", "ambos"]

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
    rango: str  # A1 range or the sentinel "auto:bordes"
    renderer: Literal["libreoffice", "html_playwright"] = "libreoffice"
    caption: str | None = None  # image label (nombres_hojas / WhatsApp caption)
    caption_anchor: str | None = None  # A1 override (relative to each detected region) for the caption cell
    caption_header: str | None = None  # header label to scan for; caption = value of the cell directly below it
    recortar: bool = False  # crop the rendered PNG to `rango` (only meaningful for non-"auto:bordes" ranges)


class GlobalFilters(BaseModel):
    """Filters shared across all reports in a config file."""

    fecha_desde: str
    fecha_hasta: str
    genericos: list[str] | None = None
    categorias: dict[str, Any] | None = None
    con_slicers: bool = True
    con_cobertura: bool = True
    con_montos: bool = True
    enviar_email: bool = True
    enviar_whatsapp: bool = True
    archivo_plantilla: str | None = None
    tipo_plantilla: Literal["branca", "badie", "guemes"] = "branca"
    # avances: contact name (from contactos catalog) or raw phone to notify with
    # the month's applied holidays. None disables the notification.
    notificar_feriados_a: str | None = None
    id_sucursal: int | None = None
    id_fuerza_ventas: int | None = None
    id_articulo: int | None = None
    whatsapp_enviar_como: WhatsAppEnviarComo = "imagen"
    whatsapp_caption_imagenes: bool = True
    email_adjuntos: list[str] = ["excel"]  # ["excel"] | ["imagen"] | ["excel", "imagen"]
    detalle_movimientos_path: str | None = None  # Path to detalle_movimientos.xlsx for merge import
    detalle_movimientos_ma_path: str | None = None    # Mes anterior — imported as separate sheet
    detalle_movimientos_mmaa_path: str | None = None  # Mismo mes año anterior — imported as separate sheet
    categorias_deposito_path: str | None = None       # Path to JSON con master-data {codigo, concatenar, division} para hoja "Categorias"
    # Genericos for which fact_ventas.id_documento='PRVTA' is excluded (resumen-mensual)
    genericos_sin_prvta: list[str] | None = None
    # Mapping {generico: [marcas]} for split-by-marca (resumen-mensual)
    marca_splits: dict[str, list[str]] | None = None
    # Cupos hardcodeados {sucursal: {generico: cupo}} — se concatenan al df_cupos
    # antes del merge final. Útil para sucursales que no se cargan en fact_cupos.
    cupos_manuales: dict[str, dict[str, float]] | None = None
    # avances: si True, el daily solo entrega el reporte cuando los cupos
    # (objetivo) del mes ya están cargados en gold. Ver run_daily _objetivo_gate.
    esperar_objetivo: bool = False
    # acciones-comerciales: directorio con wapi.xlsx + compras.xls (RF-02/RF-03)
    input_dir: str | None = None
    # acciones-comerciales: master gate para CUALQUIER escritura en el INFORME
    # externo (Fase 2). Debe arrancar en False (RF-13) hasta el sign-off
    # (Decision 7) de S1-S4.
    escribir_informe: bool = False
    # acciones-comerciales: ruta al INFORME externo .xlsm/.xlsx (nunca tocado
    # mientras escribir_informe sea False)
    informe_path: str | None = None
    # acciones-comerciales: opt-in al gate de frescura de wapi en run_daily (RF-20)
    esperar_wapi_fresco: bool = False
    # acciones-comerciales: umbral de frescura configurable (RF-20, Decision 16)
    wapi_cobertura_requerida: str | None = None
    # acciones-comerciales: directorio con el backup manual (backup.xlsx +
    # known_defects.json) para el diff paralelo Fase-1 (RF-12, S4). None => diff
    # deshabilitado.
    backup_dir: str | None = None
    # acciones-comerciales: ruta al aexcel.xlsx real para validar el pick de
    # precio por terna contra la fuente (RF-12/Decision 14). None => sin validación.
    aexcel_path: str | None = None


class ReportFilters(BaseModel):
    """Per-report filter overrides. All fields optional — None means inherit global."""

    supervisores: list[str] | None = None
    sucursales: list[str] | None = None
    genericos: list[str] | None = None
    con_slicers: bool | None = None
    con_cobertura: bool | None = None
    con_montos: bool | None = None
    enviar_email: bool | None = None
    enviar_whatsapp: bool | None = None
    id_articulo: int | None = None
    id_sucursal: int | None = None
    clientes: list[dict] | None = None      # each dict: {"id_cliente": int, "id_sucursal": int}
    articulos: list[int] | None = None      # list of id_articulo
    marcas: list[str] | None = None         # list of marca names
    agrupar_por_generico: bool | None = None  # historico-cliente: all marcas grouped by generico
    marcas_completas: bool | None = None      # historico-cliente: fill full marca universe (0 if not bought)
    genericos_universo: list[str] | None = None  # genericos whose full marca set defines the universe


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

    tipo: Literal["ventas", "resumen-mensual", "champions-league", "historico-fratelli", "stock-diario", "cartesiano", "avances", "graficos-cobertura", "ventas-articulo", "historico-cliente", "reporte-general-badie", "reporte-rebotes", "reporte-incentivo-cobertura", "reporte-descuentos", "subdistribuidores", "stock-suria", "ventas-marca", "ventas-cober-preventista-marca", "acciones-comerciales"]
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
