"""Esquema independiente de mensajería; no habilita operaciones ni rutas."""

import os
import re
import sqlite3
import stat
from contextlib import closing, contextmanager
from pathlib import Path

from app.coordinacion import BloqueoDatos
from app.mensajeria.configuracion import directorio_configurado
from app.mensajeria.identidad import exigir_identidad_verificada
from app.temporal_privado import directorio_privado, verificar_acl_privada

VERSION = 2
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


def _base_segura(path: Path) -> None:
    if os.path.lexists(path):
        datos = path.lstat()
        if (not stat.S_ISREG(datos.st_mode) or getattr(datos, "st_file_attributes", 0) & 0x400
                or datos.st_nlink != 1):
            raise ValueError("La base de mensajería no es un archivo regular privado")


def _validar_esquema(conexion: sqlite3.Connection, version: int) -> None:
    if conexion.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise ValueError("La base no pertenece a mensajería de SIGED")
    esperados = {}
    for sentencia in (*ESTRUCTURA, *(ESTRUCTURA_V2 if version == 2 else ())):
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
def _conectar_infraestructura():
    """Acceso interno para verificaciones de infraestructura, no autorización."""
    raiz = directorio_configurado()
    verificar_acl_privada(raiz, 30)
    ruta = raiz / NOMBRE_BASE
    _base_segura(ruta)
    if not ruta.is_file():
        raise FileNotFoundError("La base de mensajería no está inicializada")
    with closing(sqlite3.connect(ruta.resolve().as_uri() + "?mode=rw", uri=True, timeout=30)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 30000")
        db.execute("PRAGMA foreign_keys = ON")
        try:
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
            db.execute(f"PRAGMA user_version = {VERSION}")
        elif version != VERSION:
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
