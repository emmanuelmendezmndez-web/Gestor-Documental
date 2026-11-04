"""Cola persistente para retirar archivos desvinculados, con control por SQLite.

``python -m app.eliminaciones`` reintenta hasta 200 tareas pendientes. Las
tareas suspendidas requieren revisión y nunca se reactivan automáticamente.
La coordinación protege escrituras de SIGED que usan esta base; procesos externos
con acceso directo al sistema de archivos no participan en el bloqueo SQLite.
"""

import json
import logging
from pathlib import Path, PureWindowsPath
import sqlite3
import stat

from app.configuracion import AVISOS_DIR, DATA_DIR, FOTOS_PERFIL_DIR, STORAGE_DIR
from app.database import conectar

logger = logging.getLogger("gestor")
DIRECTORIOS = {"documento": STORAGE_DIR, "aviso": AVISOS_DIR, "foto": FOTOS_PERFIL_DIR}
REFERENCIAS = {
    "documento": ("documentos", "nombre_guardado"),
    "aviso": ("avisos", "imagen_guardada"),
    "foto": ("usuarios", "foto_perfil"),
}


def _ruta(tipo: str, nombre: str) -> Path:
    if (tipo not in DIRECTORIOS or not isinstance(nombre, str) or not nombre
            or nombre in {".", ".."} or nombre.endswith((".", " ")) or "/" in nombre or "\\" in nombre or ":" in nombre
            or PureWindowsPath(nombre).name != nombre):
        raise ValueError("Nombre o tipo de archivo no autorizado")
    directorio = DIRECTORIOS[tipo]
    # No seguir enlaces ni directorios sustituidos fuera del almacenamiento.
    raiz = DATA_DIR.resolve() / "storage"
    if (STORAGE_DIR.resolve() != raiz or directorio.is_symlink()
            or directorio.resolve() != (raiz if tipo == "documento" else raiz / ("avisos" if tipo == "aviso" else "perfiles"))):
        raise ValueError("Directorio de almacenamiento no autorizado")
    return directorio / nombre


def _identidad(ruta: Path) -> str:
    try:
        datos = ruta.lstat()
    except FileNotFoundError:
        return "ausente"
    if not stat.S_ISREG(datos.st_mode) or not datos.st_ino:
        raise ValueError("El archivo no es regular o no tiene identidad verificable")
    return json.dumps([datos.st_dev, datos.st_ino, datos.st_size, datos.st_mtime_ns, datos.st_ctime_ns])


def _referenciado(conexion: sqlite3.Connection, tipo: str, nombre: str) -> bool:
    # Nombres inesperados pueden cruzar directorios; ante esa ambigüedad no se borra.
    for tabla, columna in REFERENCIAS.values():
        sospechoso = conexion.execute(
            f"SELECT 1 FROM {tabla} WHERE instr({columna}, '/') > 0 "
            f"OR instr({columna}, char(92)) > 0 OR instr({columna}, ':') > 0 "
            f"OR rtrim({columna}, ' .') != {columna} LIMIT 1"
        ).fetchone()
        if sospechoso:
            raise ValueError("Hay referencias con rutas no verificables; requiere revisión")
    tabla, columna = REFERENCIAS[tipo]
    # SQLite NOCASE no cubre todos los caracteres de Windows.
    return any(isinstance(fila[0], str) and fila[0].casefold() == nombre.casefold()
               for fila in conexion.execute(f"SELECT {columna} FROM {tabla} WHERE {columna} IS NOT NULL"))


def encolar(conexion: sqlite3.Connection, tipo: str, nombre: str) -> int:
    """Debe llamarse dentro de la transacción que retira la referencia."""
    estado, error, identidad = "pendiente", "", None
    try:
        identidad = _identidad(_ruta(tipo, nombre))
    except (OSError, ValueError) as exc:
        estado, error = "suspendida", str(exc)[:500]
    return conexion.execute(
        "INSERT INTO eliminaciones_pendientes(tipo,nombre,identidad,estado,ultimo_error) VALUES(?,?,?,?,?)",
        (tipo, nombre, identidad, estado, error),
    ).lastrowid


