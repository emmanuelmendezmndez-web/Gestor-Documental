"""Casos de integración lanzados por test_respaldo en un proceso aislado."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from unittest.mock import patch
import zipfile

from aislamiento import exigir_directorio_temporal

exigir_directorio_temporal("siged-prueba-respaldo-")

import httpx

from app import respaldo
from app.configuracion import DATA_DIR, STORAGE_DIR
from app.database import conectar, inicializar_db
from app.seguridad import hashear_password

inicializar_db()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
with conectar() as db:
    db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) VALUES(?,?,?,?,?)",
               ("adminrespaldo", "Administrador ficticio", hashear_password("ClavePrueba123!"), "admin", "Tesorería"))

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    puerto = sock.getsockname()[1]
base = f"http://127.0.0.1:{puerto}"
python_real = Path(sys.base_prefix) / "python.exe"
python_servidor = str(python_real) if os.name == "nt" and python_real.is_file() else sys.executable
entorno_servidor = os.environ.copy()
if python_servidor != sys.executable:
    entorno_servidor["PYTHONPATH"] = os.pathsep.join((str(Path(sys.prefix) / "Lib" / "site-packages"), entorno_servidor.get("PYTHONPATH", "")))
servidor = subprocess.Popen([python_servidor, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "error"],
    env=entorno_servidor, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

try:
    with httpx.Client(base_url=base, trust_env=False, timeout=30, follow_redirects=False) as cliente:
        for _ in range(120):
            if servidor.poll() is not None:
                raise RuntimeError("Servidor temporal terminó")
            try:
                respuesta = cliente.get("/login")
                if respuesta.status_code == 200:
                    break
            except httpx.RequestError:
                time.sleep(.2)
        else:
            raise RuntimeError("Servidor temporal no respondió")
        token = re.search(r'<meta name="csrf-token" content="([^"]+)', respuesta.text).group(1)
        respuesta = cliente.post("/login", data={"usuario": "adminrespaldo", "password": "ClavePrueba123!", "csrf_token": token})
        assert respuesta.status_code == 303
        token = re.search(r'<meta name="csrf-token" content="([^"]+)', cliente.get("/inicio").text).group(1)

        def post(ruta, datos=None, **kwargs):
            return cliente.post(ruta, data={**(datos or {}), "csrf_token": token}, **kwargs)

        def subir(titulo, contenido):
            r = post("/subir", {"titulo": titulo, "categoria": "Otros"}, files={"archivo": (titulo + ".txt", contenido, "text/plain")})
            assert r.status_code == 303 and "subido" in r.headers["location"], (r.status_code, r.text)
            with conectar() as db:
                return dict(db.execute("SELECT id,nombre_guardado FROM documentos WHERE titulo=?", (titulo,)).fetchone())

        original = subir("original", b"contenido original ficticio")
        inicio = threading.Event()
        continuar = threading.Event()
        resultado = {}
        agregar = respaldo._agregar_archivo

        def ejecutar_con_pausa(destino, nombre):
            inicio.clear()
            continuar.clear()
            resultado.clear()
            def copiar(archive, miembro, path, kind):
                if miembro == "storage/" + nombre:
                    inicio.set()
                    if not continuar.wait(30):
                        raise TimeoutError("La prueba no recibió señal de continuación")
                return agregar(archive, miembro, path, kind)
            def trabajo():
                try:
                    resultado["ruta"] = respaldo.crear_respaldo(destino)
                except BaseException as error:
                    resultado["error"] = error
                    resultado["trace"] = traceback.format_exc()
            parche = patch.object(respaldo, "_agregar_archivo", side_effect=copiar)
            parche.start()
            hilo = threading.Thread(target=trabajo)
            hilo.start()
            for _ in range(300):
                if inicio.wait(.1) or not hilo.is_alive():
                    break
            if not inicio.is_set():
                continuar.set()
                hilo.join(5)
                parche.stop()
                raise AssertionError(f"No comenzó la copia del archivo: {resultado!r}")
            return hilo, parche

        destino = DATA_DIR / "concurrente.zip"
        hilo, parche = ejecutar_con_pausa(destino, original["nombre_guardado"])
        try:
            if not (post(f'/documentos/{original["id"]}/eliminar').status_code == 303):
                raise AssertionError()
            if not (post(f'/documentos/{original["id"]}/restaurar').status_code == 303):
                raise AssertionError()
            nuevo = subir("nuevo", b"contenido nuevo ficticio")
        finally:
            continuar.set()
            hilo.join(60)
            parche.stop()
        assert not hilo.is_alive() and "error" not in resultado, resultado
        respaldo.validar_respaldo(destino)
        with tempfile.TemporaryDirectory(dir=DATA_DIR) as extraido:
            carpeta = Path(extraido)
            respaldo.validar_respaldo(destino, carpeta)
            with closing(sqlite3.connect(carpeta / "database" / "gestor.db")) as db:
                titulos = {fila[0] for fila in db.execute("SELECT titulo FROM documentos")}
            assert "original" in titulos and "nuevo" not in titulos
            assert (carpeta / "storage" / original["nombre_guardado"]).read_bytes() == b"contenido original ficticio"

        # La restauración se ejecuta con SIGED detenido en otro directorio de prueba.
        with tempfile.TemporaryDirectory(prefix="siged-destino-restauracion-") as destino_raiz:
            entorno = os.environ.copy()
            entorno["GESTOR_DATA_DIR"] = destino_raiz
            codigo = '''
import sys
from aislamiento import exigir_directorio_temporal
exigir_directorio_temporal('siged-destino-restauracion-')
from app.configuracion import STORAGE_DIR
from app.database import inicializar_db, conectar
from app.respaldo import restaurar_respaldo
inicializar_db(); STORAGE_DIR.mkdir(parents=True, exist_ok=True)
restaurar_respaldo(__import__('pathlib').Path(sys.argv[1]))
with conectar() as db:
    fila = db.execute("SELECT nombre_guardado FROM documentos WHERE titulo='original'").fetchone()
    assert fila is not None and (STORAGE_DIR / fila['nombre_guardado']).read_bytes() == b'contenido original ficticio'
    assert db.execute("SELECT COUNT(*) FROM documentos WHERE titulo='nuevo'").fetchone()[0] == 0
'''
            entorno["PYTHONPATH"] = os.pathsep.join((str(Path(__file__).resolve().parent), entorno.get("PYTHONPATH", "")))
            subprocess.run([sys.executable, "-c", codigo, str(destino)], env=entorno, check=True, timeout=60)

        # Si un archivo desaparece tras la captura de SQLite, no se publica un ZIP.
        destino_fallido = DATA_DIR / "eliminacion-concurrente.zip"
        hilo, parche = ejecutar_con_pausa(destino_fallido, nuevo["nombre_guardado"])
        try:
            if not (post(f'/documentos/{nuevo["id"]}/eliminar').status_code == 303):
                raise AssertionError()
            if not (post(f'/documentos/{nuevo["id"]}/eliminar-definitivamente').status_code == 303):
                raise AssertionError()
        finally:
            continuar.set()
            hilo.join(60)
            parche.stop()
        assert not hilo.is_alive() and "error" in resultado and not destino_fallido.exists(), resultado

        # Las referencias que ya faltan no pueden generar ni validar un respaldo exitoso.
        with conectar() as db:
            faltante = db.execute("INSERT INTO documentos(titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes) VALUES(?,?,?,?,?)",
                                  ("ausente", "ausente.txt", "ausente.txt", "Otros", 4)).lastrowid
        try:
            respaldo.crear_respaldo(DATA_DIR / "faltante.zip")
            raise AssertionError("Se aceptó un documento faltante")
        except ValueError as error:
            assert "Falta en el respaldo" in str(error)
        assert not (DATA_DIR / "faltante.zip").exists()
        with conectar() as db:
            db.execute("DELETE FROM documentos WHERE id=?", (faltante,))

        for tabla, columna, subcarpeta in (("usuarios", "foto_perfil", "perfiles"), ("avisos", "imagen_guardada", "avisos")):
            with conectar() as db:
                if tabla == "usuarios":
                    db.execute("UPDATE usuarios SET foto_perfil=? WHERE usuario='adminrespaldo'", ("ausente.png",))
                else:
                    db.execute("INSERT INTO avisos(titulo,imagen_guardada) VALUES(?,?)", ("Aviso ficticio", "ausente.png"))
            try:
                respaldo.crear_respaldo(DATA_DIR / f"faltante-{subcarpeta}.zip")
                raise AssertionError(f"Se aceptó un archivo faltante en {subcarpeta}")
            except ValueError as error:
                assert f"storage/{subcarpeta}/ausente.png" in str(error)
            with conectar() as db:
                if tabla == "usuarios":
                    db.execute("UPDATE usuarios SET foto_perfil=NULL WHERE usuario='adminrespaldo'")
                else:
                    db.execute("DELETE FROM avisos WHERE titulo='Aviso ficticio'")

        # Un documento de longitud distinta tampoco se considera consistente.
        with conectar() as db:
            db.execute("UPDATE documentos SET tamano_bytes=tamano_bytes+1 WHERE id=?", (original["id"],))
        try:
            respaldo.crear_respaldo(DATA_DIR / "tamano-incorrecto.zip")
            raise AssertionError("Se aceptó una longitud distinta a la base")
        except ValueError as error:
            assert "tamaño" in str(error)
        with conectar() as db:
            db.execute("UPDATE documentos SET tamano_bytes=tamano_bytes-1 WHERE id=?", (original["id"],))
            db.execute("UPDATE documentos SET nombre_guardado='' WHERE id=?", (original["id"],))
        try:
            respaldo.crear_respaldo(DATA_DIR / "nombre-vacio.zip")
            raise AssertionError("Se aceptó un documento sin nombre de archivo")
        except ValueError as error:
            assert "Nombre de archivo no seguro" in str(error)
        with conectar() as db:
            db.execute("UPDATE documentos SET nombre_guardado=? WHERE id=?", (original["nombre_guardado"], original["id"]))

        # Errores de E/S e interrupciones dejan el destino sin publicar.
        for tipo in (OSError("fallo ficticio"), KeyboardInterrupt()):
            incompleto = DATA_DIR / ("error-escritura.zip" if isinstance(tipo, OSError) else "interrumpido.zip")
            try:
                with patch.object(respaldo, "_agregar_archivo", side_effect=tipo):
                    respaldo.crear_respaldo(incompleto)
                raise AssertionError("No se propagó el error")
            except (OSError, KeyboardInterrupt):
                pass
            assert not incompleto.exists() and not list(DATA_DIR.glob(".siged-respaldo-*.tmp"))

        # Una terminación abrupta puede dejar un temporal, pero nunca el ZIP final.
        codigo = '''
import os
from app import respaldo
from app.configuracion import DATA_DIR
original = respaldo._agregar_archivo
def bloquear(archive, nombre, path, kind):
    if nombre.startswith('storage/'):
        (DATA_DIR / 'prueba-pausada.flag').write_text('pausada')
        os._exit(23)
    return original(archive, nombre, path, kind)
respaldo._agregar_archivo = bloquear
respaldo.crear_respaldo(DATA_DIR / 'proceso-interrumpido.zip')
'''
        proceso = subprocess.Popen([sys.executable, "-c", codigo], env=os.environ.copy(), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        marca = DATA_DIR / "prueba-pausada.flag"
        if not (proceso.wait(timeout=60) == 23):
            raise AssertionError()
        assert marca.exists(), "El proceso de prueba no comenzó a copiar"
        assert not (DATA_DIR / "proceso-interrumpido.zip").exists()
        marca.unlink(missing_ok=True)
        for temporal in DATA_DIR.glob(".siged-respaldo-*.tmp"):
            temporal.unlink()

        # Un ZIP de formato 1 anterior conserva compatibilidad si contiene sus referencias.
        with zipfile.ZipFile(destino) as anterior:
            manifiesto = json.loads(anterior.read("manifest.json"))
            assert manifiesto["format_version"] == 1
            datos = {nombre: anterior.read(nombre) for nombre in anterior.namelist() if not nombre.endswith("/") and nombre != "manifest.json"}
        antiguo = DATA_DIR / "formato-anterior.zip"
        with zipfile.ZipFile(antiguo, "w", compression=zipfile.ZIP_DEFLATED) as archivo:
            archivo.writestr("storage/", b"")
            for nombre, contenido in datos.items():
                assert hashlib.sha256(contenido).hexdigest() == manifiesto["files"][nombre]["sha256"]
                archivo.writestr(nombre, contenido)
            archivo.writestr("manifest.json", json.dumps(manifiesto))
        respaldo.validar_respaldo(antiguo)
        # Un ZIP antiguo con manifiesto internamente correcto pero sin un documento se rechaza.
        miembro_faltante = "storage/" + original["nombre_guardado"]
        manifiesto["files"].pop(miembro_faltante)
        incompleto = DATA_DIR / "antiguo-incompleto.zip"
        with zipfile.ZipFile(incompleto, "w") as archivo:
            archivo.writestr("storage/", b"")
            for nombre, contenido in datos.items():
                if nombre != miembro_faltante:
                    archivo.writestr(nombre, contenido)
            archivo.writestr("manifest.json", json.dumps(manifiesto))
        try:
            respaldo.validar_respaldo(incompleto)
            raise AssertionError("Se aceptó el respaldo anterior incompleto")
        except ValueError as error:
            assert "Falta en el respaldo" in str(error)
        print("OK: subida, papelera, restauración y eliminación concurrentes; validación, restauración aislada, faltantes e interrupciones")
finally:
    servidor.terminate()
    servidor.wait(timeout=10)
