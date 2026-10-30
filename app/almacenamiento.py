"""Consulta de la capacidad de la unidad que almacena documentos."""

import logging
import shutil
from pathlib import Path

from app.utilidades import formatear_espacio_disco

logger = logging.getLogger("gestor")


def consultar_uso_disco(directorio: Path) -> dict:
    """Devuelve las capacidades de la unidad o indica que no están disponibles."""
    try:
        uso = shutil.disk_usage(directorio)
    except OSError:
        logger.exception("No se pudo consultar la capacidad de almacenamiento de SIGED")
        return {"disponible": False}

    porcentaje = round((uso.used / uso.total) * 100) if uso.total else 0
    porcentaje = min(100, max(0, porcentaje))
    return {
        "disponible": True,
        "ocupado": formatear_espacio_disco(uso.used),
        "total": formatear_espacio_disco(uso.total),
        "libre": formatear_espacio_disco(uso.free),
        "porcentaje": porcentaje,
    }
