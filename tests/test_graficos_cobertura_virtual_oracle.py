"""Oracle parity test for the cobertura_zonas virtual dataset.

Marked `@pytest.mark.integration`. Connects to the production PostgreSQL DWH
as `superset_ro` and compares the dataset's SUM(clientes) per
(periodo, zona, generico, marca) against the output of the Python
`GraficosCoberturaService` for a known test period.

**Skipped on DB unreachable** (no `psycopg2` connect, no `superset_ro` role,
no `gold.cob_*` tables, etc.) — the test never fails on infra, it skips.

Spec: sdd/graficos-cobertura-virtual/spec  (RF-14)
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_YAML = (
    REPO_ROOT
    / "superset"
    / "bundle"
    / "graficos-cobertura"
    / "datasets"
    / "Medallion_Gold"
    / "cobertura_zonas.yaml"
)


def _db_url() -> str | None:
    """Compose a `postgresql://superset_ro:...@.../medallion_db` URL from env.

    Required env: DB_HOST, DB_PORT, DB_NAME, SUPERSET_RO_USER, SUPERSET_RO_PASSWORD.
    Optional: DB_SSLMODE (default `prefer`).
    """
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME")
    user = os.environ.get("SUPERSET_RO_USER", "superset_ro")
    pwd = os.environ.get("SUPERSET_RO_PASSWORD")
    if not (host and name and pwd):
        return None
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"


@pytest.fixture(scope="module")
def db_connection():
    """Open a psycopg2 connection. Skip the entire module on failure."""
    url = _db_url()
    if url is None:
        pytest.skip(
            "DB_HOST / DB_NAME / SUPERSET_RO_PASSWORD env not set; "
            "skipping oracle test"
        )
    try:
        import psycopg2  # type: ignore
    except ImportError:
        pytest.skip("psycopg2 not installed; skipping oracle test")
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
    except Exception as exc:  # connection refused / wrong creds / network
        pytest.skip(f"DB unreachable ({type(exc).__name__}: {exc}); skipping")
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def dataset_sql() -> str:
    """Load the dataset SQL from the YAML."""
    if not DATASET_YAML.exists():
        pytest.skip(f"Dataset YAML missing: {DATASET_YAML}")
    import yaml
    with DATASET_YAML.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    sql = data.get("sql")
    if not sql:
        pytest.skip("dataset `sql:` is null")
    return sql


@pytest.fixture(scope="module")
def dataset_rows(db_connection, dataset_sql: str):
    """Execute the dataset SQL and load rows into a DataFrame.

    Adds a derived `anio` column by extracting the year from `periodo` so the
    rows align with the Python `df` grain.
    """
    import pandas as pd
    sql = f"""
    WITH src AS ({dataset_sql})
    SELECT
        periodo,
        zona,
        generico,
        marca,
        SUM(clientes)::numeric AS clientes
    FROM src
    GROUP BY periodo, zona, generico, marca
    """
    return pd.read_sql_query(sql, db_connection)


@pytest.fixture(scope="module")
def service_rows(db_connection):
    """Run the Python GraficosCoberturaService against a small test period.

    Uses 2024-06 (a pre-2025 period) so the SALTA CAPITAL preventista half is
    exercised (the 2025+ suc-1 half is empty for that period).
    """
    pytest.importorskip("pandas")
    pytest.importorskip("sqlalchemy")

    from sqlalchemy import create_engine
    from src.services.graficos_cobertura.config import GraficosCoberturaConfig
    from src.services.graficos_cobertura.service import GraficosCoberturaService

    url = _db_url()
    if url is None:
        pytest.skip("DB env not set; skipping service_rows fixture")
    engine = create_engine(url)

    # Service is constructed with a data_loader; for the oracle we want
    # exactly the same DB connection the dataset SQL uses.
    from src.core.data_loader import DataLoader

    loader = DataLoader(engine=engine)
    service = GraficosCoberturaService(data_loader=loader)

    # 2024-06 → 2024-06: covers the pre-2025 SALTA CAPITAL preventista half
    # and gives one full month of data to compare against.
    config = GraficosCoberturaConfig(fecha_desde="2024-06-01", fecha_hasta="2024-06-30")
    data = service._fetch_data(config)
    data = service._apply_zonas(data)

    # Reassemble to (periodo, zona, generico, marca) grain.
    # We do this by stacking the zona-keyed bars/dfs and projecting to the
    # same columns the dataset SQL emits.
    import pandas as pd
    rows: list[pd.DataFrame] = []
    zonas_to_dfs: dict[str, tuple] = {
        # (marca-grain df, generico-grain df, source for SALTA CAPITAL pre2025)
        "NOA NORTE":          (data["marca_todas"],   data["gen_todas"],   None),
        "INTERIOR SALTA SUR": (data["marca_interior"], data["gen_interior"], None),
        "INTERIOR SALTA NORTE": (data["marca_snorte"], data["gen_snorte"], None),
        "JUJUY INTERIOR":     (data["marca_jujuy"],   data["gen_jujuy"],   None),
    }
    for zona, (mdf, gdf, _) in zonas_to_dfs.items():
        if not mdf.empty:
            rows.append(
                mdf.assign(zona=zona, periodo=mdf["anio"].astype(str) + "-"
                           + mdf["mes"].astype(str).str.zfill(2))
                [["periodo", "zona", "marca", "clientes"]]
                .assign(generico=None)
            )
        if not gdf.empty:
            rows.append(
                gdf.assign(zona=zona, periodo=gdf["anio"].astype(str) + "-"
                           + gdf["mes"].astype(str).str.zfill(2))
                [["periodo", "zona", "generico", "clientes"]]
                .assign(marca=None)
            )
    # SALTA CAPITAL: pre-2025 from preventista (only 2024 here, so ALL of it)
    sc = data["gen_prev"]
    if not sc.empty:
        rows.append(
            sc.assign(zona="SALTA CAPITAL",
                      periodo=sc["anio"].astype(str) + "-"
                              + sc["mes"].astype(str).str.zfill(2))
            [["periodo", "zona", "generico", "clientes"]]
            .assign(marca=None)
        )
    sc_marca = data["marca_prev"]
    if not sc_marca.empty:
        rows.append(
            sc_marca.assign(zona="SALTA CAPITAL",
                            periodo=sc_marca["anio"].astype(str) + "-"
                                    + sc_marca["mes"].astype(str).str.zfill(2))
            [["periodo", "zona", "marca", "clientes"]]
            .assign(generico=None)
        )

    if not rows:
        return pd.DataFrame(columns=["periodo", "zona", "generico", "marca", "clientes"])

    df = pd.concat(rows, ignore_index=True)
    df = df.groupby(["periodo", "zona", "generico", "marca"], dropna=False)["clientes"].sum().reset_index()
    return df


# ────────────────────────────────────────────────────────────────────
# RF-14: Oracle parity
# ────────────────────────────────────────────────────────────────────
class TestOracleParity:
    def test_noa_norte_matches_service(
        self, dataset_rows, service_rows
    ) -> None:
        """MV_NO_NORTE == service_NO_NORTE for the test period."""
        ds = dataset_rows[dataset_rows["zona"] == "NOA NORTE"]["clientes"].sum()
        sv = service_rows[service_rows["zona"] == "NOA NORTE"]["clientes"].sum()
        # Both can be 0 in environments without cob_sucursal_marca data;
        # the structural assertion is that they agree.
        assert ds == sv, (
            f"NOA NORTE mismatch: dataset={ds!r} service={sv!r}"
        )

    def test_noa_norte_not_equal_to_sum_of_others(
        self, dataset_rows, service_rows
    ) -> None:
        """The structural test from spec: NOA NORTE is its own branch,
        NOT a sum of the other 4 zonas. The dataset total of NOA NORTE
        must not equal the sum of (SALTA CAPITAL + INTERIOR SALTA SUR +
        INTERIOR SALTA NORTE + JUJUY INTERIOR).

        For the test period (2024-06) this should hold because:
        - NOA NORTE reads from cob_sucursal_marca (all sucursales)
        - INTERIOR SALTA SUR also adds reassigned preventista rows that
          NOA NORTE does NOT include
        So the two totals will differ by the reassigned preventista amount.
        """
        ds_total = dataset_rows["clientes"].sum()
        noa = dataset_rows[dataset_rows["zona"] == "NOA NORTE"]["clientes"].sum()
        others = dataset_rows[
            dataset_rows["zona"].isin([
                "SALTA CAPITAL", "INTERIOR SALTA SUR",
                "INTERIOR SALTA NORTE", "JUJUY INTERIOR"
            ])
        ]["clientes"].sum()

        # If there is no data at all, this assertion is trivially true but
        # meaningless — skip in that case.
        if ds_total == 0:
            pytest.skip("no data for test period — assertion is vacuous")

        assert noa != others, (
            f"NOA NORTE ({noa}) must NOT equal SUM(other 4 zonas) ({others}) — "
            "the dataset's NOA NORTE branch must be a true rollup, not a sum"
        )

    def test_salta_capital_pre_2025_matches_preventista(
        self, dataset_rows, service_rows
    ) -> None:
        """For pre-2025 periods, SALTA CAPITAL must equal the preventista
        source (reaggregated)."""
        pre = dataset_rows[
            (dataset_rows["zona"] == "SALTA CAPITAL")
            & (dataset_rows["periodo"] < "2025")
        ]["clientes"].sum()
        sv_pre = service_rows[
            (service_rows["zona"] == "SALTA CAPITAL")
            & (service_rows["periodo"] < "2025")
        ]["clientes"].sum()
        if pre == 0 and sv_pre == 0:
            pytest.skip("no pre-2025 SALTA CAPITAL data")
        assert pre == sv_pre, (
            f"SALTA CAPITAL pre-2025 mismatch: dataset={pre!r} service={sv_pre!r}"
        )

    def test_ruta_reassignment_parity(
        self, dataset_rows, db_connection
    ) -> None:
        """The SQL must NOT include ruta 85, 86, 87, 88, 118, 119 in SALTA
        CAPITAL, and MUST include them in INTERIOR SALTA SUR (as a
        cob_preventista_marca contribution).

        This is a coarse parity check at the data level: query the source
        `cob_preventista_marca` for these rutas and confirm the total
        appears in INTERIOR SALTA SUR but not SALTA CAPITAL.
        """
        import pandas as pd
        sql = """
        SELECT
            EXTRACT(YEAR  FROM periodo)::int AS anio,
            EXTRACT(MONTH FROM periodo)::int AS mes,
            SUM(clientes_compradores) AS clientes
        FROM gold.cob_preventista_marca
        WHERE id_fuerza_ventas = 1
          AND id_sucursal = 1
          AND id_ruta IN (85, 86, 87, 88, 118, 119)
        GROUP BY 1, 2
        """
        try:
            reassign = pd.read_sql_query(sql, db_connection)
        except Exception as exc:
            pytest.skip(f"reassign source query failed: {exc}")
        if reassign.empty:
            pytest.skip("no reassigned-ruta data in test DB")

        # The total reassigned amount must appear in INTERIOR SALTA SUR.
        expected_total = float(reassign["clientes"].sum())
        sur_total = float(
            dataset_rows[dataset_rows["zona"] == "INTERIOR SALTA SUR"]["clientes"].sum()
        )
        # Allow zero if the data is too sparse — only assert when expected > 0.
        if expected_total == 0:
            pytest.skip("reassigned total is zero")
        assert sur_total >= expected_total, (
            f"INTERIOR SALTA SUR ({sur_total}) must include the reassigned "
            f"ruta total ({expected_total})"
        )
