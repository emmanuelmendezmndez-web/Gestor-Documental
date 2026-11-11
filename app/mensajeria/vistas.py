"""Política de previsualización de originales autorizados en Mensajería."""

from pathlib import PureWindowsPath
from urllib.parse import quote

from app.mensajeria import motor
from app.vista_documental import TIPOS_EN_LINEA, pagina

LIMITE_TEXTO = 1024 * 1024
IMAGENES = frozenset(extension for extension, tipo in TIPOS_EN_LINEA.items() if tipo.startswith("image/"))
CABECERAS = {
    "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}


def compatible(extension, tamano, descarga):
    if extension == ".txt":
        return 0 <= tamano <= LIMITE_TEXTO
    return descarga and extension in IMAGENES


def habilitada(datos):
    extension = PureWindowsPath(datos["nombre_original"]).suffix.lower()
    return bool(datos["formato"] and compatible(extension, datos["tamano_bytes"], "descargar" in datos["acciones"]))


def preparar(request, archivo, datos):
    """Proyecta el original ya autorizado como HTML escapado o imagen nativa."""
    if not habilitada(datos):
        raise motor.ErrorMotor("adjunto_no_disponible")
    nombre = datos["nombre_original"]
    extension = PureWindowsPath(nombre).suffix.lower()
    if extension == ".txt":
        contenido = archivo.read(LIMITE_TEXTO + 1)
        if len(contenido) != datos["tamano_bytes"]:
            raise motor.ErrorMotor("adjunto_no_disponible")
        return pagina(request, nombre, extension, texto=contenido.decode("utf-8-sig", errors="replace"),
                      headers=CABECERAS), None
    return None, {
        **CABECERAS,
        "Content-Type": TIPOS_EN_LINEA[extension],
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(nombre, safe='')}",
        "Content-Length": str(datos["tamano_bytes"]),
    }
