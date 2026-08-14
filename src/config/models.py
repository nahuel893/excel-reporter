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
    # Ventana RELATIVA. Cuando esta puesto, main.py recalcula fecha_desde y
    # fecha_hasta desde la fecha de hoy e IGNORA las de arriba, que pasan a ser
    # solo documentacion del formato.
    #
    # Existe porque las fechas guardadas envejecen: el daily las patchea en cada
    # corrida, pero una corrida manual usaba lo que quedo escrito. Asi salio el
    # informe de FULL SPORT con junio-julio cuando tenia que ser julio-agosto.
    # Es el mismo modo que declara scripts/run_daily.py, resuelto por el mismo
    # codigo (src/core/periodos.resolver_ventana).
    fecha_modo: Literal["mes_a_hoy", "mes_completo", "hoy"] | None = None
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
    # stock-suria: si True, ignora la lista JSON de match y trae TODOS los
    # articulos de SURIA con registro de stock (reporte completo).
    todos_los_articulos: bool = False
    # stock-badie: dias de stock objetivo (alcance en dias = stock / venta_dia).
    dias_stock: int = 15
    # stock-badie / stock-valorizado: genericos que NO forman parte del informe
    # (envases, marketing, equipos de frio, dispensers — no son articulos de venta).
    genericos_excluidos: list[str] | None = None
    # volumen-cobertura: sucursales que quedan FUERA del informe, por id.
    # CASA CENTRAL (1) suele excluirse porque tiene su propio circuito y su
    # volumen tapa al del interior.
    sucursales_excluidas: list[int] | None = None
    # stock-valorizado: xlsx exportado del ERP con la lista de precios de
    # referencia (columnas "Articulo" y "Precio Base"). No hay precio en gold,
    # asi que sin este archivo no hay valorizacion.
    lista_precios_path: str | None = None
    # stock-valorizado: fecha del snapshot de stock. None -> ultima disponible
    # en gold.fact_stock (NO se deriva de fecha_desde/fecha_hasta, que el daily
    # parchea al mes en curso y no describen un snapshot).
    fecha_stock: str | None = None
    # stock-valorizado: antiguedad en dias a partir de la cual la lista de
    # precios se marca como VENCIDA (banner rojo en las hojas + aviso en la CLI).
    # Los precios se exportan a mano del ERP: sin esto, una lista de hace cuatro
    # meses produce un informe que parece tan valido como uno fresco.
    lista_precios_max_dias: int | None = None
    # cupo-desagregado: archivo "Objetivo <MES> Badie" con los cupos por preventista.
    cupos_source_path: str | None = None
    # cupo-desagregado: hoja del archivo fuente. None -> nombre del mes de fecha_desde.
    cupos_hoja: str | None = None
    # cupo-desagregado: ventana de historia [desde, hasta) para abrir los cupos
    # por ruta. None -> mes anterior completo al periodo del cupo.
    historia_desde: str | None = None
    historia_hasta: str | None = None
    # avances: si True, NO regenera las hojas de cupos (CuposVolumen,
    # CuposCoberGen, CuposCober) — preserva lo cargado a mano. Sirve para
    # corridas de recarga cuando los objetivos aún no están en gold.
    skip_cupos: bool = False


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
    solo_con_cargo: bool | None = None         # historico-cliente: exclude 100%-discount (gift) units
    con_detalle_clientes: bool | None = None   # comparativo-salta: include the per-client volume sheet
    anios_mensual: list[int] | None = None     # comparativo-salta: años de la hoja mensual
    sucursal_comparativa: str | None = None    # comparativo-salta: sucursal apilada año contra año
    meses_vendedor: list[str] | None = None    # comparativo-salta: meses de la hoja por preventista
    # comparativo-salta: bloques de columnas armados a mano. Cada uno:
    # {"grupo": str, "sabor": str, "calibre": str, "meses": [str], "cupo": float|None}
    bloques_vendedor: list[dict] | None = None
    id_sucursal_vendedor: int | None = None    # comparativo-salta: sucursal de la hoja por preventista
    excluir_vendedores: list[str] | None = None  # comparativo-salta: preventistas dados de baja
    con_lista_precio: bool | None = None      # descuentos: si False, no genera la hoja "lista_precio"
    # ventas-marca / ventas-cober-preventista-marca: agrega una columna con el mes
    # anterior completo, DERIVADO de fecha_desde (nunca escrito en el config).
    incluir_mes_anterior: bool | None = None
    # ventas-cober-preventista-marca: columna Objetivo = % de la cobertura de otra
    # marca. {"marca","pct_anterior","pct_actual","base_actual"} — ver el servicio.
    objetivo_cobertura: dict | None = None
    # ventas-cober-preventista-marca: piso de VOLUMEN al pie del bloque de preventistas.
    clausula_gatillo: float | None = None
    # incentivo-salta: xlsx con los bloques y los cupos fijos por preventista.
    objetivos_path: str | None = None
    # cobertura: apertura del informe (que columnas forman el index del pivot).
    apertura_cobertura: Literal[
        "preventista_generico", "preventista_marca", "sucursal_marca"
    ] | None = None
    # cobertura: offsets en meses respecto del mes de fecha_desde, uno por columna
    # de periodo. Default [13, 1] = mismo mes del año anterior contra el mes
    # cerrado. NUNCA se escriben periodos literales: el daily patchea fechas pero
    # no el resto del JSON, y un mes a mano se desincroniza al cambiar de mes.
    meses_atras: list[int] | None = None
    # avances: override per-report de skip_cupos (default: heredar del global).
    skip_cupos: bool | None = None


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

    tipo: Literal["ventas", "resumen-mensual", "champions-league", "historico-fratelli", "stock-diario", "cartesiano", "avances", "graficos-cobertura", "ventas-articulo", "historico-cliente", "reporte-general-badie", "reporte-rebotes", "reporte-incentivo-cobertura", "reporte-descuentos", "subdistribuidores", "stock-suria", "stock-suria-control", "ventas-marca", "ventas-cober-preventista-marca", "incentivo-salta", "stock-badie", "stock-valorizado", "cupo-desagregado", "comparativo-salta", "cobertura", "cobertura-cupos", "cobertura-aguas", "quesos", "volumen-cobertura"]
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
