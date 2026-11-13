"""Transacciones breves con autorización vigente para escrituras documentales."""

import sqlite3
from contextlib import contextmanager

from fastapi import HTTPException, Request

from app.database import conectar
from app.seguridad import NOMBRES_ROL, PERMISOS, NoAutenticado


@contextmanager
def transaccion_documental(request: Request, permiso: str):
    try:
        with conectar() as conexion:
            conexion.execute("BEGIN IMMEDIATE")
            usuario_id = request.session.get("usuario_id")
            fila = conexion.execute(
                "SELECT id, usuario, nombre, correo, telefono, foto_perfil, rol, departamento, version_sesion "
                "FROM usuarios WHERE id=? AND activo=1", (usuario_id,),
            ).fetchone()
            if fila is None or request.session.get("version") != fila["version_sesion"]:
                request.session.clear()
                raise NoAutenticado()
            usuario = dict(fila)
            usuario.pop("version_sesion")
            usuario["rol_nombre"] = NOMBRES_ROL.get(usuario["rol"], usuario["rol"])
            if permiso not in PERMISOS.get(usuario["rol"], set()):
                raise HTTPException(status_code=403, detail="No tienes permiso para realizar esta acción.")
            request.state.usuario = usuario
            yield conexion, usuario
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise HTTPException(status_code=503, detail="La base de datos está ocupada. Inténtalo de nuevo.") from exc
        raise
