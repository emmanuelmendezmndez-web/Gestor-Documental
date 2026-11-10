"""Registro persistente y proyección mínima de señales de Mensajería."""

import hmac
import re

RETENCION = 15 * 86400
PAGINA = 32
TIPOS = {
    "mensaje_confirmado": "mensaje_nuevo",
    "mensaje_leido": "lectura_actualizada",
    "bandeja_actualizada": "bandeja_actualizada",
}
_FILTRO = "destinatario_ref=? AND creado_utc>? AND tipo IN ('mensaje_confirmado','mensaje_leido','bandeja_actualizada')"
_CURSOR = re.compile(r"[0-9a-f]{32}\.[0-9a-f]{64}")


def depurar(db, ahora, limite=100):
    db.execute(
        "DELETE FROM eventos WHERE id IN (SELECT id FROM eventos WHERE creado_utc<=? "
        "ORDER BY creado_utc, id LIMIT ?)", (ahora - RETENCION, limite),
    )


def registrar(db, destinatario, tipo, ahora, mensaje=None):
    if tipo not in TIPOS:
        raise ValueError("tipo_evento_invalido")
    db.execute(
        "INSERT INTO eventos(mensaje_id, destinatario_ref, tipo, creado_utc) VALUES (?,?,?,?)",
        (mensaje, destinatario, tipo, ahora),
    )
    depurar(db, ahora)


def _firmar(secreto, actor, generacion, cursor):
    datos = f"siged:mensajeria:cursor:v1:{actor}:{generacion}:{cursor}".encode("ascii")
    return cursor + "." + hmac.digest(secreto, datos, "sha256").hex()


def pagina(db, actor, generacion, cursor, inicial, ahora, secreto):
    """Proyecta una página sin entregar IDs internos ni datos del mensaje."""
    parametros = (actor, ahora - RETENCION)
    ancla = None
    if cursor is not None and _CURSOR.fullmatch(cursor):
        token = cursor.split(".", 1)[0]
        if hmac.compare_digest(cursor, _firmar(secreto, actor, generacion, token)):
            ancla = db.execute(
                "SELECT id FROM eventos WHERE " + _FILTRO + " AND cursor=?", (*parametros, token),
            ).fetchone()
    if (inicial and cursor is None) or (cursor is not None and ancla is None):
        ultima = db.execute(
            "SELECT cursor FROM eventos WHERE " + _FILTRO + " ORDER BY id DESC LIMIT 1", parametros,
        ).fetchone()
        return [{"tipo": "resincronizar",
                 "cursor": _firmar(secreto, actor, generacion, ultima[0]) if ultima else None}]
    return [
        {"tipo": TIPOS[fila["tipo"]], "cursor": _firmar(secreto, actor, generacion, fila["cursor"])}
        for fila in db.execute(
            "SELECT tipo,cursor FROM eventos WHERE " + _FILTRO + " AND id>? ORDER BY id LIMIT ?",
            (*parametros, ancla[0] if ancla else 0, PAGINA),
        )
    ]
