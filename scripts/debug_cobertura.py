"""Debug: verificar split de cobertura CASA CENTRAL / VALLE SALTA."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.data_loader import DataLoader
from src.core.zonas import aplicar_zonas_virtuales
from config.settings import ZONAS_VIRTUALES

dl = DataLoader()
df = dl.get_cobertura_preventista_generico(periodos=["2026-03-01"])

print("=== ANTES del split ===")
mask_cc = (df["sucursal"] == "CASA CENTRAL") & (df["generico"] == "CERVEZAS")
print(f"CASA CENTRAL + CERVEZAS:")
print(f"  Filas: {mask_cc.sum()}")
print(f"  Total clientes_compradores: {df.loc[mask_cc, 'clientes_compradores'].sum()}")
rutas_cc = sorted(df.loc[mask_cc, "id_ruta"].unique())
print(f"  Rutas ({len(rutas_cc)}): {rutas_cc}")

rutas_valle = ZONAS_VIRTUALES["VALLE SALTA"]["rutas"]
rutas_en_valle = [r for r in rutas_cc if r in rutas_valle]
rutas_no_valle = [r for r in rutas_cc if r not in rutas_valle]
print(f"\n  Rutas que van a VALLE SALTA ({len(rutas_en_valle)}): {rutas_en_valle}")
print(f"  Rutas que quedan en CASA CENTRAL ({len(rutas_no_valle)}): {rutas_no_valle}")

mask_valle_pre = mask_cc & df["id_ruta"].isin(rutas_valle)
mask_cc_pre = mask_cc & ~df["id_ruta"].isin(rutas_valle)
print(f"\n  clientes_compradores VALLE SALTA (pre-split): {df.loc[mask_valle_pre, 'clientes_compradores'].sum()}")
print(f"  clientes_compradores CASA CENTRAL (pre-split): {df.loc[mask_cc_pre, 'clientes_compradores'].sum()}")

df2 = aplicar_zonas_virtuales(df)

print("\n=== DESPUES del split ===")
for suc in ["CASA CENTRAL", "VALLE SALTA"]:
    mask = (df2["sucursal"] == suc) & (df2["generico"] == "CERVEZAS")
    print(f"{suc} + CERVEZAS:")
    print(f"  Filas: {mask.sum()}")
    print(f"  Total clientes_compradores: {df2.loc[mask, 'clientes_compradores'].sum()}")

print("\n=== AGRUPADO (como lo usa el reporte) ===")
grouped = df2.groupby(["sucursal", "generico"])["clientes_compradores"].sum().reset_index()
for suc in ["CASA CENTRAL", "VALLE SALTA"]:
    row = grouped[(grouped["sucursal"] == suc) & (grouped["generico"] == "CERVEZAS")]
    if not row.empty:
        print(f"{suc} + CERVEZAS: {row['clientes_compradores'].values[0]}")
    else:
        print(f"{suc} + CERVEZAS: (no data)")
