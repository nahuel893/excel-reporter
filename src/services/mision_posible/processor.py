"""
Processor para Mision Posible - Logica de procesamiento de cobertura.

Funciones para calcular tablas de cobertura por sucursal y vendedor,
con objetivos, faltantes y porcentajes.
"""
import pandas as pd


def procesar_cobertura_sucursal(
    df_cob: pd.DataFrame,
    marca: str,
    objetivo_total: int | None,
    porcentajes_sucursal: dict[str, float],
) -> pd.DataFrame:
    """Genera tabla de cobertura por sucursal para una marca.

    Args:
        df_cob: DataFrame de cob_preventista_marca (post zonas virtuales).
        marca: Nombre de la marca a filtrar.
        objetivo_total: Objetivo total empresa para esta marca (o None).
        porcentajes_sucursal: Dict {sucursal: porcentaje} para reparto.

    Returns:
        DataFrame con columnas [Sucursal, Cobertura, Objetivo, Faltante, %].
    """
    df_marca = df_cob[df_cob["marca"] == marca] if not df_cob.empty else df_cob

    # Agrupar cobertura por sucursal
    if not df_marca.empty:
        cob_por_suc = (
            df_marca.groupby("sucursal")["clientes_compradores"]
            .sum()
            .reset_index()
            .rename(columns={"clientes_compradores": "Cobertura"})
        )
    else:
        cob_por_suc = pd.DataFrame(columns=["sucursal", "Cobertura"])

    # Asegurar todas las sucursales de porcentajes_sucursal
    todas_suc = pd.DataFrame({"sucursal": list(porcentajes_sucursal.keys())})
    df_result = todas_suc.merge(cob_por_suc, on="sucursal", how="left")
    df_result["Cobertura"] = df_result["Cobertura"].fillna(0).astype(int)

    # Calcular objetivo por sucursal
    def _objetivo_suc(suc):
        if objetivo_total is None:
            return None
        pct = porcentajes_sucursal.get(suc)
        if pct is None:
            return None
        return round(objetivo_total * pct / 100)

    df_result["Objetivo"] = df_result["sucursal"].apply(_objetivo_suc)
    df_result["Faltante"] = df_result.apply(
        lambda r: r["Objetivo"] - r["Cobertura"] if r["Objetivo"] is not None else None,
        axis=1,
    )
    df_result["%"] = df_result.apply(
        lambda r: round(r["Cobertura"] / r["Objetivo"] * 100, 1)
        if r["Objetivo"] is not None and r["Objetivo"] != 0
        else None,
        axis=1,
    )

    df_result = df_result.sort_values("sucursal").reset_index(drop=True)
    df_result = df_result.rename(columns={"sucursal": "Sucursal"})
    return df_result[["Sucursal", "Cobertura", "Objetivo", "Faltante", "%"]]


def procesar_cobertura_vendedor(
    df_cob: pd.DataFrame,
    marca: str,
    objetivo_total: int | None,
    porcentajes_sucursal: dict[str, float],
) -> pd.DataFrame:
    """Genera tabla de cobertura por vendedor para una marca.

    Args:
        df_cob: DataFrame de cob_preventista_marca (post zonas virtuales).
        marca: Nombre de la marca a filtrar.
        objetivo_total: Objetivo total empresa para esta marca (o None).
        porcentajes_sucursal: Dict {sucursal: porcentaje} para reparto.

    Returns:
        DataFrame con columnas [Vendedor, Sucursal, Cobertura, Objetivo, Faltante, %].
    """
    df_marca = df_cob[df_cob["marca"] == marca] if not df_cob.empty else df_cob

    if df_marca.empty:
        return pd.DataFrame(columns=["Vendedor", "Sucursal", "Cobertura", "Objetivo", "Faltante", "%"])

    # Agrupar por vendedor+sucursal
    df_vend = (
        df_marca.groupby(["sucursal", "vendedor"])["clientes_compradores"]
        .sum()
        .reset_index()
        .rename(columns={"clientes_compradores": "Cobertura"})
    )

    # Contar vendedores por sucursal para reparto igualitario
    vend_por_suc = df_vend.groupby("sucursal")["vendedor"].count().to_dict()

    # Calcular objetivo por vendedor
    def _objetivo_vend(row):
        suc = row["sucursal"]
        if objetivo_total is None:
            return None
        pct = porcentajes_sucursal.get(suc)
        if pct is None:
            return None
        obj_suc = round(objetivo_total * pct / 100)
        cant_vend = vend_por_suc.get(suc, 1)
        return round(obj_suc / cant_vend)

    df_vend["Objetivo"] = df_vend.apply(_objetivo_vend, axis=1)
    df_vend["Faltante"] = df_vend.apply(
        lambda r: r["Objetivo"] - r["Cobertura"] if r["Objetivo"] is not None else None,
        axis=1,
    )
    df_vend["%"] = df_vend.apply(
        lambda r: round(r["Cobertura"] / r["Objetivo"] * 100, 1)
        if r["Objetivo"] is not None and r["Objetivo"] != 0
        else None,
        axis=1,
    )

    df_vend = (
        df_vend.sort_values(["sucursal", "vendedor"])
        .reset_index(drop=True)
        .rename(columns={"sucursal": "Sucursal", "vendedor": "Vendedor"})
    )
    return df_vend[["Vendedor", "Sucursal", "Cobertura", "Objetivo", "Faltante", "%"]]


def concatenar_tablas(df_sucursal: pd.DataFrame, df_vendedor: pd.DataFrame) -> pd.DataFrame:
    """Concatena tabla sucursal y vendedor con fila separadora.

    La tabla vendedor tiene columnas [Vendedor, Sucursal, ...] que se mapean
    a las posiciones de la tabla sucursal [Sucursal, Cobertura, ...].

    Returns:
        DataFrame unificado con ambas tablas.
    """
    cols_suc = list(df_sucursal.columns)

    # Fila separadora vacia
    sep = pd.DataFrame([{c: None for c in cols_suc}])

    # Fila titulo "Por Vendedor"
    titulo = pd.DataFrame([{cols_suc[0]: "Por Vendedor", **{c: None for c in cols_suc[1:]}}])

    # Encabezado de tabla vendedor mapeado a columnas de sucursal
    header_vend = pd.DataFrame([{
        cols_suc[0]: "Vendedor",
        cols_suc[1]: "Sucursal",
        cols_suc[2]: "Cobertura",
        cols_suc[3]: "Objetivo",
        cols_suc[4]: "Faltante",
    }])
    # Agregar columna % si existe
    if len(cols_suc) > 5:
        header_vend[cols_suc[5]] = "%"

    # Datos de vendedor mapeados a columnas de sucursal
    if not df_vendedor.empty:
        vend_data = pd.DataFrame()
        vend_cols = list(df_vendedor.columns)
        for i, col_suc in enumerate(cols_suc):
            if i < len(vend_cols):
                vend_data[col_suc] = df_vendedor[vend_cols[i]].values
            else:
                vend_data[col_suc] = None
    else:
        vend_data = pd.DataFrame(columns=cols_suc)

    result = pd.concat([df_sucursal, sep, titulo, header_vend, vend_data], ignore_index=True)
    return result
