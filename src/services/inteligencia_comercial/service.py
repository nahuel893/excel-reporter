"""InteligenciaComercialService — reporte analitico integral sobre el esquema gold.

Que hace
--------
Corre cinco familias de analisis sobre el Data Warehouse y las consolida en un
unico libro Excel con portada, KPIs, alertas, graficos nativos y una hoja de
metodologia que documenta como se calculo cada numero.

    clientes      RFM, riesgo de fuga, cohortes, puente de crecimiento, concentracion
    portafolio    ABC-XYZ, matriz canal x generico, cross-sell, reglas de asociacion
    rentabilidad  margen, venta bajo costo, cascada de descuentos, dispersion de precios
    demanda       estacionalidad, pronostico con backtest, control estadistico
    logistica     nivel de servicio, rechazos, devoluciones, stock, economia de rutas

Reglas que gobiernan todo el reporte
------------------------------------
- El neto es `subtotal_neto`. `facturacion_neta` es BRUTO a precio de lista pese
  a como se llama, y confundirlas sobreestima la facturacion un 12,6%.
- Toda comparacion entre periodos va en bultos o hectolitros. En pesos nominales
  la inflacion argentina convierte un +10,6% real en un +41,8% de fantasia.
- Los generos que no son articulos de venta (marketing, envases, equipos de frio)
  se excluyen de toda medida de volumen.
- Los agregados de mostrador se marcan, nunca se borran, para que la facturacion
  siga cerrando contra los totales.

Ninguna familia puede tumbar el reporte: si una falla, devuelve `failed=True`,
sus hojas se omiten y el motivo queda escrito en la hoja de metodologia.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from src.core.data_loader import DataLoader
from src.core.output_paths import Granularity
from src.services.base_service import BaseService
from src.services.inteligencia_comercial import constants as k
from src.services.inteligencia_comercial.analytics import (
    clientes,
    demanda,
    logistica,
    portafolio,
    rentabilidad,
)
from src.services.inteligencia_comercial.contracts import AnalysisContext, AnalysisResult
from src.services.inteligencia_comercial.excel_builder import build_workbook
from src.services.inteligencia_comercial.report_plan import PLAN

logger = logging.getLogger(__name__)

MODULOS = {
    "clientes": clientes,
    "portafolio": portafolio,
    "rentabilidad": rentabilidad,
    "demanda": demanda,
    "logistica": logistica,
}

MESES_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _miles(valor: float) -> str:
    """Formatea con separador de miles en castellano (punto)."""
    return f"{valor:,.0f}".replace(",", ".")


@dataclass
class InteligenciaComercialConfig:
    """Configuracion del reporte.

    Attributes:
        fecha_hasta: corte del analisis (inclusive), YYYY-MM-DD.
        meses_ventana: largo de la ventana principal, en meses.
        meses_historia: largo de la ventana larga (estacionalidad, ritmos de compra).
        nombre_archivo: nombre del xlsx sin extension. Se deriva si es None.
        modulos: subconjunto de familias a correr. None corre todas.
    """

    fecha_hasta: str
    meses_ventana: int = 12
    meses_historia: int = 24
    nombre_archivo: str | None = None
    modulos: list[str] | None = None

    def __post_init__(self):
        try:
            datetime.strptime(self.fecha_hasta, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(
                f"fecha_hasta debe ser YYYY-MM-DD, llego {self.fecha_hasta!r}"
            ) from exc
        if self.meses_ventana < 1:
            raise ValueError("meses_ventana debe ser al menos 1")
        if self.meses_historia < self.meses_ventana:
            raise ValueError("meses_historia no puede ser menor que meses_ventana")
        if self.modulos:
            desconocidos = sorted(set(self.modulos) - set(MODULOS))
            if desconocidos:
                raise ValueError(
                    f"modulos desconocidos: {desconocidos}. Validos: {sorted(MODULOS)}"
                )
        if self.nombre_archivo is None:
            self.nombre_archivo = f"Inteligencia Comercial - {self.fecha_hasta}"


@dataclass
class InteligenciaComercialResult:
    """Resultado de la generacion."""

    ruta_archivo: Path
    hojas: int
    analisis_ok: list[str] = field(default_factory=list)
    analisis_fallidos: list[str] = field(default_factory=list)
    alertas: int = 0
    duracion_segundos: float = 0.0

    @property
    def registros_procesados(self) -> int:
        """Compatibilidad con el contrato de resultado del resto de los servicios."""
        return self.hojas


class InteligenciaComercialService(BaseService):
    """Orquesta los analisis y arma el libro."""

    SERVICE_SLUG: ClassVar[str] = k.SERVICE_SLUG
    GRANULARITY: ClassVar[Granularity] = "month"

    def __init__(self, data_loader: DataLoader | None = None):
        super().__init__(data_loader)

    def generar_reporte(
        self, config: InteligenciaComercialConfig
    ) -> InteligenciaComercialResult:
        """Corre los analisis pedidos y escribe el libro.

        Una familia que falla no interrumpe el reporte: se registra, sus hojas se
        omiten y el motivo aparece en la hoja de metodologia.
        """
        inicio = time.time()
        ctx = AnalysisContext(
            data_loader=self.data_loader,
            fecha_hasta=config.fecha_hasta,
            meses_ventana=config.meses_ventana,
            meses_historia=config.meses_historia,
        )

        pedidos = config.modulos or list(MODULOS)
        resultados: dict[str, AnalysisResult] = {}
        ok: list[str] = []
        fallidos: list[str] = []

        for clave in pedidos:
            modulo = MODULOS[clave]
            t0 = time.time()
            logger.info("inteligencia-comercial: corriendo %s", clave)
            try:
                resultado = modulo.build(ctx)
            except Exception as exc:  # noqa: BLE001
                # El contrato dice que build() no levanta, pero si algo se escapa
                # el reporte igual se entrega con el resto de los analisis.
                logger.exception("inteligencia-comercial: %s levanto excepcion", clave)
                resultado = AnalysisResult(
                    name=clave,
                    failed=True,
                    notes=[f"El analisis levanto una excepcion inesperada: {exc}"],
                )
            resultados[clave] = resultado
            (fallidos if resultado.failed else ok).append(clave)
            logger.info(
                "inteligencia-comercial: %s termino en %.1fs (failed=%s, tablas=%d)",
                clave, time.time() - t0, resultado.failed, len(resultado.tables),
            )

        specs = [spec for spec in PLAN if spec.analysis in resultados]
        destino = self._output_dir(config.fecha_hasta)
        ruta = destino / f"{config.nombre_archivo}.xlsx"

        build_workbook(
            results=resultados,
            specs=specs,
            output_path=ruta,
            periodo=self._describir_periodo(config),
            generado=datetime.now().strftime("%d/%m/%Y %H:%M"),
            reconciliaciones=self._conciliar(resultados),
        )

        alertas = sum(len(r.alerts) for r in resultados.values())
        # Portada + hojas con datos + Metodologia.
        hojas = 2 + sum(
            1 for spec in specs
            if not resultados[spec.analysis].table(spec.table).empty
        )

        return InteligenciaComercialResult(
            ruta_archivo=ruta,
            hojas=hojas,
            analisis_ok=ok,
            analisis_fallidos=fallidos,
            alertas=alertas,
            duracion_segundos=time.time() - inicio,
        )

    @staticmethod
    def _conciliar(resultados: dict[str, AnalysisResult]) -> list[str]:
        """Explica las diferencias entre cifras parecidas de distintos analisis.

        El volumen en hectolitros aparece dos veces en la portada y no coincide,
        porque el puente de clientes usa una ventana movil de 12 meses desde la
        fecha de corte y la serie de demanda usa meses calendario completos.
        Las dos son correctas para su definicion; lo inaceptable seria publicarlas
        juntas sin decir en que se diferencian.
        """
        notas: list[str] = []

        puente = resultados.get("clientes")
        serie = resultados.get("demanda")
        if puente is None or serie is None:
            return notas

        tabla = puente.table("puente")
        mensual = serie.table("serie_mensual")
        if tabla.empty or mensual.empty or "Htl actual" not in tabla.columns:
            return notas

        etiqueta = tabla.iloc[:, 0].astype(str).str.upper()
        total = tabla[etiqueta.str.startswith("TOTAL")]
        columnas_htl = [
            c for c in mensual.columns
            if str(c).startswith("TOTAL GENERAL") and str(c).endswith("Htl")
        ]
        if total.empty or not columnas_htl:
            return notas

        htl_puente = float(total["Htl actual"].iloc[0])
        meses = mensual[~mensual.iloc[:, 0].astype(str).str.upper().str.startswith("TOTAL")]
        htl_serie = float(meses[columnas_htl[0]].tail(12).sum())
        brecha = htl_serie - htl_puente
        if htl_puente <= 0:
            return notas

        notas.append(
            f"Hectolitros de los ultimos 12 meses: el puente de crecimiento mide "
            f"{_miles(htl_puente)} htl y la serie mensual de demanda {_miles(htl_serie)} htl, "
            f"una diferencia de {_miles(brecha)} htl "
            f"({abs(brecha) / htl_puente * 100:.1f}%). "
            f"El puente usa una ventana movil de 12 meses desde la fecha de corte y "
            f"atribuye cada hectolitro a un cliente; la serie usa los ultimos 12 meses "
            f"calendario completos y suma todo lo facturado. Para hablar de clientes, "
            f"usar el puente; para hablar de volumen y estacionalidad, usar la serie."
        )
        return notas

    @staticmethod
    def _describir_periodo(config: InteligenciaComercialConfig) -> str:
        hasta = datetime.strptime(config.fecha_hasta, "%Y-%m-%d").date()
        return (
            f"Ventana de {config.meses_ventana} meses al "
            f"{hasta.day} de {MESES_ES[hasta.month - 1]} de {hasta.year} "
            f"(historia de {config.meses_historia} meses para ritmos y estacionalidad)"
        )
