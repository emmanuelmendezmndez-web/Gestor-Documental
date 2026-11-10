"""Esquema independiente de mensajería; no habilita operaciones ni rutas."""

import os
import re
import sqlite3
import stat
import time
from contextlib import closing, contextmanager
from pathlib import Path

from app.coordinacion import BloqueoDatos
from app.mensajeria.configuracion import directorio_configurado
from app.mensajeria.identidad import exigir_identidad_verificada
from app.temporal_privado import (
    directorio_privado,
    verificar_acl_base_privada,
    verificar_acl_privada,
)

VERSION = 6
APPLICATION_ID = 0x53474D31
NOMBRE_BASE = "mensajeria.sqlite3"
LIMITE_ARCHIVO = 20 * 1024 * 1024
ESTRUCTURA = (
    """CREATE TABLE contexto (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        instalacion_id TEXT,
        generacion_id TEXT,
        estado TEXT NOT NULL CHECK (estado = 'no_verificada'),
        CHECK (instalacion_id IS NULL AND generacion_id IS NULL)
    )""",
    """INSERT INTO contexto(id, estado) VALUES (1, 'no_verificada')""",
    """CREATE TABLE conversaciones (
        id TEXT PRIMARY KEY NOT NULL,
        participante_a TEXT NOT NULL,
        participante_b TEXT NOT NULL,
        CHECK (length(participante_a) = 32 AND participante_a NOT GLOB '*[^0-9a-f]*'),
        CHECK (length(participante_b) = 32 AND participante_b NOT GLOB '*[^0-9a-f]*'),
        CHECK (participante_a < participante_b),
        UNIQUE(participante_a, participante_b)
    )""",
    """CREATE TABLE mensajes (
        id TEXT PRIMARY KEY NOT NULL,
        conversacion_id TEXT NOT NULL REFERENCES conversaciones(id),
        remitente_ref TEXT NOT NULL,
        destinatario_ref TEXT NOT NULL,
        texto TEXT NOT NULL DEFAULT '' CHECK (length(texto) <= 300),
        confirmado_utc INTEGER NOT NULL,
        vence_utc INTEGER NOT NULL,
        tipo_adjunto TEXT NOT NULL CHECK (tipo_adjunto IN ('documento', 'externo')),
        documento_ref TEXT,
        archivo_token TEXT UNIQUE,
        nombre_original TEXT,
        tamano_bytes INTEGER,
        CHECK (remitente_ref != destinatario_ref),
        CHECK (typeof(confirmado_utc) = 'integer' AND typeof(vence_utc) = 'integer'),
        CHECK (vence_utc > confirmado_utc),
        CHECK (
          (tipo_adjunto = 'documento' AND documento_ref IS NOT NULL
           AND length(documento_ref) = 32 AND documento_ref NOT GLOB '*[^0-9a-f]*'
           AND archivo_token IS NULL AND nombre_original IS NULL AND tamano_bytes IS NULL
           AND vence_utc <= confirmado_utc + 604800)
          OR
          (tipo_adjunto = 'externo' AND documento_ref IS NULL AND archivo_token IS NOT NULL
           AND length(archivo_token) = 32 AND archivo_token NOT GLOB '*[^0-9a-f]*'
           AND nombre_original IS NOT NULL AND length(nombre_original) BETWEEN 1 AND 260
           AND typeof(tamano_bytes) = 'integer' AND tamano_bytes BETWEEN 1 AND 20971520
           AND vence_utc = confirmado_utc + 10800)
        )
    )""",
    """CREATE TRIGGER mensajes_participantes_insert BEFORE INSERT ON mensajes
       WHEN NOT EXISTS (
         SELECT 1 FROM conversaciones c WHERE c.id = NEW.conversacion_id AND
         ((c.participante_a = NEW.remitente_ref AND c.participante_b = NEW.destinatario_ref)
          OR (c.participante_b = NEW.remitente_ref AND c.participante_a = NEW.destinatario_ref))
       ) BEGIN SELECT RAISE(ABORT, 'Participantes inconsistentes'); END""",
    """CREATE TRIGGER mensajes_participantes_update
       BEFORE UPDATE OF conversacion_id, remitente_ref, destinatario_ref ON mensajes
       WHEN NOT EXISTS (
         SELECT 1 FROM conversaciones c WHERE c.id = NEW.conversacion_id AND
         ((c.participante_a = NEW.remitente_ref AND c.participante_b = NEW.destinatario_ref)
          OR (c.participante_b = NEW.remitente_ref AND c.participante_a = NEW.destinatario_ref))
       ) BEGIN SELECT RAISE(ABORT, 'Participantes inconsistentes'); END""",
    """CREATE TRIGGER conversaciones_inmutables
       BEFORE UPDATE OF participante_a, participante_b ON conversaciones
       BEGIN SELECT RAISE(ABORT, 'Participantes inmutables'); END""",
    """CREATE TABLE estado_participante (
        conversacion_id TEXT NOT NULL REFERENCES conversaciones(id),
        usuario_ref TEXT NOT NULL,
        archivada INTEGER NOT NULL DEFAULT 0 CHECK (archivada IN (0, 1)),
        ultimo_leido_utc INTEGER,
        PRIMARY KEY (conversacion_id, usuario_ref)
    )""",
    """CREATE TRIGGER estado_participante_insert BEFORE INSERT ON estado_participante
       WHEN NOT EXISTS (
         SELECT 1 FROM conversaciones c WHERE c.id = NEW.conversacion_id
         AND NEW.usuario_ref IN (c.participante_a, c.participante_b)
       ) BEGIN SELECT RAISE(ABORT, 'Participante no autorizado'); END""",
    """CREATE TRIGGER estado_participante_update
       BEFORE UPDATE OF conversacion_id, usuario_ref ON estado_participante
       WHEN NOT EXISTS (
         SELECT 1 FROM conversaciones c WHERE c.id = NEW.conversacion_id
         AND NEW.usuario_ref IN (c.participante_a, c.participante_b)
       ) BEGIN SELECT RAISE(ABORT, 'Participante no autorizado'); END""",
    """CREATE TABLE cuotas (
        usuario_ref TEXT NOT NULL,
        dia_local TEXT NOT NULL,
        envios INTEGER NOT NULL DEFAULT 0 CHECK (envios BETWEEN 0 AND 50),
        PRIMARY KEY (usuario_ref, dia_local)
    )""",
    """CREATE TABLE operaciones (
        usuario_ref TEXT NOT NULL,
        clave TEXT NOT NULL,
        estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'confirmada', 'rechazada')),
        mensaje_id TEXT REFERENCES mensajes(id),
        PRIMARY KEY (usuario_ref, clave),
        CHECK ((estado = 'confirmada' AND mensaje_id IS NOT NULL)
            OR (estado != 'confirmada' AND mensaje_id IS NULL))
    )""",
    """CREATE TABLE limpieza (
        id INTEGER PRIMARY KEY,
        archivo_token TEXT NOT NULL UNIQUE CHECK (
            length(archivo_token) = 32 AND archivo_token NOT GLOB '*[^0-9a-f]*'),
        identidad TEXT,
        estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'completada', 'suspendida')),
        intentos INTEGER NOT NULL DEFAULT 0 CHECK (intentos >= 0),
        ultimo_error TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE eventos (
        id INTEGER PRIMARY KEY,
        mensaje_id TEXT REFERENCES mensajes(id) ON DELETE SET NULL,
        destinatario_ref TEXT NOT NULL,
        tipo TEXT NOT NULL,
        creado_utc INTEGER NOT NULL,
        entregado INTEGER NOT NULL DEFAULT 0 CHECK (entregado IN (0, 1))
    )""",
    "CREATE INDEX idx_mensajes_conversacion ON mensajes(conversacion_id, confirmado_utc, id)",
    "CREATE INDEX idx_mensajes_vencimiento ON mensajes(tipo_adjunto, vence_utc)",
    "CREATE INDEX idx_eventos_destinatario ON eventos(destinatario_ref, entregado, id)",
)

