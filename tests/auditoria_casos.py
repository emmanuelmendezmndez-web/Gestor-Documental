"""Ejecutado en un proceso con GESTOR_DATA_DIR temporal."""
import logging
import os
import sqlite3
import subprocess
import sys
from io import BytesIO
from unittest.mock import patch

from aislamiento import exigir_directorio_temporal

exigir_directorio_temporal("siged-auditoria-")

from starlette.requests import Request
from starlette.datastructures import UploadFile

from app.configuracion import STORAGE_DIR
from app.database import conectar, inicializar_db
from app.rutas_documentos import editar_documento, enviar_documentos_papelera, subir
from app.rutas_expedientes import crear_expediente
from app.servicios.avisos import crear_aviso_servicio
from app.rutas_papelera import (eliminar_definitivamente, eliminar_documentos_seleccionados,
                               restaurar_documento, restaurar_documentos_masivo)
from app.rutas_usuarios import cambiar_estado, crear_usuario_web, editar_usuario, restablecer_password
from app.rutas_sesion import cerrar_sesion
from app import crear_usuario
from app.actividad import registrar


logging.getLogger("gestor").disabled = True
inicializar_db()
STORAGE_DIR.mkdir(exist_ok=True)
with conectar() as db:
    admin = db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) VALUES('admin','Admin','falso','admin','Tesorería')").lastrowid
    editor = db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) VALUES('editor','Editor','falso','editor','Tesorería')").lastrowid
    ids = []
    for i in range(5):
        nombre = f"archivo{i}.txt"
        (STORAGE_DIR / nombre).write_text("archivo ficticio", encoding="utf-8")
        ids.append(db.execute("INSERT INTO documentos(titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes,departamento,eliminado_en) VALUES(?,?,?,?,?,?,?)",
                              (f"Titulo {i}", nombre, nombre, "Otros", 16, "Tesorería", None if i < 2 else "2026-01-01")).lastrowid)
    db.execute("CREATE TRIGGER fallo_actividad BEFORE INSERT ON actividad BEGIN SELECT RAISE(FAIL, 'fallo ficticio'); END")

req = Request({"type": "http", "method": "POST", "path": "/", "headers": [],
               "client": ("127.0.0.1", 1000), "session": {"usuario_id": admin, "version": 0}})
req.state.usuario = {"id": admin, "usuario": "admin", "nombre": "Admin", "rol": "admin", "departamento": "Tesorería"}


def debe_fallar(funcion, *args):
    try:
        respuesta = funcion(*args)
    except sqlite3.Error:
        return
    assert "error" in respuesta.headers.get("location", ""), respuesta.headers


debe_fallar(editar_documento, req, ids[0], "Cambio", "Otros", "", "", "Tesorería", "", "", 1)
debe_fallar(enviar_documentos_papelera, req, ids[:2])
debe_fallar(restaurar_documento, req, ids[2])
debe_fallar(restaurar_documentos_masivo, req, ids[2:4])
debe_fallar(eliminar_definitivamente, req, ids[4])
debe_fallar(eliminar_documentos_seleccionados, req, ids[2:4])
debe_fallar(editar_usuario, req, editor, "Editor", "lector", "Recursos Humanos")
debe_fallar(cambiar_estado, req, editor, 0)
debe_fallar(restablecer_password, req, editor, "NuevaClaveFicticia123!", "NuevaClaveFicticia123!")
debe_fallar(crear_usuario_web, req, "nuevo", "Nuevo", "lector", "ClaveFicticia123!", "ClaveFicticia123!", "Tesorería")
debe_fallar(crear_expediente, req, "Expediente ficticio", "")
if not (crear_aviso_servicio(req, "Aviso ficticio", "Texto", "", 1, None, STORAGE_DIR / "avisos") == "aviso_error"):
    raise AssertionError()
debe_fallar(subir, req, "Nuevo documento", "Otros", "", "", "Tesorería", "", "",
            UploadFile(filename="ficticio.txt", file=BytesIO(b"documento de prueba")))
with conectar() as db:
    assert db.execute("SELECT titulo FROM documentos WHERE id=?", (ids[0],)).fetchone()[0] == "Titulo 0"
    assert db.execute("SELECT COUNT(*) FROM documentos WHERE id IN (?,?) AND eliminado_en IS NULL", ids[:2]).fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM documentos WHERE id IN (?,?,?) AND eliminado_en IS NOT NULL", ids[2:]).fetchone()[0] == 3
    assert tuple(db.execute("SELECT rol,departamento,activo FROM usuarios WHERE id=?", (editor,)).fetchone()) == ("editor", "Tesorería", 1)
    assert db.execute("SELECT password_hash FROM usuarios WHERE id=?", (editor,)).fetchone()[0] == "falso"
    assert db.execute("SELECT 1 FROM usuarios WHERE usuario='nuevo'").fetchone() is None
    assert db.execute("SELECT COUNT(*) FROM eliminaciones_pendientes WHERE estado='pendiente'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM actividad").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM expedientes").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM avisos").fetchone()[0] == 0
assert (STORAGE_DIR / "archivo4.txt").exists()

# Cerrar sesión conserva la política de mejor esfuerzo.
with patch("app.rutas_sesion.usuario_actual", return_value=req.state.usuario):
    respuesta = cerrar_sesion(req)
assert respuesta.status_code == 303 and not req.session

