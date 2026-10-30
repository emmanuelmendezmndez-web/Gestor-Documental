"""Funciones de formato y validación compartidas por las rutas."""

from datetime import date


def fecha_valida(texto: str) -> str:
    """Devuelve la fecha como AAAA-MM-DD, o una cadena vacía si no es válida."""
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError:
        return ""


def formatear_tamano(total_bytes: int) -> str:
    """Convierte bytes a un texto legible: 512 B, 48.3 KB, 2.3 MB..."""
    tamano = float(total_bytes)
    for unidad in ("B", "KB", "MB", "GB"):
        if tamano < 1024 or unidad == "GB":
            if unidad == "B":
                return f"{int(tamano)} B"
            return f"{tamano:.1f} {unidad}"
        tamano /= 1024


def formatear_espacio_disco(total_bytes: int) -> str:
    """Muestra capacidades en unidades legibles, hasta PB."""
    cantidad = float(total_bytes)
    for unidad in ("B", "KB", "MB", "GB", "TB", "PB"):
        if cantidad < 1024 or unidad == "PB":
            valor = f"{cantidad:.1f}".rstrip("0").rstrip(".")
            return f"{valor} {unidad}"
        cantidad /= 1024


def escapar_like(texto: str) -> str:
    """Evita que % y _ escritos por el usuario se comporten como comodines."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
