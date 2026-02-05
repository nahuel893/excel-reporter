"""
ExcelSlicers - Agrega segmentadores a archivos Excel.

Utiliza win32com para agregar slicers a tablas Excel.
Solo funciona en Windows con Excel instalado.
En otros sistemas, las funciones no hacen nada (graceful degradation).
"""
import platform
from pathlib import Path

# Detectar si estamos en Windows
IS_WINDOWS = platform.system() == "Windows"

# Intentar importar win32com solo en Windows
if IS_WINDOWS:
    try:
        import win32com.client as win32
        WIN32COM_AVAILABLE = True
    except ImportError:
        WIN32COM_AVAILABLE = False
else:
    WIN32COM_AVAILABLE = False


def agregar_slicers(
    archivo_excel: Path,
    nombre_tabla: str,
    columnas_slicer: list[str],
    posiciones: list[tuple[float, float]] | None = None
) -> bool:
    """
    Agrega slicers (segmentadores) a una tabla Excel existente.

    Solo funciona en Windows con Excel y pywin32 instalados.
    En otros sistemas, retorna False sin hacer nada.

    Args:
        archivo_excel: Ruta al archivo Excel
        nombre_tabla: Nombre de la tabla Excel (ej: "Tabla_Ventas")
        columnas_slicer: Lista de nombres de columnas para crear slicers
        posiciones: Lista de tuplas (left, top) en puntos para posicionar slicers.
                   Si es None, se posicionan automaticamente.

    Returns:
        True si los slicers fueron agregados, False si no fue posible
    """
    if not WIN32COM_AVAILABLE:
        return False

    if not archivo_excel.exists():
        return False

    excel = None
    try:
        # Iniciar Excel en modo invisible
        excel = win32.gencache.EnsureDispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False

        # Abrir el archivo
        wb = excel.Workbooks.Open(str(archivo_excel.absolute()))
        ws = wb.Worksheets(1)

        # Obtener la tabla
        tabla = None
        for tbl in ws.ListObjects:
            if tbl.Name == nombre_tabla:
                tabla = tbl
                break

        if tabla is None:
            wb.Close(SaveChanges=False)
            return False

        # Crear SlicerCache y Slicer para cada columna
        for i, columna in enumerate(columnas_slicer):
            # Verificar que la columna existe en la tabla
            col_exists = False
            for col in tabla.ListColumns:
                if col.Name == columna:
                    col_exists = True
                    break

            if not col_exists:
                continue

            # Crear SlicerCache
            cache_name = f"Slicer_{columna.replace(' ', '_')}"
            slicer_cache = wb.SlicerCaches.Add2(
                tabla,
                columna
            )

            # Calcular posicion
            if posiciones and i < len(posiciones):
                left, top = posiciones[i]
            else:
                # Posicion automatica: debajo de filas de resumen, escalonados horizontalmente
                # Posicion basada en columnas (aproximadamente columna H en adelante)
                # Cada slicer tiene ~150 de ancho + 10 de separacion
                left = 500 + (i * 160)  # Columna H aprox, escalonados
                top = 5  # Fila 1 aproximadamente

            # Crear Slicer visual (tamano mas compacto)
            slicer = slicer_cache.Slicers.Add(
                ws,
                Left=left,
                Top=top,
                Width=144,
                Height=110,
                Caption=columna
            )

        # Guardar y cerrar
        wb.Save()
        wb.Close(SaveChanges=True)

        return True

    except Exception as e:
        print(f"Error al agregar slicers: {e}")
        return False

    finally:
        if excel:
            try:
                excel.Quit()
            except:
                pass


def slicers_disponibles() -> bool:
    """
    Verifica si la funcionalidad de slicers esta disponible.

    Returns:
        True si estamos en Windows con win32com instalado
    """
    return WIN32COM_AVAILABLE
