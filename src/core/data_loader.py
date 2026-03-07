"""
DataLoader - Acceso a datos del Data Warehouse.

Proporciona acceso centralizado a la base de datos PostgreSQL
usando SQLAlchemy con soporte para inyección de dependencias.
"""
from datetime import timedelta, datetime

import pandas as pd
from dateutil.relativedelta import relativedelta
from sqlalchemy import create_engine, text, Engine

from config.settings import DB_CONFIG


class DataLoader:
    """Clase para acceso a datos del Data Warehouse."""

    def __init__(self, engine: Engine | None = None):
        """
        Inicializa el DataLoader.

        Args:
            engine: Engine de SQLAlchemy. Si es None, crea uno con DB_CONFIG.
        """
        self._engine = engine

    @property
    def engine(self) -> Engine:
        """Obtiene el engine, creándolo si no existe."""
        if self._engine is None:
            url = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
            self._engine = create_engine(url)
        return self._engine

    def get_connection(self):
        """Crea conexión a la base de datos."""
        return self.engine.connect()

    def execute_query(self, query: str, params: dict | None = None) -> pd.DataFrame:
        """
        Ejecuta una query y retorna el resultado como DataFrame.

        Args:
            query: Query SQL a ejecutar
            params: Parámetros para la query

        Returns:
            DataFrame con los resultados
        """
        with self.engine.connect() as conn:
            return pd.read_sql_query(text(query), conn, params=params or {})

    def get_sucursales(self) -> pd.DataFrame:
        """Obtiene todas las sucursales."""
        query = """
        SELECT DISTINCT descripcion AS sucursal
        FROM gold.dim_sucursal
        ORDER BY descripcion
        """
        return self.execute_query(query)

    def get_articulos(self, genericos: list[str] | None = None) -> pd.DataFrame:
        """
        Obtiene todas las combinaciones generico-marca.

        Args:
            genericos: Lista de genericos a filtrar. Si es None, trae todos.
        """
        if genericos:
            placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
            query = f"""
            SELECT DISTINCT generico, marca
            FROM gold.dim_articulo
            WHERE generico IS NOT NULL AND marca IS NOT NULL
            AND generico IN ({placeholders})
            ORDER BY generico, marca
            """
            params = {f"gen_{i}": g for i, g in enumerate(genericos)}
        else:
            query = """
            SELECT DISTINCT generico, marca
            FROM gold.dim_articulo
            WHERE generico IS NOT NULL AND marca IS NOT NULL
            ORDER BY generico, marca
            """
            params = {}

        return self.execute_query(query, params)

    def get_ventas_diarias(self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None) -> pd.DataFrame:
        """
        Obtiene ventas diarias por sucursal, generico y marca.

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD'
            genericos: Lista de genericos a filtrar. Si es None, trae todos.

        Returns:
            DataFrame con columnas: sucursal, generico, marca, fecha, cantidad, monto
        """
        if genericos:
            placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
            query = f"""
            SELECT
                ds.descripcion AS sucursal,
                da.generico,
                da.marca,
                fv.fecha_comprobante AS fecha,
                SUM(fv.cantidades_total) AS cantidad,
                SUM(fv.cantidad_total_htls) AS cantidad_htls,
                SUM(fv.subtotal_neto) AS monto
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
            AND da.generico IN ({placeholders})
            GROUP BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante
            ORDER BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}
            params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        else:
            query = """
            SELECT
                ds.descripcion AS sucursal,
                da.generico,
                da.marca,
                fv.fecha_comprobante AS fecha,
                SUM(fv.cantidades_total) AS cantidad,
                SUM(fv.cantidad_total_htls) AS cantidad_htls,
                SUM(fv.subtotal_neto) AS monto
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
            GROUP BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante
            ORDER BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}

        return self.execute_query(query, params)

    def get_ventas_diarias_con_ruta(self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None) -> pd.DataFrame:
        """
        Obtiene ventas diarias incluyendo id_ruta para split de zonas virtuales.

        Igual a get_ventas_diarias pero agrega id_ruta_fv1 de dim_cliente al GROUP BY.
        id_ruta se obtiene via: fact_ventas.id_cliente -> dim_cliente.id_ruta_fv1
        """
        if genericos:
            placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
            query = f"""
            SELECT
                ds.descripcion AS sucursal,
                da.generico,
                da.marca,
                fv.fecha_comprobante AS fecha,
                dc.id_ruta_fv1 AS id_ruta,
                SUM(fv.cantidades_total) AS cantidad,
                SUM(fv.cantidad_total_htls) AS cantidad_htls,
                SUM(fv.subtotal_neto) AS monto
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
            LEFT JOIN gold.dim_cliente dc ON fv.id_cliente = dc.id_cliente
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
            AND da.generico IN ({placeholders})
            GROUP BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}
            params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        else:
            query = """
            SELECT
                ds.descripcion AS sucursal,
                da.generico,
                da.marca,
                fv.fecha_comprobante AS fecha,
                dc.id_ruta_fv1 AS id_ruta,
                SUM(fv.cantidades_total) AS cantidad,
                SUM(fv.cantidad_total_htls) AS cantidad_htls,
                SUM(fv.subtotal_neto) AS monto
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
            LEFT JOIN gold.dim_cliente dc ON fv.id_cliente = dc.id_cliente
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
            GROUP BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}

        return self.execute_query(query, params)

    def get_ventas(self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None) -> pd.DataFrame:
        """
        Obtiene ventas agrupadas por sucursal, generico y marca.

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD'
            genericos: Lista de genericos a filtrar. Si es None, trae todos.

        Returns:
            DataFrame con columnas: sucursal, generico, marca, cantidad, monto
        """
        if genericos:
            placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
            query = f"""
            SELECT
                ds.descripcion AS sucursal,
                da.generico,
                da.marca,
                SUM(fv.cantidades_total) AS cantidad,
                SUM(fv.cantidad_total_htls) AS cantidad_htls,
                SUM(fv.subtotal_neto) AS monto
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
            AND da.generico IN ({placeholders})
            GROUP BY ds.descripcion, da.generico, da.marca
            ORDER BY ds.descripcion, da.generico, monto DESC
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}
            params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        else:
            query = """
            SELECT
                ds.descripcion AS sucursal,
                da.generico,
                da.marca,
                SUM(fv.cantidades_total) AS cantidad,
                SUM(fv.cantidad_total_htls) AS cantidad_htls,
                SUM(fv.subtotal_neto) AS monto
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
            GROUP BY ds.descripcion, da.generico, da.marca
            ORDER BY ds.descripcion, da.generico, monto DESC
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}

        return self.execute_query(query, params)

    # ── Resumen Mensual ─────────────────────────────────────────

    def get_ventas_resumen_mensual(self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None) -> pd.DataFrame:
        """
        Obtiene ventas mensuales agrupadas por sucursal, generico e id_ruta.

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD'
            genericos: Lista de genericos a filtrar. Si es None, trae todos.

        Returns:
            DataFrame con columnas: sucursal, generico, id_ruta, cantidad
        """
        if genericos:
            placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
            query = f"""
            SELECT
                ds.descripcion          AS sucursal,
                da.generico,
                dc.id_ruta_fv1          AS id_ruta,
                SUM(fv.cantidades_total) AS cantidad
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
            LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal  = ds.id_sucursal
            LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
              AND da.generico IS NOT NULL
              AND da.generico IN ({placeholders})
            GROUP BY ds.descripcion, da.generico, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}
            params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        else:
            query = """
            SELECT
                ds.descripcion          AS sucursal,
                da.generico,
                dc.id_ruta_fv1          AS id_ruta,
                SUM(fv.cantidades_total) AS cantidad
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
            LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal  = ds.id_sucursal
            LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
              AND da.generico IS NOT NULL
            GROUP BY ds.descripcion, da.generico, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}

        return self.execute_query(query, params)

    def get_ventas_ultimos_dias_habiles(self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None) -> pd.DataFrame:
        """
        Obtiene ventas diarias del rango completo del mes, con desglose por fecha e id_ruta.

        Trae todos los dias del mes para que el procesador pueda detectar los
        ultimos 2 dias con ventas reales en la BD (sin usar la fecha de hoy como referencia).

        Args:
            fecha_desde: Primer dia del mes formato 'YYYY-MM-DD'
            fecha_hasta: Ultimo dia del rango formato 'YYYY-MM-DD'
            genericos: Lista de genericos a filtrar. Si es None, trae todos.

        Returns:
            DataFrame con columnas: sucursal, generico, fecha, id_ruta, cantidad
        """
        if genericos:
            placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
            query = f"""
            SELECT
                ds.descripcion           AS sucursal,
                da.generico,
                fv.fecha_comprobante     AS fecha,
                dc.id_ruta_fv1           AS id_ruta,
                SUM(fv.cantidades_total) AS cantidad
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
            LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal  = ds.id_sucursal
            LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
              AND da.generico IS NOT NULL
              AND da.generico IN ({placeholders})
            GROUP BY ds.descripcion, da.generico, fv.fecha_comprobante, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico, fv.fecha_comprobante
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}
            params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        else:
            query = """
            SELECT
                ds.descripcion           AS sucursal,
                da.generico,
                fv.fecha_comprobante     AS fecha,
                dc.id_ruta_fv1           AS id_ruta,
                SUM(fv.cantidades_total) AS cantidad
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
            LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal  = ds.id_sucursal
            LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
              AND da.generico IS NOT NULL
            GROUP BY ds.descripcion, da.generico, fv.fecha_comprobante, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico, fv.fecha_comprobante
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}

        return self.execute_query(query, params)

    def get_ventas_mes_anterior(self, fecha_desde: str, genericos: list[str] | None = None) -> pd.DataFrame:
        """
        Obtiene ventas del mes calendario completo anterior a fecha_desde.

        Args:
            fecha_desde: Fecha de referencia formato 'YYYY-MM-DD'. El mes anterior
                         se calcula como el mes calendario que precede a esta fecha.
            genericos: Lista de genericos a filtrar. Si es None, trae todos.

        Returns:
            DataFrame con columnas: sucursal, generico, id_ruta, cantidad
        """
        fecha_dt = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
        primer_dia = (fecha_dt.replace(day=1) - relativedelta(months=1))
        ultimo_dia = fecha_dt.replace(day=1) - timedelta(days=1)
        return self.get_ventas_resumen_mensual(
            primer_dia.strftime("%Y-%m-%d"),
            ultimo_dia.strftime("%Y-%m-%d"),
            genericos,
        )

    def get_ventas_mismo_mes_anio_anterior(self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None) -> pd.DataFrame:
        """
        Obtiene ventas del mismo rango de fechas pero del anio anterior.

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD'
            genericos: Lista de genericos a filtrar. Si es None, trae todos.

        Returns:
            DataFrame con columnas: sucursal, generico, id_ruta, cantidad
        """
        fecha_desde_aa = f"{int(fecha_desde[:4]) - 1}{fecha_desde[4:]}"
        fecha_hasta_aa = f"{int(fecha_hasta[:4]) - 1}{fecha_hasta[4:]}"
        return self.get_ventas_resumen_mensual(fecha_desde_aa, fecha_hasta_aa, genericos)

    # ── Cobertura ──────────────────────────────────────────────

    def _filtro_periodos(
        self,
        alias: str,
        periodos: list[str] | None = None,
        periodo_desde: str | None = None,
        periodo_hasta: str | None = None,
    ) -> tuple[str, dict]:
        """Construye filtro SQL y params para periodos (lista o rango)."""
        params = {}
        if periodos:
            placeholders = ", ".join([f":per_{i}" for i in range(len(periodos))])
            filtro = f"{alias}.periodo IN ({placeholders})"
            params.update({f"per_{i}": p for i, p in enumerate(periodos)})
        elif periodo_desde and periodo_hasta:
            filtro = f"{alias}.periodo BETWEEN :desde AND :hasta"
            params = {"desde": periodo_desde, "hasta": periodo_hasta}
        else:
            raise ValueError("Debe especificar 'periodos' o 'periodo_desde'/'periodo_hasta'")
        return filtro, params

    def _filtro_sucursales(self, alias: str, sucursales: list[str] | None) -> tuple[str, dict]:
        """Construye filtro SQL y params para sucursales."""
        if not sucursales:
            return "", {}
        placeholders = ", ".join([f":suc_{i}" for i in range(len(sucursales))])
        filtro = f"AND {alias}.ds_sucursal IN ({placeholders})"
        params = {f"suc_{i}": s for i, s in enumerate(sucursales)}
        return filtro, params

    def get_cobertura_preventista_generico(
        self,
        periodo_desde: str | None = None,
        periodo_hasta: str | None = None,
        periodos: list[str] | None = None,
        sucursales: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Obtiene cobertura por preventista y generico.

        Args:
            periodo_desde: Periodo inicio formato 'YYYY-MM-DD' (rango)
            periodo_hasta: Periodo fin formato 'YYYY-MM-DD' (rango)
            periodos: Lista de periodos especificos ['2025-02-01', '2026-01-01']
            sucursales: Lista de sucursales a filtrar.
        """
        filtro_per, params = self._filtro_periodos("cpg", periodos, periodo_desde, periodo_hasta)
        filtro_suc, params_suc = self._filtro_sucursales("cpg", sucursales)
        params.update(params_suc)

        query = f"""
        SELECT
            cpg.periodo,
            cpg.ds_sucursal AS sucursal,
            cpg.id_vendedor,
            dv.des_vendedor AS vendedor,
            cpg.id_ruta,
            cpg.generico,
            cpg.clientes_compradores,
            cpg.volumen_total
        FROM gold.cob_preventista_generico cpg
        LEFT JOIN gold.dim_vendedor dv ON cpg.id_vendedor = dv.id_vendedor
        WHERE {filtro_per}
        {filtro_suc}
        ORDER BY cpg.periodo, cpg.ds_sucursal, dv.des_vendedor, cpg.generico
        """
        return self.execute_query(query, params)

    def get_cobertura_preventista_marca(
        self,
        periodo_desde: str | None = None,
        periodo_hasta: str | None = None,
        periodos: list[str] | None = None,
        sucursales: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Obtiene cobertura por preventista y marca.

        Args:
            periodo_desde: Periodo inicio formato 'YYYY-MM-DD' (rango)
            periodo_hasta: Periodo fin formato 'YYYY-MM-DD' (rango)
            periodos: Lista de periodos especificos ['2025-02-01', '2026-01-01']
            sucursales: Lista de sucursales a filtrar.
        """
        filtro_per, params = self._filtro_periodos("cpm", periodos, periodo_desde, periodo_hasta)
        filtro_suc, params_suc = self._filtro_sucursales("cpm", sucursales)
        params.update(params_suc)

        query = f"""
        SELECT
            cpm.periodo,
            cpm.ds_sucursal AS sucursal,
            cpm.id_vendedor,
            dv.des_vendedor AS vendedor,
            cpm.id_ruta,
            cpm.marca,
            cpm.clientes_compradores,
            cpm.volumen_total
        FROM gold.cob_preventista_marca cpm
        LEFT JOIN gold.dim_vendedor dv ON cpm.id_vendedor = dv.id_vendedor
        WHERE {filtro_per}
        {filtro_suc}
        ORDER BY cpm.periodo, cpm.ds_sucursal, dv.des_vendedor, cpm.marca
        """
        return self.execute_query(query, params)

    def get_cobertura_sucursal_marca(
        self,
        periodo_desde: str | None = None,
        periodo_hasta: str | None = None,
        periodos: list[str] | None = None,
        sucursales: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Obtiene cobertura agregada por sucursal y marca.

        Args:
            periodo_desde: Periodo inicio formato 'YYYY-MM-DD' (rango)
            periodo_hasta: Periodo fin formato 'YYYY-MM-DD' (rango)
            periodos: Lista de periodos especificos ['2025-02-01', '2026-01-01']
            sucursales: Lista de sucursales a filtrar.
        """
        filtro_per, params = self._filtro_periodos("csm", periodos, periodo_desde, periodo_hasta)
        filtro_suc, params_suc = self._filtro_sucursales("csm", sucursales)
        params.update(params_suc)

        query = f"""
        SELECT
            csm.periodo,
            csm.ds_sucursal AS sucursal,
            csm.marca,
            csm.clientes_compradores,
            csm.volumen_total
        FROM gold.cob_sucursal_marca csm
        WHERE {filtro_per}
        {filtro_suc}
        ORDER BY csm.periodo, csm.ds_sucursal, csm.marca
        """
        return self.execute_query(query, params)

    def get_cobertura_sucursal_generico(
        self,
        periodo_desde: str | None = None,
        periodo_hasta: str | None = None,
        periodos: list[str] | None = None,
        sucursales: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Obtiene cobertura agregada por sucursal y generico.

        Agrega datos de cob_preventista_generico agrupando por sucursal.

        Args:
            periodo_desde: Periodo inicio formato 'YYYY-MM-DD' (rango)
            periodo_hasta: Periodo fin formato 'YYYY-MM-DD' (rango)
            periodos: Lista de periodos especificos ['2025-02-01', '2026-01-01']
            sucursales: Lista de sucursales a filtrar.
        """
        filtro_per, params = self._filtro_periodos("cpg", periodos, periodo_desde, periodo_hasta)
        filtro_suc, params_suc = self._filtro_sucursales("cpg", sucursales)
        params.update(params_suc)

        query = f"""
        SELECT
            cpg.periodo,
            cpg.ds_sucursal AS sucursal,
            cpg.generico,
            SUM(cpg.clientes_compradores) AS clientes_compradores,
            SUM(cpg.volumen_total) AS volumen_total
        FROM gold.cob_preventista_generico cpg
        WHERE {filtro_per}
        {filtro_suc}
        GROUP BY cpg.periodo, cpg.ds_sucursal, cpg.generico
        ORDER BY cpg.periodo, cpg.ds_sucursal, cpg.generico
        """
        return self.execute_query(query, params)

    def get_ultima_fecha_venta(self):
        """Obtiene la fecha mas reciente de venta en fact_ventas.

        Returns:
            date o None si no hay datos.
        """
        query = "SELECT MAX(fv.fecha_comprobante) AS ultima_venta FROM gold.fact_ventas fv"
        df = self.execute_query(query)
        if df.empty or df["ultima_venta"].iloc[0] is None:
            return None
        return pd.to_datetime(df["ultima_venta"].iloc[0]).date()


# Instancia por defecto para compatibilidad
_default_loader = None


def get_default_loader() -> DataLoader:
    """Obtiene la instancia por defecto del DataLoader."""
    global _default_loader
    if _default_loader is None:
        _default_loader = DataLoader()
    return _default_loader


# Funciones de compatibilidad con codigo existente
def get_engine():
    return get_default_loader().engine


def get_connection():
    return get_default_loader().get_connection()


def get_sucursales():
    return get_default_loader().get_sucursales()


def get_articulos(genericos=None):
    return get_default_loader().get_articulos(genericos)


def get_ventas(fecha_desde, fecha_hasta, genericos=None):
    return get_default_loader().get_ventas(fecha_desde, fecha_hasta, genericos)
