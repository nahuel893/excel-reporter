"""
Procesador especifico para reportes de ventas.

Contiene la logica de procesamiento y formato de datos
para el reporte de ventas por sucursal, generico y marca.
"""
import pandas as pd
from datetime import datetime
from config.settings import COLUMN_NAMES, DIAS_SEMANA
from src.core.base_processor import calcular_factor_tendencia, completar_combinaciones as base_completar


def completar_combinaciones(df_ventas: pd.DataFrame, df_sucursales: pd.DataFrame, df_articulos: pd.DataFrame, col_cantidad: str = "cantidad") -> pd.DataFrame:
    """
    Completa el DataFrame de ventas con todas las combinaciones sucursal-generico-marca.
    Las combinaciones sin ventas se rellenan con 0.

    Args:
        df_ventas: DataFrame con ventas (sucursal, generico, marca, cantidad, monto)
        df_sucursales: DataFrame con todas las sucursales
        df_articulos: DataFrame con todas las combinaciones generico-marca
        col_cantidad: Nombre de la columna de cantidad a usar

    Returns:
        DataFrame con todas las combinaciones, ventas faltantes en 0
    """
    return base_completar(
        df_datos=df_ventas,
        df_dimension1=df_sucursales,
        df_dimension2=df_articulos,
        cols_join=["sucursal", "generico", "marca"],
        cols_fill=[col_cantidad, "monto"]
    )


def formatear_nombre_dia(fecha: datetime) -> str:
    """
    Formatea una fecha como 'dd-mm DayName'.

    Args:
        fecha: Objeto datetime

    Returns:
        String formateado, ej: '01-01 Jueves'
    """
    dia_semana = DIAS_SEMANA[fecha.weekday()]
    return f"{fecha.strftime('%d-%m')} {dia_semana}"


