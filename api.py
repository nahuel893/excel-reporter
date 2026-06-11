"""
API Principal - FastAPI para servicios de reportes CCU.

Uso:
    uvicorn api:app --reload --port 8000

Documentacion interactiva:
    http://localhost:8000/docs  (Swagger UI)
    http://localhost:8000/redoc (ReDoc)
"""
import asyncio
import logging

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routes import ventas_router, resumen_mensual_router, graficos_cobertura_router
from src.api.routes.mgmt_runs import router as mgmt_runs_router
from src.api.routes.mgmt_configs import router as mgmt_configs_router
from src.core.data_loader import DataLoader

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Excel Reporter API",
    description=(
        "API para generacion automatizada de reportes Excel desde Data Warehouse CCU.\n\n"
        "## Flujo tipico\n"
        "1. Consultar `/ventas/genericos` y `/ventas/sucursales` para ver los datos disponibles.\n"
        "2. Generar reporte con `POST /ventas/reporte` (retorna metadata) "
        "o `POST /ventas/reporte/download` (retorna el archivo directamente).\n"
        "3. Para reportes por supervisor, incluir el campo `supervisores` en el body.\n\n"
        "## Reportes por supervisor\n"
        "Si se incluye `supervisores` en el request, se genera un archivo por supervisor "
        "y `/download` retorna un ZIP con todos los archivos.\n\n"
        "## Resumen Mensual\n"
        "Genera un reporte ejecutivo por generico con ventas de los ultimos dos dias habiles, "
        "total acumulado, tendencia al cierre, ventas del mes anterior y del mismo mes del ano anterior."
    ),
    version="2.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Existing routes (unchanged)
app.include_router(ventas_router)
app.include_router(resumen_mensual_router)
app.include_router(graficos_cobertura_router)

# Management UI routes
app.include_router(mgmt_runs_router)
app.include_router(mgmt_configs_router)


# ---------------------------------------------------------------------------
# Startup / shutdown hooks
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def _startup():
    """Initialize DB, recover interrupted runs, start scheduler, mount BD Agent."""
    from src.api.db import get_default_engine, init_db, recover_interrupted_runs
    from src.api.runner import RunRegistry
    from src.api.scheduler import build_scheduler, seed_daily_master_job

    # 1. DB
    engine = get_default_engine()
    init_db(engine=engine)
    interrupted = recover_interrupted_runs(engine=engine)
    if interrupted:
        logger.warning("Startup: marked %d run(s) as 'interrupted'", interrupted)

    # 2. Runner
    loop = asyncio.get_running_loop()
    app.state.runner = RunRegistry(loop=loop, engine=engine)
    app.state.engine = engine

    # 3. Scheduler
    try:
        sched = build_scheduler(engine=engine)
        seed_daily_master_job(sched)
        sched.start()
        app.state.scheduler = sched
        logger.info("Scheduler started")
    except Exception as exc:
        logger.warning("Scheduler could not start: %s", exc)
        app.state.scheduler = None

    # 4. BD Agent (optional — skipped if GEMINI_API_KEY or AGENT_DB_URL are absent)
    try:
        from bd_agent.wiring import build_agent_runtime
        runtime = build_agent_runtime()
        if runtime is not None:
            app.include_router(runtime.router, prefix="")
            app.state.bd_agent_runtime = runtime
            logger.info("BD Agent mounted at /agent")
        else:
            app.state.bd_agent_runtime = None
    except Exception as exc:
        logger.warning("BD Agent startup error: %s — /agent router not mounted.", exc)
        app.state.bd_agent_runtime = None


@app.on_event("shutdown")
async def _shutdown():
    """Shut down scheduler and terminate active runs."""
    sched = getattr(app.state, "scheduler", None)
    if sched is not None:
        try:
            sched.shutdown(wait=False)
        except Exception:
            pass

    runner = getattr(app.state, "runner", None)
    if runner is not None:
        for sess in list(runner.sessions.values()):
            sess.terminate(grace=5)


@app.get("/", tags=["Health"], summary="Estado del servicio")
def root():
    """Retorna estado basico del servicio."""
    return {
        "status": "ok",
        "service": "Excel Reporter API",
        "version": "2.2.0",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"], summary="Health check con verificacion de BD")
def health_check():
    """Verifica conectividad con la base de datos."""
    db_status = "ok"
    db_error = None
    try:
        loader = DataLoader()
        # Consulta minima para verificar conexion
        loader.execute_query("SELECT 1")
    except Exception as e:
        db_status = "error"
        db_error = str(e)

    status = "healthy" if db_status == "ok" else "degraded"
    response = {
        "status": status,
        "database": db_status,
        "services": {"ventas": "available"},
    }
    if db_error:
        response["database_error"] = db_error

    return response


# ---------------------------------------------------------------------------
# SPA static files mount (only when frontend/dist/ exists)
# Mounted AFTER all API routes so API routes take priority.
# html=True enables SPA fallback (404 → index.html).
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/app", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="spa")
else:
    logger.info(
        "frontend/dist/ not found — SPA not mounted. "
        "Run `cd frontend && npm run build` to enable."
    )

_RESUMEN_DIST = Path(__file__).parent / "resumen-web" / "dist"
if _RESUMEN_DIST.exists():
    app.mount("/resumen", StaticFiles(directory=str(_RESUMEN_DIST), html=True), name="resumen-spa")
else:
    logger.info(
        "resumen-web/dist/ not found — resumen view not mounted. "
        "Run `cd resumen-web && npm run build` to enable."
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
