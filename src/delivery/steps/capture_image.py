"""
CaptureImageStep - Paso de captura de rango Excel como imagen PNG.
"""
import logging
from pathlib import Path

from src.delivery.pipeline import CaptureConfig, DeliveryConfig, DeliveryStep, ReportArtifact, StepResult

AUTO_BORDES_SENTINEL = "auto:bordes"
AUTO_BORDES_RENDERER = "libreoffice"  # only backend that supports print_area cropping


class CaptureImageStep(DeliveryStep):
    """Captura N rangos de hojas Excel como imagenes PNG (LibreOffice + Pillow).

    Cada captura es aislada: si una falla, las otras se intentan igual.
    Poblar artifact.rutas_imagenes con la lista de PNGs generados.

    Soporta el sentinel ``rango: "auto:bordes"``: se expande, ANTES del loop
    de render, en N CaptureConfig concretos (uno por region detectada por
    RangeRecognizer), cada uno renderizado con crop=True. Nunca muta
    `config`/`DeliveryConfig` — la expansion arma una lista local nueva.

    Las entradas con rango fijo (no ``auto:bordes``) se renderizan con
    crop=``cfg.recortar`` (default False, comportamiento historico de
    branca/schneider preservado); las expandidas de ``auto:bordes`` siempre
    usan crop=True.
    """

    def execute(
        self,
        artifact: ReportArtifact,
        config: DeliveryConfig,
        logger: logging.Logger,
    ) -> StepResult:
        # Support either plural capture_images or legacy singular capture_image.
        captures = list(config.capture_images or [])
        if not captures and config.capture_image is not None:
            captures = [config.capture_image]

        if not captures:
            return StepResult(
                status="skipped",
                step_name="CaptureImageStep",
                message="capture_images no configurado",
            )

        from src.core.excel_renderers import get_renderer

        errores: list[str] = []
        expanded = self._expand_auto_bordes(artifact, captures, errores, logger)

        if not expanded:
            if errores:
                return StepResult(
                    status="error",
                    step_name="CaptureImageStep",
                    message=f"Todas las capturas fallaron: {'; '.join(errores)}",
                )
            # Reaching here means captures WERE configured but every auto:bordes
            # sentinel detected zero regions (e.g. the template lost its border
            # styling). Report it distinctly — naming the sheet(s) — instead of
            # the misleading "no configurado" so an operator can investigate.
            auto_sheets = [c.hoja for c in captures if c.rango == AUTO_BORDES_SENTINEL]
            if auto_sheets:
                sheets_str = ", ".join(f"'{s}'" for s in auto_sheets)
                return StepResult(
                    status="error",
                    step_name="CaptureImageStep",
                    message=f"auto:bordes: no bordered regions detected in sheet {sheets_str}",
                )
            return StepResult(
                status="skipped",
                step_name="CaptureImageStep",
                message="capture_images no configurado",
            )

        produced: list[str] = []

        for cfg, crop in expanded:
            renderer_name = getattr(cfg, "renderer", "libreoffice")
            try:
                renderer = get_renderer(renderer_name)
                png_path = renderer.render(
                    xlsx_path=artifact.ruta_excel,
                    sheet=cfg.hoja,
                    range_addr=cfg.rango,
                    output_dir=artifact.ruta_excel.parent,
                    crop=crop,
                )
                artifact.rutas_imagenes.append(png_path)
                artifact.nombres_hojas.append(cfg.caption or cfg.hoja)
                produced.append(f"{cfg.hoja}[{renderer_name}]:{png_path.name}")
            except ImportError as exc:
                # A genuinely missing renderer dependency (e.g. Pillow) affects
                # every region equally — there is no point continuing the loop.
                logger.warning(
                    "Dependencia faltante en renderer '%s', omitiendo capturas: %s",
                    renderer_name, exc,
                )
                return StepResult(
                    status="skipped",
                    step_name="CaptureImageStep",
                    message=str(exc),
                )
            except Exception as exc:  # per-region failure (incl. RuntimeError)
                # RuntimeError from soffice/pdftoppm (non-zero exit, missing
                # binary) is per-render: isolate it so one bad region does not
                # abort the remaining regions. Record it and keep going.
                logger.error(
                    "Captura fallida [%s %s/%s]: %s",
                    cfg.hoja, cfg.rango, renderer_name, exc,
                )
                errores.append(f"{cfg.hoja}[{cfg.rango}]/{renderer_name}: {exc}")

        if produced and not errores:
            return StepResult(
                status="success",
                step_name="CaptureImageStep",
                message=f"Imagenes generadas: {', '.join(produced)}",
                artifact_path=artifact.rutas_imagenes[0] if artifact.rutas_imagenes else None,
            )
        if produced and errores:
            return StepResult(
                status="partial",
                step_name="CaptureImageStep",
                message=(
                    f"Exito: {', '.join(produced)} | "
                    f"Fallos: {'; '.join(errores)}"
                ),
                artifact_path=artifact.rutas_imagenes[0] if artifact.rutas_imagenes else None,
            )
        return StepResult(
            status="error",
            step_name="CaptureImageStep",
            message=f"Todas las capturas fallaron: {'; '.join(errores)}",
        )

    @staticmethod
    def _expand_auto_bordes(
        artifact: ReportArtifact,
        captures: list[CaptureConfig],
        errores: list[str],
        logger: logging.Logger,
    ) -> list[tuple[CaptureConfig, bool]]:
        """Expands any ``rango == "auto:bordes"`` entry into one concrete
        CaptureConfig per detected region (crop=True), leaving non-sentinel
        entries untouched (crop=``cfg.recortar``, default False). Builds a
        NEW local list — `captures` (and therefore the shared DeliveryConfig
        it came from) is never mutated. Reuses a SINGLE RangeRecognizer
        instance across every auto:bordes entry in this run (the underlying
        workbook load is expensive, ~110-125s on real templates — see
        range_recognizer.py)."""
        expanded: list[tuple[CaptureConfig, bool]] = []
        recognizer = None
        try:
            for cfg in captures:
                if cfg.rango != AUTO_BORDES_SENTINEL:
                    expanded.append((cfg, cfg.recortar))
                    continue

                renderer_name = getattr(cfg, "renderer", "libreoffice")
                if renderer_name != AUTO_BORDES_RENDERER:
                    msg = (
                        f"'{AUTO_BORDES_SENTINEL}' solo soportado con "
                        f"renderer='{AUTO_BORDES_RENDERER}', recibido "
                        f"'{renderer_name}' para hoja '{cfg.hoja}'"
                    )
                    logger.error(msg)
                    errores.append(f"{cfg.hoja}/{renderer_name}: {msg}")
                    continue

                if recognizer is None:
                    from src.core.range_recognizer import RangeRecognizer
                    recognizer = RangeRecognizer(artifact.ruta_excel)

                try:
                    regions = recognizer.detect_ranges_with_captions(
                        cfg.hoja, caption_anchor=cfg.caption_anchor, caption_header=cfg.caption_header,
                    )
                except Exception as exc:
                    logger.error(
                        "Fallo detectando regiones '%s' en hoja '%s': %s",
                        AUTO_BORDES_SENTINEL, cfg.hoja, exc,
                    )
                    errores.append(f"{cfg.hoja}/{AUTO_BORDES_SENTINEL}: {exc}")
                    continue

                for a1_range, region_caption in regions:
                    concrete = cfg.model_copy(update={
                        "rango": a1_range,
                        "caption": region_caption or cfg.caption,
                    })
                    expanded.append((concrete, True))
        finally:
            if recognizer is not None:
                recognizer.close()

        return expanded
