"""
API Principal - FastAPI para servicios de reportes CCU.

Uso:
    uvicorn api:app --reload --port 8000

Documentacion interactiva:
    http://localhost:8000/docs  (Swagger UI)
    http://localhost:8000/redoc (ReDoc)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import ventas_router
from src.core.data_loader import DataLoader

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
        "y `/download` retorna un ZIP con todos los archivos."
    ),
    version="2.0.0",
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

app.include_router(ventas_router)


@app.get("/", tags=["Health"], summary="Estado del servicio")
def root():
    """Retorna estado basico del servicio."""
    return {
        "status": "ok",
        "service": "Excel Reporter API",
        "version": "2.0.0",
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
