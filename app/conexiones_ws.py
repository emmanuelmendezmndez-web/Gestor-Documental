"""Cupos de WebSocket y consultas agrupadas, sin lógica de dominio."""

import asyncio
import logging
from contextlib import contextmanager

from app.diagnostico_io import detalle_error

logger = logging.getLogger("gestor.websocket")


class CupoNoDisponible(RuntimeError):
    pass


class FuenteNoDisponible(RuntimeError):
    pass


class AdministradorConexiones:
    def __init__(self, consultar, *, por_usuario=4, total=32, intervalo=2):
        self._consultar = consultar
        self._por_usuario = por_usuario
        self._total = total
        self._intervalo = intervalo
        self._activas = {}
        self._pendientes = {}
        self._tarea = None

    @contextmanager
    def reservar(self):
        if len(self._activas) >= self._total:
            raise CupoNoDisponible
        puesto = object()
        self._activas[puesto] = None
        try:
            yield puesto
        finally:
            del self._activas[puesto]

    def asociar(self, puesto, usuario):
        if sum(u == usuario for u in self._activas.values()) >= self._por_usuario:
            raise CupoNoDisponible
        self._activas[puesto] = usuario

    async def consultar(self, puesto, solicitud):
        futuro = asyncio.get_running_loop().create_future()
        self._pendientes[puesto] = (solicitud, futuro)
        if self._tarea is None:
            self._tarea = asyncio.create_task(self._despachar())
        try:
            return await futuro
        finally:
            self._pendientes.pop(puesto, None)

    async def _despachar(self):
        try:
            while self._pendientes:
                await asyncio.sleep(self._intervalo)
                lote = tuple(self._pendientes.values())
                self._pendientes.clear()
                if not lote:
                    continue
                solicitudes, futuros = zip(*lote, strict=True)
                try:
                    resultados = await asyncio.to_thread(self._consultar, solicitudes)
                    if len(resultados) != len(futuros):
                        raise FuenteNoDisponible
                except Exception as error:  # noqa: BLE001 - No expone detalles privados de la fuente.
                    logger.warning("Fuente de señales no disponible (%s)", detalle_error(error))
                    for futuro in futuros:
                        if not futuro.done():
                            futuro.set_exception(FuenteNoDisponible())
                else:
                    for futuro, resultado in zip(futuros, resultados, strict=True):
                        if not futuro.done():
                            futuro.set_result(resultado)
        finally:
            self._tarea = None