def procesar_tarea(identificador: int) -> str:
    """Revalida referencia e identidad bajo bloqueo de escritura entre procesos."""
    with conectar() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        tarea = conexion.execute("SELECT * FROM eliminaciones_pendientes WHERE id=?", (identificador,)).fetchone()
        if tarea is None:
            return "inexistente"
        if tarea["estado"] != "pendiente":
            return tarea["estado"]
        try:
            ruta = _ruta(tarea["tipo"], tarea["nombre"])
            if _referenciado(conexion, tarea["tipo"], tarea["nombre"]):
                estado, error = "cancelada", "El archivo sigue referenciado"
            else:
                actual = _identidad(ruta)
                if actual == "ausente":
                    estado, error = "completada", ""
                elif actual != tarea["identidad"]:
                    estado, error = "suspendida", "La identidad del archivo cambió; requiere revisión"
                else:
                    ruta.unlink()
                    estado, error = "completada", ""
        except FileNotFoundError:
            estado, error = "completada", ""
        except OSError as exc:
            estado, error = "pendiente", str(exc)[:500]
        except (ValueError, KeyError) as exc:
            estado, error = "suspendida", str(exc)[:500]
        conexion.execute("UPDATE eliminaciones_pendientes SET estado=?, intentos=intentos+1, ultimo_error=? WHERE id=?",
                         (estado, error, identificador))
        # Las tareas históricas pueden no tener actividad asociada. Para las
        # nuevas, conservar el resultado físico en la misma transacción que el
        # estado de la cola; una caída tras unlink deja la tarea reintentable.
        if estado != "pendiente":
            actividad = conexion.execute(
                "SELECT usuario_id, usuario, accion, entidad, entidad_id, entidad_nombre, ip "
                "FROM actividad WHERE detalle LIKE ? AND accion IN "
                "('eliminar_definitivo','aviso_eliminar','usuario_eliminar','cuenta_perfil') "
                "ORDER BY id DESC LIMIT 1", (f"%; tarea {identificador}",),
            ).fetchone()
            if actividad is not None:
                conexion.execute(
                    "INSERT INTO actividad(usuario_id,usuario,accion,resultado,entidad,entidad_id,entidad_nombre,detalle,ip) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (actividad["usuario_id"], actividad["usuario"], actividad["accion"],
                     "exito" if estado in {"completada", "cancelada"} else "fallo",
                     actividad["entidad"], actividad["entidad_id"], actividad["entidad_nombre"],
                     f"limpieza física {estado}; tarea {identificador}", actividad["ip"]),
                )
        return estado


def procesar_tareas(ids: list[int]) -> dict[int, str]:
    resultados = {}
    for identificador in ids:
        try:
            resultados[identificador] = procesar_tarea(identificador)
        except Exception:
            logger.exception("No se pudo procesar la tarea de limpieza %s", identificador)
            resultados[identificador] = "pendiente"
    return resultados


def descartar_generado(tipo: str, nombre: str) -> None:
    """Programa la limpieza de un archivo creado por una operación fallida."""
    try:
        with conectar() as conexion:
            conexion.execute("BEGIN IMMEDIATE")
            tarea = encolar(conexion, tipo, nombre)
        procesar_tareas([tarea])
    except Exception:
        # Si SQLite no está disponible, conservar el archivo es más seguro.
        logger.exception("No se pudo programar la limpieza de un archivo generado")


def reintentar_pendientes(limite: int = 200) -> dict[int, str]:
    with conectar() as conexion:
        ids = [fila["id"] for fila in conexion.execute(
            "SELECT id FROM eliminaciones_pendientes WHERE estado='pendiente' ORDER BY intentos, id LIMIT ?", (limite,)
        )]
    return procesar_tareas(ids)


if __name__ == "__main__":
    resultados = reintentar_pendientes()
    with conectar() as conexion:
        totales = {fila["estado"]: fila["cantidad"] for fila in conexion.execute(
            "SELECT estado, COUNT(*) AS cantidad FROM eliminaciones_pendientes GROUP BY estado"
        )}
    print(f"Tareas procesadas: {len(resultados)}; pendientes: {totales.get('pendiente', 0)}; "
          f"suspendidas para revisión: {totales.get('suspendida', 0)}")
