"""API privada experimental de Mensajería. Se instala explícitamente."""

import asyncio
import json
import logging
from contextlib import ExitStack
from typing import Annotated, Literal

from anyio import CancelScope, CapacityLimiter, WouldBlock
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, StreamingResponse

from app.csrf import validar_csrf
from app.inventario_restauracion import pares_unicos
from app.mensajeria import (
    adjuntos,
    biblioteca,
    consultas,
    motor,
    recepcion_http,
    sesiones_ws,
)
from app.mensajeria.base_datos import LIMITE_ARCHIVO
from app.mensajeria.websocket import _origen_exacto

PREFIJO = "/mensajeria/api/v1"
CHAT = "/conversaciones/{chat}"
MENSAJE = CHAT + "/mensajes/{mensaje}"
PATRON_REF = r"^[0-9a-f]{32}$"
Referencia = Annotated[str, Field(pattern=PATRON_REF)]
Pagina = Annotated[int, Query(ge=1, le=50)]
CursorRef = Annotated[str | None, Query(pattern=PATRON_REF)]
CursorMensaje = Annotated[str | None, Query(pattern=r"^[0-9]{1,12}\.[0-9a-f]{32}$")]
logger = logging.getLogger("gestor.mensajeria")
PRIVADAS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


class _Envio(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    destinatario: Referencia
    clave: Referencia
    texto: Annotated[str, Field(min_length=1, max_length=300)]


class EnvioBiblioteca(_Envio):
    documento: Referencia
    modalidad: Literal["visualizar", "visualizar_y_descargar"]


class ConfirmacionExterna(_Envio):
    nombre: Annotated[str, Field(min_length=1, max_length=200)]
    tamano_bytes: Annotated[int, Field(ge=1, le=LIMITE_ARCHIVO)]


class ArchivoConversacion(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    archivada: bool


class _Privada(JSONResponse):
    def __init__(self, content, headers=None, **kw):
        super().__init__(content, headers={**(headers or {}), **PRIVADAS}, **kw)


class _Rechazo(motor.ErrorMotor):
    def __init__(self, codigo, estado):
        super().__init__(codigo)
        self.estado = estado


def _error(error):
    if isinstance(error, _Rechazo):
        return _Privada({"error": str(error)}, status_code=error.estado)
    codigo = str(error)
    if codigo in {"sesion_no_valida", "usuario_no_disponible"}:
        codigo, estado = "sesion_no_valida" if codigo == "sesion_no_valida" else "no_disponible", (
            401 if codigo == "sesion_no_valida" else 404
        )
    elif codigo in {"mensaje_no_disponible", "conversacion_no_disponible", "adjunto_no_disponible",
                    "documento_no_disponible", "preparacion_no_disponible", "adjunto_no_confirmado"}:
        codigo, estado = "no_disponible", 404
    elif codigo in {"archivo_demasiado_grande", "cuerpo_demasiado_grande"}:
        estado = 413
    elif codigo in {"conflicto_idempotencia", "identidad_no_reconciliada", "generacion_cambio",
                    "adjunto_ya_utilizado", "carga_en_curso"}:
        estado = 409
    elif codigo in {"cuota_agotada", "capacidad_cargas_agotada", "capacidad_adjuntos_agotada"}:
        estado = 429
    elif codigo in {"plazo_http_agotado", "carga_inactiva", "plazo_preparacion_agotado"}:
        estado = 408
    elif codigo == "preparacion_vencida":
        estado = 410
    elif codigo == "espacio_adjuntos_insuficiente":
        estado = 507
    elif codigo in {"formato_no_permitido", "formato_incompatible"}:
        estado = 415
    elif codigo in {"texto_invalido", "referencia_invalida", "nombre_invalido", "archivo_vacio",
                    "autoenvio_no_permitido", "multipart_invalido", "multipart_incompleto", "carga_interrumpida",
                    "adjunto_invalido"}:
        estado = 400
    else:
        # Los mensajes de excepción pueden contener rutas. Solo se registra la clase.
        logger.warning("Operación HTTP de Mensajería indisponible (%s)", type(error).__name__)
        codigo, estado = "servicio_no_disponible", 503
    return _Privada({"error": codigo}, status_code=estado)


def _operar(datos, funcion, *args, lectura, **kw):
    with sesiones_ws.autorizar_http(datos, lectura=lectura) as actor:
        return funcion(actor, *args, **kw)


async def _ejecutar(datos, funcion, *args, lectura=False, **kw):
    return await run_in_threadpool(_operar, datos, funcion, *args, lectura=lectura, **kw)


async def _json(request, esquema):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise _Rechazo("tipo_de_cuerpo_invalido", 415)
    entrada = recepcion_http.Entrada(request, recepcion_http.MAX_JSON, 10, 5)
    datos = bytearray()
    while bloque := await entrada.bloque():
        datos.extend(bloque)
    try:
        return esquema.model_validate(json.loads(datos.decode("utf-8"), object_pairs_hook=pares_unicos))
    except (ValidationError, ValueError, RecursionError):
        raise _Rechazo("solicitud_invalida", 400) from None


def _preparar(actor, destino, clave, lector):
    adjunto = adjuntos.preparar(actor, destino, clave, lector.nombre(), lector)
    return {"clave": clave, "nombre": adjunto.nombre_original, "tamano_bytes": adjunto.tamano_bytes}


def _abrir(pila, actor, chat, mensaje):
    if consultas.tipo_adjunto(actor, chat, mensaje) == "externo":
        return pila.enter_context(adjuntos.abrir_descarga(actor, mensaje, conversacion=chat))
    return pila.enter_context(biblioteca.abrir_descarga(actor, chat, mensaje, informar_estado_sesion=True))


def _credencial(request, origenes, https_only):
    host = request.headers.getlist("host")
    actual = _origen_exacto(f"{request.scope['scheme']}://{host[0]}") if len(host) == 1 else None
    recibido = request.headers.getlist("origin")
    if (actual not in origenes or len(recibido) > 1 or (recibido and _origen_exacto(recibido[0]) != actual)
            or (https_only and actual[0] != "https")):
        raise _Rechazo("origen_no_autorizado", 403)
    datos = sesiones_ws.credencial(request.session)
    if datos is None:
        raise _Rechazo("sesion_no_valida", 401)
    return datos


class _Descarga(StreamingResponse):
    def __init__(self, datos, chat, mensaje, cupos):
        super().__init__(iter(()), headers=PRIVADAS)
        self._datos, self._chat, self._mensaje, self._cupos = datos, chat, mensaje, cupos

    async def __call__(self, scope, receive, send):
        try:
            self._cupos.acquire_nowait()
        except WouldBlock:
            await _error(_Rechazo("capacidad_descargas_agotada", 429))(scope, receive, send)
            return
        pila = ExitStack()
        try:
            try:
                with CancelScope(shield=True):
                    archivo, cabeceras = await _ejecutar(
                        self._datos, lambda actor: _abrir(pila, actor, self._chat, self._mensaje), lectura=True,
                    )
            except sesiones_ws.ERRORES_DATOS as error:
                await _error(error)(scope, receive, send)
                return
            respuesta = StreamingResponse(
                iter(lambda: archivo.read(recepcion_http.CORTE), b""),
                headers={**cabeceras, **PRIVADAS, "Content-Security-Policy": "sandbox; default-src 'none'"},
            )
            async with asyncio.timeout(300):
                await respuesta(scope, receive, send)
        finally:
            self._cupos.release()
            with CancelScope(shield=True):
                await run_in_threadpool(pila.close)


def instalar(app, *, origenes, https_only):
    if getattr(app.state, "mensajeria_http_instalada", False):
        raise ValueError("La API experimental ya está instalada")
    origenes = {_origen_exacto(o) for o in origenes}
    if not origenes or None in origenes or (https_only and any(o[0] != "https" for o in origenes)):
        raise ValueError("Configura orígenes exactos compatibles con HTTPS")
    api = FastAPI(default_response_class=_Privada, openapi_url=None, redirect_slashes=False)
    cargas, descargas = CapacityLimiter(4), CapacityLimiter(8)

    @api.exception_handler(RequestValidationError)
    async def parametros_invalidos(_request, _error):
        return _Privada({"error": "solicitud_invalida"}, status_code=400)

    async def error_de_operacion(_request, error):
        return _error(error)

    api.add_exception_handler(motor.ErrorMotor, error_de_operacion)
    for tipo in sesiones_ws.ERRORES_DATOS:
        api.add_exception_handler(tipo, error_de_operacion)

    async def credencial(request: Request):
        datos = _credencial(request, origenes, https_only)
        if request.method == "POST":
            # Obligatorio antes de tocar multipart. El validador común
            # comprueba el token y Origin/Referer sin llamar a request.form().
            tokens = request.headers.getlist("x-csrf-token")
            if len(tokens) != 1 or not tokens[0] or len(request.headers.getlist("referer")) > 1:
                raise _Rechazo("csrf_invalido", 403)
            from starlette.exceptions import HTTPException
            try:
                await validar_csrf(request)
            except HTTPException:
                raise _Rechazo("csrf_invalido", 403) from None
        return datos

    Sesion = Annotated[sesiones_ws.Credencial, Depends(credencial)]

    @api.get("/destinatarios")
    async def destinatarios(datos: Sesion, despues: CursorRef = None, limite: Pagina = 25):
        return await _ejecutar(datos, consultas.destinatarios, despues, limite, lectura=True)

    @api.get("/conversaciones")
    async def conversaciones(datos: Sesion, archivadas: bool = False,
                             despues: CursorRef = None, limite: Pagina = 25):
        return await _ejecutar(datos, consultas.conversaciones, archivadas, despues, limite, lectura=True)

    @api.get(CHAT + "/mensajes")
    async def mensajes(chat: Referencia, datos: Sesion, antes: CursorMensaje = None, limite: Pagina = 25):
        cursor = None
        if antes:
            instante, identificador = antes.split(".", 1)
            cursor = int(instante), identificador
        return await _ejecutar(datos, consultas.mensajes, chat, cursor, limite, lectura=True)

    @api.get("/cuota")
    async def cuota(datos: Sesion):
        return consultas.con_restantes(await _ejecutar(datos, motor.cuota, lectura=True))

    @api.get("/sincronizacion")
    async def sincronizacion(datos: Sesion, archivadas: bool = False,
                            despues: CursorRef = None, limite: Pagina = 25):
        return await _ejecutar(datos, consultas.sincronizar, archivadas, despues, limite, lectura=True)

    @api.post("/envios/externos/preparar")
    async def preparar(request: Request, datos: Sesion):
        destino = request.headers.getlist("x-siged-destinatario")
        clave = request.headers.getlist("idempotency-key")
        if len(destino) != 1 or len(clave) != 1:
            raise _Rechazo("solicitud_invalida", 400)
        motor._referencia(destino[0])
        motor._referencia(clave[0])
        try:
            cargas.acquire_nowait()
        except WouldBlock:
            raise _Rechazo("capacidad_cargas_agotada", 429) from None
        try:
            entrada = recepcion_http.Entrada(request, recepcion_http.MAX_MULTIPART,
                                             recepcion_http.CARGA_SEGUNDOS, recepcion_http.CARGA_INACTIVA)
            lector = recepcion_http.ArchivoMultipart(entrada, request.headers.get("content-type", ""))
            return await _ejecutar(datos, _preparar, destino[0], clave[0], lector)
        finally:
            cargas.release()

    @api.post("/envios/externos/confirmar")
    async def confirmar(request: Request, datos: Sesion):
        envio = await _json(request, ConfirmacionExterna)
        mensaje = await _ejecutar(datos, adjuntos.confirmar_preparado, envio.destinatario, envio.texto,
                                  envio.clave, envio.nombre, envio.tamano_bytes)
        return {"mensaje": mensaje}

    @api.post("/envios/biblioteca")
    async def compartir(request: Request, datos: Sesion):
        envio = await _json(request, EnvioBiblioteca)
        adjunto = motor.Adjunto("documento", envio.documento, modalidad=envio.modalidad)
        return {"mensaje": await _ejecutar(datos, motor.enviar, envio.destinatario, envio.texto, envio.clave, adjunto)}

    @api.get(MENSAJE + "/adjunto")
    async def tarjeta(chat: Referencia, mensaje: Referencia, datos: Sesion):
        return await _ejecutar(datos, consultas.tarjeta, chat, mensaje, lectura=True)

    @api.get(MENSAJE + "/adjunto/descarga", response_class=StreamingResponse)
    async def descarga(chat: Referencia, mensaje: Referencia, datos: Sesion):
        return _Descarga(datos, chat, mensaje, descargas)

    @api.get(MENSAJE + "/adjunto/vista")
    async def vista(chat: Referencia, mensaje: Referencia, datos: Sesion):
        tarjeta_ = await _ejecutar(datos, consultas.tarjeta, chat, mensaje, lectura=True)
        if not tarjeta_.get("visualizacion_pendiente"):
            raise _Rechazo("no_disponible", 404)
        raise _Rechazo("visualizacion_no_habilitada", 501)

    @api.post(MENSAJE + "/lectura")
    async def lectura(chat: Referencia, mensaje: Referencia, datos: Sesion):
        await _ejecutar(datos, motor.marcar_leido, mensaje, conversacion_id=chat)
        return {"leido": True}

    @api.post(CHAT + "/archivo")
    async def archivar(request: Request, chat: Referencia, datos: Sesion):
        entrada = await _json(request, ArchivoConversacion)
        await _ejecutar(datos, motor.archivar, chat, archivada=entrada.archivada)
        return {"archivada": entrada.archivada}

    app.mount(PREFIJO, api, name="mensajeria_api_experimental")
    app.state.mensajeria_http_instalada = True
    app.state.sesiones_ws_mensajeria = True
