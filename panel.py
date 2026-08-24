"""
Admin panel entrypoint — composition root for the management API.

Run with:
    uvicorn panel:app --host <tailscale-ip> --port 8010

Why this file exists instead of adding routers to api.py:

api.py is the production application: systemd runs it, the daily pipeline and
the WhatsApp agent depend on it. Every line added there is a line that can
break a report that goes out at 07:00. This feature must not carry that risk,
so it composes the production app from the outside rather than editing it.

    api.py    — production surface, left untouched by this feature
    panel.py  — that same surface plus the admin routers this feature adds

What this does and does not isolate: `app` is the very object api.py builds,
and include_router mutates it. So the isolation is by PROCESS, not by app
object — running `uvicorn api:app` gives you a process without these routes,
but anything that imports `panel` gets them on `api.app` too, in that process.
That is enough for the goal here (production never imports this module) and
the routers are read-only anyway, but it is not a sandbox and should not be
described as one.

Note: mgmt_runs and mgmt_configs were already mounted inside api.py by earlier
work and are intentionally left there — this file adds only what is new.

Security: these routes are unauthenticated by design (single user, private
network). Bind to a Tailscale or loopback address, never 0.0.0.0 —
ADMIN_PANEL_ARTIFACTS_ROOT can point the artifact browser at any directory on
disk, so a public bind turns it into an anonymous read of that whole subtree.
"""
from __future__ import annotations

import logging
import os

from api import app
from src.api.daily_store import init_daily_store
from src.api.routes.mgmt_artifacts import router as mgmt_artifacts_router
from src.api.routes.mgmt_daily import router as mgmt_daily_router
from src.api.routes.mgmt_schedule import router as mgmt_schedule_router

logger = logging.getLogger(__name__)

app.include_router(mgmt_artifacts_router)
app.include_router(mgmt_daily_router)
app.include_router(mgmt_schedule_router)


def _init_daily_store(application) -> None:
    """Create the daily-run tables on the engine api.py built.

    api.py owns the engine and knows nothing about these tables, so they are
    created here. create_all is idempotent, and an empty daily-runs screen is
    the honest answer before the first recorded run — reading a table that was
    never created would be a 500 instead.

    A missing engine is logged and survived: the panel is an observer, and an
    observer that refuses to start takes down the thing it was watching.
    """
    engine = getattr(application.state, "engine", None)
    if engine is None:
        logger.warning(
            "No engine on app.state; the daily-run tables were not created and "
            "/mgmt/daily-runs will answer 503."
        )
        return
    init_daily_store(engine)


@app.on_event("startup")
async def _panel_startup() -> None:
    # Registered after api.py's own startup handler, so app.state.engine is
    # already set by the time this runs.
    _init_daily_store(app)

_external_root = os.environ.get("ADMIN_PANEL_ARTIFACTS_ROOT")
if _external_root:
    logger.warning(
        "Artifact browser is serving %s (ADMIN_PANEL_ARTIFACTS_ROOT). "
        "These routes have no authentication — bind to a private address.",
        _external_root,
    )

__all__ = ["app"]
