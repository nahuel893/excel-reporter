"""CupoDesagregadoService — abre el cupo mensual de cada preventista por ruta.

Que hace
--------
El archivo "Objetivo <MES> Badie" trae un cupo por preventista y categoria.
Este servicio lo reparte entre las rutas de cada preventista, proporcional a
lo que esas rutas vendieron en el periodo de historia (por defecto, el mes
anterior completo). CASA CENTRAL queda afuera: tiene su propio circuito.

Reglas del reparto
------------------
1. Las rutas de un preventista salen de dim_cliente (id_personal_fv1 ->
   id_ruta_fv1) sobre clientes activos.
2. La historia de una ruta son las ventas de SUS clientes, sin importar que
   vendedor las cargo — refleja la demanda real de la ruta.
3. CERVEZAS es doble apertura: por ruta es la suma de SALTA + HEINEKEN +
   IMPERIAL + MILLER + MULTICERVEZA.
4. Redondeo a 2 decimales, la ultima ruta absorbe el residuo: la suma de las
   rutas iguala el cupo del preventista al centavo (validado en cada corrida).
5. Categoria sin historia en ninguna ruta -> reparto parejo.
6. Preventista sin clientes asignados -> fila unica "SIN RUTA ASIGNADA".

Receta mensual
--------------
Cambiar `fecha_desde`/`fecha_hasta` al mes del cupo y apuntar
`cupos_source_path` al nuevo archivo. La hoja del archivo y la ventana de
historia se derivan solas del mes. Despues revisar en `constants.py`:
vendedores nuevos (NOMBRE_OVERRIDES), migraciones de sucursal
(RUTAS_OVERRIDE), categorias nuevas (SRC_COLS + CATEGORIAS) y sucursales
nuevas (SUCURSAL_IDS).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from src.services.base_service import BaseReporteConfig, BaseReporteResult, BaseService
from src.services.cupo_desagregado.constants import SUCURSALES_INCLUIDAS
from src.services.cupo_desagregado.excel_builder import escribir_excel
from src.services.cupo_desagregado.processor import (
    agregar_historia,
    construir_mapa_vendedores,
    construir_rutas_por_vendedor,
    distribuir_cupos,
    hoja_del_mes,
    leer_cupos,
    periodo_historia,
    validar,
)

logger = logging.getLogger(__name__)


@dataclass
class CupoDesagregadoConfig(BaseReporteConfig):
    """Configuracion del reporte.

    fecha_desde/fecha_hasta delimitan el MES DEL CUPO (definen la carpeta de
    salida y la hoja del archivo fuente). La historia es un periodo aparte.
    """

    cupos_source_path: str = ""
    # Hoja del archivo fuente. None -> el nombre del mes de fecha_desde.
    cupos_hoja: str | None = None
    # Ventana de historia [desde, hasta). None -> mes anterior completo.
    historia_desde: str | None = None
    historia_hasta: str | None = None

    def __post_init__(self):
        super().__post_init__()
        if not self.cupos_source_path:
            raise ValueError(
                "cupo-desagregado requiere cupos_source_path (archivo Objetivo del mes)"
            )

    def resolver_hoja(self) -> str:
        return self.cupos_hoja or hoja_del_mes(self.fecha_desde)

    def resolver_historia(self) -> tuple[date, date]:
        if self.historia_desde and self.historia_hasta:
            return (date.fromisoformat(self.historia_desde[:10]),
                    date.fromisoformat(self.historia_hasta[:10]))
        return periodo_historia(self.fecha_desde)


@dataclass
class CupoDesagregadoResult(BaseReporteResult):
    """Resultado del reporte, con los diagnosticos del mes."""

    vendedores: int = 0
    filas_ruta: int = 0
    sin_ruta: list[str] = field(default_factory=list)
    sin_historia: list[str] = field(default_factory=list)
    errores_validacion: dict[str, float] = field(default_factory=dict)
    hojas: list[str] = field(default_factory=list)


class CupoDesagregadoService(BaseService):
    """Genera el Excel de Cupo Desagregado Por Ruta."""

    # Todos los informes de cupos comparten carpeta: data/output/cupos/{mes}/.
    # Son el mismo cuerpo de trabajo (interior, CASA CENTRAL, Branca) y
    # separarlos por servicio obligaba a buscar el mes en cuatro lugares.
    SERVICE_SLUG = "cupos"
    GRANULARITY = "month"

    def generar_reporte(
        self, config: CupoDesagregadoConfig
    ) -> CupoDesagregadoResult:
        source = Path(config.cupos_source_path).expanduser()
        if not source.exists():
            raise FileNotFoundError(f"Archivo de cupos no encontrado: {source}")

        hoja = config.resolver_hoja()
        hist_desde, hist_hasta = config.resolver_historia()
        logger.info(
            "cupo-desagregado: fuente=%s hoja=%s historia=[%s, %s)",
            source.name, hoja, hist_desde, hist_hasta,
        )

        vendedores = leer_cupos(source, hoja)
        if not vendedores:
            logger.warning("La hoja %s no tiene vendedores en el bloque Objetivo", hoja)

        mapa = construir_mapa_vendedores(
            self.data_loader.get_vendedores_dim(SUCURSALES_INCLUIDAS))
        rutas = construir_rutas_por_vendedor(
            self.data_loader.get_rutas_por_vendedor(SUCURSALES_INCLUIDAS))
        historia = agregar_historia(
            self.data_loader.get_ventas_por_ruta_categoria(
                hist_desde.isoformat(), hist_hasta.isoformat(), SUCURSALES_INCLUIDAS))

        distribucion = distribuir_cupos(vendedores, rutas, mapa, historia)
        errores = validar(distribucion.filas, vendedores)

        nombre = config.nombre_archivo or f"Cupo Desagregado {config.fecha_desde[:7]}"
        ruta = escribir_excel(
            distribucion.filas, vendedores,
            self._output_dir(config.fecha_desde) / f"{nombre}.xlsx",
        )

        if distribucion.sin_ruta:
            logger.warning("Sin ruta asignada: %s", distribucion.sin_ruta)
        if distribucion.sin_historia:
            logger.info("Sin historia (reparto parejo): %s",
                        sorted(set(distribucion.sin_historia)))
        if errores:
            logger.error("La suma de rutas no cierra con el cupo: %s", errores)

        return CupoDesagregadoResult(
            ruta_archivo=ruta,
            registros_procesados=len(distribucion.filas),
            vendedores=len(vendedores),
            filas_ruta=len(distribucion.filas),
            sin_ruta=distribucion.sin_ruta,
            sin_historia=sorted(set(distribucion.sin_historia)),
            errores_validacion=errores,
            hojas=["Cupo Ruta", "Cupo Preventa", "Resumen Sucursal"],
        )

    def run(self, config: CupoDesagregadoConfig) -> CupoDesagregadoResult:
        return self.generar_reporte(config)
