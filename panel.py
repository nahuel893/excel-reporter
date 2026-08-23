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
from src.api.routes.mgmt_artifacts import router as mgmt_artifacts_router

logger = logging.getLogger(__name__)

app.include_router(mgmt_artifacts_router)

_external_root = os.environ.get("ADMIN_PANEL_ARTIFACTS_ROOT")
if _external_root:
    logger.warning(
        "Artifact browser is serving %s (ADMIN_PANEL_ARTIFACTS_ROOT). "
        "These routes have no authentication — bind to a private address.",
        _external_root,
    )

__all__ = ["app"]
