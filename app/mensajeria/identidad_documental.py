"""Identidad local aditiva en la base documental, sin enlaces entre bases."""

import re
import sqlite3

TABLAS = ("usuarios", "documentos")
CREAR_INSTALACION = """CREATE TABLE mensajeria_instalacion (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    referencia TEXT NOT NULL CHECK (
        length(referencia) = 32 AND referencia NOT GLOB '*[^0-9a-f]*')
)"""


def _definiciones():
    yield "mensajeria_instalacion", CREAR_INSTALACION
    for tabla in TABLAS:
        nombre = f"mensajeria_{tabla}"
        asignar = "mensajeria_ref = lower(hex(randomblob(16)))"
        if tabla == "documentos":
            asignar += ", mensajeria_original = NEW.nombre_guardado"
        yield nombre + "_ref", f"CREATE UNIQUE INDEX {nombre}_ref ON {tabla}(mensajeria_ref)"
        yield nombre + "_nueva", f"""CREATE TRIGGER {nombre}_nueva AFTER INSERT ON {tabla}
            BEGIN
                SELECT CASE WHEN NEW.mensajeria_ref IS NOT NULL
                    THEN RAISE(ABORT, 'Identidad asignada por SIGED') END;
                UPDATE {tabla} SET {asignar} WHERE id = NEW.id;
            END"""
        campos = "mensajeria_ref"
        condicion = "OLD.mensajeria_ref IS NOT NEW.mensajeria_ref"
        if tabla == "documentos":
            campos += ", mensajeria_original"
            condicion += " OR OLD.mensajeria_original IS NOT NEW.mensajeria_original"
        yield nombre + "_inmutable", f"""CREATE TRIGGER {nombre}_inmutable
            BEFORE UPDATE OF {campos} ON {tabla}
            WHEN OLD.mensajeria_ref IS NOT NULL AND ({condicion})
            BEGIN SELECT RAISE(ABORT, 'Identidad estable inmutable'); END"""


def _columnas(db: sqlite3.Connection, tabla: str) -> set[str]:
    return {fila[1] for fila in db.execute(f"PRAGMA table_info({tabla})")}


def instalacion(db: sqlite3.Connection) -> str | None:
    """Ausencia completa es legado. Una migración parcial es contradictoria."""
    objetos = dict(db.execute(
        "SELECT name, sql FROM sqlite_master WHERE name GLOB 'mensajeria_*'"
    ))
    columnas = {tabla: _columnas(db, tabla) for tabla in TABLAS}
    esperadas = dict(_definiciones())
    if not objetos and not any(
        cols & {"mensajeria_ref", "mensajeria_original"} for cols in columnas.values()
    ):
        return None
    if (set(objetos) != set(esperadas)
            or any(objetos[k] != sql for k, sql in esperadas.items())
            or not all("mensajeria_ref" in cols for cols in columnas.values())
            or "mensajeria_original" not in columnas["documentos"]):
        raise ValueError("identidad_contradictoria")
    fila = db.execute("SELECT referencia FROM mensajeria_instalacion WHERE id=1").fetchone()
    if fila is None or not isinstance(fila[0], str) or not re.fullmatch("[0-9a-f]{32}", fila[0]):
        raise ValueError("identidad_contradictoria")
    return fila[0]


def preparar(db: sqlite3.Connection) -> None:
    """Provisiona solo la base elegida explícitamente y dentro de una transacción."""
    if instalacion(db) is not None:
        return
    verificar_disparadores_para_recuperacion(db)
    for tabla in TABLAS:
        db.execute(f"ALTER TABLE {tabla} ADD COLUMN mensajeria_ref TEXT")
        db.execute(f"UPDATE {tabla} SET mensajeria_ref = lower(hex(randomblob(16)))")
    db.execute("ALTER TABLE documentos ADD COLUMN mensajeria_original TEXT")
    db.execute("UPDATE documentos SET mensajeria_original = nombre_guardado")
    for _, sentencia in _definiciones():
        db.execute(sentencia)
    db.execute("INSERT INTO mensajeria_instalacion VALUES (1, lower(hex(randomblob(16))))")
    instalacion(db)


def verificar_disparadores_para_recuperacion(db: sqlite3.Connection) -> None:
    """La transformación de la cola solo admite nuestros disparadores ajenos a ella."""
    disparadores = {
        nombre: (tabla, sql) for nombre, tabla, sql in db.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='trigger'"
        )
    }
    if not disparadores:
        return
    esperados = {
        nombre: (nombre.split("_")[1], sql)
        for nombre, sql in _definiciones() if sql.startswith("CREATE TRIGGER ")
    }
    if disparadores != esperados or instalacion(db) is None:
        raise ValueError("Triggers requieren revisión")
