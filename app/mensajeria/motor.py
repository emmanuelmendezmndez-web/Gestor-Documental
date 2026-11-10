"""Operaciones internas de mensajería con identidad y generación reconciliadas."""

import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.mensajeria.base_datos import LIMITE_ARCHIVO
from app.mensajeria.reconciliacion import _bases, _evaluar, _incidencias

RETENCION = 15 * 86400
CUOTA_DIARIA = 50
VIGENCIA_ARCHIVO = 3 * 3600


class ErrorMotor(ValueError):
    """Código de rechazo apto para diagnóstico, sin datos del mensaje."""


@dataclass(frozen=True)
class Adjunto:
    tipo: str
    referencia: str
    nombre_original: str | None = None
    tamano_bytes: int | None = None


@dataclass(frozen=True)
class VerificacionAdjunto:
    adjunto: Adjunto
    remitente: str
    destinatario: str
    generacion: str
    clave_operacion: str


def _referencia(valor):
    if not isinstance(valor, str) or not re.fullmatch(r"[0-9a-f]{32}", valor):
        raise ErrorMotor("referencia_invalida")


def _texto_valido(valor, maximo):
    if not isinstance(valor, str) or not valor.strip() or len(valor) > maximo or "\0" in valor:
        return False
    try:
        valor.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _adjunto_valido(adjunto):
    if not isinstance(adjunto, Adjunto):
        raise ErrorMotor("adjunto_obligatorio")
    _referencia(adjunto.referencia)
    if adjunto.tipo == "documento" and adjunto.nombre_original is None and adjunto.tamano_bytes is None:
        return
    if (adjunto.tipo == "externo" and _texto_valido(adjunto.nombre_original, 260)
            and type(adjunto.tamano_bytes) is int and 1 <= adjunto.tamano_bytes <= LIMITE_ARCHIVO):
        return
    raise ErrorMotor("adjunto_invalido")


def _ahora():
    return int(datetime.now(UTC).timestamp())


def _zona():
    nombre = os.environ.get("GESTOR_MENSAJERIA_ZONA_HORARIA", "UTC").strip()
    if nombre == "UTC":
        return nombre, UTC
    coincidencia = re.fullmatch(r"([+-])(\d{2}):(\d{2})", nombre, flags=re.ASCII)
    if coincidencia:
        horas, minutos = map(int, coincidencia.groups()[1:])
        if minutos < 60 and horas * 60 + minutos <= 14 * 60:
            signo = -1 if coincidencia[1] == "-" else 1
            return nombre, timezone(signo * timedelta(hours=horas, minutes=minutos))
    try:
        return nombre, ZoneInfo(nombre)
    except (ValueError, ZoneInfoNotFoundError):
        raise ErrorMotor("zona_horaria_no_disponible") from None


def _reloj(db):
    nombre, zona = _zona()
    ahora = _ahora()
    previo = db.execute("SELECT ultimo_utc, zona FROM reloj_motor WHERE id=1").fetchone()
    if previo is not None:
        if previo["zona"] not in (None, nombre):
            raise ErrorMotor("zona_horaria_incompatible")
        if ahora < previo["ultimo_utc"]:
            raise ErrorMotor("reloj_retrocedio")
    db.execute(
        "INSERT INTO reloj_motor VALUES (1, ?, ?) ON CONFLICT(id) "
        "DO UPDATE SET ultimo_utc=excluded.ultimo_utc, zona=excluded.zona",
        (ahora, nombre),
    )
    return ahora, datetime.fromtimestamp(ahora, zona).date().isoformat()


@contextmanager
def _transaccion(*usuarios):
    for usuario in usuarios:
        _referencia(usuario)
    with _bases() as (principal, db, generacion):
        if _evaluar(principal, db, generacion)["estado"] != "identidad_coherente":
            raise ErrorMotor("identidad_no_reconciliada")
        for usuario in usuarios:
            if principal.execute(
                "SELECT 1 FROM usuarios WHERE mensajeria_ref=? AND activo=1", (usuario,),
            ).fetchone() is None:
                raise ErrorMotor("usuario_no_disponible")
        ahora, dia = _reloj(db)
        yield principal, db, generacion, ahora, dia


