"""Guardado de archivos recibidos por los formularios."""

from pathlib import Path

from fastapi import UploadFile

TAMANO_MAXIMO = 20 * 1024 * 1024  # 20 MB
TAMANO_BLOQUE = 1024 * 1024  # se lee de 1 MB en 1 MB


class ArchivoInvalido(Exception):
    def __init__(self, codigo: str):
        self.codigo = codigo


def guardar_en_disco(archivo: UploadFile, destino: Path) -> int:
    """Copia el archivo por bloques y valida el tamaño real."""
    tamano = 0
    with destino.open("wb") as salida:
        while bloque := archivo.file.read(TAMANO_BLOQUE):
            tamano += len(bloque)
            if tamano > TAMANO_MAXIMO:
                raise ArchivoInvalido("grande")
            salida.write(bloque)
    if tamano == 0:
        raise ArchivoInvalido("vacio")
    return tamano
