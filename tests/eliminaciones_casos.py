"""Casos destructivos restringidos a la base y storage temporales de la prueba."""

import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from aislamiento import exigir_directorio_temporal

exigir_directorio_temporal("siged-prueba-eliminaciones-")

import httpx
from fastapi import HTTPException, UploadFile
from starlette.requests import Request

from app.configuracion import DATA_DIR, STORAGE_DIR, AVISOS_DIR, FOTOS_PERFIL_DIR
from app.database import conectar, inicializar_db
from app.eliminaciones import descartar_generado, encolar, procesar_tarea
from app.rutas_avisos import eliminar_aviso
from app.rutas_cuenta import actualizar_perfil
from app.rutas_papelera import eliminar_definitivamente, eliminar_documentos_seleccionados, vaciar_papelera
from app.rutas_usuarios import eliminar_usuario
from app.respaldo import crear_respaldo, validar_respaldo
from app.seguridad import hashear_password
from app.servicios import papelera as servicio_papelera
from app.servicios.avisos import crear_aviso_servicio

inicializar_db()
for carpeta in (STORAGE_DIR, AVISOS_DIR, FOTOS_PERFIL_DIR):
    carpeta.mkdir(parents=True, exist_ok=True)
with conectar() as db:
    admin = db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) VALUES(?,?,?,?,?)",
                       ("adminprueba", "Admin Prueba", hashear_password("ClavePrueba123!"), "admin", "Tesorería")).lastrowid

# Migración repetible a partir de una base anterior con datos ficticios.
with conectar() as db:
    db.execute("DROP TABLE eliminaciones_pendientes")
inicializar_db()
inicializar_db()
with conectar() as db:
    assert db.execute("SELECT usuario FROM usuarios WHERE id=?", (admin,)).fetchone()[0] == "adminprueba"
    assert db.execute("SELECT name FROM sqlite_master WHERE name='eliminaciones_pendientes'").fetchone()

