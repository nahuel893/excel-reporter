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

    def get_ventas_diarias(
        self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None
    ) -> pd.DataFrame:
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

    def get_ventas_diarias_con_ruta(
        self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None
    ) -> pd.DataFrame:
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
            LEFT JOIN gold.dim_cliente dc ON fv.id_cliente = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
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
            LEFT JOIN gold.dim_cliente dc ON fv.id_cliente = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
            GROUP BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}

        return self.execute_query(query, params)

    def get_ventas_historico_mmaa(
        self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Obtiene ventas del mismo periodo del año anterior (MMAA).

        Desplaza internamente las fechas -1 año con relativedelta.
        Misma estructura de JOINs que get_ventas_diarias_con_ruta pero sin monto.

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD' (del periodo actual)
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD' (del periodo actual)
            genericos: Lista de genericos a filtrar. Si es None, trae todos.

        Returns:
            DataFrame con columnas: sucursal, generico, marca, fecha, id_ruta, cantidad, cantidad_htls
        """
        desde = (pd.to_datetime(fecha_desde) - relativedelta(years=1)).strftime("%Y-%m-%d")
        hasta = (pd.to_datetime(fecha_hasta) - relativedelta(years=1)).strftime("%Y-%m-%d")

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
                SUM(fv.cantidad_total_htls) AS cantidad_htls
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
            LEFT JOIN gold.dim_cliente dc ON fv.id_cliente = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
            AND da.generico IN ({placeholders})
            GROUP BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante
            """
            params = {"desde": desde, "hasta": hasta}
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
                SUM(fv.cantidad_total_htls) AS cantidad_htls
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
            LEFT JOIN gold.dim_cliente dc ON fv.id_cliente = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
            GROUP BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico, da.marca, fv.fecha_comprobante
            """
            params = {"desde": desde, "hasta": hasta}

        return self.execute_query(query, params)

    def get_ventas(
        self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None
    ) -> pd.DataFrame:
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

    def get_ventas_resumen_mensual(
        self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None
    ) -> pd.DataFrame:
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
            LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
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
            LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
              AND da.generico IS NOT NULL
            GROUP BY ds.descripcion, da.generico, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}

        return self.execute_query(query, params)

    def get_ventas_ultimos_dias_habiles(
        self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None
    ) -> pd.DataFrame:
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
            LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
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
            LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
            WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
              AND da.generico IS NOT NULL
            GROUP BY ds.descripcion, da.generico, fv.fecha_comprobante, dc.id_ruta_fv1
            ORDER BY ds.descripcion, da.generico, fv.fecha_comprobante
            """
            params = {"desde": fecha_desde, "hasta": fecha_hasta}

        return self.execute_query(query, params)

    def get_ventas_mes_anterior(
        self, fecha_desde: str, genericos: list[str] | None = None
    ) -> pd.DataFrame:
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
        primer_dia = fecha_dt.replace(day=1) - relativedelta(months=1)
        ultimo_dia = fecha_dt.replace(day=1) - timedelta(days=1)
        return self.get_ventas_resumen_mensual(
            primer_dia.strftime("%Y-%m-%d"),
            ultimo_dia.strftime("%Y-%m-%d"),
            genericos,
        )

    def get_ventas_mismo_mes_anio_anterior(
        self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None
    ) -> pd.DataFrame:
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
        return self.get_ventas_resumen_mensual(
            fecha_desde_aa, fecha_hasta_aa, genericos
        )

    def get_ventas_mision_imposible_categorias(
        self, fecha_desde: str, fecha_hasta: str, articulos_ids: list[int]
    ) -> pd.DataFrame:
        """Obtiene ventas detalladas por cliente y articulo para armar pivot de categorias."""
        if not articulos_ids:
            return pd.DataFrame()

        placeholders = ", ".join([f":art_{i}" for i in range(len(articulos_ids))])

        query = f"""
        SELECT
            ds.descripcion AS sucursal,
            dc.id_ruta_fv1 AS id_ruta,
            fv.id_vendedor,
            dv.des_vendedor AS vendedor,
            fv.id_cliente,
            COALESCE(dc.fantasia, dc.razon_social) AS cliente,
            da.marca,
            fv.id_articulo,
            da.des_articulo,
            SUM(fv.cantidades_total) AS cantidad
        FROM gold.fact_ventas fv
        LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
        LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
        LEFT JOIN gold.dim_cliente dc ON fv.id_cliente = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
        LEFT JOIN gold.dim_vendedor dv ON fv.id_vendedor = dv.id_vendedor AND fv.id_sucursal = dv.id_sucursal
        WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
        AND fv.id_articulo IN ({placeholders})
        GROUP BY
            ds.descripcion, dc.id_ruta_fv1, fv.id_vendedor, dv.des_vendedor,
            fv.id_cliente, COALESCE(dc.fantasia, dc.razon_social),
            da.marca, fv.id_articulo, da.des_articulo
        HAVING SUM(fv.cantidades_total) > 0
        """
        params = {"desde": fecha_desde, "hasta": fecha_hasta}
        params.update({f"art_{i}": art for i, art in enumerate(articulos_ids)})

        return self.execute_query(query, params)

    def get_ventas_historico_fratelli(
        self,
        id_sucursal: int = 1,
        generico: str = "FRATELLI B",
    ) -> pd.DataFrame:
        """
        Obtiene ventas mensuales de un generico por anio, marca y lista de precio.
        Filtra sucursal fija, excluye facturas presupuesto (PRVTA).
        Trae datos de 2024, 2025 y 2026.
        """
        query = """
        SELECT
            EXTRACT(YEAR FROM fv.fecha_comprobante)::int AS anio,
            EXTRACT(MONTH FROM fv.fecha_comprobante)::int AS mes,
            da.marca,
            dc.id_lista_precio,
            SUM(fv.cantidades_total) AS cantidad,
            SUM(fv.descuentos) AS descuentos
        FROM gold.fact_ventas fv
        JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
        LEFT JOIN gold.dim_cliente dc
            ON fv.id_cliente = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
        WHERE fv.id_sucursal = :id_sucursal
          AND da.generico = :generico
          AND fv.id_documento != 'PRVTA'
          AND fv.fecha_comprobante >= '2024-01-01'
          AND fv.fecha_comprobante <= '2026-12-31'
        GROUP BY anio, mes, da.marca, dc.id_lista_precio
        ORDER BY anio, mes
        """
        return self.execute_query(
            query, {"id_sucursal": id_sucursal, "generico": generico}
        )

    def get_cobertura_historico_fratelli(
        self,
        id_sucursal: int = 1,
        generico: str = "FRATELLI B",
    ) -> dict[str, pd.DataFrame]:
        """
        Obtiene cobertura historica de FRATELLI B desde 3 tablas:
        - cob_sucursal_generico: total por mes
        - cob_sucursal_lista_generico: por lista de precio
        - cob_sucursal_marca: por marca

        Returns:
            dict con keys 'total', 'lista', 'marca', cada uno un DataFrame
            con columnas: anio, mes, [dimension], clientes_compradores
        """
        base_where = """
            WHERE ds_sucursal = (
                SELECT descripcion FROM gold.dim_sucursal WHERE id_sucursal = :id_sucursal LIMIT 1
            )
            AND periodo >= '2024-01-01'
            AND periodo <= '2026-12-31'
        """
        params = {"id_sucursal": id_sucursal, "generico": generico}

        # Total por mes (cob_sucursal_generico)
        q_total = f"""
        SELECT
            EXTRACT(YEAR FROM periodo)::int AS anio,
            EXTRACT(MONTH FROM periodo)::int AS mes,
            SUM(clientes_compradores) AS clientes_compradores
        FROM gold.cob_sucursal_generico
        {base_where}
        AND generico = :generico
        GROUP BY anio, mes
        ORDER BY anio, mes
        """

        # Por lista de precio (cob_sucursal_lista_generico)
        q_lista = f"""
        SELECT
            EXTRACT(YEAR FROM periodo)::int AS anio,
            EXTRACT(MONTH FROM periodo)::int AS mes,
            id_lista_precio,
            SUM(clientes_compradores) AS clientes_compradores
        FROM gold.cob_sucursal_lista_generico
        {base_where}
        AND generico = :generico
        GROUP BY anio, mes, id_lista_precio
        ORDER BY anio, mes, id_lista_precio
        """

        # Por marca (cob_sucursal_marca) — filtra marcas del genérico via dim_articulo
        q_marca = f"""
        SELECT
            EXTRACT(YEAR FROM csm.periodo)::int AS anio,
            EXTRACT(MONTH FROM csm.periodo)::int AS mes,
            csm.marca,
            SUM(csm.clientes_compradores) AS clientes_compradores
        FROM gold.cob_sucursal_marca csm
        WHERE csm.ds_sucursal = (
            SELECT descripcion FROM gold.dim_sucursal WHERE id_sucursal = :id_sucursal LIMIT 1
        )
        AND csm.periodo >= '2024-01-01'
        AND csm.periodo <= '2026-12-31'
        AND csm.marca IN (
            SELECT DISTINCT marca FROM gold.dim_articulo WHERE generico = :generico
        )
        GROUP BY anio, mes, csm.marca
        ORDER BY anio, mes, csm.marca
        """

        return {
            "total": self.execute_query(q_total, params),
            "lista": self.execute_query(q_lista, params),
            "marca": self.execute_query(q_marca, params),
        }

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
            raise ValueError(
                "Debe especificar 'periodos' o 'periodo_desde'/'periodo_hasta'"
            )
        return filtro, params

    def _filtro_sucursales(
        self, alias: str, sucursales: list[str] | None
    ) -> tuple[str, dict]:
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
        sucursales: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Obtiene cobertura por preventista y generico.

        Args:
            periodo_desde: Periodo inicio formato 'YYYY-MM-DD' (rango)
            periodo_hasta: Periodo fin formato 'YYYY-MM-DD' (rango)
            periodos: Lista de periodos especificos ['2025-02-01', '2026-01-01']
            sucursales: Lista de sucursales a filtrar.
        """
        filtro_per, params = self._filtro_periodos(
            "cpg", periodos, periodo_desde, periodo_hasta
        )
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
        LEFT JOIN gold.dim_vendedor dv
            ON cpg.id_vendedor = dv.id_vendedor
            AND cpg.id_sucursal = dv.id_sucursal
        WHERE cpg.id_fuerza_ventas = 1
        AND {filtro_per}
        {filtro_suc}
        ORDER BY cpg.periodo, cpg.ds_sucursal, dv.des_vendedor, cpg.generico
        """
        return self.execute_query(query, params)

    def get_cobertura_preventista_marca(
        self,
        periodo_desde: str | None = None,
        periodo_hasta: str | None = None,
        periodos: list[str] | None = None,
        sucursales: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Obtiene cobertura por preventista y marca.

        Args:
            periodo_desde: Periodo inicio formato 'YYYY-MM-DD' (rango)
            periodo_hasta: Periodo fin formato 'YYYY-MM-DD' (rango)
            periodos: Lista de periodos especificos ['2025-02-01', '2026-01-01']
            sucursales: Lista de sucursales a filtrar.
        """
        filtro_per, params = self._filtro_periodos(
            "cpm", periodos, periodo_desde, periodo_hasta
        )
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
        LEFT JOIN gold.dim_vendedor dv
            ON cpm.id_vendedor = dv.id_vendedor
            AND cpm.id_sucursal = dv.id_sucursal
        WHERE cpm.id_fuerza_ventas = 1
        AND {filtro_per}
        {filtro_suc}
        ORDER BY cpm.periodo, cpm.ds_sucursal, dv.des_vendedor, cpm.marca
        """
        return self.execute_query(query, params)

    def get_cobertura_custom(
        self,
        periodo: str,
        marcas: list[str],
        filtro_descripcion: str | None = None,
        requiere_todas_marcas: bool = False,
        articulos_ids: list[int] | None = None,
    ) -> pd.DataFrame:
        """
        Calcula cobertura desde fact_ventas para un grupo de marcas o articulos especificos.

        Args:
            periodo: Primer dia del mes, formato 'YYYY-MM-DD'.
            marcas: Lista de marcas en dim_articulo. Requerido si articulos_ids es None.
                    Cuando articulos_ids esta presente, marcas se usa solo para calcular
                    num_marcas en la logica requiere_todas_marcas.
            filtro_descripcion: Substring ILIKE sobre des_articulo. Opcional.
            requiere_todas_marcas: Si True, cuenta solo clientes con compra en CADA marca.
            articulos_ids: Lista de id_articulo especificos. Si se provee, filtra por
                           fv.id_articulo IN (...) en lugar de da.marca IN (...).

        Returns:
            DataFrame con columnas:
                periodo, id_fuerza_ventas, id_sucursal, sucursal, vendedor,
                id_ruta, clientes_compradores, volumen_total
        """
        if not marcas and articulos_ids is None:
            raise ValueError("marcas no puede estar vacia.")

        if articulos_ids is not None and not articulos_ids:
            raise ValueError("articulos_ids no puede estar vacia.")

        marcas_upper = [m.upper() for m in marcas]
        marcas_upper = list(dict.fromkeys(marcas_upper))  # deduplicate preserving order

        params: dict = {"periodo": periodo}

        # Build principal filter clause
        if articulos_ids is not None:
            if len(articulos_ids) > 1000:
                print(
                    f"⚠ articulos_ids tiene {len(articulos_ids)} elementos en el IN clause."
                )
            art_params = {f"art_{i}": aid for i, aid in enumerate(articulos_ids)}
            art_placeholders = ", ".join(f":art_{i}" for i in range(len(articulos_ids)))
            filtro_principal_clause = f"AND fv.id_articulo IN ({art_placeholders})"
            params.update(art_params)
        else:
            marca_params = {f"marca_{i}": m for i, m in enumerate(marcas_upper)}
            marca_placeholders = ", ".join(
                f":marca_{i}" for i in range(len(marcas_upper))
            )
            filtro_principal_clause = f"AND da.marca IN ({marca_placeholders})"
            params.update(marca_params)

        if filtro_descripcion is not None and filtro_descripcion.strip() == "":
            filtro_descripcion = None

        if filtro_descripcion is not None:
            escaped = filtro_descripcion.replace("%", r"\%").replace("_", r"\_")
            filtro_desc_clause = "AND da.des_articulo ILIKE :filtro"
            params["filtro"] = f"%{escaped}%"
        else:
            filtro_desc_clause = ""

        usar_todas_marcas = requiere_todas_marcas and len(marcas_upper) >= 2

        if usar_todas_marcas:
            params["num_marcas"] = len(marcas_upper)
            query = self._build_query_todas_marcas(
                filtro_principal_clause, filtro_desc_clause
            )
        else:
            query = self._build_query_default(
                filtro_principal_clause, filtro_desc_clause
            )

        return self.execute_query(query, params)

    def _build_query_default(
        self, filtro_principal_clause: str, filtro_desc_clause: str
    ) -> str:
        return f"""
        WITH vendedor_cliente AS (
            -- Rama FV1
            SELECT
                DATE_TRUNC('month', fv.fecha_comprobante)::date AS periodo,
                1                                               AS id_fuerza_ventas,
                dc.des_personal_fv1                             AS vendedor,
                dc.id_ruta_fv1                                  AS id_ruta,
                fv.id_sucursal,
                ds.descripcion                                  AS sucursal,
                fv.id_cliente,
                SUM(fv.cantidades_total)                        AS total_qty
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_cliente  dc ON fv.id_cliente  = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
                                          AND fv.id_sucursal = dc.id_sucursal
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal  = ds.id_sucursal
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo  = da.id_articulo
            WHERE dc.des_personal_fv1 IS NOT NULL
              {filtro_principal_clause}
              {filtro_desc_clause}
              AND DATE_TRUNC('month', fv.fecha_comprobante) = :periodo
            GROUP BY 1, 2, 3, 4, 5, 6, fv.id_cliente
            HAVING SUM(fv.cantidades_total) > 0

            UNION ALL

            -- Rama FV4
            SELECT
                DATE_TRUNC('month', fv.fecha_comprobante)::date AS periodo,
                4                                               AS id_fuerza_ventas,
                dc.des_personal_fv4                             AS vendedor,
                dc.id_ruta_fv4                                  AS id_ruta,
                fv.id_sucursal,
                ds.descripcion                                  AS sucursal,
                fv.id_cliente,
                SUM(fv.cantidades_total)                        AS total_qty
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_cliente  dc ON fv.id_cliente  = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
                                          AND fv.id_sucursal = dc.id_sucursal
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal  = ds.id_sucursal
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo  = da.id_articulo
            WHERE dc.des_personal_fv4 IS NOT NULL
              {filtro_principal_clause}
              {filtro_desc_clause}
              AND DATE_TRUNC('month', fv.fecha_comprobante) = :periodo
            GROUP BY 1, 2, 3, 4, 5, 6, fv.id_cliente
            HAVING SUM(fv.cantidades_total) > 0
        )
        SELECT
            vc.periodo,
            vc.id_fuerza_ventas,
            vc.id_sucursal,
            vc.sucursal,
            vc.vendedor,
            vc.id_ruta,
            COUNT(DISTINCT vc.id_cliente)    AS clientes_compradores,
            SUM(vc.total_qty)                AS volumen_total
        FROM vendedor_cliente vc
        GROUP BY vc.periodo, vc.id_fuerza_ventas, vc.id_sucursal, vc.sucursal,
                 vc.vendedor, vc.id_ruta
        ORDER BY vc.sucursal, vc.vendedor
        """

    def _build_query_todas_marcas(
        self, filtro_principal_clause: str, filtro_desc_clause: str
    ) -> str:
        return f"""
        WITH cliente_marca AS (
            -- Rama FV1: un registro por (cliente, marca) con volumen neto positivo
            SELECT
                DATE_TRUNC('month', fv.fecha_comprobante)::date AS periodo,
                1                                               AS id_fuerza_ventas,
                dc.des_personal_fv1                             AS vendedor,
                dc.id_ruta_fv1                                  AS id_ruta,
                fv.id_sucursal,
                ds.descripcion                                  AS sucursal,
                fv.id_cliente,
                da.marca,
                SUM(fv.cantidades_total)                        AS total_qty
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_cliente  dc ON fv.id_cliente  = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
                                          AND fv.id_sucursal = dc.id_sucursal
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal  = ds.id_sucursal
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo  = da.id_articulo
            WHERE dc.des_personal_fv1 IS NOT NULL
              {filtro_principal_clause}
              {filtro_desc_clause}
              AND DATE_TRUNC('month', fv.fecha_comprobante) = :periodo
            GROUP BY 1, 2, 3, 4, 5, 6, fv.id_cliente, da.marca
            HAVING SUM(fv.cantidades_total) > 0

            UNION ALL

            -- Rama FV4
            SELECT
                DATE_TRUNC('month', fv.fecha_comprobante)::date AS periodo,
                4                                               AS id_fuerza_ventas,
                dc.des_personal_fv4                             AS vendedor,
                dc.id_ruta_fv4                                  AS id_ruta,
                fv.id_sucursal,
                ds.descripcion                                  AS sucursal,
                fv.id_cliente,
                da.marca,
                SUM(fv.cantidades_total)                        AS total_qty
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_cliente  dc ON fv.id_cliente  = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
                                          AND fv.id_sucursal = dc.id_sucursal
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal  = ds.id_sucursal
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo  = da.id_articulo
            WHERE dc.des_personal_fv4 IS NOT NULL
              {filtro_principal_clause}
              {filtro_desc_clause}
              AND DATE_TRUNC('month', fv.fecha_comprobante) = :periodo
            GROUP BY 1, 2, 3, 4, 5, 6, fv.id_cliente, da.marca
            HAVING SUM(fv.cantidades_total) > 0
        ),
        cliente_valido AS (
            SELECT
                periodo,
                id_fuerza_ventas,
                vendedor,
                id_ruta,
                id_sucursal,
                sucursal,
                id_cliente,
                SUM(total_qty) AS total_qty
            FROM cliente_marca
            GROUP BY periodo, id_fuerza_ventas, vendedor, id_ruta,
                     id_sucursal, sucursal, id_cliente
            HAVING COUNT(DISTINCT marca) = :num_marcas
        )
        SELECT
            cv.periodo,
            cv.id_fuerza_ventas,
            cv.id_sucursal,
            cv.sucursal,
            cv.vendedor,
            cv.id_ruta,
            COUNT(DISTINCT cv.id_cliente)    AS clientes_compradores,
            SUM(cv.total_qty)                AS volumen_total
        FROM cliente_valido cv
        GROUP BY cv.periodo, cv.id_fuerza_ventas, cv.id_sucursal, cv.sucursal,
                 cv.vendedor, cv.id_ruta
        ORDER BY cv.sucursal, cv.vendedor
        """

    def get_cobertura_sucursal_marca(
        self,
        periodo_desde: str | None = None,
        periodo_hasta: str | None = None,
        periodos: list[str] | None = None,
        sucursales: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Obtiene cobertura agregada por sucursal y marca.

        Args:
            periodo_desde: Periodo inicio formato 'YYYY-MM-DD' (rango)
            periodo_hasta: Periodo fin formato 'YYYY-MM-DD' (rango)
            periodos: Lista de periodos especificos ['2025-02-01', '2026-01-01']
            sucursales: Lista de sucursales a filtrar.
        """
        filtro_per, params = self._filtro_periodos(
            "csm", periodos, periodo_desde, periodo_hasta
        )
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
        sucursales: list[str] | None = None,
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
        filtro_per, params = self._filtro_periodos(
            "cpg", periodos, periodo_desde, periodo_hasta
        )
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
        WHERE cpg.id_fuerza_ventas = 1
        AND {filtro_per}
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
        query = (
            "SELECT MAX(fv.fecha_comprobante) AS ultima_venta FROM gold.fact_ventas fv"
        )
        df = self.execute_query(query)
        if df.empty or df["ultima_venta"].iloc[0] is None:
            return None
        return pd.to_datetime(df["ultima_venta"].iloc[0]).date()

    # ── Stock Diario ────────────────────────────────────────────

    def get_stock_diario(self, fecha: str) -> pd.DataFrame:
        """Stock snapshot for a single date, grouped by article+sucursal.

        Args:
            fecha: Date string in 'YYYY-MM-DD' format.

        Returns:
            DataFrame with columns: generico, marca, des_articulo, sucursal,
            cant_bultos, cant_htls.
        """
        query = """
        SELECT
            a.generico,
            a.marca,
            a.des_articulo,
            d.des_sucursal AS sucursal,
            SUM(f.cant_bultos) AS cant_bultos,
            SUM(f.cantidad_total_htls) AS cant_htls
        FROM gold.fact_stock f
        JOIN gold.dim_articulo a ON a.id_articulo = f.id_articulo
        JOIN gold.dim_deposito d ON d.id_deposito = f.id_deposito
        WHERE f.date_stock = :fecha
        GROUP BY a.generico, a.marca, a.des_articulo, d.des_sucursal
        ORDER BY a.generico, a.marca, a.des_articulo, d.des_sucursal
        """
        return self.execute_query(query, {"fecha": fecha})


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
