"""Rutas de SIGED."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from app.configuracion import STORAGE_DIR
from app.plantillas import templates
from app.servicios.inicio import buscar_global_datos, dashboard_datos
from app.servicios.estado_sistema import consultar_estado_sistema
from app.seguridad import requiere_permiso

router = APIRouter()

@router.get(
    "/buscar",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("ver"))],
)
def buscar_global(request: Request, q: str = ""):
    return templates.TemplateResponse(request=request, name="buscar.html",
                                      context=buscar_global_datos(request.state.usuario, q))


@router.get(
    "/inicio",
    response_class=HTMLResponse,
    dependencies=[Depends(requiere_permiso("ver"))],
)
def dashboard(request: Request):
    contexto = dashboard_datos(request.state.usuario, STORAGE_DIR)
    contexto["saludo_clippy_entrada"] = bool(request.session.pop("saludo_clippy_pendiente", False))
    return templates.TemplateResponse(request=request, name="inicio.html", context=contexto)


@router.get("/inicio/estado-sistema", include_in_schema=False)
def estado_sistema(request: Request):
    habilitada = bool(getattr(request.app.state, "mensajeria_http_instalada", False))
    codigo, estado = consultar_estado_sistema(request.session, habilitada)
    return JSONResponse(estado, status_code=codigo, headers={"Cache-Control": "private, no-store"})