usuario = {"id": admin, "usuario": "adminprueba", "nombre": "Admin Prueba", "rol": "admin", "departamento": "Tesorería", "correo": "", "telefono": "", "foto_perfil": None}
request = Request({"type": "http", "method": "POST", "path": "/prueba", "headers": [], "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8000), "scheme": "http", "query_string": b"", "session": {"usuario_id": admin, "version": 0}})
request.state.usuario = usuario


def documento(nombre, existe=True, eliminado=True):
    ruta = STORAGE_DIR / (nombre + ".txt")
    if existe:
        ruta.write_bytes(b"documento ficticio")
    with conectar() as db:
        ident = db.execute("INSERT INTO documentos(titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes,eliminado_en) VALUES(?,?,?,?,?,?)",
            (nombre, ruta.name, ruta.name, "Otros", len(b"documento ficticio"), "2026-01-01" if eliminado else None)).lastrowid
    return ident, ruta


def tarea(nombre):
    with conectar() as db:
        return dict(db.execute("SELECT * FROM eliminaciones_pendientes WHERE nombre=? ORDER BY id DESC", (nombre,)).fetchone())


def permiso_denegado(rutas):
    original = Path.unlink
    bloqueadas = {p.resolve() for p in rutas}
    def unlink(ruta, *args, **kwargs):
        if ruta.resolve() in bloqueadas:
            raise PermissionError("bloqueo ficticio")
        return original(ruta, *args, **kwargs)
    return patch.object(Path, "unlink", unlink)


ident, archivo = documento("individual")
assert "eliminado_definitivo" in eliminar_definitivamente(request, ident).headers["location"]
assert not archivo.exists() and tarea(archivo.name)["estado"] == "completada"
assert procesar_tarea(tarea(archivo.name)["id"]) == "completada"

ident, archivo = documento("rollback")
with patch.object(servicio_papelera, "encolar", side_effect=RuntimeError("fallo ficticio")):
    try:
        eliminar_definitivamente(request, ident)
        raise AssertionError("La transacción no propagó el fallo")
    except RuntimeError:
        pass
with conectar() as db:
    assert db.execute("SELECT 1 FROM documentos WHERE id=?", (ident,)).fetchone() and archivo.exists()
assert "eliminado_definitivo" in eliminar_definitivamente(request, ident).headers["location"]

ident, archivo = documento("bloqueado")
with permiso_denegado([archivo]):
    assert "limpieza_pendiente" in eliminar_definitivamente(request, ident).headers["location"]
pendiente = tarea(archivo.name)
assert archivo.exists() and pendiente["estado"] == "pendiente" and pendiente["intentos"] == 1
assert procesar_tarea(pendiente["id"]) == "completada" and not archivo.exists()

a, pa = documento("lote_uno")
b, pb = documento("lote_dos")
with permiso_denegado([pb]):
    assert "limpieza_pendiente" in eliminar_documentos_seleccionados(request, [a, b]).headers["location"]
assert not pa.exists() and pb.exists() and tarea(pb.name)["estado"] == "pendiente"
with conectar() as db:
    assert db.execute("SELECT resultado FROM actividad WHERE accion='eliminar_definitivo' AND entidad_id=?", (b,)).fetchone()[0] == "fallo"
assert procesar_tarea(tarea(pb.name)["id"]) == "completada"

a, pa = documento("vaciar_uno")
b, pb = documento("vaciar_dos")
with permiso_denegado([pb]):
    assert "limpieza_pendiente" in vaciar_papelera(request, "ClavePrueba123!").headers["location"]
assert not pa.exists() and pb.exists() and tarea(pb.name)["estado"] == "pendiente"

ident, archivo = documento("noexiste", existe=False)
assert "eliminado_definitivo" in eliminar_definitivamente(request, ident).headers["location"]
assert tarea(archivo.name)["estado"] == "completada"

# Un archivo activo no puede purgarse; tampoco uno con referencia creada tras encolar.
ident, archivo = documento("activo", eliminado=False)
try:
    eliminar_definitivamente(request, ident)
    raise AssertionError("Se aceptó un documento activo")
except HTTPException as exc:
    assert exc.status_code == 404 and archivo.exists()
with conectar() as db:
    db.execute("BEGIN IMMEDIATE")
    t = encolar(db, "documento", archivo.name)
assert procesar_tarea(t) == "cancelada" and archivo.exists()
descartar_generado("documento", archivo.name)
assert tarea(archivo.name)["estado"] == "cancelada" and archivo.exists()

# Las rutas manipuladas quedan suspendidas y no se intentan borrar.
with conectar() as db:
    db.execute("BEGIN IMMEDIATE")
    t = encolar(db, "documento", "../fuera.txt")
assert procesar_tarea(t) == "suspendida"
fuera = DATA_DIR / "fuera.txt"
fuera.write_bytes(b"no borrar")
with conectar() as db:
    db.execute("BEGIN IMMEDIATE")
    t = encolar(db, "documento", str(fuera))
assert procesar_tarea(t) == "suspendida" and fuera.read_bytes() == b"no borrar"

foto = FOTOS_PERFIL_DIR / "compartida.png"
foto.write_bytes(b"foto compartida")
with conectar() as db:
    db.execute("UPDATE usuarios SET foto_perfil=? WHERE id=?", (foto.name, admin))
    otro = db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento,foto_perfil) VALUES(?,?,?,?,?,?)",
        ("otro", "Otro", hashear_password("ClavePrueba123!"), "lector", "Tesorería", foto.name)).lastrowid
request.state.usuario = {**usuario, "foto_perfil": foto.name}
assert "perfil_actualizado" in actualizar_perfil(request, nombre="Admin Prueba", correo="", telefono="", foto=None, quitar_foto=True).headers["location"]
assert foto.exists() and tarea(foto.name)["estado"] == "cancelada"
with conectar() as db:
    assert db.execute("SELECT foto_perfil FROM usuarios WHERE id=?", (otro,)).fetchone()[0] == foto.name

foto_propia = FOTOS_PERFIL_DIR / "cuenta.png"
foto_propia.write_bytes(b"foto de cuenta")
with conectar() as db:
    eliminado = db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento,foto_perfil,activo) VALUES(?,?,?,?,?,?,0)",
        ("borrable", "Borrable", hashear_password("ClavePrueba123!"), "lector", "Tesorería", foto_propia.name)).lastrowid
request.state.usuario = usuario
assert "usuario_eliminado" in eliminar_usuario(request, eliminado).headers["location"]
assert not foto_propia.exists() and tarea(foto_propia.name)["estado"] == "completada"

foto_bloqueada = FOTOS_PERFIL_DIR / "bloqueada.png"
foto_bloqueada.write_bytes(b"foto bloqueada")
with conectar() as db:
    eliminado = db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento,foto_perfil,activo) VALUES(?,?,?,?,?,?,0)",
        ("borrable2", "Borrable Dos", hashear_password("ClavePrueba123!"), "lector", "Tesorería", foto_bloqueada.name)).lastrowid
with permiso_denegado([foto_bloqueada]):
    assert "usuario_limpieza_pendiente" in eliminar_usuario(request, eliminado).headers["location"]
assert foto_bloqueada.exists() and tarea(foto_bloqueada.name)["estado"] == "pendiente"
assert procesar_tarea(tarea(foto_bloqueada.name)["id"]) == "completada"

