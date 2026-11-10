"""Preparación, confirmación y lectura interna de archivos externos privados."""

import hashlib
import json
import os
import shutil
import sqlite3
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from urllib.parse import quote
from uuid import uuid4

from app.mensajeria import disco, formatos, motor
from app.mensajeria.base_datos import LIMITE_ARCHIVO


@dataclass(frozen=True)
class _Limites:
    simultaneas: int
    sin_confirmar: int
    capacidad: int
    archivos: int
    libre: int
    preparacion: int
    inactividad: int


def _config(nombre, valor, maximo):
    texto = os.environ.get("GESTOR_MENSAJERIA_" + nombre, str(valor)).strip()
    if not texto.isascii() or not texto.isdecimal() or len(texto) > 14 or not 1 <= int(texto) <= maximo:
        raise motor.ErrorMotor("configuracion_adjuntos_invalida")
    return int(texto)


def _limites():
    return _Limites(
        _config("CARGAS_SIMULTANEAS", 4, 32),
        _config("CARGAS_SIN_CONFIRMAR", 20, 100),
        _config("ARCHIVOS_MAX_BYTES", 2 * 1024**3, 1024**4),
        _config("ARCHIVOS_MAX_CANTIDAD", 4096, 16384),
        _config("ESPACIO_LIBRE_BYTES", 512 * 1024**2, 1024**4),
        _config("PREPARACION_SEGUNDOS", 600, 3600),
        _config("CARGA_INACTIVA_SEGUNDOS", 60, 600),
    )


@contextmanager
def _seguridad():
    try:
        yield
    except motor.ErrorMotor:
        raise
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        raise motor.ErrorMotor("almacenamiento_adjunto_no_disponible") from None


def _ruta(zona, token):
    motor._referencia(token)
    return zona / (token + ".bin")


def _fila(db, remitente, clave):
    return db.execute(
        "SELECT * FROM archivos_externos WHERE remitente=? AND clave=?", (remitente, clave),
    ).fetchone()


def _espacio(zona, minimo):
    if shutil.disk_usage(zona).free < minimo:
        raise motor.ErrorMotor("espacio_adjuntos_insuficiente")


def _reservar(db, zona, remitente, destinatario, clave, generacion, ahora, limites):
    cantidad, activas, pendientes, reservado, ocupado = db.execute(
        """SELECT count(*), count(*) FILTER (WHERE estado='recibiendo'),
           count(*) FILTER (WHERE estado IN ('recibiendo','preparado')),
           coalesce(sum(?) FILTER (WHERE estado='recibiendo'),0), coalesce(sum(tamano),0)
           FROM archivos_externos WHERE estado!='retirado'""", (LIMITE_ARCHIVO,),
    ).fetchone()
    if activas >= limites.simultaneas or pendientes >= limites.sin_confirmar:
        raise motor.ErrorMotor("capacidad_cargas_agotada")
    if cantidad >= limites.archivos or ocupado + reservado + LIMITE_ARCHIVO > limites.capacidad:
        raise motor.ErrorMotor("capacidad_adjuntos_agotada")
    _espacio(zona, limites.libre + reservado + LIMITE_ARCHIVO)
    token = uuid4().hex
    db.execute(
        """INSERT INTO archivos_externos(token, remitente, destinatario, clave, generacion,
           limite_utc, inactivo_utc, estado) VALUES (?, ?, ?, ?, ?, ?, ?, 'recibiendo')""",
        (token, remitente, destinatario, clave, generacion,
         ahora + limites.preparacion, ahora + limites.inactividad),
    )
    return _fila(db, remitente, clave)


def _huella(nombre, tamano, sha):
    return hashlib.sha256(json.dumps([nombre, tamano, sha], separators=(",", ":")).encode("ascii")).hexdigest()


def _plazo(segundos):
    limite = time.monotonic() + segundos

    def comprobar():
        if time.monotonic() >= limite:
            raise motor.ErrorMotor("plazo_preparacion_agotado")

    return comprobar