def _pareja(remitente, destinatario):
    _referencia(remitente)
    _referencia(destinatario)
    if remitente == destinatario:
        raise ErrorMotor("autoenvio_no_permitido")
    return tuple(sorted((remitente, destinatario)))


def _conversacion(db, pareja, crear):
    fila = db.execute(
        "SELECT id FROM conversaciones WHERE participante_a=? AND participante_b=?", pareja,
    ).fetchone()
    if fila is not None:
        return fila["id"]
    if not crear:
        return None
    identificador = uuid4().hex
    db.execute("INSERT INTO conversaciones VALUES (?, ?, ?)", (identificador, *pareja))
    return identificador


def conversacion(actor, otro, *, crear=False):
    pareja = _pareja(actor, otro)
    with _transaccion(*pareja) as (_, db, _, _, _):
        return _conversacion(db, pareja, crear)


def _huella(destinatario, texto, adjunto):
    campos = [destinatario, texto, adjunto.tipo, adjunto.referencia,
              adjunto.nombre_original, adjunto.tamano_bytes]
    return hashlib.sha256(json.dumps(campos, separators=(",", ":")).encode("ascii")).hexdigest()


def _repeticion(db, remitente, clave, huella):
    previa = db.execute(
        "SELECT estado, resultado_id, huella FROM operaciones WHERE usuario_ref=? AND clave=?",
        (remitente, clave),
    ).fetchone()
    if previa is None:
        return None
    if previa["estado"] != "confirmada" or previa["huella"] != huella:
        raise ErrorMotor("conflicto_idempotencia")
    return previa["resultado_id"]


def _consumir_cuota(db, remitente, dia):
    cambio = db.execute(
        "INSERT INTO cuotas VALUES (?, ?, 1) ON CONFLICT(usuario_ref, dia_local) "
        "DO UPDATE SET envios=envios+1 WHERE envios < ?",
        (remitente, dia, CUOTA_DIARIA),
    )
    if cambio.rowcount != 1:
        raise ErrorMotor("cuota_agotada")


def _persistir(principal, db, solicitud, pareja, clave, huella, texto, ahora, dia):
    adjunto = solicitud.adjunto
    documento = adjunto.referencia if adjunto.tipo == "documento" else None
    archivo = adjunto.referencia if adjunto.tipo == "externo" else None
    if documento is not None and any(_incidencias(principal, (), (documento,)).values()):
        raise ErrorMotor("adjunto_no_disponible")
    if archivo is not None and db.execute(
        "SELECT 1 FROM mensajes WHERE archivo_token=? UNION ALL "
        "SELECT 1 FROM limpieza WHERE archivo_token=?", (archivo, archivo),
    ).fetchone():
        raise ErrorMotor("adjunto_ya_utilizado")
    _consumir_cuota(db, solicitud.remitente, dia)
    conversacion_id = _conversacion(db, pareja, crear=True)
    mensaje = uuid4().hex
    vence = ahora + (VIGENCIA_ARCHIVO if archivo else 604800)
    db.execute(
        "INSERT INTO mensajes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (mensaje, conversacion_id, solicitud.remitente, solicitud.destinatario, texto,
         ahora, vence, adjunto.tipo, documento, archivo, adjunto.nombre_original, adjunto.tamano_bytes),
    )
    db.execute(
        "INSERT INTO operaciones VALUES (?, ?, 'confirmada', ?, ?, ?)",
        (solicitud.remitente, clave, mensaje, mensaje, huella),
    )
    db.execute(
        "INSERT INTO eventos(mensaje_id, destinatario_ref, tipo, creado_utc) "
        "VALUES (?, ?, 'mensaje_confirmado', ?)", (mensaje, solicitud.destinatario, ahora),
    )
    return mensaje


