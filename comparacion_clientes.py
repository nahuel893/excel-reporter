"""
Comparación de clientes - CERVEZAS.

Script standalone que genera un Excel comparando la venta en bultos
de cada cliente para Enero y Febrero 2025 vs 2026.

Hojas:
  - Comparacion Clientes: bultos vendidos + bonificaciones + variación + estado
  - Por Lista Precio: resumen agrupado por lista de precio
  - Por Preventista: resumen agrupado por preventista
  - Por Ruta: resumen agrupado por ruta

Uso:
    python comparacion_clientes.py
    python comparacion_clientes.py --sucursales "CASA CENTRAL,SUCURSAL CAFAYATE"
"""
import argparse

import pandas as pd

from openpyxl.formatting.rule import IconSet, FormatObject, IconSetRule
from openpyxl.utils import get_column_letter

from src.core.data_loader import DataLoader
from src.core.excel_writer import ExcelWriter, SheetStyle, ColumnFormat

GENERICO = "CERVEZAS"
CLIENTES_XLSX = "/home/nahuel/VM shared/clientes.xlsx"

PERIODOS = {
    "Ene 2025": ("2025-01-01", "2025-01-31"),
    "Ene 2026": ("2026-01-01", "2026-01-31"),
    "Feb 2025": ("2025-02-01", "2025-02-28"),
    "Feb 2026": ("2026-02-01", "2026-02-28"),
}


def get_clientes(loader: DataLoader) -> pd.DataFrame:
    """Obtiene clientes que tuvieron ventas de CERVEZAS en alguno de los 4 períodos."""
    params = {
        "generico": GENERICO,
        "desde_1": "2025-01-01", "hasta_1": "2025-01-31",
        "desde_2": "2025-02-01", "hasta_2": "2025-02-28",
        "desde_3": "2026-01-01", "hasta_3": "2026-01-31",
        "desde_4": "2026-02-01", "hasta_4": "2026-02-28",
    }

    query = """
    SELECT DISTINCT
        fv.id_cliente,
        fv.id_sucursal
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
    WHERE fv.id_sucursal = 1
      AND da.generico = :generico
      AND (
          fv.fecha_comprobante BETWEEN :desde_1 AND :hasta_1
          OR fv.fecha_comprobante BETWEEN :desde_2 AND :hasta_2
          OR fv.fecha_comprobante BETWEEN :desde_3 AND :hasta_3
          OR fv.fecha_comprobante BETWEEN :desde_4 AND :hasta_4
      )
    ORDER BY fv.id_cliente
    """
    return loader.execute_query(query, params)


def cargar_datos_clientes() -> pd.DataFrame:
    """Carga datos de clientes desde el Excel externo (ruta, preventista, subcanal, etc.)."""
    df = pd.read_excel(CLIENTES_XLSX)
    df = df.rename(columns={
        "Sucursal": "id_sucursal",
        "Cliente": "id_cliente",
        "Razon social": "razon_social",
        "Subcanal": "id_subcanal",
        "Descripcion subcanal": "subcanal",
        "Lista de precios": "id_lista_precio",
        "Descripcion lista de precios": "desc_lista_precio",
        "Fuerza de venta 1 Ruta de venta": "id_ruta",
        "Fuerza de venta 1 Descripcion ruta de venta": "desc_ruta",
        "Fuerza de venta 1 Personal comercial": "id_preventista",
        "Fuerza de venta 1 Descripcion personal comercial": "preventista",
    })
    # Convertir claves a float para que matcheen con la BD
    df["id_cliente"] = pd.to_numeric(df["id_cliente"], errors="coerce")
    df["id_sucursal"] = pd.to_numeric(df["id_sucursal"], errors="coerce")
    # Quedarme con las columnas útiles
    cols = ["id_sucursal", "id_cliente", "razon_social", "subcanal",
            "id_lista_precio", "desc_lista_precio", "id_ruta", "desc_ruta",
            "id_preventista", "preventista"]
    return df[cols]


def get_ventas_periodo(loader: DataLoader, fecha_desde: str, fecha_hasta: str) -> pd.DataFrame:
    """Obtiene bultos vendidos por cliente en un período para CERVEZAS."""
    params = {"desde": fecha_desde, "hasta": fecha_hasta, "generico": GENERICO}

    query = """
    SELECT
        fv.id_cliente,
        fv.id_sucursal,
        SUM(fv.cantidades_total) AS bultos
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
    WHERE fv.id_sucursal = 1
      AND fv.fecha_comprobante BETWEEN :desde AND :hasta
      AND da.generico = :generico
    GROUP BY fv.id_cliente, fv.id_sucursal
    """
    return loader.execute_query(query, params)