def _copiar(flujo, comprobar, inactividad, *, escribir=None):
    sha = hashlib.sha256()
    tamano = 0
    while True:
        comprobar()
        inicio = time.monotonic()
        try:
            bloque = flujo.read(formatos.BLOQUE)
        except Exception:  # noqa: BLE001 - Una fuente interna puede lanzar errores con datos privados.
            raise motor.ErrorMotor("carga_interrumpida") from None
        if time.monotonic() - inicio >= inactividad:
            raise motor.ErrorMotor("carga_inactiva")
        comprobar()
        if not isinstance(bloque, bytes) or len(bloque) > formatos.BLOQUE:
            raise motor.ErrorMotor("flujo_invalido")
        if not bloque:
            break
        if tamano + len(bloque) > LIMITE_ARCHIVO:
            raise motor.ErrorMotor("archivo_demasiado_grande")
        if escribir is not None:
            escribir(bloque, tamano)
        tamano += len(bloque)
        sha.update(bloque)
    if not tamano:
        raise motor.ErrorMotor("archivo_vacio")
    return tamano, sha.hexdigest()


def _preparacion_vigente(fila, generacion, ahora):
    if fila["generacion"] != generacion:
        raise motor.ErrorMotor("generacion_cambio")
    if fila["limite_utc"] <= ahora:
        raise motor.ErrorMotor("preparacion_vencida")


def _registrar_archivo(zona, fila, pila):
    colision = False
    identidad = None
    with motor._transaccion(fila["remitente"], fila["destinatario"]) as (_, db, gen, ahora, _):
        actual = _fila(db, fila["remitente"], fila["clave"])
        if (actual is None or actual["token"] != fila["token"]
                or actual["estado"] != "recibiendo" or actual["identidad"] is not None):
            raise motor.ErrorMotor("preparacion_no_disponible")
        _preparacion_vigente(actual, gen, ahora)
        try:
            archivo, identidad = disco.abrir(_ruta(zona, fila["token"]), crear=True)
        except FileExistsError:
            colision = True
            db.execute("UPDATE archivos_externos SET error='colision' WHERE token=?", (fila["token"],))
        else:
            pila.enter_context(archivo)
            db.execute("UPDATE archivos_externos SET identidad=? WHERE token=?", (identidad, fila["token"]))
    if colision:
        raise motor.ErrorMotor("destino_adjunto_ocupado")
    return identidad


def _seguir_carga(db, fila, identidad, generacion, ahora):
    actual = _fila(db, fila["remitente"], fila["clave"])
    if (actual is None or actual["token"] != fila["token"] or actual["identidad"] != identidad
            or actual["estado"] != "recibiendo"):
        raise motor.ErrorMotor("preparacion_no_disponible")
    _preparacion_vigente(actual, generacion, ahora)
    if actual["inactivo_utc"] <= ahora:
        raise motor.ErrorMotor("carga_inactiva")


