import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.actividad import registrar
from app.database import conectar
from app.plantillas import templates
from app.seguridad import (
    PASSWORD_MAXIMO,
    PASSWORD_MINIMO,
    NoAutenticado,
    demasiados_intentos,
    hashear_password,
    limpiar_fallos,
    registrar_fallo,
    usuario_actual,
    verificar_password,
)

logger = logging.getLogger("gestor")


def requiere_sesion(request: Request):
    """Cualquier usuario con sesión iniciada puede entrar, sea cual sea su rol."""
    usuario = usuario_actual(request)
    if usuario is None:
        raise NoAutenticado()
    request.state.usuario = usuario
    return usuario


router = APIRouter(dependencies=[Depends(requiere_sesion)])

AVISOS_CUENTA = {
    "password_cambiada": ("exito", "Contraseña actualizada. Se cerraron tus otras sesiones abiertas, si las había."),
    "actual_incorrecta": ("error", "La contraseña actual no es correcta."),
    "password_corta": ("error", f"La contraseña nueva debe tener entre {PASSWORD_MINIMO} y {PASSWORD_MAXIMO} caracteres."),
    "password_distinta": ("error", "Las contraseñas nuevas no coinciden."),
    "password_igual": ("error", "La contraseña nueva debe ser distinta de la actual."),
    "bloqueado": ("error", "Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo."),
    "error": ("error", "Ocurrió un error. Inténtalo de nuevo."),
}

DESCRIPCIONES_ROL = {
    "lector": "Puedes ver y descargar documentos.",
    "editor": "Puedes ver, descargar, subir y editar documentos.",
    "admin": "Puedes hacer todo lo anterior, eliminar documentos y administrar usuarios y el registro de actividad.",
}


def redirigir(codigo: str) -> RedirectResponse:
    # 303: tras el POST el navegador hace GET, y recargar no reenvía el formulario
    return RedirectResponse(url=f"/cuenta?aviso={codigo}", status_code=303)


@router.get("/cuenta", response_class=HTMLResponse)
def mi_cuenta(request: Request, aviso: str | None = None):
    tipo, mensaje = AVISOS_CUENTA.get(aviso, (None, None))
    usuario = request.state.usuario

    return templates.TemplateResponse(
        request=request,
        name="cuenta.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "cuenta",
            "descripcion_rol": DESCRIPCIONES_ROL.get(usuario["rol"], ""),
            "password_minimo": PASSWORD_MINIMO,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post("/cuenta/password")
def cambiar_password(
    request: Request,
    actual: str = Form(...),
    nueva: str = Form(...),
    confirmacion: str = Form(...),
):
    usuario = request.state.usuario
    ip = request.client.host if request.client else "desconocida"
    clave = f"cuenta|{usuario['id']}|{ip}"

    # Mientras dure el bloqueo no se anota cada intento, para que el registro no se llene
    if demasiados_intentos(clave):
        return redirigir("bloqueado")

    # Primero lo que no depende de la contraseña actual: así estos errores no cuentan como intentos
    if not (PASSWORD_MINIMO <= len(nueva) <= PASSWORD_MAXIMO):
        return redirigir("password_corta")

    if nueva != confirmacion:
        return redirigir("password_distinta")

    with conectar() as conexion:
        fila = conexion.execute(
            "SELECT password_hash FROM usuarios WHERE id = ?",
            (usuario["id"],),
        ).fetchone()

    if (
        fila is None
        or len(actual) > PASSWORD_MAXIMO
        or not verificar_password(actual, fila["password_hash"])
    ):
        registrar_fallo(clave)

        detalle = "contraseña actual incorrecta"
        if demasiados_intentos(clave):
            detalle += " (bloqueo temporal)"

        registrar(
            request,
            "cuenta_password",
            "fallo",
            entidad="usuario",
            entidad_id=usuario["id"],
            entidad_nombre=usuario["usuario"],
            detalle=detalle,
        )
        return redirigir("actual_incorrecta")

    if nueva == actual:
        return redirigir("password_igual")

    password_hash = hashear_password(nueva)

    try:
        with conectar() as conexion:
            # Subir la versión cierra las demás sesiones abiertas de esta persona
            conexion.execute(
                """
                UPDATE usuarios
                SET password_hash = ?, version_sesion = version_sesion + 1
                WHERE id = ?
                """,
                (password_hash, usuario["id"]),
            )
            nueva_version = conexion.execute(
                "SELECT version_sesion FROM usuarios WHERE id = ?",
                (usuario["id"],),
            ).fetchone()["version_sesion"]
    except Exception:
        logger.exception("No se pudo cambiar la contraseña del usuario %s", usuario["id"])
        return redirigir("error")

    # La sesión actual se queda abierta: se actualiza su versión
    request.session["version"] = nueva_version
    limpiar_fallos(clave)

    # Nunca se guarda la contraseña, solo el hecho de que se cambió
    registrar(
        request,
        "cuenta_password",
        entidad="usuario",
        entidad_id=usuario["id"],
        entidad_nombre=usuario["usuario"],
        detalle="se cerraron las demás sesiones abiertas",
    )

    return redirigir("password_cambiada")