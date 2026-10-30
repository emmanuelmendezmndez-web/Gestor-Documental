"""Rutas de SIGED."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.actividad import registrar
from app.mensajes import AVISOS
from app.plantillas import templates
from app.seguridad import autenticar, buscar_usuario, demasiados_intentos, limpiar_fallos, registrar_fallo, usuario_actual

router = APIRouter()

@router.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request, aviso: str | None = None):
    if usuario_actual(request):
        return RedirectResponse(url="/inicio", status_code=303)

    tipo, mensaje = AVISOS.get(aviso, (None, None))

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "login",
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post("/login")
def iniciar_sesion(
    request: Request,
    usuario: str = Form(...),
    password: str = Form(...),
):
    usuario = usuario.strip()
    ip = request.client.host if request.client else "desconocida"
    clave = f"{usuario.lower()[:100]}|{ip}"

    # Mientras dure el bloqueo no se anota cada intento, para que el registro no se llene
    if demasiados_intentos(clave):
        return RedirectResponse(url="/login?aviso=bloqueado", status_code=303)

    fila = None
    if len(usuario) <= 100 and len(password) <= 200:
        fila = autenticar(usuario, password)

    if fila is None:
        registrar_fallo(clave)

        # Solo se guarda el nombre si corresponde a un usuario real: así no queda
        # en el registro una contraseña que alguien tecleó por error en este campo.
        existente = buscar_usuario(usuario) if len(usuario) <= 100 else None
        if existente is None:
            motivo = "usuario no registrado"
        elif not existente["activo"]:
            motivo = "cuenta desactivada"
        else:
            motivo = "contraseña incorrecta"
        if demasiados_intentos(clave):
            motivo += " (cuenta bloqueada temporalmente)"

        registrar(request, "inicio_sesion", "fallo", usuario=existente, detalle=motivo)
        return RedirectResponse(url="/login?aviso=credenciales", status_code=303)

    limpiar_fallos(clave)
    request.session.clear()  # sesión nueva en cada inicio
    request.session["usuario_id"] = fila["id"]
    request.session["version"] = fila["version_sesion"]
    request.session["saludo_clippy_pendiente"] = True

    registrar(
        request,
        "inicio_sesion",
        usuario={"id": fila["id"], "usuario": fila["usuario"]},
    )
    return RedirectResponse(url="/inicio", status_code=303)


@router.post("/salir")
def cerrar_sesion(request: Request):
    usuario = usuario_actual(request)
    if usuario:
        registrar(request, "cierre_sesion", usuario=usuario)

    request.session.clear()
    return RedirectResponse(url="/login?aviso=sesion_cerrada", status_code=303)