def _recibir(zona, fila, nombre, extension, flujo, limites, comprobar):
    with ExitStack() as pila:
        identidad = _registrar_archivo(zona, fila, pila)
    ruta = _ruta(zona, fila["token"])
    renovar = fila["inactivo_utc"] - limites.inactividad // 2

    def escribir(bloque, previo):
        nonlocal renovar
        if motor._ahora() >= renovar:
            with motor._transaccion(fila["remitente"], fila["destinatario"]) as (_, db, gen, ahora, _):
                _seguir_carga(db, fila, identidad, gen, ahora)
                db.execute("UPDATE archivos_externos SET inactivo_utc=? WHERE token=?",
                           (ahora + limites.inactividad, fila["token"]))
                renovar = ahora + max(1, limites.inactividad // 2)
        _espacio(zona, limites.libre + len(bloque))
        archivo, actual = disco.abrir(ruta, escribir=True)
        with archivo:
            if actual != identidad or archivo.seek(0, 2) != previo:
                raise motor.ErrorMotor("adjunto_no_disponible")
            if archivo.write(bloque) != len(bloque):
                raise motor.ErrorMotor("escritura_incompleta")

    # Ningún HANDLE de escritura se mantiene abierto mientras la fuente espera datos.
    tamano, sha = _copiar(flujo, comprobar, limites.inactividad, escribir=escribir)
    archivo, actual = disco.abrir(ruta, escribir=True)
    with archivo:
        if actual != identidad or _copiar(archivo, comprobar, limites.inactividad) != (tamano, sha):
            raise motor.ErrorMotor("adjunto_no_disponible")
        try:
            formatos.validar(archivo, extension, tamano, comprobar)
        except ValueError:
            raise motor.ErrorMotor("formato_incompatible") from None
        os.fsync(archivo.fileno())
        comprobar()
        # Publicación lógica: los bytes permanecen en el mismo objeto privado.
        # El escritor sigue excluyendo acceso y borrado hasta que acabe el commit.
        with motor._transaccion(fila["remitente"], fila["destinatario"]) as (_, db, gen, ahora, _):
            _seguir_carga(db, fila, identidad, gen, ahora)
            cambio = db.execute(
                "UPDATE archivos_externos SET estado='preparado', tamano=?, huella=? "
                "WHERE token=? AND estado='recibiendo' AND identidad IS NOT NULL",
                (tamano, _huella(nombre, tamano, sha), fila["token"]),
            )
            if cambio.rowcount != 1:
                raise motor.ErrorMotor("preparacion_no_disponible")
    return tamano


def preparar(remitente, destinatario, clave, nombre, flujo):
    """Recibe un lector binario con read(n). El transporte debe limitar lecturas bloqueadas."""
    pareja = motor._pareja(remitente, destinatario)
    motor._referencia(clave)
    try:
        extension = formatos.extension(nombre)
    except ValueError as error:
        raise motor.ErrorMotor(str(error)) from None
    limites = _limites()
    comprobar = _plazo(limites.preparacion)
    with _seguridad(), disco.zona() as zona:
        with motor._transaccion(*pareja) as (_, db, gen, ahora, _):
            fila = _fila(db, remitente, clave)
            nueva = fila is None
            if nueva:
                if db.execute("SELECT 1 FROM operaciones WHERE usuario_ref=? AND clave=?",
                              (remitente, clave)).fetchone():
                    raise motor.ErrorMotor("conflicto_idempotencia")
                fila = _reservar(db, zona, remitente, destinatario, clave, gen, ahora, limites)
            elif fila["destinatario"] != destinatario:
                raise motor.ErrorMotor("conflicto_idempotencia")
            elif fila["estado"] == "recibiendo":
                raise motor.ErrorMotor("carga_en_curso")
            elif fila["estado"] == "preparado":
                _preparacion_vigente(fila, gen, ahora)
        if nueva:
            try:
                tamano = _recibir(zona, fila, nombre, extension, flujo, limites, comprobar)
            except (Exception, KeyboardInterrupt):
                # Acorta la espera solo para nuestra intención aún sin publicar.
                from app.mensajeria.limpieza_adjuntos import abortar
                abortar(zona, fila["token"])
                raise
        else:
            tamano, sha = _copiar(flujo, comprobar, limites.inactividad)
            if _huella(nombre, tamano, sha) != fila["huella"]:
                raise motor.ErrorMotor("conflicto_idempotencia")
        return motor.Adjunto("externo", fila["token"], nombre, tamano)


def _verificar_archivo(zona, fila, nombre, tamano, pila):
    archivo, identidad = disco.abrir(_ruta(zona, fila["token"]))
    pila.enter_context(archivo)
    if identidad != fila["identidad"] or tamano != fila["tamano"]:
        raise motor.ErrorMotor("adjunto_no_disponible")
    real, sha = _copiar(archivo, _plazo(30), 30)
    if real != tamano or _huella(nombre, real, sha) != fila["huella"]:
        raise motor.ErrorMotor("adjunto_no_disponible")
    archivo.seek(0)
    return archivo


def _validar_preparado(fila, solicitud, ahora):
    if (fila is None or fila["token"] != solicitud.adjunto.referencia
            or fila["estado"] != "preparado" or fila["destinatario"] != solicitud.destinatario):
        raise motor.ErrorMotor("adjunto_no_confirmado")
    _preparacion_vigente(fila, solicitud.generacion, ahora)


def confirmar(remitente, destinatario, texto, clave, adjunto):
    pareja, huella = motor._datos_envio(remitente, destinatario, texto, clave, adjunto)
    if adjunto.tipo != "externo":
        raise motor.ErrorMotor("adjunto_invalido")
    with _seguridad(), disco.zona() as zona, ExitStack() as pila:
        with motor._transaccion(*pareja) as (_, db, gen, ahora, _):
            previa = motor._repeticion(db, remitente, clave, huella)
            if previa is not None:
                return previa
            solicitud = motor.VerificacionAdjunto(adjunto, remitente, destinatario, gen, clave)
            fila = _fila(db, remitente, clave)
            _validar_preparado(fila, solicitud, ahora)
        _verificar_archivo(zona, fila, adjunto.nombre_original, adjunto.tamano_bytes, pila)
        with motor._transaccion(*pareja) as (principal, db, actual, ahora, dia):
            if actual != gen:
                raise motor.ErrorMotor("generacion_cambio")
            previa = motor._repeticion(db, remitente, clave, huella)
            if previa is not None:
                return previa
            vigente = _fila(db, remitente, clave)
            _validar_preparado(vigente, solicitud, ahora)
            if tuple(vigente) != tuple(fila):
                raise motor.ErrorMotor("adjunto_no_disponible")
            mensaje = motor._persistir(principal, db, solicitud, pareja, clave, huella, texto, ahora, dia)
            db.execute(
                "UPDATE archivos_externos SET estado='confirmado', mensaje_id=?, vence_utc=? WHERE token=?",
                (mensaje, ahora + motor.VIGENCIA_ARCHIVO, fila["token"]),
            )
            return mensaje


def _autorizado(db, actor, mensaje, ahora):
    fila = db.execute(
        """SELECT a.*, m.nombre_original, m.tamano_bytes FROM mensajes m
           JOIN archivos_externos a ON a.token=m.archivo_token AND a.mensaje_id=m.id
           AND a.remitente=m.remitente_ref AND a.destinatario=m.destinatario_ref
           AND a.vence_utc=m.vence_utc
           WHERE m.id=? AND ? IN (m.remitente_ref, m.destinatario_ref)
           AND a.estado='confirmado' AND m.vence_utc>?""",
        (mensaje, actor, ahora),
    ).fetchone()
    if fila is None:
        raise motor.ErrorMotor("adjunto_no_disponible")
    return fila


@contextmanager
def abrir_descarga(actor, mensaje):
    """Devuelve un flujo binario privado y cabeceras para una futura respuesta adjunta."""
    motor._referencia(mensaje)
    with ExitStack() as pila:
        with _seguridad():
            zona = pila.enter_context(disco.zona())
            with motor._transaccion(actor) as (_, db, generacion, ahora, _):
                fila = _autorizado(db, actor, mensaje, ahora)
            archivo = _verificar_archivo(zona, fila, fila["nombre_original"], fila["tamano_bytes"], pila)
            with motor._transaccion(actor) as (_, db, actual, ahora, _):
                if actual != generacion or tuple(_autorizado(db, actor, mensaje, ahora)) != tuple(fila):
                    raise motor.ErrorMotor("adjunto_no_disponible")
            nombre = quote(fila["nombre_original"], safe="")
            cabeceras = {
                "Content-Type": "application/octet-stream",
                "Content-Disposition": f"attachment; filename*=UTF-8''{nombre}",
                "Content-Length": str(fila["tamano_bytes"]),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            }
        yield archivo, cabeceras
