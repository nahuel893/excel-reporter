#!/usr/bin/env python3
"""Compare ported graficos-cobertura pipeline against standalone tool.

Runs BOTH the standalone (/home/nahuel/projects/work/graficos-cobertura/
generar_graficos.py) and the ported (src.services.graficos_cobertura)
pipelines against the same DB, then diffs DataFrames at every key stage:

1. Raw fetch  — 13 DataFrames from each fetch_data implementation
2. After reassign_rutas_suc1
3. After filtrar_barras_mixtas
4. get_zona_data outputs per (zona, generico)

Prints a concise PASS/FAIL summary. Exits 0 if everything matches.

Usage:
    source .venv/bin/activate
    python scripts/compare_graficos_standalone.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make both packages importable
ROOT_PORTED = Path("/home/nahuel/projects/work/Informes Badie")
ROOT_STANDALONE = Path("/home/nahuel/projects/work/graficos-cobertura")
sys.path.insert(0, str(ROOT_PORTED))
sys.path.insert(0, str(ROOT_STANDALONE))

import pandas as pd  # noqa: E402

# Standalone
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT_PORTED / ".env")  # use the same credentials

import generar_graficos as sa  # noqa: E402

# Ported
from src.services.graficos_cobertura.config import GraficosCoberturaConfig  # noqa: E402
from src.services.graficos_cobertura.service import GraficosCoberturaService  # noqa: E402
from src.services.graficos_cobertura.processor import (  # noqa: E402
    build_gen_marcas_mapping,
    filtrar_barras_mixtas,
    get_zona_data,
    reassign_rutas_suc1,
)
from src.services.graficos_cobertura.constants import (  # noqa: E402
    GENERICOS_INCLUIDOS,
    ZONAS,
)


# ── Config: match standalone defaults ──
SA_ANIO_ACTUAL = sa.ANIO_BARRAS_ACTUAL  # 2026
SA_ANIO_ANTERIOR = sa.ANIO_BARRAS_ANTERIOR  # 2025
SA_MES_CORTE = sa.MES_CORTE_BARRAS  # today's month

CONFIG = GraficosCoberturaConfig(
    fecha_desde=f"{SA_ANIO_ACTUAL}-01-01",
    fecha_hasta=f"{SA_ANIO_ACTUAL}-{SA_MES_CORTE:02d}-28",  # last day of mes_corte approx
    id_fuerza_ventas=sa.FV,
    con_aguas=True,
)


# ── Helpers ──

def _norm(df: pd.DataFrame, sort_cols: list[str]) -> pd.DataFrame:
    """Sort + reindex a DataFrame for order-independent diff."""
    if df.empty:
        return df
    existing = [c for c in sort_cols if c in df.columns]
    if not existing:
        return df.reset_index(drop=True)
    return df.sort_values(existing).reset_index(drop=True)


def compare(
    name: str, df_sa: pd.DataFrame, df_pt: pd.DataFrame, sort_cols: list[str]
) -> bool:
    """Compare two DataFrames. Returns True if they match."""
    a = _norm(df_sa, sort_cols)
    b = _norm(df_pt, sort_cols)

    if a.shape != b.shape:
        print(f"  ❌ {name}: SHAPE differs — standalone {a.shape} vs ported {b.shape}")
        return False
    if list(a.columns) != list(b.columns):
        print(f"  ❌ {name}: COLUMNS differ — SA {list(a.columns)} vs PT {list(b.columns)}")
        return False
    try:
        pd.testing.assert_frame_equal(
            a, b, check_dtype=False, check_exact=False, atol=1e-6
        )
        print(f"  ✅ {name}: {a.shape[0]} rows match")
        return True
    except AssertionError as exc:
        print(f"  ❌ {name}: VALUES differ")
        # Show first few diffs
        diff_mask = ~(a == b).all(axis=1) if a.shape == b.shape else None
        if diff_mask is not None and diff_mask.any():
            diff_rows = diff_mask.sum()
            print(f"     ({diff_rows} row(s) differ)")
            print(f"     Standalone head:\n{a[diff_mask].head(3)}")
            print(f"     Ported head:\n{b[diff_mask].head(3)}")
        return False


# ── Pipeline runners ──

def run_standalone():
    """Run standalone fetch + reassign + filter. Return dict of labeled DataFrames."""
    print("→ Standalone: connecting + fetching...")
    conn = sa.get_connection()
    try:
        data = sa.fetch_data(conn)
    finally:
        conn.close()

    (mapping, df_marca_prev, df_gen_prev,
     df_marca_interior, df_gen_interior,
     df_marca_snorte, df_gen_snorte,
     df_marca_jujuy, df_gen_jujuy,
     df_marca_todas, df_gen_todas,
     df_gen_suc1,
     df_aguas) = data

    raw = {
        "articulos": mapping,
        "marca_prev": df_marca_prev,
        "gen_prev": df_gen_prev,
        "marca_interior": df_marca_interior,
        "gen_interior": df_gen_interior,
        "marca_snorte": df_marca_snorte,
        "gen_snorte": df_gen_snorte,
        "marca_jujuy": df_marca_jujuy,
        "gen_jujuy": df_gen_jujuy,
        "marca_todas": df_marca_todas,
        "gen_todas": df_gen_todas,
        "gen_suc1": df_gen_suc1,
        "aguas": df_aguas,
    }

    # Reassign rutas (replicate standalone's inline logic from generate_charts)
    mask_m = df_marca_prev["id_ruta"].isin(sa.RUTAS_A_SUC16)
    mask_g = df_gen_prev["id_ruta"].isin(sa.RUTAS_A_SUC16)
    reasig_marca = (
        df_marca_prev[mask_m].groupby(["anio", "mes", "marca"])["clientes"].sum().reset_index()
    )
    reasig_gen = (
        df_gen_prev[mask_g].groupby(["anio", "mes", "generico"])["clientes"].sum().reset_index()
    )
    df_marca_prev2 = df_marca_prev[~mask_m].copy()
    df_gen_prev2 = df_gen_prev[~mask_g].copy()
    df_marca_interior2 = (
        pd.concat([df_marca_interior, reasig_marca], ignore_index=True)
        .groupby(["anio", "mes", "marca"])["clientes"].sum().reset_index()
    )
    df_gen_interior2 = (
        pd.concat([df_gen_interior, reasig_gen], ignore_index=True)
        .groupby(["anio", "mes", "generico"])["clientes"].sum().reset_index()
    )

    reassigned = {
        "marca_prev": df_marca_prev2,
        "gen_prev": df_gen_prev2,
        "marca_interior": df_marca_interior2,
        "gen_interior": df_gen_interior2,
    }

    # Filter barras mixtas (standalone's function)
    def _filtrar(df):
        actual = df[(df["anio"] == SA_ANIO_ACTUAL) & (df["mes"] <= SA_MES_CORTE)]
        anterior = df[(df["anio"] == SA_ANIO_ANTERIOR) & (df["mes"] > SA_MES_CORTE)]
        return pd.concat([actual, anterior], ignore_index=True).drop(columns="anio")

    df_marca_prev_f = _filtrar(
        df_marca_prev2.groupby(["anio", "mes", "marca"])["clientes"].sum().reset_index()
    )
    filtered = {
        "marca_prev": df_marca_prev_f,
        "marca_interior": _filtrar(df_marca_interior2),
        "marca_snorte": _filtrar(df_marca_snorte),
        "marca_jujuy": _filtrar(df_marca_jujuy),
        "marca_todas": _filtrar(df_marca_todas),
    }

    gen_marcas = mapping.groupby("generico")["marca"].apply(set).to_dict()
    for subdiv, marcas in sa.SUBDIVISION_AGUAS.items():
        gen_marcas[subdiv] = set(marcas)

    return raw, reassigned, filtered, gen_marcas, df_gen_prev2, df_gen_interior2


def run_ported():
    """Run ported fetch + reassign + filter. Return dict of labeled DataFrames."""
    print("→ Ported: fetching via DataLoader...")
    service = GraficosCoberturaService()
    data = service._fetch_data(CONFIG)

    raw = dict(data)  # shallow copy

    data2 = service._apply_zonas(dict(data))  # reassign_rutas_suc1
    reassigned = {
        "marca_prev": data2["marca_prev"],
        "gen_prev": data2["gen_prev"],
        "marca_interior": data2["marca_interior"],
        "gen_interior": data2["gen_interior"],
    }

    gen_prev_after = data2["gen_prev"]
    gen_interior_after = data2["gen_interior"]

    # Filter (match service's inline loop)
    def _filter(df, aggregate=False):
        if aggregate:
            df = df.groupby(["anio", "mes", "marca"])["clientes"].sum().reset_index()
        return filtrar_barras_mixtas(df, CONFIG.anio_actual, CONFIG.anio_anterior, CONFIG.mes_corte)

    filtered = {
        "marca_prev": _filter(data2["marca_prev"], aggregate=True),
        "marca_interior": _filter(data2["marca_interior"]),
        "marca_snorte": _filter(data2["marca_snorte"]),
        "marca_jujuy": _filter(data2["marca_jujuy"]),
        "marca_todas": _filter(data2["marca_todas"]),
    }

    gen_marcas = build_gen_marcas_mapping(data2["articulos"])

    return raw, reassigned, filtered, gen_marcas, gen_prev_after, gen_interior_after


# ── Main ──

def main() -> int:
    total_checks = 0
    passed = 0

    sa_raw, sa_reassig, sa_filt, sa_gen_marcas, sa_gen_prev, sa_gen_interior = run_standalone()
    pt_raw, pt_reassig, pt_filt, pt_gen_marcas, pt_gen_prev, pt_gen_interior = run_ported()

    print("\n=== STAGE 1: Raw fetch_data ===")
    raw_checks = [
        ("articulos", ["generico", "marca"]),
        ("marca_prev", ["anio", "mes", "id_ruta", "marca"]),
        ("gen_prev", ["anio", "mes", "id_ruta", "generico"]),
        ("marca_interior", ["anio", "mes", "marca"]),
        ("gen_interior", ["anio", "mes", "generico"]),
        ("marca_snorte", ["anio", "mes", "marca"]),
        ("gen_snorte", ["anio", "mes", "generico"]),
        ("marca_jujuy", ["anio", "mes", "marca"]),
        ("gen_jujuy", ["anio", "mes", "generico"]),
        ("marca_todas", ["anio", "mes", "marca"]),
        ("gen_todas", ["anio", "mes", "generico"]),
        ("gen_suc1", ["anio", "mes", "generico"]),
        ("aguas", ["anio", "mes", "id_sucursal", "subdivision_aguas"]),
    ]
    for name, sort_cols in raw_checks:
        total_checks += 1
        if compare(name, sa_raw[name], pt_raw[name], sort_cols):
            passed += 1

    print("\n=== STAGE 2: After reassign_rutas_suc1 ===")
    reassig_checks = [
        ("marca_prev (reassigned)", ["anio", "mes", "id_ruta", "marca"]),
        ("gen_prev (reassigned)", ["anio", "mes", "id_ruta", "generico"]),
        ("marca_interior (reassigned)", ["anio", "mes", "marca"]),
        ("gen_interior (reassigned)", ["anio", "mes", "generico"]),
    ]
    key_map = {
        "marca_prev (reassigned)": "marca_prev",
        "gen_prev (reassigned)": "gen_prev",
        "marca_interior (reassigned)": "marca_interior",
        "gen_interior (reassigned)": "gen_interior",
    }
    for name, sort_cols in reassig_checks:
        key = key_map[name]
        total_checks += 1
        if compare(name, sa_reassig[key], pt_reassig[key], sort_cols):
            passed += 1

    print("\n=== STAGE 3: After filtrar_barras_mixtas ===")
    for key in ["marca_prev", "marca_interior", "marca_snorte", "marca_jujuy", "marca_todas"]:
        total_checks += 1
        if compare(f"{key} (filtered)", sa_filt[key], pt_filt[key], ["mes", "marca"]):
            passed += 1

    print("\n=== STAGE 4: get_zona_data per (zona, generico) ===")
    # Need gen_prev and gen_interior AFTER reassign — use variables from runners
    sa_call_args = dict(
        df_marca_prev=sa_filt["marca_prev"],
        df_gen_prev=sa_gen_prev,
        df_marca_interior=sa_filt["marca_interior"],
        df_gen_interior=sa_gen_interior,
        df_marca_snorte=sa_filt["marca_snorte"],
        df_gen_snorte=sa_raw["gen_snorte"],
        df_marca_jujuy=sa_filt["marca_jujuy"],
        df_gen_jujuy=sa_raw["gen_jujuy"],
        df_marca_todas=sa_filt["marca_todas"],
        df_gen_todas=sa_raw["gen_todas"],
        df_gen_suc1=sa_raw["gen_suc1"],
        df_aguas=sa_raw["aguas"],
    )
    pt_call_args = dict(
        df_marca_prev=pt_filt["marca_prev"],
        df_gen_prev=pt_gen_prev,
        df_marca_interior=pt_filt["marca_interior"],
        df_gen_interior=pt_gen_interior,
        df_marca_snorte=pt_filt["marca_snorte"],
        df_gen_snorte=pt_raw["gen_snorte"],
        df_marca_jujuy=pt_filt["marca_jujuy"],
        df_gen_jujuy=pt_raw["gen_jujuy"],
        df_marca_todas=pt_filt["marca_todas"],
        df_gen_todas=pt_raw["gen_todas"],
        df_gen_suc1=pt_raw["gen_suc1"],
        df_aguas=pt_raw["aguas"],
    )

    for zona in ZONAS:
        for generico in GENERICOS_INCLUIDOS:
            if generico not in sa_gen_marcas or generico not in pt_gen_marcas:
                continue

            # Standalone call uses positional args + different param order
            sa_bars, sa_gen = sa.get_zona_data(
                zona, sa_gen_marcas, generico,
                sa_call_args["df_marca_prev"], sa_call_args["df_gen_prev"],
                sa_call_args["df_marca_interior"], sa_call_args["df_gen_interior"],
                sa_call_args["df_marca_snorte"], sa_call_args["df_gen_snorte"],
                sa_call_args["df_marca_jujuy"], sa_call_args["df_gen_jujuy"],
                sa_call_args["df_marca_todas"], sa_call_args["df_gen_todas"],
                sa_call_args["df_gen_suc1"], sa_call_args["df_aguas"],
            )
            pt_bars, pt_gen = get_zona_data(
                zona=zona, generico=generico, gen_marcas=pt_gen_marcas, **pt_call_args,
            )

            pair = f"{zona} / {generico}"
            total_checks += 2
            if compare(f"[{pair}] df_bars", sa_bars, pt_bars, ["mes", "marca"]):
                passed += 1
            if compare(f"[{pair}] df_gen", sa_gen, pt_gen, ["anio", "mes"]):
                passed += 1

    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {passed}/{total_checks} checks passed")
    print(f"{'=' * 60}")
    return 0 if passed == total_checks else 1


if __name__ == "__main__":
    sys.exit(main())
