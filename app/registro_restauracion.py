"""Registro persistente; debe consultarse manteniendo el bloqueo de datos."""
import json
import os
import tempfile
from pathlib import Path

from app.configuracion import DATA_DIR

REGISTRO = DATA_DIR / ".siged-restauracion.json"
AVISO = ("Restauración pendiente o registro ilegible. Detenga SIGED y conserve "
         "el registro, el directorio de trabajo y los respaldos para recuperación manual.")


def comprobar_estado():
    try:
        try:
            info = REGISTRO.lstat()
        except FileNotFoundError:
            return
        if REGISTRO.is_symlink() or info.st_size > 65536:
            raise ValueError("registro inválido")
        datos = json.loads(REGISTRO.read_text(encoding="utf-8"))
        if not isinstance(datos, dict) or datos.get("version") != 1 or datos.get("estado") != "finalizada":
            raise ValueError("restauración no finalizada")
        if (not isinstance(datos.get("operacion"), str) or not datos["operacion"].startswith("operacion-")
                or Path(datos["operacion"]).name != datos["operacion"]
                or datos.get("directorio") != str(DATA_DIR / ".siged-restauraciones" / datos["operacion"])
                or not isinstance(datos.get("respaldo_previo"), str) or datos.get("paso") != "verificada"):
            raise ValueError("registro incompleto")
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        raise RuntimeError(AVISO) from error


def escribir(datos):
    """Publica un registro completo sin sobrescribirlo parcialmente."""
    descriptor, nombre = tempfile.mkstemp(prefix=".siged-registro-", suffix=".tmp", dir=DATA_DIR)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            json.dump(datos, archivo, ensure_ascii=False)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(nombre, REGISTRO)
        if os.name != "nt":
            directorio = os.open(DATA_DIR, os.O_RDONLY)
            try:
                os.fsync(directorio)
            finally:
                os.close(directorio)
    finally:
        Path(nombre).unlink(missing_ok=True)
