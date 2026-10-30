"""Rutas de SIGED."""

import logging
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.acceso_documentos import filtro_area_documento
from app.actividad import registrar
from app.configuracion import STORAGE_DIR
from app.database import conectar
from app.mensajes import AVISOS
from app.plantillas import templates
from app.seleccion import leer_seleccion
from app.servicios.papelera import purgar_documentos_papelera
from app.seguridad import demasiados_intentos, limpiar_fallos, registrar_fallo, requiere_permiso, verificar_password

logger = logging.getLogger("gestor")
POR_PAGINA = 20
router = APIRouter()

@router.get(
    "/papelera",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("restaurar"))],
)
def ver_papelera(request: Request, aviso: str | None = None):
    tipo, mensaje = AVISOS.get(aviso, (None, None))
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario, "d.")
    with conectar() as conexion:
        documentos = conexion.execute(
            """
            SELECT d.id, d.titulo, d.nombre_archivo, d.categoria,
                   d.eliminado_en, u.usuario AS eliminado_por_nombre
            FROM documentos d
            LEFT JOIN usuarios u ON u.id = d.eliminado_por
            WHERE d.eliminado_en IS NOT NULL""" + filtro_area + """
            ORDER BY d.eliminado_en DESC, d.id DESC
            """,
            parametros_area,
        ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="papelera.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "papelera",
            "documentos": documentos,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post(
    "/documentos/{documento_id}/restaurar",
    dependencies=[Depends(requiere_permiso("restaurar"))],
)
def restaurar_documento(request: Request, documento_id: int):
    filtro_area, parametros_area = filtro_area_documento(request.state.usuario)
    with conectar() as conexion:
        fila = conexion.execute(
            "SELECT titulo FROM documentos WHERE id = ? AND eliminado_en IS NOT NULL" + filtro_area,
            [documento_id, *parametros_area],
        ).fetchone()
        if fila is None:
            raise HTTPException(status_code=404, detail="Documento no encontrado en la papelera.")
        conexion.execute(
            "UPDATE documentos SET eliminado_en = NULL, eliminado_por = NULL "
            "WHERE id = ? AND eliminado_en IS NOT NULL" + filtro_area,
            (documento_id, *parametros_area),
        )

    registrar(request, "restaurar", entidad="documento", entidad_id=documento_id,
              entidad_nombre=fila["titulo"])
    return RedirectResponse(url="/papelera?aviso=restaurado", status_code=303)


@router.post(
    "/papelera/restaurar",
    dependencies=[Depends(requiere_permiso("restaurar"))],
)
def restaurar_documentos_masivo(
    request: Request,
    documento_ids: list[int] = Form(default=[]),
):
    ids, placeholders, error = leer_seleccion(documento_ids)
    if error:
        return RedirectResponse(url=f"/papelera?aviso={error}", status_code=303)

    filtro_area, parametros_area = filtro_area_documento(request.state.usuario, "d.")
    # El SELECT usa el alias ``d`` y el UPDATE no; filtrar cada consulta
    # con su referencia correcta evita que SQLite rechace la restauración.
    filtro_area_actualizacion, parametros_area_actualizacion = filtro_area_documento(
        request.state.usuario
    )
    with conectar() as conexion:
        documentos = conexion.execute(
            "SELECT d.id, d.titulo FROM documentos d "
            f"WHERE d.id IN ({placeholders}) AND d.eliminado_en IS NOT NULL" + filtro_area,
            [*ids, *parametros_area],
        ).fetchall()
        if len(documentos) != len(ids):
            raise HTTPException(status_code=404, detail="Uno o más documentos no están disponibles en tu papelera.")
        conexion.execute(
            "UPDATE documentos SET eliminado_en = NULL, eliminado_por = NULL "
            f"WHERE id IN ({placeholders}) AND eliminado_en IS NOT NULL" + filtro_area_actualizacion,
            [*ids, *parametros_area_actualizacion],
        )

    for documento in documentos:
        registrar(
            request,
            "restaurar",
            entidad="documento",
            entidad_id=documento["id"],
            entidad_nombre=documento["titulo"],
            detalle="restauración en lote",
        )
    return RedirectResponse(url="/papelera?aviso=documentos_restaurados", status_code=303)


@router.post(
    "/papelera/eliminar-seleccionados",
    dependencies=[Depends(requiere_permiso("eliminar"))],
)
def eliminar_documentos_seleccionados(request: Request, documento_ids: list[int] = Form(default=[])):
    ids, _, error = leer_seleccion(documento_ids)
    if error:
        return RedirectResponse(url=f"/papelera?aviso={error}", status_code=303)
    try:
        purgar_documentos_papelera(request, STORAGE_DIR, ids)
    except HTTPException:
        raise
    except Exception:
        logger.exception("No se pudieron eliminar los documentos seleccionados de la papelera")
        return RedirectResponse(url="/papelera?aviso=error_papelera", status_code=303)
    return RedirectResponse(url="/papelera?aviso=documentos_purgados", status_code=303)


@router.post(
    "/papelera/vaciar",
    dependencies=[Depends(requiere_permiso("eliminar"))],
)
def vaciar_papelera(request: Request, password: str = Form(...)):
    if request.state.usuario["rol"] != "admin":
        return RedirectResponse(url="/papelera?aviso=clave_incorrecta", status_code=303)
    ip = request.client.host if request.client else "desconocida"
    clave = f"vaciar_papelera|{request.state.usuario['id']}|{ip}"
    if demasiados_intentos(clave):
        return RedirectResponse(url="/papelera?aviso=bloqueado", status_code=303)
    with conectar() as conexion:
        usuario = conexion.execute(
            "SELECT password_hash FROM usuarios WHERE id = ? AND activo = 1",
            (request.state.usuario["id"],),
        ).fetchone()
    if usuario is None or not password or len(password) > 200 or not verificar_password(password, usuario["password_hash"]):
        registrar_fallo(clave)
        return RedirectResponse(url="/papelera?aviso=clave_incorrecta", status_code=303)
    limpiar_fallos(clave)
    try:
        purgar_documentos_papelera(request, STORAGE_DIR)
    except Exception:
        logger.exception("No se pudo vaciar la papelera")
        return RedirectResponse(url="/papelera?aviso=error_papelera", status_code=303)
    return RedirectResponse(url="/papelera?aviso=papelera_vacia", status_code=303)


@router.post(
    "/documentos/{documento_id}/eliminar-definitivamente",
    dependencies=[Depends(requiere_permiso("eliminar"))],
)
def eliminar_definitivamente(request: Request, documento_id: int):
    purgar_documentos_papelera(request, STORAGE_DIR, [documento_id], individual=True)
    return RedirectResponse(url="/papelera?aviso=eliminado_definitivo", status_code=303)

