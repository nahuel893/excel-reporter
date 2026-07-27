"""
DataLoader - Acceso a datos del Data Warehouse.

Proporciona acceso centralizado a la base de datos PostgreSQL
usando SQLAlchemy con soporte para inyección de dependencias.
"""

from datetime import timedelta, datetime, date

import pandas as pd
from dateutil.relativedelta import relativedelta
from sqlalchemy import create_engine, text, Engine

from config.settings import DB_CONFIG


def _build_marca_split_clause(
    marca_splits: dict[str, list[str]] | None, params: dict
) -> str:
    """Build the SQL CASE expression that rewrites ``da.generico`` per marca_splits.

    For each (generico, [marcas]) entry, rows whose ``da.marca`` is in the list
    surface their marca as the synthetic generico value; the rest surface as
    ``"{generico} (sin {m1, m2, ...})"``. Genericos NOT in marca_splits are returned
    unchanged.

    Mutates ``params`` in-place to register the named parameters used by the
    CASE clause. Caller is responsible for passing those params to execute_query.

    Returns:
        ``"da.generico"`` if marca_splits is None/empty.
        ``"CASE ... ELSE da.generico END"`` otherwise.
    """
    if not marca_splits:
        return "da.generico"

    when_parts: list[str] = []
    counter = 0
    for generico, marcas in marca_splits.items():
        gen_param = f"split_g_{counter}"
        params[gen_param] = generico
        counter += 1
        for marca in marcas:
            marca_param = f"split_m_{counter}"
            params[marca_param] = marca
            when_parts.append(
                f"WHEN da.generico = :{gen_param} AND da.marca = :{marca_param} THEN da.marca"
            )
            counter += 1
        label = f"{generico} (sin {', '.join(marcas)})"
        label_param = f"split_l_{counter}"
        params[label_param] = label
        counter += 1
        when_parts.append(f"WHEN da.generico = :{gen_param} THEN :{label_param}")

    return "CASE\n            " + "\n            ".join(when_parts) + "\n            ELSE da.generico END"


