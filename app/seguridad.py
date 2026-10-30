import hashlib
import hmac
import os
import re
import secrets
import time

from fastapi import HTTPException, Request

from app.actividad import registrar
from app.configuracion import SECRET_PATH
from app.database import conectar

ROLES = ("lector", "editor", "admin")

NOMBRES_ROL = {
    "lector": "Lector",
    "editor": "Editor",
    "admin": "Administrador",
}

# Qué puede hacer cada rol
PERMISOS = {
    "lector": {"ver", "descargar", "ver_expedientes"},
    "editor": {
        "ver", "descargar", "subir", "editar",
        "ver_expedientes", "gestionar_expedientes", "restaurar", "papelera",
    },
    "admin": {
        "ver", "descargar", "subir", "editar", "eliminar", "restaurar", "papelera",
        "usuarios", "actividad", "avisos", "ver_expedientes", "gestionar_expedientes",
    },
}

# Reglas de usuarios y contraseñas (se validan con fullmatch)
PATRON_USUARIO = re.compile(r"[A-Za-z0-9._-]{3,50}")
PASSWORD_MINIMO = 10
PASSWORD_MAXIMO = 200


class NoAutenticado(Exception):
    """Se lanza cuando hay que iniciar sesión; main.py la convierte en redirección."""


# ---------- Clave secreta de las sesiones ----------

def obtener_clave_secreta() -> str:
    """Usa la variable GESTOR_SECRET_KEY o, si no existe, un archivo .secret_key
    que se genera solo la primera vez. Ese archivo NO debe compartirse ni subirse a git."""
    clave = os.environ.get("GESTOR_SECRET_KEY")
    if clave:
        return clave

    ruta = SECRET_PATH
    if ruta.is_file():
        return ruta.read_text(encoding="utf-8").strip()

    ruta.parent.mkdir(parents=True, exist_ok=True)
    clave = secrets.token_hex(32)
    ruta.write_text(clave, encoding="utf-8")
    return clave


# ---------- Contraseñas ----------

_N, _R, _P = 2**14, 8, 1


def hashear_password(password: str) -> str:
    sal = os.urandom(16)
    derivada = hashlib.scrypt(
        password.encode("utf-8"), salt=sal, n=_N, r=_R, p=_P, dklen=64
    )
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${derivada.hex()}"


def verificar_password(password: str, guardado: str) -> bool:
    try:
        algoritmo, n, r, p, sal, esperado = guardado.split("$")
        if algoritmo != "scrypt":
            return False
        esperado_bytes = bytes.fromhex(esperado)
        derivada = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(sal),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(esperado_bytes),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derivada, esperado_bytes)


# Se usa cuando el usuario no existe, para que responder tarde lo mismo
# y no se pueda adivinar qué usuarios están registrados.
_HASH_FALSO = hashear_password("contraseña-que-nadie-usa")


def autenticar(usuario: str, password: str):
    """Devuelve la fila del usuario si los datos son correctos; si no, None."""
    with conectar() as conexion:
        fila = conexion.execute(
            """
            SELECT id, usuario, password_hash, version_sesion
            FROM usuarios
            WHERE usuario = ? AND activo = 1
            """,
            (usuario,),
        ).fetchone()

    if fila is None:
        verificar_password(password, _HASH_FALSO)
        return None

    if not verificar_password(password, fila["password_hash"]):
        return None

    return fila


def buscar_usuario(nombre: str):
    """Devuelve {'id', 'usuario', 'activo'} si el nombre existe (sin distinguir
    mayúsculas); si no, None. Sirve para el registro de actividad."""
    with conectar() as conexion:
        fila = conexion.execute(
            "SELECT id, usuario, activo FROM usuarios WHERE usuario = ?",
            (nombre,),
        ).fetchone()
    return dict(fila) if fila else None


# ---------- Límite de intentos fallidos (en memoria) ----------

INTENTOS_MAXIMOS = 5
VENTANA_SEGUNDOS = 300  # 5 minutos

_fallos: dict[str, list[float]] = {}


def _recientes(clave: str) -> list[float]:
    ahora = time.monotonic()
    return [t for t in _fallos.get(clave, []) if ahora - t < VENTANA_SEGUNDOS]


def demasiados_intentos(clave: str) -> bool:
    return len(_recientes(clave)) >= INTENTOS_MAXIMOS


def registrar_fallo(clave: str) -> None:
    if len(_fallos) > 1000:  # evita que el diccionario crezca sin límite
        for k in list(_fallos):
            if not _recientes(k):
                _fallos.pop(k, None)
    _fallos[clave] = _recientes(clave) + [time.monotonic()]


def limpiar_fallos(clave: str) -> None:
    _fallos.pop(clave, None)


# ---------- Sesión y permisos ----------

def usuario_actual(request: Request):
    """Devuelve el usuario de la sesión (como diccionario) o None.
    Se consulta la base en cada petición: si desactivas a alguien, le cambias
    el rol o restableces su contraseña, el cambio se aplica de inmediato."""
    usuario_id = request.session.get("usuario_id")
    if not usuario_id:
        return None

    with conectar() as conexion:
        fila = conexion.execute(
            """
            SELECT id, usuario, nombre, correo, telefono, foto_perfil,
                   rol, departamento, version_sesion
            FROM usuarios
            WHERE id = ? AND activo = 1
            """,
            (usuario_id,),
        ).fetchone()

    # La sesión deja de valer si el usuario ya no existe, está desactivado
    # o su versión de sesión cambió (por ejemplo, al restablecer su contraseña).
    if fila is None or request.session.get("version") != fila["version_sesion"]:
        request.session.clear()
        return None

    datos = dict(fila)
    datos.pop("version_sesion")
    datos["rol_nombre"] = NOMBRES_ROL.get(datos["rol"], datos["rol"])
    return datos


def requiere_permiso(permiso: str):
    """Crea una dependencia de FastAPI que exige sesión iniciada y un permiso."""

    if not any(permiso in permisos for permisos in PERMISOS.values()):
        raise ValueError(f"Permiso desconocido: {permiso!r}")

    def dependencia(request: Request):
        usuario = usuario_actual(request)
        if usuario is None:
            raise NoAutenticado()

        if permiso not in PERMISOS.get(usuario["rol"], set()):
            registrar(
                request,
                "acceso_denegado",
                "denegado",
                usuario=usuario,
                detalle=f"{request.method} {request.url.path} (requiere «{permiso}»)",
            )
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para realizar esta acción.",
            )

        request.state.usuario = usuario
        return usuario

    return dependencia


def contexto_usuario(request: Request) -> dict:
    """Datos que reciben todas las plantillas: el usuario y la función puede()."""
    usuario = getattr(request.state, "usuario", None) or usuario_actual(request)
    permisos = PERMISOS.get(usuario["rol"], set()) if usuario else set()
    return {
        "usuario": usuario,
        "puede": lambda permiso: permiso in permisos,
    }
