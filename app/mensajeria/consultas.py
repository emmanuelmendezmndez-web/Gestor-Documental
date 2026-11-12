"""Proyecciones acotadas para clientes autenticados de Mensajería."""

from pathlib import PureWindowsPath

from app.mensajeria import adjuntos, biblioteca, motor, vistas


def destinatarios(actor, despues, limite):
    with motor._transaccion(actor) as (principal, _, _, _, _):
        filas = principal.execute(
            """SELECT mensajeria_ref,nombre,departamento FROM usuarios WHERE activo=1
               AND mensajeria_ref!=? AND mensajeria_ref>?
               ORDER BY mensajeria_ref LIMIT ?""", (actor, despues or "", limite + 1),
        ).fetchall()
        return {"elementos": [{"referencia": f[0], "nombre": f[1] or "Usuario", "area": f[2]}
                              for f in filas[:limite]],
                "siguiente": filas[limite - 1][0] if len(filas) > limite else None}


def _conversaciones(principal, db, actor, archivadas, despues, limite, ahora):
    filas = db.execute(
        """SELECT c.id, CASE WHEN c.participante_a=? THEN c.participante_b ELSE c.participante_a END
           FROM conversaciones c LEFT JOIN estado_participante e
           ON e.conversacion_id=c.id AND e.usuario_ref=?
           WHERE ? IN (c.participante_a,c.participante_b) AND coalesce(e.archivada,0)=?
           AND c.id>? ORDER BY c.id LIMIT ?""", (actor, actor, actor, archivadas, despues or "", limite + 1),
    ).fetchall()
    resultado = []
    for chat, otro in filas[:limite]:
        usuario = principal.execute(
            "SELECT nombre,departamento FROM usuarios WHERE mensajeria_ref=? AND activo=1", (otro,),
        ).fetchone()
        ultimo = db.execute(
            """SELECT texto,confirmado_utc FROM mensajes WHERE conversacion_id=? AND confirmado_utc>?
               ORDER BY confirmado_utc DESC,id DESC LIMIT 1""",
            (chat, ahora - motor.RETENCION),
        ).fetchone()
        no_leidos = db.execute(
            """SELECT count(*) FROM mensajes m WHERE conversacion_id=? AND destinatario_ref=? AND confirmado_utc>?
               AND NOT EXISTS (SELECT 1 FROM lecturas l WHERE l.mensaje_id=m.id)""",
            (chat, actor, ahora - motor.RETENCION),
        ).fetchone()[0]
        resultado.append({
            "id": chat,
            "otro": {"referencia": otro, "nombre": usuario[0] or "Usuario", "area": usuario[1]} if usuario else None,
            "archivada": archivadas, "ultimo": dict(ultimo) if ultimo else None, "no_leidos": no_leidos,
        })
    return {"elementos": resultado, "siguiente": filas[limite - 1][0] if len(filas) > limite else None}


def conversaciones(actor, archivadas, despues, limite):
    with motor._transaccion(actor) as (principal, db, _, ahora, _):
        return _conversaciones(principal, db, actor, archivadas, despues, limite, ahora)


def _avisos(principal, db, actor, desde):
    filas = db.execute(
        """WITH pendientes AS (
               SELECT conversacion_id,remitente_ref,id,confirmado_utc,
                      row_number() OVER (PARTITION BY conversacion_id ORDER BY confirmado_utc DESC,id DESC) AS orden
               FROM mensajes m WHERE destinatario_ref=? AND confirmado_utc>?
               AND NOT EXISTS (SELECT 1 FROM lecturas l WHERE l.mensaje_id=m.id)
           )
           SELECT remitente_ref,id,conversacion_id,confirmado_utc FROM pendientes WHERE orden=1
           ORDER BY confirmado_utc DESC,id DESC LIMIT 25""",
        (actor, desde),
    ).fetchall()
    avisos = []
    for remitente, mensaje, conversacion, confirmado in filas:
        perfil = principal.execute(
            "SELECT nombre FROM usuarios WHERE mensajeria_ref=? AND activo=1", (remitente,),
        ).fetchone()
        avisos.append({
            "mensaje": mensaje, "nombre": perfil[0] if perfil else None,
            "conversacion": conversacion, "confirmado_utc": confirmado,
        })
    return avisos


def sincronizar(actor, archivadas, despues, limite, avisos=False):
    with motor._transaccion(actor) as (principal, db, _, ahora, dia):
        no_leidos = db.execute(
            """SELECT count(*) FROM mensajes m WHERE destinatario_ref=? AND confirmado_utc>?
               AND NOT EXISTS (SELECT 1 FROM lecturas l WHERE l.mensaje_id=m.id)""",
            (actor, ahora - motor.RETENCION),
        ).fetchone()[0]
        estado = {"conversaciones": _conversaciones(principal, db, actor, archivadas, despues, limite, ahora),
                  "no_leidos": no_leidos, "cuota": con_restantes(motor._cuota(db, actor, dia))}
        if avisos:
            estado["avisos"] = _avisos(principal, db, actor, ahora - motor.RETENCION)
        return estado


def con_restantes(cuota):
    return {**cuota, "restantes": cuota["limite"] - cuota["envios"]}


def mensajes(actor, chat, cursor, limite):
    filas = motor.mensajes(actor, chat, antes_de=cursor, limite=limite + 1)
    campos = ("id", "remitente_ref", "destinatario_ref", "texto", "confirmado_utc",
              "historial_vence_utc", "tipo_adjunto", "leido_utc")
    siguiente = filas[limite - 1] if len(filas) > limite else None
    elementos = [{**{k: f[k] for k in campos}, "enviado": f["remitente_ref"] == actor} for f in filas[:limite]]
    return {"elementos": elementos,
            "siguiente": f"{siguiente['confirmado_utc']}.{siguiente['id']}" if siguiente else None}


def tipo_adjunto(actor, chat, mensaje):
    with motor._transaccion(actor) as (_, db, _, ahora, _):
        fila = db.execute(
            """SELECT tipo_adjunto FROM mensajes WHERE id=? AND conversacion_id=?
               AND ? IN (remitente_ref,destinatario_ref) AND confirmado_utc>?""",
            (mensaje, chat, actor, ahora - motor.RETENCION),
        ).fetchone()
        if fila is None:
            raise motor.ErrorMotor("mensaje_no_disponible")
        return fila[0]


def tarjeta(actor, chat, mensaje):
    tipo = tipo_adjunto(actor, chat, mensaje)
    if tipo == "externo":
        try:
            datos = adjuntos.tarjeta(actor, mensaje, chat)
        except motor.ErrorMotor as error:
            if str(error) in {"sesion_no_valida", "identidad_no_reconciliada"}:
                raise
            return {"estado": "no_disponible"}
    else:
        datos = biblioteca.tarjeta(actor, chat, mensaje, informar_estado_sesion=True)
    if datos["estado"] == "disponible":
        datos["extension"] = PureWindowsPath(datos["nombre_original"]).suffix.lower() or None
        acciones = ["visualizar"] if vistas.habilitada(datos) else []
        if "descargar" in datos["acciones"]:
            acciones.append("descargar")
        datos["acciones"] = acciones
    return datos
