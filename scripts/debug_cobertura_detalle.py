"""Debug detallado: comparar query raw vs transformaciones Python."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.data_loader import DataLoader

dl = DataLoader()

# 1. Query directa sin JOIN — valor puro de la tabla
print("=== 1. QUERY DIRECTA SIN JOIN (valor puro de la tabla) ===")
df_raw = dl.execute_query("""
    SELECT ds_sucursal AS sucursal, generico,
           SUM(clientes_compradores) AS total_cc,
           COUNT(*) AS filas
    FROM gold.cob_preventista_generico
    WHERE id_fuerza_ventas = 1
      AND periodo = '2026-03-01'
      AND ds_sucursal = 'CASA CENTRAL'
      AND generico = 'CERVEZAS'
    GROUP BY ds_sucursal, generico
""")
print(df_raw.to_string(index=False))

# 2. Query con LEFT JOIN (como la usa el codigo)
print("\n=== 2. QUERY CON LEFT JOIN dim_vendedor (como la usa el codigo) ===")
df_join = dl.execute_query("""
    SELECT cpg.ds_sucursal AS sucursal, cpg.generico,
           SUM(cpg.clientes_compradores) AS total_cc,
           COUNT(*) AS filas
    FROM gold.cob_preventista_generico cpg
    LEFT JOIN gold.dim_vendedor dv ON cpg.id_vendedor = dv.id_vendedor
    WHERE cpg.id_fuerza_ventas = 1
      AND cpg.periodo = '2026-03-01'
      AND cpg.ds_sucursal = 'CASA CENTRAL'
      AND cpg.generico = 'CERVEZAS'
    GROUP BY cpg.ds_sucursal, cpg.generico
""")
print(df_join.to_string(index=False))

# 3. Verificar duplicados por el JOIN
print("\n=== 3. VENDEDORES CON MULTIPLES FILAS EN dim_vendedor ===")
df_dupes = dl.execute_query("""
    SELECT cpg.id_vendedor, COUNT(DISTINCT dv.des_vendedor) AS nombres_distintos, COUNT(*) AS filas_join
    FROM gold.cob_preventista_generico cpg
    LEFT JOIN gold.dim_vendedor dv ON cpg.id_vendedor = dv.id_vendedor
    WHERE cpg.id_fuerza_ventas = 1
      AND cpg.periodo = '2026-03-01'
      AND cpg.ds_sucursal = 'CASA CENTRAL'
      AND cpg.generico = 'CERVEZAS'
    GROUP BY cpg.id_vendedor
    HAVING COUNT(*) > 1
    ORDER BY filas_join DESC
    LIMIT 20
""")
if df_dupes.empty:
    print("  No hay duplicados por el JOIN")
else:
    print(df_dupes.to_string(index=False))

# 4. Comparar filas antes y despues del join
print("\n=== 4. CONTEO DE FILAS ===")
df_count_raw = dl.execute_query("""
    SELECT COUNT(*) AS filas
    FROM gold.cob_preventista_generico
    WHERE id_fuerza_ventas = 1
      AND periodo = '2026-03-01'
      AND ds_sucursal = 'CASA CENTRAL'
      AND generico = 'CERVEZAS'
""")
df_count_join = dl.execute_query("""
    SELECT COUNT(*) AS filas
    FROM gold.cob_preventista_generico cpg
    LEFT JOIN gold.dim_vendedor dv ON cpg.id_vendedor = dv.id_vendedor
    WHERE cpg.id_fuerza_ventas = 1
      AND cpg.periodo = '2026-03-01'
      AND cpg.ds_sucursal = 'CASA CENTRAL'
      AND cpg.generico = 'CERVEZAS'
""")
print(f"  Sin JOIN: {df_count_raw['filas'].iloc[0]}")
print(f"  Con JOIN: {df_count_join['filas'].iloc[0]}")
diff = df_count_join['filas'].iloc[0] - df_count_raw['filas'].iloc[0]
if diff > 0:
    print(f"  >>> JOIN ESTA DUPLICANDO {diff} FILAS <<<")
else:
    print("  OK: mismo numero de filas")

# 5. Lo que Python ve despues de todo el flujo
print("\n=== 5. RESULTADO FINAL (como lo ve el reporte) ===")
df_full = dl.get_cobertura_preventista_generico(periodos=["2026-03-01"])
from src.core.zonas import aplicar_zonas_virtuales
df_full = aplicar_zonas_virtuales(df_full)
grouped = df_full.groupby(["sucursal", "generico"])["clientes_compradores"].sum().reset_index()
for suc in ["CASA CENTRAL", "VALLE SALTA"]:
    row = grouped[(grouped["sucursal"] == suc) & (grouped["generico"] == "CERVEZAS")]
    if not row.empty:
        print(f"  {suc} + CERVEZAS: {row['clientes_compradores'].values[0]}")