ESTRUCTURA_V2 = (
    """CREATE TABLE vinculo_identidad (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        instalacion_id TEXT NOT NULL CHECK (
            length(instalacion_id) = 32 AND instalacion_id NOT GLOB '*[^0-9a-f]*'),
        generacion_id TEXT NOT NULL CHECK (
            length(generacion_id) = 64 AND generacion_id NOT GLOB '*[^0-9a-f]*')
    )""",
)

ESTRUCTURA_V3 = (
    """CREATE TABLE operaciones (
        usuario_ref TEXT NOT NULL,
        clave TEXT NOT NULL,
        estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'confirmada', 'rechazada')),
        mensaje_id TEXT REFERENCES mensajes(id) ON DELETE SET NULL,
        resultado_id TEXT,
        huella TEXT CHECK (length(huella) = 64 AND huella NOT GLOB '*[^0-9a-f]*'),
        PRIMARY KEY (usuario_ref, clave),
        CHECK ((estado = 'confirmada' AND resultado_id IS NOT NULL
            AND (mensaje_id IS NULL OR mensaje_id = resultado_id))
            OR (estado != 'confirmada' AND mensaje_id IS NULL AND resultado_id IS NULL AND huella IS NULL))
    )""",
    """CREATE TABLE lecturas (
        mensaje_id TEXT PRIMARY KEY NOT NULL REFERENCES mensajes(id) ON DELETE CASCADE,
        leido_utc INTEGER NOT NULL
    )""",
    """CREATE TABLE reloj_motor (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        ultimo_utc INTEGER NOT NULL CHECK (typeof(ultimo_utc) = 'integer'),
        zona TEXT
    )""",
    "CREATE INDEX idx_mensajes_confirmados ON mensajes(confirmado_utc, id)",
)

