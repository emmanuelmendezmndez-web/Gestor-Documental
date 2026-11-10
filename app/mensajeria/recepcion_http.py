"""Recepción ASGI acotada y multipart de una sola parte, sin spool."""

import asyncio
import re
import time

from anyio import from_thread
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.exceptions import HTTPException

from app.mensajeria.motor import ErrorMotor

CORTE = 64 * 1024
MAX_MULTIPART = 21 * 1024 * 1024
MAX_JSON = 4096
CARGA_SEGUNDOS = 180
CARGA_INACTIVA = 15


class Entrada:
    def __init__(self, request, maximo, total, inactividad):
        self._recibir = request.receive
        self._maximo = maximo
        self._recibidos = 0
        ahora = time.monotonic()
        self._fin = ahora + total
        self._inactividad = inactividad
        self.terminada = False

    async def bloque(self):
        fin = min(self._fin, time.monotonic() + self._inactividad)
        while not self.terminada:
            plazo = fin - time.monotonic()
            if plazo <= 0:
                raise ErrorMotor("plazo_http_agotado")
            try:
                async with asyncio.timeout(plazo):
                    mensaje = await self._recibir()
            except TimeoutError:
                raise ErrorMotor("plazo_http_agotado") from None
            except HTTPException as error:
                if error.status_code == 413:
                    raise ErrorMotor("cuerpo_demasiado_grande") from None
                raise
            if mensaje["type"] != "http.request":
                raise ErrorMotor("carga_interrumpida")
            self.terminada = not mensaje.get("more_body", False)
            datos = mensaje.get("body", b"")
            self._recibidos += len(datos)
            if self._recibidos > self._maximo:
                raise ErrorMotor("cuerpo_demasiado_grande")
            if datos:
                return datos
        return b""


class ArchivoMultipart:
    """Lector síncrono para adjuntos.preparar, alimentado por ASGI en el event loop."""

    def __init__(self, entrada, contenido):
        tipo, opciones = parse_options_header(contenido)
        limite = opciones.get(b"boundary", b"")
        if tipo != b"multipart/form-data" or not re.fullmatch(rb"[0-9A-Za-z'()+_,./:=?\-]{1,70}", limite):
            raise ErrorMotor("multipart_invalido")
        self._entrada = entrada
        self._parte = False
        self._fin = False
        self._nombre = None
        self._cabeceras = {}
        self._campo = bytearray()
        self._valor = bytearray()
        self._archivo = bytearray()
        self._bloque = b""
        self._pos = 0
        self._parser = MultipartParser(
            limite,
            {"on_part_begin": self._iniciar, "on_header_field": self._campo_dato,
             "on_header_value": self._valor_dato, "on_header_end": self._cabecera,
             "on_headers_finished": self._nombre_archivo, "on_part_data": self._datos, "on_end": self._terminar},
            max_header_count=4, max_header_size=2048,
        )

    def _iniciar(self):
        if self._parte:
            raise ErrorMotor("multipart_invalido")
        self._parte = True

    def _campo_dato(self, datos, inicio, fin):
        self._campo.extend(datos[inicio:fin])

    def _valor_dato(self, datos, inicio, fin):
        self._valor.extend(datos[inicio:fin])

    def _cabecera(self):
        campo = bytes(self._campo).lower()
        if campo in self._cabeceras or campo not in {b"content-disposition", b"content-type"}:
            raise ErrorMotor("multipart_invalido")
        self._cabeceras[campo] = bytes(self._valor)
        self._campo.clear()
        self._valor.clear()

    def _nombre_archivo(self):
        tipo, opciones = parse_options_header(self._cabeceras.get(b"content-disposition", b""))
        if tipo != b"form-data" or opciones.get(b"name") != b"archivo" or b"filename" not in opciones:
            raise ErrorMotor("multipart_invalido")
        self._nombre = opciones[b"filename"].decode("utf-8", errors="strict")

    def _datos(self, datos, inicio, fin):
        self._archivo.extend(datos[inicio:fin])

    def _terminar(self):
        self._fin = True

    def _avanzar(self):
        if self._pos >= len(self._bloque):
            self._bloque = from_thread.run(self._entrada.bloque)
            self._pos = 0
        try:
            if self._bloque:
                fin = self._pos + CORTE
                self._parser.write(self._bloque[self._pos:fin])
                self._pos = fin
                return True
            self._parser.finalize()
        except (FormParserError, UnicodeError):
            raise ErrorMotor("multipart_invalido") from None
        if not self._fin or self._nombre is None:
            raise ErrorMotor("multipart_incompleto")
        return False

    def nombre(self):
        while self._nombre is None:
            self._avanzar()
        return self._nombre

    def read(self, cantidad):
        while not self._archivo and self._avanzar():
            pass
        salida = bytes(self._archivo[:cantidad])
        del self._archivo[:cantidad]
        return salida
