"""
Procesador especifico para reportes de resumen mensual.

Contiene la logica de procesamiento y formato de datos
para el reporte de resumen mensual por sucursal y generico.
"""
import pandas as pd
from datetime import date, datetime

from config.settings import FERIADOS, DIAS_SEMANA
from src.core.base_processor import calcular_factor_tendencia


def _formatear_dia(d) -> str:
    """Formatea una fecha como 'dd-mm DiaSemana', ej: '28-02 Sabado'."""
    return f"{d.strftime('%d-%m')} {DIAS_SEMANA[d.weekday()]}"


def _detectar_dias_habiles_con_ventas(df: pd.DataFrame, n: int = 2) -> list:
    """
    Retorna los ultimos N dias que tienen ventas reales en el DataFrame,
    filtrando domingos y feriados.

    Args:
        df: DataFrame con columna 'fecha'
        n: Cantidad de dias a retornar

    Returns:
        Lista de dates ordenados descendente (el ultimo primero)
    """
    feriados_set = {datetime.strptime(f, "%Y-%m-%d").date() for f in FERIADOS}
    fechas_con_ventas = pd.to_datetime(df["fecha"]).dt.date.unique()
    fechas_habiles = sorted(
        [d for d in fechas_con_ventas if d.weekday() != 6 and d not in feriados_set],
        reverse=True,
    )
    return fechas_habiles[:n]


