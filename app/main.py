import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.acceso_documentos import filtro_area_documento
from app.actividad import registrar
from app.asistente import router as router_asistente
from app.configuracion import APP_DIR, AVISOS_DIR, STORAGE_DIR
from app.database import conectar, inicializar_db
from app.mensajes import AVISOS, MENSAJES_HTTP
from app.plantillas import templates
from app.seleccion import leer_seleccion
from app.servicios.papelera import purgar_documentos_papelera
from app.rutas_actividad import router as router_actividad
from app.rutas_cuenta import router as router_cuenta
from app.rutas_usuarios import router as router_usuarios
from app.rutas_documentos import router as router_rutas_documentos
from app.rutas_biblioteca import router as router_rutas_biblioteca
from app.rutas_expedientes import router as router_rutas_expedientes
from app.rutas_avisos import router as router_rutas_avisos
from app.rutas_inicio import router as router_rutas_inicio
from app.rutas_sesion import router as router_rutas_sesion
from app.seguridad import (
    NoAutenticado,
    demasiados_intentos,
    limpiar_fallos,
    obtener_clave_secreta,
    registrar_fallo,
    requiere_permiso,
    verificar_password,
)

logger = logging.getLogger("gestor")


POR_PAGINA = 20  # documentos por página en la biblioteca
COOKIE_HTTPS_ONLY = os.environ.get("GESTOR_HTTPS_ONLY", "").strip().lower() in {
    "1", "true", "yes", "si"
}



@asynccontextmanager
async def lifespan(app: FastAPI):
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    AVISOS_DIR.mkdir(parents=True, exist_ok=True)
    inicializar_db()

    with conectar() as conexion:
        hay_usuarios = conexion.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone()
    if hay_usuarios is None:
        logger.warning(
            "No hay usuarios registrados. Crea el primero con: python -m app.crear_usuario"
        )

    yield


app = FastAPI(title="Gestor Documental", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=obtener_clave_secreta(),
    session_cookie="gestor_sesion",
    max_age=10 * 60 * 60,  # la sesión dura 10 horas desde la última actividad
    same_site="lax",
    https_only=COOKIE_HTTPS_ONLY,  # activa GESTOR_HTTPS_ONLY detrás de HTTPS
)

app.mount(
    "/static",
    StaticFiles(directory=APP_DIR / "static"),
    name="static",
)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(
        APP_DIR / "static" / "img" / "siged-isotipo.png",
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )

app.include_router(router_usuarios)
app.include_router(router_actividad)
app.include_router(router_cuenta)
app.include_router(router_asistente)
app.include_router(router_rutas_documentos)
app.include_router(router_rutas_biblioteca)
app.include_router(router_rutas_expedientes)
app.include_router(router_rutas_avisos)
app.include_router(router_rutas_inicio)
app.include_router(router_rutas_sesion)


# ---------- Errores ----------

@app.exception_handler(NoAutenticado)
async def manejar_no_autenticado(request: Request, exc: NoAutenticado):
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def manejar_error_http(request: Request, exc: StarletteHTTPException):
    titulo_error, detalle = MENSAJES_HTTP.get(
        exc.status_code, ("Error", "Ocurrió un problema al procesar la solicitud.")
    )
    # Respetamos los textos propios en español; los genéricos en inglés se reemplazan
    if isinstance(exc.detail, str) and exc.detail not in (
        "Not Found",
        "Forbidden",
        "Method Not Allowed",
    ):
        detalle = exc.detail

    return templates.TemplateResponse(
        request=request,
        name="error.html",
        status_code=exc.status_code,
        context={
            "titulo": "Gestor Documental",
            "pagina": "",
            "codigo": exc.status_code,
            "titulo_error": titulo_error,
            "detalle": detalle,
        },
    )


# ---------- Funciones de apoyo ----------





# ---------- Inicio y cierre de sesión ----------







# ---------- Inicio / Dashboard ----------





# ---------- Gestión de avisos (solo administradores) ----------











# ---------- Biblioteca ----------



# ---------- Expedientes ----------















# ---------- Subir ----------





# ---------- Ficha ----------





# ---------- Editar ----------





# ---------- Eliminar ----------







# ---------- Papelera ----------

@app.get(
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


@app.post(
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


@app.post(
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


@app.post(
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


@app.post(
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


@app.post(
    "/documentos/{documento_id}/eliminar-definitivamente",
    dependencies=[Depends(requiere_permiso("eliminar"))],
)
def eliminar_definitivamente(request: Request, documento_id: int):
    purgar_documentos_papelera(request, STORAGE_DIR, [documento_id], individual=True)
    return RedirectResponse(url="/papelera?aviso=eliminado_definitivo", status_code=303)


# ---------- Descargar ----------

