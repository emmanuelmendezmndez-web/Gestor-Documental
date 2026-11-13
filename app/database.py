from contextlib import contextmanager
import sqlite3
import unicodedata

from app.configuracion import DATA_DIR as DATA_DIR, DB_PATH as DB_PATH


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
    # Las escrituras de SQLite se serializan. Esperar un poco más evita fallos
    # transitorios cuando varias peticiones guardan a la vez en el servidor.
    conexion = sqlite3.connect(DB_PATH, timeout=30)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA busy_timeout = 30000")
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
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with conectar() as conexion:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS eliminaciones_pendientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL CHECK(tipo IN ('documento', 'aviso', 'foto')),
                nombre TEXT NOT NULL,
                identidad TEXT,
                estado TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK(estado IN ('pendiente', 'suspendida', 'completada', 'cancelada')),
                intentos INTEGER NOT NULL DEFAULT 0,
                ultimo_error TEXT NOT NULL DEFAULT '',
                creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
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
                version INTEGER NOT NULL DEFAULT 1,
                autor TEXT NOT NULL DEFAULT '',
                fecha_documento TEXT,
                eliminado_en TEXT,
                eliminado_por INTEGER
            )
        """)

        # Migración: si la tabla ya existía sin las columnas nuevas, se agregan.
        columnas_documentos = {
            fila["name"] for fila in conexion.execute("PRAGMA table_info(documentos)")
        }
        columnas_nuevas = {
            "numero_oficio": "TEXT NOT NULL DEFAULT ''",
            "departamento": "TEXT NOT NULL DEFAULT ''",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "autor": "TEXT NOT NULL DEFAULT ''",
            "fecha_documento": "TEXT",
        }
        for nombre, definicion in columnas_nuevas.items():
            if nombre not in columnas_documentos:
                conexion.execute(
                    f"ALTER TABLE documentos ADD COLUMN {nombre} {definicion}"
                )

        columnas_documentos = {
            fila["name"] for fila in conexion.execute("PRAGMA table_info(documentos)")
        }
        for nombre, definicion in {
            "eliminado_en": "TEXT",
            "eliminado_por": "INTEGER",
        }.items():
            if nombre not in columnas_documentos:
                conexion.execute(
                    f"ALTER TABLE documentos ADD COLUMN {nombre} {definicion}"
                )

        conexion.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
                nombre TEXT NOT NULL,
                correo TEXT NOT NULL DEFAULT '',
                telefono TEXT NOT NULL DEFAULT '',
                foto_perfil TEXT,
                password_hash TEXT NOT NULL,
                rol TEXT NOT NULL CHECK (rol IN ('lector', 'editor', 'admin')),
                departamento TEXT NOT NULL DEFAULT '',
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
        if "departamento" not in columnas_usuarios:
            conexion.execute(
                "ALTER TABLE usuarios ADD COLUMN departamento TEXT NOT NULL DEFAULT ''"
            )
        for nombre, definicion in {
            "correo": "TEXT NOT NULL DEFAULT ''",
            "telefono": "TEXT NOT NULL DEFAULT ''",
            "foto_perfil": "TEXT",
        }.items():
            if nombre not in columnas_usuarios:
                conexion.execute(
                    f"ALTER TABLE usuarios ADD COLUMN {nombre} {definicion}"
                )

        conexion.execute("""
            CREATE TABLE IF NOT EXISTS expedientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folio TEXT UNIQUE,
                titulo TEXT NOT NULL,
                descripcion TEXT NOT NULL DEFAULT '',
                fecha_creacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                creado_por INTEGER
            )
        """)

        conexion.execute("""
            CREATE TABLE IF NOT EXISTS expediente_documentos (
                expediente_id INTEGER NOT NULL,
                documento_id INTEGER NOT NULL,
                fecha_vinculacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                vinculado_por INTEGER,
                PRIMARY KEY (expediente_id, documento_id),
                FOREIGN KEY (expediente_id) REFERENCES expedientes(id) ON DELETE CASCADE,
                FOREIGN KEY (documento_id) REFERENCES documentos(id) ON DELETE CASCADE
            )
        """)

        conexion.execute(
            "CREATE INDEX IF NOT EXISTS idx_expediente_documentos_documento "
            "ON expediente_documentos(documento_id)"
        )

        conexion.execute("""
            CREATE TABLE IF NOT EXISTS avisos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                cuerpo TEXT NOT NULL DEFAULT '',
                imagen_guardada TEXT UNIQUE,
                imagen_nombre TEXT,
                departamento TEXT NOT NULL DEFAULT '',
                autor_id INTEGER,
                publicado INTEGER NOT NULL DEFAULT 1,
                fecha_creacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                vence_en INTEGER
            )
        """)

        columnas_avisos = {fila["name"] for fila in conexion.execute("PRAGMA table_info(avisos)")}
        if "vence_en" not in columnas_avisos:
            conexion.execute("ALTER TABLE avisos ADD COLUMN vence_en INTEGER")

        conexion.execute(
            "CREATE INDEX IF NOT EXISTS idx_avisos_publicado_area "
            "ON avisos(publicado, departamento, fecha_creacion)"
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

        conexion.execute("""
            CREATE TABLE IF NOT EXISTS asistente_habitos (
                usuario_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                valor TEXT NOT NULL,
                veces INTEGER NOT NULL DEFAULT 1,
                ultima_vez TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (usuario_id, tipo, valor),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)


if __name__ == "__main__":
    from app.coordinacion import BloqueoDatos
    with BloqueoDatos(exclusivo=False):
        inicializar_db()
        print(f"Base de datos creada en: {DB_PATH}")
