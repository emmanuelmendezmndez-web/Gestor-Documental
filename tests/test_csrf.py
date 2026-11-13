"""Pruebas HTTP CSRF: servidor y base exclusivos con datos ficticios."""

import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing

import httpx

RAIZ = Path(__file__).resolve().parents[1]


class CsrfHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="siged-csrf-")
        cls.env = os.environ.copy()
        cls.env.update(GESTOR_DATA_DIR=cls.temp.name, GESTOR_SECRET_KEY="clave-ficticia-para-pruebas-csrf-123456",
                       PYTHONPATH=os.pathsep.join((str(RAIZ / "tests"), str(RAIZ))))
        preparar = '''
from aislamiento import exigir_directorio_temporal
exigir_directorio_temporal('siged-csrf-')
from app.database import inicializar_db, conectar
from app.seguridad import hashear_password
with conectar() as db:
    db.execute("""CREATE TABLE avisos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL,
        cuerpo TEXT NOT NULL DEFAULT '', imagen_guardada TEXT UNIQUE,
        imagen_nombre TEXT, departamento TEXT NOT NULL DEFAULT '',
        autor_id INTEGER, publicado INTEGER NOT NULL DEFAULT 1,
        fecha_creacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("INSERT INTO avisos(titulo) VALUES ('Comunicado anterior a la migración')")
inicializar_db()
with conectar() as db:
    for usuario, rol in [('admincsrf','admin'), ('lectorcsrf','lector')]:
        db.execute('INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) VALUES(?,?,?,?,?)',
                   (usuario, usuario, hashear_password('ClavePrueba123!'), rol, 'Tesorería'))
'''
        subprocess.run([sys.executable, "-c", preparar], cwd=RAIZ, env=cls.env, check=True, timeout=60)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            puerto = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{puerto}"
        # En Windows el ejecutable del venv es un lanzador que crea otro proceso;
        # terminarlo no termina el servidor hijo ni libera su bloqueo.
        python_real = Path(sys.base_prefix) / "python.exe"
        python_servidor = str(python_real) if os.name == "nt" and python_real.is_file() else sys.executable
        entorno_servidor = cls.env.copy()
        if python_servidor != sys.executable:
            entorno_servidor["PYTHONPATH"] = os.pathsep.join((str(Path(sys.prefix) / "Lib" / "site-packages"), entorno_servidor["PYTHONPATH"]))
        cls.servidor = subprocess.Popen(
            [python_servidor, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "error"],
            cwd=RAIZ, env=entorno_servidor, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            with httpx.Client(trust_env=False, timeout=1) as cliente:
                for _ in range(120):
                    if cls.servidor.poll() is not None:
                        raise RuntimeError("El servidor de prueba terminó al arrancar")
                    try:
                        if cliente.get(cls.base + "/login").status_code == 200:
                            break
                    except httpx.RequestError:
                        time.sleep(.2)
                else:
                    raise RuntimeError("El servidor temporal no respondió")
        except BaseException:
            cls.servidor.terminate()
            cls.servidor.wait(timeout=10)
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.servidor.terminate()
        cls.servidor.wait(timeout=10)
        cls.temp.cleanup()

    def setUp(self):
        self.cliente = httpx.Client(base_url=self.base, follow_redirects=False, trust_env=False, timeout=30)
        self.addCleanup(self.cliente.close)

    def token(self, ruta="/inicio"):
        respuesta = self.cliente.get(ruta)
        self.assertEqual(respuesta.status_code, 200)
        coincidencia = re.search(r'<meta name="csrf-token" content="([^"]+)"', respuesta.text)
        self.assertIsNotNone(coincidencia)
        return coincidencia.group(1)

    def login(self, usuario="admincsrf"):
        token = self.token("/login")
        respuesta = self.cliente.post("/login", data={"usuario": usuario, "password": "ClavePrueba123!", "csrf_token": token})
        self.assertEqual(respuesta.status_code, 303)
        self.assertEqual(respuesta.headers["location"], "/inicio")
        return self.token()

    def test_login_exige_token_y_rota_en_sesion(self):
        token = self.token("/login")
        credenciales = {"usuario": "admincsrf", "password": "ClavePrueba123!"}
        self.assertEqual(self.cliente.post("/login", data=credenciales).status_code, 403)
        self.assertEqual(self.cliente.post("/login", data={**credenciales, "csrf_token": "incorrecto"}).status_code, 403)
        self.assertEqual(self.cliente.post("/login", data={**credenciales, "csrf_token": token}, headers={"Origin": "https://atacante.invalid"}).status_code, 403)
        self.assertEqual(self.cliente.post("/login", data={**credenciales, "csrf_token": token}, headers={"Origin": self.base}).status_code, 303)
        nuevo = self.token()
        self.assertNotEqual(token, nuevo)
        self.assertEqual(self.cliente.post("/salir", data={"csrf_token": token}).status_code, 403)
        self.assertEqual(self.cliente.post("/salir", data={"csrf_token": nuevo}).status_code, 303)
        self.assertEqual(self.cliente.get("/inicio").status_code, 303)

    def test_formulario_json_origen_y_permisos(self):
        token = self.login()
        for headers in ({}, {"X-CSRF-Token": "incorrecto"}, {"X-CSRF-Token": token, "Origin": "null"}, {"X-CSRF-Token": token, "Referer": "https://atacante.invalid/"}):
            r = self.cliente.post("/asistente/habito", json={"tipo": "seccion", "valor": "inicio"}, headers=headers)
            self.assertEqual(r.status_code, 403, headers)
        r = self.cliente.post("/asistente/habito", json={"tipo": "seccion", "valor": "inicio"}, headers={"X-CSRF-Token": token, "Origin": self.base})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["guardado"])
        self.assertEqual(self.cliente.post("/expedientes", data={"titulo": "No crear", "csrf_token": token}, headers={"Origin": "https://atacante.invalid"}).status_code, 403)
        duplicado = f"csrf_token={token}&csrf_token={token}&titulo=NoCrear"
        self.assertEqual(self.cliente.post("/expedientes", content=duplicado, headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code, 403)
        self.assertEqual(self.cliente.post("/expedientes", data={"csrf_token": "á", "titulo": "No crear"}).status_code, 403)
        with httpx.Client(base_url=self.base, trust_env=False) as otro:
            self.assertEqual(otro.post("/expedientes", data={"titulo": "No crear", "csrf_token": token}).status_code, 403)

    def test_todas_las_rutas_post_rechazan_sin_token(self):
        self.login()
        rutas = (
            "/salir", "/ajustes", "/asistente/habito", "/cuenta/perfil", "/cuenta/password",
            "/usuarios", "/usuarios/1/editar", "/usuarios/1/password", "/usuarios/1/estado", "/usuarios/1/eliminar",
            "/avisos", "/avisos/1/estado", "/avisos/1/vencimiento", "/avisos/1/eliminar", "/subir", "/documentos/1/editar",
            "/documentos/1/eliminar", "/documentos/papelera", "/documentos/1/restaurar", "/papelera/restaurar",
            "/papelera/eliminar-seleccionados", "/papelera/vaciar", "/documentos/1/eliminar-definitivamente",
            "/expedientes", "/expedientes/1/eliminar", "/expedientes/1/documentos", "/expedientes/1/documentos/1",
        )
        esquema = self.cliente.get("/openapi.json").json()
        declaradas = {
            re.sub(r"\{[^}]+\}", "1", ruta)
            for ruta, metodos in esquema["paths"].items()
            if "post" in metodos and ruta != "/login"
        }
        self.assertEqual(declaradas, set(rutas))
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.cliente.post(ruta).status_code, 403)

    def test_flujos_de_escritura(self):
        token = self.login()
        def post(ruta, data=None, **kwargs):
            return self.cliente.post(ruta, data={**(data or {}), "csrf_token": token}, **kwargs)
        r = post("/subir", {"titulo": "Documento CSRF", "categoria": "Otros"}, files={"archivo": ("prueba.txt", b"contenido ficticio", "text/plain")})
        self.assertTrue(r.headers.get("location", "").endswith("subido"), (r.status_code, r.text))
        with closing(sqlite_temporal(self.temp.name)) as db:
            ident = db.execute("SELECT id FROM documentos WHERE titulo='Documento CSRF'").fetchone()[0]
        r = post(f"/documentos/{ident}/editar", {"titulo": "Documento editado", "categoria": "Otros", "version": "1"})
        self.assertIn("editado", r.headers.get("location", ""))
        self.assertEqual(post(f"/documentos/{ident}/eliminar").status_code, 303)
        self.assertEqual(post(f"/documentos/{ident}/restaurar").status_code, 303)
        self.assertIn("documentos_papelera", post("/documentos/papelera", {"documento_ids": str(ident)}).headers.get("location", ""))
        self.assertIn("documentos_restaurados", post("/papelera/restaurar", {"documento_ids": str(ident)}).headers.get("location", ""))
        r = post("/avisos", {"titulo": "Aviso CSRF", "cuerpo": "Prueba"}, files={"imagen": ("cartel.png", b"\x89PNG\r\n\x1a\nprueba", "image/png")})
        self.assertIn("aviso_creado", r.headers.get("location", ""))
        r = post("/expedientes", {"titulo": "Expediente CSRF"})
        self.assertIn("expediente_creado", r.headers.get("location", ""))
        with closing(sqlite_temporal(self.temp.name)) as db:
            expediente = db.execute("SELECT id FROM expedientes WHERE titulo='Expediente CSRF'").fetchone()[0]
        r = post(f"/expedientes/{expediente}/documentos", {"documento_ids": str(ident)})
        self.assertIn("documentos_vinculados", r.headers.get("location", ""))
        self.assertEqual(post(f"/expedientes/{expediente}/eliminar").status_code, 303)
        self.assertEqual(post(f"/documentos/{ident}/eliminar").status_code, 303)
        self.assertEqual(post(f"/documentos/{ident}/eliminar-definitivamente").status_code, 303)

    def test_vencimiento_de_avisos(self):
        token = self.login()
        anterior = "Comunicado anterior a la migración"
        nuevo = "Comunicado con vencimiento"
        datos = {"csrf_token": token, "titulo": nuevo, "departamento": "Tesorería"}
        self.assertIn(anterior, self.cliente.get("/inicio").text)
        for invalida in ("", "0", "-1", "1.5", "3651"):
            r = self.cliente.post("/avisos", data={**datos, "duracion": "personalizada", "dias_personalizados": invalida})
            self.assertEqual(r.headers["location"], "/avisos?aviso=aviso_duracion")
        r = self.cliente.post("/avisos", data={**datos, "duracion": "3"})
        self.assertEqual(r.headers["location"], "/avisos?aviso=aviso_creado")
        with closing(sqlite_temporal(self.temp.name)) as db:
            self.assertIsNone(db.execute("SELECT vence_en FROM avisos WHERE titulo = ?", (anterior,)).fetchone()[0])
            filas = db.execute("SELECT id, vence_en - unixepoch('now') FROM avisos WHERE titulo = ?", (nuevo,)).fetchall()
            [(ident, segundos)] = filas
            self.assertAlmostEqual(segundos, 3 * 86400, delta=5)

        inicio = self.cliente.get("/inicio").text
        self.assertIn(nuevo, inicio)
        self.assertIn('data-segundos-vigente="', inicio)
        ruta = f"/avisos/{ident}/vencimiento"
        r = self.cliente.post(ruta, data={"csrf_token": token, "duracion": "personalizada", "dias_personalizados": "2"})
        self.assertEqual(r.headers["location"], "/avisos?aviso=aviso_vencimiento")
        with closing(sqlite_temporal(self.temp.name)) as db, db:
            segundos = db.execute("SELECT vence_en - unixepoch('now') FROM avisos WHERE id = ?", (ident,)).fetchone()[0]
            self.assertAlmostEqual(segundos, 2 * 86400, delta=5)
            db.execute("UPDATE avisos SET vence_en = unixepoch('now') WHERE id = ?", (ident,))
        inicio = self.cliente.get("/inicio").text
        self.assertNotIn(nuevo, inicio)
        self.assertIn(anterior, inicio)
        gestion = self.cliente.get("/avisos").text
        self.assertIn(nuevo, gestion)
        self.assertIn("Vencido", gestion)
        r = self.cliente.post(ruta, data={"csrf_token": token, "duracion": "sin_vencimiento"})
        self.assertEqual(r.headers["location"], "/avisos?aviso=aviso_vencimiento")
        self.assertIn(nuevo, self.cliente.get("/inicio").text)

    def test_creacion_de_usuario_en_pantalla_independiente(self):
        self.login()
        lista = self.cliente.get("/usuarios")
        self.assertIn('href="/usuarios/nuevo"', lista.text)
        self.assertNotIn('id="nuevo-usuario"', lista.text)
        formulario = self.cliente.get("/usuarios/nuevo")
        self.assertIn('action="/usuarios" method="post"', formulario.text)
        self.assertIn("Volver a Usuarios", formulario.text)
        datos = {
            "usuario": "cuenta-nueva", "nombre": "Cuenta de prueba", "rol": "lector",
            "departamento": "Tesorería", "password": "ClavePrueba123!",
            "confirmacion": "ClavePrueba123!", "csrf_token": self.token("/usuarios/nuevo"),
        }
        error = self.cliente.post("/usuarios", data={**datos, "confirmacion": "ClaveDistinta!"})
        self.assertEqual((error.status_code, error.headers["location"]),
                         (303, "/usuarios/nuevo?aviso=password_distinta"))
        self.assertIn("Las contraseñas no coinciden.", self.cliente.get(error.headers["location"]).text)
        creada = self.cliente.post("/usuarios", data=datos)
        self.assertEqual((creada.status_code, creada.headers["location"]),
                         (303, "/usuarios?aviso=usuario_creado"))
        confirmacion = self.cliente.get(creada.headers["location"])
        self.assertIn("Usuario creado correctamente.", confirmacion.text)
        self.assertIn("cuenta-nueva", confirmacion.text)
        duplicada = self.cliente.post("/usuarios", data=datos)
        self.assertEqual((duplicada.status_code, duplicada.headers["location"]),
                         (303, "/usuarios/nuevo?aviso=usuario_existe"))

    def test_ajustes_de_clippy_persisten_y_son_individuales(self):
        self.assertEqual(self.cliente.get("/ajustes").status_code, 303)
        token = self.login("lectorcsrf")
        habito = {"tipo": "seccion", "valor": "biblioteca"}
        cabeceras = {"X-CSRF-Token": token}
        self.assertTrue(self.cliente.post("/asistente/habito", json=habito, headers=cabeceras).json()["guardado"])
        self.assertIn("biblioteca", self.cliente.get("/asistente/preferencias").json()["secciones"])

        guardado = self.cliente.post("/ajustes", data={"csrf_token": token, "clippy_consejos": "1"})
        self.assertEqual((guardado.status_code, guardado.headers["location"]), (303, "/ajustes?guardado=1"))
        self.assertIn("Tus ajustes se guardaron.", self.cliente.get(guardado.headers["location"]).text)
        self.assertFalse(self.cliente.post("/asistente/habito", json=habito, headers=cabeceras).json()["guardado"])
        self.assertEqual(self.cliente.get("/asistente/preferencias").json()["secciones"], [])
        self.assertEqual(self.cliente.post("/salir", data={"csrf_token": token}).status_code, 303)

        token = self.login("lectorcsrf")
        inicio = self.cliente.get("/inicio").text
        self.assertNotIn("clippy_asistente.js", inicio)
        self.assertIn('id="abrir-busqueda-asistida"', inicio)
        self.assertIn('"registrarHabitos": false', inicio)
        with closing(sqlite_temporal(self.temp.name)) as db:
            ajustes = db.execute(
                "SELECT usuario, clippy_visible, clippy_consejos, clippy_habitos FROM usuarios "
                "WHERE usuario IN ('admincsrf', 'lectorcsrf') ORDER BY usuario"
            ).fetchall()
            self.assertEqual(ajustes, [("admincsrf", 1, 1, 1), ("lectorcsrf", 0, 1, 0)])
            self.assertEqual(db.execute(
                "SELECT veces FROM asistente_habitos JOIN usuarios ON usuarios.id = usuario_id "
                "WHERE usuario = 'lectorcsrf' AND tipo = 'seccion' AND valor = 'biblioteca'"
            ).fetchone()[0], 1)

        guardado = self.cliente.post("/ajustes", data={"csrf_token": token, "clippy_visible": "1", "clippy_habitos": "1"})
        self.assertEqual(guardado.status_code, 303)
        self.assertIn('data-consejos-automaticos="0"', self.cliente.get("/inicio").text)
        self.assertIn("biblioteca", self.cliente.get("/asistente/preferencias").json()["secciones"])

    def test_tema_se_guarda_por_usuario_y_se_renderiza_desde_el_inicio(self):
        token = self.login()
        datos = {"csrf_token": token, "clippy_visible": "1", "clippy_consejos": "1", "clippy_habitos": "1"}
        self.assertIn('data-tema="automatico"', self.cliente.get("/ajustes").text)
        for tema in ("claro", "automatico", "oscuro"):
            r = self.cliente.post("/ajustes", data={**datos, "tema": tema})
            self.assertEqual(r.status_code, 303)
            ajustes = self.cliente.get(r.headers["location"]).text
            self.assertIn(f'data-tema="{tema}"', ajustes)
            self.assertIn(f'value="{tema}" selected', ajustes)
        self.assertEqual(self.cliente.post("/ajustes", data={**datos, "tema": "invalido"}).status_code, 422)
        self.assertEqual(self.cliente.post("/salir", data={"csrf_token": token}).status_code, 303)
        token = self.login()
        self.assertIn('<html lang="es" data-tema="oscuro">', self.cliente.get("/inicio").text)
        self.assertEqual(self.cliente.post("/salir", data={"csrf_token": token}).status_code, 303)
        self.login("lectorcsrf")
        self.assertIn('<html lang="es" data-tema="automatico">', self.cliente.get("/inicio").text)

    def test_lector_sigue_sin_permiso(self):
        token = self.login("lectorcsrf")
        self.assertEqual(self.cliente.get("/usuarios/nuevo").status_code, 403)
        self.assertEqual(self.cliente.post("/avisos/1/vencimiento", data={"csrf_token": token, "duracion": "1"}).status_code, 403)
        r = self.cliente.post("/expedientes", data={"titulo": "No autorizado", "csrf_token": token})
        self.assertEqual(r.status_code, 403)


def sqlite_temporal(carpeta):
    import sqlite3
    return sqlite3.connect(Path(carpeta) / "gestor.db")


class FormulariosCsrfTest(unittest.TestCase):
    def test_todos_los_formularios_post_incluyen_token(self):
        total = 0
        for archivo in (RAIZ / "app" / "templates").glob("*.html"):
            texto = archivo.read_text(encoding="utf-8")
            for formulario in re.findall(r"<form\b[^>]*>.*?</form>", texto, re.I | re.S):
                apertura = formulario.split(">", 1)[0]
                if re.search(r"\bmethod\s*=\s*['\"]post['\"]", apertura, re.I):
                    total += 1
                    self.assertIn('name="csrf_token"', formulario, str(archivo))
        self.assertGreater(total, 15)
