"""Transporte experimental con sesiones, archivos NTFS y bases ficticias."""

import asyncio
import hashlib
import json
import socket
import subprocess
import sys
import time
import unittest
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Thread
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx
import uvicorn
from aislamiento import exigir_directorio_temporal
from fastapi import Depends, FastAPI, Request
from itsdangerous import TimestampSigner
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

RAIZ = exigir_directorio_temporal("siged-prueba-mensajeria-")

from app import respaldo
from app.configuracion import APP_DIR, STORAGE_DIR
from app.csrf import token_csrf, validar_csrf
from app.database import conectar, inicializar_db
from app.limite_solicitud import LimitarCuerpo
from app.mensajeria import (
    adjuntos,
    api_http,
    interfaz,
    motor,
    recepcion_http,
    websocket,
)
from app.mensajeria import base_datos as bd
from app.mensajeria import limpieza_adjuntos as limpieza
from app.mensajeria import reconciliacion as rec
from app.rutas_sesion import router
from app.seguridad import hashear_password

P = api_http.PREFIJO
SECRETO = "secreto-de-prueba-http-experimental"
CLAVE = "Contrasena-ficticia-2026"
ORIGEN = "http://testserver"
MIB = 1024 * 1024


def _app(origen=ORIGEN, *, habilitada=True, segura=False, vista=False):
    app = FastAPI(dependencies=[Depends(validar_csrf)])
    app.add_middleware(SessionMiddleware, secret_key=SECRETO, session_cookie="gestor_sesion",
                       https_only=segura, max_age=36000)
    app.add_middleware(LimitarCuerpo)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    if habilitada:
        api_http.instalar(app, origenes=[origen], https_only=segura)
    if vista:
        interfaz.instalar(app, origenes=[origen], https_only=segura)

    @app.get("/fixture/csrf")
    def csrf(request: Request):
        return {"token": token_csrf(request)}

    return app


def _login(cliente, nombre, origen=ORIGEN):
    csrf = "csrf-inicial-ficticio"
    firma = TimestampSigner(SECRETO).sign(b64encode(json.dumps({"csrf_token": csrf}).encode())).decode()
    entrada = cliente.post("/login", data={"usuario": nombre, "password": CLAVE, "csrf_token": csrf},
                          headers={"Cookie": f"gestor_sesion={firma}", "Origin": origen}, follow_redirects=False)
    if entrada.headers.get("location") != "/inicio":
        raise AssertionError("Falló el login ficticio")
    cookie = {"Cookie": f"gestor_sesion={entrada.cookies['gestor_sesion']}"}
    token = cliente.get("/fixture/csrf", headers=cookie).json()["token"]
    actual = cliente.cookies.get("gestor_sesion")
    return {"Cookie": f"gestor_sesion={actual}", "Origin": origen, "X-CSRF-Token": token}


@contextmanager
def _servidor():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        origen = f"http://127.0.0.1:{listener.getsockname()[1]}"
        servidor = uvicorn.Server(uvicorn.Config(_app(origen), ws="none", proxy_headers=False,
                                                access_log=False, log_level="warning"))
        hilo = Thread(target=servidor.run, kwargs={"sockets": [listener]}, daemon=True)
        hilo.start()
        try:
            fin = time.monotonic() + 10
            while not servidor.started:
                if not hilo.is_alive() or time.monotonic() >= fin:
                    raise AssertionError("No inició el servidor loopback")
                time.sleep(.01)
            yield origen
        finally:
            servidor.should_exit = True
            hilo.join(15)
            if hilo.is_alive():
                raise AssertionError("El servidor de prueba no terminó")