ESTRUCTURA_V4 = (
    """CREATE TABLE archivos_externos (
        token TEXT PRIMARY KEY NOT NULL CHECK (length(token)=32 AND token NOT GLOB '*[^0-9a-f]*'),
        remitente TEXT NOT NULL,
        destinatario TEXT NOT NULL,
        clave TEXT NOT NULL,
        generacion TEXT NOT NULL,
        limite_utc INTEGER NOT NULL,
        inactivo_utc INTEGER NOT NULL,
        estado TEXT NOT NULL CHECK (estado IN ('recibiendo', 'preparado', 'confirmado', 'retirado')),
        identidad TEXT,
        tamano INTEGER CHECK (tamano BETWEEN 1 AND 20971520),
        huella TEXT,
        mensaje_id TEXT UNIQUE,
        vence_utc INTEGER,
        reintento_utc INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        UNIQUE(remitente, clave),
        CHECK ((estado='recibiendo' AND tamano IS NULL AND huella IS NULL)
            OR (estado='retirado' AND tamano IS NULL AND huella IS NOT NULL AND identidad IS NULL)
            OR (estado IN ('preparado', 'confirmado') AND tamano IS NOT NULL
                AND huella IS NOT NULL AND identidad IS NOT NULL)),
        CHECK ((estado IN ('confirmado', 'retirado') AND mensaje_id IS NOT NULL AND vence_utc IS NOT NULL)
            OR (estado IN ('recibiendo', 'preparado') AND mensaje_id IS NULL AND vence_utc IS NULL))
    )""",
    "CREATE INDEX idx_archivos_limpieza ON archivos_externos(estado, vence_utc, limite_utc, reintento_utc)",
)

ESTRUCTURA_V5 = (
    """CREATE TABLE referencias_biblioteca (
        mensaje_id TEXT PRIMARY KEY NOT NULL REFERENCES mensajes(id) ON DELETE CASCADE,
        modalidad TEXT NOT NULL CHECK (modalidad IN ('visualizar', 'visualizar_y_descargar'))
    )""",
)