def enviar(remitente, destinatario, texto, clave, adjunto, *, verificar_adjunto=None):
    """Los archivos externos requieren la preparación privada de Mensajería."""
    if isinstance(adjunto, Adjunto) and adjunto.tipo == "externo":
        from app.mensajeria.adjuntos import confirmar
        return confirmar(remitente, destinatario, texto, clave, adjunto)
    return _enviar_con_adaptador(remitente, destinatario, texto, clave, adjunto, verificar_adjunto)


def _datos_envio(remitente, destinatario, texto, clave, adjunto):
    pareja = _pareja(remitente, destinatario)
    _referencia(clave)
    if not _texto_valido(texto, 300):
        raise ErrorMotor("texto_invalido")
    _adjunto_valido(adjunto)
    return pareja, _huella(destinatario, texto, adjunto)


def _enviar_con_adaptador(remitente, destinatario, texto, clave, adjunto, verificar_adjunto):
    pareja, huella = _datos_envio(remitente, destinatario, texto, clave, adjunto)
    with _transaccion(*pareja) as (_, db, generacion, _, _):
        previa = _repeticion(db, remitente, clave, huella)
        if previa is not None:
            return previa
    solicitud = VerificacionAdjunto(adjunto, remitente, destinatario, generacion, clave)
    try:
        aprobado = verificar_adjunto(solicitud) if verificar_adjunto is not None else False
    except Exception:  # noqa: BLE001 - Un adaptador interno puede incluir datos privados en el error.
        raise ErrorMotor("verificacion_adjunto_fallida") from None
    if aprobado is not True:
        raise ErrorMotor("adjunto_no_confirmado")
    with _transaccion(*pareja) as (principal, db, actual, ahora, dia):
        if actual != solicitud.generacion:
            raise ErrorMotor("generacion_cambio")
        previa = _repeticion(db, remitente, clave, huella)
        if previa is not None:
            return previa
        return _persistir(principal, db, solicitud, pareja, clave, huella, texto, ahora, dia)


def cuota(actor):
    with _transaccion(actor) as (_, db, _, _, dia):
        fila = db.execute(
            "SELECT envios FROM cuotas WHERE usuario_ref=? AND dia_local=?", (actor, dia),
        ).fetchone()
        return {"dia": dia, "envios": fila[0] if fila else 0, "limite": CUOTA_DIARIA}


def _comprobar_participante(db, actor, conversacion_id):
    _referencia(conversacion_id)
    if db.execute(
        "SELECT 1 FROM conversaciones WHERE id=? AND ? IN (participante_a, participante_b)",
        (conversacion_id, actor),
    ).fetchone() is None:
        raise ErrorMotor("conversacion_no_disponible")


def conversaciones(actor, *, archivadas=False):
    with _transaccion(actor) as (_, db, _, _, _):
        return [dict(fila) for fila in db.execute(
            "SELECT c.id, CASE WHEN c.participante_a=? THEN c.participante_b ELSE c.participante_a END AS otro "
            "FROM conversaciones c LEFT JOIN estado_participante e "
            "ON e.conversacion_id=c.id AND e.usuario_ref=? "
            "WHERE ? IN (c.participante_a, c.participante_b) AND coalesce(e.archivada,0)=? ORDER BY c.id",
            (actor, actor, actor, int(archivadas)),
        )]


def archivar(actor, conversacion_id, *, archivada=True):
    with _transaccion(actor) as (_, db, _, _, _):
        _comprobar_participante(db, actor, conversacion_id)
        db.execute(
            "INSERT INTO estado_participante(conversacion_id, usuario_ref, archivada) VALUES (?, ?, ?) "
            "ON CONFLICT(conversacion_id, usuario_ref) DO UPDATE SET archivada=excluded.archivada",
            (conversacion_id, actor, int(archivada)),
        )


