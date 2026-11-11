"""Arranque unificado con datos ficticios y sin instalar servicios."""

import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI

from app import arranque, parada_siged, proxy_siged


class ArranqueTest(unittest.TestCase):
    def test_host_operativo_exige_dns_o_ipv4_de_lan(self):
        for host in ("", "localhost", "127.0.0.2", "https://siged.test", "siged.test:8000", "*", "siged.test/"):
            with (self.subTest(host=host), patch.dict(os.environ, SIGED_HOST=host),
                  self.assertRaises(proxy_siged.ProxyNoDisponible)):
                proxy_siged.host_configurado()
        for host in ("siged.test", "192.168.5.12"):
            with patch.dict(os.environ, SIGED_HOST=host):
                self.assertEqual(proxy_siged.host_configurado(), host)

    def test_caddy_ausente_y_servicio_existente(self):
        with (patch.dict(os.environ, SIGED_HOST="siged.test"), patch.object(proxy_siged.shutil, "which", return_value=None),
              self.assertRaisesRegex(proxy_siged.ProxyNoDisponible, "PATH")):
            proxy_siged.preparar(arranque.RAIZ)
        with patch.object(proxy_siged.subprocess, "run", side_effect=[
            SimpleNamespace(stdout="Running\n"), SimpleNamespace(stdout=""),
        ]):
            self.assertTrue(proxy_siged._externo())
        with patch.object(proxy_siged.subprocess, "run", side_effect=[
            SimpleNamespace(stdout="Stopped\n"), SimpleNamespace(stdout=""),
        ]), self.assertRaisesRegex(proxy_siged.ProxyNoDisponible, "detenido"):
            proxy_siged._externo()
        with patch.object(proxy_siged.subprocess, "Popen") as lanzar:
            self.assertIsNone(proxy_siged.iniciar(proxy_siged.Proxy("siged.test", "caddy.exe", Path("Caddyfile"), True)))
            lanzar.assert_not_called()

    def test_disponibilidad_exige_proxy_correcto_cookie_segura_y_denegacion_ws(self):
        proxy = SimpleNamespace(host="siged.test")
        cookie = "gestor_sesion=ficticia; path=/; httponly; samesite=lax; secure"
        with (patch.object(arranque, "_estado", side_effect=[(204, "_estado"), (200, cookie), (401, "")]),
              patch.object(arranque, "_rechaza_ws", return_value=True)):
            self.assertTrue(arranque._disponible(proxy, "/_estado", 8000))
        with (patch.object(arranque, "_estado", side_effect=[(204, "_estado"), (200, cookie.removesuffix("; secure"))]),
              patch.object(arranque, "_rechaza_ws") as ws):
            self.assertFalse(arranque._disponible(proxy, "/_estado", 8000))
            ws.assert_not_called()
        with (patch.object(arranque, "_estado", side_effect=[(204, "_estado"), (200, cookie), (401, "")]),
              patch.object(arranque, "_rechaza_ws", return_value=False)):
            self.assertFalse(arranque._disponible(proxy, "/_estado", 8000))
        with (patch.object(arranque, "_estado", return_value=(204, "otra-instancia")),
              patch.object(arranque, "_rechaza_ws") as ws):
            self.assertFalse(arranque._disponible(proxy, "/_estado", 8000))
            ws.assert_not_called()

    def test_fallback_no_rebaja_https_explicito(self):
        with (patch.dict(os.environ, {arranque.ACTIVACION: "1", "GESTOR_HTTPS_ONLY": "1"}),
              patch("app.coordinacion.BloqueoDatos"),
              patch.object(arranque, "_preparar", side_effect=proxy_siged.ProxyNoDisponible("Falta Caddy")),
              patch.object(arranque.uvicorn, "Server") as servidor):
            self.assertEqual(arranque._servir(None, lambda: False, False, 8000), 1)
            servidor.assert_not_called()

    def test_certificado_invalido_interrumpe_el_sondeo(self):
        with patch.object(proxy_siged, "HTTPSConnection") as conexion:
            conexion.return_value.connect.side_effect = ssl.SSLCertVerificationError("certificado ficticio")
            with self.assertRaisesRegex(proxy_siged.ProxyNoDisponible, "autoridad"):
                proxy_siged.verificar_tls("siged.test", None)
            conexion.return_value.close.assert_called_once()

    def test_almacen_bloqueado_o_sin_reconciliar_impide_el_montaje(self):
        with (patch.dict(os.environ, GESTOR_MENSAJERIA_DIR="laboratorio-ficticio"),
              patch.object(arranque, "find_spec", return_value=True), patch.object(proxy_siged, "preparar"),
              patch("app.mensajeria.reconciliacion._bases") as bases,
              patch("app.mensajeria.reconciliacion._vinculo_vigente", return_value=False)):
            bases.side_effect = sqlite3.OperationalError("database is locked")
            with self.assertRaisesRegex(proxy_siged.ProxyNoDisponible, "bloqueo"):
                arranque._preparar()
            bases.side_effect = None
            bases.return_value.__enter__.return_value = (None, None, "ficticia")
            with self.assertRaisesRegex(proxy_siged.ProxyNoDisponible, "reconciliación"):
                arranque._preparar()

    def test_activacion_monta_los_tres_componentes_en_la_misma_aplicacion(self):
        app = FastAPI()
        proxy = proxy_siged.Proxy("siged.test", "caddy.exe", Path("Caddyfile"), True)
        with (
            patch.dict(os.environ, {arranque.ACTIVACION: "1"}),
            patch.dict(sys.modules, {"app.main": SimpleNamespace(app=app)}),
            patch("app.coordinacion.BloqueoDatos"),
            patch.object(arranque, "_preparar", return_value=proxy),
            patch.object(proxy_siged, "verificar_tls"),
            patch("app.seguridad.obtener_clave_secreta", return_value="ficticia"),
            patch.object(arranque.uvicorn, "Server") as servidor,
            patch.object(arranque, "Thread"),
        ):
            arranque._servir(None, lambda: False, False, 8000)
            self.assertEqual(os.environ["GESTOR_HTTPS_ONLY"], "1")
        rutas = {ruta.path for ruta in app.routes}
        self.assertTrue({"/mensajeria", "/mensajeria/ws", "/mensajeria/api/v1"} <= rutas)
        configuracion = servidor.call_args.args[0]
        self.assertIs(configuracion.app, app)
        self.assertEqual((configuracion.host, configuracion.workers, configuracion.forwarded_allow_ips),
                         ("127.0.0.1", 1, "127.0.0.1"))
        self.assertEqual((configuracion.ws_max_size, configuracion.ws_max_queue), (1024, 2))
        self.assertFalse(configuracion.ws_per_message_deflate)

    def test_navegador_espera_la_comprobacion_de_disponibilidad(self):
        servidor = SimpleNamespace(started=True)
        fin = SimpleNamespace(wait=iter((False, False, True)).__next__)
        resultado = {}
        with (patch.object(arranque, "_disponible", side_effect=[False, True]) as verificar,
              patch.object(arranque.webbrowser, "open") as abrir):
            # Event.wait recibe el plazo de espera en cada comprobación.
            siguiente = fin.wait
            fin.wait = lambda _: siguiente()
            arranque._vigilar(servidor, lambda: False, fin, resultado, None, None, None, True, 8123)
            self.assertEqual(verificar.call_count, 2)
            abrir.assert_called_once_with("http://127.0.0.1:8123")
            self.assertTrue(resultado["listo"])

    @unittest.skipUnless(os.name == "nt", "El lanzador usa objetos de Windows")
    def test_senal_y_job_de_windows(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            self.assertFalse(parada_siged.solicitar(raiz))
            with parada_siged.escuchar(raiz) as detener:
                self.assertFalse(detener())
                with self.assertRaises(FileExistsError), parada_siged.escuchar(raiz):
                    self.fail("Dos lanzadores no deben compartir el evento")
                self.assertTrue(parada_siged.solicitar(raiz))
                self.assertTrue(detener())
        proceso = subprocess.Popen(
            [sys._base_executable, "-c", "from threading import Event; Event().wait(30)"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            cerrar = parada_siged.custodiar_proceso(proceso.pid)
            cerrar()
            proceso.wait(timeout=10)
        finally:
            if proceso.poll() is None:
                proceso.kill()
                proceso.wait(timeout=5)

    @unittest.skipUnless(os.name == "nt" and sys.prefix != sys.base_prefix, "Requiere .venv de SIGED en Windows")
    def test_bat_real_reserva_puerto_y_admite_reinicio(self):
        with tempfile.TemporaryDirectory(prefix="siged-arranque-") as temporal:
            env = {**os.environ, "GESTOR_DATA_DIR": temporal, "GESTOR_SECRET_KEY": "clave-ficticia-de-arranque",
                   arranque.ACTIVACION: "0", "GESTOR_HTTPS_ONLY": "0", "PYTHONUTF8": "1"}
            env["GESTOR_MENSAJERIA_DIR"] = str(Path(temporal) / ".siged-mensajeria")
            subprocess.run(
                [sys.executable, "-c", "from app.database import inicializar_db; inicializar_db()"],
                cwd=arranque.RAIZ, env=env, timeout=30, check=True,
            )
            bat = arranque.RAIZ / "Iniciar SIGED.bat"
            with socket.socket() as ocupado:
                ocupado.bind((arranque.HOST, 0))
                ocupado.listen()
                puerto = ocupado.getsockname()[1]
                comando = ["cmd.exe", "/d", "/c", "call", str(bat), "--sin-navegador", "--puerto-local", str(puerto)]
                conflicto = subprocess.run(comando, cwd=temporal, env=env, stdin=subprocess.DEVNULL,
                                           capture_output=True, text=True, timeout=30, check=False)
                self.assertNotEqual(conflicto.returncode, 0)
                self.assertIn("no puede reservar", conflicto.stdout)
            for intento in range(2):
                with self.subTest(intento=intento), tempfile.TemporaryFile(mode="w+b") as salida:
                    proceso = subprocess.Popen(comando, cwd=temporal, env=env, stdin=subprocess.DEVNULL,
                                               stdout=salida, stderr=subprocess.STDOUT)
                    try:
                        fin = time.monotonic() + 100
                        while time.monotonic() < fin and proceso.poll() is None:
                            if self._http(puerto, "/login") == 200:
                                break
                            time.sleep(.2)
                        salida.seek(0)
                        self.assertEqual(self._http(puerto, "/login"), 200, salida.read().decode("utf-8", "replace"))
                        self.assertEqual(self._http(puerto, "/login", host="siged.test"), 400)
                        self.assertEqual(self._http(puerto, "/mensajeria"), 303)
                        self.assertEqual(self._http(puerto, "/mensajeria/api/v1/cuota"), 401)
                        if intento == 0:
                            duplicado = subprocess.run(comando, cwd=temporal, env=env, stdin=subprocess.DEVNULL,
                                                       capture_output=True, text=True, timeout=30, check=False)
                            self.assertNotEqual(duplicado.returncode, 0)
                            self.assertEqual(self._http(puerto, "/login"), 200)
                    finally:
                        if proceso.poll() is None:
                            parada_siged.solicitar(arranque.ambito_parada(puerto))
                            proceso.wait(timeout=25)
                    self.assertEqual(proceso.returncode, 0)
            with closing(sqlite3.connect(Path(temporal) / "gestor.db")) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM documentos").fetchone()[0], 0)

    @staticmethod
    def _http(puerto, ruta, host=None):
        conexion = HTTPConnection(arranque.HOST, puerto, timeout=1)
        try:
            conexion.request("GET", ruta, headers={"Host": host} if host else {})
            return conexion.getresponse().status
        except OSError:
            return None
        finally:
            conexion.close()
