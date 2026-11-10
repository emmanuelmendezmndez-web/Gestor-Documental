"""Canal experimental de señales. Solo se instala por autorización explícita."""

import asyncio
import json
from contextlib import suppress
from functools import partial
from urllib.parse import urlsplit

from starlette.websockets import WebSocketDisconnect

from app.conexiones_ws import (
    AdministradorConexiones,
    CupoNoDisponible,
    FuenteNoDisponible,
)
from app.csrf import _origen
from app.inventario_restauracion import pares_unicos
from app.mensajeria import sesiones_ws

MAX_TRAMA = 1024
PLAZO_CONSULTA = 12
PLAZO_ENVIO = 2
RUTA = "/mensajeria/ws"


def _origen_exacto(valor):
    try:
        if not valor or any(ord(c) <= 32 or ord(c) == 127 for c in valor) or any(c in valor for c in "?#\\"):
            return None
        url = urlsplit(valor)
        if url.path or url.query or url.fragment or "*" in url.netloc:
            return None
        return _origen(valor)
    except ValueError:
        return None


def _origen_permitido(socket, origenes, https_only):
    recibido = socket.headers.getlist("origin")
    host = socket.headers.getlist("host")
    esquema = {"ws": "http", "wss": "https"}.get(socket.scope["scheme"])
    if len(recibido) != 1 or len(host) != 1 or not esquema or (https_only and esquema != "https"):
        return False
    origen = _origen_exacto(recibido[0])
    return origen in origenes and origen == _origen_exacto(f"{esquema}://{host[0]}")


class TramaInvalida(ValueError):
    def __init__(self, codigo=1008):
        self.codigo = codigo


def _texto(trama):
    if trama["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(trama.get("code", 1000))
    texto = trama.get("text")
    binario = trama.get("bytes")
    if (texto is not None and len(texto.encode("utf-8")) > MAX_TRAMA
            or binario is not None and len(binario) > MAX_TRAMA):
        raise TramaInvalida(1009)
    if texto is None:
        raise TramaInvalida()
    return texto


def _sincronizacion(trama):
    try:
        datos = json.loads(_texto(trama), object_pairs_hook=pares_unicos)
    except (json.JSONDecodeError, RecursionError, UnicodeError) as error:
        raise TramaInvalida() from error
    except ValueError as error:
        if isinstance(error, TramaInvalida):
            raise
        raise TramaInvalida() from error
    if (not isinstance(datos, dict) or set(datos) != {"tipo", "cursor"}
            or datos["tipo"] != "sincronizar"
            or (datos["cursor"] is not None and not isinstance(datos["cursor"], str))):
        raise TramaInvalida()
    return datos["cursor"]


async def _cerrar(socket, codigo):
    with suppress(OSError, RuntimeError, TimeoutError, WebSocketDisconnect):
        await asyncio.wait_for(socket.close(code=codigo), 1)


async def _enviar(socket, lote):
    async with asyncio.timeout(PLAZO_ENVIO):
        for evento in lote:
            await socket.send_json(evento)


async def _transmitir(socket, admin, puesto, datos, identidad):
    await _enviar(socket, ({"tipo": "conexion_lista"},))
    cursor = _sincronizacion(await asyncio.wait_for(socket.receive(), 5))
    inicial = True
    lectura = asyncio.create_task(socket.receive())
    consulta = None
    try:
        while True:
            solicitud = sesiones_ws.Solicitud(datos, identidad, inicial, cursor)
            consulta = asyncio.create_task(admin.consultar(puesto, solicitud))
            listas, _ = await asyncio.wait(
                (lectura, consulta), timeout=PLAZO_CONSULTA, return_when=asyncio.FIRST_COMPLETED,
            )
            if lectura in listas:
                _texto(lectura.result())
                # El cliente solo puede enviar su cursor inicial.
                raise TramaInvalida()
            if consulta not in listas:
                raise TimeoutError
            lote = consulta.result()
            if lote is None:
                await _cerrar(socket, 1008)
                return
            await _enviar(socket, lote)
            if lote:
                cursor = lote[-1]["cursor"]
            inicial = False
    finally:
        tareas = (lectura,) if consulta is None else (lectura, consulta)
        for tarea in tareas:
            tarea.cancel()
        await asyncio.gather(*tareas, return_exceptions=True)


def instalar(app, *, origenes, secreto, https_only, intervalo=2):
    """Montaje exclusivo de la aplicación experimental, ausente en app.main."""
    if getattr(app.state, "sesiones_ws_mensajeria", False):
        raise ValueError("El canal experimental ya está instalado")
    permitidos = {_origen_exacto(o) for o in origenes}
    if (not permitidos or None in permitidos or not secreto
            or (https_only and any(o[0] != "https" for o in permitidos))):
        raise ValueError("Configura orígenes exactos compatibles con el modo HTTPS")
    fuente = partial(sesiones_ws.consultar_lote, secreto=secreto.encode("utf-8"))
    admin = AdministradorConexiones(fuente, intervalo=intervalo)

    async def conectar(socket):
        if socket.scope.get("query_string") or not _origen_permitido(socket, permitidos, https_only):
            await _cerrar(socket, 1008)
            return
        datos = sesiones_ws.credencial(socket.scope.get("session", {}))
        if datos is None:
            await _cerrar(socket, 1008)
            return
        try:
            with admin.reservar() as puesto:
                identidad = await asyncio.wait_for(
                    admin.consultar(puesto, sesiones_ws.Solicitud(datos)), PLAZO_CONSULTA,
                )
                if identidad is None:
                    await _cerrar(socket, 1008)
                    return
                admin.asociar(puesto, identidad.usuario_ref)
                await asyncio.wait_for(socket.accept(), PLAZO_ENVIO)
                await _transmitir(socket, admin, puesto, datos, identidad)
        except TramaInvalida as error:
            await _cerrar(socket, error.codigo)
        except (CupoNoDisponible, FuenteNoDisponible, TimeoutError):
            await _cerrar(socket, 1013)
        except (OSError, WebSocketDisconnect, asyncio.CancelledError):
            # El transporte puede cancelar la sesión antes de entregar
            # websocket.disconnect. Los cupos y tareas ya se liberaron.
            pass

    # Starlette monta el WebSocket sin ejecutar dependencias CSRF de tipo HTTP.
    app.router.add_websocket_route(RUTA, conectar)
    app.state.sesiones_ws_mensajeria = True
    return admin
