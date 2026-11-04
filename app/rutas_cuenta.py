import logging
import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.actividad import registrar
from app.configuracion import FOTOS_PERFIL_DIR
from app.database import conectar
from app.eliminaciones import encolar, procesar_tareas
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
TAMANO_MAXIMO_FOTO = 5 * 1024 * 1024
PIXELES_MAXIMOS_FOTO = 16_000_000
CORREO_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
TELEFONO_RE = re.compile(r"[0-9+().\-\s]{7,30}")


def requiere_sesion(request: Request):
    """Cualquier usuario con sesión iniciada puede entrar, sea cual sea su rol."""
    usuario = usuario_actual(request)
    if usuario is None:
        raise NoAutenticado()
    request.state.usuario = usuario
    return usuario


router = APIRouter(dependencies=[Depends(requiere_sesion)])

AVISOS_CUENTA = {
    "perfil_actualizado": ("exito", "Los datos de tu perfil se actualizaron correctamente."),
    "perfil_limpieza_pendiente": ("error", "Tu perfil se actualizó, pero la limpieza de la foto anterior quedó pendiente."),
    "perfil_igual": ("exito", "Los datos de tu perfil ya estaban actualizados."),
    "perfil_invalido": ("error", "Revisa tu nombre, correo electrónico y teléfono."),
    "foto_invalida": ("error", "La foto debe ser una imagen PNG o JPEG válida de hasta 5 MB."),
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


def detectar_foto_perfil(contenido: bytes) -> tuple[str, str] | None:
    """Comprueba la firma y dimensiones de PNG/JPEG sin confiar en su nombre o MIME."""
    def dimensiones_validas(ancho: int, alto: int) -> bool:
        return (
            ancho > 0
            and alto > 0
            and ancho <= 8192
            and alto <= 8192
            and ancho * alto <= PIXELES_MAXIMOS_FOTO
        )

    if (
        len(contenido) >= 24
        and contenido.startswith(b"\x89PNG\r\n\x1a\n")
        and contenido[12:16] == b"IHDR"
    ):
        ancho = int.from_bytes(contenido[16:20], "big")
        alto = int.from_bytes(contenido[20:24], "big")
        if dimensiones_validas(ancho, alto):
            return ".png", "image/png"
        return None

    if not contenido.startswith(b"\xff\xd8"):
        return None

    marcadores_sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    cursor = 2
    while cursor + 3 < len(contenido):
        if contenido[cursor] != 0xFF:
            return None
        while cursor < len(contenido) and contenido[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(contenido):
            return None
        marcador = contenido[cursor]
        cursor += 1
        if marcador in {0xD9, 0xDA}:
            return None
        if marcador == 0x01 or 0xD0 <= marcador <= 0xD7:
            continue
        if cursor + 2 > len(contenido):
            return None
        largo = int.from_bytes(contenido[cursor:cursor + 2], "big")
        if largo < 2 or cursor + largo > len(contenido):
            return None
        if marcador in marcadores_sof:
            if largo < 7:
                return None
            alto = int.from_bytes(contenido[cursor + 3:cursor + 5], "big")
            ancho = int.from_bytes(contenido[cursor + 5:cursor + 7], "big")
            if dimensiones_validas(ancho, alto):
                return ".jpg", "image/jpeg"
            return None
        cursor += largo
    return None


def borrar_archivo_foto(ruta: Path | None, conexion=None) -> None:
    """Limpia archivos generados durante una subida fallida sin saltar la cola."""
    if ruta is None:
        return
    try:
        if ruta.parent != FOTOS_PERFIL_DIR:
            raise ValueError("Directorio de foto no autorizado")
        if conexion is not None:
            encolar(conexion, "foto", ruta.name)
            return
        with conectar() as db:
            db.execute("BEGIN IMMEDIATE")
            tarea = encolar(db, "foto", ruta.name)
        procesar_tareas([tarea])
    except Exception:
        logger.exception("No se pudo programar la limpieza de una foto de perfil")


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


@router.post("/cuenta/perfil")
def actualizar_perfil(
    request: Request,
    nombre: str = Form(...),
    correo: str = Form(""),
    telefono: str = Form(""),
    foto: UploadFile | None = File(default=None),
    quitar_foto: bool = Form(False),
):
    usuario = request.state.usuario
    nombre = nombre.strip()
    correo = correo.strip()
    telefono = telefono.strip()
    digitos_telefono = sum(caracter.isdigit() for caracter in telefono)
    if (
        not nombre
        or len(nombre) > 100
        or len(correo) > 254
        or (correo and not CORREO_RE.fullmatch(correo))
        or len(telefono) > 30
        or (telefono and (not TELEFONO_RE.fullmatch(telefono) or not 7 <= digitos_telefono <= 15))
    ):
        return redirigir("perfil_invalido")

    contenido_foto = b""
    tipo_foto = None
    if foto and foto.filename:
        contenido_foto = foto.file.read(TAMANO_MAXIMO_FOTO + 1)
        if len(contenido_foto) > TAMANO_MAXIMO_FOTO:
            return redirigir("foto_invalida")
        tipo_foto = detectar_foto_perfil(contenido_foto)
        if tipo_foto is None:
            return redirigir("foto_invalida")

    nombre_foto_anterior = usuario.get("foto_perfil")
    nueva_foto = None
    ruta_foto_nueva = None
    ruta_temporal = None
    if tipo_foto:
        extension, _ = tipo_foto
        nueva_foto = f"{uuid4().hex}{extension}"
        ruta_foto_nueva = FOTOS_PERFIL_DIR / nueva_foto
        ruta_temporal = FOTOS_PERFIL_DIR / f".{uuid4().hex}.tmp"
        try:
            FOTOS_PERFIL_DIR.mkdir(parents=True, exist_ok=True)
            ruta_temporal.write_bytes(contenido_foto)
            os.replace(ruta_temporal, ruta_foto_nueva)
        except OSError:
            borrar_archivo_foto(ruta_temporal)
            borrar_archivo_foto(ruta_foto_nueva)
            logger.exception("No se pudo guardar la foto de perfil del usuario %s", usuario["id"])
            return redirigir("error")

    foto_perfil = nueva_foto or (None if quitar_foto else nombre_foto_anterior)
    cambios = []
    for clave, valor, etiqueta in (
        ("nombre", nombre, "nombre"),
        ("correo", correo, "correo"),
        ("telefono", telefono, "teléfono"),
    ):
        if valor != usuario.get(clave, ""):
            cambios.append(etiqueta)
    if foto_perfil != nombre_foto_anterior:
        cambios.append("foto de perfil")
    if not cambios:
        borrar_archivo_foto(ruta_foto_nueva)
        return redirigir("perfil_igual")

    tarea = None
    try:
        with conectar() as conexion:
            conexion.execute("BEGIN IMMEDIATE")
            actual = conexion.execute("SELECT foto_perfil FROM usuarios WHERE id=? AND activo=1", (usuario["id"],)).fetchone()
            if actual is None or actual["foto_perfil"] != nombre_foto_anterior:
                borrar_archivo_foto(ruta_foto_nueva, conexion)
                return redirigir("error")
            resultado = conexion.execute(
                """
                UPDATE usuarios
                SET nombre = ?, correo = ?, telefono = ?, foto_perfil = ?
                WHERE id = ? AND activo = 1
                """,
                (nombre, correo, telefono, foto_perfil, usuario["id"]),
            )
            if resultado.rowcount != 1:
                borrar_archivo_foto(ruta_foto_nueva, conexion)
                return redirigir("error")
            if nombre_foto_anterior and foto_perfil != nombre_foto_anterior:
                tarea = encolar(conexion, "foto", nombre_foto_anterior)
            registrar(request, "cuenta_perfil", entidad="usuario", entidad_id=usuario["id"],
                      entidad_nombre=usuario["usuario"],
                      detalle="actualizó: " + ", ".join(cambios) + (f"; limpieza física pendiente; tarea {tarea}" if tarea else ""),
                      conexion=conexion)
    except Exception:
        borrar_archivo_foto(ruta_foto_nueva)
        logger.exception("No se pudo actualizar el nombre del usuario %s", usuario["id"])
        return redirigir("error")

    pendiente = tarea is not None and procesar_tareas([tarea])[tarea] not in {"completada", "cancelada"}

    return redirigir("perfil_limpieza_pendiente" if pendiente else "perfil_actualizado")


@router.get("/cuenta/foto")
def obtener_foto_perfil(request: Request):
    with conectar() as conexion:
        fila = conexion.execute(
            "SELECT foto_perfil FROM usuarios WHERE id = ? AND activo = 1",
            (request.state.usuario["id"],),
        ).fetchone()
    if fila is None or not fila["foto_perfil"]:
        raise HTTPException(status_code=404, detail="Foto de perfil no encontrada.")

    nombre = fila["foto_perfil"]
    if Path(nombre).name != nombre:
        raise HTTPException(status_code=404, detail="Foto de perfil no encontrada.")
    extension = Path(nombre).suffix.lower()
    tipos = {".png": "image/png", ".jpg": "image/jpeg"}
    ruta = FOTOS_PERFIL_DIR / nombre
    if extension not in tipos or not ruta.is_file():
        raise HTTPException(status_code=404, detail="Foto de perfil no encontrada.")
    return FileResponse(
        ruta,
        media_type=tipos[extension],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
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
            registrar(request, "cuenta_password", entidad="usuario", entidad_id=usuario["id"],
                      entidad_nombre=usuario["usuario"], detalle="se cerraron las demás sesiones abiertas",
                      conexion=conexion)
    except Exception:
        logger.exception("No se pudo cambiar la contraseña del usuario %s", usuario["id"])
        return redirigir("error")

    # La sesión actual se queda abierta: se actualiza su versión
    request.session["version"] = nueva_version
    limpiar_fallos(clave)

    return redirigir("password_cambiada")
