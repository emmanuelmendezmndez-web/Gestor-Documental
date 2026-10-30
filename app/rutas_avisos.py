"""Rutas de SIGED."""

import logging
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from app.actividad import registrar
from app.catalogos import DEPARTAMENTOS
from app.configuracion import AVISOS_DIR
from app.database import conectar
from app.mensajes import AVISOS
from app.plantillas import templates
from app.servicios.avisos import crear_aviso_servicio
from app.seguridad import requiere_permiso

logger = logging.getLogger("gestor")
router = APIRouter()

@router.get(
    "/avisos",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("avisos"))],
)
def gestionar_avisos(request: Request, aviso: str | None = None):
    tipo, mensaje = AVISOS.get(aviso, (None, None))
    with conectar() as conexion:
        avisos = conexion.execute(
            """
            SELECT a.id, a.titulo, a.cuerpo, a.imagen_guardada,
                   a.imagen_nombre, a.departamento, a.publicado,
                   datetime(a.fecha_creacion, 'localtime') AS fecha_creacion,
                   COALESCE(u.nombre, u.usuario, 'Administrador') AS autor
            FROM avisos a
            LEFT JOIN usuarios u ON u.id = a.autor_id
            ORDER BY a.fecha_creacion DESC, a.id DESC
            """
        ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="avisos_admin.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "inicio",
            "avisos": avisos,
            "departamentos": DEPARTAMENTOS,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post("/avisos", dependencies=[Depends(requiere_permiso("avisos"))])
def crear_aviso(
    request: Request, titulo: str = Form(...), cuerpo: str = Form(""),
    departamento: str = Form(""), publicado: int = Form(1),
    imagen: UploadFile | None = File(None),
):
    codigo = crear_aviso_servicio(request, titulo, cuerpo, departamento, publicado, imagen, AVISOS_DIR)
    return RedirectResponse(url=f"/avisos?aviso={codigo}", status_code=303)


@router.post(
    "/avisos/{aviso_id}/estado",
    dependencies=[Depends(requiere_permiso("avisos"))],
)
def cambiar_estado_aviso(
    request: Request,
    aviso_id: int,
    publicado: int = Form(...),
):
    if publicado not in (0, 1):
        raise HTTPException(status_code=400, detail="Estado de aviso no válido.")
    with conectar() as conexion:
        aviso = conexion.execute(
            "SELECT titulo FROM avisos WHERE id = ?",
            (aviso_id,),
        ).fetchone()
        if aviso is None:
            raise HTTPException(status_code=404, detail="Aviso no encontrado.")
        conexion.execute("UPDATE avisos SET publicado = ? WHERE id = ?", (publicado, aviso_id))

    registrar(
        request,
        "aviso_estado",
        entidad="aviso",
        entidad_id=aviso_id,
        entidad_nombre=aviso["titulo"],
        detalle="publicado" if publicado else "oculto",
    )
    return RedirectResponse(url="/avisos?aviso=aviso_estado", status_code=303)


@router.post(
    "/avisos/{aviso_id}/eliminar",
    dependencies=[Depends(requiere_permiso("avisos"))],
)
def eliminar_aviso(request: Request, aviso_id: int):
    with conectar() as conexion:
        aviso = conexion.execute(
            "SELECT titulo, imagen_guardada FROM avisos WHERE id = ?",
            (aviso_id,),
        ).fetchone()
        if aviso is None:
            raise HTTPException(status_code=404, detail="Aviso no encontrado.")
        conexion.execute("DELETE FROM avisos WHERE id = ?", (aviso_id,))

    if aviso["imagen_guardada"]:
        try:
            (AVISOS_DIR / aviso["imagen_guardada"]).unlink(missing_ok=True)
        except OSError:
            logger.exception("No se pudo borrar la imagen del aviso %s", aviso_id)
    registrar(
        request,
        "aviso_eliminar",
        entidad="aviso",
        entidad_id=aviso_id,
        entidad_nombre=aviso["titulo"],
    )
    return RedirectResponse(url="/avisos?aviso=aviso_eliminado", status_code=303)


@router.get(
    "/avisos/{aviso_id}/imagen",
    dependencies=[Depends(requiere_permiso("ver"))],
)
def imagen_aviso(request: Request, aviso_id: int):
    with conectar() as conexion:
        aviso = conexion.execute(
            "SELECT imagen_guardada, imagen_nombre, departamento, publicado FROM avisos WHERE id = ?",
            (aviso_id,),
        ).fetchone()

    if aviso is None or not aviso["imagen_guardada"]:
        raise HTTPException(status_code=404, detail="Imagen del aviso no encontrada.")
    usuario = request.state.usuario
    es_admin = usuario["rol"] == "admin"
    visible = aviso["publicado"] and (
        not aviso["departamento"]
        or aviso["departamento"] == usuario.get("departamento", "")
    )
    if not es_admin and not visible:
        raise HTTPException(status_code=404, detail="Imagen del aviso no encontrada.")

    extension = Path(aviso["imagen_guardada"]).suffix.lower()
    tipos_imagen = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    if extension not in tipos_imagen:
        raise HTTPException(status_code=404, detail="Imagen del aviso no encontrada.")
    ruta_imagen = AVISOS_DIR / aviso["imagen_guardada"]
    if not ruta_imagen.is_file():
        raise HTTPException(status_code=404, detail="Imagen del aviso no encontrada.")
    return FileResponse(
        path=ruta_imagen,
        media_type=tipos_imagen[extension],
        filename=aviso["imagen_nombre"] or ruta_imagen.name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )

