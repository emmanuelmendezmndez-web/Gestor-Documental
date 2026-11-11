"""WebSocket experimental con sesiones HTTP y bases ficticias aisladas."""

import asyncio
import json
import socket
import time
import unittest
from base64 import b64decode, b64encode
from contextlib import ExitStack, contextmanager
from threading import Thread
from unittest.mock import patch
from uuid import uuid4

import httpx
import uvicorn
from aislamiento import exigir_directorio_temporal
from fastapi import Depends, FastAPI
from itsdangerous import TimestampSigner
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as conectar_ws

RAIZ = exigir_directorio_temporal("siged-prueba-mensajeria-")

from app import respaldo, temporal_privado
from app.configuracion import STORAGE_DIR
from app.coordinacion import BloqueoNoDisponible
from app.csrf import validar_csrf
from app.database import conectar, inicializar_db
from app.mensajeria import base_datos as bd
from app.mensajeria import eventos, motor, sesiones_ws, websocket
from app.mensajeria import reconciliacion as rec
from app.rutas_cuenta import router as cuenta
from app.rutas_sesion import router as sesion
from app.seguridad import hashear_password

SECRETO = "secreto-exclusivo-del-fixture"
CLAVE = "Contrasena-ficticia-2026"
CSRF = "csrf-ficticio"
ORIGEN = "http://testserver"


def _cookie(datos):
    return TimestampSigner(SECRETO).sign(b64encode(json.dumps(datos).encode())).decode()


def _app(*, origen=ORIGEN, habilitada=True, segura=False):
    app = FastAPI(dependencies=[Depends(validar_csrf)])
    app.add_middleware(SessionMiddleware, secret_key=SECRETO, session_cookie="gestor_sesion",
                       max_age=36000, https_only=segura)
    app.include_router(sesion)
    app.include_router(cuenta)
    admin = websocket.instalar(app, origenes=[origen], secreto=SECRETO,
                               https_only=segura, intervalo=0.4) if habilitada else None
    return app, admin


def _headers(cookie, origen):
    return {"Cookie": f"gestor_sesion={cookie}", "Origin": origen}


def _login(cliente, usuario, origen=ORIGEN):
    respuesta = cliente.post("/login", data={"usuario": usuario, "password": CLAVE, "csrf_token": CSRF},
                            headers=_headers(_cookie({"csrf_token": CSRF}), origen), follow_redirects=False)
    if respuesta.headers.get("location") != "/inicio":
        raise AssertionError("El login ficticio no terminó correctamente")
    return respuesta.cookies["gestor_sesion"]


def _sincronizar(socket_, cursor=None):
    if socket_.receive_json() != {"tipo": "conexion_lista"}:
        raise AssertionError("Falta el saludo técnico")
    socket_.send_json({"tipo": "sincronizar", "cursor": cursor})


