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
        manipulada = self.client.get('/', params={**filtros, 'departamento': 'Recursos Humanos'})
        self.assertNotIn('Ficticio Humano', manipulada.text)
        with closing(sqlite3.connect(Path(self.fixture.temp.name) / 'gestor.db')) as db:
            ident = db.execute("SELECT id FROM documentos WHERE titulo='Ficticio Humano'").fetchone()[0]
        self.assertIn(self.client.get(f'/documentos/{ident}').status_code, (403, 404))

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


if __name__ == '__main__':
    unittest.main()
