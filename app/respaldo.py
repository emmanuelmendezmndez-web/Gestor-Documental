"""Respaldo y restauración íntegros del sistema SIGED.

Uso:
  python -m app.respaldo crear [--salida RUTA]
  python -m app.respaldo verificar ARCHIVO.zip
  python -m app.respaldo restaurar ARCHIVO.zip --confirmar

La base se copia con SQLite Connection.backup. Se comprueba que los archivos
referenciados estén en el ZIP y que el tamaño de cada documento coincida. Los
originales que SIGED crea con nombres únicos no se modifican; una eliminación
concurrente de un archivo necesario hace fallar el respaldo. Los archivos extra
de storage no forman una instantánea conjunta con la base. La sustitución externa
de contenido por otro del mismo tamaño antes de leerlo no se puede detectar sin
hashes previos: para una captura integral usa SIGED detenido. La restauración
siempre requiere detener SIGED; una caída durante ella puede requerir recuperar
manualmente el respaldo previo. Los ZIP de formato 1 siguen siendo compatibles
si contienen todos los archivos que su base referencia.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import sys
import tempfile
import unicodedata
import zipfile

from app.configuracion import BACKUP_DIR, DATA_DIR, DB_PATH, SECRET_PATH, STORAGE_DIR
from app.coordinacion import BloqueoDatos
from app.seguridad import obtener_clave_secreta

FORMAT_VERSION = 1
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_SESSION_KEY_BYTES = 64 * 1024
_WINDOWS_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?$", re.IGNORECASE)


def _limite(nombre: str, predeterminado: int) -> int:
    valor = os.environ.get(nombre)
    if valor is None:
        return predeterminado
    try:
        limite = int(valor)
    except ValueError as error:
        raise ValueError(f"{nombre} debe ser un entero positivo.") from error
    if limite <= 0:
        raise ValueError(f"{nombre} debe ser un entero positivo.")
    return limite


def _safe_name(name: str) -> bool:
    if not name or len(name) > 32767 or name.startswith("/") or "\\" in name:
        return False
    parts = name.rstrip("/").split("/")
    if not parts or any(not p or p in {".", ".."} or p[-1] in {" ", "."}
                        or len(p.encode("utf-16-le", errors="surrogatepass")) > 510
                        or any(ord(c) < 32 or c in '<>:"|?*' for c in p)
                        or _WINDOWS_RESERVED.fullmatch(p) for p in parts):
        return False
    return True


def _validar_entradas(infos: list[zipfile.ZipInfo]) -> None:
    max_entradas = _limite("GESTOR_RESPALDO_MAX_ENTRADAS", 100_000)
    max_archivo = _limite("GESTOR_RESPALDO_MAX_ARCHIVO_BYTES", 64 * 1024**3)
    max_total = _limite("GESTOR_RESPALDO_MAX_TOTAL_BYTES", 1024**4)
    if len(infos) > max_entradas:
        raise ValueError("El respaldo supera el límite de entradas.")
    total = 0
    nombres: set[str] = set()
    rutas: dict[str, tuple[str, bool]] = {}
    for info in infos:
        name = info.filename
        if name in nombres:
            raise ValueError("El ZIP contiene nombres duplicados.")
        nombres.add(name)
        if not _safe_name(name):
            raise ValueError("El ZIP contiene una ruta no segura.")
        if not (name in {"manifest.json", "database/gestor.db", "secrets/session_key", "storage/"}
                or (name.startswith("storage/") and not name.endswith("/"))):
            raise ValueError(f"Entrada no permitida en el respaldo: {name}")
        if name == "storage/" and info.file_size:
            raise ValueError("El directorio storage no puede contener datos.")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError("El ZIP contiene un enlace simbólico.")
        if info.file_size > max_archivo:
            raise ValueError("El respaldo supera el límite por archivo.")
        total += info.file_size
        if total > max_total:
            raise ValueError("El respaldo supera el límite de tamaño total.")
        # Comparar también directorios implícitos evita colisiones archivo/directorio.
        partes = name.rstrip("/").split("/")
        for i in range(1, len(partes) + 1):
            original = "/".join(partes[:i])
            clave = unicodedata.normalize("NFC", original).casefold()
            directorio = i < len(partes) or name.endswith("/")
            previo = rutas.get(clave)
            if previo is not None and previo != (original, directorio):
                raise ValueError("El ZIP contiene rutas equivalentes en Windows.")
            rutas[clave] = (original, directorio)


def _sin_claves_duplicadas(pares: list[tuple[str, object]]) -> dict:
    resultado = {}
    for clave, valor in pares:
        if clave in resultado:
            raise ValueError("El manifiesto contiene claves duplicadas.")
        resultado[clave] = valor
    return resultado


def _referencias_archivos(db: Path) -> dict[str, int | None]:
    """Obtiene los archivos exigidos por la copia de SQLite, incluso en papelera."""
    referencias: dict[str, int | None] = {}
    with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as conexion:
        tablas = {fila[0] for fila in conexion.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "documentos" not in tablas:
            raise ValueError("La base del respaldo no contiene la tabla de documentos.")
        for tabla, columna, subcarpeta in (
            ("documentos", "nombre_guardado", ""),
            ("avisos", "imagen_guardada", "avisos/"),
            ("usuarios", "foto_perfil", "perfiles/"),
        ):
            if tabla not in tablas:
                continue
            columnas = {fila[1] for fila in conexion.execute(f"PRAGMA table_info({tabla})")}
            if columna not in columnas:
                if tabla == "documentos":
                    raise ValueError("La base no contiene los nombres de archivo de documentos.")
                continue
            tamano = "tamano_bytes" if tabla == "documentos" and "tamano_bytes" in columnas else "NULL"
            condicion = "" if tabla == "documentos" else f" WHERE {columna} IS NOT NULL AND {columna} != ''"
            for nombre, longitud in conexion.execute(f"SELECT {columna}, {tamano} FROM {tabla}" + condicion):
                if not isinstance(nombre, str) or not nombre or nombre in {".", ".."} or "/" in nombre or "\\" in nombre:
                    raise ValueError(f"Nombre de archivo no seguro en {tabla}.")
                clave = f"storage/{subcarpeta}{nombre}"
                if clave in referencias and referencias[clave] != longitud:
                    raise ValueError(f"Referencias incompatibles al archivo: {clave}")
                referencias[clave] = longitud
    return referencias


def _comprobar_referencias(db: Path, files: dict) -> None:
    for nombre, tamano in _referencias_archivos(db).items():
        metadata = files.get(nombre)
        if not isinstance(metadata, dict):
            raise ValueError(f"Falta en el respaldo el archivo referenciado: {nombre}")
        if tamano is not None and metadata.get("size") != tamano:
            raise ValueError(f"El tamaño del archivo no coincide con la base de datos: {nombre}")


def _agregar_archivo(archive: zipfile.ZipFile, nombre: str, path: Path, kind: str) -> dict:
    """Empaqueta y calcula el hash de los mismos bytes; detecta cambios durante la lectura."""
    digest = hashlib.sha256()
    total = 0
    if path.is_symlink():
        raise ValueError(f"No se respaldan enlaces simbólicos: {path}")
    with path.open("rb") as origen:
        antes = os.fstat(origen.fileno())
        with archive.open(nombre, "w", force_zip64=True) as salida:
            for bloque in iter(lambda: origen.read(1024 * 1024), b""):
                salida.write(bloque)
                digest.update(bloque)
                total += len(bloque)
        despues = os.fstat(origen.fileno())
    actual = path.stat()
    identidad = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if path.is_symlink() or identidad(antes) != identidad(despues) or identidad(despues) != identidad(actual) or total != antes.st_size:
        raise RuntimeError(f"El archivo cambió durante el respaldo: {path}")
    return {"size": total, "sha256": digest.hexdigest(), "kind": kind}


def crear_respaldo(salida: Path | None = None) -> Path:
    """Genera, verifica y publica un ZIP sin reemplazar un archivo existente."""
    with BloqueoDatos(exclusivo=False):
        return _crear_respaldo_con_bloqueo(salida)


def _crear_respaldo_con_bloqueo(salida: Path | None = None) -> Path:
    if not DB_PATH.is_file():
        raise RuntimeError(f"No se encontró la base de datos: {DB_PATH}")
    if not STORAGE_DIR.is_dir():
        raise RuntimeError(f"No se encontró el almacenamiento: {STORAGE_DIR}")
    destino = (salida or BACKUP_DIR / f"siged-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip").expanduser().resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino == STORAGE_DIR or STORAGE_DIR in destino.parents:
        raise ValueError("Guarda el respaldo fuera de la carpeta storage.")
    if destino.exists():
        raise FileExistsError(f"El archivo de salida ya existe: {destino}")

    with tempfile.TemporaryDirectory(prefix="siged-respaldo-") as temporal:
        temporal_dir = Path(temporal)
        db_snapshot = temporal_dir / "gestor.db"
        with closing(sqlite3.connect(DB_PATH, timeout=30)) as origen, closing(sqlite3.connect(db_snapshot)) as copia:
            origen.backup(copia)
            resultado = copia.execute("PRAGMA integrity_check").fetchone()[0]
            if resultado != "ok":
                raise RuntimeError(f"La copia SQLite no pasó integrity_check: {resultado}")

        entries: dict[str, tuple[Path, str]] = {"database/gestor.db": (db_snapshot, "base_de_datos")}
        for path in sorted(STORAGE_DIR.rglob("*")):
            if path.is_symlink():
                raise RuntimeError(f"No se respaldan enlaces simbólicos: {path}")
            if path.is_file():
                rel = path.relative_to(STORAGE_DIR).as_posix()
                entries[f"storage/{rel}"] = (path, "documento_o_archivo")

        key_value = obtener_clave_secreta()
        if len(key_value) < 32:
            raise RuntimeError("La clave de sesión configurada es demasiado corta para respaldarla.")
        key_path = temporal_dir / "session_key"
        key_path.write_text(key_value, encoding="utf-8")
        entries["secrets/session_key"] = (key_path, "clave_de_sesion")
        descriptor, nombre_temporal = tempfile.mkstemp(prefix=".siged-respaldo-", suffix=".tmp", dir=destino.parent)
        os.close(descriptor)
        zip_temporal = Path(nombre_temporal)
        try:
            with zipfile.ZipFile(zip_temporal, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr("storage/", b"")
                files = {}
                for name, (path, kind) in entries.items():
                    files[name] = _agregar_archivo(archive, name, path, kind)
                _comprobar_referencias(db_snapshot, files)
                manifest = {
                    "format": "SIGED-backup", "format_version": FORMAT_VERSION,
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "database": "SQLite online backup API", "secret_key_source": "environment" if os.environ.get("GESTOR_SECRET_KEY") else "file",
                    "files": files,
                }
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
            validar_respaldo(zip_temporal)
            # El enlace solo se crea si el destino aún no existe; nunca sobrescribe un respaldo.
            os.link(zip_temporal, destino)
        finally:
            zip_temporal.unlink(missing_ok=True)
    return destino


def validar_respaldo(archivo: Path, staging: Path | None = None) -> dict:
    """Comprueba hashes, SQLite y las referencias; admite respaldos previos completos."""
    if staging is None:
        with tempfile.TemporaryDirectory(prefix="siged-verificar-") as temporal:
            return validar_respaldo(archivo, Path(temporal))
    staging = Path(staging)
    if staging.is_symlink() or (staging.exists() and (not staging.is_dir() or any(staging.iterdir()))):
        raise ValueError("El directorio de validación debe estar vacío y no ser un enlace.")
    staging.mkdir(parents=True, exist_ok=True)
    try:
        return _validar_en_directorio(archivo, staging)
    except BaseException:
        for item in staging.iterdir():
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
        raise


def _validar_en_directorio(archivo: Path, staging: Path) -> dict:
    archivo = archivo.expanduser().resolve()
    if not archivo.is_file():
        raise FileNotFoundError(archivo)
    with zipfile.ZipFile(archivo) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        _validar_entradas(infos)
        info = archive.getinfo("manifest.json")
        if info.file_size > MAX_MANIFEST_BYTES:
            raise ValueError("El manifiesto es demasiado grande.")
        manifest = json.loads(archive.read(info).decode("utf-8"), object_pairs_hook=_sin_claves_duplicadas)
        if manifest.get("format") != "SIGED-backup" or manifest.get("format_version") != FORMAT_VERSION:
            raise ValueError("Formato o versión de respaldo no compatible.")
        files = manifest.get("files")
        allowed_dirs = {"storage/"} if "storage/" in names else set()
        if not isinstance(files, dict) or set(names) != set(files) | {"manifest.json"} | allowed_dirs:
            raise ValueError("El contenido no coincide con el manifiesto.")
        required = {"database/gestor.db", "secrets/session_key"}
        if not required.issubset(files) or not (any(name.startswith("storage/") for name in files) or "storage/" in names):
            raise ValueError("Faltan la base de datos, la clave o el directorio de archivos.")
        extracted: dict[str, Path] = {}
        if "storage/" in names:
            (staging / "storage").mkdir(parents=True, exist_ok=True)
        total_real = info.file_size
        max_archivo = _limite("GESTOR_RESPALDO_MAX_ARCHIVO_BYTES", 64 * 1024**3)
        max_total = _limite("GESTOR_RESPALDO_MAX_TOTAL_BYTES", 1024**4)
        for name, metadata in files.items():
            member = archive.getinfo(name)
            mode = (member.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError("El ZIP contiene un enlace simbólico.")
            if not isinstance(metadata, dict) or type(metadata.get("size")) is not int or member.file_size != metadata.get("size"):
                raise ValueError(f"Tamaño incorrecto: {name}")
            if name == "secrets/session_key" and member.file_size > MAX_SESSION_KEY_BYTES:
                raise ValueError("La clave de sesión es demasiado grande.")
            target = staging.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            longitud = 0
            with archive.open(member) as source, target.open("wb") as out:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    longitud += len(block)
                    total_real += len(block)
                    if longitud > max_archivo or longitud > member.file_size or total_real > max_total:
                        raise ValueError("La extracción supera el tamaño permitido.")
                    digest.update(block)
                    out.write(block)
            if longitud != member.file_size:
                raise ValueError(f"Tamaño descomprimido incorrecto: {name}")
            if digest.hexdigest() != metadata.get("sha256"):
                raise ValueError(f"La verificación SHA-256 falló: {name}")
            extracted[name] = target
        db = extracted["database/gestor.db"]
        with closing(sqlite3.connect(db)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"La base de datos del respaldo está dañada: {integrity}")
        _comprobar_referencias(db, files)
        key = extracted["secrets/session_key"].read_text(encoding="utf-8").strip()
        if len(key) < 32:
            raise ValueError("La clave de sesión del respaldo está incompleta.")
        return manifest


def restaurar_respaldo(archivo: Path) -> tuple[Path, dict]:
    """Valida todo antes de tocar datos y deja un respaldo previo automático."""
    with BloqueoDatos(exclusivo=True):
        return _restaurar_con_bloqueo(archivo)


def _restaurar_con_bloqueo(archivo: Path) -> tuple[Path, dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="siged-restaurar-", dir=DATA_DIR) as temporal:
        root = Path(temporal)
        manifest = validar_respaldo(archivo, root / "validado")
        validado = root / "validado"
        nuevo_db = validado / "database" / "gestor.db"
        nueva_storage = validado / "storage"
        nueva_clave = validado / "secrets" / "session_key"
        if not nueva_storage.is_dir():
            nueva_storage.mkdir(parents=True)

        # La identidad física cambia al extraer un ZIP. Las tareas anteriores
        # nunca deben ejecutarse sobre un archivo restaurado o un nombre reutilizado.
        with closing(sqlite3.connect(nuevo_db)) as conexion:
            existe_cola = conexion.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='eliminaciones_pendientes'"
            ).fetchone()
            if existe_cola:
                conexion.execute(
                    "UPDATE eliminaciones_pendientes SET estado='suspendida', "
                    "ultimo_error='Tarea suspendida al restaurar; requiere revisión' WHERE estado='pendiente'"
                )
                conexion.commit()

        # Captura el estado actual antes de la restauración para permitir volver atrás.
        previo = _crear_respaldo_con_bloqueo(BACKUP_DIR / f"previo-restauracion-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip")
        swaps: list[tuple[Path, Path | None]] = []
        try:
            for origen, destino in ((nuevo_db, DB_PATH), (nueva_storage, STORAGE_DIR)):
                destino.parent.mkdir(parents=True, exist_ok=True)
                anterior = root / f"anterior-{len(swaps)}"
                if destino.exists():
                    os.replace(destino, anterior)
                    swaps.append((destino, anterior))
                else:
                    swaps.append((destino, None))
                os.replace(origen, destino)
            # Si la clave está definida en el entorno, esa variable sigue teniendo precedencia.
            if not os.environ.get("GESTOR_SECRET_KEY"):
                destino = SECRET_PATH
                anterior = root / "anterior-clave"
                if destino.exists():
                    os.replace(destino, anterior)
                    swaps.append((destino, anterior))
                else:
                    swaps.append((destino, None))
                shutil.copy2(nueva_clave, destino)
            return previo, manifest
        except Exception:
            # Recupera cada destino reemplazado, en orden inverso.
            for destino, anterior in reversed(swaps):
                if destino.is_dir():
                    shutil.rmtree(destino)
                else:
                    destino.unlink(missing_ok=True)
                if anterior is not None and anterior.exists():
                    os.replace(anterior, destino)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Respaldo y restauración de SIGED")
    sub = parser.add_subparsers(dest="accion", required=True)
    crear = sub.add_parser("crear", help="crear un respaldo ZIP")
    crear.add_argument("--salida", type=Path)
    verificar = sub.add_parser("verificar", help="validar integridad y contenido")
    verificar.add_argument("archivo", type=Path)
    restaurar = sub.add_parser("restaurar", help="restaurar con confirmación explícita")
    restaurar.add_argument("archivo", type=Path)
    restaurar.add_argument("--confirmar", action="store_true", help="confirma que la aplicación está detenida y autoriza reemplazar los datos")
    args = parser.parse_args()
    try:
        if args.accion == "crear":
            result = crear_respaldo(args.salida)
            print(f"Respaldo creado: {result}")
            print("Se verificaron la base de datos y los archivos referenciados en el ZIP.")
            print("Para una captura integral de storage, incluidos archivos extra, detén SIGED antes de crear el respaldo.")
            print("Contiene documentos y clave de sesión; guárdalo en un medio protegido. El ZIP no está cifrado.")
        elif args.accion == "verificar":
            manifest = validar_respaldo(args.archivo)
            print(f"Respaldo válido ({len(manifest['files'])} archivos), creado {manifest['created_at_utc']}.")
        else:
            if not args.confirmar:
                parser.error("restaurar requiere --confirmar; primero detén la aplicación y conserva el ZIP en un lugar seguro")
            previo, manifest = restaurar_respaldo(args.archivo)
            print("Restauración completada. Datos anteriores guardados en:", previo)
            if manifest.get("secret_key_source") == "environment":
                print("Aviso: el respaldo usaba GESTOR_SECRET_KEY; restaura también esa variable de entorno para conservar la clave original.")
        return 0
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
