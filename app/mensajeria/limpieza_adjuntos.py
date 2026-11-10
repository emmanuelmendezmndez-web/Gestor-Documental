"""Limpieza recuperable limitada a objetos físicos reservados por Mensajería."""

import asyncio
import errno
import logging
import os
import re
import sqlite3
from contextlib import contextmanager

from app.mensajeria import disco, motor
from app.mensajeria.adjuntos import _ruta, _seguridad
from app.mensajeria.identidad_documental import instalacion
from app.mensajeria.reconciliacion import _vinculo

logger = logging.getLogger("gestor.mensajeria")
_LOTE = 16
_REINTENTO = 60


@contextmanager
def _mantenimiento():
    with motor._bases() as (principal, db, _):
        vinculo = _vinculo(db)
        if vinculo is None or vinculo["instalacion_id"] != instalacion(principal):
            raise motor.ErrorMotor("identidad_no_reconciliada")
        ahora, _ = motor._reloj(db)
        yield db, ahora


def _aplazar(db, token, ahora, codigo):
    db.execute(
        "UPDATE archivos_externos SET reintento_utc=?, error=? WHERE token=?",
        (ahora + _REINTENTO, codigo, token),
    )
    return False


def _limpiar(db, zona, fila, ahora):
    token = fila["token"]
    mensaje = db.execute(
        "SELECT id, vence_utc, remitente_ref, destinatario_ref FROM mensajes WHERE archivo_token=?", (token,),
    ).fetchone()
    confirmado = fila["estado"] == "confirmado"
    if mensaje is not None and (
        not confirmado or tuple(mensaje) != (
            fila["mensaje_id"], fila["vence_utc"], fila["remitente"], fila["destinatario"],
        ) or mensaje["vence_utc"] > ahora
    ):
        return _aplazar(db, token, ahora, "referencia_incompatible")
    if db.execute("SELECT 1 FROM limpieza WHERE archivo_token=?", (token,)).fetchone():
        return _aplazar(db, token, ahora, "referencia_incompatible")
    if fila["error"] == "colision" and fila["estado"] == "recibiendo" and fila["identidad"] is None:
        # El destino nunca fue nuestro. Libera la reserva y conserva el objeto
        # para que el inventario de huérfanos lo señale sin borrarlo.
        db.execute("DELETE FROM archivos_externos WHERE token=?", (token,))
        return True
    try:
        disco.borrar(
            _ruta(zona, token), fila["identidad"],
            intencion_vacia=fila["estado"] == "recibiendo" and fila["identidad"] is None,
        )
    except (OSError, motor.ErrorMotor):
        return _aplazar(db, token, ahora, "borrado_no_disponible")
    # Si termina el proceso entre el borrado y el COMMIT, la misma fila
    # sigue siendo elegible. La ausencia del objeto completa el reintento.
    if confirmado:
        db.execute(
            "UPDATE archivos_externos SET estado='retirado', identidad=NULL, tamano=NULL, "
            "reintento_utc=0, error=NULL WHERE token=?", (token,),
        )
    else:
        db.execute("DELETE FROM archivos_externos WHERE token=?", (token,))
    return True


def abortar(zona, token):
    """Libera una reserva fallida si sus bytes siguen sin publicarse."""
    try:
        with _mantenimiento() as (db, ahora):
            db.execute(
                "UPDATE archivos_externos SET limite_utc=? WHERE token=? AND estado='recibiendo'",
                (ahora, token),
            )
            fila = db.execute(
                "SELECT * FROM archivos_externos WHERE token=? AND estado='recibiendo'", (token,),
            ).fetchone()
            if fila is not None:
                _limpiar(db, zona, fila, ahora)
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        # El vencimiento persistido permite reintentar después de restaurar o reiniciar.
        logger.warning("Mensajería: liberación de reserva aplazada")


@contextmanager
def _turno(zona):
    import msvcrt

    archivo, _ = disco.abrir(zona.parent / ".limpieza.lock", trabajador=True)
    with archivo:
        try:
            msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno != errno.EACCES:
                raise
            yield False
        else:
            # El cierre libera también el rango después de una excepción.
            yield True


def limpiar():
    """Completa un lote, con un solo trabajador activo por almacenamiento privado."""
    with _seguridad(), disco.zona() as zona:
        # Verificar primero el vínculo y las ACL. La apertura del marcador puede crearlo.
        with _mantenimiento():
            pass
        with _turno(zona) as turno:
            if not turno:
                return {"retirados": 0, "aplazados": 0, "sin_evidencia": 0}
            with _mantenimiento() as (db, ahora):
                filas = db.execute(
                    """SELECT * FROM archivos_externos WHERE reintento_utc<=?
                       AND ((estado IN ('recibiendo','preparado') AND limite_utc<=?)
                            OR (estado='recibiendo' AND inactivo_utc<=?)
                            OR (estado='confirmado' AND vence_utc<=?))
                       ORDER BY reintento_utc, coalesce(vence_utc,limite_utc), token LIMIT ?""",
                    (ahora, ahora, ahora, ahora, _LOTE),
                ).fetchall()
                retirados = sum(_limpiar(db, zona, fila, ahora) for fila in filas)
                desconocidos = _sin_evidencia(db, zona)
                return {"retirados": retirados, "aplazados": len(filas) - retirados,
                        "sin_evidencia": desconocidos}


def _sin_evidencia(db, zona):
    """Detecta elementos ajenos al protocolo sin adoptar ni borrar su contenido."""
    sin_evidencia = 0
    with os.scandir(zona) as entradas:
        for entrada in entradas:
            if not re.fullmatch(r"[a-f0-9]{32}\.bin", entrada.name) or not db.execute(
                "SELECT 1 FROM archivos_externos WHERE token=? AND estado!='retirado' "
                "AND coalesce(error,'')!='colision'", (entrada.name[:-4],),
            ).fetchone():
                sin_evidencia += 1
    return sin_evidencia


async def vigilar(detener):
    """Una revisión inicial y una por minuto mientras exista el servidor."""
    while not detener.is_set():
        try:
            resultado = await asyncio.to_thread(limpiar)
            if resultado["aplazados"] or resultado["sin_evidencia"]:
                logger.warning("Mensajería: revisión con objetos aplazados o sin evidencia")
        except motor.ErrorMotor:
            logger.warning("Mensajería: revisión de adjuntos aplazada")
        try:
            await asyncio.wait_for(detener.wait(), timeout=60)
        except TimeoutError:
            pass
