from contextlib import contextmanager
from pathlib import Path
import sqlite3
import unicodedata

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "gestor.db"


def normalizar_texto(texto) -> str:
    """Pasa a minúsculas y quita acentos: 'Tesorería' -> 'tesoreria'."""
    if texto is None:
        return ""
    descompuesto = unicodedata.normalize("NFD", str(texto))
    sin_acentos = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return sin_acentos.casefold()


@contextmanager
def conectar():
    """Abre la conexión, confirma los cambios al terminar y siempre la cierra."""
    conexion = sqlite3.connect(DB_PATH)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    # Permite usar normalizar(columna) dentro de las consultas SQL
    conexion.create_function("normalizar", 1, normalizar_texto, deterministic=True)
    try:
        yield conexion
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


def inicializar_db():
    with conectar() as conexion:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS documentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                nombre_archivo TEXT NOT NULL,
                nombre_guardado TEXT NOT NULL UNIQUE,
                categoria TEXT NOT NULL,
                descripcion TEXT NOT NULL DEFAULT '',
                fecha_subida TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                tamano_bytes INTEGER NOT NULL,
                numero_oficio TEXT NOT NULL DEFAULT '',
                departamento TEXT NOT NULL DEFAULT '',
                autor TEXT NOT NULL DEFAULT '',
                fecha_documento TEXT
            )
        """)

        # Migración: si la tabla ya existía sin las columnas nuevas, se agregan.
        columnas_documentos = {
            fila["name"] for fila in conexion.execute("PRAGMA table_info(documentos)")
        }
        columnas_nuevas = {
            "numero_oficio": "TEXT NOT NULL DEFAULT ''",
            "departamento": "TEXT NOT NULL DEFAULT ''",
            "autor": "TEXT NOT NULL DEFAULT ''",
            "fecha_documento": "TEXT",
        }
        for nombre, definicion in columnas_nuevas.items():
            if nombre not in columnas_documentos:
                conexion.execute(
                    f"ALTER TABLE documentos ADD COLUMN {nombre} {definicion}"
                )

        conexion.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
                nombre TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                rol TEXT NOT NULL CHECK (rol IN ('lector', 'editor', 'admin')),
                activo INTEGER NOT NULL DEFAULT 1,
                fecha_creacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                version_sesion INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Migración: si la tabla ya existía sin la columna nueva, se agrega.
        columnas_usuarios = {
            fila["name"] for fila in conexion.execute("PRAGMA table_info(usuarios)")
        }
        if "version_sesion" not in columnas_usuarios:
            conexion.execute(
                "ALTER TABLE usuarios ADD COLUMN version_sesion INTEGER NOT NULL DEFAULT 0"
            )

        # Registro de actividad. Se guarda el nombre del usuario y del elemento tal
        # como estaban en ese momento, sin llaves foráneas, para que el historial
        # siga siendo legible aunque después se elimine un documento.
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS actividad (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                usuario_id INTEGER,
                usuario TEXT,
                accion TEXT NOT NULL,
                resultado TEXT NOT NULL CHECK (resultado IN ('exito', 'fallo', 'denegado')),
                entidad TEXT,
                entidad_id INTEGER,
                entidad_nombre TEXT,
                detalle TEXT NOT NULL DEFAULT '',
                ip TEXT
            )
        """)


if __name__ == "__main__":
    inicializar_db()
    print(f"Base de datos creada en: {DB_PATH}")