ESTRUCTURA_V6 = (
    """CREATE TABLE eventos (
        id INTEGER PRIMARY KEY,
        mensaje_id TEXT REFERENCES mensajes(id) ON DELETE SET NULL,
        destinatario_ref TEXT NOT NULL,
        tipo TEXT NOT NULL,
        creado_utc INTEGER NOT NULL,
        entregado INTEGER NOT NULL DEFAULT 0 CHECK (entregado IN (0, 1)),
        cursor TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(16))))
            CHECK (length(cursor)=32 AND cursor NOT GLOB '*[^0-9a-f]*')
    )""",
    "CREATE INDEX idx_eventos_destinatario ON eventos(destinatario_ref, id)",
    "CREATE INDEX idx_eventos_retencion ON eventos(creado_utc, id)",
    """CREATE TABLE sesiones_ws (
        id TEXT PRIMARY KEY NOT NULL CHECK (length(id)=32 AND id NOT GLOB '*[^0-9a-f]*'),
        usuario_ref TEXT NOT NULL,
        version_sesion INTEGER NOT NULL,
        generacion TEXT NOT NULL,
        emitida_utc INTEGER NOT NULL,
        vence_utc INTEGER NOT NULL CHECK (vence_utc > emitida_utc),
        revocada INTEGER NOT NULL DEFAULT 0 CHECK (revocada IN (0, 1))
    )""",
    "CREATE INDEX idx_sesiones_ws_vence ON sesiones_ws(vence_utc)",
)


def _base_segura(path: Path) -> None:
    try:
        datos = path.lstat()
    except FileNotFoundError:
        return
    if (not stat.S_ISREG(datos.st_mode) or getattr(datos, "st_file_attributes", 0) & 0x400
            or datos.st_nlink != 1):
        raise ValueError("La base de mensajería no es un archivo regular privado")


def _validar_esquema(conexion: sqlite3.Connection, version: int) -> None:
    if conexion.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise ValueError("La base no pertenece a mensajería de SIGED")
    esperados = {}
    sentencias = list(ESTRUCTURA)
    if version >= 2:
        sentencias.extend(ESTRUCTURA_V2)
    if version >= 3:
        sentencias.extend(ESTRUCTURA_V3)
    if version >= 4:
        sentencias.extend(ESTRUCTURA_V4)
    if version >= 5:
        sentencias.extend(ESTRUCTURA_V5)
    if version >= 6:
        sentencias = [sql for sql in sentencias
                      if not sql.startswith(("CREATE TABLE eventos ", "CREATE INDEX idx_eventos_destinatario "))]
        sentencias.extend(ESTRUCTURA_V6)
    for sentencia in sentencias:
        coincidencia = re.match(r"CREATE (TABLE|TRIGGER|INDEX) (\w+)", sentencia)
        if coincidencia:
            esperados[(coincidencia.group(1).lower(), coincidencia.group(2))] = " ".join(
                sentencia.split()
            )
    encontrados = {
        (fila[0], fila[1]): " ".join(fila[2].split())
        for fila in conexion.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        )
    }
    if encontrados != esperados:
        raise ValueError("Definición de esquema de mensajería inesperada")
    if conexion.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ValueError("Base de mensajería corrupta")
    if conexion.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("Referencias internas inconsistentes")
    contexto = conexion.execute(
        "SELECT instalacion_id, generacion_id, estado FROM contexto WHERE id=1"
    ).fetchone()
    if contexto is None or tuple(contexto) != (None, None, "no_verificada"):
        raise ValueError("Contexto de identidad no verificable")


@contextmanager
def _conectar_infraestructura(*, lectura=False):
    """Acceso interno para verificaciones de infraestructura, no autorización."""
    raiz = directorio_configurado()
    if lectura:
        verificar_acl_base_privada(raiz, NOMBRE_BASE, 6)
        for sufijo in ("-journal", "-wal", "-shm"):
            _base_segura(raiz / (NOMBRE_BASE + sufijo))
    else:
        verificar_acl_privada(raiz, 30)
    ruta = raiz / NOMBRE_BASE
    _base_segura(ruta)
    if not ruta.is_file():
        raise FileNotFoundError("La base de mensajería no está inicializada")
    modo, espera = ("ro", 1) if lectura else ("rw", 30)
    with closing(sqlite3.connect(ruta.resolve().as_uri() + "?mode=" + modo, uri=True, timeout=espera)) as db:
        db.row_factory = sqlite3.Row
        db.execute(f"PRAGMA busy_timeout = {espera * 1000}")
        db.execute("PRAGMA foreign_keys = ON")
        try:
            if lectura:
                fin = time.monotonic() + 3
                db.set_progress_handler(lambda: int(time.monotonic() >= fin), 1000)
                db.execute("BEGIN")
            if db.execute("PRAGMA user_version").fetchone()[0] != VERSION:
                raise ValueError("Versión de mensajería desconocida")
            _validar_esquema(db, VERSION)
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


