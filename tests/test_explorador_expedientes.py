"""Pruebas HTTP del explorador con datos ficticios en el fixture aislado."""
import re
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

import httpx
import test_csrf as soporte


class ExploradorExpedientesHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        soporte.CsrfHTTPTest.setUpClass()
        cls.fixture = soporte.CsrfHTTPTest
        cls.base = cls.fixture.base
        with closing(sqlite3.connect(Path(cls.fixture.temp.name) / 'gestor.db')) as db, db:
            db.execute("INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) SELECT 'editorexp','Editor ficticio',password_hash,'editor','Tesorería' FROM usuarios WHERE usuario='lectorcsrf'")
            db.execute("INSERT INTO expedientes(folio,titulo) VALUES ('EXP-PRUEBA','Asunto ficticio')")
            eid = db.execute("SELECT id FROM expedientes WHERE folio='EXP-PRUEBA'").fetchone()[0]
            cls.eid = eid
            for titulo, area in [('Visible ficticio', 'Tesorería'), ('Restringido ficticio', 'Recursos Humanos')]:
                cur = db.execute("INSERT INTO documentos(titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes,departamento) VALUES (?,?,?,?,?,?)", (titulo, titulo+'.txt', titulo+'.txt', 'Otros', 1, area))
                db.execute('INSERT INTO expediente_documentos(expediente_id,documento_id) VALUES (?,?)', (eid, cur.lastrowid))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def setUp(self):
        self.client = httpx.Client(base_url=self.base, follow_redirects=False, trust_env=False, timeout=30)
        self.addCleanup(self.client.close)

    def login(self, usuario):
        token = re.search(r'<meta name="csrf-token" content="([^"]+)"', self.client.get('/login').text).group(1)
        self.assertEqual(self.client.post('/login', data={'usuario':usuario, 'password':'ClavePrueba123!', 'csrf_token':token}).status_code, 303)
        return re.search(r'<meta name="csrf-token" content="([^"]+)"', self.client.get('/inicio').text).group(1)

    def test_lector_ve_solo_recuento_y_documentos_permitidos(self):
        self.login('lectorcsrf')
        lista = self.client.get('/expedientes')
        self.assertEqual(lista.status_code, 200)
        self.assertIn('Asunto ficticio', lista.text)
        self.assertIn('1 documento visible', lista.text)
        self.assertNotIn('href="/expedientes/nuevo"', lista.text)
        self.assertNotIn('Eliminar expediente EXP-PRUEBA', lista.text)
        self.assertEqual(self.client.get('/expedientes/nuevo').status_code, 403)
        ficha = self.client.get(f'/expedientes/{self.eid}')
        self.assertIn('Visible ficticio', ficha.text)
        self.assertNotIn('Restringido ficticio', ficha.text)

    def test_editor_crea_desde_formulario_separado(self):
        token = self.login('editorexp')
        lista = self.client.get('/expedientes')
        self.assertIn('href="/expedientes/nuevo"', lista.text)
        self.assertNotIn('id="titulo-expediente"', lista.text)
        nuevo = self.client.get('/expedientes/nuevo')
        self.assertEqual(nuevo.status_code, 200)
        self.assertIn('text/html', nuevo.headers['content-type'])
        self.assertIn('id="titulo-expediente"', nuevo.text)
        self.assertIn('action="/expedientes" method="post"', nuevo.text)
        self.assertIn('name="csrf_token"', nuevo.text)
        self.assertIn('href="/expedientes"', nuevo.text)
        self.assertEqual(self.client.post('/expedientes', data={'titulo':'Sin CSRF'}, headers={'Origin':self.base}).status_code, 403)
        r = self.client.post('/expedientes', data={'titulo':'Creado ficticio', 'descripcion':'prueba', 'csrf_token':token}, headers={'Origin':self.base})
        self.assertEqual(r.status_code, 303)
        self.assertRegex(r.headers['location'], r'^/expedientes/\d+\?aviso=expediente_creado$')
        ficha = self.client.get(r.headers['location'])
        self.assertEqual(ficha.status_code, 200)
        self.assertIn('Creado ficticio', ficha.text)
        self.assertRegex(ficha.text, r'EXP-\d{4}-\d{6}')

    def test_admin_conteo_completo_y_confirmacion_de_eliminacion(self):
        token = self.login('admincsrf')
        lista = self.client.get('/expedientes')
        self.assertIn('2 documentos visibles', lista.text)
        self.assertIn('data-confirm-title="Eliminar expediente"', lista.text)
        r = self.client.post('/expedientes', data={'titulo':'Eliminar ficticio', 'csrf_token':token}, headers={'Origin':self.base})
        ident = re.search(r'/expedientes/(\d+)', r.headers['location']).group(1)
        self.assertEqual(self.client.post(f'/expedientes/{ident}/eliminar', data={'csrf_token':token}, headers={'Origin':self.base}).status_code, 303)


if __name__ == '__main__':
    unittest.main()