def procesar_ventas_diarias(
    df: pd.DataFrame,
    fecha_desde: str,
    fecha_hasta: str,
    df_sucursales: pd.DataFrame | None = None,
    df_articulos: pd.DataFrame | None = None,
    col_cantidad: str = "cantidad",
    df_cob_generico: pd.DataFrame | None = None,
    df_cob_marca: pd.DataFrame | None = None,
    df_mmaa: pd.DataFrame | None = None,
    df_cupos: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Procesa las ventas diarias para generar tabla con columnas por dia.

    Formato de salida:
    Sucursal | Generico | Cant(Gen) | Tend(Gen) | Monto(Gen) | Cob(Gen) | Cupo(Gen) | Cupo vs Tend(Gen) | Marca | dias... | Total | MMAA | Var% | Tend | Monto | Cob(Marca) | Cupo(Marca) | Cupo vs Tend(Marca)

    Args:
        df: DataFrame con columnas: sucursal, generico, marca, fecha, cantidad, monto
        fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
        fecha_hasta: Fecha fin formato 'YYYY-MM-DD'
        df_sucursales: DataFrame con todas las sucursales (para completar combinaciones)
        df_articulos: DataFrame con todas las combinaciones generico-marca
        col_cantidad: Columna de cantidad a usar ('cantidad' para bultos, 'cantidad_htls' para htls)
        df_cob_generico: DataFrame con cobertura por (sucursal, generico, clientes_compradores)
        df_cob_marca: DataFrame con cobertura por (sucursal, marca, clientes_compradores)
        df_mmaa: DataFrame con ventas del mismo periodo año anterior, agrupado por
                 (sucursal, generico, marca) con columnas cantidad y cantidad_htls.
        df_cupos: DataFrame con cupos por (sucursal, cupo_generico, cupo).
                  cupo_generico contiene tanto genericos como marcas.

    Returns:
        DataFrame con formato incluyendo dias como columnas y columnas de cobertura y cupos
    """
    if df.empty:
        return pd.DataFrame(columns=list(COLUMN_NAMES.values()))

    # Construir dict de lookup para cupos: (sucursal, cupo_generico) -> cupo
    # Sirve tanto para genericos como para marcas (mismo lookup, distinta clave)
    cupos_dict: dict = {}
    if df_cupos is not None and not df_cupos.empty:
        for _, r in df_cupos.iterrows():
            cupo_val = r["cupo"]
            if cupo_val is not None and not (isinstance(cupo_val, float) and cupo_val != cupo_val) and cupo_val > 0:
                cupos_dict[(r["sucursal"], r["cupo_generico"])] = cupo_val

    # Construir dicts de lookup para cobertura (acceso O(1) en el loop)
    cob_gen_dict = {}
    if df_cob_generico is not None and not df_cob_generico.empty:
        cob_gen_dict = {
            (r["sucursal"], r["generico"]): r["clientes_compradores"]
            for _, r in df_cob_generico.iterrows()
        }

    cob_marca_dict = {}
    if df_cob_marca is not None and not df_cob_marca.empty:
        cob_marca_dict = {
            (r["sucursal"], r["marca"]): r["clientes_compradores"]
            for _, r in df_cob_marca.iterrows()
        }

    # Construir dict de lookup para MMAA (acceso O(1) en el loop)
    mmaa_dict: dict = {}
    if df_mmaa is not None and not df_mmaa.empty:
        for _, r in df_mmaa.iterrows():
            val = r.get(col_cantidad, 0)
            mmaa_dict[(r["sucursal"], r["generico"], r["marca"])] = int(val) if val and val > 0 else None

    # Asegurar que fecha sea datetime
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"])

    # Completar combinaciones faltantes si se proporcionan las dimensiones
    if df_sucursales is not None and df_articulos is not None:
        fechas_unicas = df["fecha"].unique()

        # Crear producto cartesiano: sucursales × articulos × fechas
        df_sucursales_temp = df_sucursales.copy()
        df_articulos_temp = df_articulos.copy()
        df_sucursales_temp["_key"] = 1
        df_articulos_temp["_key"] = 1

        todas_combinaciones = df_sucursales_temp.merge(df_articulos_temp, on="_key").drop("_key", axis=1)

        # Expandir por fechas
        df_fechas = pd.DataFrame({"fecha": fechas_unicas, "_key": 1})
        todas_combinaciones["_key"] = 1
        todas_combinaciones = todas_combinaciones.merge(df_fechas, on="_key").drop("_key", axis=1)

        # Merge con ventas reales (left join)
        df = todas_combinaciones.merge(
            df,
            on=["sucursal", "generico", "marca", "fecha"],
            how="left"
        )

        # Rellenar NaN con 0
        df[col_cantidad] = df[col_cantidad].fillna(0)
        df["monto"] = df["monto"].fillna(0)
        if "descuentos" in df.columns:
            df["descuentos"] = df["descuentos"].fillna(0)

    # Factor de tendencia
    factor_tendencia = calcular_factor_tendencia(fecha_desde, fecha_hasta)

    # Obtener fechas unicas ordenadas y crear nombres de columnas
    fechas_unicas = sorted(df["fecha"].unique())
    columnas_dias = {fecha: formatear_nombre_dia(pd.Timestamp(fecha)) for fecha in fechas_unicas}

    # Pivotar cantidades por dia
    pivot_dias = df.pivot_table(
        index=["sucursal", "generico", "marca"],
        columns="fecha",
        values=col_cantidad,
        aggfunc="sum",
        fill_value=0
    ).reset_index()

    # Renombrar columnas de fecha al formato deseado
    pivot_dias.columns = [
        columnas_dias.get(col, col) if col in columnas_dias else col
        for col in pivot_dias.columns
    ]

    # Calcular totales por marca (suma de cantidad, monto y descuentos)
    agg_cols = {col_cantidad: "sum", "monto": "sum"}
    has_descuentos = "descuentos" in df.columns
    if has_descuentos:
        agg_cols["descuentos"] = "sum"
    totales_marca = df.groupby(["sucursal", "generico", "marca"]).agg(agg_cols).reset_index()
    rename_cols = ["sucursal", "generico", "marca", "total_marca", "monto_marca"]
    if has_descuentos:
        rename_cols.append("desc_marca")
    totales_marca.columns = rename_cols
    totales_marca["tend_marca"] = totales_marca["total_marca"] * factor_tendencia

    # Merge pivot con totales
    df_merged = pivot_dias.merge(totales_marca, on=["sucursal", "generico", "marca"])

    # Calcular totales por generico
    agg_gen = {"total_marca": "sum", "monto_marca": "sum"}
    if has_descuentos:
        agg_gen["desc_marca"] = "sum"
    totales_generico = df_merged.groupby(["sucursal", "generico"]).agg(agg_gen).reset_index()
    rename_gen = ["sucursal", "generico", "cant_generico", "monto_generico"]
    if has_descuentos:
        rename_gen.append("desc_generico")
    totales_generico.columns = rename_gen
    totales_generico["tend_generico"] = totales_generico["cant_generico"] * factor_tendencia

    # Ordenar por sucursal, generico y monto descendente
    df_merged = df_merged.sort_values(
        ["sucursal", "generico", "monto_marca"],
        ascending=[True, True, False]
    )

    # Obtener nombres de columnas de dias en orden
    cols_dias = [columnas_dias[f] for f in fechas_unicas]

    # Construir tabla final con totales de generico solo en primera fila
    rows = []
    for (sucursal, generico), grupo in df_merged.groupby(["sucursal", "generico"], sort=False):
        # Obtener totales del generico
        totales = totales_generico[
            (totales_generico["sucursal"] == sucursal) &
            (totales_generico["generico"] == generico)
        ].iloc[0]

        for i, (_, fila) in enumerate(grupo.iterrows()):
            # Cupo de generico (solo primera fila del grupo)
            cupo_gen = cupos_dict.get((sucursal, generico))
            cupo_gen_val = cupo_gen if i == 0 else None
            tend_gen_rounded = round(totales["tend_generico"]) if i == 0 else None
            cupo_vs_tend_gen = (tend_gen_rounded / cupo_gen) if (i == 0 and cupo_gen) else None

            row = {
                COLUMN_NAMES["sucursal"]: sucursal,
                COLUMN_NAMES["generico"]: generico,
                COLUMN_NAMES["cant_generico"]: totales["cant_generico"] if i == 0 else None,
                COLUMN_NAMES["tend_generico"]: tend_gen_rounded,
                COLUMN_NAMES["monto_generico"]: totales["monto_generico"] if i == 0 else None,
                COLUMN_NAMES["desc_generico"]: totales.get("desc_generico") if i == 0 else None,
                COLUMN_NAMES["desc_pct_generico"]: (
                    totales.get("desc_generico") / totales["monto_generico"]
                    if i == 0 and totales.get("desc_generico") and totales["monto_generico"]
                    else None
                ),
                COLUMN_NAMES["cob_generico"]: cob_gen_dict.get((sucursal, generico)) if i == 0 else None,
                COLUMN_NAMES["cupo_generico"]: cupo_gen_val,
                COLUMN_NAMES["cupo_vs_tend_generico"]: cupo_vs_tend_gen,
                COLUMN_NAMES["marca"]: fila["marca"],
            }

            # Agregar columnas de dias (0 si no hay venta)
            for col_dia in cols_dias:
                row[col_dia] = int(fila[col_dia])

            # Agregar totales de marca
            row[COLUMN_NAMES["total_marca"]] = fila["total_marca"]

            tend_marca_rounded = round(fila["tend_marca"])
            row[COLUMN_NAMES["tend_marca"]] = tend_marca_rounded

            # Cupo de marca
            cupo_marca = cupos_dict.get((sucursal, fila["marca"]))
            row[COLUMN_NAMES["cupo_marca"]] = cupo_marca
            row[COLUMN_NAMES["cupo_vs_tend_marca"]] = (tend_marca_rounded / cupo_marca) if cupo_marca else None

            # MMAA y Var%
            mmaa_val = mmaa_dict.get((sucursal, generico, fila["marca"]))
            row[COLUMN_NAMES["mmaa_marca"]] = mmaa_val
            row[COLUMN_NAMES["var_mmaa_marca"]] = (fila["total_marca"] / mmaa_val) if mmaa_val else None

            row[COLUMN_NAMES["cob_marca"]] = cob_marca_dict.get((sucursal, fila["marca"]))

            # Columnas de plata
            monto_m = fila["monto_marca"]
            desc_m = fila.get("desc_marca")
            row[COLUMN_NAMES["monto_marca"]] = monto_m
            row[COLUMN_NAMES["desc_marca"]] = desc_m
            row[COLUMN_NAMES["desc_pct_marca"]] = (desc_m / monto_m) if desc_m and monto_m else None

            rows.append(row)

    return pd.DataFrame(rows)


# Mantener funcion original para compatibilidad
def procesar_ventas(df: pd.DataFrame, fecha_desde: str, fecha_hasta: str) -> pd.DataFrame:
    """
    Procesa las ventas para generar tabla con totales por generico y tendencias.
    Version sin desglose diario (compatibilidad).

    Args:
        df: DataFrame con columnas: sucursal, generico, marca, cantidad, monto
        fecha_desde: Fecha inicio formato 'YYYY-MM-DD'
        fecha_hasta: Fecha fin formato 'YYYY-MM-DD'

    Returns:
        DataFrame con formato incluyendo tendencias
    """
    if df.empty:
        return pd.DataFrame(columns=list(COLUMN_NAMES.values()))

    # Factor de tendencia
    factor_tendencia = calcular_factor_tendencia(fecha_desde, fecha_hasta)

    # Calcular totales por sucursal y generico
    totales_generico = df.groupby(["sucursal", "generico"]).agg({
        "cantidad": "sum",
        "monto": "sum"
    }).reset_index()
    totales_generico.columns = ["sucursal", "generico", "cant_generico", "monto_generico"]
    totales_generico["tend_generico"] = totales_generico["cant_generico"] * factor_tendencia

    # Ordenar datos por sucursal, generico y monto descendente
    df = df.sort_values(["sucursal", "generico", "monto"], ascending=[True, True, False])

    # Construir tabla final
    rows = []
    for (sucursal, generico), grupo in df.groupby(["sucursal", "generico"], sort=False):
        # Obtener totales del generico
        totales = totales_generico[
            (totales_generico["sucursal"] == sucursal) &
            (totales_generico["generico"] == generico)
        ].iloc[0]

        for i, (_, fila) in enumerate(grupo.iterrows()):
            tendencia_marca = fila["cantidad"] * factor_tendencia
            row = {
                COLUMN_NAMES["sucursal"]: sucursal,
                COLUMN_NAMES["generico"]: generico,
                COLUMN_NAMES["cant_generico"]: totales["cant_generico"] if i == 0 else None,
                COLUMN_NAMES["tend_generico"]: round(totales["tend_generico"]) if i == 0 else None,
                COLUMN_NAMES["monto_generico"]: totales["monto_generico"] if i == 0 else None,
                COLUMN_NAMES["marca"]: fila["marca"],
                COLUMN_NAMES["total_marca"]: fila["cantidad"],
                COLUMN_NAMES["tend_marca"]: round(tendencia_marca),
                COLUMN_NAMES["monto_marca"]: fila["monto"],
            }
            rows.append(row)

    return pd.DataFrame(rows)
