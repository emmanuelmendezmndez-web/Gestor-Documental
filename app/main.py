import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.asistente import router as router_asistente
from app.configuracion import APP_DIR, AVISOS_DIR, STORAGE_DIR
from app.database import conectar, inicializar_db
from app.mensajes import MENSAJES_HTTP
from app.plantillas import templates
from app.rutas_actividad import router as router_actividad
from app.rutas_cuenta import router as router_cuenta
from app.rutas_usuarios import router as router_usuarios
from app.rutas_papelera import router as router_rutas_papelera
from app.rutas_documentos import router as router_rutas_documentos
from app.rutas_biblioteca import router as router_rutas_biblioteca
from app.rutas_expedientes import router as router_rutas_expedientes
from app.rutas_avisos import router as router_rutas_avisos
from app.rutas_inicio import router as router_rutas_inicio
from app.rutas_sesion import router as router_rutas_sesion
from app.seguridad import (
    NoAutenticado,
    obtener_clave_secreta,
)

logger = logging.getLogger("gestor")


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
app.include_router(router_rutas_papelera)
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
