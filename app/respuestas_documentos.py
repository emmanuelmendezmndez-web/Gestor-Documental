"""Redirecciones tras las operaciones sobre documentos."""

from fastapi.responses import RedirectResponse


def avisar(codigo: str) -> RedirectResponse:
    # 303 evita que el navegador reenvíe el formulario al recargar.
    ruta = "/" if codigo == "subido" else "/subir"
    return RedirectResponse(url=f"{ruta}?aviso={codigo}", status_code=303)


def avisar_edicion(documento_id: int, codigo: str) -> RedirectResponse:
    if codigo == "editado":
        ruta = f"/documentos/{documento_id}"
    else:
        ruta = f"/documentos/{documento_id}/editar"
    return RedirectResponse(url=f"{ruta}?aviso={codigo}", status_code=303)


def avisar_eliminacion(documento_id: int, codigo: str) -> RedirectResponse:
    if codigo == "eliminado":
        ruta = "/"
    else:
        ruta = f"/documentos/{documento_id}/eliminar"
    return RedirectResponse(url=f"{ruta}?aviso={codigo}", status_code=303)
