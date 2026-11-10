"""Ubicación privada explícita de la infraestructura de mensajería."""

import os
import stat
from pathlib import Path

from app.configuracion import APP_DIR, BACKUP_DIR, BASE_DIR, DB_PATH, STORAGE_DIR

NOMBRE_DIRECTORIO = ".siged-mensajeria"


def _sin_reanalisis(ruta: Path) -> None:
    for componente in (ruta, *ruta.parents):
        datos = componente.lstat()
        if stat.S_ISLNK(datos.st_mode) or getattr(datos, "st_file_attributes", 0) & 0x400:
            raise ValueError("La ruta de mensajería no admite enlaces ni puntos de reanálisis")


def directorio_configurado() -> Path:
    """Valida la ruta sin crearla; no recurre a directorios predeterminados."""
    valor = os.environ.get("GESTOR_MENSAJERIA_DIR", "").strip()
    if not valor:
        raise ValueError("Configure GESTOR_MENSAJERIA_DIR antes de inicializar mensajería")
    ruta = Path(valor).expanduser()
    if not ruta.is_absolute() or ruta.name != NOMBRE_DIRECTORIO:
        raise ValueError("La ruta debe ser absoluta y terminar en .siged-mensajeria")
    _sin_reanalisis(ruta.parent)
    padre = ruta.parent.resolve(strict=True)
    if not padre.is_dir():
        raise ValueError("El directorio padre de mensajería no existe")
    destino = padre / NOMBRE_DIRECTORIO
    prohibidos = (
        BASE_DIR.resolve(), STORAGE_DIR.resolve(), BACKUP_DIR.resolve(),
        (APP_DIR / "static").resolve(),
    )
    if any(destino == p or p in destino.parents or destino in p.parents for p in prohibidos):
        raise ValueError("La ubicación se superpone con el proyecto o con datos respaldados")
    if DB_PATH.resolve() == destino or destino in DB_PATH.resolve().parents:
        raise ValueError("La ubicación contiene la base documental")
    if os.path.lexists(destino):
        _sin_reanalisis(destino)
        if not destino.is_dir():
            raise ValueError("La ubicación de mensajería no es un directorio")
    return destino
