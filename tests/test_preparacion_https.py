"""Comprobaciones aisladas de configuración y middleware, sin servidor ni SQLite."""
import unittest
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.csrf import token_csrf, validar_csrf

RAIZ = Path(__file__).resolve().parents[1]


def aplicacion(secure=True):
    app = FastAPI(dependencies=[Depends(validar_csrf)])
    app.add_middleware(SessionMiddleware, secret_key='clave-ficticia', session_cookie='gestor_sesion',
                       same_site='lax', https_only=secure)

    @app.get('/')
    def estado(request: Request):
        return {'ip': request.client.host, 'scheme': request.url.scheme,
                'base': str(request.base_url), 'csrf': token_csrf(request)}

    @app.post('/')
    def enviar():
        return {'ok': True}

    return ProxyHeadersMiddleware(app, trusted_hosts='127.0.0.1')


class PreparacionHTTPSTest(unittest.TestCase):
    def test_arranques_son_locales_y_confianza_esta_acotada(self):
        dev = (RAIZ / 'Iniciar SIGED.bat').read_text(encoding='utf-8')
        prod = (RAIZ / 'Iniciar SIGED produccion.bat').read_text(encoding='utf-8')
        for texto in (dev, prod):
            self.assertIn('--host 127.0.0.1 --port 8000', texto)
            self.assertNotIn('--host 0.0.0.0', texto)
        self.assertIn('GESTOR_HTTPS_ONLY=0', dev)
        self.assertIn('--no-proxy-headers', dev)
        self.assertIn('GESTOR_HTTPS_ONLY=1', prod)
        self.assertIn('--forwarded-allow-ips 127.0.0.1', prod)
        self.assertNotIn('--forwarded-allow-ips *', prod)

    def test_encabezados_de_cliente_no_confiable_no_alteran_ip_ni_esquema(self):
        with TestClient(aplicacion(), base_url='http://siged.test', client=('192.0.2.20', 1234)) as cliente:
            r = cliente.get('/', headers={'X-Forwarded-For':'198.51.100.55', 'X-Forwarded-Proto':'https'})
            self.assertEqual(r.json()['ip'], '192.0.2.20')
            self.assertEqual(r.json()['scheme'], 'http')

    def test_proxy_confiable_cookie_y_csrf_con_host_publico(self):
        with TestClient(aplicacion(), base_url='https://siged.test', client=('127.0.0.1', 1234)) as cliente:
            headers = {'Host':'siged.test', 'X-Forwarded-For':'192.0.2.20', 'X-Forwarded-Proto':'https'}
            r = cliente.get('/', headers=headers)
            self.assertEqual(r.json()['ip'], '192.0.2.20')
            self.assertEqual(r.json()['base'], 'https://siged.test/')
            cookie = r.headers['set-cookie'].lower()
            for atributo in ('secure', 'httponly', 'samesite=lax'): self.assertIn(atributo, cookie)
            token = r.json()['csrf']
            self.assertEqual(cliente.post('/', headers={**headers, 'Origin':'https://siged.test', 'X-CSRF-Token':token}).status_code, 200)
            self.assertEqual(cliente.post('/', headers={**headers, 'Origin':'https://otro.test', 'X-CSRF-Token':token}).status_code, 403)

    def test_ejemplo_caddy_usa_tls_y_solo_backend_local(self):
        texto = (RAIZ / 'Caddyfile.ejemplo').read_text(encoding='utf-8')
        for esperado in ('https://{$SIGED_HOST}', 'tls "{$SIGED_CERT}" "{$SIGED_KEY}"',
                         'reverse_proxy 127.0.0.1:8000', 'header_up X-Forwarded-For {remote_host}',
                         'header_up X-Forwarded-Proto https', 'auto_https off', 'admin off'):
            self.assertIn(esperado, texto)


if __name__ == '__main__':
    unittest.main()