# La herramienta de consola también revierte si falla la auditoría.
with patch("builtins.input", side_effect=["consola", "Consola"]), \
     patch.object(crear_usuario, "pedir_rol", return_value="lector"), \
     patch.object(crear_usuario, "pedir_password", return_value="ClaveFicticia123!"):
    try:
        crear_usuario.main()
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("La consola no revirtió el fallo de auditoría")
with conectar() as db:
    assert db.execute("SELECT 1 FROM usuarios WHERE usuario='consola'").fetchone() is None
    db.execute("DROP TRIGGER fallo_actividad")

with patch("builtins.input", side_effect=["consola", "Consola"]), \
     patch.object(crear_usuario, "pedir_rol", return_value="lector"), \
     patch.object(crear_usuario, "pedir_password", return_value="ClaveFicticia123!"):
    crear_usuario.main()
with patch("builtins.input", side_effect=["consola", "s"]), \
     patch.object(crear_usuario, "pedir_rol", return_value="editor"), \
     patch.object(crear_usuario, "pedir_password", return_value="OtraClaveFicticia123!"):
    crear_usuario.main()
with conectar() as db:
    assert db.execute("SELECT rol FROM usuarios WHERE usuario='consola'").fetchone()[0] == "editor"
    detalles = [fila[0] for fila in db.execute("SELECT detalle FROM actividad WHERE entidad_nombre='consola'")]
    assert len(detalles) == 2 and not any("ClaveFicticia" in texto for texto in detalles)
    db.execute("CREATE TABLE padre_prueba(id INTEGER PRIMARY KEY)")
    db.execute("CREATE TABLE hijo_prueba(id INTEGER REFERENCES padre_prueba(id) DEFERRABLE INITIALLY DEFERRED)")

# Una violación diferida hace fallar el commit, después de insertar la actividad.
try:
    with conectar() as db:
        db.execute("INSERT INTO hijo_prueba(id) VALUES(999)")
        registrar(None, "usuario_editar", detalle="commit ficticio", conexion=db)
except sqlite3.IntegrityError:
    pass
else:
    raise AssertionError("Se esperaba un fallo de commit")
with conectar() as db:
    assert db.execute("SELECT COUNT(*) FROM hijo_prueba").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM actividad WHERE detalle='commit ficticio'").fetchone()[0] == 0

# Interrupción del proceso antes y después de confirmar, usando solo esta base ficticia.
base_codigo = """
import os
from app.database import conectar
from app.actividad import registrar
with conectar() as db:
    db.execute("UPDATE documentos SET titulo='interrupcion' WHERE id=1")
    registrar(None, 'editar', entidad='documento', entidad_id=1, detalle='interrupcion ficticia', conexion=db)
    {salida}
os._exit(0)
"""
subprocess.run([sys.executable, "-c", base_codigo.format(salida="os._exit(0)")],
               env=os.environ.copy(), check=True, timeout=30)
with conectar() as db:
    assert db.execute("SELECT titulo FROM documentos WHERE id=1").fetchone()[0] == "Titulo 0"
    assert db.execute("SELECT COUNT(*) FROM actividad WHERE detalle='interrupcion ficticia'").fetchone()[0] == 0
subprocess.run([sys.executable, "-c", base_codigo.format(salida="pass")],
               env=os.environ.copy(), check=True, timeout=30)
with conectar() as db:
    assert db.execute("SELECT titulo FROM documentos WHERE id=1").fetchone()[0] == "interrupcion"
    assert db.execute("SELECT COUNT(*) FROM actividad WHERE detalle='interrupcion ficticia'").fetchone()[0] == 1

req.scope["session"] = {"usuario_id": admin, "version": 0}
if not ("eliminado_definitivo" in eliminar_definitivamente(req, ids[4]).headers["location"]):
    raise AssertionError()
with conectar() as db:
    registros = db.execute("SELECT resultado,detalle FROM actividad WHERE accion='eliminar_definitivo' AND entidad_id=? ORDER BY id", (ids[4],)).fetchall()
    assert len(registros) == 2
    assert "pendiente" in registros[0]["detalle"] and "completada" in registros[1]["detalle"]
    assert registros[1]["resultado"] == "exito"

# Si falla la auditoría tras unlink, el estado sigue pendiente y se recupera.
from app.eliminaciones import procesar_tarea
nombre = "borrado_interrumpido.txt"
(STORAGE_DIR / nombre).write_text("ficticio", encoding="utf-8")
with conectar() as db:
    documento = db.execute("INSERT INTO documentos(titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes,eliminado_en) VALUES(?,?,?,?,?,?)",
                           ("Interrupción", nombre, nombre, "Otros", 8, "2026-01-01")).lastrowid
    db.execute("CREATE TRIGGER fallo_limpieza BEFORE INSERT ON actividad WHEN NEW.detalle LIKE 'limpieza física %' BEGIN SELECT RAISE(FAIL, 'fallo limpieza ficticio'); END")
if not ("limpieza_pendiente" in eliminar_definitivamente(req, documento).headers["location"]):
    raise AssertionError()
assert not (STORAGE_DIR / nombre).exists()
with conectar() as db:
    tarea = db.execute("SELECT id,estado FROM eliminaciones_pendientes WHERE nombre=?", (nombre,)).fetchone()
    assert tarea["estado"] == "pendiente"
    db.execute("DROP TRIGGER fallo_limpieza")
if not (procesar_tarea(tarea["id"]) == "completada"):
    raise AssertionError()
with conectar() as db:
    assert db.execute("SELECT COUNT(*) FROM actividad WHERE entidad_id=? AND detalle LIKE 'limpieza física completada%'", (documento,)).fetchone()[0] == 1
