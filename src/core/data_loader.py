"""
DataLoader - Acceso a datos del Data Warehouse.

Proporciona acceso centralizado a la base de datos PostgreSQL
usando SQLAlchemy con soporte para inyección de dependencias.
"""
import pandas as pd
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

    # ── Cobertura ──────────────────────────────────────────────

    def get_cobertura_preventista_generico(
        self,
        periodo_desde: str,
        periodo_hasta: str,
        sucursales: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Obtiene cobertura por preventista y generico.

        Args:
            periodo_desde: Periodo inicio formato 'YYYY-MM-DD'
            periodo_hasta: Periodo fin formato 'YYYY-MM-DD'
            sucursales: Lista de sucursales a filtrar. Si es None, trae todas.

        Returns:
            DataFrame con columnas: periodo, sucursal, id_vendedor, id_ruta,
            generico, clientes_compradores, volumen_total
        """
        filtro_suc = ""
        params = {"desde": periodo_desde, "hasta": periodo_hasta}

        if sucursales:
            placeholders = ", ".join([f":suc_{i}" for i in range(len(sucursales))])
            filtro_suc = f"AND cpg.ds_sucursal IN ({placeholders})"
            params.update({f"suc_{i}": s for i, s in enumerate(sucursales)})

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
        WHERE cpg.periodo BETWEEN :desde AND :hasta
        {filtro_suc}
        ORDER BY cpg.periodo, cpg.ds_sucursal, dv.des_vendedor, cpg.generico
        """
        return self.execute_query(query, params)

    def get_cobertura_preventista_marca(
        self,
        periodo_desde: str,
        periodo_hasta: str,
        sucursales: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Obtiene cobertura por preventista y marca.

        Args:
            periodo_desde: Periodo inicio formato 'YYYY-MM-DD'
            periodo_hasta: Periodo fin formato 'YYYY-MM-DD'
            sucursales: Lista de sucursales a filtrar. Si es None, trae todas.

        Returns:
            DataFrame con columnas: periodo, sucursal, id_vendedor, vendedor,
            id_ruta, marca, clientes_compradores, volumen_total
        """
        filtro_suc = ""
        params = {"desde": periodo_desde, "hasta": periodo_hasta}

        if sucursales:
            placeholders = ", ".join([f":suc_{i}" for i in range(len(sucursales))])
            filtro_suc = f"AND cpm.ds_sucursal IN ({placeholders})"
            params.update({f"suc_{i}": s for i, s in enumerate(sucursales)})

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
        WHERE cpm.periodo BETWEEN :desde AND :hasta
        {filtro_suc}
        ORDER BY cpm.periodo, cpm.ds_sucursal, dv.des_vendedor, cpm.marca
        """
        return self.execute_query(query, params)

    def get_cobertura_sucursal_marca(
        self,
        periodo_desde: str,
        periodo_hasta: str,
        sucursales: list[str] | None = None
    ) -> pd.DataFrame:
        """
        Obtiene cobertura agregada por sucursal y marca.

        Args:
            periodo_desde: Periodo inicio formato 'YYYY-MM-DD'
            periodo_hasta: Periodo fin formato 'YYYY-MM-DD'
            sucursales: Lista de sucursales a filtrar. Si es None, trae todas.

        Returns:
            DataFrame con columnas: periodo, sucursal, marca,
            clientes_compradores, volumen_total
        """
        filtro_suc = ""
        params = {"desde": periodo_desde, "hasta": periodo_hasta}

        if sucursales:
            placeholders = ", ".join([f":suc_{i}" for i in range(len(sucursales))])
            filtro_suc = f"AND csm.ds_sucursal IN ({placeholders})"
            params.update({f"suc_{i}": s for i, s in enumerate(sucursales)})

        query = f"""
        SELECT
            csm.periodo,
            csm.ds_sucursal AS sucursal,
            csm.marca,
            csm.clientes_compradores,
            csm.volumen_total
        FROM gold.cob_sucursal_marca csm
        WHERE csm.periodo BETWEEN :desde AND :hasta
        {filtro_suc}
        ORDER BY csm.periodo, csm.ds_sucursal, csm.marca
        """
        return self.execute_query(query, params)


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
