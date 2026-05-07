"""bd_agent/scripts/smoke_test.py — manual pre-flight smoke test (T-110).

Verifies that the runtime environment is correctly configured before starting
the BD Agent.  Each check returns a ``{"name": str, "ok": bool, ...}`` dict.

Run:
    python -m bd_agent.scripts.smoke_test

The script prints a checklist with ✓/✗ per check and exits with code 0 if all
pass, or 1 if any fail.

Design rules:
    - Zero imports from src.* (RF-070)
    - DB ping uses a passed-in engine (injectable for tests)
    - HTTP check uses a passed-in http_client (injectable for tests)
    - ``run_all_checks`` accepts keyword overrides so unit tests can inject
      mocks without patching module globals
"""
from __future__ import annotations

import os
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

_REQUIRED_ENV_VARS = ["AGENT_DB_URL", "GEMINI_API_KEY", "WHATSAPP_SERVICE_URL"]


def check_env_vars(*, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Check that all required environment variables are set.

    Args:
        env: Mapping to check.  Defaults to ``os.environ``.

    Returns:
        ``{"name": "env_vars", "ok": bool, "missing": list[str]}``
    """
    if env is None:
        env = dict(os.environ)

    missing = [v for v in _REQUIRED_ENV_VARS if not env.get(v)]
    return {
        "name": "env_vars",
        "ok": len(missing) == 0,
        "missing": missing,
    }


def check_db_ping(*, engine: Any = None) -> dict[str, Any]:
    """Ping the database with ``SELECT 1``.

    Args:
        engine: SQLAlchemy engine.  If None, one is built from ``AGENT_DB_URL``.

    Returns:
        ``{"name": "db_ping", "ok": bool, "error": str | None}``
    """
    try:
        if engine is None:
            from sqlalchemy import create_engine
            db_url = os.environ.get("AGENT_DB_URL", "")
            if not db_url:
                return {"name": "db_ping", "ok": False, "error": "AGENT_DB_URL not set"}
            engine = create_engine(db_url)

        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            scalar = result.scalar()
            if scalar != 1:
                return {
                    "name": "db_ping",
                    "ok": False,
                    "error": f"SELECT 1 returned {scalar!r} (expected 1)",
                }
        return {"name": "db_ping", "ok": True, "error": None}

    except Exception as exc:
        return {"name": "db_ping", "ok": False, "error": str(exc).lower()}


def check_sqlglot_validator() -> dict[str, Any]:
    """Verify the sqlglot validator rejects DROP and accepts SELECT.

    Returns:
        ``{"name": "sqlglot_validator", "ok": bool,
           "select_accepted": bool, "drop_rejected": bool}``
    """
    from bd_agent.safety.sqlglot_validator import UnsafeQuery, validate

    select_accepted = False
    drop_rejected = False

    try:
        validate("SELECT 1")
        select_accepted = True
    except UnsafeQuery:
        pass

    try:
        validate("DROP TABLE gold.fact_ventas")
        # If we get here, the validator did NOT reject it — bad
    except UnsafeQuery:
        drop_rejected = True

    return {
        "name": "sqlglot_validator",
        "ok": select_accepted and drop_rejected,
        "select_accepted": select_accepted,
        "drop_rejected": drop_rejected,
    }


def check_whatsapp_status(
    *,
    http_client: Any = None,
    url: str | None = None,
) -> dict[str, Any]:
    """Verify that the WhatsApp service reports ``connected`` on ``/status``.

    Args:
        http_client: Object with a ``.get(url)`` method.  Defaults to
            ``httpx.Client()``.
        url: Full URL to check.  Defaults to
            ``{WHATSAPP_SERVICE_URL}/status``.

    Returns:
        ``{"name": "whatsapp_status", "ok": bool, "error": str | None}``
    """
    try:
        if http_client is None:
            import httpx
            http_client = httpx.Client(timeout=5)

        if url is None:
            base = os.environ.get("WHATSAPP_SERVICE_URL", "http://localhost:3000")
            url = f"{base}/status"

        response = http_client.get(url)
        if response.status_code != 200:
            return {
                "name": "whatsapp_status",
                "ok": False,
                "error": f"HTTP {response.status_code}",
            }
        data = response.json()
        status = data.get("status", "")
        if status != "connected":
            return {
                "name": "whatsapp_status",
                "ok": False,
                "error": f"status={status!r} (expected 'connected')",
            }
        return {"name": "whatsapp_status", "ok": True, "error": None}

    except Exception as exc:
        return {"name": "whatsapp_status", "ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# run_all_checks — aggregate runner
# ---------------------------------------------------------------------------

def run_all_checks(
    *,
    env: dict[str, str] | None = None,
    engine: Any = None,
    http_client: Any = None,
) -> list[dict[str, Any]]:
    """Run all smoke checks and return the list of results.

    Args:
        env:         Optional override for environment variables dict.
        engine:      Optional SQLAlchemy engine for the DB ping check.
        http_client: Optional HTTP client for the WhatsApp status check.
    """
    results: list[dict[str, Any]] = []

    # 1. Environment variables
    results.append(check_env_vars(env=env))

    # 2. DB ping
    results.append(check_db_ping(engine=engine))

    # 3. sqlglot validator
    results.append(check_sqlglot_validator())

    # 4. WhatsApp service status
    wa_url: str | None = None
    if env is not None:
        base = env.get("WHATSAPP_SERVICE_URL")
        if base:
            wa_url = f"{base}/status"
    results.append(check_whatsapp_status(http_client=http_client, url=wa_url))

    return results


# ---------------------------------------------------------------------------
# Pretty-print helper
# ---------------------------------------------------------------------------

def _print_results(results: list[dict[str, Any]]) -> bool:
    """Print a human-readable checklist; return True if all checks pass."""
    all_ok = True
    print("\n=== BD Agent Smoke Test ===\n")
    for r in results:
        mark = "✓" if r["ok"] else "✗"
        name = r["name"]
        extra = ""
        if not r["ok"]:
            all_ok = False
            # Show the most useful field
            if "missing" in r and r["missing"]:
                extra = f"  [missing: {', '.join(r['missing'])}]"
            elif "error" in r and r["error"]:
                extra = f"  [error: {r['error']}]"
        print(f"  {mark} {name}{extra}")

    print()
    if all_ok:
        print("All checks passed.")
    else:
        print("One or more checks FAILED. Fix the issues above before starting the agent.")
    print()
    return all_ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = run_all_checks()
    ok = _print_results(results)
    sys.exit(0 if ok else 1)
