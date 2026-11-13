"""Presentación compartida por las vistas documentales de SIGED."""

from app.plantillas import templates

TIPOS_EN_LINEA = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
CABECERAS_PRIVADAS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}


def pagina(request, nombre, extension, *, texto=None, error=None, headers=None):
    return templates.TemplateResponse(
        request=request,
        name="previsualizacion.html",
        context={"nombre_archivo": nombre, "extension": extension, "texto": texto, "error": error},
        headers={
            **CABECERAS_PRIVADAS,
            "Content-Security-Policy": "default-src 'none'; style-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'self'",
            **(headers or {}),
        },
    )
