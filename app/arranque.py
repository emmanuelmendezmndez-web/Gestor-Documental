"""Lanzador habitual de SIGED. Una aplicación ASGI y un puerto local."""

import argparse
import os
import socket
import sqlite3
import time
import webbrowser
from contextlib import ExitStack
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from importlib.util import find_spec
from pathlib import Path
from secrets import token_hex
from threading import Event, Thread

import uvicorn
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import beta_siged, parada_siged, proxy_siged
from app.diagnostico_io import detalle_error

RAIZ = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PUERTO = 8000
ACTIVACION = "SIGED_MENSAJERIA_OPERATIVA"


def ambito_parada(puerto):
    return RAIZ / str(puerto)


def _preparar():
    from app.coordinacion import BloqueoNoDisponible
    from app.limite_solicitud import limite_configurado
    from app.mensajeria.reconciliacion import _bases, _vinculo_vigente

    if find_spec("websockets") is None:
        raise proxy_siged.ProxyNoDisponible("Falta el grupo de dependencias mensajeria-ws en .venv.")
    if not os.environ.get("GESTOR_MENSAJERIA_DIR", "").strip():
        raise proxy_siged.ProxyNoDisponible("Falta configurar el almacén privado de Mensajería.")
    os.environ["SIGED_MAX_CUERPO_BYTES"] = str(limite_configurado())
    proxy = proxy_siged.preparar(RAIZ)
    try:
        # Reserva de escritura en ambas bases. El sondeo no cambia filas ni migra esquemas.
        with _bases() as (principal, privada, generacion):
            if not _vinculo_vigente(principal, privada, generacion):
                raise proxy_siged.ProxyNoDisponible("La generación de Mensajería requiere reconciliación.")
    except (BloqueoNoDisponible, OSError, sqlite3.Error, ValueError):
        raise proxy_siged.ProxyNoDisponible(
            "El almacén privado no está disponible. Revise ACL, bloqueo, esquema y reconciliación.",
        ) from None
    return proxy


def _estado(host, ruta, *, seguro, puerto=PUERTO, cabecera="Set-Cookie"):
    conexion = HTTPSConnection(host, timeout=3) if seguro else HTTPConnection(host, puerto, timeout=3)
    try:
        conexion.request("GET", ruta)
        respuesta = conexion.getresponse()
        return respuesta.status, respuesta.getheader(cabecera, "")
    finally:
        conexion.close()


def _rechaza_ws(host):
    from websockets.exceptions import InvalidStatus, WebSocketException
    from websockets.sync.client import connect

    from app.mensajeria.websocket import RUTA

    try:
        with connect(f"wss://{host}{RUTA}", origin=f"https://{host}", proxy=None, open_timeout=4):
            return False
    except InvalidStatus as error:
        return error.response.status_code == 403
    except WebSocketException:
        return False


def _disponible(proxy, ruta, puerto, host=HOST, beta=False):
    if not proxy:
        if _estado(host, "/login", seguro=False, puerto=puerto)[0] != 200:
            return False
        return not beta or _estado(host, "/mensajeria/api/v1/cuota", seguro=False, puerto=puerto)[0] == 401
    marca = ruta.rsplit("/", 1)[-1]
    if _estado(proxy.host, ruta, seguro=True, cabecera="X-SIGED-Arranque") != (204, marca):
        return False
    estado, cookie = _estado(proxy.host, "/login", seguro=True)
    atributos = {a.strip().lower() for a in cookie.split(";")[1:]}
    if estado != 200 or not cookie.startswith("gestor_sesion=") or not {"secure", "httponly", "samesite=lax"} <= atributos:
        return False
    api, _ = _estado(proxy.host, "/mensajeria/api/v1/cuota", seguro=True)
    return api == 401 and _rechaza_ws(proxy.host)


def _vigilar(servidor, detener, fin, resultado, proxy, proceso, ruta, navegador, puerto, host=HOST, beta=False):
    plazo = time.monotonic() + 45
    listo = False
    while not fin.wait(.25):
        if detener():
            servidor.should_exit = True
            return
        if proceso is not None and proceso.poll() is not None:
            print("Caddy se detuvo. SIGED cerrará el servidor local.", flush=True)
            servidor.should_exit = True
            resultado["error"] = True
            return
        if listo:
            continue
        if time.monotonic() >= plazo:
            print("SIGED no superó la comprobación de disponibilidad. Revise HTTPS o vuelva a iniciar en modo local.",
                  flush=True)
            servidor.should_exit = True
            resultado["error"] = True
            return
        if not servidor.started:
            continue
        try:
            listo = _disponible(proxy, ruta, puerto, host, beta)
        except (OSError, HTTPException, ValueError):
            continue
        if listo:
            resultado["listo"] = True
            url = f"https://{proxy.host}" if proxy else f"http://{host}:{puerto}"
            if beta:
                modo = "BETA local con Mensajería" if host == HOST else "BETA LAN con Mensajería"
            else:
                modo = "Mensajería integrada" if proxy else "modo local, Mensajería deshabilitada"
            print(f"SIGED disponible en {url} ({modo}). Para detenerlo, use Ctrl+C o el acceso Detener SIGED.",
                  flush=True)
            if navegador:
                try:
                    if webbrowser.open(url):
                        continue
                except (OSError, webbrowser.Error):
                    pass
                print("El navegador no se abrió automáticamente. Use la dirección indicada.", flush=True)


