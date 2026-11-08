"""Casos de integración: la barrera se comprueba antes de importar la aplicación."""
from aislamiento import exigir_directorio_temporal
exigir_directorio_temporal('siged-limite-')

import asyncio
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.archivos import TAMANO_MAXIMO
from app.configuracion import STORAGE_DIR
from app.database import conectar
from app.main import app
from app.seguridad import hashear_password
from app.limite_solicitud import LIMITE_PREDETERMINADO, limite_configurado


class Casos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cliente = TestClient(app, base_url='http://siged.test')
        cls.cliente.__enter__()
        with conectar() as db:
            for usuario, rol in [('admin_prueba','admin'), ('lector_prueba','lector')]:
                db.execute('INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) VALUES(?,?,?,?,?)',
                           (usuario, usuario, hashear_password('ClavePrueba123!'), rol, 'Tesorería'))

    @classmethod
    def tearDownClass(cls):
        cls.cliente.__exit__(None, None, None)

    def login(self, usuario='admin_prueba'):
        self.cliente.cookies.clear()
        pagina = self.cliente.get('/login')
        token = re.search(r'<meta name="csrf-token" content="([^"]+)"', pagina.text).group(1)
        r = self.cliente.post('/login', data={'usuario':usuario, 'password':'ClavePrueba123!', 'csrf_token':token}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        return re.search(r'<meta name="csrf-token" content="([^"]+)"', self.cliente.get('/inicio').text).group(1)

    def archivos(self):
        return {str(p.relative_to(STORAGE_DIR)) for p in STORAGE_DIR.rglob('*') if p.is_file()}

    def test_configuracion_valida_y_falla_cerrado(self):
        for valor in ('0', str(TAMANO_MAXIMO), '-1', 'invalido', '9'*100):
            with self.subTest(valor=valor), patch.dict('os.environ', {'GESTOR_MAX_CUERPO_BYTES':valor}):
                with self.assertRaises(ValueError): limite_configurado()
        with patch.dict('os.environ', {'GESTOR_MAX_CUERPO_BYTES':str(TAMANO_MAXIMO+100)}):
            self.assertEqual(limite_configurado(), TAMANO_MAXIMO+100)

    def test_multipart_limite_archivo_y_campos(self):
        token = self.login()
        datos = {'titulo':'Ficticio', 'categoria':'Otros', 'descripcion':'descripción ficticia',
                 'numero_oficio':'OF-123', 'autor':'Autor ficticio', 'csrf_token':token}
        for tamano in (1024, TAMANO_MAXIMO):
            with self.subTest(tamano=tamano):
                r = self.cliente.post('/subir', data=datos, files={'archivo':('ficticio.txt', b'x'*tamano, 'text/plain')}, follow_redirects=False)
                self.assertEqual(r.status_code, 303); self.assertIn('subido', r.headers['location'])
        antes = self.archivos()
        r = self.cliente.post('/subir', data=datos, files={'archivo':('grande.txt', b'x'*(TAMANO_MAXIMO+1), 'text/plain')}, follow_redirects=False)
        self.assertEqual(r.status_code, 303); self.assertIn('grande', r.headers['location'])
        self.assertEqual(self.archivos(), antes)

    def test_csrf_y_permisos_siguen_vigentes(self):
        token = self.login('lector_prueba')
        antes = self.archivos()
        datos = {'titulo':'Ficticio', 'categoria':'Otros', 'csrf_token':token}
        r = self.cliente.post('/subir', data=datos, files={'archivo':('x.txt', b'x', 'text/plain')})
        self.assertEqual(r.status_code, 403)
        self.login()
        r = self.cliente.post('/subir', data={'titulo':'Ficticio', 'categoria':'Otros'}, files={'archivo':('x.txt', b'x', 'text/plain')})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.archivos(), antes)

    def ejecutar_asgi(self, headers, mensajes):
        enviados, leidos = [], []
        scope = {'type':'http', 'asgi':{'version':'3.0', 'spec_version':'2.3'}, 'http_version':'1.1',
                 'method':'POST', 'scheme':'http', 'path':'/subir', 'raw_path':b'/subir', 'query_string':b'',
                 'root_path':'', 'server':('siged.test', 80), 'client':('127.0.0.1', 1234), 'headers':headers}
        async def recibir():
            indice = len(leidos); leidos.append(indice)
            if indice < len(mensajes): return mensajes[indice]
            return {'type':'http.disconnect'}
        async def enviar(mensaje): enviados.append(mensaje)
        asyncio.run(app(scope, recibir, enviar))
        return enviados, leidos

    def test_longitud_excesiva_no_lee_cuerpo(self):
        enviados, leidos = self.ejecutar_asgi([(b'host',b'siged.test'), (b'content-length',str(LIMITE_PREDETERMINADO+1).encode())], [])
        self.assertEqual(enviados[0]['status'], 413)
        self.assertEqual(leidos, [])

    def test_multipart_valido_sin_longitud_declarada(self):
        token = self.login()
        cookie = self.cliente.cookies.get('gestor_sesion')
        partes = [b'--limite\r\nContent-Disposition: form-data; name="titulo"\r\n\r\nEjemplo\r\n',
                  b'--limite\r\nContent-Disposition: form-data; name="categoria"\r\n\r\nOtros\r\n',
                  b'--limite\r\nContent-Disposition: form-data; name="archivo"; filename="f.txt"\r\nContent-Type: text/plain\r\n\r\n',
                  b'contenido ficticio\r\n--limite--\r\n']
        mensajes = [{'type':'http.request', 'body':parte, 'more_body':i < len(partes)-1} for i, parte in enumerate(partes)]
        headers = [(b'host',b'siged.test'), (b'content-type',b'multipart/form-data; boundary=limite'),
                   (b'cookie',f'gestor_sesion={cookie}'.encode()), (b'x-csrf-token',token.encode())]
        enviados, _ = self.ejecutar_asgi(headers, mensajes)
        self.assertEqual(enviados[0]['status'], 303)
        self.assertIn(b'subido', dict(enviados[0]['headers'])[b'location'])

    def test_fragmentos_sin_longitud_detienen_lectura_y_cierran_temporales(self):
        token = self.login()
        cookie = self.cliente.cookies.get('gestor_sesion')
        inicio = b'--limite\r\nContent-Disposition: form-data; name="archivo"; filename="f.txt"\r\nContent-Type: text/plain\r\n\r\n'
        mensajes = [{'type':'http.request','body':inicio, 'more_body':True}]
        mensajes += [{'type':'http.request','body':b'x'*(1024*1024), 'more_body':True} for _ in range(24)]
        mensajes.append({'type':'http.request','body':b'\r\n--limite--\r\n', 'more_body':False})
        headers = [(b'host',b'siged.test'), (b'content-type',b'multipart/form-data; boundary=limite'),
                   (b'transfer-encoding',b'chunked'), (b'cookie',f'gestor_sesion={cookie}'.encode()),
                   (b'x-csrf-token',token.encode())]
        creados = []
        original = tempfile.SpooledTemporaryFile
        def crear(*args, **kwargs):
            archivo = original(*args, **kwargs); creados.append(archivo); return archivo
        antes = self.archivos()
        with patch('starlette.formparsers.SpooledTemporaryFile', side_effect=crear):
            enviados, leidos = self.ejecutar_asgi(headers, mensajes)
        self.assertEqual(enviados[0]['status'], 413)
        self.assertLess(len(leidos), len(mensajes))
        self.assertTrue(creados); self.assertTrue(all(f.closed for f in creados))
        self.assertEqual(self.archivos(), antes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
