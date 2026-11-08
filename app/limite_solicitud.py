"""Límite ASGI del cuerpo, antes del análisis de formularios y archivos."""
import os

from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse

from app.archivos import TAMANO_MAXIMO

LIMITE_PREDETERMINADO = 21 * 1024 * 1024


def limite_configurado():
    valor = os.environ.get('GESTOR_MAX_CUERPO_BYTES', str(LIMITE_PREDETERMINADO)).strip()
    if not valor.isascii() or not valor.isdecimal() or len(valor) > 12:
        raise ValueError('GESTOR_MAX_CUERPO_BYTES debe ser un número entero de bytes')
    limite = int(valor)
    if limite <= TAMANO_MAXIMO:
        raise ValueError('GESTOR_MAX_CUERPO_BYTES debe superar el límite por archivo de 20 MiB')
    return limite


class LimitarCuerpo:
    def __init__(self, app, limite=None):
        self.app = app
        self.limite = limite_configurado() if limite is None else limite

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        longitudes = [v.strip() for k, v in scope.get('headers', ()) if k.lower() == b'content-length']
        if longitudes:
            if len(longitudes) != 1 or not longitudes[0].isdigit():
                await PlainTextResponse('Content-Length inválido', status_code=400)(scope, receive, send)
                return
            valor = longitudes[0].lstrip(b'0') or b'0'
            if len(valor) > len(str(self.limite)) or int(valor) > self.limite:
                await PlainTextResponse('La solicitud supera el tamaño permitido.', status_code=413)(scope, receive, send)
                return

        recibidos = 0
        respuesta_iniciada = False

        async def recibir_limitado():
            nonlocal recibidos
            mensaje = await receive()
            if mensaje['type'] == 'http.request':
                recibidos += len(mensaje.get('body', b''))
                if recibidos > self.limite:
                    raise HTTPException(status_code=413, detail='La solicitud supera el tamaño permitido.')
            return mensaje

        async def enviar_controlado(mensaje):
            nonlocal respuesta_iniciada
            if mensaje['type'] == 'http.response.start':
                respuesta_iniciada = True
            await send(mensaje)

        try:
            await self.app(scope, recibir_limitado, enviar_controlado)
        except HTTPException as exc:
            if exc.status_code != 413 or respuesta_iniciada:
                raise
            await PlainTextResponse('La solicitud supera el tamaño permitido.', status_code=413)(scope, receive, send)
