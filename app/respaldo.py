"""Respaldo y restauración íntegros del sistema SIGED.

Uso:
  python -m app.respaldo crear [--salida RUTA]
  python -m app.respaldo verificar ARCHIVO.zip
  python -m app.respaldo restaurar ARCHIVO.zip --confirmar

Detén la aplicación antes de crear un respaldo completo y antes de restaurar.
La base de datos se copia con la API SQLite Connection.backup.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys
import tempfile
import zipfile

from app.configuracion import BACKUP_DIR, DATA_DIR, DB_PATH, SECRET_PATH, STORAGE_DIR
from app.seguridad import obtener_clave_secreta

FORMAT_VERSION = 1
MAX_MANIFEST_BYTES = 16 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (bool(name) and not path.is_absolute() and ".." not in path.parts
            and "\\" not in name and not name.startswith("/"))


def crear_respaldo(salida: Path | None = None) -> Path:
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
        with sqlite3.connect(DB_PATH, timeout=30) as origen, sqlite3.connect(db_snapshot) as copia:
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
        manifest = {
            "format": "SIGED-backup", "format_version": FORMAT_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "database": "SQLite online backup API", "secret_key_source": "environment" if os.environ.get("GESTOR_SECRET_KEY") else "file",
            "files": {name: {"size": path.stat().st_size, "sha256": _sha256(path), "kind": kind}
                      for name, (path, kind) in entries.items()},
        }
        try:
            with zipfile.ZipFile(destino, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
                archive.writestr("storage/", b"")
                for name, (path, _) in entries.items():
                    archive.write(path, name)
        except Exception:
            destino.unlink(missing_ok=True)
            raise
    return destino


def validar_respaldo(archivo: Path, staging: Path | None = None) -> dict:
    archivo = archivo.expanduser().resolve()
    if not archivo.is_file():
        raise FileNotFoundError(archivo)
    with zipfile.ZipFile(archivo) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)):
            raise ValueError("El ZIP contiene nombres duplicados.")
        if any(not _safe_name(name) for name in names):
            raise ValueError("El ZIP contiene una ruta no segura.")
        info = archive.getinfo("manifest.json")
        if info.file_size > MAX_MANIFEST_BYTES:
            raise ValueError("El manifiesto es demasiado grande.")
        manifest = json.loads(archive.read(info).decode("utf-8"))
        if manifest.get("format") != "SIGED-backup" or manifest.get("format_version") != FORMAT_VERSION:
            raise ValueError("Formato o versión de respaldo no compatible.")
        files = manifest.get("files")
        allowed_dirs = {"storage/"} if "storage/" in names else set()
        if not isinstance(files, dict) or set(names) != set(files) | {"manifest.json"} | allowed_dirs:
            raise ValueError("El contenido no coincide con el manifiesto.")
        required = {"database/gestor.db", "secrets/session_key"}
        if not required.issubset(files) or not (any(name.startswith("storage/") for name in files) or "storage/" in names):
            raise ValueError("Faltan la base de datos, la clave o el directorio de archivos.")
        if staging is None:
            with tempfile.TemporaryDirectory(prefix="siged-verificar-") as temporal:
                return validar_respaldo(archivo, Path(temporal))
        extracted: dict[str, Path] = {}
        if "storage/" in names:
            (staging / "storage").mkdir(parents=True, exist_ok=True)
        for name, metadata in files.items():
            member = archive.getinfo(name)
            mode = (member.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError("El ZIP contiene un enlace simbólico.")
            if member.file_size != metadata.get("size"):
                raise ValueError(f"Tamaño incorrecto: {name}")
            target = staging.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with archive.open(member) as source, target.open("wb") as out:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
                    out.write(block)
            if digest.hexdigest() != metadata.get("sha256"):
                raise ValueError(f"La verificación SHA-256 falló: {name}")
            extracted[name] = target
        db = extracted["database/gestor.db"]
        with sqlite3.connect(db) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"La base de datos del respaldo está dañada: {integrity}")
        key = extracted["secrets/session_key"].read_text(encoding="utf-8").strip()
        if len(key) < 32:
            raise ValueError("La clave de sesión del respaldo está incompleta.")
        return manifest


def restaurar_respaldo(archivo: Path) -> tuple[Path, dict]:
    """Valida todo antes de tocar datos y deja un respaldo previo automático."""
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

        # Captura el estado actual antes de la restauración para permitir volver atrás.
        previo = crear_respaldo(BACKUP_DIR / f"previo-restauracion-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip")
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
            print("Para consistencia entre la base y los archivos, ejecuta el respaldo con SIGED detenido.")
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
