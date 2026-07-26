"""Structural assertions for the cobertura_zonas virtual dataset YAML.

Parses `superset/bundle/graficos-cobertura/datasets/Medallion_Gold/cobertura_zonas.yaml`
and validates the contracts defined in RF-01..RF-10. No database required.

Spec: sdd/graficos-cobertura-virtual/spec
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


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

DB_UUID = "a842c321-6955-4eea-9c30-01824a8d0039"

# Zona labels (must each appear as a literal in the SQL)
ZONAS = [
    "NOA NORTE",
    "SALTA CAPITAL",
    "INTERIOR SALTA SUR",
    "INTERIOR SALTA NORTE",
    "JUJUY INTERIOR",
]

# Whitelist (must each appear as a literal in the SQL)
GENERICOS = [
    "CERVEZAS",
    "AGUAS SABORIZADAS",
    "AGUAS MINERAL",
    "SIDRAS Y LICORES",
    "VINOS CCU",
]

# AGUAS subdivision mapping tokens
AGUAS_MARCA_TOKENS = [
    "LEVITE",
    "SER",
    "BRIO",
    "FULL SPORT",
    "VILLA DEL SUR",
    "VILLAVICENCIO",
]

# Regex matching a multi-element `col IN ('a', 'b', ...)` clause and capturing
# the inner CSV of single-quoted literals.
IN_CLAUSE_RE = re.compile(
    r"""\b([A-Za-z_][A-Za-z0-9_]*)\s+IN\s*\(\s*         # col IN (
        ((?:'[^']+'\s*,\s*)*'[^']+')\s*                # captured: 'a', 'b', ..., 'z'
    \)""",
    re.IGNORECASE | re.VERBOSE,
)


def _split_csv_quoted(literal_csv: str) -> list[str]:
    """Parse `'a', 'b', 'c'` → `['a', 'b', 'c']`."""
    return [s.strip().strip("'") for s in literal_csv.split(",")]


@pytest.fixture(scope="module")
def dataset_yaml() -> dict:
    """Load the dataset YAML once per module."""
    assert DATASET_YAML.exists(), (
        f"Dataset YAML missing: {DATASET_YAML}. "
        "Create the file before running this test (see T-A.3)."
    )
    with DATASET_YAML.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def dataset_sql(dataset_yaml: dict) -> str:
    sql = dataset_yaml.get("sql")
    assert sql is not None, "dataset `sql:` is null — virtual dataset must have inline SQL"
    assert isinstance(sql, str) and sql.strip(), "dataset `sql:` must be a non-empty string"
    return sql


# ────────────────────────────────────────────────────────────────────
# RF-01: Virtual dataset YAML contract
# ────────────────────────────────────────────────────────────────────
class TestRF01VirtualDatasetContract:
    def test_table_name(self, dataset_yaml: dict) -> None:
        assert dataset_yaml["table_name"] == "cobertura_zonas"

    def test_schema(self, dataset_yaml: dict) -> None:
        assert dataset_yaml["schema"] == "gold"

    def test_database_uuid(self, dataset_yaml: dict) -> None:
        assert dataset_yaml["database_uuid"] == DB_UUID

    def test_uuid_is_well_formed(self, dataset_yaml: dict) -> None:
        assert re.fullmatch(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            dataset_yaml["uuid"],
        ), f"UUID malformed: {dataset_yaml['uuid']}"

    def test_uuid_is_unique_across_bundle(
        self, dataset_yaml: dict
    ) -> None:
        """No other file in the bundle reuses this dataset's `uuid` field.

        Charts and dashboards reference the dataset via `dataset_uuid` (which
        is the same value as the dataset's `uuid`) — that's a normal pointer,
        not a duplicate.  We only check the asset's own `uuid` key.
        """
        my_uuid = dataset_yaml["uuid"]
        bundle_root = REPO_ROOT / "superset" / "bundle"
        if not bundle_root.exists():
            pytest.skip("bundle root not present")
        offenders: list[Path] = []
        for yaml_path in bundle_root.rglob("*.yaml"):
            if yaml_path == DATASET_YAML:
                continue
            try:
                with yaml_path.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("uuid") == my_uuid:
                offenders.append(yaml_path)
        assert offenders == [], (
            f"UUID {my_uuid} reused in: {[str(p) for p in offenders]}"
        )


# ────────────────────────────────────────────────────────────────────
# RF-02: Output shape (column contract)
# ────────────────────────────────────────────────────────────────────
class TestRF02OutputShape:
    def test_required_columns_present_and_filterable(self, dataset_yaml: dict) -> None:
        cols_by_name = {c["column_name"]: c for c in dataset_yaml["columns"]}
        for required in ("periodo", "zona", "generico", "marca"):
            assert required in cols_by_name, f"missing column: {required}"
            col = cols_by_name[required]
            assert col.get("groupby") is True
            assert col.get("filterable") is True

    def test_metrics_exposes_sum_clientes(self, dataset_yaml: dict) -> None:
        metric_names = [m["metric_name"] for m in dataset_yaml["metrics"]]
        assert "sum_clientes" in metric_names, (
            f"sum_clientes metric not declared (got: {metric_names})"
        )
        m = next(m for m in dataset_yaml["metrics"] if m["metric_name"] == "sum_clientes")
        assert m["expression"].upper().replace(" ", "") == "SUM(CLIENTES)"
        assert m["d3format"] == ",.0f"


# ────────────────────────────────────────────────────────────────────
# RF-03: 5 ramas (UNION ALL branches, structural)
# ────────────────────────────────────────────────────────────────────
class TestRF03UnionAllBranches:
    def test_no_grouping_sets_rollup_cube(self, dataset_sql: str) -> None:
        for forbidden in (r"GROUPING\s+SETS", r"\bROLLUP\s*\(", r"\bCUBE\s*\("):
            assert not re.search(forbidden, dataset_sql, re.IGNORECASE), (
                f"forbidden token present: {forbidden}"
            )

    def test_at_least_four_union_all_tokens(self, dataset_sql: str) -> None:
        """5 ramas (zones) → at least 4 outer UNION ALLs.

        Internal UNION ALLs in CTEs (e.g. SALTA CAPITAL splice, INTERIOR SALTA
        SUR multi-source) push the count above 4 — that's allowed.  The lower
        bound is what guards against someone deleting one of the 5 zonas.
        """
        matches = re.findall(r"\bUNION\s+ALL\b", dataset_sql, re.IGNORECASE)
        assert len(matches) >= 4, (
            f"expected at least 4 UNION ALL tokens (one per outer connection), "
            f"got {len(matches)}: {matches}"
        )

    def test_five_rama_ctes(self, dataset_sql: str) -> None:
        """Exactly 5 rama_X AS (...) CTEs."""
        ramas = re.findall(
            r"\brama_([A-Za-z_]+)\s+AS\b", dataset_sql, re.IGNORECASE
        )
        # unique, in canonical order
        unique = list(dict.fromkeys(ramas))
        expected = ["noa_norte", "salta_capital", "interior_salta_sur", "interior_salta_norte", "jujuy_interior"]
        assert unique == expected, (
            f"expected ramas {expected}, got {unique}"
        )


# ────────────────────────────────────────────────────────────────────
# RF-04: NOA NORTE = its own branch (no fan-out)
# ────────────────────────────────────────────────────────────────────
class TestRF04NoaNorteOwnBranch:
    def test_noa_norte_appears_as_literal(self, dataset_sql: str) -> None:
        assert "'NOA NORTE'" in dataset_sql, (
            "NOA NORTE must appear as a literal label inside the dataset SQL"
        )

    def test_noa_norte_rama_reads_cob_sucursal_not_preventista(
        self, dataset_sql: str
    ) -> None:
        """NOA NORTE must source from cob_sucursal_* only (no preventista)."""
        body = self._rama_body(dataset_sql, "noa_norte")
        assert body is not None, "rama_noa_norte CTE not found"
        assert re.search(
            r"cob_sucursal_(marca|generico|aguas)", body, re.IGNORECASE
        ), "NOA NORTE rama must reference cob_sucursal_*"
        assert not re.search(
            r"cob_preventista_(marca|generico)", body, re.IGNORECASE
        ), "NOA NORTE rama must NOT reference cob_preventista_*"

    def test_noa_norte_has_no_id_sucursal_filter(self, dataset_sql: str) -> None:
        """The NOA NORTE rama is the all-sucursales rollup — no id_sucursal IN."""
        body = self._rama_body(dataset_sql, "noa_norte")
        assert body is not None, "rama_noa_norte CTE not found"
        assert not re.search(
            r"id_sucursal\s+IN\s*\(", body, re.IGNORECASE
        ), "NOA NORTE must NOT filter by id_sucursal IN (...) — it's the rollup"

    @staticmethod
    def _rama_body(sql: str, rama_name: str) -> str | None:
        """Return the body of `rama_<name> AS (...)`, or None if not found.

        Finds the start `rama_<name> AS (` and walks parens to find the matching
        closing paren, tolerating comments and blank lines.
        """
        start = re.search(
            rf"rama_{re.escape(rama_name)}\s+AS\s*\(",
            sql,
            re.IGNORECASE,
        )
        if not start:
            return None
        depth = 0
        i = start.end() - 1  # at the opening '('
        for i in range(start.end() - 1, len(sql)):
            c = sql[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return sql[start.end():i]
        return None


# ────────────────────────────────────────────────────────────────────
# RF-05: 2025 splice SQL comment + boundary
# ────────────────────────────────────────────────────────────────────
class TestRF05S2025Splice:
    def test_lineage_boundary_comment_present(self, dataset_sql: str) -> None:
        assert re.search(
            r"LINEAGE\s+BOUNDARY.*preventista\s+source.*suc-1\s+aggregate",
            dataset_sql,
            re.IGNORECASE | re.DOTALL,
        ), "SQL must carry a `-- LINEAGE BOUNDARY: ... preventista source; ... suc-1 aggregate` comment"

    def test_pre_2025_preventista_half_present(self, dataset_sql: str) -> None:
        """cob_preventista_marca/_generico gated by anio < 2025."""
        assert re.search(
            r"cob_preventista_(marca|generico)", dataset_sql, re.IGNORECASE
        ), "SQL must reference cob_preventista_marca or cob_preventista_generico"
        assert re.search(
            r"anio\s*<\s*2025", dataset_sql, re.IGNORECASE
        ) or re.search(
            r"EXTRACT\(\s*YEAR\s+FROM\s+[^)]+\)\s*<\s*2025", dataset_sql, re.IGNORECASE
        ), "SQL must encode anio < 2025 predicate somewhere"

    def test_post_2025_suc1_half_present(self, dataset_sql: str) -> None:
        """cob_sucursal_marca/_generico with id_sucursal = 1 AND anio >= 2025."""
        # Look for the combination: id_sucursal = 1 + anio >= 2025 in proximity
        # (within ~500 chars — gives room for the WHERE clause to be multi-line)
        for m in re.finditer(
            r"id_sucursal\s*=\s*1\b", dataset_sql, re.IGNORECASE
        ):
            window = dataset_sql[m.start():m.start() + 600]
            if re.search(r"anio\s*>=\s*2025", window, re.IGNORECASE) or re.search(
                r"EXTRACT\(\s*YEAR\s+FROM\s+[^)]+\)\s*>=\s*2025", window, re.IGNORECASE
            ):
                break
        else:
            raise AssertionError(
                "id_sucursal = 1 must be paired with anio >= 2025 (2025+ suc-1 aggregate)"
            )


# ────────────────────────────────────────────────────────────────────
# RF-06: reassign_rutas_suc1 encoded in SQL
# ────────────────────────────────────────────────────────────────────
class TestRF06ReassignRutas:
    RUTAS = [85, 86, 87, 88, 118, 119]

    def test_salta_capital_excludes_rutas(self, dataset_sql: str) -> None:
        assert re.search(
            r"id_ruta\s+NOT\s+IN\s*\(\s*85\s*,\s*86\s*,\s*87\s*,\s*88\s*,\s*118\s*,\s*119\s*\)",
            dataset_sql,
            re.IGNORECASE,
        ), "SQL must exclude the reassigned rutas via `id_ruta NOT IN (85,86,87,88,118,119)`"

    def test_interior_salta_sur_includes_rutas(self, dataset_sql: str) -> None:
        assert re.search(
            r"id_ruta\s+IN\s*\(\s*85\s*,\s*86\s*,\s*87\s*,\s*88\s*,\s*118\s*,\s*119\s*\)",
            dataset_sql,
            re.IGNORECASE,
        ), "SQL must include the reassigned rutas via `id_ruta IN (85,86,87,88,118,119)` for INTERIOR SALTA SUR"

    def test_reassign_comment_present(self, dataset_sql: str) -> None:
        assert re.search(
            r"REASSIGN:?\s+rutas\s+85,?\s*86,?\s*87,?\s*88,?\s*118,?\s*119",
            dataset_sql,
            re.IGNORECASE,
        ), "SQL must carry a `-- REASSIGN: rutas 85,86,87,88,118,119` comment"


# ────────────────────────────────────────────────────────────────────
# RF-07: AGUAS subdivision graceful degradation
# ────────────────────────────────────────────────────────────────────
class TestRF07AguasGuard:
    def test_to_regclass_guard_present(self, dataset_sql: str) -> None:
        assert re.search(
            r"to_regclass\(\s*'gold\.cob_sucursal_aguas'\s*\)",
            dataset_sql,
            re.IGNORECASE,
        ), "SQL must guard AGUAS source with to_regclass('gold.cob_sucursal_aguas')"

    def test_subdivision_mapping_tokens_inline(self, dataset_sql: str) -> None:
        for token in AGUAS_MARCA_TOKENS:
            assert re.search(
                rf"\b{re.escape(token)}\b", dataset_sql
            ), f"AGUAS subdivision token missing in SQL: {token}"


# ────────────────────────────────────────────────────────────────────
# RF-08: GENERICOS_INCLUIDOS whitelist inline
# ────────────────────────────────────────────────────────────────────
class TestRF08GenericosWhitelist:
    def test_all_five_genericos_in_sql(self, dataset_sql: str) -> None:
        for g in GENERICOS:
            assert f"'{g}'" in dataset_sql, f"whitelist generico literal missing: {g}"

    def test_no_unauthorized_generico_in_clause(self, dataset_sql: str) -> None:
        """Every `generico IN ('...')` clause must contain only whitelist values."""
        authorized = set(GENERICOS)
        in_clauses = IN_CLAUSE_RE.findall(dataset_sql)
        generico_in_clauses = [t for col, t in in_clauses if col.lower() == "generico"]
        assert generico_in_clauses, "no `generico IN (...)` clause found in SQL"
        for literal_csv in generico_in_clauses:
            values = _split_csv_quoted(literal_csv)
            for v in values:
                assert v in authorized, (
                    f"unauthorized generico in whitelist: {v!r} "
                    f"(in clause: {literal_csv!r})"
                )


# ────────────────────────────────────────────────────────────────────
# RF-09: id_fuerza_ventas = 1 documented
# ────────────────────────────────────────────────────────────────────
class TestRF09FuerzaVentas:
    def test_id_fuerza_ventas_literal_present(self, dataset_sql: str) -> None:
        matches = re.findall(
            r"id_fuerza_ventas\s*=\s*1\b", dataset_sql, re.IGNORECASE
        )
        # Must appear in at least 4 branches (one per source) — strict lower bound
        assert len(matches) >= 4, (
            f"id_fuerza_ventas = 1 must appear in every branch, found {len(matches)}"
        )

    def test_assumption_comment_present(self, dataset_sql: str) -> None:
        assert re.search(
            r"ASSUMPTION:?\s+id_fuerza_ventas\s*=\s*1",
            dataset_sql,
            re.IGNORECASE,
        ), "SQL must carry a comment documenting the id_fuerza_ventas=1 assumption"


# ────────────────────────────────────────────────────────────────────
# RF-10: No numeric rounding in dataset SQL
# ────────────────────────────────────────────────────────────────────
class TestRF10NoRounding:
    def test_no_round_on_clientes(self, dataset_sql: str) -> None:
        assert not re.search(
            r"ROUND\s*\(\s*clientes\b", dataset_sql, re.IGNORECASE
        ), "ROUND(clientes) forbidden — see feedback_no_rounding"
        assert not re.search(
            r"\bclientes\b[^,\)]*::int", dataset_sql, re.IGNORECASE
        ), "::int cast on clientes forbidden — see feedback_no_rounding"
        assert not re.search(
            r"CAST\s*\(\s*clientes\s+AS\s+int", dataset_sql, re.IGNORECASE
        ), "CAST(clientes AS int) forbidden — see feedback_no_rounding"
        assert not re.search(
            r"CAST\s*\(\s*clientes\s+AS\s+INTEGER", dataset_sql, re.IGNORECASE
        ), "CAST(clientes AS INTEGER) forbidden — see feedback_no_rounding"


# ────────────────────────────────────────────────────────────────────
# RF-13 (lite): Bundle directory + DB UUID reuse
# ────────────────────────────────────────────────────────────────────
class TestRF13BundleLayout:
    def test_databases_yaml_reuses_uuid(self) -> None:
        db_yaml = (
            REPO_ROOT
            / "superset"
            / "bundle"
            / "graficos-cobertura"
            / "databases"
            / "Medallion_Gold.yaml"
        )
        if not db_yaml.exists():
            pytest.skip("databases/Medallion_Gold.yaml not yet created (T-A.2)")
        with db_yaml.open("r", encoding="utf-8") as fh:
            db = yaml.safe_load(fh)
        assert db["uuid"] == DB_UUID

    def test_password_is_masked(self) -> None:
        db_yaml = (
            REPO_ROOT
            / "superset"
            / "bundle"
            / "graficos-cobertura"
            / "databases"
            / "Medallion_Gold.yaml"
        )
        if not db_yaml.exists():
            pytest.skip("databases/Medallion_Gold.yaml not yet created (T-A.2)")
        with db_yaml.open("r", encoding="utf-8") as fh:
            db = yaml.safe_load(fh)
        uri = db["sqlalchemy_uri"]
        assert "XXXXXXXXXX" in uri, "Password must remain masked (`XXXXXXXXXX`)"
        assert "superset_ro:" in uri
