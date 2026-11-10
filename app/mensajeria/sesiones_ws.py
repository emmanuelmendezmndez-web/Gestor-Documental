"""Vincula la cookie SIGED con una sesión experimental revocable de Mensajería."""

import re
import sqlite3
from dataclasses import dataclass
from secrets import token_hex

from app.coordinacion import BloqueoDatos
from app.database import conectar
from app.mensajeria import eventos, motor
from app.mensajeria.reconciliacion import _bases, _vinculo_vigente

CAMPO = "mensajeria_ws"
VIGENCIA = 10 * 3600
MAX_REGISTROS = 4096
_ID = re.compile(r"[0-9a-f]{32}")
ERRORES_DATOS = (OSError, RuntimeError, ValueError, sqlite3.Error)


@dataclass(frozen=True)
class Credencial:
    token: str
    usuario_id: int
    version: int
    vence: int


@dataclass(frozen=True)
class Identidad:
    usuario_ref: str
    generacion: str


@dataclass(frozen=True)
class Solicitud:
    credencial: Credencial
    identidad: Identidad | None = None
    inicial: bool = False
    cursor: str | None = None


def credencial(sesion):
    marca = sesion.get(CAMPO)
    usuario, version = sesion.get("usuario_id"), sesion.get("version")
    if (not isinstance(marca, list) or len(marca) != 2
            or not isinstance(marca[0], str) or not _ID.fullmatch(marca[0]) or type(marca[1]) is not int
            or type(usuario) is not int or type(version) is not int):
        return None
    return Credencial(marca[0], usuario, version, marca[1])


def registrar(fila):
    """Solo se invoca después de autenticar la contraseña por el flujo normal."""
    try:
        with _bases() as (principal, db, generacion):
            if not _vinculo_vigente(principal, db, generacion):
                return None
            usuario = principal.execute(
                """SELECT mensajeria_ref FROM usuarios WHERE id=? AND activo=1
                   AND usuario=? AND password_hash=? AND version_sesion=?""",
                (fila["id"], fila["usuario"], fila["password_hash"], fila["version_sesion"]),
            ).fetchone()
            if usuario is None or not isinstance(usuario[0], str) or not _ID.fullmatch(usuario[0]):
                return None
            ahora = motor._ahora()
            db.execute("DELETE FROM sesiones_ws WHERE vence_utc<=?", (ahora,))
            if db.execute("SELECT count(*) FROM sesiones_ws").fetchone()[0] >= MAX_REGISTROS:
                return None
            token = token_hex(16)
            vence = ahora + VIGENCIA
            db.execute(
                "INSERT INTO sesiones_ws VALUES (?,?,?,?,?,?,0)",
                (token, usuario[0], fila["version_sesion"], generacion, ahora, vence),
            )
            return [token, vence]
    except ERRORES_DATOS:
        # Una incidencia experimental no impide el login normal.
        return None


def revocar(sesion):
    """Revoca esa sesión. Si el registro privado falla, invalida su versión."""
    datos = credencial(sesion)
    if datos is None or datos.vence <= motor._ahora():
        return
    try:
        with _bases() as (_, db, _):
            cambio = db.execute(
                "UPDATE sesiones_ws SET revocada=1 WHERE id=? AND vence_utc=?",
                (datos.token, datos.vence),
            )
            if cambio.rowcount:
                return
    except ERRORES_DATOS:
        pass
    # Ante un almacén privado inaccesible, el cambio de versión sigue siendo
    # verificable en la base principal por conexiones nuevas y existentes.
    with BloqueoDatos(exclusivo=False), conectar() as principal:
        principal.execute(
            "UPDATE usuarios SET version_sesion=version_sesion+1 WHERE id=? AND version_sesion=?",
            (datos.usuario_id, datos.version),
        )


def _identidad(principal, db, datos, generacion, ahora):
    if datos.vence <= ahora:
        return None
    registro = db.execute(
        """SELECT usuario_ref FROM sesiones_ws WHERE id=? AND revocada=0 AND version_sesion=?
           AND generacion=? AND emitida_utc<=? AND vence_utc=?""",
        (datos.token, datos.version, generacion, ahora, datos.vence),
    ).fetchone()
    if registro is None:
        return None
    usuario = principal.execute(
        "SELECT 1 FROM usuarios WHERE id=? AND mensajeria_ref=? AND activo=1 AND version_sesion=?",
        (datos.usuario_id, registro[0], datos.version),
    ).fetchone()
    return Identidad(registro[0], generacion) if usuario is not None else None


def consultar_lote(solicitudes, secreto):
    """Una instantánea coordinada para todas las conexiones del ciclo."""
    with _bases(lectura=True) as (principal, db, generacion):
        if not _vinculo_vigente(principal, db, generacion):
            return [None for _ in solicitudes]
        ahora = motor._ahora()
        resultados = []
        for solicitud in solicitudes:
            actor = _identidad(principal, db, solicitud.credencial, generacion, ahora)
            if solicitud.identidad is None:
                resultados.append(actor)
            elif actor != solicitud.identidad:
                resultados.append(None)
            else:
                resultados.append(eventos.pagina(
                    db, actor.usuario_ref, generacion, solicitud.cursor, solicitud.inicial, ahora, secreto,
                ))
        return resultados