def get_bonificaciones_periodo(loader: DataLoader, fecha_desde: str, fecha_hasta: str) -> pd.DataFrame:
    """Obtiene bultos bonificados por cliente en un período para CERVEZAS.

    Calcula: SUM(cantidades_total * bonificacion / 100) por cliente.
    """
    params = {"desde": fecha_desde, "hasta": fecha_hasta, "generico": GENERICO}

    query = """
    SELECT
        fv.id_cliente,
        fv.id_sucursal,
        SUM(fv.cantidades_total * fv.bonificacion / 100.0) AS bultos_bonificados
    FROM gold.fact_ventas fv
    LEFT JOIN gold.dim_articulo da ON fv.id_articulo = da.id_articulo
    WHERE fv.id_sucursal = 1
      AND fv.fecha_comprobante BETWEEN :desde AND :hasta
      AND da.generico = :generico
      AND fv.bonificacion > 0
    GROUP BY fv.id_cliente, fv.id_sucursal
    """
    return loader.execute_query(query, params)


def generar_comparacion(sucursales: list[str] | None = None) -> str:
    """Genera el reporte de comparación de clientes."""
    loader = DataLoader()

    # 1. Obtener clientes con ventas desde la BD
    df_clientes = get_clientes(loader)
    print(f"Clientes con ventas: {len(df_clientes)}")

    # 2. Traer campo anulado de dim_cliente
    df_anulado = loader.execute_query("""
        SELECT id_cliente, id_sucursal, anulado
        FROM gold.dim_cliente
        WHERE id_sucursal = 1
    """)
    df_clientes = df_clientes.merge(df_anulado, on=["id_cliente", "id_sucursal"], how="left")

    # 3. Cruzar con datos del Excel (ruta, preventista, subcanal, etc.)
    df_xlsx = cargar_datos_clientes()
    df_xlsx = df_xlsx.dropna(subset=["id_cliente", "id_sucursal"])
    df_xlsx["id_cliente"] = df_xlsx["id_cliente"].astype(int)
    df_xlsx["id_sucursal"] = df_xlsx["id_sucursal"].astype(int)
    df_clientes = df_clientes.merge(df_xlsx, on=["id_cliente", "id_sucursal"], how="left")
    print(f"Clientes tras cruce con Excel: {len(df_clientes)}")

    # 3. Obtener ventas por período
    df_base = df_clientes.copy()

    for nombre_periodo, (desde, hasta) in PERIODOS.items():
        df_ventas = get_ventas_periodo(loader, desde, hasta)
        df_base = df_base.merge(
            df_ventas.rename(columns={"bultos": nombre_periodo}),
            on=["id_cliente", "id_sucursal"],
            how="left",
        )
        df_base[nombre_periodo] = df_base[nombre_periodo].fillna(0)

    # 4. Obtener bonificaciones por período
    for nombre_periodo, (desde, hasta) in PERIODOS.items():
        df_b = get_bonificaciones_periodo(loader, desde, hasta)
        col_bonif = f"Bonif {nombre_periodo}"
        df_base = df_base.merge(
            df_b.rename(columns={"bultos_bonificados": col_bonif}),
            on=["id_cliente", "id_sucursal"],
            how="left",
        )
        df_base[col_bonif] = df_base[col_bonif].fillna(0)
        # % Bonificación sobre venta
        df_base[f"% Bonif {nombre_periodo}"] = df_base[col_bonif] / df_base[nombre_periodo].replace(0, None)

    # 5. Columnas calculadas - Ventas
    df_base["Var Ene"] = df_base["Ene 2026"] - df_base["Ene 2025"]
    df_base["Var Feb"] = df_base["Feb 2026"] - df_base["Feb 2025"]
    df_base["% Var Ene"] = df_base.apply(
        lambda r: (r["Ene 2026"] / r["Ene 2025"] - 1) if r["Ene 2025"] != 0 else None, axis=1
    )
    df_base["% Var Feb"] = df_base.apply(
        lambda r: (r["Feb 2026"] / r["Feb 2025"] - 1) if r["Feb 2025"] != 0 else None, axis=1
    )

    # Estado Enero: compró en Ene 2026 vs Ene 2025
    compro_ene_25 = df_base["Ene 2025"] > 0
    compro_ene_26 = df_base["Ene 2026"] > 0
    df_base["Estado Ene"] = ""
    df_base.loc[compro_ene_26 & ~compro_ene_25, "Estado Ene"] = "NUEVO"
    df_base.loc[compro_ene_25 & ~compro_ene_26, "Estado Ene"] = "PERDIDO"
    df_base.loc[compro_ene_25 & compro_ene_26, "Estado Ene"] = "MANTIENE"

    # Estado Febrero: compró en Feb 2026 vs Feb 2025
    compro_feb_25 = df_base["Feb 2025"] > 0
    compro_feb_26 = df_base["Feb 2026"] > 0
    df_base["Estado Feb"] = ""
    df_base.loc[compro_feb_26 & ~compro_feb_25, "Estado Feb"] = "NUEVO"
    df_base.loc[compro_feb_25 & ~compro_feb_26, "Estado Feb"] = "PERDIDO"
    df_base.loc[compro_feb_25 & compro_feb_26, "Estado Feb"] = "MANTIENE"

    # 6. Resúmenes agrupados
    cols_periodo = list(PERIODOS.keys())

    def resumen_por(df, col_grupo):
        agg = df.groupby(col_grupo, dropna=False)[cols_periodo].sum().reset_index()
        for p in ["Ene", "Feb"]:
            agg[f"Var {p}"] = agg[f"{p} 2026"] - agg[f"{p} 2025"]
            agg[f"% Var {p}"] = agg[f"{p} 2026"] / agg[f"{p} 2025"].replace(0, None) - 1
        agg["Clientes"] = df.groupby(col_grupo, dropna=False)["id_cliente"].nunique().values
        return agg

    df_por_lista = resumen_por(df_base, "desc_lista_precio")
    df_por_preventista = resumen_por(df_base, "preventista")
    df_por_ruta = resumen_por(df_base, "desc_ruta")

    # 8. Sacar columnas internas (solo se usan para joins)
    cols_drop = ["id_sucursal", "id_subcanal", "id_preventista"]
    df_base = df_base.drop(columns=[c for c in cols_drop if c in df_base.columns])

    # 9. Generar Excel
    pct_fmt = ColumnFormat(number_format='0.00%')
    pct_cols = {"% Var Ene": pct_fmt, "% Var Feb": pct_fmt}
    pct_cols.update({f"% Bonif {p}": pct_fmt for p in PERIODOS})

    style_ventas = SheetStyle(
        numeric_format="#,##0",
        as_table=True,
        table_style="TableStyleMedium9",
        column_formats=pct_cols,
    )

    style_resumen = SheetStyle(
        numeric_format="#,##0",
        as_table=True,
        table_style="TableStyleMedium9",
        column_formats={
            "% Var Ene": pct_fmt,
            "% Var Feb": pct_fmt,
        },
    )

    writer = ExcelWriter("Comparacion Clientes CERVEZAS")
    writer.add_sheet(df_base, sheet_name="Comparacion Clientes", style=style_ventas)
    writer.add_sheet(df_por_lista, sheet_name="Por Lista Precio", style=style_resumen)
    writer.add_sheet(df_por_preventista, sheet_name="Por Preventista", style=style_resumen)
    writer.add_sheet(df_por_ruta, sheet_name="Por Ruta", style=style_resumen)

    # 10. Formato condicional semáforo en columnas de %
    def agregar_semaforo(ws, df, col_nombres):
        headers = list(df.columns)
        for col_name in col_nombres:
            if col_name not in headers:
                continue
            col_idx = headers.index(col_name) + 1
            col_letter = get_column_letter(col_idx)
            rango = f"{col_letter}2:{col_letter}{len(df) + 1}"
            rule = IconSetRule(
                icon_style="3TrafficLights1",
                type="num",
                values=[-0.1, 0, 0.1],
                showValue=True,
                reverse=False,
            )
            ws.conditional_formatting.add(rango, rule)

    wb = writer.workbook
    cols_semaforo = ["% Var Ene", "% Var Feb"] + [f"% Bonif {p}" for p in PERIODOS]
    agregar_semaforo(wb["Comparacion Clientes"], df_base, cols_semaforo)
    agregar_semaforo(wb["Por Lista Precio"], df_por_lista, ["% Var Ene", "% Var Feb"])
    agregar_semaforo(wb["Por Preventista"], df_por_preventista, ["% Var Ene", "% Var Feb"])
    agregar_semaforo(wb["Por Ruta"], df_por_ruta, ["% Var Ene", "% Var Feb"])

    ruta = writer.save()

    print(f"Reporte generado: {ruta}")
    return str(ruta)


def main():
    parser = argparse.ArgumentParser(description="Comparación de clientes CERVEZAS")
    parser.add_argument(
        "--sucursales",
        type=str,
        default=None,
        help="Sucursales separadas por coma (ej: 'CASA CENTRAL,SUCURSAL CAFAYATE')",
    )
    args = parser.parse_args()

    sucursales = None
    if args.sucursales:
        sucursales = [s.strip() for s in args.sucursales.split(",")]

    generar_comparacion(sucursales)


if __name__ == "__main__":
    main()