foto_usuario = FOTOS_PERFIL_DIR / "perfil-bloqueado.png"
foto_usuario.write_bytes(b"foto perfil")
with conectar() as db:
    db.execute("UPDATE usuarios SET foto_perfil=? WHERE id=?", (foto_usuario.name, admin))
request.state.usuario = {**usuario, "foto_perfil": foto_usuario.name}
with permiso_denegado([foto_usuario]):
    assert "perfil_limpieza_pendiente" in actualizar_perfil(request, nombre="Admin Prueba", correo="", telefono="", foto=None, quitar_foto=True).headers["location"]
assert foto_usuario.exists() and tarea(foto_usuario.name)["estado"] == "pendiente"
assert procesar_tarea(tarea(foto_usuario.name)["id"]) == "completada"
request.state.usuario = usuario

banner = AVISOS_DIR / "cartel.png"
banner.write_bytes(b"cartel ficticio")
with conectar() as db:
    aviso = db.execute("INSERT INTO avisos(titulo,imagen_guardada) VALUES(?,?)", ("Aviso", banner.name)).lastrowid
with permiso_denegado([banner]):
    assert "limpieza_pendiente" in eliminar_aviso(request, aviso).headers["location"]
assert banner.exists() and tarea(banner.name)["estado"] == "pendiente"
assert procesar_tarea(tarea(banner.name)["id"]) == "completada"

anteriores = set(AVISOS_DIR.iterdir())
imagen_falsa = UploadFile(filename="falsa.png", file=BytesIO(b"imagen no valida"))
assert crear_aviso_servicio(request, "Aviso inválido", "", "", 1, imagen_falsa, AVISOS_DIR) == "aviso_imagen_formato"
assert set(AVISOS_DIR.iterdir()) == anteriores

# Una interrupción después del commit deja la tarea para que otro proceso la reanude.
ident, archivo = documento("interrumpido")
codigo = '''
import os,sys
from starlette.requests import Request
from app.configuracion import STORAGE_DIR
import app.servicios.papelera as servicio
r=Request({'type':'http','method':'POST','path':'/','headers':[],'client':('127.0.0.1',1),'server':('127.0.0.1',8000),'scheme':'http','query_string':b'','session':{'usuario_id':int(sys.argv[2]),'version':0}})
r.state.usuario={'id':int(sys.argv[2]),'usuario':'adminprueba','rol':'admin'}
servicio.procesar_tareas=lambda ids: os._exit(39)
servicio.purgar_documentos_papelera(r, STORAGE_DIR, [int(sys.argv[1])], individual=True)
'''
assert subprocess.run([sys.executable, "-c", codigo, str(ident), str(admin)], env=os.environ.copy(), timeout=40).returncode == 39
assert archivo.exists() and tarea(archivo.name)["estado"] == "pendiente"
assert procesar_tarea(tarea(archivo.name)["id"]) == "completada" and not archivo.exists()

# Reutilización de nombre: una identidad diferente no debe eliminarse.
ident, archivo = documento("reutilizado")
with permiso_denegado([archivo]):
    eliminar_definitivamente(request, ident)
pendiente = tarea(archivo.name)
archivo.unlink()
archivo.write_bytes(b"nuevo archivo con nombre reutilizado")
assert procesar_tarea(pendiente["id"]) == "suspendida" and archivo.read_bytes() == b"nuevo archivo con nombre reutilizado"

# Otro proceso mantiene la transacción mientras crea una referencia.
comp = FOTOS_PERFIL_DIR / "concurrente.png"
comp.write_bytes(b"foto concurrente")
with conectar() as db:
    db.execute("BEGIN IMMEDIATE")
    t = encolar(db, "foto", comp.name)
