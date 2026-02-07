# Documentación - Excel Reporter

Documentación completa del proyecto Excel Reporter.

## Índice

### 📚 Documentación General

- **[CLAUDE.md](../CLAUDE.md)** - Contexto completo del proyecto para Claude AI
  - Stack tecnológico
  - Estructura del proyecto
  - Comandos frecuentes
  - Patrones de diseño

### 🔌 API REST

- **[API.md](./API.md)** - Documentación de la API FastAPI
  - Endpoints disponibles
  - Ejemplos de uso
  - Integración con agentes AI
  - Deployment

### 📊 Características Excel

- **[EXCEL_FEATURES.md](./EXCEL_FEATURES.md)** - Características avanzadas de Excel
  - **Slicers (Segmentadores)**: Filtros visuales interactivos
  - **Column Groups**: Grupos de columnas colapsables
  - Ejemplos y troubleshooting

## Guías Rápidas

### Inicio Rápido - CLI

```bash
# Activar entorno
.venv\Scripts\activate

# Generar reporte
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31

# Con slicers (solo Windows)
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31

# Sin slicers
python main.py ventas --desde 2026-01-01 --hasta 2026-01-31 --no-slicers
```

### Inicio Rápido - API

```bash
# Iniciar API
uvicorn api:app --reload --port 8000

# Documentación interactiva
# http://localhost:8000/docs
```

```bash
# Generar reporte via API
curl -X POST "http://localhost:8000/ventas/reporte" \
  -H "Content-Type: application/json" \
  -d '{"fecha_desde": "2026-01-01", "fecha_hasta": "2026-01-31"}'
```

### Inicio Rápido - Python

```python
from src.services.ventas import VentasService, ReporteVentasConfig

# Configurar reporte
config = ReporteVentasConfig(
    fecha_desde="2026-01-01",
    fecha_hasta="2026-01-31",
    genericos=["CERVEZAS", "AGUAS"],
    con_slicers=True
)

# Generar
service = VentasService()
result = service.generar_reporte(config)

print(f"Reporte generado: {result.ruta_archivo}")
```

## Características Principales

### ✨ Reportes Excel Profesionales

- Tablas nativas de Excel con filtros
- Formato condicional y estilos personalizables
- Columnas agrupadas y colapsables
- Filas de resumen automáticas

### 🎚️ Slicers (Solo Windows)

- Filtros visuales interactivos
- Compatibilidad automática (se omiten en Linux/Mac)
- Posicionamiento configurable

### 🌐 API REST

- Endpoints para generar reportes
- Descarga directa de archivos
- Especificación OpenAPI para agentes AI
- Documentación interactiva Swagger

### 📊 Formato Avanzado

- Grupos de columnas colapsables
- Formato numérico personalizado
- Anchos de columna configurables
- Encabezados con estilo

## Arquitectura

```
Excel Reporter
│
├── CLI (main.py)
│   └── Comandos de terminal
│
├── API REST (api.py)
│   └── FastAPI endpoints
│
├── Services (src/services/)
│   ├── VentasService
│   └── [Nuevos servicios]
│
├── Core (src/core/)
│   ├── DataLoader - Acceso a BD
│   ├── ExcelWriter - Generación Excel
│   ├── ExcelSlicers - Slicers (Windows)
│   └── BaseProcessor - Utilidades
│
└── Config (config/)
    └── Settings - Configuración global
```

## Flujo de Trabajo

### 1. Extracción de Datos

```
DataLoader → PostgreSQL (Gold Layer)
```

### 2. Procesamiento

```
VentasProcessor → Transformaciones → DataFrame
```

### 3. Generación Excel

```
ExcelWriter → Formato + Estilo → .xlsx
```

### 4. Post-procesamiento (Opcional)

```
ExcelSlicers → win32com → Slicers agregados
```

## Tecnologías

| Componente | Tecnología | Versión |
|------------|------------|---------|
| Backend | Python | 3.12+ |
| Base de Datos | PostgreSQL | - |
| ORM | SQLAlchemy | 2.0+ |
| Procesamiento | Pandas | 2.0+ |
| Excel | OpenPyXL | 3.1+ |
| Slicers | pywin32 | 306+ |
| API | FastAPI | 0.109+ |
| Testing | pytest | 8.0+ |

## Contribuir

### Agregar un nuevo reporte

1. Crear `src/services/nuevo_reporte/`
2. Implementar `processor.py` con lógica de transformación
3. Implementar `service.py` heredando de `BaseService`
4. Agregar ruta en `src/api/routes/nuevo_reporte.py`
5. Registrar router en `api.py`
6. Agregar subcomando en `main.py`

Ver [CLAUDE.md](../CLAUDE.md#agregar-nuevo-reporte) para detalles.

### Testing

```bash
# Ejecutar tests
pytest -v

# Con cobertura
pytest --cov=src --cov-report=html
```

## Recursos Adicionales

- **OpenAPI Spec**: http://localhost:8000/openapi.json
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Soporte

Para preguntas o issues:
1. Revisar la documentación en `docs/`
2. Consultar `CLAUDE.md` para contexto del proyecto
3. Revisar logs de ejecución
4. Verificar configuración en `.env`

## Changelog

### v1.0.0 (2026-02-07)

- ✨ API REST con FastAPI
- ✨ Slicers para Excel (Windows)
- ✨ Grupos de columnas colapsables
- 🐛 Fix formato numérico
- 🐛 Fix combinaciones faltantes de marcas
- 📝 Documentación completa

---

**Última actualización**: 2026-02-07