class MensajeriaHTTPCasos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_db()
        STORAGE_DIR.mkdir()
        (STORAGE_DIR / "original.txt").write_bytes(b"Original")
        cls.hash = hashear_password(CLAVE)
        with conectar() as db:
            db.executemany(
                "INSERT INTO usuarios(usuario,nombre,password_hash,rol,departamento) VALUES (?,?,?,'lector',?)",
                [("alfa", "Perfil A", cls.hash, "Tesorería"), ("beta", "Perfil B", cls.hash, "Tesorería"),
                 ("gama", "Perfil C", cls.hash, "Archivos")],
            )
            db.execute("""INSERT INTO documentos(titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes,departamento)
                          VALUES ('Reservado','original.txt','original.txt','Oficios',8,'Tesorería')""")
        cls.base = bd.inicializar()
        informe = rec.preparar_identidades()
        if rec.reconciliar(informe["confirmacion"])["estado"] != "identidad_coherente":
            raise AssertionError("Fixture sin reconciliación")

    def setUp(self):
        for ruta in (self.base.parent / "temporales").glob("*.bin"):
            ruta.unlink()
        with bd._conectar_infraestructura() as db:
            for tabla in ("archivos_externos", "eventos", "sesiones_ws", "operaciones", "mensajes",
                          "estado_participante", "conversaciones", "cuotas", "limpieza", "reloj_motor"):
                db.execute(f"DELETE FROM {tabla}")
        with conectar() as db:
            db.execute("UPDATE usuarios SET activo=1,version_sesion=0,departamento='Tesorería' WHERE usuario='beta'")
            db.execute("UPDATE documentos SET eliminado_en=NULL,departamento='Tesorería'")
            self.refs = dict(db.execute("SELECT usuario,mensajeria_ref FROM usuarios"))
            self.doc = db.execute("SELECT mensajeria_ref FROM documentos").fetchone()[0]
        self.instante = 1780000000
        self.enterContext(patch.object(motor, "_ahora", side_effect=lambda: self.instante))

    def cliente(self):
        return self.enterContext(TestClient(_app()))

    def datos(self, destino="beta", **kw):
        return {"destinatario": self.refs[destino], "clave": uuid4().hex, "texto": "Texto ficticio", **kw}

    def _subir(self, cliente, hdr, datos, nombre="dato.txt", contenido=b"Ficticio", **kw):
        return cliente.post(P + "/envios/externos/preparar",
                            headers={**hdr, "X-SIGED-Destinatario": datos["destinatario"],
                                     "Idempotency-Key": datos["clave"]},
                            files={"archivo": (nombre, contenido, "application/octet-stream")}, **kw)

    def _externo(self, cliente, hdr, **kw):
        datos = self.datos()
        preparado = self._subir(cliente, hdr, datos, **kw)
        self.assertEqual(preparado.status_code, 200, preparado.text)
        datos.update(preparado.json())
        return datos

    def _confirmar(self, cliente, hdr, datos):
        return cliente.post(P + "/envios/externos/confirmar", headers=hdr, json=datos)

    def _biblioteca(self, cliente, hdr, modalidad="visualizar", destino="beta"):
        return cliente.post(P + "/envios/biblioteca", headers=hdr,
                            json=self.datos(destino, documento=self.doc, modalidad=modalidad))

    def _mensaje(self, respuesta, remitente="alfa", destinatario="beta"):
        self.assertEqual(respuesta.status_code, 200, respuesta.text)
        chat = motor.conversacion(self.refs[remitente], self.refs[destinatario])
        return P + f"/conversaciones/{chat}/mensajes/{respuesta.json()['mensaje']}"

    def test_activacion_autenticacion_csrf_y_origen(self):
        with TestClient(_app(habilitada=False)) as normal:
            self.assertEqual(normal.get(P + "/cuota").status_code, 404)
        cliente = self.cliente()
        self.assertEqual(cliente.get(P + "/cuota").status_code, 401)
        hdr = _login(cliente, "alfa")
        self.assertEqual(cliente.get(P + "/cuota", headers=hdr).json()["restantes"], 50)
        for adicional in ({"Origin": "http://otro"}, {"Host": "otro"}):
            self.assertEqual(cliente.get(P + "/cuota", headers={**hdr, **adicional}).status_code, 403)
        malo = {**hdr, "X-CSRF-Token": "invalido"}
        self.assertEqual(self._biblioteca(cliente, malo).status_code, 403)
        self.assertEqual(self._subir(cliente, malo, self.datos()).status_code, 403)
        sin = {k: v for k, v in hdr.items() if k != "X-CSRF-Token"}
        self.assertEqual(self._subir(cliente, sin, self.datos()).status_code, 403)
        self.assertEqual(self._biblioteca(cliente, hdr).status_code, 200)
        segura = _app("https://testserver", segura=True)
        with TestClient(segura, base_url="https://testserver") as tls:
            hdr_tls = _login(tls, "alfa", "https://testserver")
            self.assertTrue(next(iter(tls.cookies.jar)).secure)
            self.assertEqual(tls.get(P + "/cuota", headers=hdr_tls).status_code, 200)
            self.assertEqual(tls.get("http://testserver" + P + "/cuota", headers=hdr_tls).status_code, 403)

    def test_sesion_revocada_expirada_e_identidad(self):
        cliente = self.cliente()
        hdr = _login(cliente, "beta")
        self.instante += 36000
        self.assertEqual(cliente.get(P + "/cuota", headers=hdr).status_code, 401)
        hdr = _login(cliente, "beta")
        with conectar() as db:
            db.execute("UPDATE usuarios SET activo=0 WHERE usuario='beta'")
        self.assertEqual(cliente.get(P + "/cuota", headers=hdr).status_code, 401)
        with conectar() as db:
            db.execute("UPDATE usuarios SET activo=1 WHERE usuario='beta'")
        with bd._conectar_infraestructura() as db:
            db.execute("UPDATE sesiones_ws SET usuario_ref=? WHERE usuario_ref=?", (self.refs["gama"], self.refs["beta"]))
        self.assertEqual(cliente.get(P + "/cuota", headers=hdr).status_code, 401)
        hdr = _login(cliente, "beta")
        salir = cliente.post("/salir", headers=hdr, data={"csrf_token": hdr["X-CSRF-Token"]}, follow_redirects=False)
        self.assertEqual(salir.status_code, 303)
        self.assertEqual(cliente.get(P + "/cuota", headers=hdr).status_code, 401)

    def test_esquema_reenviado_solo_desde_proxy_autorizado(self):
        app = ProxyHeadersMiddleware(_app("https://testserver", segura=True), trusted_hosts="127.0.0.1")
        encabezados = {"Origin": "https://testserver", "X-Forwarded-Proto": "https"}
        with TestClient(app, client=("127.0.0.1", 10000)) as proxy:
            self.assertEqual(proxy.get(P + "/cuota", headers=encabezados).status_code, 401)
        with TestClient(app, client=("192.0.2.10", 10000)) as externo:
            self.assertEqual(externo.get(P + "/cuota", headers=encabezados).status_code, 403)

    def test_arranque_real_normal_no_monta_api(self):
        codigo = """
from starlette.testclient import TestClient
from app.main import app
with TestClient(app) as cliente:
    assert cliente.get('/login').status_code == 200
    assert cliente.get('/mensajeria/api/v1/cuota').status_code == 404
    assert cliente.get('/mensajeria').status_code == 404
"""
        subprocess.run([sys.executable, "-c", codigo], timeout=90, check=True)

    def test_interfaz_experimental_y_recursos(self):
        with TestClient(_app()) as solo_api:
            a = _login(solo_api, "alfa")
            self.assertEqual(solo_api.get("/mensajeria", headers=a).status_code, 404)
        with TestClient(_app(vista=True)) as cliente:
            a = _login(cliente, "alfa")
            respuesta = cliente.get("/mensajeria", headers=a)
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(respuesta.headers["cache-control"], "private, no-store")
            self.assertIn('aria-current="page">Mensajes</span>', respuesta.text)
            self.assertIn("Comunicación documental en un solo lugar", respuesta.text)
            self.assertIn("Acceso controlado según los permisos de SIGED", respuesta.text)
            self.assertNotIn('data-mensajeria-no-leidos aria-hidden="true">', respuesta.text)
            self.assertIn("javascript", cliente.get("/static/mensajeria_transporte.mjs").headers["content-type"])
            self.assertEqual(cliente.get("/static/img/mensajeria-bienvenida.svg").status_code, 200)

    def test_selector_documental_valida_ambos_participantes(self):
        with TestClient(_app(vista=True)) as cliente:
            a = _login(cliente, "alfa")
            params = {"destinatario": self.refs["beta"], "buscar": "reservado"}
            permitido = cliente.get("/mensajeria", params=params, headers=a)
            self.assertEqual(permitido.status_code, 200)
            self.assertIn(self.doc, permitido.text)
            self.assertNotIn(str(STORAGE_DIR), permitido.text)
            otro = cliente.get("/mensajeria", params={**params, "destinatario": self.refs["gama"]}, headers=a)
            self.assertEqual(otro.status_code, 200)
            self.assertNotIn(self.doc, otro.text)
            self.assertNotIn("Reservado", otro.text)
            self.assertEqual(cliente.get("/mensajeria", params=params, headers={**a, "Origin": "http://ajeno"}).status_code, 403)
            with conectar() as db:
                db.execute("UPDATE documentos SET titulo='<img src=x onerror=alert(1)>'")
            titulo = cliente.get("/mensajeria", params={**params, "buscar": ""}, headers=a).text
            self.assertIn("&lt;img", titulo)
            self.assertNotIn("<img", titulo)
            with conectar() as db:
                db.execute("UPDATE documentos SET titulo='Reservado', eliminado_en='2026-01-01'")
            self.assertNotIn(self.doc, cliente.get("/mensajeria", params=params, headers=a).text)

    def test_proyecciones_para_bandeja_respetan_autorizacion_y_retencion(self):
        cliente = self.cliente()
        a, b, c = (_login(cliente, usuario) for usuario in ("alfa", "beta", "gama"))
        ruta = self._mensaje(self._biblioteca(cliente, a))
        chat = ruta.split("/")[5]
        estado = cliente.get(P + "/sincronizacion", headers=b).json()
        ficha = estado["conversaciones"]["elementos"][0]
        self.assertEqual(ficha["no_leidos"], 1)
        self.assertEqual(ficha["ultimo"]["texto"], "Texto ficticio")
        self.assertEqual(ficha["otro"]["area"], "Tesorería")
        self.assertEqual(cliente.get(P + "/conversaciones", headers=c).json()["elementos"], [])
        self.assertEqual(cliente.get(P + "/conversaciones/" + chat + "/mensajes", headers=b).json()["elementos"][0]["enviado"], False)
        self.instante += motor.RETENCION
        a = _login(cliente, "alfa")
        ficha = cliente.get(P + "/conversaciones", headers=a).json()["elementos"][0]
        self.assertIsNone(ficha["ultimo"])
        self.assertEqual(ficha["no_leidos"], 0)

    def test_listados_paginados_lectura_archivo_y_sincronizacion(self):
        cliente = self.cliente()
        a, b, c = (_login(cliente, u) for u in ("alfa", "beta", "gama"))
        destinatarios = cliente.get(P + "/destinatarios?limite=1", headers=a).json()
        self.assertEqual(len(destinatarios["elementos"]), 1)
        segundo = cliente.get(P + "/destinatarios", params={"despues": destinatarios["siguiente"]}, headers=a).json()
        self.assertNotEqual(destinatarios["elementos"][0], segundo["elementos"][0])
        self.assertTrue(segundo["elementos"][0]["nombre"].startswith("Perfil"))
        ruta = self._mensaje(self._biblioteca(cliente, a))
        self._mensaje(self._biblioteca(cliente, a))
        motor.conversacion(self.refs["alfa"], self.refs["gama"], crear=True)
        primero = cliente.get(P + "/conversaciones?limite=1", headers=a).json()
        self.assertEqual(len(primero["elementos"]), 1)
        otra = cliente.get(P + "/conversaciones", params={"despues": primero["siguiente"]}, headers=a).json()
        self.assertNotEqual(otra["elementos"][0]["id"], primero["elementos"][0]["id"])
        lista = ruta.rsplit("/", 1)[0]
        pagina = cliente.get(lista + "?limite=1", headers=b).json()
        siguiente = cliente.get(lista, params={"antes": pagina["siguiente"]}, headers=b).json()
        self.assertNotEqual(pagina["elementos"][0]["id"], siguiente["elementos"][0]["id"])
        self.assertEqual(cliente.get(lista, headers=c).status_code, 404)
        self.assertEqual(cliente.get(P + "/sincronizacion", headers=b).json()["no_leidos"], 2)
        self.assertEqual(cliente.post(ruta + "/lectura", headers=a).status_code, 404)
        self.assertEqual(cliente.post(ruta + "/lectura", headers=c).status_code, 404)
        self.assertEqual(cliente.post(ruta + "/lectura", headers=b).status_code, 200)
        self.assertEqual(cliente.get(P + "/sincronizacion", headers=b).json()["no_leidos"], 1)
        archivo = lista.rsplit("/", 1)[0] + "/archivo"
        self.assertEqual(cliente.post(archivo, headers=b, json={"archivada": True}).status_code, 200)
        self.assertEqual(cliente.get(P + "/conversaciones", headers=b).json()["elementos"], [])
        self.assertEqual(len(cliente.get(P + "/conversaciones?archivadas=true", headers=b).json()["elementos"]), 1)
        self.assertEqual(len(cliente.get(P + "/conversaciones", headers=a).json()["elementos"]), 2)

    def test_sincronizacion_http_despues_de_reconectar_ws(self):
        app = _app(habilitada=False)
        websocket.instalar(app, origenes=[ORIGEN], secreto=SECRETO, https_only=False, intervalo=.2)
        api_http.instalar(app, origenes=[ORIGEN], https_only=False)
        with TestClient(app) as cliente:
            a, b = (_login(cliente, u) for u in ("alfa", "beta"))
            self.assertEqual(self._biblioteca(cliente, a).status_code, 200)
            with cliente.websocket_connect(websocket.RUTA, headers=b) as ws:
                self.assertEqual(ws.receive_json()["tipo"], "conexion_lista")
                ws.send_json({"tipo": "sincronizar", "cursor": None})
                primero = ws.receive_json()["cursor"]
            self.assertEqual(self._biblioteca(cliente, a).status_code, 200)
            with cliente.websocket_connect(websocket.RUTA, headers=b) as ws:
                self.assertEqual(ws.receive_json()["tipo"], "conexion_lista")
                ws.send_json({"tipo": "sincronizar", "cursor": primero})
                self.assertEqual(ws.receive_json()["tipo"], "mensaje_nuevo")
                estado = cliente.get(P + "/sincronizacion", headers=b).json()
                self.assertEqual(estado["no_leidos"], 2)
                self.assertEqual(len(estado["conversaciones"]["elementos"]), 1)

    def test_externo_idempotente_descarga_y_limpieza_concurrente(self):
        cliente = self.cliente()
        a, b, c = (_login(cliente, u) for u in ("alfa", "beta", "gama"))
        datos = self._externo(cliente, a, nombre="dato ñ.txt")
        confirmada = self._confirmar(cliente, a, datos)
        ruta = self._mensaje(confirmada)
        self.assertEqual(self._subir(cliente, a, datos, nombre="dato ñ.txt").json()["nombre"], datos["nombre"])
        self.assertEqual(self._confirmar(cliente, a, datos).json(), confirmada.json())
        self.assertEqual(self._confirmar(cliente, a, {**datos, "texto": "Otro"}).status_code, 409)
        self.assertEqual(cliente.get(P + "/cuota", headers=a).json()["envios"], 1)
        self.assertEqual(cliente.get(ruta + "/adjunto", headers=b).json()["nombre_original"], "dato ñ.txt")
        self.assertEqual(cliente.get(ruta + "/adjunto/descarga", headers=c).status_code, 404)
        descarga = cliente.get(ruta + "/adjunto/descarga", headers=b)
        self.assertEqual(descarga.content, b"Ficticio")
        self.assertEqual(descarga.headers["cache-control"], "private, no-store")
        self.assertIn("%C3%B1", descarga.headers["content-disposition"])
        self.assertEqual(descarga.headers["content-type"], "application/octet-stream")
        abrir = adjuntos.abrir_descarga

        @contextmanager
        def durante(*args, **kwargs):
            with abrir(*args, **kwargs) as flujo:
                self.instante += motor.VIGENCIA_ARCHIVO
                self.assertEqual(limpieza.limpiar()["aplazados"], 1)
                yield flujo

        with patch.object(adjuntos, "abrir_descarga", durante):
            self.assertEqual(cliente.get(ruta + "/adjunto/descarga", headers=b).content, b"Ficticio")
        self.assertEqual(cliente.get(ruta + "/adjunto", headers=b).json(), {"estado": "no_disponible"})
        self.assertEqual(cliente.get(ruta + "/adjunto/descarga", headers=b).status_code, 404)
        self.instante += 61
        self.assertEqual(limpieza.limpiar()["retirados"], 1)

    def test_respuesta_perdida_despues_del_commit(self):
        app = _app()
        cortar = False
        estados = []

        class CorteSimulado(Exception):
            pass

        async def interponer(scope, receive, send):
            async def salida(evento):
                if cortar and scope["path"].endswith("/confirmar") and evento["type"] == "http.response.start":
                    estados.append(evento["status"])
                    raise CorteSimulado
                await send(evento)
            await app(scope, receive, salida if scope["type"] == "http" else send)

        with TestClient(interponer) as cliente:
            a = _login(cliente, "alfa")
            datos = self._externo(cliente, a)
            cortar = True
            with self.assertRaises(CorteSimulado):
                self._confirmar(cliente, a, datos)
            cortar = False
            self.assertEqual(estados, [200])
            with bd._conectar_infraestructura() as db:
                identificador = db.execute("SELECT id FROM mensajes").fetchone()[0]
            self.assertEqual(self._confirmar(cliente, a, datos).json(), {"mensaje": identificador})
            self.assertEqual(cliente.get(P + "/cuota", headers=a).json()["envios"], 1)
            self.assertEqual(len(list((self.base.parent / "temporales").glob("*.bin"))), 1)

    def test_biblioteca_modalidad_vencimiento_y_revocacion(self):
        cliente = self.cliente()
        a, b = (_login(cliente, u) for u in ("alfa", "beta"))
        self.assertEqual(self._biblioteca(cliente, a, destino="gama").status_code, 404)
        vista = self._mensaje(self._biblioteca(cliente, a))
        ruta = self._mensaje(self._biblioteca(cliente, a, "visualizar_y_descargar"))
        self.assertEqual(cliente.get(vista + "/adjunto/descarga", headers=b).status_code, 404)
        self.assertEqual(cliente.get(vista + "/adjunto/vista", headers=b).status_code, 501)
        self.assertEqual(cliente.get(ruta + "/adjunto/descarga", headers=b).content, b"Original")
        for sql in ("UPDATE documentos SET eliminado_en='2026-01-01'",
                    "UPDATE documentos SET eliminado_en=NULL,departamento='Archivos'"):
            with conectar() as db:
                db.execute(sql)
            self.assertEqual(cliente.get(ruta + "/adjunto", headers=b).json(), {"estado": "no_disponible"})
        with conectar() as db:
            db.execute("UPDATE documentos SET departamento='Tesorería'")
        self.instante += motor.VIGENCIA_DOCUMENTO
        b = _login(cliente, "beta")
        self.assertEqual(cliente.get(ruta + "/adjunto", headers=b).json(), {"estado": "no_disponible"})

    def test_multipart_rechazos_y_espacio(self):
        cliente = self.cliente()
        a = _login(cliente, "alfa")
        for nombre, contenido, estado in (("vacio.txt", b"", 400), ("programa.exe", b"Ficticio", 415),
                                         ("archivo.pdf", b"Ficticio", 415), ("../dato.txt", b"Ficticio", 400)):
            with self.subTest(nombre=nombre):
                self.assertEqual(self._subir(cliente, a, self.datos(), nombre, contenido).status_code, estado)
        with patch.object(adjuntos.shutil, "disk_usage", return_value=type("Disco", (), {"free": 1})()):
            self.assertEqual(self._subir(cliente, a, self.datos()).status_code, 507)
        hdr = {**a, "X-SIGED-Destinatario": self.refs["beta"], "Idempotency-Key": uuid4().hex,
               "Content-Type": "multipart/form-data; boundary=x"}
        incompleto = b'--x\r\nContent-Disposition: form-data; name="archivo"; filename="dato.txt"\r\n\r\nparcial'
        self.assertEqual(cliente.post(P + "/envios/externos/preparar", headers=hdr, content=incompleto).status_code, 400)
        self.assertEqual(cliente.get(P + "/cuota", headers=a).json()["envios"], 0)
        self.assertEqual(list((self.base.parent / "temporales").iterdir()), [])

    def test_plazos_y_corte_de_recepcion_asgi(self):
        app = _app()
        with TestClient(app) as cliente:
            a = _login(cliente, "alfa")
            hdr = {**a, "Host": "testserver", "X-SIGED-Destinatario": self.refs["beta"],
                   "Content-Type": "multipart/form-data; boundary=x"}
            ruta = P + "/envios/externos/preparar"

            async def simular(lento):
                encabezados = {**hdr, "Idempotency-Key": uuid4().hex}
                scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "scheme": "http",
                         "method": "POST", "path": ruta, "raw_path": ruta.encode(), "query_string": b"",
                         "root_path": "", "server": ("testserver", 80), "client": ("127.0.0.1", 1),
                         "headers": [(k.lower().encode(), v.encode()) for k, v in encabezados.items()]}
                contador = 0
                salida = []

                async def receive():
                    nonlocal contador
                    contador += 1
                    if contador == 1:
                        return {"type": "http.request", "more_body": True,
                                "body": b'--x\r\nContent-Disposition: form-data; name="archivo"; filename="a.txt"\r\n\r\nabc'}
                    if lento:
                        await asyncio.sleep(2)
                    return {"type": "http.disconnect"}

                async def send(evento):
                    salida.append(evento)

                await app(scope, receive, send)
                return salida[0]["status"]

            self.assertEqual(cliente.portal.call(simular, False), 400)
            with patch.object(recepcion_http, "CARGA_INACTIVA", .15):
                self.assertEqual(cliente.portal.call(simular, True), 408)
        self.assertEqual(list((self.base.parent / "temporales").iterdir()), [])

    def test_plazo_total_aun_con_avance_y_limite_sin_longitud(self):
        async def ejecutar():
            async def goteo():
                await asyncio.sleep(.02)
                return {"type": "http.request", "more_body": True, "body": b"x"}

            entrada = recepcion_http.Entrada(SimpleNamespace(receive=goteo), 100, .12, .10)
            bloques = 0
            with self.assertRaisesRegex(motor.ErrorMotor, "plazo_http_agotado"):
                while await entrada.bloque():
                    bloques += 1
            self.assertGreater(bloques, 0)
            entrada = recepcion_http.Entrada(SimpleNamespace(receive=goteo), 2, 2, 1)
            self.assertEqual(await entrada.bloque(), b"x")
            self.assertEqual(await entrada.bloque(), b"x")
            with self.assertRaisesRegex(motor.ErrorMotor, "cuerpo_demasiado_grande"):
                await entrada.bloque()

        asyncio.run(ejecutar())

    def test_loopback_multipart_20_mib_chunked_y_limite_http(self):
        fuente = RAIZ / "grande.txt"
        sha = hashlib.sha256()
        with fuente.open("xb") as archivo:
            for _ in range(20):
                bloque = b"a" * MIB
                archivo.write(bloque)
                sha.update(bloque)
        with _servidor() as origen, httpx.Client(base_url=origen, timeout=90, trust_env=False) as cliente:
            a = _login(cliente, "alfa", origen)
            with fuente.open("rb") as archivo:
                datos = self._externo(cliente, a, contenido=archivo)
            self.assertEqual(datos["tamano_bytes"], 20 * MIB)
            ruta = self._mensaje(self._confirmar(cliente, a, datos))
            resultado = hashlib.sha256()
            with cliente.stream("GET", ruta + "/adjunto/descarga", headers=a) as descarga:
                self.assertEqual(descarga.headers["content-length"], str(20 * MIB))
                for bloque in descarga.iter_bytes():
                    resultado.update(bloque)
            self.assertEqual(resultado.digest(), sha.digest())
            with fuente.open("ab") as archivo:
                archivo.write(b"x")
            with fuente.open("rb") as archivo:
                self.assertEqual(self._subir(cliente, a, self.datos(), contenido=archivo).status_code, 413)
            datos = self.datos()
            hdr = {**a, "X-SIGED-Destinatario": datos["destinatario"], "Idempotency-Key": datos["clave"],
                   "Content-Type": "multipart/form-data; boundary=x"}
            trozos = (b'--x\r\nContent-Disposition: form-data; name="archivo"; filename="a.txt"\r\n\r\n',
                      b"Texto", b"\r\n--x--\r\n")
            subida = cliente.post(P + "/envios/externos/preparar", headers=hdr, content=iter(trozos))
            self.assertEqual(subida.status_code, 200, subida.text)
            host, puerto = origen.removeprefix("http://").split(":")
            hdr.update({"Host": f"{host}:{puerto}", "Content-Length": str(21 * MIB + 1)})
            peticion = "\r\n".join([f"POST {P}/envios/externos/preparar HTTP/1.1",
                                     *(f"{k}: {v}" for k, v in hdr.items()), "", ""])
            with socket.create_connection((host, int(puerto)), timeout=10) as conexion, conexion.makefile("rb") as flujo:
                conexion.sendall(peticion.encode("ascii"))
                self.assertIn(b" 413 ", flujo.readline())

    def test_cuota_concurrente_y_cierre_antes_de_confirmar(self):
        cliente = self.cliente()
        a = _login(cliente, "alfa")
        primero = self._externo(cliente, a)
        segundo = self._externo(cliente, a)
        dia = motor.cuota(self.refs["alfa"])["dia"]
        with bd._conectar_infraestructura() as db:
            db.execute("INSERT INTO cuotas VALUES (?,?,49)", (self.refs["alfa"], dia))
        with ThreadPoolExecutor(2) as pool:
            tareas = [pool.submit(self._confirmar, cliente, a, datos) for datos in (primero, segundo)]
            self.assertEqual(sorted(t.result(timeout=90).status_code for t in tareas), [200, 429])
        self.assertEqual(motor.cuota(self.refs["alfa"])["envios"], 50)
        self.instante += 86400
        a = _login(cliente, "alfa")
        tercero = self._externo(cliente, a)
        verificar = adjuntos._verificar_archivo

        def revocar(*args):
            flujo = verificar(*args)
            with bd._conectar_infraestructura() as db:
                db.execute("UPDATE sesiones_ws SET revocada=1")
            return flujo

        with patch.object(adjuntos, "_verificar_archivo", side_effect=revocar):
            self.assertEqual(self._confirmar(cliente, a, tercero).status_code, 401)
        self.assertEqual(motor.cuota(self.refs["alfa"])["envios"], 0)

    def test_z_generacion_incompatible_y_purga_documental(self):
        cliente = self.cliente()
        a, b = (_login(cliente, u) for u in ("alfa", "beta"))
        ruta = self._mensaje(self._biblioteca(cliente, a, "visualizar_y_descargar"))
        copia = respaldo.crear_respaldo(RAIZ / "antes-http.zip")
        with conectar() as db:
            db.execute("DELETE FROM documentos")
        self.assertEqual(cliente.get(ruta + "/adjunto", headers=b).json(), {"estado": "no_disponible"})
        respaldo.restaurar_respaldo(copia)
        self.assertEqual(cliente.get(ruta + "/adjunto/descarga", headers=b).status_code, 409)


if __name__ == "__main__":
    unittest.main(verbosity=2)
