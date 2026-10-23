import logging
import sqlite3

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.actividad import registrar
from app.database import conectar
from app.plantillas import templates
from app.seguridad import (
    NOMBRES_ROL,
    PASSWORD_MAXIMO,
    PASSWORD_MINIMO,
    PATRON_USUARIO,
    ROLES,
    hashear_password,
    requiere_permiso,
)

logger = logging.getLogger("gestor")

# Todas las rutas de este archivo exigen el permiso "usuarios" (solo administradores)
router = APIRouter(dependencies=[Depends(requiere_permiso("usuarios"))])

AVISOS_USUARIOS = {
    "usuario_creado": ("exito", "Usuario creado correctamente."),
    "usuario_editado": ("exito", "Datos del usuario actualizados."),
    "usuario_activado": ("exito", "Usuario activado."),
    "usuario_desactivado": ("exito", "Usuario desactivado. Ya no puede iniciar sesión."),
    "usuario_eliminado": ("exito", "Usuario eliminado. Su historial de actividad se conserva."),
    "password_restablecida": ("exito", "Contraseña restablecida. Se cerraron las sesiones abiertas de ese usuario."),
    "usuario_invalido": ("error", "El usuario debe tener de 3 a 50 caracteres: letras, números, punto, guion o guion bajo."),
    "usuario_existe": ("error", "Ese nombre de usuario ya existe."),
    "usuario_reservado": ("error", "Ese nombre perteneció a un usuario eliminado y tiene historial. Usa otro para que el registro de actividad no se confunda."),
    "nombre_invalido": ("error", "El nombre es obligatorio (máximo 100 caracteres)."),
    "rol_invalido": ("error", "El rol seleccionado no es válido."),
    "password_corta": ("error", f"La contraseña debe tener entre {PASSWORD_MINIMO} y {PASSWORD_MAXIMO} caracteres."),
    "password_distinta": ("error", "Las contraseñas no coinciden."),
    "propio": ("error", "No puedes cambiar tu propio rol ni desactivar tu propia cuenta."),
    "propio_eliminar": ("error", "No puedes eliminar tu propia cuenta."),
    "eliminar_activo": ("error", "Para eliminar una cuenta primero debes desactivarla."),
    "error": ("error", "Ocurrió un error. Inténtalo de nuevo."),
}

ROLES_PARA_FORMULARIO = [(rol, NOMBRES_ROL[rol]) for rol in ROLES]


def redirigir(ruta: str, codigo: str) -> RedirectResponse:
    # 303: tras el POST el navegador hace GET, y recargar no reenvía el formulario
    return RedirectResponse(url=f"{ruta}?aviso={codigo}", status_code=303)


def obtener_usuario(usuario_id: int):
    with conectar() as conexion:
        fila = conexion.execute(
            """
            SELECT id, usuario, nombre, rol, activo,
                   datetime(fecha_creacion, 'localtime') AS fecha_creacion
            FROM usuarios
            WHERE id = ?
            """,
            (usuario_id,),
        ).fetchone()

    if fila is None:
        raise HTTPException(
            status_code=404,
            detail="Usuario no encontrado.",
        )
    return fila


def validar_password(password: str, confirmacion: str) -> str | None:
    """Devuelve el código del error, o None si la contraseña es válida."""
    if not (PASSWORD_MINIMO <= len(password) <= PASSWORD_MAXIMO):
        return "password_corta"
    if password != confirmacion:
        return "password_distinta"
    return None


# ---------- Lista y creación ----------

