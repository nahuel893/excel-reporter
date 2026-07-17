"""
DeliveryPipeline - Orquestacion de entrega automatizada de reportes.

El pipeline ejecuta pasos configurables (captura de imagen, email, WhatsApp)
de forma secuencial. Cada paso falla de forma aislada: si uno falla, los
demas siguen ejecutandose.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Config models — Pydantic para validacion al parsear el JSON de configuracion
# ---------------------------------------------------------------------------

class CaptureConfig(BaseModel):
    """Configuracion para captura de rango Excel como imagen."""
    hoja: str
    rango: str  # Ej: "A1:H20" o el sentinel "auto:bordes"
    renderer: str = "libreoffice"  # backend key, resolved by excel_renderers.get_renderer
    caption: str | None = None  # etiqueta de la imagen (nombres_hojas / WhatsApp caption)
    caption_anchor: str | None = None  # override A1 (relativo a la region) de donde leer el caption
    caption_header: str | None = None  # etiqueta de encabezado a buscar; caption = celda directamente debajo
    recortar: bool = False  # recorta el PNG renderizado a `rango` (solo aplica a rangos fijos, no "auto:bordes")


class EmailConfig(BaseModel):
    """Configuracion para envio por email."""
    destinatarios: list[str]
    cc: list[str] = []
    asunto: str | None = None
    adjuntos: list[Literal["excel", "imagen"]] = ["excel"]

    @field_validator("adjuntos")
    @classmethod
    def adjuntos_no_vacios(cls, v: list) -> list:
        if len(v) == 0:
            raise ValueError("adjuntos no puede estar vacio")
        return v


class Recipient(BaseModel):
    """Metadata de un destinatario WhatsApp para personalizar captions."""
    target: str           # JID/numero/grupo enviado al wpp-service
    is_group: bool = False
    contact_name: str | None = None


class WhatsAppConfig(BaseModel):
    """Configuracion para envio por WhatsApp."""
    grupos: list[str]  # Nombres de grupos o contactos individuales (legacy / cardinal)
    enviar_como: Literal["imagen", "archivo", "ambos"] = "imagen"
    caption_imagenes: bool = True
    # Opcional: metadata paralela a `grupos` para personalizar captions.
    # Misma longitud y orden que `grupos`. Si esta vacia, se usa caption default.
    recipients_meta: list[Recipient] = []


class DeliveryConfig(BaseModel):
    """Configuracion completa del pipeline de entrega."""
    capture_image: CaptureConfig | None = None  # legacy singular (use capture_images)
    capture_images: list[CaptureConfig] = []     # N captures per report
    email: EmailConfig | None = None
    whatsapp: WhatsAppConfig | None = None
    log_steps: bool = True


# ---------------------------------------------------------------------------
# Runtime dataclasses — resultados internos, no requieren validacion Pydantic
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """Resultado de la ejecucion de un paso del pipeline."""
    status: Literal["success", "skipped", "error", "partial"]
    step_name: str
    message: str = ""
    artifact_path: Path | None = None


@dataclass
class PipelineResult:
    """Resultado de la ejecucion completa del pipeline."""
    steps: list[StepResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(s.status not in ("error", "partial") for s in self.steps)


@dataclass
class ReportArtifact:
    """Artefactos generados por un reporte (archivos en disco)."""
    ruta_excel: Path
    rutas_imagenes: list[Path] = field(default_factory=list)
    nombres_hojas: list[str] = field(default_factory=list)  # paralelo a rutas_imagenes — sheet de cada imagen
    metadata: dict = field(default_factory=dict)

    @property
    def ruta_imagen(self) -> Path | None:
        """Legacy single-image accessor — returns first if any, else None."""
        return self.rutas_imagenes[0] if self.rutas_imagenes else None

    @ruta_imagen.setter
    def ruta_imagen(self, path: Path | None) -> None:
        """Legacy setter — replaces list with [path] or empty."""
        self.rutas_imagenes = [path] if path is not None else []


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class DeliveryStep(ABC):
    """Paso del pipeline de entrega. Cada paso debe implementar execute()."""

    @abstractmethod
    def execute(
        self,
        artifact: ReportArtifact,
        config: DeliveryConfig,
        logger: logging.Logger,
    ) -> StepResult:
        """Ejecuta el paso y retorna su resultado."""
        ...


class DeliveryPipeline:
    """Pipeline de entrega que ejecuta pasos en secuencia con fallo aislado."""

    def __init__(self, steps: list[DeliveryStep]):
        self.steps = steps
        self.logger = logging.getLogger("delivery.pipeline")

    def run(self, artifact: ReportArtifact, config: DeliveryConfig) -> PipelineResult:
        """Ejecuta todos los pasos. Un paso que falla no detiene los siguientes."""
        result = PipelineResult()

        for step in self.steps:
            step_class = type(step).__name__
            if config.log_steps:
                self.logger.info("Iniciando paso: %s", step_class)
            try:
                step_result = step.execute(artifact, config, self.logger)
            except Exception as exc:
                self.logger.error("Error inesperado en %s: %s", step_class, exc)
                step_result = StepResult(
                    status="error",
                    step_name=step_class,
                    message=str(exc),
                )

            result.steps.append(step_result)

            if config.log_steps:
                self.logger.info(
                    "Paso %s finalizado: status=%s message=%s",
                    step_class,
                    step_result.status,
                    step_result.message,
                )

        return result