def mensajes(actor, conversacion_id, *, antes_de=None, limite=50):
    if type(limite) is not int or not 1 <= limite <= 100:
        raise ErrorMotor("limite_invalido")
    if antes_de is not None:
        if not isinstance(antes_de, tuple) or len(antes_de) != 2 or type(antes_de[0]) is not int:
            raise ErrorMotor("cursor_invalido")
        _referencia(antes_de[1])
    with _transaccion(actor) as (_, db, _, ahora, _):
        _comprobar_participante(db, actor, conversacion_id)
        filas = db.execute(
            "SELECT m.id, m.remitente_ref, m.destinatario_ref, m.texto, m.confirmado_utc, "
            "m.confirmado_utc + ? AS historial_vence_utc, m.tipo_adjunto, m.vence_utc, "
            "m.nombre_original, m.tamano_bytes, "
            "CASE WHEN m.tipo_adjunto='externo' THEN CASE "
            "WHEN m.vence_utc<=? THEN 'vencido' "
            "WHEN a.estado='confirmado' AND a.mensaje_id=m.id THEN 'vigente' "
            "ELSE 'no_disponible' END END AS estado_archivo, "
            "CASE WHEN m.destinatario_ref=? THEN l.leido_utc END AS leido_utc "
            "FROM mensajes m LEFT JOIN lecturas l ON l.mensaje_id=m.id "
            "LEFT JOIN archivos_externos a ON a.token=m.archivo_token "
            "WHERE m.conversacion_id=? AND m.confirmado_utc>? "
            "AND (? IS NULL OR (m.confirmado_utc, m.id) < (?, ?)) "
            "ORDER BY m.confirmado_utc DESC, m.id DESC LIMIT ?",
            (RETENCION, ahora, actor, conversacion_id, ahora - RETENCION,
             antes_de[0] if antes_de else None, *(antes_de or (None, None)), limite),
        )
        resultado = []
        for fila in filas:
            datos = dict(fila)
            if fila["tipo_adjunto"] != "externo":
                for campo in ("nombre_original", "tamano_bytes", "estado_archivo"):
                    del datos[campo]
            resultado.append(datos)
        return resultado


def marcar_leido(actor, mensaje_id):
    _referencia(mensaje_id)
    with _transaccion(actor) as (_, db, _, ahora, _):
        if db.execute(
            "SELECT 1 FROM mensajes WHERE id=? AND destinatario_ref=? AND confirmado_utc>?",
            (mensaje_id, actor, ahora - RETENCION),
        ).fetchone() is None:
            raise ErrorMotor("mensaje_no_disponible")
        db.execute("INSERT OR IGNORE INTO lecturas VALUES (?, ?)", (mensaje_id, ahora))


def depurar_historial(*, limite=200):
    """Retira historial vencido y conserva cuota, comprobante y token externo."""
    if type(limite) is not int or not 1 <= limite <= 200:
        raise ErrorMotor("limite_invalido")
    with _transaccion() as (_, db, _, ahora, _):
        filas = db.execute(
            "SELECT id, archivo_token FROM mensajes WHERE confirmado_utc<=? "
            "ORDER BY confirmado_utc, id LIMIT ?", (ahora - RETENCION, limite),
        ).fetchall()
        for fila in filas:
            if fila["archivo_token"] is not None and not db.execute(
                "SELECT 1 FROM archivos_externos WHERE token=? AND mensaje_id=?",
                (fila["archivo_token"], fila["id"]),
            ).fetchone():
                db.execute(
                    "INSERT INTO limpieza(archivo_token, estado, ultimo_error) "
                    "VALUES (?, 'suspendida', 'Pendiente de verificacion del adjunto') "
                    "ON CONFLICT(archivo_token) DO NOTHING", (fila["archivo_token"],),
                )
            db.execute("DELETE FROM eventos WHERE mensaje_id=?", (fila["id"],))
            db.execute("DELETE FROM mensajes WHERE id=?", (fila["id"],))
        return len(filas)