@router.get("/usuarios", response_class=HTMLResponse)
def lista_usuarios(request: Request, aviso: str | None = None):
    tipo, mensaje = AVISOS_USUARIOS.get(aviso, (None, None))

    with conectar() as conexion:
        usuarios = conexion.execute(
            """
            SELECT id, usuario, nombre, rol, activo,
                   datetime(fecha_creacion, 'localtime') AS fecha_creacion
            FROM usuarios
            ORDER BY activo DESC, usuario COLLATE NOCASE
            """
        ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="usuarios.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "usuarios",
            "usuarios": usuarios,
            "roles": ROLES_PARA_FORMULARIO,
            "nombres_rol": NOMBRES_ROL,
            "password_minimo": PASSWORD_MINIMO,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post("/usuarios")
def crear_usuario_web(
    request: Request,
    usuario: str = Form(...),
    nombre: str = Form(...),
    rol: str = Form(...),
    password: str = Form(...),
    confirmacion: str = Form(...),
):
    usuario = usuario.strip()
    nombre = nombre.strip()

    if not PATRON_USUARIO.fullmatch(usuario):
        return redirigir("/usuarios", "usuario_invalido")

    if not nombre or len(nombre) > 100:
        return redirigir("/usuarios", "nombre_invalido")

    if rol not in ROLES:
        return redirigir("/usuarios", "rol_invalido")

    error = validar_password(password, confirmacion)
    if error:
        return redirigir("/usuarios", error)

    # Un nombre que ya tiene historial pero ya no existe perteneció a un usuario
    # eliminado: no se reutiliza, para no mezclar a dos personas en el registro.
    with conectar() as conexion:
        existe = conexion.execute(
            "SELECT 1 FROM usuarios WHERE usuario = ?",
            (usuario,),
        ).fetchone()
        con_historial = conexion.execute(
            "SELECT 1 FROM actividad WHERE usuario = ? COLLATE NOCASE LIMIT 1",
            (usuario,),
        ).fetchone()

    if existe is None and con_historial is not None:
        return redirigir("/usuarios", "usuario_reservado")

    password_hash = hashear_password(password)

    try:
        with conectar() as conexion:
            resultado = conexion.execute(
                """
                INSERT INTO usuarios (usuario, nombre, password_hash, rol)
                VALUES (?, ?, ?, ?)
                """,
                (usuario, nombre, password_hash, rol),
            )
            nuevo_id = resultado.lastrowid
    except sqlite3.IntegrityError:
        # El campo usuario es UNIQUE (sin distinguir mayúsculas)
        return redirigir("/usuarios", "usuario_existe")
    except Exception:
        logger.exception("No se pudo crear el usuario")
        return redirigir("/usuarios", "error")

    registrar(
        request,
        "usuario_crear",
        entidad="usuario",
        entidad_id=nuevo_id,
        entidad_nombre=usuario,
        detalle=f"rol: {NOMBRES_ROL[rol]}",
    )
    return redirigir("/usuarios", "usuario_creado")


# ---------- Edición ----------

@router.get("/usuarios/{usuario_id}/editar", response_class=HTMLResponse)
def pagina_editar_usuario(
    request: Request,
    usuario_id: int,
    aviso: str | None = None,
):
    tipo, mensaje = AVISOS_USUARIOS.get(aviso, (None, None))
    editado = obtener_usuario(usuario_id)

    return templates.TemplateResponse(
        request=request,
        name="usuario_editar.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "usuarios",
            "editado": editado,
            "es_propio": editado["id"] == request.state.usuario["id"],
            "roles": ROLES_PARA_FORMULARIO,
            "password_minimo": PASSWORD_MINIMO,
            "mensaje": mensaje,
            "tipo": tipo,
        },
    )


@router.post("/usuarios/{usuario_id}/editar")
def editar_usuario(
    request: Request,
    usuario_id: int,
    nombre: str = Form(...),
    rol: str = Form(...),
):
    ruta = f"/usuarios/{usuario_id}/editar"
    nombre = nombre.strip()

    if not nombre or len(nombre) > 100:
        return redirigir(ruta, "nombre_invalido")

    if rol not in ROLES:
        return redirigir(ruta, "rol_invalido")

    actual = obtener_usuario(usuario_id)  # 404 si no existe

    # Nadie puede cambiarse su propio rol: así siempre queda un administrador
    if usuario_id == request.state.usuario["id"] and rol != actual["rol"]:
        return redirigir(ruta, "propio")

    try:
        with conectar() as conexion:
            conexion.execute(
                "UPDATE usuarios SET nombre = ?, rol = ? WHERE id = ?",
                (nombre, rol, usuario_id),
            )
    except Exception:
        logger.exception("No se pudo editar el usuario %s", usuario_id)
        return redirigir(ruta, "error")

    cambios = []
    if actual["nombre"] != nombre:
        cambios.append(f"nombre: «{actual['nombre']}» → «{nombre}»")
    if actual["rol"] != rol:
        cambios.append(f"rol: {NOMBRES_ROL[actual['rol']]} → {NOMBRES_ROL[rol]}")

    if cambios:
        registrar(
            request,
            "usuario_editar",
            entidad="usuario",
            entidad_id=usuario_id,
            entidad_nombre=actual["usuario"],
            detalle="; ".join(cambios),
        )

    return redirigir("/usuarios", "usuario_editado")