@contextmanager
def _servidor():
    """Inicia Uvicorn real solo en loopback, con un puerto ya reservado."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        origen = f"http://127.0.0.1:{listener.getsockname()[1]}"
        app, _ = _app(origen=origen)
        servidor = uvicorn.Server(uvicorn.Config(
            app, ws="websockets", ws_max_size=websocket.MAX_TRAMA, ws_max_queue=2,
            ws_per_message_deflate=False, proxy_headers=False, log_level="warning", access_log=False,
        ))
        hilo = Thread(target=servidor.run, kwargs={"sockets": [listener]}, daemon=True)
        hilo.start()
        try:
            fin = time.monotonic() + 10
            while not servidor.started:
                if not hilo.is_alive() or time.monotonic() > fin:
                    raise AssertionError("No inició el servidor loopback")
                time.sleep(0.01)
            yield origen
        finally:
            servidor.should_exit = True
            hilo.join(10)
            if hilo.is_alive():
                raise AssertionError("El servidor de prueba no terminó")


class WebSocketCasos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_db()
        STORAGE_DIR.mkdir()
        (STORAGE_DIR / "privado-ficticio.txt").write_bytes(b"Ficticio")
        cls.hash = hashear_password(CLAVE)
        with conectar() as db:
            db.executemany(
                "INSERT INTO usuarios(usuario,nombre,password_hash,rol) VALUES (?,?,?,'lector')",
                [(n, n, cls.hash) for n in ("alfa", "beta", "gama", "delta")],
            )
            db.execute(
                """INSERT INTO documentos(titulo,nombre_archivo,nombre_guardado,categoria,tamano_bytes)
                   VALUES ('Título reservado','privado-ficticio.txt','privado-ficticio.txt','Oficios',8)""",
            )
        bd.inicializar()
        informe = rec.preparar_identidades()
        if rec.reconciliar(informe["confirmacion"])["estado"] != "identidad_coherente":
            raise AssertionError("No se pudo reconciliar la prueba")

    def setUp(self):
        with bd._conectar_infraestructura() as db:
            for tabla in ("eventos", "sesiones_ws", "operaciones", "mensajes", "estado_participante",
                          "conversaciones", "cuotas", "limpieza", "reloj_motor"):
                db.execute(f"DELETE FROM {tabla}")
        with conectar() as db:
            db.execute("UPDATE usuarios SET activo=1,version_sesion=0,password_hash=?", (self.hash,))
            self.refs = dict(db.execute("SELECT usuario,mensajeria_ref FROM usuarios"))
            self.ref_doc = db.execute("SELECT mensajeria_ref FROM documentos").fetchone()[0]
        self.instante = 1780000000
        self.enterContext(patch.object(motor, "_ahora", side_effect=lambda: self.instante))

    def _cliente(self):
        app, admin = _app()
        return self.enterContext(TestClient(app)), admin

    def _ws(self, cliente, cookie, *, origen=ORIGEN, url=websocket.RUTA):
        return cliente.websocket_connect(url, headers=_headers(cookie, origen))

    def _emitir(self, usuario="beta", tipo="mensaje_confirmado"):
        with bd._conectar_infraestructura() as db:
            eventos.registrar(db, self.refs[usuario], tipo, self.instante)

    def _cerrado(self, cliente, cookie, **kw):
        with self.assertRaises(WebSocketDisconnect), self._ws(cliente, cookie, **kw):
            self.fail("La conexión no estaba autorizada")

    def test_origen_cookie_y_configuracion_normal(self):
        normal, _ = _app(habilitada=False)
        self.assertFalse(any(getattr(r, "path", None) == websocket.RUTA for r in normal.routes))
        with TestClient(normal) as cliente:
            legado = _login(cliente, "alfa")
        cliente, _ = self._cliente()
        for cookie in ("incorrecta", legado):
            self._cerrado(cliente, cookie)
        cookie = _login(cliente, "alfa")
        for origen in ("null", "https://testserver", "http://otro", "http://testserver/extra"):
            self._cerrado(cliente, cookie, origen=origen)
        with (
            self.assertRaises(WebSocketDisconnect),
            cliente.websocket_connect(websocket.RUTA, headers={"Cookie": f"gestor_sesion={cookie}"}),
        ):
            self.fail("El Origin es obligatorio")
        self._cerrado(cliente, cookie, url=websocket.RUTA + "?token=ficticio")
        with self._ws(cliente, cookie) as ws:
            _sincronizar(ws)
            self.assertEqual(ws.receive_json(), {"tipo": "resincronizar", "cursor": None})
        segura, _ = _app(origen="https://testserver", segura=True)
        with TestClient(segura, base_url="https://testserver") as tls:
            tls_cookie = _login(tls, "alfa", "https://testserver")
            self._cerrado(tls, tls_cookie, origen="https://testserver")
            with self._ws(tls, tls_cookie, origen="https://testserver", url="wss://testserver/mensajeria/ws") as ws:
                _sincronizar(ws)
                self.assertEqual(ws.receive_json()["tipo"], "resincronizar")

    def test_logout_individual_y_otra_sesion_permanece(self):
        cliente, _ = self._cliente()
        una, otra = _login(cliente, "beta"), _login(cliente, "beta")
        with self._ws(cliente, una) as ws, self._ws(cliente, otra) as dispositivo:
            for conexion in (ws, dispositivo):
                _sincronizar(conexion)
                conexion.receive_json()
            sesion_http = json.loads(b64decode(TimestampSigner(SECRETO).unsign(una)))
            # El login rota CSRF. Emula un formulario posterior con su nuevo token.
            sesion_http["csrf_token"] = CSRF
            respuesta = cliente.post("/salir", data={"csrf_token": CSRF},
                                     headers=_headers(_cookie(sesion_http), ORIGEN), follow_redirects=False)
            self.assertEqual(respuesta.status_code, 303)
            with self.assertRaises(WebSocketDisconnect) as error:
                ws.receive_json()
            self.assertEqual(error.exception.code, 1008)
            self._cerrado(cliente, una)
            self._emitir()
            self.assertEqual(dispositivo.receive_json()["tipo"], "mensaje_nuevo")

    def test_expiracion_password_y_revocacion_administrativa(self):
        cliente, _ = self._cliente()
        acciones = ("expirar", "password", "version", "desactivar", "identidad")
        for accion in acciones:
            with self.subTest(accion=accion):
                cookie = _login(cliente, "beta")
                with self._ws(cliente, cookie) as ws:
                    _sincronizar(ws)
                    ws.receive_json()
                    if accion == "expirar":
                        self.instante += sesiones_ws.VIGENCIA
                    elif accion == "password":
                        datos = json.loads(b64decode(TimestampSigner(SECRETO).unsign(cookie)))
                        datos["csrf_token"] = CSRF
                        respuesta = cliente.post(
                            "/cuenta/password", headers=_headers(_cookie(datos), ORIGEN), follow_redirects=False,
                            data={"actual": CLAVE, "nueva": CLAVE + "-nueva", "confirmacion": CLAVE + "-nueva",
                                  "csrf_token": CSRF},
                        )
                        self.assertIn("password_cambiada", respuesta.headers["location"])
                    else:
                        with conectar() as db:
                            if accion == "version":
                                db.execute("UPDATE usuarios SET version_sesion=version_sesion+1 WHERE usuario='beta'")
                            elif accion == "desactivar":
                                db.execute("UPDATE usuarios SET activo=0 WHERE usuario='beta'")
                            else:
                                numero = db.execute("SELECT id FROM usuarios WHERE usuario='beta'").fetchone()[0]
                                db.execute("DELETE FROM usuarios WHERE id=?", (numero,))
                                db.execute(
                                    "INSERT INTO usuarios(id,usuario,nombre,password_hash,rol) "
                                    "VALUES (?,'beta','beta',?,'lector')", (numero, self.hash),
                                )
                                self.refs["beta"] = db.execute(
                                    "SELECT mensajeria_ref FROM usuarios WHERE id=?", (numero,),
                                ).fetchone()[0]
                    with self.assertRaises(WebSocketDisconnect) as error:
                        ws.receive_json()
                    self.assertEqual(error.exception.code, 1008)
                self._cerrado(cliente, cookie)
                with conectar() as db:
                    db.execute("UPDATE usuarios SET activo=1,password_hash=? WHERE usuario='beta'", (self.hash,))

    def test_logout_respalda_revocacion_si_falla_sqlite_privado(self):
        cliente, _ = self._cliente()
        cookie = _login(cliente, "beta")
        datos = json.loads(b64decode(TimestampSigner(SECRETO).unsign(cookie)))
        datos["csrf_token"] = CSRF
        with patch.object(sesiones_ws, "_bases", side_effect=OSError("ficticio")):
            respuesta = cliente.post("/salir", data={"csrf_token": CSRF},
                                     headers=_headers(_cookie(datos), ORIGEN), follow_redirects=False)
        self.assertEqual(respuesta.status_code, 303)
        with conectar() as db:
            self.assertEqual(db.execute("SELECT version_sesion FROM usuarios WHERE usuario='beta'").fetchone()[0], 1)
        self._cerrado(cliente, cookie)

    def test_paginacion_y_ancla_depurada(self):
        with rec._bases() as (_, db, generacion):
            actor = self.refs["beta"]
            secreto = SECRETO.encode()
            eventos.registrar(db, actor, "mensaje_confirmado", self.instante)
            ancla = eventos.pagina(db, actor, generacion, None, True, self.instante, secreto)[0]["cursor"]
            for _ in range(33):
                eventos.registrar(db, actor, "mensaje_confirmado", self.instante)
            lote = eventos.pagina(db, actor, generacion, ancla, True, self.instante, secreto)
            self.assertEqual(len(lote), 32)
            self.assertEqual(len(eventos.pagina(db, actor, generacion, lote[-1]["cursor"],
                                               False, self.instante, secreto)), 1)
            db.execute("DELETE FROM eventos WHERE destinatario_ref=? AND cursor=?", (actor, ancla[:32]))
            self.assertEqual(eventos.pagina(db, actor, generacion, ancla, True, self.instante, secreto)[0]["tipo"],
                             "resincronizar")

    def test_acl_base_se_revalida_si_cambia_el_descriptor(self):
        ruta = RAIZ / ".siged-mensajeria"
        comprobar = temporal_privado.verificar_acl_base_privada
        temporal_privado._acl_base_verificadas.clear()
        with patch.object(temporal_privado, "_verificar_acl", wraps=temporal_privado._verificar_acl) as control:
            comprobar(ruta, bd.NOMBRE_BASE, 30)
            comprobar(ruta, bd.NOMBRE_BASE, 6)
            self.assertEqual(control.call_count, 1)
        volumen, archivo, descriptor = temporal_privado._huella_acl(ruta)
        with (
            patch.object(temporal_privado, "_huella_acl", return_value=(volumen, archivo, descriptor + b"cambio")),
            patch.object(temporal_privado, "_verificar_acl", side_effect=OSError("ACL ficticia rechazada")),
            self.assertRaises(OSError),
        ):
            comprobar(ruta, bd.NOMBRE_BASE, 6)

    def test_cursor_repetido_privacidad_y_cambios_confirmados(self):
        cliente, _ = self._cliente()
        receptor, tercero = _login(cliente, "beta"), _login(cliente, "gama")
        clave = uuid4().hex
        adjunto = motor.Adjunto("documento", self.ref_doc, modalidad="visualizar")
        with self._ws(cliente, receptor) as ws:
            _sincronizar(ws)
            ws.receive_json()
            mensaje = motor.enviar(self.refs["alfa"], self.refs["beta"], "texto privado", clave, adjunto)
            uno = ws.receive_json()
            self.assertEqual(set(uno), {"tipo", "cursor"})
            self.assertEqual(uno["tipo"], "mensaje_nuevo")
            self.assertNotIn(mensaje, json.dumps(uno))
            self.assertNotIn("privado", json.dumps(uno))
            self.assertEqual(motor.enviar(self.refs["alfa"], self.refs["beta"], "texto privado", clave, adjunto),
                             mensaje)
            motor.marcar_leido(self.refs["beta"], mensaje)
            motor.marcar_leido(self.refs["beta"], mensaje)
            dos = ws.receive_json()
            self.assertEqual(dos["tipo"], "lectura_actualizada")
        chat = motor.conversacion(self.refs["alfa"], self.refs["beta"])
        motor.archivar(self.refs["beta"], chat)
        self.assertEqual(motor.cuota(self.refs["alfa"])["envios"], 1)
        for _ in range(2):
            with self._ws(cliente, receptor) as ws:
                _sincronizar(ws, uno["cursor"])
                self.assertEqual(ws.receive_json(), dos)
                self.assertEqual(ws.receive_json()["tipo"], "bandeja_actualizada")
        with self._ws(cliente, tercero) as ws:
            _sincronizar(ws, uno["cursor"])
            self.assertEqual(ws.receive_json(), {"tipo": "resincronizar", "cursor": None})
            self._emitir("gama", "bandeja_actualizada")
            self.assertEqual(ws.receive_json()["tipo"], "bandeja_actualizada")
        self.instante += motor.RETENCION
        with self._ws(cliente, _login(cliente, "beta")) as ws:
            _sincronizar(ws, uno["cursor"])
            self.assertEqual(ws.receive_json(), {"tipo": "resincronizar", "cursor": None})

    def test_trece_conexiones_cupos_y_tramas(self):
        cliente, admin = self._cliente()
        cookies = [_login(cliente, usuario) for usuario in ("alfa", "beta", "gama", "delta")]
        with ExitStack() as pila:
            conexiones = []
            for cookie in [c for c in cookies[:3] for _ in range(4)] + cookies[3:]:
                ws = pila.enter_context(self._ws(cliente, cookie))
                _sincronizar(ws)
                self.assertEqual(ws.receive_json()["tipo"], "resincronizar")
                conexiones.append(ws)
            self._cerrado(cliente, cookies[0])
            self._emitir()
            for ws in conexiones[4:8]:
                self.assertEqual(ws.receive_json()["tipo"], "mensaje_nuevo")
            conexiones[0].send_json({"tipo": "sincronizar", "cursor": None})
            with self.assertRaises(WebSocketDisconnect) as error:
                conexiones[0].receive_json()
            self.assertEqual(error.exception.code, 1008)
        self.assertEqual(len(admin._activas), 0)
        with self._ws(cliente, cookies[0]) as ws:
            self.assertEqual(ws.receive_json()["tipo"], "conexion_lista")
            ws.send_text("x" * (websocket.MAX_TRAMA + 1))
            with self.assertRaises(WebSocketDisconnect) as error:
                ws.receive_json()
            self.assertEqual(error.exception.code, 1009)

    def test_cliente_lento_y_liberacion_del_cupo(self):
        app, admin = _app()

        async def asgi(scope, receive, send):
            async def lento(evento):
                if evento["type"] == "websocket.send":
                    await asyncio.sleep(1)
                await send(evento)
            await app(scope, receive, lento if scope["type"] == "websocket" else send)

        with TestClient(asgi) as cliente, patch.object(websocket, "PLAZO_ENVIO", 0.1):
            cookie = _login(cliente, "beta")
            with self._ws(cliente, cookie) as ws, self.assertRaises(WebSocketDisconnect) as error:
                ws.receive_json()
            self.assertEqual(error.exception.code, 1013)
            self.assertEqual(len(admin._activas), 0)
            self.assertFalse(admin._pendientes)

    def test_upgrade_loopback_corte_reinicio_y_limite_de_transporte(self):
        self._emitir()
        with _servidor() as origen, httpx.Client(base_url=origen, timeout=15, trust_env=False) as cliente:
            cookie = _login(cliente, "beta", origen)
            with conectar_ws(origen.replace("http", "ws") + websocket.RUTA, origin=origen,
                             additional_headers={"Cookie": f"gestor_sesion={cookie}"}, proxy=None) as ws:
                self.assertEqual(json.loads(ws.recv(timeout=15))["tipo"], "conexion_lista")
                ws.send('{"tipo":"sincronizar","cursor":null}')
                cursor = json.loads(ws.recv(timeout=15))["cursor"]
                # Cierra el transporte sin enviar un cierre WebSocket ordenado.
                ws.socket.shutdown(socket.SHUT_RDWR)
        self._emitir()
        with _servidor() as origen, conectar_ws(
            origen.replace("http", "ws") + websocket.RUTA, origin=origen,
            additional_headers={"Cookie": f"gestor_sesion={cookie}"}, proxy=None,
        ) as ws:
            self.assertEqual(json.loads(ws.recv(timeout=15))["tipo"], "conexion_lista")
            ws.send(json.dumps({"tipo": "sincronizar", "cursor": cursor}))
            self.assertEqual(json.loads(ws.recv(timeout=15))["tipo"], "mensaje_nuevo")
            ws.send("x" * (websocket.MAX_TRAMA + 1))
            with self.assertRaises(ConnectionClosed) as error:
                ws.recv(timeout=15)
            self.assertEqual(error.exception.rcvd.code, 1009)

    def test_z_restauracion_cierra_y_requiere_sesion_de_generacion_nueva(self):
        copia = respaldo.crear_respaldo(RAIZ / "antes-ws.zip")
        cliente, _ = self._cliente()
        cookie = _login(cliente, "beta")
        self._emitir()
        with self._ws(cliente, cookie) as ws:
            _sincronizar(ws)
            anterior = ws.receive_json()["cursor"]
            fin = time.monotonic() + 10
            while True:
                try:
                    respaldo.restaurar_respaldo(copia)
                except BloqueoNoDisponible:
                    if time.monotonic() > fin:
                        raise
                    time.sleep(0.02)
                else:
                    break
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()
        self._cerrado(cliente, cookie)
        informe = rec.diagnosticar()
        self.assertEqual(informe["estado"], "generacion_incompatible")
        self.assertEqual(rec.reconciliar(informe["confirmacion"])["estado"], "identidad_coherente")
        self._cerrado(cliente, cookie)
        with self._ws(cliente, _login(cliente, "beta")) as ws:
            _sincronizar(ws, anterior)
            self.assertEqual(ws.receive_json()["tipo"], "resincronizar")


if __name__ == "__main__":
    unittest.main(verbosity=2)
