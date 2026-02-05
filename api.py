"""
API Principal - FastAPI para servicios de reportes CCU.

Uso:
    uvicorn api:app --reload --port 8000

Documentacion:
    http://localhost:8000/docs (Swagger UI)
    http://localhost:8000/redoc (ReDoc)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import ventas_router

app = FastAPI(
    title="Excel Reporter API",
    description="API para generacion automatizada de reportes Excel desde Data Warehouse",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configurar CORS para permitir requests desde cualquier origen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar routers
app.include_router(ventas_router)


@app.get("/", tags=["Health"])
def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "Excel Reporter API",
        "version": "1.0.0"
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Health check detallado."""
    return {
        "status": "healthy",
        "database": "connected",  # TODO: verificar conexion real
        "services": {
            "ventas": "available"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