@router.post("/usuarios/{usuario_id}/password")
def restablecer_password(
    request: Request,
    usuario_id: int,
    password: str = Form(...),
    confirmacion: str = Form(...),
):
    ruta = f"/usuarios/{usuario_id}/editar"
    objetivo = obtener_usuario(usuario_id)  # 404 si no existe

    error = validar_password(password, confirmacion)
    if error:
        return redirigir(ruta, error)

    password_hash = hashear_password(password)

    try:
        with conectar() as conexion:
            # Subir la versión cierra todas las sesiones abiertas de ese usuario
            conexion.execute(
                """
                UPDATE usuarios
                SET password_hash = ?, version_sesion = version_sesion + 1
                WHERE id = ?
                """,
                (password_hash, usuario_id),
            )
            nueva_version = conexion.execute(
                "SELECT version_sesion FROM usuarios WHERE id = ?",
                (usuario_id,),
            ).fetchone()["version_sesion"]
    except Exception:
        logger.exception("No se pudo restablecer la contraseña de %s", usuario_id)
        return redirigir(ruta, "error")

    # Si el administrador cambió su propia contraseña, no le cerramos su sesión
    if usuario_id == request.state.usuario["id"]:
        request.session["version"] = nueva_version

    # Nunca se guarda la contraseña, solo el hecho de que se restableció
    registrar(
        request,
        "usuario_password",
        entidad="usuario",
        entidad_id=usuario_id,
        entidad_nombre=objetivo["usuario"],
        detalle="se cerraron sus sesiones abiertas",
    )

    return redirigir(ruta, "password_restablecida")


@router.post("/usuarios/{usuario_id}/estado")
def cambiar_estado(
    request: Request,
    usuario_id: int,
    activo: int = Form(...),
):
    ruta = f"/usuarios/{usuario_id}/editar"

    if activo not in (0, 1):
        return redirigir(ruta, "error")

    objetivo = obtener_usuario(usuario_id)  # 404 si no existe

    # Nadie puede desactivarse a sí mismo
    if usuario_id == request.state.usuario["id"]:
        return redirigir(ruta, "propio")

    try:
        with conectar() as conexion:
            # También se sube la versión: al reactivarlo no revive sesiones viejas
            conexion.execute(
                """
                UPDATE usuarios
                SET activo = ?, version_sesion = version_sesion + 1
                WHERE id = ?
                """,
                (activo, usuario_id),
            )
    except Exception:
        logger.exception("No se pudo cambiar el estado del usuario %s", usuario_id)
        return redirigir(ruta, "error")

    registrar(
        request,
        "usuario_estado",
        entidad="usuario",
        entidad_id=usuario_id,
        entidad_nombre=objetivo["usuario"],
        detalle="activado" if activo else "desactivado",
    )

    return redirigir(
        "/usuarios",
        "usuario_activado" if activo else "usuario_desactivado",
    )


# ---------- Eliminación ----------

@router.get("/usuarios/{usuario_id}/eliminar", response_class=HTMLResponse)
def pagina_eliminar_usuario(request: Request, usuario_id: int):
    # Esta ruta solo MUESTRA la confirmación: no borra nada.
    editado = obtener_usuario(usuario_id)  # 404 si no existe
    ruta = f"/usuarios/{usuario_id}/editar"

    if usuario_id == request.state.usuario["id"]:
        return redirigir(ruta, "propio_eliminar")

    if editado["activo"]:
        return redirigir(ruta, "eliminar_activo")

    return templates.TemplateResponse(
        request=request,
        name="usuario_eliminar.html",
        context={
            "titulo": "Gestor Documental",
            "pagina": "usuarios",
            "editado": editado,
            "nombres_rol": NOMBRES_ROL,
        },
    )


@router.post("/usuarios/{usuario_id}/eliminar")
def eliminar_usuario(request: Request, usuario_id: int):
    ruta = f"/usuarios/{usuario_id}/editar"
    objetivo = obtener_usuario(usuario_id)  # 404 si no existe

    if usuario_id == request.state.usuario["id"]:
        return redirigir(ruta, "propio_eliminar")

    try:
        with conectar() as conexion:
            # Solo se borra si sigue desactivada: la condición va en la misma sentencia
            resultado = conexion.execute(
                "DELETE FROM usuarios WHERE id = ? AND activo = 0",
                (usuario_id,),
            )
            borrado = resultado.rowcount > 0
    except Exception:
        logger.exception("No se pudo eliminar el usuario %s", usuario_id)
        return redirigir(ruta, "error")

    if not borrado:
        return redirigir(ruta, "eliminar_activo")

    registrar(
        request,
        "usuario_eliminar",
        entidad="usuario",
        entidad_id=usuario_id,
        entidad_nombre=objetivo["usuario"],
        detalle=f"nombre: «{objetivo['nombre']}» · rol: {NOMBRES_ROL[objetivo['rol']]}",
    )

    return redirigir("/usuarios", "usuario_eliminado")