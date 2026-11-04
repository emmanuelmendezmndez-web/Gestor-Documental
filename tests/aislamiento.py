"""Comprobaciones obligatorias antes de ejecutar pruebas que escriben datos."""

import os
import tempfile
from pathlib import Path


def exigir_directorio_temporal(prefijo: str) -> Path:
    """Rechaza configuraciones inseguras antes de importar la aplicación."""
    configurado = os.environ.get("GESTOR_DATA_DIR")
    if not configurado:
        raise RuntimeError("Aislamiento de pruebas: falta GESTOR_DATA_DIR")

    ruta = Path(configurado).expanduser()
    temporal = Path(tempfile.gettempdir()).resolve()
    proyecto = Path(__file__).resolve().parents[1]
    if not ruta.is_absolute() or ruta.is_symlink() or not ruta.is_dir():
        raise RuntimeError(
            "Aislamiento de pruebas: se requiere un directorio absoluto sin enlaces"
        )
    ruta = ruta.resolve()
    if (
        ruta.parent != temporal
        or not ruta.name.startswith(prefijo)
        or len(ruta.name) < len(prefijo) + 6
        or ruta == proyecto
        or proyecto in ruta.parents
        or ruta in proyecto.parents
    ):
        raise RuntimeError("Aislamiento de pruebas: directorio temporal no autorizado")
    if any(ruta.iterdir()):
        raise RuntimeError("Aislamiento de pruebas: el directorio debe estar vacío")
    return ruta
