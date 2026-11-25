"""Regresión HTTP con el servidor y SQLite ficticios del fixture CSRF."""

import json
import re
import shutil
import sqlite3
import subprocess
import unittest
from contextlib import closing
from pathlib import Path

import httpx
import test_csrf as soporte

from app.catalogos import CATEGORIAS, DEPARTAMENTOS
from app.servicios.clippy_propuestas import preparar_propuestas


class BusquedaClippyHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        soporte.CsrfHTTPTest.setUpClass()
        cls.fixture = soporte.CsrfHTTPTest
        cls.base = cls.fixture.base
        with closing(sqlite3.connect(Path(cls.fixture.temp.name) / "gestor.db")) as db, db:
            db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) SELECT 'editorcsrf','editorcsrf',password_hash,'editor','Tesorería' FROM usuarios WHERE usuario='lectorcsrf'")
            db.execute(
                "INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) "
                "SELECT 'revisioncsrf','revisioncsrf',password_hash,'lector','Tesorería' "
                "FROM usuarios WHERE usuario='lectorcsrf'"
            )
            db.executemany(
                "INSERT INTO documentos(titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes,numero_oficio,departamento,fecha_documento,eliminado_en) VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    ("Ficticio Tesoro", "t.txt", "t.txt", "Contratos", 1, "OF-123", "Tesorería", "2025-03-10", None),
                    ("Ficticio Humano", "h.txt", "h.txt", "Contratos", 1, "OF-123", "Recursos Humanos", "2025-03-10", None),
                    ("Ficticio Compartido", "c.txt", "c.txt", "Contratos", 1, "OF-123", "", "2025-03-10", None),
                    ("Ficticio Papelera", "p.txt", "p.txt", "Contratos", 1, "OF-123", "Tesorería", "2025-03-10", "2025-04-01"),
                ],
            )
            db.execute("INSERT INTO expedientes(folio,titulo) VALUES (?,?)", ("EXP-TEST", "Ficticio expediente"))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def setUp(self):
        self.client = httpx.Client(base_url=self.base, follow_redirects=False, trust_env=False, timeout=30)
        self.addCleanup(self.client.close)

    def login(self, usuario):
        login = self.client.get('/login')
        token = re.search(r'<meta name="csrf-token" content="([^"]+)"', login.text).group(1)
        respuesta = self.client.post('/login', data={'usuario': usuario, 'password': 'ClavePrueba123!', 'csrf_token': token})
        self.assertEqual(respuesta.status_code, 303)
        self.assertEqual(respuesta.headers['location'], '/inicio')
        return re.search(r'<meta name="csrf-token" content="([^"]+)"', self.client.get('/inicio').text).group(1)

    def test_global_y_filtros_asistidos_respetan_area_y_papelera(self):
        self.login('lectorcsrf')
        global_ = self.client.get('/buscar', params={'q': 'Ficticio'})
        self.assertEqual(global_.status_code, 200)
        for nombre in ('Ficticio Tesoro', 'Ficticio Compartido', 'Ficticio expediente'):
            self.assertIn(nombre, global_.text)
        for nombre in ('Ficticio Humano', 'Ficticio Papelera'):
            self.assertNotIn(nombre, global_.text)
        filtros = {'categoria': 'Contratos', 'oficio': 'OF-123', 'desde': '2025-03-01', 'hasta': '2025-03-31'}
        biblioteca = self.client.get('/', params=filtros)
        self.assertEqual(biblioteca.status_code, 200)
        self.assertIn('Ficticio Tesoro', biblioteca.text)
        self.assertIn('Ficticio Compartido', biblioteca.text)
        self.assertNotIn('Ficticio Humano', biblioteca.text)
        self.assertNotIn('Ficticio Papelera', biblioteca.text)
        self.assertIn('<details class="biblioteca-panel-filtros">', biblioteca.text)
        self.assertIn('Categoría: Contratos', biblioteca.text)
        self.assertIn('Desde: 2025-03-01', biblioteca.text)
        manipulada = self.client.get('/', params={**filtros, 'departamento': 'Recursos Humanos'})
        self.assertNotIn('Ficticio Humano', manipulada.text)
        with closing(sqlite3.connect(Path(self.fixture.temp.name) / 'gestor.db')) as db:
            ident = db.execute("SELECT id FROM documentos WHERE titulo='Ficticio Humano'").fetchone()[0]
        self.assertIn(self.client.get(f'/documentos/{ident}').status_code, (403, 404))

    def test_panel_de_biblioteca_con_y_sin_filtros(self):
        self.login('lectorcsrf')
        inicial = self.client.get('/')
        self.assertEqual(inicial.status_code, 200)
        self.assertIn('>Buscar y filtrar</summary>', inicial.text)
        self.assertNotIn('Filtros activos:', inicial.text)
        self.assertIn('href="/expedientes" title="Expedientes"', inicial.text)
        filtrada = self.client.get('/', params={'buscar':'Ficticio', 'categoria':'Contratos', 'orden':'titulo_asc'})
        self.assertEqual(filtrada.status_code, 200)
        self.assertIn('Búsqueda: Ficticio', filtrada.text)
        self.assertIn('Categoría: Contratos', filtrada.text)
        self.assertIn('Orden: Título (A-Z)', filtrada.text)
        self.assertNotIn('Ficticio Humano', filtrada.text)

    def test_editor_no_obtiene_documentos_de_otra_area(self):
        self.login('editorcsrf')
        for ruta in ('/buscar?q=Ficticio', '/?categoria=Contratos'):
            respuesta = self.client.get(ruta)
            self.assertEqual(respuesta.status_code, 200)
            self.assertIn('Ficticio Tesoro', respuesta.text)
            self.assertNotIn('Ficticio Humano', respuesta.text)

    @unittest.skipUnless(shutil.which("node"), "Requiere Node para ejecutar el planificador servido por HTTP")
    def test_enrutamiento_y_extraccion_hasta_sqlite_con_permisos(self):
        self.login("editorcsrf")
        with closing(sqlite3.connect(Path(self.fixture.temp.name) / "gestor.db")) as db:
            documentos_antes = db.execute("SELECT * FROM documentos ORDER BY id").fetchall()
            esperados = [r[0] for r in db.execute(
                "SELECT id FROM documentos WHERE departamento='Tesorería' "
                "AND numero_oficio='OF-123' AND eliminado_en IS NULL ORDER BY id DESC"
            )]
        nombres = ("interprete_busqueda", "interprete_contextual", "clasificador_ayuda_clippy",
                   "catalogo_ayuda_clippy", "clippy_chat_plan")
        scripts = {}
        for nombre in nombres:
            respuesta = self.client.get(f"/static/{nombre}.js", headers={"Cache-Control":"no-cache"})
            self.assertEqual(respuesta.status_code, 200)
            scripts[nombre] = respuesta.text
        texto = "Lo de Tesorería con folio OF-123, ¿te suena?"
        menciones = {"folios":[{"valor":"OF-123", "inicio":27, "texto":"OF-123"}], "fechas":[],
                     "departamentos":[{"valor":"Tesorería", "texto":"Tesorería"}],
                     "referencias":[], "negaciones":[]}
        apoyo = preparar_propuestas(texto, menciones, {"rol":"editor", "departamento":"Tesorería"})
        apoyo["analisis"] = {"estado":"abstencion"}
        casos = [
            {"texto":"Localiza el botón para cambiar la apariencia"},
            {"texto":"Localiza el botón para cambiar la apariencia", "apoyo":{"intencion":"ajustes", "analisis":{"estado":"aceptada"}}},
            {"texto":"Busca cómo cambio el tema de la pantalla"},
            {"texto":texto, "apoyo":apoyo},
            {"texto":"Tengo aquí el folio OF-123 de Tesorería", "apoyo":apoyo},
            {"texto":"Busca el folio OF-123 de Recursos Humanos"},
            {"texto":"Nunca busques el folio OF-123", "apoyo":apoyo},
        ]
        programa = """
const fs=require('node:fs'),vm=require('node:vm'),datos=JSON.parse(fs.readFileSync(0,'utf8'));
const root={};root.window=root;vm.createContext(root);
for(const s of Object.values(datos.scripts))vm.runInContext(s,root);
const ayuda=t=>root.sigedConsultarAyuda(t,{pantalla:'inicio',capacidades:{ver:true}});
const opts={areas:datos.areas,categorias:datos.categorias,detallar:root.sigedInterpretarBusqueda.detallar,
contextual:root.sigedInterpretarContexto,clasificar:root.sigedClasificarAyuda,ayudaValida:t=>ayuda(t)!==ayuda('')};
process.stdout.write(JSON.stringify(datos.casos.map(c=>root.sigedPlanClippy.resolver(c.texto,null,opts,c.apoyo))));
"""
        salida = subprocess.run(["node", "-e", programa], input=json.dumps({"scripts":scripts,
            "areas":DEPARTAMENTOS,"categorias":CATEGORIAS,"casos":casos}),
            capture_output=True, text=True, encoding="utf-8", check=True, timeout=20)
        planes = json.loads(salida.stdout)
        self.assertTrue(planes[0]["consultar_modelo"])
        self.assertEqual(planes[1], {"tipo":"ayuda", "tema":"ajustes"})
        self.assertEqual(planes[2], {"tipo":"ayuda", "tema":"ajustes"})
        plan = planes[3]
        self.assertEqual(plan["tipo"], "buscar")
        self.assertEqual(plan["dudas"], [])
        self.assertEqual(plan["filtros"], {"folio":"OF-123", "departamento":"Tesorería"})
        respuesta = self.client.get("/asistente/documentos", params=plan["filtros"])
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual([int(d["id"]) for d in respuesta.json()["documentos"]], esperados)
        self.assertTrue(esperados)
        biblioteca = self.client.get("/", params={"oficio":"OF-123", "departamento":"Tesorería"})
        self.assertIn("Ficticio Tesoro", biblioteca.text)
        self.assertNotIn("Ficticio Humano", biblioteca.text)
        self.assertEqual(planes[4]["dudas"][-1]["tipo"], "proposito")
        self.assertEqual(planes[4]["filtros"], plan["filtros"])
        self.assertEqual(self.client.get("/asistente/documentos", params=planes[5]["filtros"]).status_code, 403)
        self.assertEqual(planes[6]["tipo"], "mensaje")
        with closing(sqlite3.connect(Path(self.fixture.temp.name) / "gestor.db")) as db:
            self.assertEqual(db.execute("SELECT * FROM documentos ORDER BY id").fetchall(), documentos_antes)

    @unittest.skipUnless(shutil.which("node"), "Requiere Node para ejecutar el JavaScript servido por HTTP")
    def test_editor_orden_por_registro_desde_frase_hasta_sqlite_y_biblioteca(self):
        with closing(sqlite3.connect(Path(self.fixture.temp.name) / "gestor.db")) as db, db:
            db.execute(
                "INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) "
                "SELECT 'editororden','Editor de prueba',password_hash,'editor','Comprobación' "
                "FROM usuarios WHERE usuario='editorcsrf'"
            )
            filas = [
                (40001,"Alta reciente","Comprobación","2099-01-01 10:00:00","1901-01-01",None),
                (40009,"Alta antigua","Comprobación","1901-01-01 10:00:00","2099-01-01",None),
                (40010,"Empate posterior","Comprobación","1901-01-01T10:00:00Z","2099-01-01",None),
                (40021,"Ajeno antiguo","Recursos Humanos","1700-01-01","2025-01-01",None),
                (40022,"Ajeno reciente","Recursos Humanos","2300-01-01","2025-01-01",None),
                (40023,"Papelera antigua","Comprobación","1600-01-01","2025-01-01","2026-01-01"),
                (40024,"Papelera reciente","Comprobación","2400-01-01","2025-01-01","2026-01-01"),
                (40025,"Compartido de prueba","","2022-01-01","2025-01-01",None),
                (40026,"El documento más reciente","Comprobación","2023-01-01","2025-01-01",None),
            ]
            db.executemany(
                "INSERT INTO documentos(id,titulo,departamento,fecha_subida,fecha_documento,eliminado_en,"
                "nombre_archivo,nombre_guardado,categoria,tamano_bytes) VALUES(?,?,?,?,?,?,'prueba.txt',?,'Otros',1)",
                [(*fila, f"prueba-orden-{fila[0]}.txt") for fila in filas],
            )
        self.login("editororden")
        frases = [
            ("Busca el documentos mas antiguo","registro_asc","1",40009),
            ("Busca el último documento subido","registro_desc","1",40001),
            ("Busca el documento más reciente que se haya subido al gestor","registro_desc","1",40001),
            ("Muéstrame los últimos 5 documentos registrados","registro_desc","5",40001),
            ("Busca el primer documento subido","registro_asc","1",40009),
            ("Muéstrame los primeros 5 documentos registrados","registro_asc","5",40009),
            ("Busca el documento más reciente","registro_desc","1",40001),
            ("Porfa, muéstrame el archivo más antiguo","registro_asc","1",40009),
            ("Localiza el documento más reciente de Comprobación","registro_desc","1",40001),
            ("Busca los documentos más recientes","registro_desc","20",40001),
        ]
        nombres = ("interprete_busqueda","interprete_contextual","clasificador_ayuda_clippy",
                   "catalogo_ayuda_clippy","clippy_chat_plan")
        scripts = {}
        for nombre in nombres:
            r = self.client.get(f"/static/{nombre}.js", headers={"Cache-Control":"no-cache"})
            self.assertEqual(r.status_code, 200)
            scripts[nombre] = r.text
        programa = """
const fs=require('node:fs'), vm=require('node:vm');
const datos=JSON.parse(fs.readFileSync(0,'utf8'));
const root={}; root.window=root; vm.createContext(root);
for(const contenido of Object.values(datos.scripts)) vm.runInContext(contenido,root);
const ayuda=tema=>root.sigedConsultarAyuda(tema,{pantalla:'inicio',capacidades:{ver:true}});
const opts={areas:datos.areas,categorias:datos.categorias,detallar:root.sigedInterpretarBusqueda.detallar,
    contextual:root.sigedInterpretarContexto,clasificar:root.sigedClasificarAyuda,
    ayudaValida:tema=>ayuda(tema)!==ayuda('')};
process.stdout.write(JSON.stringify(datos.frases.map(texto=>root.sigedPlanClippy.resolver(texto,null,opts,null))));
"""
        salida = subprocess.run(
            ["node", "-e", programa],
            input=json.dumps({"scripts":scripts,"frases":[f[0] for f in frases],
                              "areas":DEPARTAMENTOS,"categorias":CATEGORIAS}),
            capture_output=True, text=True, encoding="utf-8", check=True, timeout=20,
        )
        planes = json.loads(salida.stdout)
        for (texto, orden, limite, primero), plan in zip(frases, planes, strict=True):
            with self.subTest(frase=texto):
                self.assertEqual(plan["tipo"], "buscar")
                self.assertEqual(plan["filtros"]["orden"], orden)
                self.assertEqual(plan["filtros"]["limite"], limite)
                self.assertNotIn("buscar", plan["filtros"])
                respuesta = self.client.get("/asistente/documentos", params=plan["filtros"])
                self.assertEqual(respuesta.status_code, 200)
                ids = [int(d["id"]) for d in respuesta.json()["documentos"]]
                self.assertEqual(ids[0], primero)
                self.assertLessEqual(len(ids), int(limite))
                self.assertTrue(set(ids).isdisjoint({40021,40022,40023,40024}))
                biblioteca = self.client.get("/", params={"orden":orden})
                self.assertEqual(biblioteca.status_code, 200)
                visibles = [int(i) for i in re.findall(
                    r'<a href="/documentos/(\d+)" class="enlace-titulo"', biblioteca.text
                )]
                self.assertEqual(ids, visibles[:len(ids)])
        for parametros in ({"orden":"registro_asc","limite":0}, {"orden":"registro_desc","limite":21},
                           {"orden":"fecha_subida; DROP TABLE documentos"}):
            self.assertEqual(self.client.get("/asistente/documentos", params=parametros).status_code, 422)
        self.assertEqual(self.client.get("/asistente/documentos").status_code, 422)

    def test_admin_y_habitos_aislados_por_cuenta(self):
        token = self.login('lectorcsrf')
        encabezados = {'X-CSRF-Token': token, 'Origin': self.base}
        respuesta = self.client.post('/asistente/habito', headers=encabezados, json={
            'tipo': 'busqueda', 'filtros': {'buscar': 'busqueda-ficticia-unica', 'departamento': 'Recursos Humanos'},
        })
        self.assertTrue(respuesta.json()['guardado'])
        lector = self.client.get('/asistente/preferencias').json()['busquedas']
        self.assertEqual(lector, [{'buscar': 'busqueda-ficticia-unica'}])
        with httpx.Client(base_url=self.base, follow_redirects=False, trust_env=False, timeout=30) as admin:
            token_login = re.search(r'<meta name="csrf-token" content="([^"]+)"', admin.get('/login').text).group(1)
            self.assertEqual(admin.post('/login', data={'usuario': 'admincsrf', 'password': 'ClavePrueba123!', 'csrf_token': token_login}).status_code, 303)
            self.assertNotIn('busqueda-ficticia-unica', str(admin.get('/asistente/preferencias').json()))
            self.assertIn('Ficticio Humano', admin.get('/buscar', params={'q': 'Ficticio'}).text)
            self.assertNotIn('Ficticio Papelera', admin.get('/buscar', params={'q': 'Ficticio'}).text)

    def test_rutinas_y_expedientes_son_privados_y_respetan_ajustes(self):
        with closing(sqlite3.connect(Path(self.fixture.temp.name) / "gestor.db")) as db:
            expediente = db.execute("SELECT id FROM expedientes WHERE folio = 'EXP-TEST'").fetchone()[0]
        token = self.login('editorcsrf')
        cabeceras = {'X-CSRF-Token': token}
        for habito in [
            *[{'tipo': 'rutina', 'valor': 'expedientes', 'hora': 12}] * 3,
            {'tipo': 'expediente', 'valor': expediente},
        ]:
            self.assertTrue(self.client.post('/asistente/habito', headers=cabeceras, json=habito).json()['guardado'])
        respuesta = self.client.get('/asistente/preferencias?hora=12')
        self.assertIn('no-store', respuesta.headers['Cache-Control'])
        editor = respuesta.json()
        self.assertEqual(editor['rutina'], 'expedientes')
        self.assertEqual(editor['expediente_reciente']['id'], expediente)
        self.assertTrue(editor['consejos_personalizados'])
        self.assertEqual(self.client.post('/ajustes', data={
            'csrf_token': token, 'clippy_visible': '1', 'clippy_habitos': '1',
        }).status_code, 303)
        self.assertFalse(self.client.get('/asistente/preferencias?hora=12').json()['consejos_personalizados'])
        self.assertEqual(self.client.post('/ajustes', data={
            'csrf_token': token, 'clippy_consejos': '1', 'clippy_habitos': '1',
        }).status_code, 303)
        self.assertFalse(self.client.get('/asistente/preferencias?hora=12').json()['consejos_personalizados'])
        self.assertEqual(self.client.post('/ajustes', data={'csrf_token': token}).status_code, 303)
        editor_pausado = self.client.get('/asistente/preferencias?hora=12').json()
        self.assertFalse(editor_pausado['aprendizaje'])
        self.assertIsNone(editor_pausado['rutina'])
        self.assertIsNone(editor_pausado['expediente_reciente'])
        self.assertFalse(self.client.post('/asistente/habito', headers=cabeceras, json={
            'tipo': 'expediente', 'valor': expediente,
        }).json()['guardado'])
        self.client.post('/salir', data={'csrf_token': token})
        self.login('lectorcsrf')
        lector = self.client.get('/asistente/preferencias?hora=12').json()
        self.assertNotEqual(lector['usuario_id'], editor['usuario_id'])
        self.assertIsNone(lector['rutina'])
        self.assertIsNone(lector['expediente_reciente'])

    def test_diagnostico_respeta_sesion_area_y_rol(self):
        ruta = '/asistente/diagnostico'
        self.assertEqual(self.client.get(ruta, params={'tema': 'sistema'}).status_code, 303)
        token = self.login('lectorcsrf')
        with closing(sqlite3.connect(Path(self.fixture.temp.name) / 'gestor.db')) as db:
            visibles = dict(db.execute("SELECT titulo, id FROM documentos"))
        parametros = {'tema': 'documento', 'registro': visibles['Ficticio Humano']}
        denegado = self.client.get(ruta, params=parametros)
        inexistente = self.client.get(ruta, params={**parametros, 'registro': 999999})
        eliminado = self.client.get(ruta, params={**parametros, 'registro': visibles['Ficticio Papelera']})
        self.assertEqual(denegado.status_code, 200)
        self.assertIn('no-store', denegado.headers['Cache-Control'])
        self.assertEqual(denegado.json(), inexistente.json())
        self.assertEqual(denegado.json(), eliminado.json())
        permiso = self.client.get(ruta, params={'tema': 'permisos', 'accion': 'usuarios'}).json()
        self.assertIn('no permite', permiso['mensaje'])
        self.assertEqual(self.client.get(ruta, params={'tema': 'permisos', 'accion': 'cambiar_rol'}).status_code, 400)
        self.assertEqual(self.client.get(ruta, params={'tema': 'cuentas_ajenas'}).status_code, 422)
        self.assertIn('número de registro', self.client.get(ruta, params={'tema': 'documento'}).json()['mensaje'])
        self.assertIn('no está habilitado', self.client.get(ruta, params={'tema': 'mensajeria'}).json()['mensaje'])
        self.assertIn('Estado del sistema:', self.client.get(ruta, params={'tema': 'sistema'}).json()['mensaje'])
        self.assertIn('Almacenamiento documental:', self.client.get(ruta, params={'tema': 'almacenamiento'}).json()['mensaje'])

        self.assertEqual(self.client.post('/salir', data={'csrf_token': token}).status_code, 303)
        self.login('admincsrf')
        permitido = self.client.get(ruta, params={**parametros, 'usuario_id': denegado.json()['usuario_id']}).json()
        self.assertNotEqual(permitido['usuario_id'], denegado.json()['usuario_id'])
        self.assertIn('registro es visible', permitido['mensaje'])
        self.assertNotIn('Ficticio Humano', permitido['mensaje'])


    def test_habito_de_expediente_respeta_documentos_visibles(self):
        def preparar(db, folio, documentos):
            expediente = db.execute("INSERT INTO expedientes(folio,titulo) VALUES (?,?)",
                                    (folio, "Expediente ficticio " + folio)).lastrowid
            for documento in documentos:
                db.execute("INSERT INTO expediente_documentos(expediente_id,documento_id) "
                           "SELECT ?,id FROM documentos WHERE titulo=?", (expediente, documento))
            return expediente

        with closing(sqlite3.connect(Path(self.fixture.temp.name) / "gestor.db")) as db, db:
            ajeno = preparar(db, "EXP-AJENO", ["Ficticio Humano"])
            compartido = preparar(db, "EXP-COMPARTIDO", ["Ficticio Humano", "Ficticio Compartido"])
            propio = preparar(db, "EXP-PROPIO", ["Ficticio Tesoro"])
            solo_papelera = preparar(db, "EXP-PAPELERA", ["Ficticio Papelera"])
            cuenta = db.execute("SELECT id FROM usuarios WHERE usuario='revisioncsrf'").fetchone()[0]
        token = self.login("revisioncsrf")
        headers = {"X-CSRF-Token": token, "Origin": self.base}

        def registrar(expediente):
            return self.client.post("/asistente/habito", headers=headers,
                                    json={"tipo": "expediente", "valor": str(expediente)})

        for ident in (ajeno, solo_papelera, 999999):
            with self.subTest(expediente=ident):
                respuesta = registrar(ident)
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.json(), {"guardado": False})
        for ident in (compartido, propio):
            self.assertEqual(registrar(ident).json(), {"guardado": True})

        # Un historial previo o un cambio de acceso no debe volver a ofrecer un expediente ajeno.
        with closing(sqlite3.connect(Path(self.fixture.temp.name) / "gestor.db")) as db, db:
            db.execute("DELETE FROM asistente_habitos WHERE usuario_id=? AND tipo='expediente'", (cuenta,))
            for ident, fecha in ((compartido, "2025-01-01"), (ajeno, "2025-01-02"), (solo_papelera, "2025-01-03")):
                db.execute("INSERT INTO asistente_habitos(usuario_id,tipo,valor,ultima_vez) VALUES (?, 'expediente', ?, ?)",
                           (cuenta, str(ident), fecha))
        respuesta = self.client.get("/asistente/preferencias")
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn("EXP-AJENO", respuesta.text)
        self.assertNotIn("EXP-PAPELERA", respuesta.text)
        self.assertEqual(respuesta.json()["expediente_reciente"]["id"], compartido)
        self.assertEqual(self.client.post("/salir", data={"csrf_token": token}).status_code, 303)

        token_admin = self.login("admincsrf")
        headers["X-CSRF-Token"] = token_admin
        self.assertEqual(registrar(ajeno).json(), {"guardado": True})
        self.assertEqual(self.client.get("/asistente/preferencias").json()["expediente_reciente"]["id"], ajeno)

    def test_habitos_malformados_no_escriben_ni_producen_500(self):
        token = self.login("revisioncsrf")
        headers = {"X-CSRF-Token": token, "Origin": self.base, "Content-Type": "application/json"}
        def cantidad():
            with closing(sqlite3.connect(Path(self.fixture.temp.name) / "gestor.db")) as db:
                return db.execute(
                    "SELECT COUNT(*) FROM asistente_habitos "
                    "WHERE usuario_id = (SELECT id FROM usuarios WHERE usuario = 'revisioncsrf')"
                ).fetchone()[0]

        inicial = cantidad()
        for datos in (
            {"tipo": "seccion", "valor": []},
            {"tipo": "rutina", "valor": {}, "hora": 12},
            {"tipo": "expediente", "valor": "\u00b2"},
            {"tipo": "busqueda", "filtros": {"buscar": "\ud800"}},
        ):
            with self.subTest(tipo=datos["tipo"]):
                respuesta = self.client.post("/asistente/habito", headers=headers,
                                            content=json.dumps(datos, ensure_ascii=True))
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.json(), {"guardado": False})

        self.assertEqual(cantidad(), inicial)
        self.assertEqual(self.client.post("/asistente/habito", headers=headers, content="{").status_code, 422)
        self.assertEqual(self.client.get("/asistente/preferencias", params={"hora": "incorrecta"}).status_code, 422)

    def test_preferencias_omite_busquedas_historicas_malformadas(self):
        self.login("revisioncsrf")
        with closing(sqlite3.connect(Path(self.fixture.temp.name) / "gestor.db")) as db, db:
            cuenta = db.execute("SELECT id FROM usuarios WHERE usuario='revisioncsrf'").fetchone()[0]
            contenidos = ("no es JSON", "[]", "null", r'{"buscar":"\ud800"}', '{"buscar":"consulta de prueba"}')
            db.executemany("INSERT INTO asistente_habitos(usuario_id,tipo,valor) VALUES (?, 'busqueda', ?)",
                           [(cuenta, valor) for valor in contenidos])
        respuesta = self.client.get("/asistente/preferencias")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["busquedas"], [{"buscar": "consulta de prueba"}])

    def test_habitos_y_preferencias_requieren_sesion_y_csrf(self):
        self.assertEqual(self.client.get("/asistente/preferencias").status_code, 303)
        token = self.login("revisioncsrf")
        datos = {"tipo": "seccion", "valor": "biblioteca"}
        self.assertEqual(self.client.post("/asistente/habito", json=datos).status_code, 403)
        self.assertEqual(self.client.post("/salir", data={"csrf_token": token}).status_code, 303)
        respuesta = self.client.post("/asistente/habito", json=datos, headers={"X-CSRF-Token": token})
        self.assertEqual(respuesta.status_code, 403)


if __name__ == '__main__':
    unittest.main()
