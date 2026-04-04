"""
Delivery module - Pipeline de entrega automatizada de reportes.

Permite configurar envio de reportes Excel por email y/o WhatsApp,
con captura de imagen opcional, via un pipeline de pasos configurables.
"""
from src.delivery.pipeline import (
    DeliveryConfig,
    DeliveryPipeline,
    DeliveryStep,
    PipelineResult,
    ReportArtifact,
    StepResult,
)

__all__ = [
    "DeliveryConfig",
    "DeliveryPipeline",
    "DeliveryStep",
    "PipelineResult",
    "ReportArtifact",
    "StepResult",
]