def procesar_resumen_mensual(
    df_ventas_mes: pd.DataFrame,
    df_dias: pd.DataFrame,
    df_ventas_ma: pd.DataFrame,
    df_ventas_aa: pd.DataFrame,
    fecha_desde: str,
    fecha_hasta: str,
    con_objetivo: bool = False,
    df_cupos: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Construye el DataFrame de resumen mensual con 10 columnas.

    Args:
        df_ventas_mes: Ventas del periodo actual agrupadas por (sucursal, generico).
                       Columnas: sucursal, generico, cantidad.
        df_dias:       Ventas de los ultimos dias agrupadas por (sucursal, generico, fecha).
                       Columnas: sucursal, generico, fecha, cantidad.
        df_ventas_ma:  Ventas del mes anterior agrupadas por (sucursal, generico).
                       Columnas: sucursal, generico, cantidad.
        df_ventas_aa:  Ventas del mismo mes del ano anterior agrupadas por (sucursal, generico).
                       Columnas: sucursal, generico, cantidad.
        fecha_desde:   Fecha inicio formato 'YYYY-MM-DD'.
        fecha_hasta:   Fecha fin formato 'YYYY-MM-DD'.
        con_objetivo:  Si True, calcular Tend vs Obj (%) a partir de Objetivo.
                       Si False (default), Objetivo y Tend vs Obj (%) quedan como None.
        df_cupos:      DataFrame con columnas (sucursal, generico, cupo) para el objetivo.
                       Si None o vacio, Objetivo queda como None/NaN.

    Returns:
        DataFrame con columnas (en orden):
        Sucursal, Generico, Vtas Dia N-2, Vtas Dia N-1, Total Ventas,
        Tendencia, MMAA, MA, Objetivo, Tend vs Obj (%)
    """
    if df_cupos is None:
        df_cupos = pd.DataFrame(columns=["sucursal", "generico", "cupo"])

    # -------------------------------------------------------------------------
    # 1. Detectar fechas N-1 y N-2
    # -------------------------------------------------------------------------
    fechas_nd = _detectar_dias_habiles_con_ventas(df_dias, n=2) if not df_dias.empty else []
    fecha_n1 = fechas_nd[0] if len(fechas_nd) >= 1 else None
    fecha_n2 = fechas_nd[1] if len(fechas_nd) >= 2 else None

    col_n1 = _formatear_dia(fecha_n1) if fecha_n1 else "Vtas Dia N-1"
    col_n2 = _formatear_dia(fecha_n2) if fecha_n2 else "Vtas Dia N-2"

    # -------------------------------------------------------------------------
    # 2. Extraer ventas de N-1 y N-2
    # -------------------------------------------------------------------------
    def _extraer_ventas_fecha(df: pd.DataFrame, target_date) -> pd.DataFrame:
        """Devuelve DataFrame (sucursal, generico, cantidad) para una fecha dada."""
        if df.empty or target_date is None:
            return pd.DataFrame(columns=["sucursal", "generico", "cantidad"])
        fechas_col = pd.to_datetime(df["fecha"]).dt.date
        mask = fechas_col == target_date
        subset = df[mask].copy()
        if subset.empty:
            return pd.DataFrame(columns=["sucursal", "generico", "cantidad"])
        return subset.groupby(["sucursal", "generico"], as_index=False)["cantidad"].sum()

    df_n1 = _extraer_ventas_fecha(df_dias, fecha_n1)
    df_n2 = _extraer_ventas_fecha(df_dias, fecha_n2)

    # -------------------------------------------------------------------------
    # 3. Factor de tendencia
    # -------------------------------------------------------------------------
    factor_tendencia = calcular_factor_tendencia(fecha_desde, fecha_hasta)

    # -------------------------------------------------------------------------
    # 4. Construir DataFrame base
    #    Outer join entre df_ventas_mes y df_ventas_aa para incluir combinaciones
    #    que tienen datos en cualquiera de los dos periodos.
    # -------------------------------------------------------------------------

    def _preparar_df(df: pd.DataFrame, col_nueva: str) -> pd.DataFrame:
        """Renombra 'cantidad' a col_nueva y garantiza las columnas clave."""
        if df.empty:
            return pd.DataFrame(columns=["sucursal", "generico", col_nueva])
        return df[["sucursal", "generico", "cantidad"]].rename(columns={"cantidad": col_nueva})

    df_mes_prep = _preparar_df(df_ventas_mes, "total_ventas")
    df_aa_prep = _preparar_df(df_ventas_aa, "ventas_aa")
    df_ma_prep = _preparar_df(df_ventas_ma, "ventas_ma")
    df_n1_prep = _preparar_df(df_n1, "vtas_n1")
    df_n2_prep = _preparar_df(df_n2, "vtas_n2")

    # Outer-join the 4 ventas dataframes (mes, aa, ma) plus the 2 day-slices.
    # Outer joins preserve any (sucursal, generico) that appears in ANY period —
    # so historical-only data (MMAA / MA without current month) is not lost.
    df_base = df_mes_prep.merge(df_aa_prep, on=["sucursal", "generico"], how="outer")
    df_base = df_base.merge(df_ma_prep, on=["sucursal", "generico"], how="outer")
    df_base = df_base.merge(df_n1_prep, on=["sucursal", "generico"], how="outer")
    df_base = df_base.merge(df_n2_prep, on=["sucursal", "generico"], how="outer")

    # -------------------------------------------------------------------------
    # 5. Universe expansion: every sucursal must appear for every generico.
    #    Universe = union of sucursales (and genericos) across all input dfs.
    #    Combinations with no data anywhere still appear in the result with 0s.
    # -------------------------------------------------------------------------
    all_sucursales: set = set()
    all_genericos: set = set()
    for src in (df_ventas_mes, df_dias, df_ventas_ma, df_ventas_aa):
        if src is None or src.empty:
            continue
        if "sucursal" in src.columns:
            all_sucursales.update(src["sucursal"].dropna().unique())
        if "generico" in src.columns:
            all_genericos.update(src["generico"].dropna().unique())

    if all_sucursales and all_genericos:
        cross = pd.MultiIndex.from_product(
            [sorted(all_sucursales), sorted(all_genericos)],
            names=["sucursal", "generico"],
        ).to_frame(index=False)
        df_base = cross.merge(df_base, on=["sucursal", "generico"], how="left")

    # Fill 0 for ventas-related numeric columns where no data was found.
    for col in ("total_ventas", "ventas_aa", "ventas_ma", "vtas_n1", "vtas_n2"):
        if col in df_base.columns:
            df_base[col] = df_base[col].fillna(0)

    # -------------------------------------------------------------------------
    # 6. Calcular Tendencia (PRIMARY RULE: sin .round().astype(int))
    # -------------------------------------------------------------------------
    df_base["tendencia"] = df_base["total_ventas"] * factor_tendencia

    # -------------------------------------------------------------------------
    # 7. Left-join con cupos para Objetivo
    # -------------------------------------------------------------------------
    if not df_cupos.empty and "cupo" in df_cupos.columns:
        df_cupos_prep = df_cupos[["sucursal", "generico", "cupo"]].rename(
            columns={"cupo": "objetivo"}
        )
        df_base = df_base.merge(df_cupos_prep, on=["sucursal", "generico"], how="left")
    else:
        df_base["objetivo"] = None

    # -------------------------------------------------------------------------
    # 8. Calcular Tend vs Obj (%)
    # -------------------------------------------------------------------------
    if con_objetivo:
        def _calc_tend_vs_obj(row) -> float | None:
            obj = row.get("objetivo")
            if obj is None or pd.isna(obj) or obj <= 0:
                return None
            return row["tendencia"] / obj

        df_base["tend_vs_obj"] = df_base.apply(_calc_tend_vs_obj, axis=1)
    else:
        df_base["objetivo"] = None
        df_base["tend_vs_obj"] = None

    # -------------------------------------------------------------------------
    # 9. Ordenar y renombrar columnas al formato final
    #    Orden: Sucursal | Generico | DiaN-2 | DiaN-1 | Total Ventas |
    #           Tendencia | MMAA | MA | Objetivo | Tend vs Obj (%)
    # -------------------------------------------------------------------------
    df_base = df_base.sort_values(["sucursal", "generico"]).reset_index(drop=True)

    df_resultado = pd.DataFrame({
        "Sucursal":        df_base["sucursal"],
        "Generico":        df_base["generico"],
        col_n2:            df_base["vtas_n2"],
        col_n1:            df_base["vtas_n1"],
        "Total Ventas":    df_base["total_ventas"],
        "Tendencia":       df_base["tendencia"],
        "MMAA":            df_base["ventas_aa"],
        "MA":              df_base["ventas_ma"],
        "Objetivo":        df_base["objetivo"],
        "Tend vs Obj (%)": df_base["tend_vs_obj"],
    })

    return df_resultado
