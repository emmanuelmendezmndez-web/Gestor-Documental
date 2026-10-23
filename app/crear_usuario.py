"""Crea un usuario o restablece su contraseña.

Uso (desde la carpeta raíz del proyecto):
    python -m app.crear_usuario
"""
import getpass
import re
import sys

from app.database import conectar, inicializar_db
from app.seguridad import NOMBRES_ROL, ROLES, hashear_password

PATRON_USUARIO = re.compile(r"^[A-Za-z0-9._-]{3,50}$")
LARGO_MINIMO = 10
LARGO_MAXIMO = 200


def pedir_rol() -> str:
    opciones = ", ".join(f"{rol} ({NOMBRES_ROL[rol]})" for rol in ROLES)
    while True:
        rol = input(f"Rol - {opciones}: ").strip().lower()
        if rol in ROLES:
            return rol
        print("Rol no válido. Escribe exactamente una de las opciones.")


def pedir_password() -> str:
    print("(Al escribir la contraseña no se verá nada en pantalla; es normal.)")
    while True:
        clave = getpass.getpass(f"Contraseña (mínimo {LARGO_MINIMO} caracteres): ")
        if len(clave) < LARGO_MINIMO:
            print(f"Es muy corta: usa al menos {LARGO_MINIMO} caracteres.")
            continue
        if len(clave) > LARGO_MAXIMO:
            print(f"Es muy larga: usa máximo {LARGO_MAXIMO} caracteres.")
            continue
        if clave != getpass.getpass("Repite la contraseña: "):
            print("Las contraseñas no coinciden. Inténtalo de nuevo.")
            continue
        return clave


def hay_otro_admin_activo(excluir_id: int) -> bool:
    with conectar() as conexion:
        fila = conexion.execute(
            "SELECT COUNT(*) AS total FROM usuarios "
            "WHERE rol = 'admin' AND activo = 1 AND id != ?",
            (excluir_id,),
        ).fetchone()
    return fila["total"] > 0


def main() -> None:
    inicializar_db()

    usuario = input("Usuario (3 a 50 letras, números, punto o guion): ").strip()
    if not PATRON_USUARIO.match(usuario):
        print("Usuario no válido.")
        sys.exit(1)

    with conectar() as conexion:
        existente = conexion.execute(
            "SELECT id, rol FROM usuarios WHERE usuario = ?",
            (usuario,),
        ).fetchone()

    if existente:
        respuesta = input(
            "Ese usuario ya existe. ¿Cambiar su contraseña y su rol? (s/n): "
        ).strip().lower()
        if respuesta != "s":
            print("Sin cambios.")
            return

        rol = pedir_rol()
        if (
            existente["rol"] == "admin"
            and rol != "admin"
            and not hay_otro_admin_activo(existente["id"])
        ):
            print("No se puede: es el único administrador y te quedarías sin acceso.")
            sys.exit(1)

        clave = pedir_password()
        with conectar() as conexion:
            # También lo reactiva si estaba desactivado
                       conexion.execute(
                "UPDATE usuarios SET password_hash = ?, rol = ?, activo = 1, "
                "version_sesion = version_sesion + 1 WHERE id = ?",
                (hashear_password(clave), rol, existente["id"]),
            )
        print(f"Usuario '{usuario}' actualizado ({NOMBRES_ROL[rol]}).")
        return

    nombre = input("Nombre completo: ").strip()
    if not nombre or len(nombre) > 100:
        print("El nombre es obligatorio (máximo 100 caracteres).")
        sys.exit(1)

    rol = pedir_rol()
    clave = pedir_password()

    with conectar() as conexion:
        conexion.execute(
            "INSERT INTO usuarios (usuario, nombre, password_hash, rol) VALUES (?, ?, ?, ?)",
            (usuario, nombre, hashear_password(clave), rol),
        )
    print(f"Usuario '{usuario}' creado ({NOMBRES_ROL[rol]}).")


if __name__ == "__main__":
    main()