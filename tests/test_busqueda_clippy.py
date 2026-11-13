"""Regresión HTTP con el servidor y SQLite ficticios del fixture CSRF."""

import re
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

import httpx
import test_csrf as soporte


class BusquedaClippyHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        soporte.CsrfHTTPTest.setUpClass()
        cls.fixture = soporte.CsrfHTTPTest
        cls.base = cls.fixture.base
        with closing(sqlite3.connect(Path(cls.fixture.temp.name) / "gestor.db")) as db, db:
            db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) SELECT 'editorcsrf','editorcsrf',password_hash,'editor','Tesorería' FROM usuarios WHERE usuario='lectorcsrf'")
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


if __name__ == '__main__':
    unittest.main()