def _servir(socket_local, detener, navegador, puerto, host=HOST, *, beta=False):
    from app.coordinacion import BloqueoDatos, BloqueoNoDisponible

    proxy = proceso = None
    proteccion = ExitStack()
    try:
        if not beta and os.environ.get(ACTIVACION) == "1":
            try:
                # Mantiene la generación fija hasta que app.main adquiere su bloqueo de vida.
                proteccion.enter_context(BloqueoDatos(exclusivo=False))
                candidato = _preparar()
                proceso = proxy_siged.iniciar(candidato)
                proxy_siged.verificar_tls(candidato.host, proceso)
                proxy = candidato
            except (BloqueoNoDisponible, OSError, proxy_siged.ProxyNoDisponible, ValueError) as error:
                motivo = str(error) if isinstance(error, proxy_siged.ProxyNoDisponible) else "Configuración no válida."
                print(f"Mensajería deshabilitada. {motivo}", flush=True)
                fallido, proceso = proceso, None
                proxy_siged.detener(fallido)
                proteccion.close()
        if detener():
            return 0
        if not proxy and os.environ.get("GESTOR_HTTPS_ONLY", "").strip().lower() in {"1", "true", "yes", "si"}:
            print("SIGED exige HTTPS por configuración. Se conservó esa política y no se inició HTTP local.", flush=True)
            return 1

        os.environ["GESTOR_HTTPS_ONLY"] = "1" if proxy else "0"
        if beta:
            try:
                if find_spec("websockets") is None:
                    raise ValueError("Falta la dependencia websockets en .venv.")
                proteccion.enter_context(BloqueoDatos(exclusivo=False))
                beta_siged.preparar()
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
                motivo = detalle_error(error) if isinstance(error, OSError) else str(error)
                print(f"No se pudo preparar Mensajería BETA: {motivo}", flush=True)
                return 1
        elif not proxy:
            os.environ.pop("GESTOR_MENSAJERIA_DIR", None)
        from app.main import app

        proteccion.close()
        hosts = [proxy.host] if proxy else ([HOST, "localhost"] if host == HOST else [host])
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts, www_redirect=False)
        opciones = {"ws": "none"}
        ruta = None
        if proxy or beta:
            from app.mensajeria.servidor_ws import montar, transporte

            origenes = [f"https://{proxy.host}"] if proxy else [f"http://{nombre}:{puerto}" for nombre in hosts]
            montar(app, origenes, https_only=bool(proxy))
            opciones = transporte()
        if proxy:
            from starlette.responses import Response

            marca = token_hex(16)
            ruta = "/_siged_arranque/" + marca

            @app.get(ruta, include_in_schema=False)
            def confirmar_arranque():
                return Response(status_code=204, headers={"Cache-Control": "no-store", "X-SIGED-Arranque": marca})

        servidor = uvicorn.Server(uvicorn.Config(
            app, host=host, port=puerto, workers=1, proxy_headers=bool(proxy),
            forwarded_allow_ips=HOST if proxy else "", log_level="warning", access_log=False,
            timeout_graceful_shutdown=12, **opciones,
        ))
        fin = Event()
        resultado = {"listo": False, "error": False}
        vigilancia = Thread(target=_vigilar, daemon=True,
                            args=(servidor, detener, fin, resultado, proxy, proceso, ruta, navegador, puerto, host, beta))
        vigilancia.start()
        try:
            servidor.run(sockets=[socket_local])
        finally:
            fin.set()
            vigilancia.join(timeout=15)
        return int(resultado["error"] or (not resultado["listo"] and not detener()))
    finally:
        proteccion.close()
        proxy_siged.detener(proceso)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detener", action="store_true")
    parser.add_argument("--sin-navegador", action="store_true")
    modos = parser.add_mutually_exclusive_group()
    modos.add_argument("--beta-local", action="store_true")
    modos.add_argument("--beta-lan", action="store_true")
    parser.add_argument("--ip-lan")
    parser.add_argument("--puerto-local", type=int, default=PUERTO, help="Puerto alternativo para una beta con datos separados")
    args = parser.parse_args()
    if args.detener:
        return 0 if parada_siged.solicitar(ambito_parada(args.puerto_local)) else 3
    if not 1 <= args.puerto_local <= 65535:
        parser.error("El puerto debe estar entre 1 y 65535.")
    if args.ip_lan and not args.beta_lan:
        parser.error("--ip-lan requiere --beta-lan.")
    beta = args.beta_local or args.beta_lan or os.environ.get(ACTIVACION) != "1"
    host = HOST
    if args.beta_lan:
        try:
            if os.environ.get("GESTOR_HTTPS_ONLY", "").strip().lower() in {"1", "true", "yes", "si"}:
                parser.error("La beta LAN usa HTTP. La configuración actual exige HTTPS.")
            print("BETA LAN: HTTP sin cifrar. Use una red controlada y las cuentas y documentos existentes de SIGED.",
                  flush=True)
            host = beta_siged.elegir_ip(args.ip_lan)
        except (EOFError, OSError, ValueError) as error:
            parser.error(str(error))
    if args.puerto_local != PUERTO:
        from app.configuracion import DATA_DIR

        if DATA_DIR == RAIZ or not beta:
            parser.error("El puerto alternativo requiere un modo beta y un directorio de laboratorio separado.")
    with socket.socket() as socket_local:
        socket_local.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            socket_local.bind((host, args.puerto_local))
        except OSError:
            print(f"SIGED no puede reservar {host}:{args.puerto_local}. Revise si ya se está ejecutando o si el puerto está ocupado.",
                  flush=True)
            return 1
        try:
            with parada_siged.escuchar(ambito_parada(args.puerto_local)) as detener:
                return _servir(socket_local, detener, not args.sin_navegador, args.puerto_local, host, beta=beta)
        except FileExistsError:
            print("El lanzador de este proyecto ya está en ejecución.", flush=True)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