class DataLoader:
    """Clase para acceso a datos del Data Warehouse."""

    def __init__(self, engine: Engine | None = None, db_name: str | None = None):
        """
        Inicializa el DataLoader.

        Args:
            engine: Engine de SQLAlchemy. Si es None, crea uno con DB_CONFIG.
            db_name: Nombre de la base de datos override. Si es None, usa DB_NAME de DB_CONFIG.
        """
        self._engine = engine
        self._db_name = db_name

    @property
    def engine(self) -> Engine:
        """Obtiene el engine, creándolo si no existe."""
        if self._engine is None:
            db = self._db_name or DB_CONFIG['database']
            url = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{db}"
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

    def get_dim_articulo(self) -> pd.DataFrame:
        """
        Obtiene la tabla `dim_articulo` completa para usar como lookup table
        en hojas de Excel (VLOOKUP por id_articulo).

        Returns:
            DataFrame con columnas: id_articulo, generico, marca, des_articulo
        """
        query = """
        SELECT id_articulo, generico, marca, des_articulo
        FROM gold.dim_articulo
        WHERE generico IS NOT NULL
        ORDER BY id_articulo
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
                SUM(fv.subtotal_neto) AS monto,
                SUM(fv.descuentos) AS descuentos
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
                SUM(fv.subtotal_neto) AS monto,
                SUM(fv.descuentos) AS descuentos
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
        Obtiene ventas del MES completo del año anterior (MMAA — Mismo Mes Año Anterior).

        Para cada mes cubierto por [fecha_desde, fecha_hasta] del periodo actual,
        trae todo el mes equivalente un año atrás. Esto evita comparar rangos
        parciales (ej: corriendo el reporte el 5 de mayo, igual debe traer mayo
        completo del año anterior, no solo del 1 al 5).

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD' (del periodo actual)
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD' (del periodo actual)
            genericos: Lista de genericos a filtrar. Si es None, trae todos.

        Returns:
            DataFrame con columnas: sucursal, generico, marca, fecha, id_ruta, cantidad, cantidad_htls
        """
        # MMAA: rango completo del/los mes(es) cubierto(s), un año atrás.
        # desde → primer dia del mes (de fecha_desde) un año atras.
        # hasta → ultimo dia del mes (de fecha_hasta) un año atras.
        desde_prev = (pd.to_datetime(fecha_desde) - relativedelta(years=1)).replace(day=1)
        hasta_prev_first = (pd.to_datetime(fecha_hasta) - relativedelta(years=1)).replace(day=1)
        hasta_prev = hasta_prev_first + relativedelta(months=1, days=-1)
        desde = desde_prev.strftime("%Y-%m-%d")
        hasta = hasta_prev.strftime("%Y-%m-%d")

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
        self,
        fecha_desde: str,
        fecha_hasta: str,
        genericos: list[str] | None = None,
        genericos_sin_prvta: list[str] | None = None,
        marca_splits: dict[str, list[str]] | None = None,
    ) -> pd.DataFrame:
        """
        Obtiene ventas mensuales agrupadas por sucursal, generico e id_ruta.

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD'
            genericos: Lista de genericos a filtrar. Si es None, trae todos.
            genericos_sin_prvta: Lista de genericos para los cuales se DEBE excluir
                fact_ventas.id_documento = 'PRVTA' (facturas presupuesto). Otros
                genericos no se ven afectados. Si es None o vacio, no se aplica filtro.
            marca_splits: Mapping de generico -> lista de marcas a separar. Para los
                genericos listados, cada marca matcheada se reporta como su propio
                "generico" sintetico (la marca pasa a la columna generico) y el resto
                se reporta como "{generico} (sin {marcas})". Si es None o vacio, no
                hay split.

        Returns:
            DataFrame con columnas: sucursal, generico, id_ruta, cantidad
        """
        params = {"desde": fecha_desde, "hasta": fecha_hasta}
        where_clauses = [
            "fv.fecha_comprobante BETWEEN :desde AND :hasta",
            "da.generico IS NOT NULL",
        ]
        if genericos:
            placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
            where_clauses.append(f"da.generico IN ({placeholders})")
            params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        if genericos_sin_prvta:
            sp_placeholders = ", ".join([f":sp_{i}" for i in range(len(genericos_sin_prvta))])
            where_clauses.append(
                f"NOT (da.generico IN ({sp_placeholders}) AND fv.id_documento = 'PRVTA')"
            )
            params.update({f"sp_{i}": g for i, g in enumerate(genericos_sin_prvta)})

        where_sql = "\n              AND ".join(where_clauses)
        generico_expr = _build_marca_split_clause(marca_splits, params)
        query = f"""
        SELECT
            ds.descripcion          AS sucursal,
            {generico_expr}         AS generico,
            dc.id_ruta_fv1          AS id_ruta,
            SUM(fv.cantidades_total) AS cantidad
        FROM gold.fact_ventas fv
        LEFT JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
        LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal  = ds.id_sucursal
        LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
        WHERE {where_sql}
        GROUP BY 1, 2, 3
        ORDER BY 1, 2
        """

        return self.execute_query(query, params)

    def get_ventas_ultimos_dias_habiles(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        genericos: list[str] | None = None,
        genericos_sin_prvta: list[str] | None = None,
        marca_splits: dict[str, list[str]] | None = None,
    ) -> pd.DataFrame:
        """
        Obtiene ventas diarias del rango completo del mes, con desglose por fecha e id_ruta.

        Args:
            fecha_desde: Primer dia del mes formato 'YYYY-MM-DD'
            fecha_hasta: Ultimo dia del rango formato 'YYYY-MM-DD'
            genericos: Lista de genericos a filtrar. Si es None, trae todos.
            genericos_sin_prvta: Lista de genericos para los cuales se DEBE excluir
                fact_ventas.id_documento = 'PRVTA' (facturas presupuesto).
            marca_splits: Mapping generico -> [marcas]. Las marcas matcheadas se
                reportan como su propio "generico" sintetico; el resto del generico
                se reporta como "{generico} (sin {marcas})".

        Returns:
            DataFrame con columnas: sucursal, generico, fecha, id_ruta, cantidad
        """
        params = {"desde": fecha_desde, "hasta": fecha_hasta}
        where_clauses = [
            "fv.fecha_comprobante BETWEEN :desde AND :hasta",
            "da.generico IS NOT NULL",
        ]
        if genericos:
            placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
            where_clauses.append(f"da.generico IN ({placeholders})")
            params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        if genericos_sin_prvta:
            sp_placeholders = ", ".join([f":sp_{i}" for i in range(len(genericos_sin_prvta))])
            where_clauses.append(
                f"NOT (da.generico IN ({sp_placeholders}) AND fv.id_documento = 'PRVTA')"
            )
            params.update({f"sp_{i}": g for i, g in enumerate(genericos_sin_prvta)})

        where_sql = "\n              AND ".join(where_clauses)
        generico_expr = _build_marca_split_clause(marca_splits, params)
        query = f"""
        SELECT
            ds.descripcion           AS sucursal,
            {generico_expr}          AS generico,
            fv.fecha_comprobante     AS fecha,
            dc.id_ruta_fv1           AS id_ruta,
            SUM(fv.cantidades_total) AS cantidad
        FROM gold.fact_ventas fv
        LEFT JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
        LEFT JOIN gold.dim_sucursal  ds ON fv.id_sucursal  = ds.id_sucursal
        LEFT JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
        WHERE {where_sql}
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3
        """

        return self.execute_query(query, params)

    def get_ventas_mes_anterior(
        self,
        fecha_desde: str,
        genericos: list[str] | None = None,
        genericos_sin_prvta: list[str] | None = None,
        marca_splits: dict[str, list[str]] | None = None,
    ) -> pd.DataFrame:
        """
        Obtiene ventas del mes calendario completo anterior a fecha_desde.

        Args:
            fecha_desde: Fecha de referencia formato 'YYYY-MM-DD'.
            genericos: Lista de genericos a filtrar. Si es None, trae todos.
            genericos_sin_prvta: Genericos para los que se excluye id_documento='PRVTA'.
            marca_splits: Mapping generico -> [marcas] para split por marca (sintetizando
                el valor de la columna generico).

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
            genericos_sin_prvta=genericos_sin_prvta,
            marca_splits=marca_splits,
        )

    def get_ventas_mismo_mes_anio_anterior(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        genericos: list[str] | None = None,
        genericos_sin_prvta: list[str] | None = None,
        marca_splits: dict[str, list[str]] | None = None,
    ) -> pd.DataFrame:
        """
        Obtiene ventas del MES completo del año anterior (MMAA — Mismo Mes Año Anterior).

        Para cada mes cubierto por [fecha_desde, fecha_hasta] del periodo actual,
        trae todo el mes equivalente un año atrás. Esto evita comparar rangos
        parciales (ej: corriendo el reporte el día 7, igual debe traer el mes
        completo del año anterior, no solo del 1 al 7).

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD'
            genericos: Lista de genericos a filtrar. Si es None, trae todos.
            genericos_sin_prvta: Genericos para los que se excluye id_documento='PRVTA'.
            marca_splits: Mapping generico -> [marcas] para split por marca.

        Returns:
            DataFrame con columnas: sucursal, generico, id_ruta, cantidad
        """
        # MMAA: rango completo del/los mes(es) cubierto(s), un año atrás.
        # desde → primer dia del mes (de fecha_desde) un año atras.
        # hasta → ultimo dia del mes (de fecha_hasta) un año atras.
        desde_prev = (datetime.strptime(fecha_desde, "%Y-%m-%d").date() - relativedelta(years=1)).replace(day=1)
        hasta_prev_first = (datetime.strptime(fecha_hasta, "%Y-%m-%d").date() - relativedelta(years=1)).replace(day=1)
        hasta_prev = hasta_prev_first + relativedelta(months=1) - timedelta(days=1)
        return self.get_ventas_resumen_mensual(
            desde_prev.strftime("%Y-%m-%d"),
            hasta_prev.strftime("%Y-%m-%d"),
            genericos,
            genericos_sin_prvta=genericos_sin_prvta,
            marca_splits=marca_splits,
        )

    def get_cupos_resumen_mensual(
        self, periodo: str, genericos: list[str]
    ) -> pd.DataFrame:
        """
        Obtiene cupos (objetivos) desde gold.fact_cupos para el resumen mensual.

        Args:
            periodo: Periodo en formato 'YYYY-MM' (e.g. '2026-04')
            genericos: Lista de genericos a filtrar (top-level, sin aperturas).

        Returns:
            DataFrame con columnas: sucursal, generico, cupo
            Agregado por (descripcion, generico) — SUM(cupo).
        """
        placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
        query = f"""
        SELECT
            REGEXP_REPLACE(sucursal, '^\\d+ - ', '') AS sucursal,
            id_ruta,
            generico,
            SUM(cupo)                                AS cupo
        FROM gold.fact_cupos
        WHERE periodo = :periodo
          AND generico IN ({placeholders})
        GROUP BY sucursal, id_ruta, generico
        ORDER BY sucursal, id_ruta, generico
        """
        params: dict = {"periodo": periodo}
        params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        return self.execute_query(query, params)

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
            da.calibre,
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
            da.marca, da.calibre, fv.id_articulo, da.des_articulo
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

    def get_prvta_historico_fratelli(
        self,
        id_sucursal: int = 1,
        generico: str = "FRATELLI B",
    ) -> pd.DataFrame:
        """
        Obtiene volumen (cantidades_total) de facturas presupuesto (PRVTA)
        de un generico, agregado por anio y mes.
        Trae datos de 2024, 2025 y 2026.
        """
        query = """
        SELECT
            EXTRACT(YEAR FROM fv.fecha_comprobante)::int AS anio,
            EXTRACT(MONTH FROM fv.fecha_comprobante)::int AS mes,
            SUM(fv.cantidades_total) AS cantidad
        FROM gold.fact_ventas fv
        JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
        WHERE fv.id_sucursal = :id_sucursal
          AND da.generico = :generico
          AND fv.id_documento = 'PRVTA'
          AND fv.fecha_comprobante >= '2024-01-01'
          AND fv.fecha_comprobante <= '2026-12-31'
        GROUP BY anio, mes
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

    def get_ventas_por_marca(
        self,
        generico: str,
        fecha_desde: str,
        fecha_hasta: str,
        id_sucursal: int = 1,
    ) -> pd.DataFrame:
        """Cantidad vendida (bultos) por marca, dentro de un generico y rango de dias.

        Args:
            generico: Nombre exacto del generico (ej. 'PERNOD RICARD').
            fecha_desde / fecha_hasta: rango de dias 'YYYY-MM-DD' (inclusive).
            id_sucursal: Sucursal a filtrar (default 1 = CASA CENTRAL).

        Returns:
            DataFrame con columnas [marca, bultos], ordenado por bultos desc.
        """
        query = """
        SELECT
            da.marca                  AS marca,
            SUM(f.cantidades_total)   AS bultos
        FROM gold.fact_ventas f
        JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
        WHERE da.generico = :generico
          AND f.id_sucursal = :id_sucursal
          AND f.fecha_comprobante::date BETWEEN :fecha_desde AND :fecha_hasta
        GROUP BY da.marca
        ORDER BY bultos DESC, da.marca
        """
        params = {
            "generico": generico,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "id_sucursal": id_sucursal,
        }
        return self.execute_query(query, params)

    def get_ventas_cobertura_por_vendedor(
        self,
        marca: str,
        fecha_desde: str,
        fecha_hasta: str,
        id_sucursal: int = 1,
    ) -> pd.DataFrame:
        """Ventas de una marca por vendedor y cliente, para armar ventas + cobertura.

        Grano fino (vendedor, id_cliente) para poder calcular en pandas tanto los
        bultos (aditivo) como la cobertura (clientes distintos, NO aditiva) a nivel
        vendedor y supervisor.

        REGLA DE ORO: el join a dim_vendedor es por clave COMPUESTA
        (id_vendedor + id_sucursal). id_vendedor se reusa entre sucursales; joinear
        solo por id_vendedor duplica ventas y filtra vendedores de otras sucursales.

        Args:
            marca: Nombre exacto de la marca (ej. 'FULL SPORT').
            fecha_desde / fecha_hasta: rango de dias 'YYYY-MM-DD' (inclusive).
            id_sucursal: Sucursal a filtrar (default 1 = CASA CENTRAL).

        Returns:
            DataFrame con columnas [vendedor, id_cliente, bultos].
        """
        query = """
        SELECT
            dv.des_vendedor           AS vendedor,
            f.id_cliente              AS id_cliente,
            SUM(f.cantidades_total)   AS bultos
        FROM gold.fact_ventas f
        JOIN gold.dim_articulo da ON da.id_articulo = f.id_articulo
        JOIN gold.dim_vendedor dv ON dv.id_vendedor = f.id_vendedor
                                 AND dv.id_sucursal = f.id_sucursal
        WHERE da.marca = :marca
          AND f.id_sucursal = :id_sucursal
          AND f.fecha_comprobante::date BETWEEN :fecha_desde AND :fecha_hasta
        GROUP BY dv.des_vendedor, f.id_cliente
        """
        params = {
            "marca": marca,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "id_sucursal": id_sucursal,
        }
        return self.execute_query(query, params)

    def get_cobertura_generico_por_vendedor(
        self,
        generico: str,
        fecha_desde: str,
        fecha_hasta: str,
        id_sucursal: int = 1,
        id_fuerza_ventas: int = 1,
    ) -> pd.DataFrame:
        """Cobertura (clientes compradores) de un generico, por vendedor, por dia(s).

        Replica EXACTAMENTE la logica del agregador medallion
        (``gold.cob_preventista_generico``) pero al grano DIARIO — porque esa tabla
        es mensual (``DATE_TRUNC('month', ...)``) y no permite filtrar por dia.
        Reglas medallion respetadas:
          - El vendedor es el PREVENTISTA ASIGNADO al cliente
            (``dim_cliente.id_personal_fv1`` para FV1, ``id_personal_fv4`` para FV4),
            NO ``fact_ventas.id_vendedor`` (quien factura).
          - Un cliente cuenta si ``SUM(cantidades_total) > 0`` en el rango (no filtra
            anulado; el neto sale de la suma). No filtra lista de precio.
          - clientes = COUNT(DISTINCT id_cliente) por vendedor.
        Validado: reproduce el total mensual de la tabla al cliente exacto.

        Args:
            generico: Nombre exacto del generico (ej. 'PERNOD RICARD').
            fecha_desde / fecha_hasta: rango de dias 'YYYY-MM-DD' (inclusive; para un
                unico dia pasar el mismo valor en ambos).
            id_sucursal: Sucursal a filtrar (default 1 = CASA CENTRAL).
            id_fuerza_ventas: 1 (todos los preventistas, id_personal_fv1) o 4 (CCU, fv4).

        Returns:
            DataFrame con columnas [vendedor, clientes, volumen]. El supervisor NO
            sale de aca: se mapea en el servicio via SUPERVISOR_VENDOR_MAP
            (dim_vendedor.supervisor no es confiable).
        """
        personal_col = "id_personal_fv4" if id_fuerza_ventas == 4 else "id_personal_fv1"
        query = f"""
        WITH cliente_generico AS (
            SELECT
                dc.{personal_col}          AS id_vendedor,
                fv.id_cliente,
                SUM(fv.cantidades_total)   AS total_qty
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_cliente dc
                ON fv.id_cliente = dc.id_cliente AND fv.id_sucursal = dc.id_sucursal
            LEFT JOIN gold.dim_articulo da
                ON fv.id_articulo = da.id_articulo
            WHERE fv.fecha_comprobante::date BETWEEN :fecha_desde AND :fecha_hasta
              AND fv.id_sucursal = :id_sucursal
              AND da.generico = :generico
              AND dc.{personal_col} IS NOT NULL
            GROUP BY dc.{personal_col}, fv.id_cliente
            HAVING SUM(fv.cantidades_total) > 0
        )
        SELECT
            dv.des_vendedor                 AS vendedor,
            COUNT(DISTINCT cg.id_cliente)   AS clientes,
            SUM(cg.total_qty)               AS volumen
        FROM cliente_generico cg
        JOIN gold.dim_vendedor dv
            ON dv.id_vendedor = cg.id_vendedor
            AND dv.id_fuerza_ventas = :id_fuerza_ventas
            AND dv.id_sucursal = :id_sucursal
        GROUP BY dv.des_vendedor
        ORDER BY clientes DESC, dv.des_vendedor
        """
        params = {
            "generico": generico,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "id_sucursal": id_sucursal,
            "id_fuerza_ventas": id_fuerza_ventas,
        }
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

    def _get_cob_cupos(
        self,
        table: str,
        value_col: str,
        periodo_desde: str,
        periodo_hasta: str,
        sucursales: list[str],
        id_fuerza_ventas: int,
    ) -> pd.DataFrame:
        """Raw cob_preventista_* dump for the cupos-cobertura engine.

        Returns the 10 original table columns (no dim joins), filtered by a
        period range, a single sales force and a list of branch descriptions.
        Ordered by (periodo, id) to mirror a natural table dump.

        ``table`` and ``value_col`` are internal constants (never user input),
        so interpolating them into the SQL is safe.
        """
        placeholders = ", ".join(f":suc_{i}" for i in range(len(sucursales)))
        params: dict = {
            "desde": periodo_desde,
            "hasta": periodo_hasta,
            "fv": id_fuerza_ventas,
        }
        params.update({f"suc_{i}": s for i, s in enumerate(sucursales)})
        query = f"""
        SELECT id, periodo, id_fuerza_ventas, id_vendedor, id_ruta, id_sucursal,
               ds_sucursal, {value_col}, clientes_compradores, volumen_total
        FROM gold.{table}
        WHERE periodo BETWEEN :desde AND :hasta
          AND id_fuerza_ventas = :fv
          AND ds_sucursal IN ({placeholders})
        ORDER BY periodo, id
        """
        return self.execute_query(query, params)

    def get_cob_generico_cupos(
        self,
        periodo_desde: str,
        periodo_hasta: str,
        sucursales: list[str],
        id_fuerza_ventas: int = 1,
    ) -> pd.DataFrame:
        """Raw cob_preventista_generico dump for the cupos-cobertura reload."""
        return self._get_cob_cupos(
            "cob_preventista_generico", "generico",
            periodo_desde, periodo_hasta, sucursales, id_fuerza_ventas,
        )

    def get_cob_marca_cupos(
        self,
        periodo_desde: str,
        periodo_hasta: str,
        sucursales: list[str],
        id_fuerza_ventas: int = 1,
    ) -> pd.DataFrame:
        """Raw cob_preventista_marca dump for the cupos-cobertura reload."""
        return self._get_cob_cupos(
            "cob_preventista_marca", "marca",
            periodo_desde, periodo_hasta, sucursales, id_fuerza_ventas,
        )

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

    # ── Cupos ──────────────────────────────────────────────────

    def get_cupos(self, periodo: str) -> pd.DataFrame:
        """
        Obtiene cupos para un periodo, uniendo via dim_sucursal para obtener
        el nombre de sucursal correcto.

        Args:
            periodo: Periodo en formato "YYYY-MM" (ej: "2026-04")

        Returns:
            DataFrame con columnas: sucursal, id_ruta, cupo_generico, cupo
        """
        query = """
        SELECT
            ds.descripcion AS sucursal,
            fc.id_ruta,
            fc.generico AS cupo_generico,
            SUM(fc.cupo) AS cupo
        FROM gold.fact_cupos fc
        JOIN gold.dim_sucursal ds ON fc.id_sucursal = ds.id_sucursal
        WHERE fc.periodo = :periodo
        GROUP BY ds.descripcion, fc.id_ruta, fc.generico
        ORDER BY ds.descripcion, fc.generico
        """
        return self.execute_query(query, {"periodo": periodo})

    def get_cupos_cobertura(self, periodo: str) -> pd.DataFrame:
        """
        Obtiene cupos de COBERTURA (objetivo de clientes) para un periodo.

        ⚠️ gold.fact_cupos_cobertura tiene las columnas INVERTIDAS segun
        `tipo_apertura`:
          - tipo_apertura='generico' -> el nombre del generico viene en `marca`
            (y `generico` queda NULL)
          - tipo_apertura='marca'    -> el nombre de la marca viene en `generico`
            (y `marca` queda NULL)
        Por eso la clave se arma con COALESCE(marca, generico): nunca vienen las
        dos con valor. Las filas con ambas en NULL no tienen contra que joinear
        y se descartan.

        A diferencia del cupo de volumen, este cupo es un CONTEO DE CLIENTES: no
        se convierte entre bultos y HTLs (vale igual en las dos hojas).

        Args:
            periodo: Periodo en formato "YYYY-MM" (ej: "2026-07")

        Returns:
            DataFrame con columnas: sucursal, id_ruta, cupo_cob_generico, cupo
            donde `cupo_cob_generico` contiene tanto genericos como marcas.
        """
        query = """
        SELECT
            ds.descripcion                        AS sucursal,
            fcc.id_ruta,
            COALESCE(fcc.marca, fcc.generico)     AS cupo_cob_generico,
            SUM(fcc.cupo)                         AS cupo
        FROM gold.fact_cupos_cobertura fcc
        JOIN gold.dim_sucursal ds ON fcc.id_sucursal = ds.id_sucursal
        WHERE fcc.periodo = :periodo
          AND COALESCE(fcc.marca, fcc.generico) IS NOT NULL
        GROUP BY ds.descripcion, fcc.id_ruta, COALESCE(fcc.marca, fcc.generico)
        ORDER BY ds.descripcion, cupo_cob_generico
        """
        return self.execute_query(query, {"periodo": periodo})

    # ── Ventas Articulo Diario ──────────────────────────────────

    def get_ventas_diarias_articulo(
        self,
        id_articulo: int,
        id_sucursal: int,
        fecha_desde: str,
        fecha_hasta: str,
    ) -> pd.DataFrame:
        """Daily sales (bultos) for a single article x sucursal in a date range."""
        query = """
        SELECT
            fv.fecha_comprobante,
            SUM(fv.cantidades_total) AS bultos
        FROM gold.fact_ventas fv
        WHERE fv.id_articulo = :id_articulo
          AND fv.id_sucursal = :id_sucursal
          AND fv.fecha_comprobante BETWEEN :desde AND :hasta
        GROUP BY fv.fecha_comprobante
        ORDER BY fv.fecha_comprobante
        """
        return self.execute_query(query, {
            "id_articulo": id_articulo,
            "id_sucursal": id_sucursal,
            "desde": fecha_desde,
            "hasta": fecha_hasta,
        })

    def get_articulo_descripcion(self, id_articulo: int) -> str | None:
        """Lookup des_articulo for a single id_articulo."""
        df = self.execute_query(
            "SELECT des_articulo FROM gold.dim_articulo WHERE id_articulo = :id LIMIT 1",
            {"id": id_articulo},
        )
        if df.empty or pd.isna(df["des_articulo"].iloc[0]):
            return None
        return str(df["des_articulo"].iloc[0])

    # ── Stock Diario ────────────────────────────────────────────

    def get_stock_diario(
        self, fecha: str, genericos: list[str] | None = None
    ) -> pd.DataFrame:
        """Stock snapshot for a single date, grouped by article+sucursal.

        Args:
            fecha: Date string in 'YYYY-MM-DD' format.
            genericos: Optional list of genericos to filter.

        Returns:
            DataFrame with columns: generico, marca, des_articulo, sucursal,
            cant_bultos, cant_htls.
        """
        params = {"fecha": fecha}

        if genericos:
            placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
            filtro_gen = f"AND a.generico IN ({placeholders})"
            params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        else:
            filtro_gen = ""

        query = f"""
        SELECT
            a.id_articulo,
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
        {filtro_gen}
        GROUP BY a.id_articulo, a.generico, a.marca, a.des_articulo, d.des_sucursal
        ORDER BY a.des_articulo, a.marca, a.generico, d.des_sucursal
        """
        return self.execute_query(query, params)

    def get_fact_ventas_raw(
        self, fecha_desde: str, fecha_hasta: str, id_sucursal: int
    ) -> pd.DataFrame:
        """Raw fact_ventas dump for avances reports, filtered by date + sucursal."""
        return self.execute_query(
            """
            SELECT id_cliente, id_articulo, id_vendedor, id_sucursal,
                   fecha_comprobante, id_documento, letra, serie, nro_doc,
                   anulado, cantidades_total, bonificacion
            FROM gold.fact_ventas
            WHERE fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
              AND id_sucursal = :id_sucursal
            """,
            {
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
                "id_sucursal": id_sucursal,
            },
        )

    def get_dim_articulo_raw(self) -> pd.DataFrame:
        """Raw dim_articulo for avances — full dimension table, no filter."""
        return self.execute_query(
            """
            SELECT id_articulo, des_articulo, marca, generico, calibre,
                   proveedor, unidad_negocio, factor_hectolitros
            FROM gold.dim_articulo
            """
        )

    def get_dim_cliente_raw(self, id_sucursal: int) -> pd.DataFrame:
        """Raw dim_cliente dump for avances — filtered by sucursal + anulado=false."""
        return self.execute_query(
            """
            SELECT id_cliente, fantasia, razon_social, des_sucursal, id_sucursal,
                   id_ruta_fv1, des_personal_fv1, id_ruta_fv4, des_personal_fv4
            FROM gold.dim_cliente
            WHERE anulado = false
              AND id_sucursal = :id_sucursal
            """,
            {"id_sucursal": id_sucursal},
        )

    def get_cob_preventista_generico_raw(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        id_fuerza_ventas: int,
        id_sucursal: int,
    ) -> pd.DataFrame:
        """Raw cob_preventista_generico — filtered by period + FV + sucursal."""
        return self.execute_query(
            """
            SELECT id, periodo, id_fuerza_ventas, id_vendedor, id_ruta,
                   id_sucursal, ds_sucursal, generico, clientes_compradores,
                   volumen_total
            FROM gold.cob_preventista_generico
            WHERE periodo BETWEEN :fecha_desde AND :fecha_hasta
              AND id_fuerza_ventas = :id_fuerza_ventas
              AND id_sucursal = :id_sucursal
            """,
            {
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
                "id_fuerza_ventas": id_fuerza_ventas,
                "id_sucursal": id_sucursal,
            },
        )

    def get_cob_preventista_marca_raw(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        id_fuerza_ventas: int,
        id_sucursal: int,
    ) -> pd.DataFrame:
        """Raw cob_preventista_marca — filtered by period + FV + sucursal."""
        return self.execute_query(
            """
            SELECT id, periodo, id_fuerza_ventas, id_vendedor, id_ruta,
                   id_sucursal, ds_sucursal, marca, clientes_compradores,
                   volumen_total
            FROM gold.cob_preventista_marca
            WHERE periodo BETWEEN :fecha_desde AND :fecha_hasta
              AND id_fuerza_ventas = :id_fuerza_ventas
              AND id_sucursal = :id_sucursal
            """,
            {
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
                "id_fuerza_ventas": id_fuerza_ventas,
                "id_sucursal": id_sucursal,
            },
        )

    # ──────────────────────────────────────────────────────────────
    # Avance Badie queries — same domain as avance-branca but with
    # descriptive joins (sucursal/vendedor/articulo/ruta) so the Excel
    # template can display names instead of IDs.
    # Column aliases match the Badie .xlsm headers exactly so the
    # service writes them without a rename map.
    # ──────────────────────────────────────────────────────────────

    def get_fact_ventas_pivot_badie(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        id_sucursal: int,
        id_fuerza_ventas: int,
    ) -> pd.DataFrame:
        """Ventas pivot for Badie pivot_python sheet — aggregated with descriptions.

        Groups fact_ventas by (sucursal, fecha, vendedor, ruta, marca, genérico,
        artículo) and sums cantidades_total. Joins dim tables to surface display
        names. Route comes from dim_cliente.id_ruta_fv{1,4}/des_personal_fv{1,4}
        depending on id_fuerza_ventas.
        """
        ruta_col = "id_ruta_fv1" if id_fuerza_ventas == 1 else "id_ruta_fv4"
        ruta_desc_col = "des_personal_fv1" if id_fuerza_ventas == 1 else "des_personal_fv4"
        return self.execute_query(
            f"""
            SELECT
                ds.id_sucursal || ' - ' || ds.descripcion        AS "Sucursal",
                fv.fecha_comprobante                              AS "Descripcion Período",
                dv.des_vendedor                                   AS "Descripcion Vendedor",
                dc.{ruta_col}                                     AS "Ruta",
                dc.{ruta_desc_col}                                AS "Descripcion_Ruta",
                da.marca                                          AS "Descripcion_Marca",
                da.generico                                       AS "GENERICO",
                fv.id_articulo                                    AS "Código_Articulo",
                da.des_articulo                                   AS "Descripcion_Articulo",
                SUM(fv.cantidades_total)                          AS "Cantidades Totales"
            FROM gold.fact_ventas fv
            LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
            LEFT JOIN gold.dim_vendedor dv
              ON fv.id_vendedor = dv.id_vendedor
             AND fv.id_sucursal = dv.id_sucursal
             AND dv.id_fuerza_ventas = :id_fuerza_ventas
            LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
            LEFT JOIN gold.dim_cliente  dc
              ON fv.id_cliente = dc.id_cliente
             AND fv.id_sucursal = dc.id_sucursal
            WHERE fv.fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
              AND fv.id_sucursal = :id_sucursal
              AND fv.anulado = false
            GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
            """,
            {
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
                "id_sucursal": id_sucursal,
                "id_fuerza_ventas": id_fuerza_ventas,
            },
        )

    def get_cob_preventista_generico_pivot_badie(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        id_fuerza_ventas: int,
        id_sucursal: int,
    ) -> pd.DataFrame:
        """Cobertura por preventista/genérico for Badie cober_gen sheet.

        Adds sucursal+vendedor descriptions. Column aliases match the Excel
        header row exactly (no rename layer needed).
        """
        return self.execute_query(
            """
            SELECT
                ds.id_sucursal || ' - ' || ds.descripcion AS "Sucursal",
                dv.des_vendedor                            AS "Descripcion Vendedor",
                cpg.id_ruta                                AS "Ruta",
                cpg.generico                               AS "GENERICO",
                cpg.clientes_compradores                   AS "Numero_Clientes"
            FROM gold.cob_preventista_generico cpg
            LEFT JOIN gold.dim_sucursal ds ON cpg.id_sucursal = ds.id_sucursal
            LEFT JOIN gold.dim_vendedor dv
              ON cpg.id_vendedor = dv.id_vendedor
             AND cpg.id_sucursal = dv.id_sucursal
            WHERE cpg.periodo BETWEEN :fecha_desde AND :fecha_hasta
              AND cpg.id_fuerza_ventas = :id_fuerza_ventas
              AND cpg.id_sucursal = :id_sucursal
            """,
            {
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
                "id_fuerza_ventas": id_fuerza_ventas,
                "id_sucursal": id_sucursal,
            },
        )

    def get_cob_preventista_marca_pivot_badie(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        id_fuerza_ventas: int,
        id_sucursal: int,
    ) -> pd.DataFrame:
        """Cobertura por preventista/marca for Badie cober_marca sheet.

        Mirror of get_cob_preventista_generico_pivot_badie but with marca.
        """
        return self.execute_query(
            """
            SELECT
                ds.id_sucursal || ' - ' || ds.descripcion AS "Sucursal",
                dv.des_vendedor                            AS "Descripcion Vendedor",
                cpm.id_ruta                                AS "Ruta",
                cpm.marca                                  AS "Descripcion_Marca",
                cpm.clientes_compradores                   AS "Numero_Clientes"
            FROM gold.cob_preventista_marca cpm
            LEFT JOIN gold.dim_sucursal ds ON cpm.id_sucursal = ds.id_sucursal
            LEFT JOIN gold.dim_vendedor dv
              ON cpm.id_vendedor = dv.id_vendedor
             AND cpm.id_sucursal = dv.id_sucursal
            WHERE cpm.periodo BETWEEN :fecha_desde AND :fecha_hasta
              AND cpm.id_fuerza_ventas = :id_fuerza_ventas
              AND cpm.id_sucursal = :id_sucursal
            """,
            {
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
                "id_fuerza_ventas": id_fuerza_ventas,
                "id_sucursal": id_sucursal,
            },
        )

    # ZONAS_VIRTUALES applied inline in SQL for cupos queries below.
    # Rutas hardcoded here to keep the queries self-contained; mirrors
    # config/settings.py:ZONAS_VIRTUALES. Excel sheets use the singular
    # form "SUB DISTRIBUIDOR" — match that in the CASE expression.
    _VALLE_SALTA_RUTAS = "(81,82,83,84,85,86,87,88,89,90,91,92,118,119,120,122)"
    _SUB_DISTRIBUIDOR_RUTAS = "(93)"

    def get_cupos_volumen_badie(
        self,
        periodo: str,
        id_sucursal: int,
    ) -> pd.DataFrame:
        """Cupos volumen for Badie CuposVolumen sheet.

        Source: gold.fact_cupos filtered to proveedor='CCU' (Badie excludes
        BRANCA from this sheet — Branca cupos live in the Avance Branca report).
        Columns aliased to match Excel headers exactly (including trailing-space
        header 'Cupo ').
        """
        return self.execute_query(
            """
            SELECT
                id_ruta     AS "Código",
                descripcion AS "Descripción",
                preventista AS "PREVENTISTA",
                generico    AS "GENERICO",
                desagregado AS "DESAGREGADO",
                cupo        AS "Cupo "
            FROM gold.fact_cupos
            WHERE periodo = :periodo
              AND id_sucursal = :id_sucursal
              AND proveedor = 'CCU'
            """,
            {"periodo": periodo, "id_sucursal": id_sucursal},
        )

    def get_cupos_cobertura_generico_badie(
        self,
        periodo: str,
        id_sucursal: int | None = None,
    ) -> pd.DataFrame:
        """Cupos de cobertura por genérico for Badie CuposCoberGen sheet.

        Source: gold.fact_cupos_cobertura filtered by tipo_apertura='generico'.

        By default (id_sucursal=None) includes all sucursales (table only
        contains id_sucursal IN (1, 16) for the relevant period). CASA CENTRAL
        rows are re-zoned to 'VALLE SALTA' / 'SUB DISTRIBUIDOR' based on
        id_ruta per ZONAS_VIRTUALES. This is the badie path — SQL/params are
        unchanged from before this parameter existed.

        When id_sucursal is set (e.g. 16 for GUEMES), the WHERE clause is
        additively scoped to that sucursal. The re-zoning CASE only ever
        matches sucursal = '1 - CASA CENTRAL', so scoping to a non-CASA
        CENTRAL sucursal makes the CASE inert (falls through to ELSE) —
        no special-casing needed here.

        DATA QUIRK: when tipo_apertura='generico', the actual generico value
        lives in the `marca` column (the `generico` column is NULL). The
        SELECT swaps to compensate.
        """
        sucursal_filter = ""
        params: dict = {"periodo": periodo}
        if id_sucursal is not None:
            sucursal_filter = "\n          AND id_sucursal = :id_sucursal"
            params["id_sucursal"] = id_sucursal

        sql = f"""
        SELECT
            id_ruta     AS "Ruta",
            preventista AS "Preventista",
            marca       AS "Generico",
            CASE
                WHEN sucursal = '1 - CASA CENTRAL'
                     AND id_ruta IN {self._VALLE_SALTA_RUTAS} THEN 'VALLE SALTA'
                WHEN sucursal = '1 - CASA CENTRAL'
                     AND id_ruta IN {self._SUB_DISTRIBUIDOR_RUTAS} THEN 'SUB DISTRIBUIDOR'
                ELSE sucursal
            END AS "ZONA",
            cupo        AS "CUPO "
        FROM gold.fact_cupos_cobertura
        WHERE periodo = :periodo
          AND tipo_apertura = 'generico'{sucursal_filter}
        """
        return self.execute_query(sql, params)

    def get_cupos_cobertura_marca_badie(
        self,
        periodo: str,
        id_sucursal: int | None = None,
    ) -> pd.DataFrame:
        """Cupos de cobertura por marca for Badie CuposCober sheet.

        Source: gold.fact_cupos_cobertura filtered by tipo_apertura='marca'.

        By default (id_sucursal=None) includes all sucursales (table only
        contains id_sucursal IN (1, 16) for the relevant period). CASA CENTRAL
        rows are re-zoned to 'VALLE SALTA' / 'SUB DISTRIBUIDOR' based on
        id_ruta per ZONAS_VIRTUALES. This is the badie path — SQL/params are
        unchanged from before this parameter existed.

        When id_sucursal is set (e.g. 16 for GUEMES), the WHERE clause is
        additively scoped to that sucursal. The re-zoning CASE only ever
        matches sucursal = '1 - CASA CENTRAL', so scoping to a non-CASA
        CENTRAL sucursal makes the CASE inert (falls through to ELSE) —
        no special-casing needed here.

        DATA QUIRK: when tipo_apertura='marca', the actual marca value lives
        in the `generico` column (the `marca` column is NULL). The SELECT
        swaps to compensate. 'Descripción Vendedor' header in Excel has
        accented capital ó — SQL alias must match byte-for-byte.
        """
        sucursal_filter = ""
        params: dict = {"periodo": periodo}
        if id_sucursal is not None:
            sucursal_filter = "\n          AND id_sucursal = :id_sucursal"
            params["id_sucursal"] = id_sucursal

        sql = f"""
        SELECT
            id_ruta     AS "Ruta",
            preventista AS "Descripción Vendedor",
            generico    AS "MARCA",
            CASE
                WHEN sucursal = '1 - CASA CENTRAL'
                     AND id_ruta IN {self._VALLE_SALTA_RUTAS} THEN 'VALLE SALTA'
                WHEN sucursal = '1 - CASA CENTRAL'
                     AND id_ruta IN {self._SUB_DISTRIBUIDOR_RUTAS} THEN 'SUB DISTRIBUIDOR'
                ELSE sucursal
            END AS "ZONA",
            cupo        AS "CUPO "
        FROM gold.fact_cupos_cobertura
        WHERE periodo = :periodo
          AND tipo_apertura = 'marca'{sucursal_filter}
        """
        return self.execute_query(sql, params)

    # ──────────────────────────────────────────────────────────────
    # Graficos-Cobertura queries
    # Aggregated per (anio, mes, axis) from cob_* tables. Distinct from the
    # preventista/sucursal queries above because the graficos service needs
    # monthly rollups (not per-periodo rows) and its own 5-zone scheme.
    # ──────────────────────────────────────────────────────────────

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Check if a table exists in the given schema via information_schema."""
        df = self.execute_query(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = :schema AND table_name = :table_name
            ) AS existe
            """,
            {"schema": schema, "table_name": table_name},
        )
        if df.empty:
            return False
        return bool(df["existe"].iloc[0])

    def get_cobertura_graficos_marca_ruta(
        self,
        id_fuerza_ventas: int,
        anios: list[int],
        id_sucursal: int,
    ) -> pd.DataFrame:
        """Preventista-grained marca data for a single sucursal (per id_ruta).

        Returns columns: [anio, mes, id_ruta, marca, clientes].
        """
        placeholders = ", ".join(f":anio_{i}" for i in range(len(anios)))
        params = {"fv": id_fuerza_ventas, "id_sucursal": id_sucursal}
        params.update({f"anio_{i}": a for i, a in enumerate(anios)})
        query = f"""
        SELECT
            EXTRACT(YEAR FROM periodo)::int  AS anio,
            EXTRACT(MONTH FROM periodo)::int AS mes,
            id_ruta, marca,
            SUM(clientes_compradores) AS clientes
        FROM gold.cob_preventista_marca
        WHERE id_fuerza_ventas = :fv
          AND id_sucursal = :id_sucursal
          AND EXTRACT(YEAR FROM periodo) IN ({placeholders})
        GROUP BY 1, 2, id_ruta, marca
        """
        return self.execute_query(query, params)

    def get_cobertura_graficos_generico_ruta(
        self,
        id_fuerza_ventas: int,
        anios: list[int],
        id_sucursal: int,
    ) -> pd.DataFrame:
        """Preventista-grained generico data for a single sucursal (per id_ruta).

        Returns columns: [anio, mes, id_ruta, generico, clientes].
        """
        placeholders = ", ".join(f":anio_{i}" for i in range(len(anios)))
        params = {"fv": id_fuerza_ventas, "id_sucursal": id_sucursal}
        params.update({f"anio_{i}": a for i, a in enumerate(anios)})
        query = f"""
        SELECT
            EXTRACT(YEAR FROM periodo)::int  AS anio,
            EXTRACT(MONTH FROM periodo)::int AS mes,
            id_ruta, generico,
            SUM(clientes_compradores) AS clientes
        FROM gold.cob_preventista_generico
        WHERE id_fuerza_ventas = :fv
          AND id_sucursal = :id_sucursal
          AND EXTRACT(YEAR FROM periodo) IN ({placeholders})
        GROUP BY 1, 2, id_ruta, generico
        """
        return self.execute_query(query, params)

    def get_cobertura_graficos_marca_sucursal(
        self,
        id_fuerza_ventas: int,
        anios: list[int],
        sucursales: list[int] | None = None,
    ) -> pd.DataFrame:
        """Aggregated marca data from cob_sucursal_marca.

        If sucursales is None, aggregates across ALL sucursales (NOA NORTE).

        Returns columns: [anio, mes, marca, clientes].
        """
        anio_ph = ", ".join(f":anio_{i}" for i in range(len(anios)))
        params = {"fv": id_fuerza_ventas}
        params.update({f"anio_{i}": a for i, a in enumerate(anios)})

        filtro_suc = ""
        if sucursales is not None:
            suc_ph = ", ".join(f":suc_{i}" for i in range(len(sucursales)))
            filtro_suc = f"AND id_sucursal IN ({suc_ph})"
            params.update({f"suc_{i}": s for i, s in enumerate(sucursales)})

        query = f"""
        SELECT
            EXTRACT(YEAR FROM periodo)::int  AS anio,
            EXTRACT(MONTH FROM periodo)::int AS mes,
            marca,
            SUM(clientes_compradores) AS clientes
        FROM gold.cob_sucursal_marca
        WHERE id_fuerza_ventas = :fv
          AND EXTRACT(YEAR FROM periodo) IN ({anio_ph})
          {filtro_suc}
        GROUP BY 1, 2, marca
        """
        return self.execute_query(query, params)

    def get_cobertura_graficos_generico_sucursal(
        self,
        id_fuerza_ventas: int,
        anios: list[int],
        sucursales: list[int] | None = None,
    ) -> pd.DataFrame:
        """Aggregated generico data from cob_sucursal_generico.

        Returns columns: [anio, mes, generico, clientes].
        """
        anio_ph = ", ".join(f":anio_{i}" for i in range(len(anios)))
        params = {"fv": id_fuerza_ventas}
        params.update({f"anio_{i}": a for i, a in enumerate(anios)})

        filtro_suc = ""
        if sucursales is not None:
            suc_ph = ", ".join(f":suc_{i}" for i in range(len(sucursales)))
            filtro_suc = f"AND id_sucursal IN ({suc_ph})"
            params.update({f"suc_{i}": s for i, s in enumerate(sucursales)})

        query = f"""
        SELECT
            EXTRACT(YEAR FROM periodo)::int  AS anio,
            EXTRACT(MONTH FROM periodo)::int AS mes,
            generico,
            SUM(clientes_compradores) AS clientes
        FROM gold.cob_sucursal_generico
        WHERE id_fuerza_ventas = :fv
          AND EXTRACT(YEAR FROM periodo) IN ({anio_ph})
          {filtro_suc}
        GROUP BY 1, 2, generico
        """
        return self.execute_query(query, params)

    def get_cobertura_graficos_aguas_sucursal(
        self,
        id_fuerza_ventas: int,
        anios: list[int],
    ) -> pd.DataFrame:
        """AGUAS DANONE subdivision data from gold.cob_sucursal_aguas.

        Pre-checks table existence via information_schema. If the table is
        absent, logs a WARNING and returns an empty DataFrame with the
        expected schema (no raise — graceful degradation).

        Returns columns: [anio, mes, id_sucursal, subdivision_aguas, clientes].
        """
        import logging

        empty_cols = ["anio", "mes", "id_sucursal", "subdivision_aguas", "clientes"]
        if not self.table_exists("gold", "cob_sucursal_aguas"):
            logging.warning(
                "gold.cob_sucursal_aguas not available — aguas subdivisions will be skipped"
            )
            return pd.DataFrame(columns=empty_cols)

        placeholders = ", ".join(f":anio_{i}" for i in range(len(anios)))
        params = {"fv": id_fuerza_ventas}
        params.update({f"anio_{i}": a for i, a in enumerate(anios)})
        query = f"""
        SELECT
            EXTRACT(YEAR FROM periodo)::int  AS anio,
            EXTRACT(MONTH FROM periodo)::int AS mes,
            id_sucursal,
            subdivision_aguas,
            SUM(clientes_compradores) AS clientes
        FROM gold.cob_sucursal_aguas
        WHERE id_fuerza_ventas = :fv
          AND EXTRACT(YEAR FROM periodo) IN ({placeholders})
        GROUP BY 1, 2, id_sucursal, subdivision_aguas
        """
        return self.execute_query(query, params)

    def get_ventas_historico_cliente(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        clientes: list[dict],
        articulos: list[int] | None = None,
        marcas: list[str] | None = None,
        agrupar_por_generico: bool = False,
    ) -> pd.DataFrame:
        """Obtiene ventas agrupadas por cliente, row_key y mes para reporte historico.

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD'
            clientes: Lista de dicts con keys 'id_cliente' e 'id_sucursal'.
            articulos: Lista de id_articulo a filtrar. Si es None, no filtra por articulo.
            marcas: Lista de marcas a filtrar. Si es None, no filtra por marca.
                    Cuando se provee, row_key es da.marca; de lo contrario es el articulo.
            agrupar_por_generico: Cuando es True, row_key es da.marca y NO se filtra por
                    marca/articulo (se traen todas las marcas). Usado por el modo de
                    reporte agrupado por generico con subtotales.

        Returns:
            DataFrame con columnas: id_cliente, id_sucursal, nombre_cliente,
            generico, row_key, mes, bultos.
            Ordenado por id_cliente, row_key, mes.
        """
        # Build composite-key OR clauses for the client list
        cliente_clauses = " OR ".join(
            f"(fv.id_cliente = :c{i}_id AND fv.id_sucursal = :c{i}_suc)"
            for i in range(len(clientes))
        )
        params: dict = {"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta}
        for i, c in enumerate(clientes):
            params[f"c{i}_id"] = c["id_cliente"]
            params[f"c{i}_suc"] = c["id_sucursal"]

        # row_key expression depends on mode. Marca-grain when marcas are filtered or
        # when grouping by generico; otherwise articulo-grain.
        if marcas is not None or agrupar_por_generico:
            row_key_expr = "da.marca"
        else:
            row_key_expr = "CAST(fv.id_articulo AS TEXT) || ' - ' || da.des_articulo"

        # Optional filters (skipped entirely in agrupar_por_generico mode)
        extra_filters = ""
        if not agrupar_por_generico:
            if marcas is not None:
                marca_ph = ", ".join(f":marca_{i}" for i in range(len(marcas)))
                extra_filters += f"\n              AND da.marca IN ({marca_ph})"
                params.update({f"marca_{i}": m for i, m in enumerate(marcas)})
            if articulos is not None:
                art_ph = ", ".join(f":art_{i}" for i in range(len(articulos)))
                extra_filters += f"\n              AND fv.id_articulo IN ({art_ph})"
                params.update({f"art_{i}": a for i, a in enumerate(articulos)})

        query = f"""
        SELECT
            fv.id_cliente,
            fv.id_sucursal,
            COALESCE(dc.fantasia, dc.razon_social, CAST(fv.id_cliente AS TEXT)) AS nombre_cliente,
            da.generico AS generico,
            {row_key_expr} AS row_key,
            TO_CHAR(fv.fecha_comprobante, 'YYYY-MM') AS mes,
            SUM(fv.cantidades_total) AS bultos
        FROM gold.fact_ventas fv
        LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
        LEFT JOIN gold.dim_cliente dc ON fv.id_cliente = dc.id_cliente
            AND fv.id_sucursal = dc.id_sucursal
        WHERE fv.fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
          AND ({cliente_clauses}){extra_filters}
        GROUP BY fv.id_cliente, fv.id_sucursal, nombre_cliente, generico, row_key, mes
        ORDER BY fv.id_cliente, row_key, mes
        """
        return self.execute_query(query, params)

    def get_marca_universe(self, genericos: list[str]) -> pd.DataFrame:
        """Todas las combinaciones (generico, marca) de los genericos dados.

        Fuente: gold.dim_articulo. Usado por el reporte historico de cliente en
        modo 'marcas completas' para rellenar con 0 las marcas sin venta y asi
        exponer los huecos de compra.

        Returns:
            DataFrame con columnas: generico, marca.
        """
        if not genericos:
            return pd.DataFrame(columns=["generico", "marca"])
        placeholders = ", ".join(f":g{i}" for i in range(len(genericos)))
        params = {f"g{i}": g for i, g in enumerate(genericos)}
        query = f"""
        SELECT DISTINCT da.generico, da.marca
        FROM gold.dim_articulo da
        WHERE da.generico IN ({placeholders})
          AND da.marca IS NOT NULL AND da.marca <> ''
        ORDER BY da.generico, da.marca
        """
        return self.execute_query(query, params)

    def get_ventas_mensuales_ccu(
        self, fecha_desde: str, fecha_hasta: str
    ) -> pd.DataFrame:
        """
        Obtiene ventas mensuales por sucursal y generico (solo CCU genericos).

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD'

        Returns:
            DataFrame con columnas: sucursal, generico, anio, mes, bultos
        """
        query = """
        SELECT ds.descripcion AS sucursal, da.generico,
          EXTRACT(YEAR FROM fv.fecha_comprobante)::int AS anio,
          EXTRACT(QUARTER FROM fv.fecha_comprobante)::int AS trimestre,
          SUM(fv.cantidades_total) AS bultos
        FROM gold.fact_ventas fv
        LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
        LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
        WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
          AND da.generico IN ('CERVEZAS','AGUAS DANONE','VINOS CCU','SIDRAS Y LICORES')
        GROUP BY ds.descripcion, da.generico, EXTRACT(YEAR FROM fv.fecha_comprobante), EXTRACT(QUARTER FROM fv.fecha_comprobante)
        ORDER BY ds.descripcion, da.generico, anio, trimestre
        """
        params = {"desde": fecha_desde, "hasta": fecha_hasta}
        return self.execute_query(query, params)

    def get_cobertura_clientes_ccu(
        self, fecha_desde: str, fecha_hasta: str
    ) -> pd.DataFrame:
        """
        Cobertura de clientes para los 4 genericos CCU
        (CERVEZAS, AGUAS DANONE, VINOS CCU, SIDRAS Y LICORES) agregada por trimestre.
        Un row por cliente-sucursal-trimestre.

        Returns:
            DataFrame con columnas:
              - sucursal, anio, trimestre, id_cliente
              - bultos                            -> SUM total CCU (incluye regalos)
              - bultos_sin_regalos                -> SUM CCU solo items bonificacion < 100
              - bultos_aguas_danone               -> SUM solo AGUAS DANONE (incluye regalos)
              - bultos_aguas_danone_sin_regalos   -> SUM AGUAS DANONE excluyendo regalos
              - meses_con_compra                  -> cantidad de meses distintos del
                                                     trimestre con compra (1, 2 o 3)
        """
        query = """
        SELECT ds.descripcion AS sucursal,
          EXTRACT(YEAR FROM fv.fecha_comprobante)::int AS anio,
          EXTRACT(QUARTER FROM fv.fecha_comprobante)::int AS trimestre,
          fv.id_cliente,
          SUM(fv.cantidades_total) AS bultos,
          SUM(CASE WHEN COALESCE(fv.bonificacion, 0) < 100
                   THEN fv.cantidades_total ELSE 0 END) AS bultos_sin_regalos,
          SUM(CASE WHEN da.generico = 'AGUAS DANONE'
                   THEN fv.cantidades_total ELSE 0 END) AS bultos_aguas_danone,
          SUM(CASE WHEN da.generico = 'AGUAS DANONE'
                    AND COALESCE(fv.bonificacion, 0) < 100
                   THEN fv.cantidades_total ELSE 0 END) AS bultos_aguas_danone_sin_regalos,
          COUNT(DISTINCT EXTRACT(MONTH FROM fv.fecha_comprobante))::int AS meses_con_compra
        FROM gold.fact_ventas fv
        LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
        LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
        WHERE fv.fecha_comprobante BETWEEN :desde AND :hasta
          AND da.generico IN ('CERVEZAS','AGUAS DANONE','VINOS CCU','SIDRAS Y LICORES')
        GROUP BY ds.descripcion, EXTRACT(YEAR FROM fv.fecha_comprobante), EXTRACT(QUARTER FROM fv.fecha_comprobante), fv.id_cliente
        ORDER BY ds.descripcion, anio, trimestre, fv.id_cliente
        """
        params = {"desde": fecha_desde, "hasta": fecha_hasta}
        result = self.execute_query(query, params)
        if result.empty:
            return pd.DataFrame(columns=[
                "sucursal", "anio", "trimestre", "id_cliente",
                "bultos", "bultos_sin_regalos",
                "bultos_aguas_danone", "bultos_aguas_danone_sin_regalos",
                "meses_con_compra",
            ])
        return result

    # ── Rebotes ──────────────────────────────────────────────────

    def get_rebotes_vendedor(
        self, fecha_desde: str, fecha_hasta: str, genericos: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Fetch bultos_vendidos per vendor for CCU generics, id_sucursal=1.

        Returns DataFrame with columns:
            vendedor, bultos_vendidos, bultos_rechazados, id_fuerza_ventas

        bultos_rechazados is always 0 — placeholder until rejection data is added.
        Only includes id_fuerza_ventas = 1 (FV1).

        Args:
            fecha_desde: Start date 'YYYY-MM-DD'
            fecha_hasta: End date 'YYYY-MM-DD'
            genericos: List of generics to filter (defaults to CCU generics).
        """
        if genericos is None:
            genericos = ["CERVEZAS", "AGUAS DANONE", "VINOS CCU", "SIDRAS Y LICORES"]

        placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
        query = f"""
        SELECT
            dv.des_vendedor                              AS vendedor,
            SUM(CASE WHEN fv.cantidades_total > 0 THEN fv.cantidades_total ELSE 0 END) AS bultos_vendidos,
            ABS(SUM(CASE WHEN fv.cantidades_total < 0 THEN fv.cantidades_total ELSE 0 END)) AS bultos_rechazados,
            dv.id_fuerza_ventas
        FROM gold.fact_ventas fv
        JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
        JOIN gold.dim_vendedor   dv ON fv.id_vendedor  = dv.id_vendedor
                                    AND fv.id_sucursal = dv.id_sucursal
        WHERE fv.id_sucursal = 1
          AND fv.fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
          AND da.generico IN ({placeholders})
          AND dv.id_fuerza_ventas = 1
        GROUP BY dv.des_vendedor, dv.id_fuerza_ventas
        HAVING SUM(CASE WHEN fv.cantidades_total > 0 THEN fv.cantidades_total ELSE 0 END) > 0
        ORDER BY dv.id_fuerza_ventas, dv.des_vendedor
        """
        params = {"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta}
        params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        return self.execute_query(query, params)

    def get_ventas_por_cliente(
        self, fecha_desde: date, fecha_hasta: date, genericos: list[str] | None = None
    ) -> pd.DataFrame:
        """Fetch bultos_vendidos, bultos_rechazados, % rechazo per cliente and generico.

        Includes preventista (`des_personal_fv1`) from dim_cliente — fuerza ventas 1 (CCU).

        Returns DataFrame with columns:
        [id_cliente, fantasia, razon_social, des_personal_fv1, generico,
         bultos_vendidos, bultos_rechazados]
        """
        if genericos is None:
            genericos = ["CERVEZAS", "AGUAS DANONE", "VINOS CCU", "SIDRAS Y LICORES"]

        placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
        query = f"""
        SELECT
            dc.id_cliente,
            dc.fantasia,
            dc.razon_social,
            dc.des_personal_fv1,
            da.generico,
            SUM(CASE WHEN fv.cantidades_total > 0 THEN fv.cantidades_total ELSE 0 END) AS bultos_vendidos,
            ABS(SUM(CASE WHEN fv.cantidades_total < 0 THEN fv.cantidades_total ELSE 0 END)) AS bultos_rechazados
        FROM gold.fact_ventas fv
        JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
        JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente
        WHERE fv.id_sucursal = 1
          AND fv.fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
          AND da.generico IN ({placeholders})
        GROUP BY dc.id_cliente, dc.fantasia, dc.razon_social, dc.des_personal_fv1, da.generico
        ORDER BY dc.fantasia, da.generico
        """
        params = {"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta}
        params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        return self.execute_query(query, params)

    def get_rechazos_por_cliente(
        self, fecha_desde: date, fecha_hasta: date, genericos: list[str] | None = None
    ) -> pd.DataFrame:
        """Fetch bultos_rechazados per cliente and generico (solo rechazos > 0).

        Includes preventista (`des_personal_fv1`) from dim_cliente — fuerza ventas 1 (CCU).

        Returns DataFrame with columns:
        [id_cliente, fantasia, razon_social, des_personal_fv1, generico, bultos_rechazados]
        """
        if genericos is None:
            genericos = ["CERVEZAS", "AGUAS DANONE", "VINOS CCU", "SIDRAS Y LICORES"]

        placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
        query = f"""
        SELECT
            dc.id_cliente,
            dc.fantasia,
            dc.razon_social,
            dc.des_personal_fv1,
            da.generico,
            ABS(SUM(fv.cantidades_total)) AS bultos_rechazados
        FROM gold.fact_ventas fv
        JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
        JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente
        WHERE fv.id_sucursal = 1
          AND fv.fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
          AND da.generico IN ({placeholders})
          AND fv.cantidades_total < 0
        GROUP BY dc.id_cliente, dc.fantasia, dc.razon_social, dc.des_personal_fv1, da.generico
        HAVING ABS(SUM(fv.cantidades_total)) > 0
        ORDER BY dc.fantasia, da.generico
        """
        params = {"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta}
        params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        return self.execute_query(query, params)

    def get_vendedores_on_premise_universo(
        self,
        id_sucursal: int,
        id_lista_precio: int,
    ) -> pd.DataFrame:
        """Universe of preventistas with at least 1 ON PREMISE client in the sucursal.

        Returns DataFrame with column [vendedor] — sorted, no nulls. Excludes
        DIRECTA (route-less customers) since they don't represent a preventista.
        """
        query = """
        SELECT DISTINCT des_personal_fv1 AS vendedor
        FROM gold.dim_cliente
        WHERE id_sucursal      = :id_sucursal
          AND id_lista_precio  = :id_lista_precio
          AND des_personal_fv1 IS NOT NULL
          AND des_personal_fv1 <> 'DIRECTA'
        ORDER BY vendedor
        """
        return self.execute_query(query, {
            "id_sucursal": id_sucursal,
            "id_lista_precio": id_lista_precio,
        })

    def get_incentivo_cobertura_on_premise(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        id_sucursal: int,
        id_lista_precio: int,
        target_specs: list[dict],
    ) -> pd.DataFrame:
        """Count distinct clients per (vendedor, marca_label) covered in incentive period.

        Each target_spec is a dict with keys: 'label' (str) and 'sql_where' (str — a
        predicate on dim_articulo aliased as `da.*`). For each target, counts unique
        id_cliente that bought at least 1 unit (cantidades_total > 0, anulado=false)
        of a matching article from ON PREMISE customers (id_lista_precio filter)
        at the given sucursal during the date range.

        Returns DataFrame with columns: [vendedor, marca_label, clientes_compradores]
        Only includes (vendedor, marca) pairs that have at least 1 client.
        """
        if not target_specs:
            import pandas as _pd
            return _pd.DataFrame(columns=["vendedor", "marca_label", "clientes_compradores"])

        target_unions = []
        params: dict = {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "id_sucursal": id_sucursal,
            "id_lista_precio": id_lista_precio,
        }
        for i, t in enumerate(target_specs):
            label_param = f"label_{i}"
            params[label_param] = t["label"]
            # Lógica oficial (medallion-etl gold.cob_sucursal_lista_marca):
            # primero agregamos por (vendedor, cliente) sumando cantidades del
            # período/marca, filtramos los clientes cuyo total neto > 0
            # (HAVING — NO se filtra a nivel línea), y recién después contamos
            # DISTINCT id_cliente por vendedor.
            target_unions.append(f"""
                SELECT
                    vendedor,
                    CAST(:{label_param} AS text) AS marca_label,
                    COUNT(DISTINCT id_cliente)   AS clientes_compradores
                FROM (
                    SELECT
                        dc.des_personal_fv1 AS vendedor,
                        fv.id_cliente,
                        SUM(fv.cantidades_total) AS total_qty
                    FROM gold.fact_ventas fv
                    JOIN gold.dim_articulo da ON fv.id_articulo  = da.id_articulo
                    JOIN gold.dim_cliente  dc ON fv.id_cliente   = dc.id_cliente
                                             AND fv.id_sucursal = dc.id_sucursal
                    WHERE fv.id_sucursal      = :id_sucursal
                      AND fv.fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
                      AND dc.id_lista_precio  = :id_lista_precio
                      AND ({t['sql_where']})
                    GROUP BY dc.des_personal_fv1, fv.id_cliente
                    HAVING SUM(fv.cantidades_total) > 0
                ) ventas_cliente_neto
                GROUP BY vendedor
            """)

        query = " UNION ALL ".join(target_unions) + " ORDER BY vendedor, marca_label"
        return self.execute_query(query, params)

    def get_rebotes_vendedor_por_generico(
        self, fecha_desde: date, fecha_hasta: date, genericos: list[str] | None = None
    ) -> pd.DataFrame:
        """Fetch bultos_vendidos, bultos_rechazados per vendor and generico.

        Returns DataFrame with columns:
        [vendedor, id_fuerza_ventas, generico, bultos_vendidos, bultos_rechazados]
        Filtered by id_sucursal=1 and CCU generics.
        """
        if genericos is None:
            genericos = ["CERVEZAS", "AGUAS DANONE", "VINOS CCU", "SIDRAS Y LICORES"]

        placeholders = ", ".join([f":gen_{i}" for i in range(len(genericos))])
        query = f"""
        SELECT
            dv.des_vendedor                              AS vendedor,
            dv.id_fuerza_ventas,
            da.generico,
            SUM(CASE WHEN fv.cantidades_total > 0 THEN fv.cantidades_total ELSE 0 END) AS bultos_vendidos,
            ABS(SUM(CASE WHEN fv.cantidades_total < 0 THEN fv.cantidades_total ELSE 0 END)) AS bultos_rechazados
        FROM gold.fact_ventas fv
        JOIN gold.dim_articulo  da ON fv.id_articulo  = da.id_articulo
        JOIN gold.dim_vendedor   dv ON fv.id_vendedor  = dv.id_vendedor
                                    AND fv.id_sucursal = dv.id_sucursal
        WHERE fv.id_sucursal = 1
          AND fv.fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
          AND da.generico IN ({placeholders})
          AND dv.id_fuerza_ventas = 1
        GROUP BY dv.des_vendedor, dv.id_fuerza_ventas, da.generico
        ORDER BY dv.des_vendedor, da.generico
        """
        params = {"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta}
        params.update({f"gen_{i}": g for i, g in enumerate(genericos)})
        return self.execute_query(query, params)


# ── Subdistribuidores ─────────────────────────────────────────

    def get_ventas_subdistribuidores(
        self, fecha_desde: str, fecha_hasta: str
    ) -> pd.DataFrame:
        """
        Obtiene ventas de subdistribuidores (ruta 93) con jerarquia de cliente.

        Filtra fact_ventas a id_ruta = 93 y une dim_cliente para obtener
        fantasia y razon_social. El join con dim_cliente usa la misma clave
        (id_cliente, id_sucursal) que el resto del sistema.

        Args:
            fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
            fecha_hasta: Fecha fin formato 'YYYY-MM-DD'

        Returns:
            DataFrame con columnas:
            - id_cliente, fantasia, razon_social (from dim_cliente)
            - generico, marca, des_articulo (from dim_articulo)
            - cantidad (SUM cantidades_total)
            Filtrado a id_ruta = 93 unicamente.
        """
        query = """
        SELECT
            dc.id_cliente,
            COALESCE(dc.fantasia, '')      AS fantasia,
            COALESCE(dc.razon_social, '')  AS razon_social,
            da.generico,
            da.marca,
            da.des_articulo,
            SUM(fv.cantidades_total)        AS cantidad
        FROM gold.fact_ventas fv
        JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
        JOIN gold.dim_cliente  dc ON fv.id_cliente   = dc.id_cliente
                                 AND fv.id_sucursal   = dc.id_sucursal
        WHERE fv.fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
          AND dc.id_ruta_fv1 = 93
        GROUP BY dc.id_cliente, dc.fantasia, dc.razon_social,
                 da.generico, da.marca, da.des_articulo
        ORDER BY dc.fantasia, dc.razon_social, da.generico, da.marca, da.des_articulo
        """
        return self.execute_query(query, {"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta})

    def get_ventas_subdistribuidores_sheet(
        self,
        fecha_desde: str,
        fecha_hasta: str,
        sucursales_interior: list[str],
        genericos: list[str],
        lista_casa_central: int = 11,
        lista_interior: int = 12,
    ) -> pd.DataFrame:
        """Ventas de SUB DISTRIBUIDORES por origen/generico/marca.

        Combina dos grupos de sub-distribuidores en una sola hoja:
        - lista_casa_central (default 11): sub-distribuidores de CASA CENTRAL
          (todos en sucursal 1). Se etiquetan con origen 'CASA CENTRAL'.
        - lista_interior (default 12): sub-distribuidores del interior, pero SOLO
          los de las `sucursales_interior` indicadas (lista 12 existe en muchas
          sucursales). Se etiquetan con la descripcion de su sucursal.

        `genericos`: SIEMPRE se filtra a esta lista (directiva del informe: solo
        genericos CCU). Es obligatorio y no debe venir vacio.

        Suma cantidades del periodo. No filtra anulado (regla del proyecto); el
        neto sale de la suma. Join con dim_cliente por clave compuesta.

        Returns:
            DataFrame con columnas
            [origen, razon_social, fantasia, generico, marca, bultos, htls].
            Se abre por sub-distribuidor (razon_social/fantasia del cliente) para
            que el informe de Adrian Garcia muestre los nombres, no solo el origen.
        """
        suc = sucursales_interior or []
        suc_placeholders = ", ".join(f":suc_{i}" for i in range(len(suc)))
        # Si no hay sucursales de interior, el bloque de lista 12 no matchea nada.
        interior_clause = (
            f"(dc.id_lista_precio = :lista_int AND ds.descripcion IN ({suc_placeholders}))"
            if suc else "FALSE"
        )
        gen = genericos or []
        gen_placeholders = ", ".join(f":gen_{i}" for i in range(len(gen)))
        # Directiva: solo genericos CCU. Si la lista viniera vacia, no devolver nada
        # (en vez de traer todo) para no romper la directiva por accidente.
        generico_clause = f"da.generico IN ({gen_placeholders})" if gen else "FALSE"
        query = f"""
        SELECT
            CASE WHEN dc.id_lista_precio = :lista_cc THEN 'CASA CENTRAL'
                 ELSE ds.descripcion END           AS origen,
            dc.razon_social                         AS razon_social,
            dc.fantasia                             AS fantasia,
            COALESCE(da.generico, 'SIN GENERICO')   AS generico,
            da.marca,
            SUM(fv.cantidades_total)                AS bultos,
            SUM(fv.cantidad_total_htls)             AS htls
        FROM gold.fact_ventas fv
        JOIN gold.dim_articulo  da ON fv.id_articulo = da.id_articulo
        JOIN gold.dim_cliente   dc ON fv.id_cliente   = dc.id_cliente
                                  AND fv.id_sucursal   = dc.id_sucursal
        JOIN gold.dim_sucursal  ds ON dc.id_sucursal   = ds.id_sucursal
        WHERE fv.fecha_comprobante BETWEEN :fecha_desde AND :fecha_hasta
          AND {generico_clause}
          AND (
                dc.id_lista_precio = :lista_cc
                OR {interior_clause}
              )
        GROUP BY 1, dc.razon_social, dc.fantasia,
                 COALESCE(da.generico, 'SIN GENERICO'), da.marca
        ORDER BY origen, dc.razon_social, generico, da.marca
        """
        params = {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "lista_cc": lista_casa_central,
            "lista_int": lista_interior,
        }
        for i, s in enumerate(suc):
            params[f"suc_{i}"] = s
        for i, g in enumerate(gen):
            params[f"gen_{i}"] = g
        return self.execute_query(query, params)

    # ── Stock Badie ────────────────────────────────────────────

    def get_venta_mes(self, fecha_desde: str, fecha_hasta: str) -> pd.DataFrame:
        """Current calendar-month sales, grouped by (id_sucursal, id_articulo).

        Args:
            fecha_desde: Inclusive lower bound, format 'YYYY-MM-DD' (first day
                of the current month).
            fecha_hasta: Exclusive upper bound, format 'YYYY-MM-DD' (first day
                of the NEXT month). The window is half-open
                [fecha_desde, fecha_hasta) to avoid partial-month leakage.

        Note: fact_ventas already carries id_sucursal directly, so this query
        does NOT join/filter by id_ruta or id_vendedor — the composite-key
        rule (id + id_sucursal) does not apply here.

        Returns:
            DataFrame with columns: id_sucursal, sucursal, id_articulo,
            venta_bultos, venta_htls.
        """
        query = """
        SELECT
            fv.id_sucursal,
            ds.descripcion AS sucursal,
            fv.id_articulo,
            SUM(fv.cantidades_total) AS venta_bultos,
            SUM(fv.cantidad_total_htls) AS venta_htls
        FROM gold.fact_ventas fv
        LEFT JOIN gold.dim_sucursal ds ON fv.id_sucursal = ds.id_sucursal
        WHERE fv.fecha_comprobante >= :fecha_desde
          AND fv.fecha_comprobante < :fecha_hasta
        GROUP BY fv.id_sucursal, ds.descripcion, fv.id_articulo
        ORDER BY fv.id_sucursal, fv.id_articulo
        """
        params = {"fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta}
        return self.execute_query(query, params)

    def get_ultima_fecha_stock(self):
        """Latest stock snapshot date available in gold.fact_stock.

        Returns:
            date, or None if fact_stock has no rows.
        """
        query = "SELECT MAX(date_stock) AS ultima_fecha FROM gold.fact_stock"
        df = self.execute_query(query)
        if df.empty or df["ultima_fecha"].iloc[0] is None:
            return None
        return pd.to_datetime(df["ultima_fecha"].iloc[0]).date()


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
