# API REST - Documentación

## Introducción

La API REST permite generar reportes Excel mediante peticiones HTTP. Construida con FastAPI, expone los servicios de generación de reportes de manera programática.

## Inicio Rápido

### Iniciar el servidor

```bash
uvicorn api:app --reload --port 8000
```

### Documentación interactiva

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Endpoints

### Health Check

#### `GET /`

Health check básico.

**Response:**
```json
{
  "status": "ok",
  "service": "Excel Reporter API",
  "version": "1.0.0"
}
```

#### `GET /health`

Health check detallado con estado de servicios.

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "services": {
    "ventas": "available"
  }
}
```

---

### Ventas

#### `POST /ventas/reporte`

Genera un reporte de ventas y retorna metadata del archivo generado.

**Request Body:**
```json
{
  "fecha_desde": "2026-01-01",
  "fecha_hasta": "2026-01-31",
  "genericos": ["CERVEZAS", "AGUAS"],
  "nombre_archivo": "reporte_enero",
  "con_slicers": true
}
```

**Parámetros:**

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `fecha_desde` | string | Sí | Fecha inicio formato YYYY-MM-DD |
| `fecha_hasta` | string | Sí | Fecha fin formato YYYY-MM-DD |
| `genericos` | array[string] | No | Lista de genéricos a filtrar |
| `nombre_archivo` | string | No | Nombre del archivo (sin extensión) |
| `con_slicers` | boolean | No | Agregar slicers (default: true, solo Windows) |

**Response (200):**
```json
{
  "ruta_archivo": "C:\\path\\to\\ventas_2026-01-01_2026-01-31.xlsx",
  "registros_ventas": 6598,
  "registros_procesados": 1652,
  "sucursales": 14,
  "genericos_incluidos": ["CERVEZAS", "AGUAS", "VINOS"],
  "slicers_agregados": true
}
```

**Ejemplo con curl:**
```bash
curl -X POST "http://localhost:8000/ventas/reporte" \
  -H "Content-Type: application/json" \
  -d '{
    "fecha_desde": "2026-01-01",
    "fecha_hasta": "2026-01-31",
    "genericos": ["CERVEZAS"]
  }'
```

**Ejemplo con Python:**
```python
import requests

response = requests.post(
    "http://localhost:8000/ventas/reporte",
    json={
        "fecha_desde": "2026-01-01",
        "fecha_hasta": "2026-01-31",
        "genericos": ["CERVEZAS", "AGUAS"],
        "con_slicers": True
    }
)

result = response.json()
print(f"Archivo generado: {result['ruta_archivo']}")
print(f"Registros procesados: {result['registros_procesados']}")
```

---

#### `POST /ventas/reporte/download`

Genera un reporte de ventas y lo descarga directamente como archivo Excel.

**Request Body:** Mismo que `/ventas/reporte`

**Response (200):**
- Content-Type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- Archivo Excel descargable

**Ejemplo con curl:**
```bash
curl -X POST "http://localhost:8000/ventas/reporte/download" \
  -H "Content-Type: application/json" \
  -d '{"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"}' \
  --output reporte.xlsx
```

**Ejemplo con Python:**
```python
import requests

response = requests.post(
    "http://localhost:8000/ventas/reporte/download",
    json={
        "fecha_desde": "2026-01-01",
        "fecha_hasta": "2026-01-31"
    }
)

with open("reporte.xlsx", "wb") as f:
    f.write(response.content)
```

---

#### `GET /ventas/genericos`

Lista todos los genéricos disponibles en la base de datos.

**Response (200):**
```json
{
  "genericos": [
    "AGUAS",
    "CERVEZAS",
    "ENERGIZANTES",
    "VINOS"
  ],
  "total": 4
}
```

**Ejemplo con curl:**
```bash
curl http://localhost:8000/ventas/genericos
```

---

#### `GET /ventas/sucursales`

Lista todas las sucursales disponibles.

**Response (200):**
```json
{
  "sucursales": [
    "SUCURSAL A",
    "SUCURSAL B",
    "SUCURSAL C"
  ],
  "total": 3
}
```

**Ejemplo con curl:**
```bash
curl http://localhost:8000/ventas/sucursales
```

---

## Manejo de Errores

Todos los endpoints retornan errores en formato estándar:

**Error Response (500):**
```json
{
  "detail": "Mensaje de error descriptivo"
}
```

## Integración con Agentes

Para que un agente AI use la API:

1. **Obtener especificación OpenAPI:**
   ```bash
   curl http://localhost:8000/openapi.json
   ```

2. **Parsear el JSON** para entender endpoints disponibles

3. **Construir requests** basándose en los schemas definidos

La especificación OpenAPI incluye:
- Todos los endpoints con métodos HTTP
- Parámetros requeridos y opcionales
- Tipos de datos y validaciones
- Ejemplos de request/response
- Descripciones detalladas

## CORS

La API está configurada con CORS abierto (`allow_origins=["*"]`) para desarrollo. Para producción, configurar orígenes específicos en `api.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://tu-frontend.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Deployment

### Desarrollo
```bash
uvicorn api:app --reload --port 8000
```

### Producción
```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4
```

### Docker (ejemplo)
```dockerfile
FROM python:3.12
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Testing

```python
from fastapi.testclient import TestClient
from api import app

client = TestClient(app)

def test_health():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_listar_genericos():
    response = client.get("/ventas/genericos")
    assert response.status_code == 200
    assert "genericos" in response.json()
```