@contextmanager
def conectar():
    """Deniega cualquier uso funcional hasta implementar la verificación de identidad."""
    exigir_identidad_verificada()
    with _conectar_infraestructura() as db:
        yield db


def _migrar(db: sqlite3.Connection) -> None:
    """Publica versión y esquema en una única transacción SQLite."""
    db.execute("BEGIN IMMEDIATE")
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        identificador = db.execute("PRAGMA application_id").fetchone()[0]
        if version == 0:
            if identificador != 0 or db.execute(
                "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone():
                raise ValueError("No se inicializa una base ajena o incompleta")
            for sentencia in ESTRUCTURA:
                db.execute(sentencia)
            db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            version = 1
        if version == 1:
            _validar_esquema(db, 1)
            for sentencia in ESTRUCTURA_V2:
                db.execute(sentencia)
            version = 2
        if version == 2:
            _validar_esquema(db, 2)
            db.execute("ALTER TABLE operaciones RENAME TO operaciones_v2")
            for sentencia in ESTRUCTURA_V3:
                db.execute(sentencia)
            db.execute(
                "INSERT INTO operaciones(usuario_ref, clave, estado, mensaje_id, resultado_id) "
                "SELECT usuario_ref, clave, estado, mensaje_id, mensaje_id FROM operaciones_v2"
            )
            db.execute("DROP TABLE operaciones_v2")
            db.execute(
                "INSERT INTO reloj_motor SELECT 1, MAX(confirmado_utc), NULL FROM mensajes HAVING COUNT(*) > 0"
            )
            version = 3
        if version == 3:
            _validar_esquema(db, 3)
            for sentencia in ESTRUCTURA_V4:
                db.execute(sentencia)
            version = 4
        if version == 4:
            _validar_esquema(db, 4)
            for sentencia in ESTRUCTURA_V5:
                db.execute(sentencia)
            version = 5
        if version == 5:
            _validar_esquema(db, 5)
            db.execute("ALTER TABLE eventos RENAME TO eventos_v5")
            db.execute("DROP INDEX idx_eventos_destinatario")
            for sentencia in ESTRUCTURA_V6:
                db.execute(sentencia)
            db.execute(
                "INSERT INTO eventos(id,mensaje_id,destinatario_ref,tipo,creado_utc,entregado) "
                "SELECT id,mensaje_id,destinatario_ref,tipo,creado_utc,entregado FROM eventos_v5"
            )
            db.execute("DROP TABLE eventos_v5")
            db.execute(f"PRAGMA user_version = {VERSION}")
            version = VERSION
        if version != VERSION:
            raise ValueError("Versión de mensajería desconocida")
        _validar_esquema(db, VERSION)
        db.commit()
    except BaseException:
        db.rollback()
        raise


def inicializar() -> Path:
    """Prepara explícitamente la infraestructura; nunca se llama desde el servidor."""
    with BloqueoDatos(exclusivo=False):
        return _inicializar()


def _inicializar() -> Path:
    raiz = directorio_configurado()
    if not os.path.lexists(raiz):
        with directorio_privado(raiz.parent, nombre=raiz.name, conservar=True):
            pass
    verificar_acl_privada(raiz, 30)
    for nombre in ("temporales", "confirmados"):
        (raiz / nombre).mkdir(exist_ok=True)
    verificar_acl_privada(raiz, 30)
    base = raiz / NOMBRE_BASE
    _base_segura(base)
    with closing(sqlite3.connect(base, timeout=30)) as db:
        db.execute("PRAGMA busy_timeout = 30000")
        db.execute("PRAGMA foreign_keys = ON")
        _migrar(db)
    verificar_acl_privada(raiz, 30)
    return base