listo = DATA_DIR / "lock-listo"
liberar = DATA_DIR / "lock-liberar"
codigo = '''
import sys,time
from pathlib import Path
from app.database import conectar
with conectar() as db:
 db.execute('BEGIN IMMEDIATE')
 db.execute('UPDATE usuarios SET foto_perfil=? WHERE id=?',(sys.argv[1],int(sys.argv[2])))
 Path(sys.argv[3]).write_text('listo')
 while not Path(sys.argv[4]).exists(): time.sleep(.05)
'''
hijo = subprocess.Popen([sys.executable, "-c", codigo, comp.name, str(admin), str(listo), str(liberar)], env=os.environ.copy(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
for _ in range(400):
    if listo.exists() or hijo.poll() is not None:
        break
    time.sleep(.05)
assert listo.exists()
resultado = {}
hilo = threading.Thread(target=lambda: resultado.update(estado=procesar_tarea(t)))
hilo.start()
time.sleep(.2)
assert hilo.is_alive(), "El bloqueo SQLite no coordinó la transacción entre procesos"
liberar.write_text("continuar")
assert hijo.wait(timeout=20) == 0
hilo.join(20)
assert resultado.get("estado") == "cancelada" and comp.exists()

# El respaldo incluye tareas pendientes; al restaurar ninguna puede ejecutarse automáticamente.
ident, archivo = documento("pendiente_respaldo")
with permiso_denegado([archivo]):
    eliminar_definitivamente(request, ident)
pendiente = tarea(archivo.name)
zip_path = crear_respaldo(DATA_DIR / "copia.zip")
validar_respaldo(zip_path)
with tempfile.TemporaryDirectory(prefix="siged-destino-cola-") as carpeta:
    entorno = os.environ.copy()
    entorno["GESTOR_DATA_DIR"] = carpeta
    codigo = '''
import sys
from pathlib import Path
from aislamiento import exigir_directorio_temporal
exigir_directorio_temporal('siged-destino-cola-')
from app.configuracion import DATA_DIR, STORAGE_DIR
from app.database import inicializar_db, conectar
from app.respaldo import restaurar_respaldo
from app.eliminaciones import procesar_tarea, reintentar_pendientes
inicializar_db(); STORAGE_DIR.mkdir(parents=True,exist_ok=True)
restaurar_respaldo(Path(sys.argv[1]))
archivo=STORAGE_DIR / sys.argv[2]
assert archivo.exists()
archivo.unlink(); archivo.write_bytes(b'archivo nuevo de nombre reutilizado')
with conectar() as db:
 fila=db.execute('SELECT estado FROM eliminaciones_pendientes WHERE id=?',(int(sys.argv[3]),)).fetchone()
assert fila['estado']=='suspendida'
assert procesar_tarea(int(sys.argv[3]))=='suspendida'
reintentar_pendientes()
assert archivo.read_bytes()==b'archivo nuevo de nombre reutilizado'
'''
    entorno["PYTHONPATH"] = os.pathsep.join((str(Path(__file__).resolve().parent), entorno.get("PYTHONPATH", "")))
    subprocess.run([sys.executable, "-c", codigo, str(zip_path), archivo.name, str(pendiente["id"])], env=entorno, check=True, timeout=60)

# Regresión HTTP con CSRF y fallo físico inyectado en un servidor aislado.
ident, archivo = documento("http-bloqueado")
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    puerto = sock.getsockname()[1]
entorno_http = os.environ.copy()
interprete_real = Path(sys.base_prefix) / "python.exe"
interprete = str(interprete_real) if os.name == "nt" and interprete_real.is_file() else sys.executable
if interprete != sys.executable:
    entorno_http["PYTHONPATH"] = os.pathsep.join((str(Path(sys.prefix) / "Lib" / "site-packages"), entorno_http.get("PYTHONPATH", "")))
codigo = '''
import sys
from pathlib import Path
import uvicorn
from app.main import app
original=Path.unlink
def falso(self,*args,**kwargs):
 if self.name=='http-bloqueado.txt': raise PermissionError('bloqueo ficticio')
 return original(self,*args,**kwargs)
Path.unlink=falso
uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[1]),log_level='error')
'''
servidor = subprocess.Popen([interprete, "-c", codigo, str(puerto)], env=entorno_http, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
try:
    with httpx.Client(base_url=f"http://127.0.0.1:{puerto}", trust_env=False, timeout=20, follow_redirects=False) as cliente:
        for _ in range(200):
            if servidor.poll() is not None:
                raise RuntimeError("El servidor de prueba terminó")
            try:
                respuesta = cliente.get('/login')
                if respuesta.status_code == 200:
                    break
            except httpx.RequestError:
                time.sleep(.1)
        else:
            raise RuntimeError("El servidor de prueba no respondió")
        token = re.search(r'<meta name="csrf-token" content="([^"]+)', respuesta.text).group(1)
        assert cliente.post('/login', data={'usuario':'adminprueba','password':'ClavePrueba123!','csrf_token':token}).status_code == 303
        token = re.search(r'<meta name="csrf-token" content="([^"]+)', cliente.get('/inicio').text).group(1)
        assert cliente.post(f'/documentos/{ident}/eliminar-definitivamente').status_code == 403
        respuesta = cliente.post(f'/documentos/{ident}/eliminar-definitivamente', data={'csrf_token':token})
        assert respuesta.status_code == 303 and 'limpieza_pendiente' in respuesta.headers['location']
        assert archivo.exists() and tarea(archivo.name)['estado'] == 'pendiente'
finally:
    servidor.terminate()
    servidor.wait(timeout=15)

print("OK: cola, permisos, interrupción, referencias compartidas, procesos, migración, restauración y HTTP")
